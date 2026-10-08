"""Synthetic live-observer tests; no Apple command or real process is sampled."""
import ast
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import watch_live_sample as d
from test_watch_xcresult_stack import inputs, DEVICE, PHONE, SHA

EPOCH = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc).timestamp()
START = "Test Case '-[" + d.CASE_LOG + "]' started.\n"
CREATE = 'WATCH_CREATE_ENTRY_RESPONSE touchFocusedCrown=true buttons=true\n'
CONTAINER_HELP = (b"Print the path of the installed app's container\n"
                  b'Usage: simctl get_app_container <device> <app bundle identifier> [<container>]\n'
                  b'app                 The .app bundle\n')
def event(seconds, message): return '    t = %7.2fs %s\n' % (seconds, message)
COPY = [event(49.7, 'Tap "watch.edit.copy" Button'), event(49.7, 'Wait for ' + d.APP + ' to idle'),
        event(49.7, 'Find the "watch.edit.copy" Button'),
        event(49.72, 'Check for interrupting elements affecting "watch.edit.copy" Button'),
        event(49.76, 'Synthesize event'), event(50.06, 'Wait for ' + d.APP + ' to idle')]

def arm(trigger, clock, lines=None):
    trigger.record(START); trigger.record(CREATE)
    clock[0] += 50.06
    for line in COPY if lines is None else lines: trigger.record(line)
    clock[0] += 5

def stack(executable, when, pid=321):
    date = dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f +0000')
    return (f'Process: TouchColor [{pid}]\nPath: {executable}\nIdentifier: {d.APP}\nDate/Time: {date}\n'
            'Call graph:\n    80 Thread_123 DispatchQueue_1: com.apple.main-thread (serial)\n'
            '    + 80 main (in TouchColor) + 4 [0x1234]\n'
            '    + 80 candidateFrame (in SwiftUI) + 8 [0x1238]\n'
            '    80 Thread_124 unrelated queue\n    + 80 PRIVATE_OTHER_THREAD (in TouchColor) [0x9999]\n'
            'Binary Images:\nPRIVATE_BINARY_INVENTORY\n').encode()

