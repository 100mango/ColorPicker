"""Portable adversarial receipt fixtures. These do not represent native runs."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import watch_crown_result as result
from watch_crown_setup_events import SCHEMA, PROTOCOL

WATCH = '11111111-1111-4111-8111-111111111111'
PHONE = '22222222-2222-4222-8222-222222222222'
PAIR = '33333333-3333-4333-8333-333333333333'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0'
TYPE = 'com.apple.CoreSimulator.SimDeviceType.Apple-Watch-SE-40mm'


def retain(root, report, name, value, kind, case=None):
    raw = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    (root/name).write_bytes(raw)
    entry = {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'kind': kind, 'case': case}
    report['evidence'].append(entry)
    return entry


def stage(command, phase, start, duration=1, timeout=5, raw=None, exit=0):
    record = dict(command=command, phase=phase, started=True, exit=exit, raw_exit=exit, timed_out=False,
                  process_group_gone=True, capture_reader_finished=True, stdout_truncated=False, reader_errors=[],
                  started_epoch=1000+start, finished_epoch=1000+start+duration,
                  started_monotonic=100+start, finished_monotonic=100+start+duration, timeout_seconds=timeout)
    if raw is not None: record.update(stdout_sha256=raw['sha256'], stdout_bytes=raw['bytes'])
    return record


def setup_fixture(root, report):
    # New schema has real synthetic setup receipts, not a placeholder command.
    roles={row['role']:row for row in report['owned_devices']}
    report['owned_devices']=[roles['phone'],roles['watch']]
    source=report['source'];phone,watch=report['owned_devices'];pair=report['pair']['id']
    report['initial_inventory']['devices'].setdefault(phone['runtime'],[{
        'udid':'original-phone','name':'iPhone template','isAvailable':True,
        'deviceTypeIdentifier':phone['deviceTypeIdentifier']}])
    commands=[['xcrun','simctl','list','devices','available','-j'],['xcrun','simctl','list','pairs','-j']]
    for device in (phone,watch):
        commands.append(['xcrun','simctl','create','TouchColor-Crown-'+device['role']+'-aabbccdd',device['deviceTypeIdentifier'],device['runtime']])
    commands.extend([['xcrun','simctl','pair',watch['udid'],phone['udid']],
        ['xcrun','simctl','list','pairs','-j'],['xcrun','simctl','list','pairs','-j']])
    for device in (phone,watch):
        commands.extend([['xcrun','simctl','boot',device['udid']],['xcrun','simctl','bootstatus',device['udid'],'-b']])
    events=[];caps={'list':30,'create':60,'pair':60,'boot':180,'bootstatus':420}
    for i,command in enumerate(commands):
        start=41+i*.25;cap=caps[command[2]];entry=stage(command,'setup',start,.1,cap)
        entry.update(source_sha=source['sha'],budget_phase='work',setup_command_cap_seconds=cap,
                     deadline_monotonic=100+start+cap)
        if i in (2,3,4):
            raw=((phone['udid'],watch['udid'],pair)[i-2]+'\n').encode()
            entry.update(stdout_bytes=len(raw),stdout_sha256=hashlib.sha256(raw).hexdigest())
        if command[2]=='bootstatus':
            device=phone if command[3]==phone['udid'] else watch
            name='setup-'+device['role']+'-bootstatus.log'
            raw=retain(root,report,name,'synthetic boot progress completed\n','setup_bootstatus',device['role'])
            entry.update(stdout_bytes=raw['bytes'],stdout_sha256=raw['sha256'])
            events.append({**device,'source_sha':source['sha'],'run_id':source['run_id'],'attempt':source['attempt'],
                'boot_stage_index':len(report['stages'])-1,'bootstatus_stage_index':len(report['stages']),
                'bootstatus_file':name,'completed_epoch':entry['finished_epoch'],'completed_monotonic':entry['finished_monotonic']})
        report['stages'].append(entry)
    report['setup_proof']={'kind':PROTOCOL,'inventory':'not_requested','simultaneous_state':'unobserved',
        'connectivity':'unobserved','continued_readiness':'unobserved','events':events}


def fixture(root, statuses=('passed', 'passed', 'passed')):
    source = dict(sha='a'*40, tree='b'*40, workflow_sha256='c'*64, ref='refs/heads/codex/watch-crown-diagnostic',
                  repository='100mango/ColorPicker', run_id='12345', attempt='1')
    snapshot = {k: source[k] for k in ('sha', 'tree', 'workflow_sha256')}
    device = dict(udid=WATCH, runtime=RUNTIME, profile='smallest', millimeters=40, deviceTypeIdentifier=TYPE,
                  text_phase='normal', owned=True)
    pair_record = {'state': '(active, connected)', 'watch': {'udid': WATCH}, 'phone': {'udid': PHONE}}
    products = {name: {'sha256': c*64, 'files': 10, 'bytes': 100} for name,c in [('actual_cold','d'),('isolated_static','e')]}
    report = dict(schema=SCHEMA, protocol=PROTOCOL, source=source, source_before=copy.deepcopy(snapshot), source_after=copy.deepcopy(snapshot),
        source_verified=True, run_id='12345', attempt='1', acceptance=False,
        toolchain={'xcode': 'Xcode 27.0\nBuild version 27A266a', 'macos': '26A428', 'architecture': 'arm64'},
        device=device, owned_devices=[{'role':'watch', **{k:device[k] for k in ('udid','runtime','deviceTypeIdentifier')}},
            {'role':'phone','udid':PHONE,'runtime':'com.apple.CoreSimulator.SimRuntime.iOS-27-0',
             'deviceTypeIdentifier':'com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation'}],
        pair={'id':PAIR,'record':pair_record,'activation':{'activation_requested':False,'record':copy.deepcopy(pair_record)}},
        products_before=products, products_after=copy.deepcopy(products),
        initial_inventory={'devices':{RUNTIME:[{'udid':'original-watch','name':'Apple Watch SE (40mm)',
            'isAvailable':True,'deviceTypeIdentifier':TYPE}]}, 'pairs':{'pairs':{}}},
        budget={'schema':1,'platform':'watch-crown-control','lane':'watch-crown-control-smallest','minutes':25,
                'sha':source['sha'],'run_id':'12345','reserves':copy.deepcopy(result.RESERVES),'startup_margin':30,
                'started_epoch':1000,'started_monotonic':100,'cleanup_unconfirmed':False},
        work_finished_monotonic=218, work_elapsed_from_original_seconds=118,
        phases=[], stages=[], cases=[], evidence=[], errors=[], cleanup={'confirmed':True,
            'device_absence_verified':True,'pair_absence_verified':True,'owned_device_ids':[WATCH,PHONE],'pair_id':PAIR})
    limits = result.PHASE_LIMITS | {'cleanup':130, 'evidence':180}
    for i,(name,limit) in enumerate(limits.items()):
        report['phases'].append(dict(name=name,limit_seconds=limit,started_epoch=1000+i*20,finished_epoch=1018+i*20,
            started_monotonic=100+i*20,finished_monotonic=118+i*20,completed=True))
    for i, name in enumerate(('preflight','builds')):
        report['stages'].append(stage(['fixture',name],name,i*20+1))
    setup_fixture(root, report)
    for i,(name,status) in enumerate(zip(result.CASE_NAMES,statuses)):
        case = result.CASES[name]; base=(i+3)*20+1
        row = {key:case[key] for key in ('identifier','project','scheme','result_bundle')}
        row.update(name=name,stage_index=len(report['stages']),cleanup_confirmed=True)
        report['stages'].append(stage(result.expected_command(name,WATCH),name,base,5,180,exit=0 if status=='passed' else 65))
        target,cls,method = case['identifier'].split('/')
        counts=dict(passedTests=int(status=='passed'),failedTests=int(status=='failed'),skippedTests=0,expectedFailures=0)
        failure={'targetName':target,'testIdentifierString':cls+'/'+method+'()',
            'testIdentifierURL':'test://com.apple.xcode/'+case['scheme']+'/'+case['identifier'],'failureText':'XCTAssertTrue failed: original Privacy assertion'}
        summary={**counts,'totalTestCount':1,'result':status.title(),'startTime':1000+base+1,'finishTime':1000+base+4,
            'testFailures':[failure] if status=='failed' else [],'devicesAndConfigurations':[{**counts,
                'device':{'deviceId':WATCH,'platform':'watchOS Simulator','osVersion':'27.0','architecture':'arm64'},
                'testPlanConfiguration':{'configurationId':'1','configurationName':'Test Scheme Action'}}]}
        row['summary_file']=name+'-summary.json'
        raw=retain(root,report,row['summary_file'],summary,'summary',name)
        row['summary_stage_index']=len(report['stages'])
        report['stages'].append(stage(['xcrun','xcresulttool','get','test-results','summary','--path',case['result_bundle']],name,base+6,raw=raw))
        prefix="Test Case '-["+target+'.'+cls+' '+method+"]' "
        row['lifecycle_file']=name+'-lifecycle.log'
        retain(root,report,row['lifecycle_file'],prefix+'started.\n'+prefix+status+' (2.000 seconds).\n','lifecycle',name)
        row['diagnostics_file']=name+'-console.log'
        retain(root,report,row['diagnostics_file'],'Original diagnostic output\n','diagnostics',name)
        cleanupfile=name+'-cleanup-services.log'
        raw=retain(root,report,cleanupfile,'PID\tStatus\tLabel\n','case_cleanup',name)
        identities=['com.mango.touchColor.watchCrownControl','com.mango.touchColor.watchCrownControl.uitests.xctrunner'] if name=='isolated_static' else ['com.mango.touchColor.watchkitapp','com.mango.touchColor.TouchColorWatchUITests.xctrunner']
        row['process_cleanup']=dict(confirmed=True,identifiers=identities,inventory_stage_index=len(report['stages']),
                                    inventory_file=cleanupfile,inventory_sha256=raw['sha256'],entries=0)
        report['stages'].append(stage(['xcrun','simctl','spawn',WATCH,'launchctl','list'],name,base+8,raw=raw))
        report['cases'].append(row)
    for filename,kind,key in [('cleanup-devices.json','cleanup_devices','device_inventory_sha256'),('cleanup-pairs.json','cleanup_pairs','pair_inventory_sha256')]:
        noun = 'devices' if kind == 'cleanup_devices' else 'pairs'
        raw=retain(root,report,filename,{noun:{}},kind);report['cleanup'][key]=raw['sha256']
        report['cleanup']['device_stage_index' if noun == 'devices' else 'pair_stage_index']=len(report['stages'])
        report['stages'].append(stage(['xcrun','simctl','list',noun,'-j'],'cleanup',121 if noun == 'devices' else 123,raw=raw))
    for i,row in enumerate(report['cases']):
        name=row['name'];target,cls,method=row['identifier'].split('/')
        tree={'testNodes':[{'nodeType':'Test Plan','name':row['scheme'],'children':[{'nodeType':'UI test bundle','name':target,
            'children':[{'nodeType':'Test Suite','name':cls,'children':[{'nodeType':'Test Case','nodeIdentifier':cls+'/'+method+'()',
                'name':method+'()','result':statuses[i].title()}]}]}]}]}
        row['tests_file']=name+'-tests.json';raw=retain(root,report,row['tests_file'],tree,'tests',name)
        row['tests_stage_index']=len(report['stages'])
        report['stages'].append(stage(['xcrun','xcresulttool','get','test-results','tests','--path',row['result_bundle']],
                                      'evidence',141+i*2,raw=raw))
    cold_records=[{'case':'-[WatchWorkflowTests testHomeListDigitalCrownFromColdLaunch]',
        'phase':'cold.0.'+side,'viewport':[0,0,200,200],'rows':[{'id':'watch.editor','frame':[0,0,100,40]}],
        'snapshotMilliseconds':1} for side in ('before','after')]
    retain(root,report,'cold-list-frames.json',dict(records=cold_records,matched_records=2,omitted_records=0,invalid_records=0),'cold_frames','actual_cold')
    cold_id='__WatchWorkflowTests_testHomeListDigitalCrownFromColdLaunch_'
    home=dict(schema=1,case=cold_id,counter_order=['appear','disappear','palette','transfer'],terminal_snapshot=False,
        counts_are_lower_bounds=True,truncated=False,matched_records=1,omitted_records=0,invalid_records=0,foreign_records=0,
        records=[dict(case=cold_id,pid=42,uptimeMilliseconds=1,log_timestamp='2026-10-05 04:00:00.000 Df',event='appear',
                      counts=[1,0,0,0],omitted=[0,0,0,0],saturated=False,terminal=False)])
    retain(root,report,'home-observations.json',home,'observation_home','actual_cold')
    static_case='WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations'
    frames=[]
    for i in range(6):
        frames.append(dict(case=static_case,phase='crown.'+str(i//2)+('.before' if i%2==0 else '.after'),runnerPID=43,uptime=i+1,
            geometryComplete=True,listCount=1,navigationCount=1,listIdentifier='static.list',navigationIdentifier='Crown Control',
            viewport=[0,0,200,200],list=[0,0,200,200],navigation=[0,0,200,40],backButtons=0,omittedIdentityCharacters=0,
            omittedSubtreeRoots=0,duplicateRows=0,invalidRows=0,omittedRows=0,omittedDescendantsUnknown=False,nodesVisited=10,
            rows=[{'id':0,'frame':[0,40,200,40]}]))
    payloads=[json.dumps(frame,separators=(',',':')) for frame in frames]
    frame_bytes=sum(len(p.encode()) for p in payloads)
    summary=dict(case=static_case,crownCalls=3,delta=-0.1,crownSnapshots=6,touchSnapshots=0,touchCalls=0,emittedFrames=6,
        touchCanSatisfyCrown=False,productHomeAcceptance='unchanged',maxStructuredBytes=16384,frameBytes=frame_bytes,
        structuredBytes=0,failureReason='none',omittedFrames=0,omittedRows=0,omittedSubtreeRoots=0,snapshotErrors=0,
        omittedDescendantsUnknown=False,crownStatus='moved_downward')
    for _ in range(4):summary['structuredBytes']=frame_bytes+len(json.dumps(summary,separators=(',',':')).encode())
    text=''.join('WATCH_STATIC_CROWN_FRAME '+p+'\n' for p in payloads)+'WATCH_STATIC_CROWN_RESULT '+json.dumps(summary,separators=(',',':'))+'\n'
    retain(root,report,'static-observations.log',text,'observation_static','isolated_static')
    return report


def mutate_file(root, report, name, transform):
    path=root/name;value=json.loads(path.read_text());transform(value)
    raw=json.dumps(value).encode();path.write_bytes(raw)
    entry=next(e for e in report['evidence'] if e['path']==name)
    entry.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    for stage in report['stages']:
        if stage.get('stdout_sha256') and stage.get('command',[])[:2]==['xcrun','xcresulttool'] and stage['command'][4] in ('tests','summary') and stage['command'][-1] in [row['result_bundle'] for row in report['cases'] if row.get(stage['command'][4]+'_file')==name]:
            stage.update(stdout_sha256=entry['sha256'],stdout_bytes=entry['bytes'])


class WatchCrownResultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.report=fixture(self.root)

    def validate(self): return result.validate_result(self.report,self.root)
    def assertIncomplete(self):
        actual=self.validate();self.assertEqual(actual['result'],'incomplete',actual);self.assertFalse(actual['complete']);self.assertFalse(actual['acceptance'])

    def test_valid_three_cases_are_diagnostic_only_and_commands_independent(self):
        actual=self.validate();self.assertEqual(actual['result'],'passed',actual);self.assertTrue(actual['complete']);self.assertFalse(actual['acceptance'])
        from watch_crown_contract import METHODS,test_command
        for method in METHODS:self.assertEqual(result.expected_command(method['key'],WATCH),test_command(method,WATCH))
        self.assertLess(len(json.dumps(actual).encode()),16384)

    def test_actual_failed_assertion_stays_failed_and_raw_diagnostics_are_retained(self):
        self.report=fixture(self.root,('failed','passed','passed'))
        actual=self.validate();self.assertEqual(actual['result'],'failed',actual);self.assertTrue(actual['complete'])
        self.assertEqual(actual['cases'][0]['original_exit'],65)
        self.assertIn('original Privacy assertion',actual['cases'][0]['summary_failures'][0]['failureText'])
        self.assertFalse(actual['acceptance'])

    def test_failure_remains_failed_when_later_control_missing(self):
        self.report=fixture(self.root,('failed','passed','passed'))
        self.report['cases'][2].pop('tests_file')
        actual=self.validate();self.assertEqual(actual['result'],'failed',actual);self.assertFalse(actual['complete'])
        self.assertEqual(actual['cases'][0]['result'],'failed');self.assertEqual(actual['cases'][2]['result'],'incomplete')

    def test_timeout_failure_diagnostic_does_not_become_ordinary_failure(self):
        self.report=fixture(self.root,('failed','passed','passed'))
        mutate_file(self.root,self.report,'actual_cold-summary.json',lambda s:s['testFailures'][0].update(failureText='Test exceeded execution time allowance of 2 minutes'))
        self.assertIncomplete();self.assertEqual(self.validate()['cases'][0]['raw_summary_result'],'Failed')

    def test_wrong_command_case_destination_allowance_or_retry_rejected(self):
        for mutate in [lambda s:s['command'].append('-retry-tests-on-failure'),lambda s:s['command'].__setitem__(-3,'-only-testing:Other'),
                       lambda s:s.update(timeout_seconds=240),lambda s:s.update(raw_exit=65),lambda s:s.update(started=False),
                       lambda s:s.update(timed_out=True),lambda s:s.update(stdout_truncated=True),lambda s:s.update(process_group_gone=False),
                       lambda s:s.update(capture_reader_finished=False)]:
            with self.subTest(mutate=mutate):
                saved=copy.deepcopy(self.report);mutate(self.report['stages'][self.report['cases'][0]['stage_index']]);self.assertIncomplete();self.report=saved

    def test_source_toolchain_profile_products_and_budget_tampering_reject(self):
        mutations=[lambda r:r['source'].update(sha='f'*40),lambda r:r['source_after'].update(tree='f'*40),lambda r:r.update(source_verified=False),
            lambda r:r['toolchain'].update(macos='26A999'),lambda r:r['device'].update(millimeters=44),lambda r:r['device'].update(text_phase='largest'),
            lambda r:r['budget'].update(minutes=45),lambda r:r['budget']['reserves'].update(cleanup=0),lambda r:r['budget'].update(started_monotonic=101),
            lambda r:r['products_after']['actual_cold'].update(sha256='f'*64),lambda r:r.update(acceptance=True),lambda r:r.update(attempt='2')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                saved=copy.deepcopy(self.report);mutate(self.report);self.assertIncomplete();self.report=saved

    def test_phase_overlap_and_original_work_cutoff_are_rejected(self):
        self.report['phases'][4]['started_monotonic']=110
        self.assertIncomplete()
        self.report=fixture(self.root);self.report['phases'][5]['finished_monotonic']=2000;self.assertIncomplete()

    def test_missing_skip_extra_and_foreign_tree_case_rejected(self):
        for change in [lambda t:t.update(testNodes=[]),lambda t:t['testNodes'][0]['children'][0]['children'][0]['children'][0].update(result='Skipped'),
                       lambda t:t['testNodes'][0]['children'][0]['children'][0]['children'].append(copy.deepcopy(t['testNodes'][0]['children'][0]['children'][0]['children'][0])),
                       lambda t:t['testNodes'][0]['children'][0]['children'][0]['children'][0].update(nodeIdentifier='Other/testOther()')]:
            self.report=fixture(self.root);mutate_file(self.root,self.report,'actual_cold-tests.json',change);self.assertIncomplete()

    def test_extraction_hash_and_case_cleanup_identity_are_required(self):
        self.report['stages'][self.report['cases'][0]['summary_stage_index']]['stdout_sha256']='f'*64;self.assertIncomplete()
        self.report=fixture(self.root);self.report['cases'][0]['process_cleanup']['identifiers']=['wrong'];self.assertIncomplete()

    def test_cleanup_absence_is_read_from_raw_evidence(self):
        mutate_file(self.root,self.report,'cleanup-devices.json',lambda d:d['devices'].update({RUNTIME:[{'udid':WATCH}]}))
        entry=next(e for e in self.report['evidence'] if e['path']=='cleanup-devices.json')
        self.report['cleanup']['device_inventory_sha256']=entry['sha256']
        self.report['stages'][self.report['cleanup']['device_stage_index']].update(stdout_sha256=entry['sha256'],stdout_bytes=entry['bytes'])
        self.assertIncomplete()

    def test_manifest_digest_missing_unlisted_symlink_and_hardlink_reject(self):
        (self.root/'actual_cold-summary.json').write_text('{}');self.assertIncomplete()
        self.report=fixture(self.root);(self.root/'unlisted').write_text('extra');self.assertIncomplete();(self.root/'unlisted').unlink()
        path=self.root/'actual_cold-summary.json';saved=path.read_bytes();path.unlink();path.symlink_to(self.root/'actual_cold-tests.json');self.assertIncomplete();path.unlink();path.write_bytes(saved)
        import os
        os.link(path,self.root/'duplicate');self.assertIncomplete()

    def test_observation_and_total_caps_are_enforced(self):
        retain(self.root,self.report,'home-observations.json','x'*16385,'observation_home','actual_cold');self.assertIncomplete()
        (self.root/'home-observations.json').unlink();self.report=fixture(self.root)
        retain(self.root,self.report,'large-console.log','x'*1_190_000,'diagnostics');self.assertIncomplete()

    def test_duplicate_json_and_nonfinite_inputs_reject(self):
        for raw in ('{"schema":1,"schema":1}', '{"n":NaN}', '{"n":1e999}'):
            with self.assertRaises(ValueError):result.strict_json(raw)

    def test_external_original_budget_binding_cannot_reset_clocks(self):
        expected=copy.deepcopy(self.report['budget']);expected['started_monotonic']=90
        actual=result.validate_result(self.report,self.root,expected_budget=expected)
        self.assertEqual(actual['result'],'incomplete');self.assertFalse(actual['acceptance'])

    def test_unknown_stage_and_case_shapes_are_incomplete(self):
        self.report['stages']=None;self.assertIncomplete()
        self.report=fixture(self.root);self.report['cases'][0]['name']=[];self.assertIncomplete()

    def test_failure_diagnostics_survive_missing_test_tree(self):
        self.report=fixture(self.root,('failed','passed','passed'));self.report['cases'][0].pop('tests_file')
        actual=self.validate();self.assertEqual(actual['cases'][0]['result'],'incomplete')
        self.assertEqual(actual['cases'][0]['raw_summary_result'],'Failed')
        self.assertIn('original Privacy assertion',actual['cases'][0]['summary_failures'][0]['failureText'])

    def test_extra_unselected_xcodebuild_test_action_is_rejected(self):
        self.report['stages'][0]['command']=['/usr/bin/xcodebuild','-project','Other.xcodeproj','test']
        self.assertIncomplete()

    def test_missing_or_truncated_observations_keep_failed_diagnostic_separate(self):
        self.report=fixture(self.root,('failed','passed','passed'))
        mutate_file(self.root,self.report,'home-observations.json',lambda h:h.update(truncated=True))
        actual=self.validate();self.assertEqual(actual['result'],'failed',actual);self.assertFalse(actual['complete'])
        self.assertEqual(actual['cases'][0]['result'],'failed')
        self.report=fixture(self.root);mutate_file(self.root,self.report,'cold-list-frames.json',lambda c:c.update(records=[]))
        self.assertIncomplete()
        self.report=fixture(self.root);entry=next(e for e in self.report['evidence'] if e['path']=='static-observations.log')
        text=(self.root/entry['path']).read_text().replace('"touchCanSatisfyCrown":false','"touchCanSatisfyCrown":true')
        (self.root/entry['path']).write_text(text);entry.update(bytes=len(text.encode()),sha256=hashlib.sha256(text.encode()).hexdigest())
        self.assertIncomplete()

    def test_duplicate_and_reordered_cases_never_pass(self):
        self.report['cases'][1]=copy.deepcopy(self.report['cases'][0]);self.assertIncomplete()
        self.report=fixture(self.root);self.report['cases'].reverse();self.assertIncomplete()


if __name__=='__main__':unittest.main()
