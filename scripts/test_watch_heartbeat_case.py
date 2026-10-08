"""Actual CLI processes with local fake Apple executables; no Xcode/Simulator/CI."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import yaml
import watch_heartbeat_case as case

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=Path(case.__file__).resolve()
CLI=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(SCRIPT)]
NONCE='F2D612CA-E494-43B8-974B-7918672C9DEB'
PHONE='11111111-1111-4111-8111-111111111111'
WATCH='22222222-2222-4222-8222-222222222222'
PAIR='33333333-3333-4333-8333-333333333333'
FAKE=r'''#!/usr/bin/env python3
import json,os,sys,time,signal
from pathlib import Path
root=Path(os.environ['FAKE_ROOT']);mode=os.environ.get('FAKE_MODE','failed-case');a=sys.argv[1:];tool=Path(sys.argv[0]).name
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps({'tool':tool,'args':a,'pid':os.getpid()})+'\n')
phone='11111111-1111-4111-8111-111111111111';watch='22222222-2222-4222-8222-222222222222';pair='33333333-3333-4333-8333-333333333333'
if tool=='git':
 if a==['rev-parse','HEAD']:print(os.environ['GITHUB_SHA'])
 elif a!=['status','--porcelain=v1','--untracked-files=all']:sys.exit(99)
 sys.exit(0)
if tool=='xcodebuild':
 if a==['-help']:print('-collect-test-diagnostics on-failure|never');sys.exit(0)
 if 'build-for-testing' in a:
  (root/'build-started').write_text(str(os.getpid()))
  if mode in ('slow-build','cancel-build'):time.sleep(30)
  Path(a[a.index('-derivedDataPath')+1]).mkdir()
  sys.exit(0)
 if 'test-without-building' not in a:sys.exit(98)
 (root/'native-started').write_text('1')
 for _ in range(100):
  if (root/'log-started').exists():break
  time.sleep(.01)
 if not (root/'log-started').exists():sys.exit(97)
 print('WATCH_MAIN_ACTOR_SCOPE nonce=F2D612CA-E494-43B8-974B-7918672C9DEB',flush=True)
 if mode=='native-overflow':print('x'*300000,flush=True);time.sleep(10)
 print("Test Case '-[TouchColorWatchUITests.WatchWorkflowTests testTouchCopyEntryTouchAndCrownRemainResponsive]' started.",flush=True)
 time.sleep(30 if mode=='cancel-native' else .25)
 passed=mode=='passed-case'
 print('    t =    39.07s Tap "watch.edit.copy" Button',flush=True)
 print('    t =    39.43s     Wait for com.mango.touchColor.watchkitapp to idle',flush=True)
 if not passed:print('    t =    99.46s         App event loop idle notification not received, will attempt to continue.',flush=True)
 print("Test Case '-[TouchColorWatchUITests.WatchWorkflowTests testTouchCopyEntryTouchAndCrownRemainResponsive]' "+('passed' if passed else 'failed')+' (120.000 seconds).',flush=True)
 print('** TEST EXECUTE '+('SUCCEEDED' if passed else 'FAILED')+' **',flush=True)
 sys.exit(0 if passed else 65)
if tool!='xcrun' or a[0]!='simctl':sys.exit(96)
a=a[1:]
if a==['list','devices','available','-j']:
 print(json.dumps({'devices':{'com.apple.CoreSimulator.SimRuntime.iOS-27-0':[{'name':'iPhone SE (3rd generation)','udid':'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA','deviceTypeIdentifier':'phone-type','isAvailable':True}],
 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0':[{'name':'Apple Watch SE 3 (40mm)','udid':'BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB','deviceTypeIdentifier':'com.apple.CoreSimulator.SimDeviceType.Apple-Watch-SE-3-40mm','isAvailable':True}]}}));sys.exit(0)
if a==['list','pairs','-j']:
 print(json.dumps({'pairs':{pair:{'watch':{'udid':watch},'phone':{'udid':phone},'state':'(active, connected)'}}} if (root/'paired').exists() else {'pairs':{}}));sys.exit(0)
if a[0]=='create':print(phone if '-phone-' in a[1] else watch);sys.exit(0)
if a[0]=='pair':(root/'paired').write_text('1');print(pair);sys.exit(0)
if a[0] in ('boot','bootstatus','unpair','delete','pair_activate'):sys.exit(0)
if a[0]=='shutdown':sys.exit(44 if mode=='cleanup-failure' else 0)
if a[0]=='spawn' and a[2:4]==['log','stream']:
 if a[-1]=='--help':
  print('unsupported' if mode=='unsupported-log-help' else '--style compact --predicate');sys.exit(64)
 (root/'log-started').write_text(str(os.getpid()))
 if mode=='log-exits':sys.exit(1)
 for _ in range(300):
  if (root/'native-started').exists():break
  time.sleep(.01)
 if mode=='log-overflow':print('x'*70000,flush=True)
 elif mode!='missing-events':
  def emit(e,s=0,ms=0):print(f'2026-10-08 09:00:00.123 Df TouchColor[11096:9ded] [com.mango.touchColor.WatchDiagnostics:editor] WATCH_MAIN_ACTOR event={e} case=__WatchWorkflowTests_testTouchCopyEntryTouchAndCrownRemainResponsive_ nonce=F2D612CA-E494-43B8-974B-7918672C9DEB seq={s} elapsed_ms={ms}',flush=True)
  emit('baseline');emit('baseline',1,2000);emit('copy_enter');emit('copy_exit',0,2);emit('copy_beat',1,2000)
 while True:time.sleep(.05)
sys.exit(95)
'''

class Fixture:
    def __init__(self,folder,mode='failed-case',elapsed=0):
        self.root=Path(folder);self.bin=self.root/'bin';self.bin.mkdir();self.out=self.root/'watch-heartbeat-evidence';self.out.mkdir()
        self.path=self.out/case.OUTPUT
        self.path.write_text(json.dumps({'run_id':'12345','run_attempt':'1','requested_sha':'b'*40,'started_monotonic':time.monotonic()-elapsed,'started_epoch':time.time()-elapsed,'state':'bootstrap-only','product_qualified':False}))
        for name in ('git','xcrun','xcodebuild'):
            p=self.bin/name;p.write_text(FAKE);p.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'RUNNER_TEMP':str(self.root),
          'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':'refs/heads/watch-copy-singlecase','GITHUB_SHA':'b'*40,
          'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'12345','FAKE_ROOT':str(self.root),'FAKE_MODE':mode,'PYTHONDONTWRITEBYTECODE':'1'}
    def run(self,*args):return subprocess.run([*CLI,*args],env=self.env,cwd=self.root,text=True,capture_output=True,timeout=15)
    def read(self):return json.loads(self.path.read_text())
    def calls(self):return [json.loads(x) for x in (self.root/'calls.jsonl').read_text().splitlines()]

class ActualCLITests(unittest.TestCase):
    def test_failed_case_keeps_failure_and_heartbeat_in_one_file(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d);r=f.run();self.assertEqual(r.returncode,1,r.stderr);v=f.read()
            self.assertEqual(v['native_case_exit'],65);self.assertEqual(v['case_state'],'failed')
            self.assertTrue(v['xctest_idle_notification_missing']);self.assertEqual(v['xctest_copy_tap_seconds'],[39.07]);self.assertEqual(v['xctest_idle_notification_missing_seconds'],[99.46])
            self.assertEqual(v['heartbeat']['pid'],11096);self.assertEqual(v['heartbeat']['copy_mainactor_samples'],1)
            self.assertFalse(v['product_qualified']);self.assertEqual(len(v['device_cleanup']),5)
            self.assertTrue(v['oslog_capture']['complete']);self.assertFalse(v['cleanup_unconfirmed'])
            self.assertEqual(list(f.out.iterdir()),[f.path]);self.assertLess(f.path.stat().st_size,65536)
    def test_single_pass_record_does_not_qualify_product_release(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'passed-case');r=f.run();self.assertEqual(r.returncode,0,r.stderr);v=f.read()
            self.assertEqual(v['state'],'case-passed-observation-retained');self.assertFalse(v['product_qualified'])
            self.assertTrue(v['xctest_idle_wait_logged']);self.assertFalse(v['xctest_idle_notification_missing'])
    def test_real_cli_uses_one_case_never_300_and_prestarted_stream(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d);f.run();v=f.read();calls=f.calls()
            tests=[x for x in calls if x['tool']=='xcodebuild' and 'test-without-building' in x['args']]
            self.assertEqual(len(tests),1);a=tests[0]['args']
            self.assertEqual([x for x in a if x.startswith('-only-testing:')],['-only-testing:'+case.CASE])
            self.assertEqual(a[a.index('-collect-test-diagnostics')+1],'never')
            self.assertEqual(a[a.index('-default-test-execution-time-allowance')+1],'120')
            self.assertEqual(a[a.index('-maximum-test-execution-time-allowance')+1],'240')
            self.assertNotIn('-quiet',a)
            native=next(x for x in v['stages'] if x['label']=='native-case');self.assertEqual(native['seconds_limit'],300)
            self.assertLessEqual(v['oslog_capture']['started_at'],v['native_started_at'])
            self.assertFalse(any('Release' in x['args'] or 'xcresulttool' in x['args'] or 'sample' in x['args'] for x in calls))
    def test_oslog_byte_limit_stops_owned_native_and_preserves_unknown_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'log-overflow');r=f.run();v=f.read();self.assertEqual(r.returncode,1)
            self.assertTrue(v['oslog_capture']['byte_limit_hit']);self.assertTrue(v['oslog_capture']['process_group_gone'])
            self.assertEqual(v['heartbeat']['state'],'unavailable');self.assertLessEqual(v['oslog_capture']['bytes'],65536)
    def test_native_byte_limit_is_not_product_pass(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'native-overflow');r=f.run();v=f.read();self.assertEqual(r.returncode,1)
            stage=next(x for x in v['stages'] if x['label']=='native-case');self.assertTrue(stage['byte_limit_hit'])
            self.assertTrue(stage['process_group_gone']);self.assertFalse(stage['output_complete']);self.assertEqual(v['case_state'],'unconfirmed')
    def test_missing_probe_records_do_not_establish_deadlock(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'missing-events');f.run();v=f.read();self.assertEqual(v['heartbeat']['state'],'not-observed')
            self.assertFalse(v['heartbeat']['deadlock_established'])
    def test_unsupported_log_help_does_not_start_native_case(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'unsupported-log-help');f.run();v=f.read()
            self.assertEqual(v['failure_reason'],'log-stream-cli-not-supported');self.assertFalse((f.root/'native-started').exists())
            self.assertEqual(len(v['device_cleanup']),5)
    def test_device_cleanup_failure_preserves_unknown_and_stops_chain(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'cleanup-failure');f.run();v=f.read()
            self.assertTrue(v['device_cleanup_unconfirmed']);self.assertEqual(len(v['device_cleanup']),1)
            self.assertFalse(v['device_cleanup'][0]['confirmed'])
    def test_actual_shared_deadline_exhausts_before_new_native_window(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,elapsed=899);r=f.run();v=f.read();self.assertEqual(r.returncode,1)
            self.assertFalse((f.root/'native-started').exists())
            self.assertIn(v.get('failure_reason'),('original-clock-exhausted','full-native-window-unavailable'))
    def test_actual_child_timeout_cleans_owned_group(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'slow-build',elapsed=894);r=f.run();v=f.read();self.assertEqual(r.returncode,1)
            stage=next(x for x in v['stages'] if x['label']=='debug-build-for-testing')
            self.assertTrue(stage['timed_out']);self.assertTrue(stage['process_group_gone']);self.assertFalse(v['cleanup_unconfirmed'])
    def test_actual_sigterm_keeps_cancelled_state_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'cancel-build');p=subprocess.Popen(CLI,env=f.env,cwd=f.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                end=time.monotonic()+5
                while not (f.root/'build-started').exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue((f.root/'build-started').exists());child=int((f.root/'build-started').read_text())
                p.send_signal(signal.SIGTERM);p.communicate(timeout=8);v=f.read()
                self.assertEqual(v['cancellation'],signal.SIGTERM);self.assertFalse(v['cleanup_unconfirmed'])
                with self.assertRaises(ProcessLookupError):os.kill(child,0)
            finally:
                if p.poll() is None:p.kill()
                p.communicate(timeout=3)
    def test_actual_sigterm_stops_both_native_and_log_stream(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'cancel-native');p=subprocess.Popen(CLI,env=f.env,cwd=f.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                end=time.monotonic()+6
                while not (f.root/'native-started').exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue((f.root/'native-started').exists())
                p.send_signal(signal.SIGTERM);p.communicate(timeout=8);v=f.read()
                self.assertEqual(v['cancellation'],signal.SIGTERM)
                self.assertTrue(v['oslog_capture']['process_group_gone']);self.assertFalse(v['cleanup_unconfirmed'])
                native=next(x for x in f.calls() if x['tool']=='xcodebuild' and 'test-without-building' in x['args'])
                for pid in (native['pid'],int((f.root/'log-started').read_text())):
                    with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            finally:
                if p.poll() is None:p.kill()
                p.communicate(timeout=3)
    def test_log_stream_early_exit_cannot_qualify_case(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d,'log-exits');r=f.run();v=f.read()
            self.assertEqual(r.returncode,1);self.assertNotEqual(v['state'],'case-passed-observation-retained')
            self.assertTrue(v['oslog_capture']['process_group_gone'])
    def test_cli_rejects_stale_bootstrap_without_spawning(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d);v=f.read();v['run_id']='old-run';f.path.write_text(json.dumps(v))
            r=f.run();self.assertEqual(r.returncode,1);self.assertFalse((f.root/'calls.jsonl').exists())
    def test_cli_rejects_extra_arguments_without_spawning(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d);r=f.run('--unexpected');self.assertEqual(r.returncode,2)
            self.assertFalse((f.root/'calls.jsonl').exists())

class BoundaryTests(unittest.TestCase):
    def test_log_spawn_cost_cannot_shorten_and_start_a_fresh_native_window(self):
        clock=[690.0]
        class Delayed:
            def __init__(self,*args):self.record={}
            def start(self):clock[0]+=10
        c=case.Controller.__new__(case.Controller);c.work_deadline=1000;c.watch=WATCH;c.check=lambda:None;c.report={}
        with patch.object(case,'LogObserver',Delayed),patch.object(case.time,'monotonic',side_effect=lambda:clock[0]),self.assertRaisesRegex(case.ObservationFailed,'full-native-window-unavailable'):
            c.observe()
    def test_actual_log_observer_deadline_is_recorded_and_stopped(self):
        observer=case.LogObserver([sys.executable,'-c','import time;time.sleep(5)'],.04,lambda:None)
        observer.start();pid=observer.process.pid
        try:
            time.sleep(.06)
            with self.assertRaisesRegex(RuntimeError,'oslog-duration-limit'):observer.drain()
        finally:observer.finish()
        self.assertTrue(observer.record['timed_out']);self.assertTrue(observer.record['process_group_gone'])
        self.assertFalse(observer.record['complete'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
    def test_actual_workflow_source_admission_and_rejections(self):
        w=yaml.safe_load((ROOT/'.github/workflows/watch-focused-case.yml').read_text())
        code=next(x for x in w['jobs']['watch']['steps'] if x.get('id')=='source')['run'].split("python3 - <<'PYTHON'\n",1)[1].split('\nPYTHON',1)[0]
        mutations=[None,'parent','extra-path','dirty','attempt','forced','workflow-sha']
        for mutation in mutations:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                f=Fixture(d);event={'created':False,'deleted':False,'forced':mutation=='forced'}
                event_path=f.root/'event.json';event_path.write_text(json.dumps(event))
                env={**f.env,'GITHUB_EVENT_NAME':'push','GITHUB_EVENT_PATH':str(event_path),
                     'GITHUB_WORKFLOW_SHA':'c'*40 if mutation=='workflow-sha' else 'b'*40,
                     'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/.github/workflows/watch-focused-case.yml@refs/heads/watch-copy-singlecase'}
                if mutation=='attempt':env['GITHUB_RUN_ATTEMPT']='2'
                def git(args,**kw):
                    a=args[1:]
                    if a==['rev-parse','HEAD']:return 'b'*40
                    if a==['rev-list','--parents','-n','1','HEAD']:return 'b'*40+' '+('a'*40 if mutation=='parent' else case.BASE)
                    if a==['status','--porcelain=v1','--untracked-files=all']:return '?? unexpected' if mutation=='dirty' else ''
                    if a==['diff','--name-status','--no-renames',case.BASE,'HEAD','--']:return '\n'.join(case.CHANGES+(['M\tUnexpected.swift'] if mutation=='extra-path' else []))
                    if a==['rev-parse','HEAD^{tree}']:return 'd'*40
                    raise AssertionError(a)
                with patch.dict(os.environ,env),patch('subprocess.check_output',side_effect=git):
                    if mutation:
                        with self.assertRaises(RuntimeError):exec(compile(code,'workflow-source','exec'),{})
                    else:
                        exec(compile(code,'workflow-source','exec'),{})
                        self.assertEqual(f.read()['source_admission']['parent'],case.BASE)
    def test_failed_observer_spawn_is_not_confirmed_stopped(self):
        observer=case.LogObserver(['/not/a/program'],1,lambda:None)
        with self.assertRaises(FileNotFoundError):observer.start()
        observer.finish();self.assertFalse(observer.record['process_group_gone'])
    def test_observer_unknown_group_and_cancel_are_retained(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d);c=case.Controller.__new__(case.Controller)
            c.observer=type('Unknown',(),{'record':{'process_group_gone':False},'finish':lambda s:None})()
            c.report={};c.unknown=False;c.cancelled=None;c.devices_uncertain=False;c.owned=[]
            c.cleanup();self.assertTrue(c.unknown);self.assertIn('device_cleanup_skipped',c.report)
    def test_cleanup_exception_still_writes_uncertainty(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fixture(d)
            with patch.dict(os.environ,f.env),patch.object(case.Controller,'prepare',side_effect=case.ObservationFailed('cancelled')),patch.object(case.Controller,'cleanup',side_effect=OSError('not public')):
                c=case.Controller();self.assertEqual(c.execute(),1)
            v=f.read();self.assertTrue(v['cleanup_unconfirmed']);self.assertEqual(v['cleanup_error_type'],'OSError')
            self.assertNotIn('not public',f.path.read_text())
    def test_workflow_has_one_job_one_artifact_and_no_heavy_collector(self):
        w=yaml.safe_load((ROOT/'.github/workflows/watch-focused-case.yml').read_text());self.assertEqual(list(w['jobs']),['watch'])
        job=w['jobs']['watch'];self.assertEqual(job['timeout-minutes'],20)
        text=json.dumps(w);self.assertNotIn('on-failure',text);self.assertNotIn('watch_native_diagnostics',text);self.assertNotIn('xcresulttool',text)
        uploads=[s for s in job['steps'] if str(s.get('uses','')).startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads),1);self.assertTrue(uploads[0]['with']['path'].endswith('/watch-heartbeat-evidence.json'))
    def test_source_admission_uses_exact_new_base_and_seven_paths(self):
        self.assertEqual(case.BASE,'9c377452c9bba89fb4919e224491a2cd5d8c29a7');self.assertEqual(len(case.CHANGES),7)
        self.assertEqual(case.CHANGES,sorted(case.CHANGES))
    def test_real_evidence_validation_rejects_extra_oversized_and_promoted_files(self):
        w=yaml.safe_load((ROOT/'.github/workflows/watch-focused-case.yml').read_text())
        code=next(x for x in w['jobs']['watch']['steps'] if x.get('id')=='evidence')['run'].split("python3 - <<'PYTHON'\n",1)[1].split('\nPYTHON',1)[0]
        for mutation in (None,'extra','oversize','promoted','symlink','stale'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                f=Fixture(d)
                if mutation=='stale':
                    v=f.read();v['run_id']='other';f.path.write_text(json.dumps(v))
                elif mutation=='extra':(f.out/'raw.log').write_text('forbidden')
                elif mutation=='oversize':f.path.write_bytes(b'x'*65537)
                elif mutation=='promoted':f.path.write_text('{"product_qualified":true}')
                elif mutation=='symlink':
                    target=f.root/'data.json';target.write_bytes(f.path.read_bytes());f.path.unlink();f.path.symlink_to(target)
                with patch.dict(os.environ,f.env):
                    if mutation:
                        with self.assertRaises(RuntimeError):exec(compile(code,'evidence-step','exec'),{})
                    else:exec(compile(code,'evidence-step','exec'),{})
    def test_real_final_gate_preserves_runtime_failure_even_with_observation_state(self):
        w=yaml.safe_load((ROOT/'.github/workflows/watch-focused-case.yml').read_text())
        code=w['jobs']['watch']['steps'][-1]['run'].split("python3 - <<'PYTHON'\n",1)[1].split('\nPYTHON',1)[0]
        for outcome,state in [('failure','case-passed-observation-retained'),('success','failed-or-incomplete')]:
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as d:
                f=Fixture(d);f.path.write_text(json.dumps({'state':state,'product_qualified':False}))
                with patch.dict(os.environ,{**f.env,'RUNTIME_OUTCOME':outcome,'EVIDENCE_OUTCOME':'success'}),self.assertRaises(SystemExit):
                    exec(compile(code,'final-step','exec'),{})
    def test_workflow_inline_python_syntax_and_fixed_budget(self):
        w=yaml.safe_load((ROOT/'.github/workflows/watch-focused-case.yml').read_text())
        for step in w['jobs']['watch']['steps']:
            script=step.get('run','')
            if "python3 - <<'PYTHON'\n" in script:
                code=script.split("python3 - <<'PYTHON'\n",1)[1].split('\nPYTHON',1)[0];compile(code,step['name'],'exec')
        self.assertEqual(case.NATIVE_SECONDS,300);self.assertEqual(case.WORK_SECONDS,900);self.assertEqual(case.TOTAL_SECONDS,1020)

if __name__=='__main__':unittest.main()