class Fixture:
    def __init__(self, directory, mutation=None):
        self.root = Path(directory); self.clock = [600.0]; self.calls = []; self.mutation = mutation
        evidence = self.root/'watch-focused-evidence'; evidence.mkdir()
        (evidence/'report.json').write_text(json.dumps({'started_monotonic': 0}))
        tools = self.root/d.TOOLS; tools.mkdir(); (tools/d.IDENTITY).write_bytes(b'synthetic-helper')
        state = {'phase': 'preflight-verified', 'calls': 3, 'seconds_spent': 1, 'attempts': 0,
                 'identity_binary_sha256': hashlib.sha256(b'synthetic-helper').hexdigest(),
                 'command_results': [{'state': 'synthetic-preflight'}] * 3}
        (self.root/d.STATE).write_text(json.dumps(state))
        folder = self.root/'Library/Developer/CoreSimulator/Devices'/DEVICE/'data/Containers/Bundle/Application/33333333-3333-4333-8333-333333333333/TouchColor.app'
        folder.mkdir(parents=True)
        (folder/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': d.APP, 'CFBundleExecutable': 'TouchColor'}))
        self.container = folder; self.executable = str(folder/'TouchColor')
        self.runtime, self.source = inputs()
        self.command = self.runtime['stages'][0]['command']
        self.runtime['stages'][0].update(started_at=dt.datetime.fromtimestamp(EPOCH-10,dt.timezone.utc).isoformat(),finished_at=dt.datetime.fromtimestamp(EPOCH+130,dt.timezone.utc).isoformat())
        self.before = {'pid': 321, 'uid': os.geteuid(), 'start_sec': int(EPOCH+1), 'start_usec': 123,
                       'executable_path': self.executable}
        self.identity_reads = 0

    def wall(self): return EPOCH + self.clock[0] - 600
    def runner(self, command, **options):
        self.calls.append((command, options)); data = b''
        if command[:3] == ['xcrun', 'simctl', 'spawn']:
            data = ('2026-10-08 00:00:01.000 Df TouchColor[321:x] [com.mango.touchColor.WatchDiagnostics:editor] WATCH_EDITOR appear case=' + d.CASE + ' visible=true\n').encode()
        elif command[:3] == ['xcrun', 'simctl', 'get_app_container']: data = (str(self.container)+'\n').encode()
        elif command[0] == str(self.root/d.TOOLS/d.IDENTITY):
            self.identity_reads += 1; data = json.dumps(self.before).encode()
        elif '--bounded-sample' in command:
            Path(command[-1]).write_bytes(stack(self.executable, self.wall()))
        else: raise AssertionError('Unexpected command: ' + repr(command))
        result = subprocess.CompletedProcess(command, 0, data, b'')
        if self.mutation: result = self.mutation(self, command, result)
        self.clock[0] += 0.01
        return result

    def live(self):
        return d.LiveSample(self.runtime, self.command, {'udid': DEVICE}, now=lambda: self.clock[0], wall=self.wall, runner=self.runner)

class LiveTests(unittest.TestCase):
    def test_exact_successful_container_help_accepts_stderr_without_broadening_other_operations(self):
        command=['xcrun','simctl','help','get_app_container']
        for stream in ('stdout','stderr'):
            report={'operation':'container-help'}
            result=subprocess.CompletedProcess(command,0,CONTAINER_HELP if stream=='stdout' else b'',CONTAINER_HELP if stream=='stderr' else b'')
            budget=d.Budget(report,0,d.observed_capture(report,lambda *a,**k:result),now=lambda:1)
            raw=budget.run(command,cap=8192)
            self.assertEqual(raw,CONTAINER_HELP);d.qualify_container_help(raw)
            if stream=='stderr':self.assertEqual(report['command_results'][0]['container_help_stream'],'stderr')
        for operation,other in (('identity-before',command),('one-owned-app-sample',command),
                                ('container-help',['xcrun','simctl','get_app_container','device','bundle','app'])):
            report={'operation':operation}
            result=subprocess.CompletedProcess(other,0,b'',CONTAINER_HELP)
            budget=d.Budget(report,0,d.observed_capture(report,lambda *a,**k:result),now=lambda:1)
            with self.assertRaises(ValueError):budget.run(other,cap=8192)

    def test_container_help_nonzero_errors_ambiguous_streams_and_oversize_fail_closed(self):
        command=['xcrun','simctl','help','get_app_container']
        for code,stdout,stderr in ((1,b'',CONTAINER_HELP),(0,b'other',CONTAINER_HELP),
             (0,b'',CONTAINER_HELP+b'Error: unknown option\n'),(0,b'',b'Operation not permitted'),
             (0,b'',CONTAINER_HELP+b'x'*8192),(0,b'',b'Usage: a different operation')):
            report={'operation':'container-help'}
            result=subprocess.CompletedProcess(command,code,stdout,stderr)
            budget=d.Budget(report,0,d.observed_capture(report,lambda *a,**k:result),now=lambda:1)
            with self.assertRaises(ValueError):budget.run(command,cap=8192)
            self.assertEqual(report['calls'],1)

    def test_sample_only_bounded_progress_stderr_exception_keeps_all_evidence_gates(self):
        for mode in ('progress','permission','usage','error-stdout','nonzero','oversize','missing-file'):
            def mutate(f,command,result):
                if '--bounded-sample' in command:
                    result.stderr=b'Sampling process 321; processing symbols.\n'
                    if mode=='permission':result.stderr=b'Operation not permitted'
                    if mode=='usage':result.stderr=b'Usage: sample pid'
                    if mode=='error-stdout':result.stdout=b'Error: unable to sample'
                    if mode=='nonzero':result.returncode=1
                    if mode=='oversize':result.stderr=b'x'*8193
                    if mode=='missing-file':Path(command[-1]).unlink()
                return result
            with self.subTest(mode=mode):
                report,fixture=self.exercise(mutate)
                self.assertEqual('main_thread' in report,mode=='progress')
                self.assertEqual(sum('--bounded-sample' in command for command,options in fixture.calls),1)
                self.assertNotIn('processing symbols',json.dumps(report))
                if mode=='progress':self.assertTrue(report['command_results'][-2]['bounded_sample_status_accepted'])
        report={'operation':'identity-before'}
        runner=d.observed_capture(report,lambda command,**options:subprocess.CompletedProcess(command,0,b'{}',b'progress'))
        budget=d.Budget(report,0,runner,now=lambda:1)
        with self.assertRaises(ValueError):budget.run(['identity-only'],cap=8192)

    def test_preflight_keeps_actual_unsupported_manual_and_sdk_error(self):
        manual=b'SAMPLE\nSYNOPSIS\nsample pid duration interval [-file filename]\nDESCRIPTION\nDuration in seconds; interval in milliseconds.\n-file filename\nWrite output report to file.\n'
        for mode in ('valid', 'unsupported-manual', 'unsupported-sdk'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,RUNNER_TEMP=directory):
                root=Path(directory);out=root/'watch-focused-evidence';out.mkdir()
                (out/'report.json').write_text(json.dumps({'started_monotonic':d.time.monotonic()}))
                calls=[]
                def runner(command,**options):
                    calls.append(command)
                    if command[:2]==['/usr/bin/man','1']:
                        return subprocess.CompletedProcess(command,0,b'unsupported actual manual' if mode=='unsupported-manual' else manual,b'')
                    if command[:3]==['xcrun','simctl','help']:
                        return subprocess.CompletedProcess(command,0,b'',CONTAINER_HELP)
                    if mode=='unsupported-sdk':return subprocess.CompletedProcess(command,1,b'',b'installed SDK declaration unavailable')
                    Path(command[-1]).write_bytes(b'synthetic binary');return subprocess.CompletedProcess(command,0,b'',b'')
                with patch.object(d,'capture',runner):
                    if mode=='valid':d.preflight()
                    else:
                        with self.assertRaises(ValueError):d.preflight()
                report=json.loads((out/d.REPORT).read_bytes())
                self.assertEqual(len(calls),1 if mode=='unsupported-manual' else 3)
                if mode=='valid':self.assertEqual(report['phase'],'preflight-verified')
                else:
                    self.assertEqual(report['phase'],'unavailable');self.assertFalse((root/d.TOOLS).exists())
                if mode=='unsupported-manual':self.assertEqual(report['sample_manual']['text'],'unsupported actual manual')
                if mode=='unsupported-sdk':self.assertIn('SDK declaration',report['command_results'][-1]['preflight_stderr_prefix'])

    def test_finalization_requires_source_case_pid_and_all_owned_cleanup(self):
        for mode in ('valid','source','pid','owned-cleanup','native-cancel','passed','sample-time'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,RUNNER_TEMP=directory,GITHUB_SHA=SHA):
                fixture=Fixture(directory);live=fixture.live();arm(live.trigger,fixture.clock);live.service()
                before=dict(fixture.source);after=dict(before);runtime=copy.deepcopy(fixture.runtime)
                if mode=='source':after['sha']='b'*40
                if mode=='pid':runtime['watch_editor_lifecycle']['processes'][0]['pid']=999
                if mode=='owned-cleanup':runtime['stages'].pop()
                if mode=='native-cancel':runtime['stages'][0]['raw_exit']=-15
                if mode=='passed':runtime['result']='passed'
                if mode=='sample-time':runtime['stages'][0]['finished_at']=dt.datetime.fromtimestamp(EPOCH+1,dt.timezone.utc).isoformat()
                out=fixture.root/'watch-focused-evidence'
                (out/'source-before.json').write_text(json.dumps(before));(out/'source-after.json').write_text(json.dumps(after))
                path=fixture.root/'build/watch-runtime';path.mkdir(parents=True);(path/'runtime.json').write_text(json.dumps(runtime))
                old=Path.cwd()
                try:
                    os.chdir(fixture.root)
                    with patch.object(d.time,'monotonic',lambda:fixture.clock[0]):d.finalize()
                finally:os.chdir(old)
                result=json.loads((out/d.REPORT).read_bytes())
                self.assertEqual('main_thread' in result,mode=='valid')
                self.assertTrue(result['tool_cleanup_confirmed'])
                self.assertFalse((fixture.root/d.STATE).exists());self.assertFalse((fixture.root/d.TOOLS).exists())

    def test_raw_cleanup_failure_prevents_publication_and_latches_unknown(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,RUNNER_TEMP=directory):
            fixture=Fixture(directory);live=fixture.live();arm(live.trigger,fixture.clock)
            original=tempfile.TemporaryDirectory.cleanup
            def cleanup(folder):
                if Path(folder.name).name.startswith('watch-stack-'):raise PermissionError('synthetic cleanup refusal')
                return original(folder)
            with patch.object(tempfile.TemporaryDirectory,'cleanup',cleanup),self.assertRaises(PermissionError):live.service()
            self.assertTrue(fixture.runtime['cleanup_unconfirmed']);self.assertFalse(live.report['raw_cleanup_confirmed'])
            self.assertNotIn('main_thread',live.report)

    def test_malformed_pending_state_still_cleans_host_tool_and_retains_no_frames(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,RUNNER_TEMP=directory):
            fixture=Fixture(directory)
            (fixture.root/d.STATE).write_bytes(b'{invalid')
            d.finalize()
            report=json.loads((fixture.root/'watch-focused-evidence'/d.REPORT).read_bytes())
            self.assertEqual(report['phase'],'unavailable')
            self.assertNotIn('main_thread',report)
            self.assertTrue(report['tool_cleanup_confirmed'])
            self.assertFalse((fixture.root/d.TOOLS).exists())
            self.assertFalse((fixture.root/d.STATE).exists())

    def test_native_owned_setup_failures_and_cancellation_restore_handlers(self):
        source=Path(d.__file__).with_name('test_extra_platforms.py').read_text()
        node=next(item for item in ast.parse(source).body if isinstance(item,ast.FunctionDef) and item.name=='run')
        module=ast.Module(body=[node],type_ignores=[]);code=compile(module,'owned-native-run','exec')
        for mode in ('report-write','print','thread-start','spawn-unknown','cancel-after-spawn','cancel-during-restore','reader-error','cleanup-unknown'):
            with tempfile.TemporaryDirectory() as directory:
                stopped=[];finished=[];report={'sha':SHA,'stages':[]};previous=signal.getsignal(signal.SIGTERM)
                class Live:
                    def __init__(self,*args):self.trigger=types.SimpleNamespace(invalidate=lambda reason:None)
                    def record(self,line):
                        if mode=='reader-error':raise ValueError('synthetic reader error')
                    def service(self):raise AssertionError('no live command expected')
                    def finish(self):finished.append(True)
                class Process:
                    args=['synthetic-native'];pid=12345
                    def __init__(self):self.stdout=io.StringIO('line\n' if mode=='reader-error' else '')
                    def wait(self,timeout):return 65
                    def poll(self):return 65
                process=Process()
                def spawn(*args,**kwargs):
                    if mode=='spawn-unknown':raise OSError('synthetic unknown spawn')
                    if mode=='cancel-after-spawn':os.kill(os.getpid(),signal.SIGTERM)
                    return process
                def output(*args,**kwargs):
                    if mode=='print' and args[0]=='NATIVE_COMMAND_STARTED':raise BrokenPipeError('synthetic output refusal')
                original_write=Path.write_text;writes=[0]
                def write(path,*args,**kwargs):
                    writes[0]+=1
                    if mode=='report-write' and writes[0]==2:raise OSError('synthetic report refusal')
                    return original_write(path,*args,**kwargs)
                real_thread=threading.Thread
                def thread(*args,**kwargs):
                    item=real_thread(*args,**kwargs)
                    if mode=='thread-start':item.start=lambda:(_ for _ in ()).throw(RuntimeError('synthetic reader start refusal'))
                    return item
                budget=types.ModuleType('job_budget');budget.enabled_budget=lambda:None;budget.fail_record=lambda *a,**k:None;budget.BudgetExhausted=RuntimeError
                class Signals(d.NativeSignals):
                    def restore(self):
                        if mode=='cancel-during-restore':os.kill(os.getpid(),signal.SIGTERM)
                        super().restore()
                env={'report':report,'out':Path(directory),'kind':'watch','device':{'udid':DEVICE},'LiveSample':Live,
                     'NativeSignals':Signals,'NativeCancelled':d.NativeCancelled,'wait_native':d.wait_native,
                     'subprocess':types.SimpleNamespace(Popen=spawn,PIPE=subprocess.PIPE,STDOUT=subprocess.STDOUT,TimeoutExpired=subprocess.TimeoutExpired),
                     'datetime':dt,'time':d.time,'json':json,'threading':types.SimpleNamespace(Event=threading.Event,Thread=thread),
                     're':__import__('re'),'WATCH_UI_BUNDLE':'build/watch-ui.xcresult','WatchCaseLifecycle':lambda:types.SimpleNamespace(record=lambda line:None,report={}),
                     'watch_frames':types.SimpleNamespace(record=lambda line:None),'stop_group':lambda p,**kwargs:(stopped.append(p.pid) or mode!='cleanup-unknown'),'print':output}
                exec(code,env)
                with patch.dict(sys.modules,job_budget=budget),patch.object(Path,'write_text',write):
                    if mode in ('reader-error','cleanup-unknown'):
                        self.assertEqual(env['run'](['xcodebuild','test-without-building','-resultBundlePath','build/watch-ui.xcresult'],2,required=False),124)
                    else:
                        with self.assertRaises(Exception):env['run'](['xcodebuild','test-without-building','-resultBundlePath','build/watch-ui.xcresult'],2,required=False)
                self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
                self.assertEqual(len(stopped),0 if mode=='spawn-unknown' else 1)
                self.assertTrue(finished)
                self.assertIsNone(report['active_command'])
                if mode in ('cancel-after-spawn','cancel-during-restore'):self.assertTrue(report['native_cancelled'])
                if mode in ('spawn-unknown','reader-error','cleanup-unknown'):self.assertTrue(report['cleanup_unconfirmed'])

    def test_only_post_synthesis_idle_claims_exactly_once(self):
        clock = [0.0]; trigger = d.Trigger(lambda: clock[0], lambda: EPOCH+clock[0])
        trigger.record(START); trigger.record(CREATE)
        for line in COPY[:-1]: trigger.record(line)
        clock[0] = 55; self.assertIsNone(trigger.claim())
        trigger.record(COPY[-1]); clock[0] += 4.99; self.assertIsNone(trigger.claim())
        clock[0] += .01; self.assertIsNotNone(trigger.claim()); self.assertIsNone(trigger.claim())

    def test_false_foreign_duplicate_split_and_regressing_markers_never_claim(self):
        sequences = [COPY[:1]+[event(49.7, 'Tap "other" Button')]+COPY[1:], COPY[:3]+[event(49.6, 'Find the "watch.edit.copy" Button')]+COPY[3:],
                     COPY[:4]+[event(49.8, 'Synthesize event')]+[event(49.81, 'Tap "other" Button')]+COPY[-1:],
                     COPY+COPY, [COPY[0][:20], COPY[0][20:]]+COPY[1:],
                     COPY+["Test Case '-[ForeignTests testOther]' started.\n"], COPY+[event(51, 'Find the "Create Color" NavigationBar')]]
        for lines in sequences:
            clock = [0.0]; trigger = d.Trigger(lambda: clock[0], lambda: EPOCH+clock[0])
            arm(trigger, clock, lines)
            self.assertIsNone(trigger.claim(), repr(lines))
        clock = [0.0]; trigger = d.Trigger(lambda: clock[0], lambda: EPOCH)
        trigger.record(START.replace(d.CASE_LOG, 'ForeignTests testOther')); trigger.record(CREATE)
        for line in COPY: trigger.record(line)
        clock[0] = 60; self.assertIsNone(trigger.claim())

    def test_delayed_buffered_case_time_cannot_reset_reserve(self):
        clock = [0.0]; trigger = d.Trigger(lambda: clock[0], lambda: EPOCH)
        lines = [replaced.replace('49.70s', '99.70s').replace('49.72s', '99.72s').replace('49.76s', '99.76s').replace('50.06s', '100.06s') for replaced in COPY]
        trigger.record(START); trigger.record(CREATE)
        for line in lines: trigger.record(line)
        clock[0] = 5
        self.assertIsNone(trigger.claim()); self.assertEqual(trigger.reason, 'insufficient-case-time')

    def exercise(self, mutation=None):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, RUNNER_TEMP=directory):
            fixture = Fixture(directory, mutation); live = fixture.live()
            arm(live.trigger, fixture.clock); live.service(); live.service()
            report = json.loads((fixture.root/d.STATE).read_bytes())
            self.assertEqual(list(fixture.root.glob('watch-stack-*')), [])
            return report, fixture

    def test_one_sample_exact_pid_complete_cleanup_bounded_normalized_result(self):
        report, fixture = self.exercise()
        self.assertEqual(report['phase'], 'complete'); self.assertEqual(report['attempts'], 1)
        self.assertEqual(report['calls'], 8); self.assertLess(report['seconds_spent'], 2)
        self.assertEqual(len(fixture.calls), 5)
        self.assertEqual(sum('--bounded-sample' in command for command, options in fixture.calls), 1)
        command = next(command for command, options in fixture.calls if '--bounded-sample' in command)
        self.assertEqual(command[-2], '321')
        self.assertIs(report['raw_cleanup_confirmed'], True)
        self.assertNotIn('PRIVATE_OTHER_THREAD', json.dumps(report)); self.assertNotIn('PRIVATE_BINARY', json.dumps(report))
        self.assertNotIn(fixture.executable, json.dumps(report))
        self.assertLess(len(json.dumps(report).encode()), d.MAX_REPORT)

    def test_old_reused_foreign_and_ambiguous_identity_never_retains_stack(self):
        modes = ('old', 'restarted-before-precheck', 'reused', 'wrong-path', 'foreign-case', 'ambiguous-pid', 'wrong-device')
        for mode in modes:
            def mutate(f, command, result):
                if mode == 'foreign-case' and command[:3] == ['xcrun', 'simctl', 'spawn']:
                    result.stdout = result.stdout.replace(d.CASE.encode(), b'foreign_case')
                if mode == 'ambiguous-pid' and command[:3] == ['xcrun', 'simctl', 'spawn']:
                    result.stdout += result.stdout.replace(b'[321:', b'[322:')
                if mode == 'wrong-device' and command[:3] == ['xcrun', 'simctl', 'get_app_container']:
                    result.stdout = result.stdout.replace(DEVICE.encode(), PHONE.encode())
                if command[0] == str(f.root/d.TOOLS/d.IDENTITY):
                    value = dict(f.before)
                    if mode == 'old': value['start_sec'] = int(EPOCH)-1
                    if mode == 'restarted-before-precheck': value['start_sec'] = int(EPOCH)+52
                    if mode == 'reused' and f.identity_reads == 2: value['start_usec'] += 1
                    if mode == 'wrong-path': value['executable_path'] = '/other/TouchColor'
                    result.stdout = json.dumps(value).encode()
                return result
            with self.subTest(mode=mode):
                report, fixture = self.exercise(mutate)
                self.assertEqual(report['phase'], 'unavailable'); self.assertNotIn('main_thread', report)
                self.assertLessEqual(sum('--bounded-sample' in command for command, options in fixture.calls), 1 if mode == 'reused' else 0)

    def test_permission_denial_has_no_fallback_or_second_pid(self):
        def mutate(f, command, result):
            if '--bounded-sample' in command: result.returncode=1; result.stderr=b'Operation not permitted'
            return result
        report, fixture = self.exercise(mutate)
        self.assertNotIn('main_thread', report)
        self.assertTrue(report['command_results'][-1]['permission_denied'])
        self.assertEqual(len(fixture.calls), 4)

    def test_sample_output_symlink_size_side_file_and_header_mismatches_discard(self):
        for mode in ('symlink', 'size', 'side-file', 'pid-header', 'path-header', 'container-header', 'duplicate-main', 'invalid-utf8', 'stderr-cap'):
            def mutate(f, command, result):
                if '--bounded-sample' in command:
                    path = Path(command[-1])
                    if mode == 'symlink': path.unlink(); path.symlink_to(f.container/'Info.plist')
                    if mode == 'size': path.write_bytes(b'x'*(d.MAX_TEXT+1))
                    if mode == 'side-file': (path.parent/'unexpected').write_bytes(b'private')
                    if mode == 'pid-header': path.write_bytes(stack(f.executable,f.wall(),pid=999))
                    if mode == 'path-header': path.write_bytes(stack(f.executable.replace(DEVICE,PHONE),f.wall()))
                    if mode == 'container-header': path.write_bytes(stack(f.executable.replace('33333333-3333-4333-8333-333333333333','44444444-4444-4444-8444-444444444444'),f.wall()))
                    if mode == 'duplicate-main': path.write_bytes(path.read_bytes()+b'    80 Thread_999 com.apple.main-thread\n')
                    if mode == 'invalid-utf8': path.write_bytes(b'\xff')
                    if mode == 'stderr-cap': result.stderr=b'x'*8193
                return result
            with self.subTest(mode=mode):
                report, fixture = self.exercise(mutate)
                self.assertEqual(report['phase'], 'unavailable'); self.assertNotIn('main_thread', report)

    def test_case_progress_and_cancellation_between_commands_prevent_next_command(self):
        for mode in ('progress', 'cancel', 'reader-ended', 'native-ended'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, RUNNER_TEMP=directory):
                fixture = Fixture(directory); live = fixture.live(); calls=[0]
                def check():
                    calls[0]+=1
                    if mode == 'cancel' and len(fixture.calls) >= 1: raise d.NativeCancelled('cancel')
                live.cancel_check=check
                def mutate(f, command, result):
                    if mode == 'progress': live.record(event(51,'Find the "Create Color" NavigationBar'))
                    if mode == 'reader-ended': live.output_active=lambda:False
                    if mode == 'native-ended': live.native_active=lambda:False
                    return result
                fixture.mutation=mutate; arm(live.trigger,fixture.clock)
                if mode=='cancel':
                    with self.assertRaises(d.NativeCancelled): live.service()
                else: live.service()
                self.assertEqual(len(fixture.calls),1)
                self.assertNotIn('main_thread',live.report)

    def test_unknown_sampler_exit_latches_cleanup_and_stops(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, RUNNER_TEMP=directory):
            def mutate(f, command, result):
                if '--bounded-sample' in command: raise d.CaptureStopped('duration-limit',False,None)
                return result
            fixture=Fixture(directory,mutate);live=fixture.live();arm(live.trigger,fixture.clock)
            with self.assertRaises(d.CaptureStopped):live.service()
            self.assertIs(fixture.runtime['cleanup_unconfirmed'],True)
            self.assertEqual(list(fixture.root.glob('watch-stack-*')),[])
            self.assertNotIn('main_thread',live.report)

    def test_signal_during_sample_cleans_raw_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, RUNNER_TEMP=directory):
            def mutate(f, command, result):
                if '--bounded-sample' in command: raise d.CaptureStopped('interrupted',True,signal.SIGTERM)
                return result
            fixture=Fixture(directory,mutate);live=fixture.live();arm(live.trigger,fixture.clock)
            with self.assertRaises(d.CaptureStopped):live.service()
            live.service();self.assertEqual(len(fixture.calls),4)
            self.assertEqual(list(fixture.root.glob('watch-stack-*')),[])

    def test_wait_uses_original_deadline_while_servicing_on_main_thread(self):
        clock=[0.0];observed=[]
        class Process:
            args=['synthetic-xcodebuild']
            def wait(self,timeout):
                observed.append(timeout);clock[0]+=timeout
                raise subprocess.TimeoutExpired(self.args,timeout)
        class Live:
            def service(self):
                self_thread=threading.current_thread()
                if self_thread is not threading.main_thread():raise AssertionError('wrong thread')
                clock[0]+=.6
        with self.assertRaises(subprocess.TimeoutExpired):d.wait_native(Process(),1,1,Live(),d.NativeSignals(),now=lambda:clock[0])
        self.assertLessEqual(clock[0],1.25);self.assertLessEqual(max(observed),.25)

    def test_native_signal_is_recorded_before_ownership_check_and_restored(self):
        previous=signal.getsignal(signal.SIGTERM);guard=d.NativeSignals()
        try:
            guard.install();os.kill(os.getpid(),signal.SIGTERM)
            self.assertEqual(guard.cancelled,signal.SIGTERM)
            with self.assertRaises(d.NativeCancelled):guard.check()
        finally:guard.restore()
        self.assertEqual(signal.getsignal(signal.SIGTERM),previous)

    def test_sample_wrapper_sets_kernel_cap_exact_pid_and_file_only(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,RUNNER_TEMP=root):
            folder=Path(root)/'watch-stack-test';folder.mkdir();path=folder/'payload.txt'
            with patch('resource.setrlimit') as limit,patch.object(d.os,'chdir'),patch.object(d.os,'execv',side_effect=RuntimeError('inspected')) as execute:
                with self.assertRaisesRegex(RuntimeError,'inspected'):d.bounded_sample('321',str(path))
                self.assertEqual([call.args[1] for call in limit.call_args_list],[(262144,262144),(0,0)])
                self.assertEqual(os.environ['TMPDIR'],str(folder))
                self.assertEqual(execute.call_args.args[1],['/usr/bin/sample','321','1','5','-file',str(path)])
            for pid in ('TouchColor','0','-1','4194304','321 trailing'):
                with self.assertRaises(ValueError):d.bounded_sample(pid,str(path))

    def test_actual_manual_contract_is_required_not_assumed(self):
        good=b'SAMPLE\nSYNOPSIS\nsample pid duration interval [-file filename]\nDESCRIPTION\nDuration in seconds; interval in milliseconds.\n-file filename\nWrite output report to file.\n'
        self.assertIn('sample pid',d.qualify_sample_manual(good))
        self.assertIn('samplingInterval',d.qualify_sample_manual(good.replace(b'sample pid duration interval',b'sample pid duration samplingInterval')))
        for token in (b'pid',b'duration',b'interval',b'milliseconds',b'-file'):
            with self.assertRaises(ValueError):d.qualify_sample_manual(good.replace(token,b'unknown'))

if __name__=='__main__':unittest.main()
