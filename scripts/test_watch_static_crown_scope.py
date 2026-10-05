"""Fixed one-case scope and adversarial synthetic evidence; no native execution."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_watch_crown_control as driver
import watch_crown_contract as contract
import watch_crown_result as result
from test_watch_crown_driver import environment, Clock
from test_watch_crown_result import fixture, WATCH, PHONE, PAIR
from job_budget import BudgetExhausted
import test_watch_crown_simulator_fence as fence

ROOT=Path(__file__).resolve().parents[1]
UNSET=object()


def replace_static(root, report, change):
    path=root/'static-observations.log'
    entries=[(line.partition(' ')[0],json.loads(line.partition(' ')[2])) for line in path.read_text().splitlines()]
    change(entries)
    frames=[v for p,v in entries if p.endswith('_FRAME')]
    summaries=[v for p,v in entries if p.endswith('_RESULT')]
    if len(summaries)==1:
        summary=summaries[0]
        summary['frameBytes']=sum(len(json.dumps(v,separators=(',',':')).encode()) for v in frames)
        for _ in range(4):summary['structuredBytes']=summary['frameBytes']+len(json.dumps(summary,separators=(',',':')).encode())
    raw=''.join(p+' '+json.dumps(v,separators=(',',':'))+'\n' for p,v in entries).encode()
    path.write_bytes(raw)
    item=next(e for e in report['evidence'] if e['path']==path.name)
    item.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class StaticScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.report=fixture(self.root)

    def scoped(self, value):
        self.assertEqual(value['purpose'],'static_list_crown_only')
        self.assertEqual(value['diagnostic_scope'],'static-list-crown-only-v1')
        self.assertEqual(value['excluded_cases'],['actual_cold','rgb_positive'])
        self.assertEqual([v['name'] for v in value['cases']],['isolated_static'])
        self.assertIs(value['acceptance'],False)

    def incomplete(self, report=UNSET):
        answer=result.validate_result(self.report if report is UNSET else report,self.root)
        self.scoped(answer);self.assertFalse(answer['complete']);self.assertEqual(answer['result'],'incomplete',answer)
        return answer

    def test_exact_singleton_contract_and_source_workflow_binding(self):
        self.assertEqual(len(contract.METHODS),1)
        self.assertEqual(contract.PHASES,{'preflight':30,'builds':240,'setup':600,'isolated_static':180})
        self.assertEqual(contract.WORKFLOW,result.WORKFLOW)
        self.assertEqual(contract.binding(environment())['workflow'],result.WORKFLOW)
        for key,value in [('GITHUB_REF','refs/heads/codex/watch-crown-diagnostic'),
                          ('GITHUB_WORKFLOW_REF','100mango/ColorPicker/.github/workflows/watch-crown-control.yml@'+contract.REF),
                          ('TOUCHCOLOR_JOB_LANE','watch-crown-control-smallest'),('TOUCHCOLOR_DIAGNOSTIC_SCOPE',''),
                          ('TOUCHCOLOR_DIAGNOSTIC_SCOPE','three-method')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                contract.binding({**environment(),key:value})
        method=copy.deepcopy(contract.METHODS[0]);method['case']='Other/testOther'
        with self.assertRaises(ValueError):contract.test_command(method,WATCH)

    def test_old_missing_foreign_scopes_refs_workflows_products_and_runners_reject(self):
        changes=[lambda r:r.pop('diagnostic_scope'),lambda r:r.update(diagnostic_scope='three-method'),
                 lambda r:r.update(excluded_cases=[]),lambda r:r.update(excluded_cases=list(reversed(r['excluded_cases']))),
                 lambda r:r['source'].update(ref='refs/heads/codex/watch-crown-diagnostic'),
                 lambda r:r['source'].update(workflow='.github/workflows/watch-crown-control.yml'),
                 lambda r:r['source'].pop('workflow'),lambda r:r['budget'].update(lane='watch-crown-control-smallest'),
                 lambda r:r['products_before'].update(actual_cold=copy.deepcopy(r['products_before']['isolated_static'])),
                 lambda r:r['runner_bundle_ids'].update(actual_cold='product-runner'),lambda r:r.pop('runner_bundle_ids')]
        for change in changes:
            with self.subTest(change=change):
                receipt=copy.deepcopy(self.report);change(receipt);self.incomplete(receipt)

    def test_singleton_inventory_rejects_extra_repeated_foreign_and_wrapped_commands(self):
        commands=[result.expected_command('isolated_static',WATCH),['xcodebuild','-project','TouchColorWatch.xcodeproj','test'],
                  ['/usr/bin/env','xcrun','simctl','launch',WATCH,'com.mango.touchColor.watchkitapp'],
                  ['/bin/sh','-c','xcodebuild test'],['xcrun','simctl','spawn',WATCH,'log','show'],
                  ['xcrun','simctl','terminate',WATCH,'com.mango.touchColor.watchkitapp']]
        for command in commands:
            with self.subTest(command=command):
                receipt=copy.deepcopy(self.report);receipt['stages'][0]['command']=command;self.incomplete(receipt)
        for key in ('cases','products_before','runner_bundle_ids'):
            receipt=copy.deepcopy(self.report)
            if key=='cases':receipt[key].append(copy.deepcopy(receipt[key][0]))
            else:receipt[key]['rgb_positive']=copy.deepcopy(next(iter(receipt[key].values())))
            self.incomplete(receipt)
        receipt=copy.deepcopy(self.report);receipt['cases']=[];self.incomplete(receipt)

    def test_native_caps_and_termination_inventory_are_exact(self):
        for selector,value in [(lambda s:s['command'][:3]==['xcrun','simctl','terminate'],3),
                               (lambda s:'launchctl' in s['command'],6),
                               (lambda s:'build-for-testing' in s['command'],120),
                               (lambda s:s['phase']=='isolated_static' and 'summary' in s['command'],20)]:
            receipt=copy.deepcopy(self.report);next(s for s in receipt['stages'] if selector(s))['timeout_seconds']=value
            self.incomplete(receipt)

    def test_retained_per_file_caps_and_build_bytes_remain_enforced(self):
        for name,cap in [('isolated_static-lifecycle.log',4096),('isolated_static-console.log',65536),
                         ('isolated_static-build.log',262144),('isolated_static-summary.json',100000),
                         ('isolated_static-tests.json',150000),('isolated_static-cleanup-services.log',65536)]:
            with self.subTest(name=name):
                self.report=fixture(self.root);raw=(self.root/name).read_bytes()
                raw+=b' '*(cap+1-len(raw));(self.root/name).write_bytes(raw)
                entry=next(e for e in self.report['evidence'] if e['path']==name)
                entry.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());self.incomplete()
        self.report=fixture(self.root)
        next(s for s in self.report['stages'] if s['phase']=='builds')['stdout_sha256']='f'*64;self.incomplete()
        self.report=fixture(self.root)
        entry=next(e for e in self.report['evidence'] if e['path']=='isolated_static-build.log')
        self.report['evidence'].remove(entry);(self.root/entry['path']).unlink();self.incomplete()

    def test_source_run_workflow_external_binding_rejects_other_job(self):
        path=self.root/'report.json';path.write_text(json.dumps(self.report))
        expected={k:self.report['source'][k] for k in ('sha','ref','workflow','workflow_sha256','run_id','attempt','repository')}
        self.scoped(result.load_result(path,expected_binding=expected))
        for key in expected:
            with self.subTest(key=key),self.assertRaises(ValueError):
                result.load_result(path,expected_binding={**expected,key:'foreign'})

    def test_stationary_crown_and_downward_touch_is_a_real_failed_case(self):
        self.report=fixture(self.root,('failed',));value=result.validate_result(self.report,self.root)
        self.scoped(value);self.assertTrue(value['complete']);self.assertEqual(value['result'],'failed')
        self.assertEqual(value['cases'][0]['crown_status'],'stationary')
        self.assertEqual(value['cases'][0]['touch_status'],'moved_downward')
        for flag in ('cleanup_confirmed','tests_file','summary_file'):
            receipt=copy.deepcopy(self.report);receipt['cases'][0].pop(flag);self.incomplete(receipt)

    def test_static_markers_cannot_alias_touch_or_fabricate_movement(self):
        changes=[lambda e:e[-1][1].update(crownStatus='stationary'),lambda e:e[-1][1].update(crownCalls=2),
                 lambda e:e[-1][1].update(delta=0.1),lambda e:e[-1][1].update(touchCanSatisfyCrown=True),
                 lambda e:e[-1][1].update(failureReason='geometry'),lambda e:e[-1][1].update(omittedRows=1),
                 lambda e:e[-1][1].update(snapshotErrors=1),lambda e:e[-1][1].update(omittedFrames=False),
                 lambda e:e[0][1].update(runnerPID=44),lambda e:e[0][1].update(geometryComplete=False),
                 lambda e:e[0][1].update(listCount=True),lambda e:e[1][1]['rows'][0].update(frame=[0,40,200,40]),
                 lambda e:e.append(copy.deepcopy(e[-1])),lambda e:e.reverse()]
        for change in changes:
            with self.subTest(change=change):
                self.report=fixture(self.root);replace_static(self.root,self.report,change)
                # One stationary first rotation can still be followed by genuine movement; erase all movement for this adversary.
                if changes.index(change)==11:
                    replace_static(self.root,self.report,lambda e:[v['rows'][0].update(frame=[0,40,200,40]) for p,v in e if p.endswith('_FRAME')])
                self.incomplete()
        self.report=fixture(self.root,('failed',))
        replace_static(self.root,self.report,lambda e:e[-1][1].update(crownStatus='moved_downward'))
        self.incomplete()

    def test_malformed_top_level_receipts_never_escape_or_claim_full_comparison(self):
        for value in (None,[],True,'foreign',{}, {'cases':[]}, {'schema':2,'errors':1}):self.incomplete(value)
        for key in ('source','device','budget','cases','stages','phases','cleanup','errors','evidence','runner_bundle_ids'):
            for value in (None,True,[],{},'foreign'):
                if key=='errors' and value==[]:continue
                receipt=copy.deepcopy(self.report);receipt[key]=value
                with self.subTest(key=key,value=value):self.incomplete(receipt)

    def test_validator_exception_and_write_failure_keep_single_case_scope(self):
        import atomic_json,job_budget
        for write_failure in (False,True):
            captured=io.StringIO()
            with patch.object(job_budget,'load',side_effect=ValueError('synthetic unavailable budget')), \
                 patch.object(atomic_json,'write_json',side_effect=OSError('synthetic storage failure') if write_failure else None), \
                 patch.object(sys,'stdout',captured):
                self.assertEqual(result.main([str(self.root/'report.json')]),1)
            value=json.loads(captured.getvalue());self.scoped(value);self.assertFalse(value['complete'])
            self.assertEqual(value['result'],'incomplete')


class StaticAdmissionTests(unittest.TestCase):
    def test_full_static_phase_at840_and_rejection_after840(self):
        for offset in (840,840.000001):
            with self.subTest(offset=offset),tempfile.TemporaryDirectory() as folder:
                previous=Path.cwd();os.chdir(folder)
                try:
                    Path('build/evidence').mkdir(parents=True);clock=Clock()
                    d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall)
                    clock.advance(offset)
                    if offset==840:
                        with d.phase('isolated_static',180):pass
                        self.assertEqual(d.report['phases'][0]['limit_seconds'],180)
                    else:
                        with self.assertRaises(BudgetExhausted):
                            with d.phase('isolated_static',180):self.fail('Late static phase admitted')
                        self.assertEqual(d.report['phases'],[])
                    self.assertEqual(d.report['stages'],[])
                finally:os.chdir(previous)

    def test_e4180_watch_boot195681_raw_zero_fences_every_later_operation(self):
        t=fence.SimulatorFenceTests();t.setUp()
        try:
            t.d.process_factory=t.process(elapsed=195.681245250000075)
            with patch.object(driver,'stop_group',return_value=True),t.d.phase('setup',600):
                row,_=t.d.run(['xcrun','simctl','boot',WATCH],180,clip_setup=True,required=False)
            self.assertEqual(row['raw_exit'],0);self.assertEqual(row['exit'],124);self.assertTrue(row['timed_out'])
            self.assertAlmostEqual(row['finished_monotonic']-row['deadline_monotonic'],15.68124525)
            t.assert_blocked_everywhere();t.reload_blocked()
        finally:t.tearDown()


class SyntheticExecutionTests(unittest.TestCase):
    """Run the actual controller/wrapper/validator against fake owned native processes."""
    def execute(self, status='passed', terminate_late=False, extraction_persist_failure=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        old=Path.cwd();os.chdir(temporary.name);self.addCleanup(os.chdir,old)
        fixture_root=Path('synthetic-fixture');fixture_root.mkdir();seed=fixture(fixture_root,(status,))
        markers=(fixture_root/'static-observations.log').read_text()
        lifecycle=(fixture_root/'isolated_static-lifecycle.log').read_text()
        tree=(fixture_root/'isolated_static-tests.json').read_text()
        native_summary=json.loads((fixture_root/'isolated_static-summary.json').read_text())
        devices=copy.deepcopy(seed['initial_inventory']['devices'])
        for i,rows in enumerate(devices.values()):rows[0]['udid']=('44444444-4444-4444-8444-444444444444','55555555-5555-4555-8555-555555555555')[i]
        workflow=Path(contract.WORKFLOW);workflow.parent.mkdir(parents=True);workflow.write_text('synthetic static workflow\n')
        clock=Clock();commands=[];state={'paired':False,'owned':{},'test_start':None}
        env=environment();products=Path('build/crown-static/Build/Products');owner=self
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):
                commands.append(command);self.elapsed=.1;self.code=0;raw=''
                if command==['git','rev-parse','HEAD']:raw=env['GITHUB_SHA']+'\n'
                elif command==['git','rev-parse','HEAD^{tree}']:raw='b'*40+'\n'
                elif command==['xcodebuild','-version']:raw='Xcode 27.0\nBuild version 27A266a\n'
                elif command==['sw_vers','-buildVersion']:raw='26A428\n'
                elif command==['uname','-m']:raw='arm64\n'
                elif 'build-for-testing' in command:
                    runner=products/'Debug-watchsimulator/TouchColorWatchCrownControlUITests-Runner.app/Info.plist'
                    runner.parent.mkdir(parents=True);runner.write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.mango.touchColor.watchCrownControl.uitests.xctrunner'}))
                    (products/'control.xctestrun').write_bytes(b'synthetic product fingerprint')
                    raw='synthetic build completed\n'
                elif command[:2]==['xcodebuild','test-without-building']:
                    state['test_start']=clock.wall;self.elapsed=4;self.code=0 if status=='passed' else 65
                    Path(command[command.index('-resultBundlePath')+1]).mkdir()
                    raw=lifecycle+markers
                    state['capture']=raw.encode()
                elif command[:2]==['xcrun','xcresulttool']:
                    if command[4]=='summary':
                        persisted=json.loads(Path('build/evidence/report.json').read_text())
                        proof=persisted['cases'][0]['capture_extraction']
                        owner.assertEqual(proof['stage_index'],persisted['cases'][0]['stage_index'])
                        owner.assertEqual(proof['capture'],{'sha256':hashlib.sha256(state['capture']).hexdigest(),'bytes':len(state['capture'])})
                        owner.assertEqual([e['path'] for e in proof['files']],['isolated_static-lifecycle.log','isolated_static-console.log','static-observations.log'])
                        state['proof_before_summary']=copy.deepcopy(proof)
                        native_summary.update(startTime=state['test_start']+.5,finishTime=state['test_start']+3)
                        raw=json.dumps(native_summary)
                    else:raw=tree
                elif command[:2]==['xcrun','simctl']:
                    action=command[2]
                    if command[2:5]==['list','devices','available']:raw=json.dumps({'devices':devices})
                    elif command[2:4]==['list','devices']:
                        current={}
                        for identifier,device in state['owned'].items():current.setdefault(device['runtime'],[]).append({'udid':identifier,'state':device['state']})
                        raw=json.dumps({'devices':current})
                    elif command[2:4]==['list','pairs']:
                        raw=json.dumps({'pairs':{PAIR:seed['pair']['record']} if state['paired'] else {}})
                    elif action=='create':
                        identifier=PHONE if '-phone-' in command[3] else WATCH
                        state['owned'][identifier]={'runtime':command[-1],'state':'Shutdown'};raw=identifier+'\n'
                    elif action=='pair':state['paired']=True;raw=PAIR+'\n'
                    elif action=='boot':state['owned'][command[3]]['state']='Booted'
                    elif action=='bootstatus':raw='synthetic boot completed\n'
                    elif action=='terminate':
                        owner.assertEqual(json.loads(Path('build/evidence/report.json').read_text())['cases'][0]['capture_extraction'],state['proof_before_summary'])
                        self.elapsed=30.25 if terminate_late else .1
                    elif command[2]=='spawn':raw='PID\tStatus\tLabel\n'
                    elif action=='shutdown':state['owned'][command[3]]['state']='Shutdown'
                    elif action=='unpair':state['paired']=False
                    elif action=='delete':state['owned'].pop(command[3])
                    else:raise AssertionError('Unexpected synthetic native command: '+repr(command))
                elif command not in ([sys.executable,'scripts/generate_watch_crown_control_project.py'],['git','status','--porcelain','--untracked-files=all']):
                    raise AssertionError('Unexpected synthetic host command: '+repr(command))
                self.stdout=io.BytesIO(raw.encode())
            def wait(self,timeout=None):clock.advance(self.elapsed);return self.code
        d=driver.Driver(env,clock=lambda:clock.mono,wall=lambda:clock.wall,process_factory=Process)
        original_write=driver.write_json;failed_once=False
        def write(path,value,**kwargs):
            nonlocal failed_once
            if extraction_persist_failure and not failed_once and path.name=='report.json' and value.get('cases') and value['cases'][0].get('capture_extraction'):
                failed_once=True;raise OSError('synthetic extraction receipt persistence failure')
            return original_write(path,value,**kwargs)
        with patch.object(driver,'stop_group',return_value=True),patch.object(driver,'_write_console_nonblocking',return_value=False), \
             patch.object(driver,'write_json',side_effect=write):
            self.assertEqual(d.execute(),0)
        return d,commands,result.load_result('build/evidence/report.json')

    def test_actual_driver_and_independent_validator_agree_on_single_static_pass(self):
        d,commands,value=self.execute()
        self.assertEqual(value['result'],'passed',value);self.assertTrue(value['complete']);self.assertFalse(value['acceptance'])
        self.assertEqual([c for c in commands if c[:2]==['xcodebuild','test-without-building']],
                         [contract.test_command(contract.METHODS[0],WATCH)])
        started=len(commands)
        with self.assertRaises(ValueError):d.method(contract.METHODS[0])
        self.assertEqual(len(commands),started)
        self.assertEqual(set(d.report['products_before']),{'isolated_static'})
        self.assertEqual(d.report['products_before'],d.report['products_after'])
        self.assertEqual(d.report['runner_bundle_ids'],{'isolated_static':'com.mango.touchColor.watchCrownControl.uitests.xctrunner'})
        self.assertFalse(any('com.mango.touchColor.watchkitapp' in c or 'log' in c or 'scripts/generate_watch_project.py' in c for c in commands))
        self.assertEqual(set(p.name for p in Path('build/evidence').iterdir()),{
            'report.json','isolated_static-build.log','setup-phone-bootstatus.log','setup-watch-bootstatus.log',
            'isolated_static-lifecycle.log','isolated_static-console.log','static-observations.log','isolated_static-summary.json',
            'isolated_static-cleanup-services.log','isolated_static-tests.json','cleanup-devices.json','cleanup-pairs.json'})

    def test_actual_driver_preserves_stationary_failure_with_touch_movement(self):
        d,commands,value=self.execute('failed')
        self.assertEqual(value['result'],'failed',value);self.assertTrue(value['complete']);self.assertFalse(value['acceptance'])
        self.assertEqual(value['cases'][0]['crown_status'],'stationary');self.assertEqual(value['cases'][0]['touch_status'],'moved_downward')
        self.assertEqual(d.report['stages'][d.report['cases'][0]['stage_index']]['raw_exit'],65)

    def test_early_static_payload_survives_real_wrapper_termination_fence(self):
        d,commands,value=self.execute('failed',terminate_late=True)
        self.assertEqual(value['result'],'incomplete');self.assertFalse(value['complete'])
        self.assertEqual(commands[-1][:3],['xcrun','simctl','terminate'])
        for suffix in ('lifecycle.log','console.log','summary.json'):
            self.assertTrue(Path('build/evidence/isolated_static-'+suffix).is_file())
        marker=Path('build/evidence/static-observations.log');before=marker.read_bytes()
        self.assertIn(b'"crownStatus":"stationary"',before)
        self.assertEqual(d.report['cases'][0]['observed_command_result'],'failed')
        self.assertFalse(d.report['cases'][0]['cleanup_confirmed']);self.assertTrue(d.simulator_uncertain)
        count=len(commands);d.cleanup();d.evidence();self.assertEqual(len(commands),count)
        self.assertEqual(marker.read_bytes(),before)
        with self.assertRaises(ValueError):d.retain(marker.name,b'changed','observation_static','isolated_static',limit=16384)
        self.assertFalse(Path('build/evidence/isolated_static-tests.json').exists())


    def test_actual_wrapper_extraction_receipt_write_failure_fences_before_summary(self):
        d,commands,value=self.execute(extraction_persist_failure=True)
        self.assertFalse(value['complete']);self.assertEqual(value['result'],'incomplete')
        self.assertTrue(d.simulator_uncertain)
        self.assertEqual(commands[-1][:2],['xcodebuild','test-without-building'])
        self.assertFalse(any(c[:2]==['xcrun','xcresulttool'] for c in commands))
        self.assertFalse(any(c[:3]==['xcrun','simctl','terminate'] for c in commands))
        for name in ('isolated_static-lifecycle.log','isolated_static-console.log','static-observations.log'):
            self.assertTrue((Path('build/evidence')/name).is_file())
        self.assertTrue(d.report['cases'][0]['capture_extraction'])

    def test_actual_wrapper_capture_stage_and_extraction_mutations_never_complete(self):
        d,commands,baseline=self.execute();self.assertTrue(baseline['complete'])
        original=copy.deepcopy(d.report);index=original['cases'][0]['stage_index']
        self.assertEqual(original['stages'][index]['stdout_bytes'],4218)
        def stage(r):return r['stages'][index]
        def proof(r):return r['cases'][0]['capture_extraction']
        mutations=[
            ('stage digest absent',lambda r:stage(r).pop('stdout_sha256')),
            ('stage count absent',lambda r:stage(r).pop('stdout_bytes')),
            ('stage digest false',lambda r:stage(r).update(stdout_sha256='f'*64)),
            ('stage digest malformed',lambda r:stage(r).update(stdout_sha256='invalid')),
            ('stage count zero',lambda r:stage(r).update(stdout_bytes=0)),
            ('stage count negative',lambda r:stage(r).update(stdout_bytes=-1)),
            ('stage count boolean',lambda r:stage(r).update(stdout_bytes=True)),
            ('stage count over cap',lambda r:stage(r).update(stdout_bytes=262145)),
            ('stage count changed',lambda r:stage(r).update(stdout_bytes=4219)),
            ('extraction absent',lambda r:r['cases'][0].pop('capture_extraction')),
            ('policy false',lambda r:proof(r).update(policy='other-policy')),
            ('schema boolean',lambda r:proof(r).update(schema=True)),
            ('provenance false',lambda r:proof(r).update(provenance='reconstructed original stream')),
            ('stage index foreign',lambda r:proof(r).update(stage_index=index+1)),
            ('stage index boolean',lambda r:proof(r).update(stage_index=True)),
            ('source foreign',lambda r:proof(r).update(source_sha='f'*40)),
            ('run foreign',lambda r:proof(r).update(run_id='999')),
            ('attempt foreign',lambda r:proof(r).update(attempt='2')),
            ('case foreign',lambda r:proof(r).update(case='actual_cold')),
            ('capture digest false',lambda r:proof(r)['capture'].update(sha256='f'*64)),
            ('capture count false',lambda r:proof(r)['capture'].update(bytes=0)),
            ('capture count boolean',lambda r:proof(r)['capture'].update(bytes=True)),
            ('split omitted',lambda r:proof(r)['files'].pop()),
            ('split extra',lambda r:proof(r)['files'].append(copy.deepcopy(proof(r)['files'][0]))),
            ('split reordered',lambda r:proof(r)['files'].reverse()),
        ]
        for part in range(3):
            for field,value in [('path','foreign.log'),('sha256','f'*64),('bytes',0),('bytes',True)]:
                mutations.append((f'split {part} {field} {value}',lambda r,p=part,f=field,v=value:proof(r)['files'][p].update({f:v})))
        for label,change in mutations:
            with self.subTest(label=label):
                receipt=copy.deepcopy(original);change(receipt)
                answer=result.validate_result(receipt,'build/evidence')
                self.assertFalse(answer['complete'],(label,answer));self.assertEqual(answer['result'],'incomplete',(label,answer))
                self.assertEqual(answer['diagnostic_scope'],'static-list-crown-only-v1')
                self.assertFalse(answer['acceptance'])

    def test_actual_wrapper_split_byte_manifest_and_visible_policy_mutations_reject(self):
        d,commands,baseline=self.execute();self.assertTrue(baseline['complete'])
        original=copy.deepcopy(d.report)
        for part,name in enumerate(['isolated_static-lifecycle.log','isolated_static-console.log','static-observations.log']):
            path=Path('build/evidence')/name;before=path.read_bytes()
            try:
                # Re-sealing the manifest alone cannot rebind a changed file to this capture.
                changed=before+b'changed\n';path.write_bytes(changed)
                receipt=copy.deepcopy(original);entry=next(e for e in receipt['evidence'] if e['path']==name)
                entry.update(bytes=len(changed),sha256=hashlib.sha256(changed).hexdigest())
                answer=result.validate_result(receipt,'build/evidence')
                self.assertFalse(answer['complete']);self.assertEqual(answer['result'],'incomplete')
            finally:path.write_bytes(before)
        # Even a self-consistent new console receipt must obey the fixed visible
        # lifecycle projection. No claim is made about discarded interleaving.
        path=Path('build/evidence/isolated_static-console.log');before=path.read_bytes()
        try:
            changed=before.replace(b'Test Case ',b'Changed Case ',1);path.write_bytes(changed)
            receipt=copy.deepcopy(original);entry=next(e for e in receipt['evidence'] if e['path']==path.name)
            entry.update(bytes=len(changed),sha256=hashlib.sha256(changed).hexdigest())
            receipt['cases'][0]['capture_extraction']['files'][1]={k:entry[k] for k in ('path','sha256','bytes')}
            answer=result.validate_result(receipt,'build/evidence')
            self.assertFalse(answer['complete']);self.assertEqual(answer['result'],'incomplete')
        finally:path.write_bytes(before)


class FrozenScopeTests(unittest.TestCase):
    def test_native_sources_projects_helpers_workflows_and_history_are_frozen(self):
        expected = {'.github/workflows/apple-platforms.yml': '8c4e6fff2438d42838e718107a16db951629febd8a9cbe43e346c90e0f78e8e7',
         '.github/workflows/ios.yml': 'e141cf19433d94cb78410f5d2b5e91f11523c92ddc3e9fae84743a17153f37ae',
         '.github/workflows/watch-crown-control.yml': '17a26672cb899157885a3bd3586eed1c0d289c55ec3f489bccaf2478a9a35542',
         'TouchColorWatch.xcodeproj/project.pbxproj': '3dda011a09cce4db4e855fe0160be8ac1aa4ae86034ff7aae79c1c65bcf5577a',
         'TouchColorWatch.xcodeproj/xcshareddata/xcschemes/TouchColorWatch.xcscheme': 'a5904ca441aae5717361678ff05a874628904b35d72ffef096c63bbbbb277417',
         'TouchColorWatch/Assets.xcassets/AppIcon.appiconset/Contents.json': '1b5863633f2718ee2d6e13ecfa061651e602bbed493761da215c985ec2a98a60',
         'TouchColorWatch/Assets.xcassets/AppIcon.appiconset/Icon-1024.png': 'b866d4ca66a2b3bc82e9375e613ca09fe3c1823c7177ec0d0ad17f465001cc18',
         'TouchColorWatch/Assets.xcassets/Contents.json': '10e3b5dc202f1cd9fad1f688c8fc9fe9e9669bf3f8295e67d216b10fd99b6f49',
         'TouchColorWatch/PrivacyInfo.xcprivacy': '69a0e9d2755490f330ef7302e81ee9fa17544103dc02beb0b77c4067f8cb08ae',
         'TouchColorWatch/TouchColorWatchApp.swift': '9cfbaeeab92b0573afaa40d5255e48551c6caa9f2bbf9068e7f05306c0013b32',
         'TouchColorWatch/WatchHomeDiagnostics.swift': '1cf58c63d3684d054824249f4ad836c060989d9fd16bd0ab9a58bc89c99776d4',
         'TouchColorWatch/WatchPalette.swift': 'ef9b07049d8870f38d4af507c418d11470cf8ecca2b7eb8e23e299f5e8efe9e5',
         'TouchColorWatch/WatchPhoto.swift': '2eac43120e03deff153777f1b3e6e992fd0c9205fed1390f3d45d27195aa190c',
         'TouchColorWatch/WatchTransfer.swift': '0b3858565b8207e84b398052ee95a3a9552f9094da004a7369b7c02178cce95f',
         'TouchColorWatch/WatchViews.swift': '2090ba4654d9d1a36123b56a91911e6364178de6ccbe5e43c886c69d1b345059',
         'TouchColorWatch/en.lproj/InfoPlist.strings': '33453f35535441b26b75404e619178466432cbab773acb7db1f481d715c2c373',
         'TouchColorWatch/en.lproj/Localizable.strings': 'ce836f5d0fad9c57aad82a42da7d92c63074ecda9438c6ce7e4d5525f4dac408',
         'TouchColorWatch/zh-Hans.lproj/InfoPlist.strings': '33453f35535441b26b75404e619178466432cbab773acb7db1f481d715c2c373',
         'TouchColorWatch/zh-Hans.lproj/Localizable.strings': 'd2c8352b82845d0d8bbdcab4db91cd4fff6a6826dc4e22ed4bda997bd7265ce3',
         'TouchColorWatchCrownControl.xcodeproj/project.pbxproj': 'bae810085bb945e9e0f3d9df354f1c383def3d49315b6685456a9114adb9bd6c',
         'TouchColorWatchCrownControl.xcodeproj/xcshareddata/xcschemes/TouchColorWatchCrownControl.xcscheme': '4ffe6fe54de33714fdfd3ff3013f751d649febf155acf8a356ec599469510e4e',
         'TouchColorWatchCrownControl/README.md': '118c986dc2d62bc615dba9e708f4aafd7facbb942788f6aabd17f1599928a69d',
         'TouchColorWatchCrownControl/StaticCrownControlApp.swift': '2dac9aa2e6610c4977b68e5c774309bf71277830ac4183bfcc60c65097794a34',
         'TouchColorWatchCrownControlUITests/TCStaticListGeometry.h': 'e8f1c5ea418240f640d386ade53333bfff40b0960cf5c6b72f8f8a1bc838fa19',
         'TouchColorWatchCrownControlUITests/WatchStaticCrownControlTests.swift': '28a3751f1c0d440ce3a7085f1b43f6f78d894ef525b5921b89152838bbbea1f2',
         'TouchColorWatchUITests/Fixtures/home-list-0eda-frames.json': '381a9518a1418b0eefee6c8f514cddb53fb1ca7c148b2874f57c5a92b2c9bb0f',
         'TouchColorWatchUITests/TCWatchListDragGeometry.h': '2ce0ef79c234888cdf500257fa84a6a6123bc3070c769dd356c202cecec30894',
         'TouchColorWatchUITests/WatchWorkflowTests.swift': 'dea14e485da6362a72f5899e09299651699e32f7d7f95d2aed34f22e1bcd1a52',
         'review/CROWN-090986-ARGV-FAILURE.json': '6d20f5d3e05a33f96ddebcded01c16a0a0535c46b27dffca5d42485268aa589b',
         'review/CROWN-11A6AD-RETENTION-CLEANUP.json': 'f22db97508e6463701f7487e1205a22bc3cacce63f153eeb613ab09546bc5476',
         'review/CROWN-E7B29-SETUP-CLOCK.json': 'e0de47c8ac8f207bc5dbac07d0da1728597b03714ca9a6459b65e2e8f4c74162',
         'scripts/atomic_json.py': '748f5cb832ef41a6a0027be8c797b6d2484e4b80a7759df104307cbe06f7e0fb',
         'scripts/bounded_process.py': '8d43e28c00d3e3d7ebe3140b63bcf9ed6b4a6d559282d67ccec30e5aed0db587',
         'scripts/generate_watch_crown_control_project.py': '41a0fc0a0fd2f5d751080a7481c25628c1fcfacab033eeaf0d4986587780a4aa',
         'scripts/generate_watch_project.py': '9d49206c796355267fb1389829f2c7dff4177e3ff1a6867c95b05f6bee147de9',
         'scripts/job_budget.py': '84e5d1c3fe789d7c92bc23fee87ace60b4cb7b6fa1bcd75e14b0a310b18b7e16',
         'scripts/test_extra_platforms.py': '3e58d0eca18f66a24123b45739bbc3c521c7109965da20a914039eb722a5e764',
         'scripts/watch_crown_setup_events.py': 'b175fa519b92189f8bbd22c3998e6162ea8744c05b3cb475b849bf12de0fe7f4',
         'scripts/watch_failure_continuation.py': '954c6cbd19ef23a4e0f7e42e3fedaa83c56a8b6568a3bc6f33b0456e5dbc11ef',
         'scripts/watch_profiles.py': 'bcbd095a3fc36f241b4ce1710d8135ef65f8453bf48fb08ff75a2501957a58ea',
         'scripts/watch_runtime_pair.py': '447a1270a7d874f111c8e110feb1cf80c8ec3910eeaaf2c813359bcc037a701d'}
        for name,sha in expected.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),sha,name)

    def test_dedicated_push_workflow_preserves_original_caps_and_actions(self):
        import yaml
        workflow=yaml.load((ROOT/contract.WORKFLOW).read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['name'],'Static-only Watch Crown diagnostic')
        self.assertEqual(workflow['on'],{'push':{'branches':['codex/watch-static-crown-diagnostic']}})
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertEqual(workflow['concurrency'],{'group':'touchcolor-watch-crown-control','cancel-in-progress':'false'})
        self.assertEqual(set(workflow['jobs']),{'watch-static-crown-control-smallest'})
        job=workflow['jobs']['watch-static-crown-control-smallest']
        self.assertEqual(job['timeout-minutes'],'25');self.assertEqual(job['runs-on'],'xcode-27')
        self.assertEqual(job['if'],"github.repository == '100mango/ColorPicker' && github.ref == 'refs/heads/codex/watch-static-crown-diagnostic' && github.event_name == 'push'")
        self.assertEqual(job['env'],{'DEVELOPER_DIR':'/Applications/Xcode_27.app/Contents/Developer',
            'TOUCHCOLOR_WATCH_PROFILE':'smallest','TOUCHCOLOR_TEXT_PHASE':'normal','TOUCHCOLOR_JOB_PLATFORM':'watch-crown-control',
            'TOUCHCOLOR_JOB_LANE':'watch-static-crown-control-smallest','TOUCHCOLOR_JOB_MINUTES':'25',
            'TOUCHCOLOR_DIAGNOSTIC_SCOPE':'static-list-crown-only-v1','TOUCHCOLOR_MAX_EVIDENCE_BYTES':'1200000'})
        steps=job['steps'];self.assertEqual(len(steps),6)
        self.assertIn('Stamp original clock',steps[0]['name'])
        self.assertEqual(steps[1]['uses'],'actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683')
        self.assertEqual(steps[1]['with'],{'persist-credentials':'false','ref':'${{ github.sha }}'})
        self.assertEqual(steps[2]['run'],'python3 scripts/run_watch_crown_control.py')
        self.assertEqual(steps[3]['run'],'python3 scripts/watch_crown_result.py build/evidence/report.json build/evidence')
        self.assertEqual(steps[-1]['uses'],'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02')
        self.assertEqual(steps[-1]['with']['retention-days'],'3')
        self.assertEqual(steps[-1]['with']['name'],'watch-static-crown-smallest-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}')
        self.assertIn('check-upload',steps[4]['run']);self.assertIn('1200000',steps[4]['run'])
        for name in ('apple-platforms.yml','ios.yml','watch-crown-control.yml'):
            prior=yaml.load((ROOT/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)
            self.assertNotIn('codex/watch-static-crown-diagnostic',prior['on']['push']['branches'])

    def test_console_boundary_identity_is_static_and_existing_ceiling_unchanged(self):
        self.assertEqual(driver.CONSOLE_BOUNDARIES,('preflight','builds','setup','isolated_static','cleanup','evidence','final'))
        self.assertEqual(driver.CONSOLE_RECORD_BYTES,512);self.assertEqual(driver.CONSOLE_TOTAL_BYTES,4608)
        from test_watch_crown_console import report
        value=report();value['cases']=[{'name':'isolated_static','stage_index':0,'observed_command_result':'passed'}]
        value['stages']=[{'started':True,'raw_exit':0}]
        decoded=json.loads(driver._console_record(value,'final',0).decode().removeprefix('WATCH_CROWN_STATUS '))
        self.assertEqual(set(decoded['cases']),{'static'});self.assertEqual(decoded['cases']['static'][:3],[True,'passed',0])


if __name__=='__main__':unittest.main()
