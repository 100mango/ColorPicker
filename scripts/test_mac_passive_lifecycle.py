"""Portable receipt and source fences, no AppKit/log execution claims."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_passive_lifecycle as observe
import retain_mac_evidence as keep
from test_retain_mac_evidence import Fixture, SOURCE

ROOT=Path(__file__).resolve().parents[1]
TOKEN='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
LAUNCH='11111111-2222-3333-4444-555555555555'
APP='/Users/runner/work/ColorPicker/ColorPicker/build/mac-tests/Build/Products/Debug/TouchColor.app'

def receipt():
    return dict(v=1,token=TOKEN,pid=345,test='-[TouchColorMacUITests '+observe.CASES[0]+']',ordinal=1,
                started=100.,captured=101.,args=observe.launch_args(observe.CASES[0],1),sandbox=False,
                bundle='com.mango.touchColor',applicationPath=APP,expectedPath=APP,executable=APP+'/Contents/MacOS/TouchColor',
                executableSHA256='a'*64,logicSHA256='b'*64,xctestPID=None,
                xctestPIDReason='No public PID query; correlate retained failure hierarchy independently')

def exported(root, value=None):
    value=receipt() if value is None else value
    folder=root/'screenshots';folder.mkdir(exist_ok=True)
    name='22222222-2222-3333-4444-555555555555.txt';(folder/name).write_bytes(observe.encode(value))
    attachment={'suggestedHumanReadableName':observe.ATTACHMENT+TOKEN+' 1_'+name,'exportedFileName':name,'timestamp':102.,'deviceId':'mac-fixture','configurationName':'Test Scheme Action'}
    group={'testIdentifier':'TouchColorMacUITests/'+observe.CASES[0]+'()',
           'testIdentifierURL':'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+observe.CASES[0],
           'attachments':[attachment]}
    (folder/'manifest.json').write_text(json.dumps([group]));(root/'mac-ui-summary.json').write_text(json.dumps({'startTime':99.,'finishTime':120.,'devicesAndConfigurations':[{'device':{'deviceId':'mac-fixture','platform':'macOS','architecture':'arm64','osVersion':'27.0'},'testPlanConfiguration':{'configurationName':'Test Scheme Action'}}]}))
    return folder/name

def event(r=None, **changes):
    r=receipt() if r is None else r
    value=dict(v=1,token=r['token'],launch=LAUNCH,pid=r['pid'],epoch=100.1,elapsed=.1,sequence=1,event='appInit',omittedRecords=0,late=False,
               app={'present':False},product=dict(bundle='com.mango.touchColor',path=APP,executable=r['executable'],reset=True,
                  language='(en)',locale='en_US',suitePresent=True,modalPresent=False,sandboxProbePresent=False))
    value.update(changes);return value

def envelope(value):
    return dict(processID=345,processImagePath=APP+'/Contents/MacOS/TouchColor',eventMessage=observe.PREFIX+json.dumps(value))

def bound():
    r=receipt();r.update(case=observe.CASES[0],result_start=99.,result_end=120.,receipt_sha256='c'*64,receipt_file='screenshots/x.txt');return r

def projection_fixture():
    source={key:SOURCE[key] for key in ('repository','ref','workflow_ref','workflow_file','event_name','sha','run_id')}
    source['attempt']=SOURCE['run_attempt']
    return dict(schema=2,contract=observe.CONTRACT,commands=[],status='unavailable',acceptance=False,source=source,records=[],host_cleanup_confirmed=None,
                raw_bytes=0,omissions=[],budget_seconds=30,elapsed_seconds=.1,reason='no-current-process-receipts')

def completed_commands():
    return [dict(stage=stage,returned=True,exit=0,cleanup_confirmed=True,stdout_bytes=0,stderr_bytes=0,
                 stderr_classification='empty',elapsed_seconds=.1,timely=True)
            for stage in ('source-head','source-clean','query')]


def add_valid_identity(root,fixture):
    group={'testIdentifier':'TouchColorMacUITests/'+observe.CASES[0]+'()',
           'testIdentifierURL':'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+observe.CASES[0],
           'attachments':[]}
    fixture.groups['screenshots'].append(group)
    raw=observe.encode(receipt());name=fixture.add(group,keep.LIFECYCLE_PREFIX+TOKEN+' 1',raw,'.txt',102);fixture.save()
    return name,raw

class IdentityTests(unittest.TestCase):
    def test_exact_export_identity_and_single_public_pid_query(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);exported(root);rows=observe.identities(root)
            self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['xctestPID'])
            command=observe.command(rows);self.assertEqual(command[:4],['/usr/bin/log','show','--style','json'])
            self.assertIn('processID == 345',command[-1]);self.assertIn(TOKEN,command[-1])
            self.assertNotIn('simctl',command);self.assertNotIn('sudo',command)
    def test_wrong_identity_lane_arguments_and_stale_intervals_reject(self):
        variants=[('pid',True),('token','bad'),('ordinal',2),('sandbox',True),('bundle','other'),('applicationPath','/Other.app'),
                  ('executableSHA256','bad'),('xctestPID',345),('started',98),('captured',121),('args',['--ui-test-reset'])]
        for key,value in variants:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as d:
                root=Path(d);r=receipt();r[key]=value;exported(root,r)
                with self.assertRaises(ValueError):observe.identities(root)
    def test_duplicate_linked_oversized_and_wrong_test_exports_fail(self):
        for mode in ['duplicate','linked','oversized','wrong-test']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root=Path(d);f=exported(root);manifest=f.parent/'manifest.json';groups=json.loads(manifest.read_text())
                if mode=='duplicate':groups[0]['attachments']*=2;manifest.write_text(json.dumps(groups))
                if mode=='linked':original=root/'original';f.rename(original);f.symlink_to(original)
                if mode=='oversized':f.write_bytes(b'x'*4097)
                if mode=='wrong-test':groups[0]['testIdentifier']='foreign';manifest.write_text(json.dumps(groups))
                with self.assertRaises(ValueError):observe.identities(root)
    def test_cross_process_launch_bounds(self):
        self.assertEqual(observe.launch_args(observe.CASES[3],2),['--ui-test-reset','-AppleLanguages','(zh-Hans)','-AppleLocale','zh_CN'])
        self.assertEqual(observe.launch_args(observe.CASES[2],1),['--ui-test-reset'])

class ProjectionTests(unittest.TestCase):
    def project(self,values):return observe.project(json.dumps(values).encode(),[bound()])
    def test_real_record_and_silent_gap_have_no_acceptance(self):
        rows=self.project([envelope(event())]);self.assertTrue(rows[0]['app_header_observed']);self.assertFalse(rows[0]['final_observed'])
        gap=self.project([]);self.assertEqual(gap[0]['status'],'observation-gap');self.assertTrue(gap[0]['absence_is_not_proof'])
    def test_wrong_pid_path_uuid_and_event_window_reject(self):
        for key,value in [('pid',346),('token','BBBBBBBB-BBBB-CCCC-DDDD-EEEEEEEEEEEE'),('launch','invalid'),('epoch',99.),
                          ('epoch',121.),('elapsed',-1),('sequence',0),('late',True),('event','activateWindow'),('v',True)]:
            with self.subTest(key=key,value=value),self.assertRaises((ValueError,TypeError)):
                self.project([envelope(event(**{key:value}))])
        wrong=envelope(event());wrong['processImagePath']='/Foreign.app/Contents/MacOS/TouchColor'
        with self.assertRaises(ValueError):self.project([wrong])
    def test_redaction_duplicate_unknown_fields_and_product_flags_reject(self):
        for mode in ['redacted','duplicate','extra','product']:
            rows=[envelope(event())]
            if mode=='redacted':rows[0]['eventMessage']='<private>'
            if mode=='duplicate':rows*=2
            if mode=='extra':v=event();v['windowTitle']='private';rows=[envelope(v)]
            if mode=='product':v=event();v['product']['reset']=1;rows=[envelope(v)]
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.project(rows)
    def test_final_late_record_reports_no_state(self):
        value=event(event='final',sequence=2,elapsed=11.,epoch=111.,late=True);del value['app'];del value['product']
        result=self.project([envelope(value)])[0];self.assertTrue(result['final_observed']);self.assertEqual(result['sequence_gaps'],[1]);self.assertFalse(result['app_header_observed'])
        value['app']={'present':True}
        with self.assertRaises(ValueError):self.project([envelope(value)])
    def test_window_census_is_bounded_and_allowlisted(self):
        window=dict(id=1,number=5,frame=[0,0,960,640],visible=True,miniaturized=False,key=True,main=True,occlusion=2,
                    restorable=True,restorationClass=False,autosaveName=True,sheet=False,workspace=True)
        app=dict(present=True,running=True,active=True,hidden=False,policy=0,count=1,omitted=0,key=1,main=1,windows=[window])
        self.project([envelope(event(app=app))])
        for transform in [lambda a:a.update(count=2),lambda a:a['windows'][0].update(title='private'),lambda a:a['windows'][0].update(frame=[0,0,-1,2])]:
            bad=copy.deepcopy(app);transform(bad)
            with self.assertRaises(ValueError):self.project([envelope(event(app=bad))])
    def test_foreign_launch_nonmonotonic_and_flood_reject(self):
        first=event();second=event(event='census',sequence=2,elapsed=.2,epoch=100.2);del second['product']
        for change in [dict(launch=TOKEN),dict(epoch=100.0),dict(elapsed=.05)]:
            with self.assertRaises(ValueError):self.project([envelope(first),envelope({**second,**change})])
        with self.assertRaises(ValueError):self.project([envelope(first)]*241)
    def test_duplicate_json_and_nonfinite_reject(self):
        with self.assertRaises(ValueError):observe.project(b'[{"processID":345,"processID":345}]',[bound()])
        with self.assertRaises(ValueError):self.project([envelope(event(epoch=float('nan')))])

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.time=0.;self.calls=[]
        self.env=dict(GITHUB_REPOSITORY='100mango/ColorPicker',GITHUB_REF='refs/heads/codex/mac-watch-repair',
            GITHUB_WORKFLOW_REF='100mango/ColorPicker/.github/workflows/mac-watch-repair.yml@refs/heads/codex/mac-watch-repair',
            GITHUB_EVENT_NAME='push',GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',
            TOUCHCOLOR_JOB_PLATFORM='mac',TOUCHCOLOR_EVIDENCE_LIMIT='3000000')
    def run_collect(self,behavior=None,receipts=True):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            if receipts:exported(root)
            def runner(argv,**kwargs):
                self.calls.append((argv,kwargs));self.time+=.1
                if behavior:return behavior(argv,kwargs)
                data=b'a'*40+b'\n' if argv==['git','rev-parse','HEAD'] else b'[]' if argv[:2]==['/usr/bin/log','show'] else b''
                return subprocess.CompletedProcess(argv,0,data,b'')
            return observe.collect(root,self.env,runner,lambda:self.time)
    def test_single_joint_collection_clock_and_scope(self):
        result=self.run_collect();self.assertEqual(result['status'],'observation-only');self.assertFalse(result['acceptance'])
        self.assertEqual(len(self.calls),3);self.assertEqual(self.calls[-1][0][:2],['/usr/bin/log','show'])
        self.assertEqual(len(result['missing_process_receipts']),9)
        self.assertTrue(all(x[1]['seconds']<=26 for x in self.calls));self.assertLess(result['elapsed_seconds'],30)
    def test_no_receipt_stops_before_help_or_query(self):
        result=self.run_collect(receipts=False);self.assertEqual(result['reason'],'no-current-process-receipts');self.assertEqual(len(self.calls),2)
    def test_late_command_stops_without_second_call(self):
        def late(argv,kw):self.time+=27;return subprocess.CompletedProcess(argv,0,b'a'*40+b'\n',b'')
        result=self.run_collect(late);self.assertEqual(result['status'],'unavailable');self.assertEqual(len(self.calls),1)
    def test_capture_failure_cleanup_is_preserved_and_never_retried(self):
        def fail(argv,kw):raise observe.CaptureStopped('timeout',False)
        result=self.run_collect(fail);self.assertFalse(result['host_cleanup_confirmed']);self.assertEqual(len(self.calls),1)
    def test_wrong_source_or_workflow_never_calls_log(self):
        for key,value in [('GITHUB_REF','refs/heads/main'),('GITHUB_WORKFLOW_SHA','b'*40),('TOUCHCOLOR_EVIDENCE_LIMIT','4000000')]:
            with self.subTest(key=key):
                self.setUp();self.env[key]=value;result=self.run_collect();self.assertEqual(result['status'],'unavailable');self.assertEqual(self.calls,[])
    def test_raw_flood_is_unavailable(self):
        def flood(argv,kw):return subprocess.CompletedProcess(argv,0,b'x'*(observe.RAW_LIMIT+1),b'')
        result=self.run_collect(flood);self.assertEqual(result['status'],'unavailable');self.assertEqual(len(self.calls),1)

class RetentionTests(unittest.TestCase):
    def test_diagnostic_fits_after_five_requested_pngs_and_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);Fixture(root);(root/keep.LIFECYCLE_FILE).write_bytes(observe.encode(projection_fixture()))
            result=keep.retain(root,SOURCE);self.assertTrue(result['complete']);self.assertEqual(result['passiveLifecycle']['status'],'retained')
            self.assertEqual(sum(x['status']=='retained' for x in result['requested'].values()),5)
            keep.validate_selection(root,require_complete=True)
            (root/keep.LIFECYCLE_FILE).write_bytes(b'[]\n')
            with self.assertRaises(ValueError):keep.validate_selection(root)
    def test_projection_cannot_displace_five_pngs_and_omission_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture=Fixture(root,image_size=400000)
            (root/'architecture.txt').write_bytes(b'a'*850000)
            raw=observe.encode(projection_fixture());(root/keep.LIFECYCLE_FILE).write_bytes(raw+b' '*(128*1024-len(raw)))
            result=keep.retain(root,SOURCE)
            self.assertTrue(result['complete']);self.assertEqual(result['passiveLifecycle']['status'],'omitted')
            self.assertFalse((root/keep.LIFECYCLE_FILE).exists())
            for name in fixture.images.values():self.assertEqual((root/name).read_bytes(),fixture.raw[name])
            keep.validate_selection(root,require_complete=True)

    def test_combined_identity_and_projection_count_is_independently_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture=Fixture(root)
            name,raw=add_valid_identity(root,fixture)
            projection=observe.encode(projection_fixture());(root/keep.LIFECYCLE_FILE).write_bytes(projection)
            result=keep.retain(root,SOURCE);self.assertEqual(result['passiveLifecycle']['combinedRetainedBytes'],len(raw)+len(projection))
            keep.validate_selection(root)
            report=root/keep.REPORT;changed=json.loads(report.read_bytes());changed['passiveLifecycle']['combinedRetainedBytes']=3;report.write_bytes(keep.encoded(changed))
            with self.assertRaisesRegex(ValueError,'Combined passive'):keep.validate_selection(root)

    def test_oversized_projection_rejected_without_budget_growth(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);Fixture(root);(root/keep.LIFECYCLE_FILE).write_bytes(b'x'*(keep.LIFECYCLE_LIMIT+1))
            with self.assertRaises(ValueError):keep.retain(root,SOURCE)

class GuardIntegrationTests(unittest.TestCase):
    def guard(self,root,**changes):
        env={**os.environ,'GITHUB_SHA':'','GITHUB_OUTPUT':'','TOUCHCOLOR_JOB_PLATFORM':'mac','TOUCHCOLOR_VISION_CASE':'',**changes}
        return subprocess.run([os.sys.executable,str(ROOT/'scripts/validate_evidence.py'),str(root),'3000000'],env=env,capture_output=True,text=True,timeout=5)
    def test_actual_final_guard_accepts_bound_projection_and_rejects_other_lane(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture=Fixture(root);add_valid_identity(root,fixture)
            (root/keep.LIFECYCLE_FILE).write_bytes(observe.encode(projection_fixture()))
            result=keep.retain(root,SOURCE);self.assertEqual(result['passiveLifecycle']['status'],'retained')
            outcome=self.guard(root);self.assertEqual(outcome.returncode,0,outcome.stderr)
            self.assertNotEqual(self.guard(root,TOUCHCOLOR_JOB_PLATFORM='vision').returncode,0)
    def test_actual_final_guard_accepts_explicit_projection_omission(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);Fixture(root,image_size=400000);(root/'architecture.txt').write_bytes(b'a'*850000)
            raw=observe.encode(projection_fixture());(root/keep.LIFECYCLE_FILE).write_bytes(raw+b' '*(128*1024-len(raw)))
            result=keep.retain(root,SOURCE);self.assertEqual(result['passiveLifecycle']['status'],'omitted')
            outcome=self.guard(root);self.assertEqual(outcome.returncode,0,outcome.stderr)
    def test_forged_lifecycle_titles_never_demote_mandatory_findings(self):
        for case in ('testOfficialAccessibilityEmptyAndPopulatedCanvas',observe.CASES[0],'unownedCase'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as d:
                root=Path(d);fixture=Fixture(root)
                group={'testIdentifier':'TouchColorMacUITests/'+case+'()',
                       'testIdentifierURL':'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+case,'attachments':[]}
                fixture.groups['screenshots'].append(group)
                raw=b'Raw mandatory contrast finding: FAILURE\n'+b'x'*140000
                name=fixture.add(group,keep.LIFECYCLE_PREFIX+TOKEN+' 1',raw,'.txt',200);fixture.save()
                result=keep.retain(root,SOURCE);self.assertEqual((root/name).read_bytes(),raw)
                self.assertTrue(result['attachmentInventory'][name]['mandatoryText']);self.assertTrue(result['complete'])
                keep.validate_selection(root,require_complete=True)
                outcome=self.guard(root);self.assertEqual(outcome.returncode,0,outcome.stderr)
    def test_unknown_or_unbound_projection_is_omitted_without_touching_findings(self):
        for change in ('unknown','source','run','extra'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                root=Path(d);fixture=Fixture(root);value=projection_fixture()
                if change=='unknown':value={}
                if change=='source':value['source']['sha']='b'*40
                if change=='run':value['source']['run_id']='2'
                if change=='extra':value['private-data']='never retain'
                (root/keep.LIFECYCLE_FILE).write_bytes(observe.encode(value))
                result=keep.retain(root,SOURCE);self.assertEqual(result['passiveLifecycle']['status'],'omitted')
                self.assertFalse((root/keep.LIFECYCLE_FILE).exists());self.assertTrue(result['complete'])
                self.assertEqual(self.guard(root).returncode,0)
    def test_retained_optional_identity_witness_is_bounded_and_source_scoped(self):
        for field,bad in [('pid',2**31),('ordinal',True),('folder','modal-probe-screenshots'),('sandbox',True),('source_sha','b'*40)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                root=Path(d);fixture=Fixture(root);name,_=add_valid_identity(root,fixture);keep.retain(root,SOURCE)
                manifest=root/'screenshots/manifest.json';groups=json.loads(manifest.read_bytes());item=next(a for g in groups for a in g['attachments'] if a['exportedFileName']==Path(name).name)
                item['retention']['lifecycleIdentity'][field]=bad;manifest.write_bytes(keep.encoded(groups))
                report=root/keep.REPORT;meta=json.loads(report.read_bytes());meta['attachmentInventory'][name]['lifecycleIdentity'][field]=bad;report.write_bytes(keep.encoded(meta))
                with self.assertRaisesRegex(ValueError,'Unproven optional'):keep.validate_selection(root)
    def test_closed_projection_schema_reconstructs_actual_typed_events(self):
        value=projection_fixture();value.update(status='observation-only',host_cleanup_confirmed=True,
             reason='missing-records-and-restoration-notifications-are-not-proof-of-window-cause',records=observe.project(json.dumps([envelope(event())]).encode(),[bound()]))
        value['commands']=completed_commands()
        # Use a real exported filename shape in the synthetic identity.
        value['records'][0]['identity']['receipt_file']='screenshots/'+TOKEN+'.txt'
        observe.validate_projection(observe.encode(value),SOURCE)
        for flag in ('app_header_observed','final_observed','absence_is_not_proof'):
            wrong=copy.deepcopy(value);wrong['records'][0][flag]=1
            with self.assertRaises(ValueError):observe.validate_projection(observe.encode(wrong),SOURCE)
        value['records'][0]['events'][0]['secret']='not an allowed field'
        with self.assertRaises(ValueError):observe.validate_projection(observe.encode(value),SOURCE)

class SourceTests(unittest.TestCase):
    def test_debug_only_hooks_and_no_focus_activation_mutations(self):
        source=(ROOT/'TouchColorMac/TouchColorMacApp.swift').read_text();helper=source.split('@MainActor final class MacPassiveLifecycle',1)[1]
        self.assertTrue(helper.rstrip().endswith('#endif'));self.assertIn('#if DEBUG\nimport OSLog\n#endif',source)
        for forbidden in ['NSApplication.shared','activate(','.unhide(','.orderFront(','.makeKeyAndOrderFront(','.close(','.openWindow(','.setFrame(','.restorationClass =','UserDefaults']:
            self.assertNotIn(forbidden,helper)
        for bound in ['sequence < 23','data.count + 22 <= 4096','final ? 12288 : 8192','windows.prefix(4)','identities.count < 16','[1.0, 5.0, 10.0]']:
            self.assertIn(bound,helper)
        self.assertIn('didFinishRestoringWindowsNotification',helper);self.assertIn('No activation',source)
    def test_no_extra_launch_wait_or_ax_query_in_receipt_helper(self):
        source=(ROOT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text();helper=source.split('private func lifecycleReceipt',1)[1].split('override func tearDownWithError',1)[0]
        for text in ['app.launch()','waitForExistence','AXUIElement','app.windows','app.debugDescription','app.activate','app.buttons']:
            self.assertNotIn(text,helper)
        self.assertIn('xctestPID": NSNull()',helper);self.assertIn('ordinal: 2',helper)
    def test_workflow_has_no_new_job_or_timeout_and_keeps_collection_in_existing_tail(self):
        targeted=(ROOT/'.github/workflows/mac-watch-repair.yml').read_text();canonical=(ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.assertEqual(targeted.count('python3 scripts/mac_passive_lifecycle.py'),1);self.assertNotIn('scripts/mac_passive_lifecycle.py',canonical)
        self.assertLess(targeted.index('scripts/mac_passive_lifecycle.py'),targeted.index('scripts/retain_mac_evidence.py'))
        self.assertIn("--seconds 180 --phase evidence",targeted)
        for text in [targeted,canonical]:self.assertIn('TOUCHCOLOR_MAC_LIFECYCLE|MAC_PASSIVE_LIFECYCLE|com.mango.touchColor.MacLifecycle',text)


class FixedQueryContractTests(CollectionTests):
    def test_actual_fixed_query_is_attempted_without_help_layout(self):
        result=self.run_collect()
        self.assertEqual(result['schema'],2);self.assertEqual(result['contract'],observe.CONTRACT)
        self.assertEqual([row['stage'] for row in result['commands']],['source-head','source-clean','query'])
        self.assertFalse(any('help' in argv for argv,_ in self.calls))
        observe.validate_commands(result)
        self.assertEqual(result['records'][0]['status'],'observation-gap')
        self.assertTrue(result['host_cleanup_confirmed'])

    def query_behavior(self,stdout=b'[]',stderr=b'',exit_code=0,late=False,stopped=None):
        def behavior(argv,kwargs):
            if argv[0]=='git':return subprocess.CompletedProcess(argv,0,b'a'*40+b'\n' if argv[1]=='rev-parse' else b'',b'')
            if stopped:raise observe.CaptureStopped('duration-limit',stopped[0])
            if late:self.time+=27
            return subprocess.CompletedProcess(argv,exit_code,stdout,stderr)
        return behavior

    def test_typed_positive_record_and_unclassified_stderr_are_retained(self):
        result=self.run_collect(self.query_behavior(json.dumps([envelope(event())]).encode(),b'informational tool notice\n'))
        self.assertEqual(result['status'],'observation-only');self.assertTrue(result['records'][0]['app_header_observed'])
        self.assertEqual(result['commands'][-1]['stderr_classification'],'unclassified');observe.validate_commands(result)

    def test_verified_permissions_and_errors_cannot_be_accepted_at_zero_exit(self):
        for raw,classification in [(b'log: Permission denied\n','permission-denied'),(b'Operation not permitted\n','permission-denied'),
                (b'log: error: unknown option\n','verified-error'),(b'log: Unable to open local log store\n','verified-error')]:
            with self.subTest(raw=raw):
                self.setUp();value=self.run_collect(self.query_behavior(stderr=raw))
                self.assertEqual(value['status'],'unavailable');self.assertEqual(value['commands'][-1]['stderr_classification'],classification)
                self.assertTrue(value['commands'][-1]['cleanup_confirmed']);self.assertEqual(len(self.calls),3)
                self.assertEqual(value['records'],[]);observe.validate_commands(value)

    def test_nonzero_unsupported_route_and_foreign_malformed_output_fail_closed(self):
        for output,code in [(b'usage: log show',64),(b'{bad-json',0),(json.dumps([envelope(event(pid=999))]).encode(),0)]:
            with self.subTest(output=output):
                self.setUp();value=self.run_collect(self.query_behavior(output,exit_code=code))
                self.assertEqual(value['status'],'unavailable');self.assertEqual(value['records'],[]);self.assertEqual(len(self.calls),3)

    def test_late_query_and_unknown_cleanup_preserve_no_observation(self):
        value=self.run_collect(self.query_behavior(late=True));self.assertEqual(value['status'],'unavailable')
        self.assertFalse(value['commands'][-1]['timely']);self.assertTrue(value['commands'][-1]['returned'])
        self.assertEqual(value['records'],[]);observe.validate_commands(value)
        self.setUp();value=self.run_collect(self.query_behavior(stopped=(False,)))
        self.assertFalse(value['host_cleanup_confirmed']);self.assertFalse(value['commands'][-1]['cleanup_confirmed'])
        self.assertIsNone(value['commands'][-1]['exit']);self.assertIsNone(value['commands'][-1]['stdout_bytes'])
        self.assertEqual(len(self.calls),3);observe.validate_commands(value)

    def test_query_byte_limit_stops_with_unknown_output_and_confirmed_owned_cleanup(self):
        def runner(argv,kwargs):
            if argv[0]=='git':return subprocess.CompletedProcess(argv,0,b'a'*40+b'\n' if argv[1]=='rev-parse' else b'',b'')
            raise observe.CaptureStopped('byte-limit',True)
        value=self.run_collect(runner)
        self.assertEqual(value['status'],'unavailable');self.assertEqual(value['reason'],'owned-capture-stopped')
        self.assertEqual(len(self.calls),3);self.assertTrue(value['host_cleanup_confirmed'])
        self.assertIsNone(value['commands'][-1]['stdout_bytes']);self.assertEqual(value['raw_bytes'],41)
        observe.validate_commands(value)

    def test_expired_pre_capture_entry_never_starts_command(self):
        ticks=iter([0.,0.,27.,27.,27.,27.]);calls=[]
        with tempfile.TemporaryDirectory() as d:
            value=observe.collect(Path(d),self.env,lambda *a,**kw:calls.append(a),lambda:next(ticks))
        self.assertEqual(calls,[]);self.assertEqual(value['status'],'unavailable')
        self.assertFalse(value['commands'][0]['returned']);self.assertIsNone(value['commands'][0]['cleanup_confirmed'])

    def test_historical_native_help_receipt_is_never_upgraded(self):
        value=json.loads((ROOT/'scripts/fixtures/mac-a6558c-help-unavailable.json').read_bytes())
        self.assertEqual(value['schema'],1);self.assertEqual(value['reason'],'documented-route-unconfirmed')
        self.assertEqual(value['source']['sha'],'a6558c8ffa1cf86b499bcfa00f02f8d7bcb1de2b')
        self.assertEqual(value['records'],[]);self.assertEqual(value['raw_bytes'],2832)
        source={**SOURCE,**value['source'],'run_attempt':value['source']['attempt']}
        with self.assertRaises(ValueError):observe.validate_projection(observe.encode(value),source)

    def test_actual_query_projection_retention_and_final_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture=Fixture(root);add_valid_identity(root,fixture)
            calls=[]
            def runner(argv,**kwargs):
                calls.append(argv)
                data=b'a'*40+b'\n' if argv==['git','rev-parse','HEAD'] else json.dumps([envelope(event())]).encode() if argv[:2]==['/usr/bin/log','show'] else b''
                return subprocess.CompletedProcess(argv,0,data,b'informational notice\n' if argv[0]=='/usr/bin/log' else b'')
            value=observe.collect(root,self.env,runner,lambda:0.)
            self.assertEqual(value['status'],'observation-only');self.assertEqual(len(calls),3)
            source={**SOURCE,**observe.workflow_identity(self.env)}
            observe.validate_projection(observe.encode(value),source)
            (root/keep.LIFECYCLE_FILE).write_bytes(observe.encode(value))
            result=keep.retain(root,source);self.assertTrue(result['complete'])
            self.assertEqual(result['passiveLifecycle']['status'],'retained')
            self.assertEqual(sum(x['status']=='retained' for x in result['requested'].values()),5)
            keep.validate_selection(root,require_complete=True)
            guard=GuardIntegrationTests().guard(root);self.assertEqual(guard.returncode,0,guard.stderr)

    def test_closed_acquisition_fields_reject_old_relabel_and_contradictions(self):
        value=projection_fixture();value['commands']=completed_commands();value['host_cleanup_confirmed']=True
        for kind in ('old','contract','stage','extra','byte','timely','cleanup','exit'):
            wrong=copy.deepcopy(value)
            if kind=='old':wrong['schema']=1
            elif kind=='contract':wrong['contract']='old-help-layout'
            elif kind=='stage':wrong['commands'][2]['stage']='query-all-logs'
            elif kind=='extra':wrong['commands'][2]['raw']='unbounded'
            elif kind=='byte':wrong['raw_bytes']=1
            else:wrong['commands'][0][{'timely':'timely','cleanup':'cleanup_confirmed','exit':'exit'}[kind]]=False if kind!='exit' else 65
            with self.subTest(kind=kind),self.assertRaises(ValueError):observe.validate_projection(observe.encode(wrong),SOURCE)

if __name__=='__main__':unittest.main()
