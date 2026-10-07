import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
import zlib

import watch_copy_observation as w

ROOT = Path(__file__).resolve().parents[1]
FIRST = '00000000-0000-0000-0000-000000000001'
SECOND = '00000000-0000-0000-0000-000000000002'
DEVICE = '00000000-0000-0000-0000-000000000003'


def event(epoch, kind, editor, active=1, visible=True, pid=123, focused=None):
    stamp = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
    focus = '' if focused is None else ' focused=' + str(focused).lower()
    return (f'{stamp} Df TouchColor[{pid}:123] [com.mango.touchColor.WatchDiagnostics:editor] '
            f'WATCH_EDITOR {kind} case={w.CASE_KEY} id={editor} visible={str(visible).lower()}'
            f'{focus} active={active} dropped=0')


def lifecycle(start=1000):
    return ('\n'.join([event(start + 1, 'appear', FIRST), event(start + 2, 'focus', FIRST, focused=True),
        event(start + 3, 'disappear', FIRST, active=0, visible=False), event(start + 6, 'appear', SECOND),
        event(start + 7, 'focus', SECOND, focused=True)]) + '\n').encode()


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value


class MemoryOwner:
    def __init__(self): self.stopped = False; self.cancelled = None; self.value = {}; self.retained = {}; self.fences = []
    def persist(self): pass
    def fence(self, reason): self.stopped = True; self.fences.append(str(reason))
    def retain_bytes(self, name, raw):
        if name in self.retained: raise ValueError('repeated evidence')
        self.retained[name] = raw


class ContractTests(unittest.TestCase):
    def test_closed_single_case_and_original_timeout(self):
        cmd = w.test_command(DEVICE)
        self.assertEqual([x for x in cmd if x.startswith('-only-testing:')], ['-only-testing:TouchColorWatchUITests/WatchWorkflowTests/' + w.CASE])
        for flag in ('-default-test-execution-time-allowance', '-maximum-test-execution-time-allowance'):
            self.assertEqual(cmd[cmd.index(flag)+1], '120')
        self.assertNotIn('-test-iterations', cmd)
        self.assertNotIn('retry', ' '.join(cmd)); self.assertNotIn('Crown', ' '.join(cmd))

    def test_source_route_requires_exact_event_workflow_and_run(self):
        env = {'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':w.BRANCH,'GITHUB_EVENT_NAME':'push',
            'GITHUB_SHA':'1'*40,'GITHUB_WORKFLOW_SHA':'1'*40,'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/'+w.WORKFLOW+'@'+w.BRANCH,
            'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
        self.assertEqual(w.source_identity(env)['parent'], w.PARENT)
        for key in env:
            changed = dict(env); changed[key] = 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError): w.source_identity(changed)

    def test_budget_fits_one_job_and_observation_is_not_acceptance(self):
        plan = w.plan()
        self.assertEqual(sum(plan['phases'].values()), 1380)
        self.assertLess(1380, plan['workSeconds'])
        self.assertEqual(plan['jobSeconds']-plan['workSeconds'], 30+130+180+60+60+20)
        self.assertFalse(plan['acceptance']); self.assertFalse(plan['retry']); self.assertFalse(plan['matrix']); self.assertFalse(plan['crown'])
        self.assertEqual(plan['testCaseSeconds'], 120)

    def test_existing_ui_test_bytes_are_identical_to_tested_parent(self):
        path = 'TouchColorWatchUITests/WatchWorkflowTests.swift'
        parent = subprocess.check_output(['git','show',w.PARENT+':'+path],cwd=ROOT)
        self.assertEqual(parent, (ROOT/path).read_bytes())

    def test_release_projection_and_behavior_are_unchanged(self):
        path = 'TouchColorWatch/WatchViews.swift'
        before = subprocess.check_output(['git','show',w.PARENT+':'+path],cwd=ROOT).decode()
        after = (ROOT/path).read_text()
        begin = '@MainActor private enum WatchEditorDiagnostics'
        def without_diagnostics(source):
            prefix, rest = source.split(begin, 1)
            return prefix + begin + rest.split('#endif', 1)[1]
        self.assertEqual(without_diagnostics(before), without_diagnostics(after))
        self.assertIn('#if DEBUG\n/// Bounded local lifecycle diagnostics', after)

    def test_focus_reservation_is_two_times_eight_without_bucket_growth(self):
        source = (ROOT/'TouchColorWatch/WatchViews.swift').read_text().split('@MainActor private enum WatchEditorDiagnostics',1)[1].split('#endif',1)[0]
        self.assertIn('focusEditors.count < 2 && !focusEditors.contains(id)', source)
        self.assertIn('focusSeen[key, default: 0] <= 8', source)
        self.assertIn('emitted[bucket, default: 0] < limits[bucket, default: 0]', source)
        self.assertIn('"focusVisible": 16, "focusHidden": 16', source)
        self.assertIn('"lifecycle": 32', source)
        self.assertIn('"writeVisible": 16, "writeHidden": 16', source)
        self.assertNotIn('removeAll', source); self.assertNotIn('focusEditors =', source)
        self.assertIn('$1.value - emitted[$1.key, default: 0]', source)

    def test_workflow_has_one_job_no_dispatch_matrix_or_retry(self):
        source = (ROOT/w.WORKFLOW).read_text()
        self.assertIn('timeout-minutes: 35', source)
        self.assertNotIn('matrix:', source); self.assertNotIn('workflow_dispatch', source)
        self.assertIn('persist-credentials: false', source)
        self.assertEqual(source.count('runs-on:'), 1)
        self.assertIn('python3 scripts/watch_copy_observation.py', source)

    def test_no_targetless_help_gate_and_actual_sample_contract_is_unchanged(self):
        source=(ROOT/'scripts/watch_copy_observation.py').read_text()
        self.assertNotIn("self.call('sample-help'",source)
        self.assertNotIn("['/usr/bin/sample', '-h']",source)
        self.assertNotIn("self.call('screenshot-help'",source)
        self.assertIn("self.spawn('sample', ['/usr/bin/sample', str(self.bound['pid']), '1', '10', '-file', '/dev/stdout'], 6)",source)
        self.assertIn("require(process.returncode == 0, label + '-nonzero')",source)
        self.assertIn('validate_sample(raw, self.identity)',source)
        self.assertIn("require(after == self.identity, 'process-changed-during-sample')",source)


class BootPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name).resolve()
        self.patches = [patch.object(w, 'EVIDENCE', root), patch.object(w, 'STATE', root/'state.json'),
                        patch.object(w, 'LATCH', root/'uncertain.json')]
        for p in self.patches: p.start()
        self.clock = Clock(); self.calls = []
        self.devices = [dict(role='phone', udid=FIRST, runtime='iOS-27-0', deviceTypeIdentifier='iPhone-17'),
                        dict(role='watch', udid=SECOND, runtime='watchOS-27-0', deviceTypeIdentifier='SE3-40mm')]
        self.inventory = {'devices': {d['runtime']: [{**d, 'state': 'Booted', 'isAvailable': True}]
                                     for d in self.devices}}

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def owner(self, behavior=None):
        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if behavior: return behavior(argv, kwargs)
            self.clock.value += 1
            raw = json.dumps(self.inventory).encode() if 'list' in argv else b''
            return subprocess.CompletedProcess(argv, 0, raw, b'')
        owner = w.Owner({'sha': '1'*40}, 90, runner=run, clock=self.clock)
        owner.devices.extend(self.devices); owner.phase('setup', 600)
        return owner

    def test_phone_direct_watch_split_then_final_inventory_share_original_setup_clock(self):
        owner = self.owner(); owner.boot_owned_pair()
        self.assertEqual([c[0] for c in self.calls], [
            ['xcrun', 'simctl', 'bootstatus', FIRST, '-b'],
            ['xcrun', 'simctl', 'boot', SECOND],
            ['xcrun', 'simctl', 'bootstatus', SECOND, '-b'],
            ['xcrun', 'simctl', 'list', 'devices', 'available', '-j']])
        self.assertEqual([c[1]['seconds'] for c in self.calls], [200, 180, 180, 20])
        self.assertEqual(20+20+30+30+30+20+sum(c[1]['seconds'] for c in self.calls), 730)
        self.assertEqual(owner.phase_deadline, 700)
        self.assertEqual(owner.value['bootedInventory'],
                         [{**d, 'state': 'Booted', 'isAvailable': True} for d in self.devices])

    def test_final_inventory_rejects_missing_duplicate_wrong_identity_and_incomplete_boot(self):
        original = json.dumps(self.inventory)
        for mode in ('missing', 'duplicate', 'runtime', 'type', 'unavailable', 'booting'):
            with self.subTest(mode=mode):
                self.inventory = json.loads(original); rows = self.inventory['devices']['watchOS-27-0']
                if mode == 'missing': rows.clear()
                elif mode == 'duplicate': rows.append(dict(rows[0]))
                elif mode == 'runtime': self.inventory['devices']['other'] = self.inventory['devices'].pop('watchOS-27-0')
                elif mode == 'type': rows[0]['deviceTypeIdentifier'] = 'other'
                elif mode == 'unavailable': rows[0]['isAvailable'] = False
                elif mode == 'booting': rows[0]['state'] = 'Booting'
                w.LATCH.unlink(missing_ok=True); self.calls.clear()
                owner = self.owner()
                with self.assertRaises(ValueError): owner.boot_owned_pair()
                owner.cleanup()
                self.assertEqual(len(self.calls), 4); self.assertTrue(owner.stopped)
                self.assertNotIn('bootedInventory', owner.value)

    def test_no_following_command_after_real_child_timeout_at_each_boot_stage(self):
        for failed_index in (1, 2, 3):
            with self.subTest(failed_index=failed_index):
                w.LATCH.unlink(missing_ok=True); self.calls.clear()
                def run(argv, kwargs):
                    code = 'import time; time.sleep(5)' if len(self.calls) == failed_index else 'pass'
                    return w.capture([sys.executable, '-c', code], seconds=.12, cap=4096, cleanup_grace=2)
                owner = self.owner(run)
                with self.assertRaises(Exception): owner.boot_owned_pair()
                owner.cleanup()
                self.assertEqual(len(self.calls), failed_index); self.assertTrue(owner.stopped)
                self.assertTrue(owner.value['commands'][-1]['cleanupConfirmed'])
                self.assertEqual(owner.value['simulatorCompletion'], 'unknown')

    def test_real_child_nonzero_boot_does_not_fall_back_or_cleanup(self):
        def run(argv, kwargs):
            return w.capture([sys.executable, '-c', 'raise SystemExit(1)'], seconds=1, cap=4096, cleanup_grace=2)
        owner = self.owner(run)
        with self.assertRaises(ValueError): owner.boot_owned_pair()
        owner.cleanup(); self.assertEqual(len(self.calls), 1)
        self.assertEqual(owner.value['commands'][0]['exit'], 1)

    def test_full_next_allowance_must_fit_unchanged_setup_deadline(self):
        # All individual calls return before their own cap. Insufficient shared
        # phase time blocks the next Watch boot, Watch status or final inventory.
        for elapsed, deadline in (([22], 305), ([199, 179], 600), ([199, 179, 179], 680)):
            with self.subTest(elapsed=elapsed):
                w.LATCH.unlink(missing_ok=True); self.calls.clear(); self.clock.value = 100
                owner = self.owner(); owner.phase_deadline = deadline
                def run(argv, **kwargs):
                    self.calls.append((argv, kwargs)); self.clock.value += elapsed[len(self.calls)-1]
                    return subprocess.CompletedProcess(argv, 0, b'', b'')
                owner.runner = run
                with self.assertRaises(ValueError): owner.boot_owned_pair()
                owner.cleanup(); self.assertEqual(len(self.calls), len(elapsed))
                self.assertEqual(owner.phase_deadline, deadline)

    def test_retained_fast_startup_timings_fit_without_resetting_six_hundred_seconds(self):
        # A mixed historical timing replay demonstrates fit, not same-run native
        # proof: v5 setup/phone, 74cc 40mm Watch, full final inventory allowance.
        owner = self.owner(); original_deadline = owner.phase_deadline
        self.clock.value += 2.879
        elapsed = [57.497, 55.588, 73.268, 19.9]
        def run(argv, **kwargs):
            self.calls.append((argv, kwargs)); self.clock.value += elapsed[len(self.calls)-1]
            raw = json.dumps(self.inventory).encode() if 'list' in argv else b''
            return subprocess.CompletedProcess(argv, 0, raw, b'')
        owner.runner = run; owner.boot_owned_pair()
        self.assertEqual(owner.phase_deadline, original_deadline)
        self.assertLess(self.clock.value-100, 210)
        self.assertEqual(len(self.calls), 4)

    def test_late_inventory_cannot_qualify_boot_or_start_cleanup(self):
        def run(argv, kwargs):
            self.clock.value += 20 if 'list' in argv else 1
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.inventory).encode(), b'')
        owner = self.owner(run)
        with self.assertRaises(ValueError): owner.boot_owned_pair()
        owner.cleanup(); self.assertEqual(len(self.calls), 4); self.assertTrue(owner.stopped)
        self.assertNotIn('bootedInventory', owner.value)


class TimelineTests(unittest.TestCase):
    def test_due_only_after_existing_copy_tap_and_delay(self):
        t = w.Timeline(); self.assertFalse(t.due(1000))
        t.line("Test Case '-[TouchColorWatchUITests.WatchWorkflowTests " + w.CASE + "]' started.",10,1000)
        t.line('    t =    31.24s Tap "watch.edit.copy" Button',20,1010)
        self.assertFalse(t.due(24.99)); self.assertTrue(t.due(25))

    def test_unbound_or_repeated_events_stop(self):
        t = w.Timeline()
        with self.assertRaises(ValueError): t.line('t = 1s Tap "watch.edit.copy" Button',10,1000)
        start = "Test Case '-[WatchWorkflowTests " + w.CASE + "]' started."
        t.line(start,10,1000)
        with self.assertRaises(ValueError): t.line(start,11,1001)

    def test_ended_or_timed_out_case_cannot_trigger(self):
        for failure in (False, True):
            t=w.Timeline(); t.started=(1,1000); t.tap=(2,1001)
            if failure: t.line('Test exceeded execution time allowance of 2 minutes',4,1003)
            else: t.line("Test Case '-[WatchWorkflowTests " + w.CASE + "]' passed (5.000 seconds).",6,1005)
            self.assertFalse(t.due(50))

    def test_normal_copy_progress_prevents_observation(self):
        t=w.Timeline();t.started=(1,1000);t.tap=(2,1001)
        t.line('t = 3.0s Tap "watch.component.down" Button',3,1002)
        self.assertTrue(t.progressed);self.assertFalse(t.due(10))

    def test_observation_needs_full_window_and_cleanup_before_original_case_limit(self):
        t=w.Timeline();t.started=(10,1000);t.tap=(20,1010,10);t.case_epoch=1000;t.elapsed=10;t.elapsed_received=20
        self.assertEqual(t.observation_ceiling(25,310,1015,(0,990)),60)
        self.assertIsNone(t.observation_ceiling(91,310,1081,(0,990)))
        self.assertIsNone(t.observation_ceiling(25,64,1015,(0,990)))
        self.assertEqual(t.observation_ceiling(25,64.001,1015,(0,990)),60)

    def test_late_relative_time_cannot_be_reset_by_buffered_start_receipt(self):
        t=w.Timeline();t.started=(100,1100);t.case_epoch=1000;t.elapsed=110;t.elapsed_received=100;t.tap=(100,1100,110)
        self.assertIsNone(t.observation_ceiling(105,400,1105,(0,1000)))

    def test_absolute_case_clock_rejects_old_tap_even_if_relative_line_is_stale(self):
        t=w.Timeline();t.started=(100,1100);t.case_epoch=1000;t.elapsed=31;t.elapsed_received=100;t.tap=(100,1100,31)
        self.assertIsNone(t.observation_ceiling(110,400,1110,(0,1000)))

    def test_missing_or_discontinuous_case_clock_never_admits_observation(self):
        t=w.Timeline();t.started=(10,1000);t.tap=(20,1010,10);t.elapsed=10;t.elapsed_received=20
        self.assertIsNone(t.observation_ceiling(25,310,1015,(0,990)))
        t.case_epoch=1000
        self.assertIsNone(t.observation_ceiling(25,310,1014,(0,990)))

    def test_actual_start_timestamp_and_tap_elapsed_are_retained(self):
        t=w.Timeline()
        t.line("Test Case '-[WatchWorkflowTests "+w.CASE+"]' started.",100,1100)
        t.line('t = 0.00s Start Test at 1970-01-01 00:16:40.000',100,1100)
        t.line('t = 110.00s Tap "watch.edit.copy" Button',100,1100)
        self.assertEqual(t.case_epoch,1000);self.assertEqual(t.elapsed,110);self.assertEqual(t.tap[2],110)


class BindingTests(unittest.TestCase):
    def test_exact_current_copy_lifecycle_binds_pid_and_second_editor(self):
        row=w.bind_lifecycle(lifecycle(),1000,1005,1008)
        self.assertEqual(row['pid'],123);self.assertEqual(row['copyEditor'],SECOND)

    def test_lifecycle_requires_same_process_two_editors_and_closed_first(self):
        variations=[lifecycle().replace(b'TouchColor[123:',b'TouchColor[456:',1),
            lifecycle().replace(SECOND.encode(),FIRST.encode()),
            lifecycle().replace(b'WATCH_EDITOR disappear',b'WATCH_EDITOR focus'),
            lifecycle().replace(b'active=0',b'active=1'),
            lifecycle().replace(w.CASE_KEY.encode(),b'other_case')]
        for raw in variations:
            with self.subTest(raw=raw), self.assertRaises(ValueError): w.bind_lifecycle(raw,1000,1005,1008)

    def test_lifecycle_rejects_stale_future_overflow_and_missing_data(self):
        for raw,begin,end in [(lifecycle(),1002,1008),(lifecycle(),1000,1006),(b'',1000,1008),(lifecycle()*20,1000,1008)]:
            with self.subTest(begin=begin,end=end),self.assertRaises(ValueError):w.bind_lifecycle(raw,begin,1005,end)

    def make_product(self, root):
        root=Path(root).resolve()
        home=root/'home'; actual=home/'Library/Developer/CoreSimulator/Devices'/DEVICE/'data/Containers/Bundle/Application'/FIRST/'TouchColor.app'
        built=root/'built';actual.mkdir(parents=True);built.mkdir()
        for base in (actual,built):
            (base/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':w.BUNDLE}))
            (base/'TouchColor').write_bytes(b'launcher');(base/'TouchColor.debug.dylib').write_bytes(b'real debug product')
        raw=('123 Tue Oct 6 00:00:00 2026 '+str(actual/'TouchColor')+'\n').encode()
        return home,actual,built,raw

    def test_process_is_bound_to_owned_device_installed_product_and_dylib(self):
        with tempfile.TemporaryDirectory() as tmp:
            home,actual,built,raw=self.make_product(Path(tmp))
            row=w.parse_process(raw,123,DEVICE,built,home)
            self.assertEqual(set(row['files']),{'Info.plist','TouchColor','TouchColor.debug.dylib'})
            (actual/'TouchColor.debug.dylib').write_bytes(b'other')
            with self.assertRaises(ValueError):w.parse_process(raw,123,DEVICE,built,home)

    def test_process_rejects_foreign_pid_device_and_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            home,actual,built,raw=self.make_product(Path(tmp))
            for pid,device in [(124,DEVICE),(123,SECOND)]:
                with self.assertRaises(ValueError):w.parse_process(raw,pid,device,built,home)
            (actual/'TouchColor').unlink();(actual/'TouchColor').symlink_to(built/'TouchColor')
            with self.assertRaises(ValueError):w.parse_process(raw,123,DEVICE,built,home)

    def test_sample_header_must_match_the_observed_process(self):
        identity={'pid':123,'path':'/owned/TouchColor.app/TouchColor'}
        raw=b'Process: TouchColor [123]\nPath: /owned/TouchColor.app/TouchColor\nCall graph:\n'
        w.validate_sample(raw,identity)
        for value in (raw.replace(b'[123]',b'[124]'),raw.replace(b'/owned/',b'/foreign/'),raw.replace(b'Call graph:',b'no stack')):
            with self.assertRaises(ValueError):w.validate_sample(value,identity)

    def test_png_requires_complete_crc_bound_40mm_image(self):
        raw=screen();w.validate_screen(raw)
        for altered in (raw[:-1],raw+b'tail',raw[:30]+b'x'+raw[31:]):
            with self.assertRaises(ValueError):w.validate_screen(altered)

    def test_owned_screenshot_file_is_regular_bounded_and_identity_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp).resolve();info=directory.stat();identity=(info.st_dev,info.st_ino);path=directory/'copy.png'
            path.write_bytes(screen());raw,_=w.read_owned_screen(path,identity);self.assertEqual(raw,screen())
            with self.assertRaises(ValueError):w.read_owned_screen(path,(info.st_dev,info.st_ino+1))
            path.write_bytes(b'x'*(w.SCREEN_CAP+1))
            with self.assertRaises(ValueError):w.read_owned_screen(path,identity)
            path.unlink();path.symlink_to(directory/'missing')
            with self.assertRaises(ValueError):w.read_owned_screen(path,identity)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.patches=[patch.object(w,'EVIDENCE',self.root),patch.object(w,'STATE',self.root/'state.json'),patch.object(w,'LATCH',self.root/'uncertain.json')]
        for p in self.patches:p.start()
        self.clock=Clock();self.calls=[]
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def owner(self,behavior=None):
        def run(argv,**kwargs):
            self.calls.append(argv)
            if behavior:return behavior(argv,kwargs)
            self.clock.value+=.1
            return subprocess.CompletedProcess(argv,0,b'ok',b'')
        o=w.Owner({'sha':'1'*40},90,runner=run,clock=self.clock);o.phase('preflight',60);return o

    def test_full_allowance_is_required_before_spawn(self):
        o=self.owner();o.phase_deadline=110
        with self.assertRaises(ValueError):o.call('no-fit',['fixed'],7)
        self.assertEqual(self.calls,[])

    def test_nonzero_fences_following_native_calls(self):
        o=self.owner(lambda argv,kwargs:subprocess.CompletedProcess(argv,1,b'',b'failed'))
        with self.assertRaises(ValueError):o.call('first',['fixed'],5)
        with self.assertRaises(ValueError):o.call('forbidden',['other'],5)
        self.assertEqual(self.calls,[['fixed']]);self.assertTrue(o.stopped)

    def test_late_return_is_unknown_even_with_host_cleanup(self):
        def late(argv,kwargs):self.clock.value+=5;return subprocess.CompletedProcess(argv,0,b'',b'')
        o=self.owner(late)
        with self.assertRaises(ValueError):o.call('late',['fixed'],5)
        self.assertTrue(o.stopped);self.assertTrue(w.LATCH.exists())

    def test_capture_failure_records_cleanup_and_stops(self):
        class Stopped(RuntimeError):cleanup_confirmed=False
        def bad(argv,kwargs):raise Stopped('timeout')
        o=self.owner(bad)
        with self.assertRaises(Stopped):o.call('timeout',['fixed'],5)
        self.assertFalse(o.value['commands'][0]['cleanupConfirmed']);self.assertTrue(o.stopped)

    def test_no_cleanup_commands_after_uncertainty(self):
        o=self.owner();o.devices=[{'role':'watch','udid':DEVICE}];o.fence('unknown');o.cleanup()
        self.assertEqual(self.calls,[])

    def test_session_cancellation_blocks_owner_device_cleanup(self):
        o=self.owner();o.devices=[{'role':'watch','udid':DEVICE}];o.cancelled=15;o.cleanup()
        self.assertEqual(self.calls,[]);self.assertTrue(o.stopped)

    def test_observer_never_starts_after_case_end_or_cancel(self):
        owner=MemoryOwner();session=w.Session(owner,DEVICE,1000,clock=self.clock)
        session.observation_deadline=900;session.timeline.ended={'result':'passed'}
        with patch.object(w.subprocess,'Popen') as popen:
            with self.assertRaises(ValueError):session.spawn('sample',['sample'],6)
            self.assertFalse(popen.called)
        session.selector.close()

    def test_observer_must_fit_xcode_command_deadline_not_only_phase(self):
        owner=MemoryOwner();session=w.Session(owner,DEVICE,400,clock=self.clock,wall=lambda:900+self.clock.value)
        session.timeline.started=(100,1000);session.timeline.case_epoch=1000
        session.timeline.tap=(104,1004,4);session.timeline.elapsed=4;session.timeline.elapsed_received=104
        session.test_process=type('Alive',(),{'poll':lambda self:None})()
        session.test_deadline=115;session.observation_deadline=145;self.clock.value=110
        with patch.object(w.subprocess,'Popen') as popen:
            with self.assertRaises(ValueError):session.spawn('pid-before',['ps'],3)
            self.assertFalse(popen.called)
        session.selector.close()

    def test_bounded_capture_has_no_native_tool_in_portable_test(self):
        # Real pipe/cap/owned-process regression, using only this Python runtime.
        from palette_lifecycle_diagnostics import CaptureStopped,capture
        with self.assertRaises(CaptureStopped) as caught:
            capture([sys.executable,'-c','print("x"*20000)'],seconds=2,cap=1000)
        self.assertTrue(caught.exception.cleanup_confirmed)

    def test_artifact_validation_is_filesystem_only_and_rejects_symlink(self):
        (self.root/'test-stdout.log').write_text('test')
        with patch.object(w,'ROOT',self.root):w.local_validation()
        (self.root/'copy-screen.png').symlink_to(self.root/'test-stdout.log')
        with patch.object(w,'ROOT',self.root),self.assertRaises(ValueError):w.local_validation()

    def test_artifact_rejects_undeclared_files(self):
        (self.root/'unrequested.log').write_text('not part of this observation')
        with patch.object(w,'ROOT',self.root),self.assertRaises(ValueError):w.local_validation()


def screen():
    def chunk(kind,data):return len(data).to_bytes(4,'big')+kind+data+(zlib.crc32(kind+data)&0xffffffff).to_bytes(4,'big')
    header=(324).to_bytes(4,'big')+(394).to_bytes(4,'big')+bytes([8,2,0,0,0])
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*(324*3))*394))+chunk(b'IEND',b'')


class MultiplexTests(unittest.TestCase):
    """Exercise real pipe draining/ownership using Python children, never Apple tools."""
    def run_session(self, mode):
        owner=MemoryOwner()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();output=root/'output';output.mkdir();end_flag=root/'emit-end'
            home,actual,built,pid_raw=BindingTests().make_product(root)
            sample=('Process: TouchColor [123]\nPath: '+str(actual/'TouchColor')+'\nCall graph:\n').encode()
            begin="Test Case '-[TouchColorWatchUITests.WatchWorkflowTests "+w.CASE+"]' started."
            end="Test Case '-[TouchColorWatchUITests.WatchWorkflowTests "+w.CASE+"]' passed (1.000 seconds)."
            script='import os,sys,time,signal,datetime,subprocess,pathlib;print('+repr(begin)+',flush=True);'
            if mode!='missing_clock':
                script+='print("t = 0.00s Start Test at "+datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],flush=True);'
            script+='time.sleep(.08);'
            if mode=='timeout':script+='print("Test exceeded execution time allowance of 2 minutes",flush=True);time.sleep(5)'
            elif mode=='signal':script+='os.kill(os.getppid(),signal.SIGTERM);time.sleep(5)'
            elif mode=='flood':script+='sys.stdout.write("x"*300000);sys.stdout.flush();time.sleep(5)'
            else:
                elapsed='110.00' if mode=='late' else '31.24'
                script+='print(\'t = '+elapsed+'s Tap "watch.edit.copy" Button\',flush=True);'
                if mode=='dead_exit':
                    script+='subprocess.Popen([sys.executable,"-c","import time;time.sleep(5)"]);os.kill(os.getpid(),signal.SIGKILL)'
                elif mode=='pending_end':
                    script+='deadline=time.monotonic()+3\nwhile not pathlib.Path('+repr(str(end_flag))+').exists() and time.monotonic()<deadline:time.sleep(.01)\nprint('+repr(end)+',flush=True);time.sleep(1)'
                else:
                    if mode in ('normal','finish_cancel'):script+='print(\'t = 32.0s Tap "watch.component.down" Button\',flush=True);'
                    script+='time.sleep(1.0);print('+repr(end)+',flush=True)'
            injected=[False]
            def persistence():
                if injected[0]:return
                rows=owner.value.get('observationCommands',[]);last=rows[-1] if rows else {}
                new=bool(last) and 'hostPID' not in last
                cancel=((mode=='persist_test_cancel' and new and last['label']=='test') or
                    (mode=='persist_observer_cancel' and new and last['label']=='sample') or
                    (mode=='finish_cancel' and owner.value.get('caseOutcome') is not None))
                if cancel:
                    injected[0]=True;os.kill(os.getpid(),__import__('signal').SIGTERM)
                elif mode=='pending_end' and new and last['label']=='sample':
                    injected[0]=True;end_flag.write_text('end');time.sleep(.1)
            owner.persist=persistence
            dispatched=[]
            class PythonSession(w.Session):
                def spawn(self,label,argv,seconds):
                    dispatched.append(label)
                    if label=='test':code=script
                    else:
                        if label=='lifecycle':
                            now=time.time();data=('\n'.join([event(now-.05,'appear',FIRST),event(now-.03,'disappear',FIRST,active=0,visible=False),
                                event(now-.01,'appear',SECOND)])+'\n').encode()
                        elif label in ('pid-before','pid-after'):data=pid_raw
                        elif label=='sample':data=sample
                        else:
                            require_path=Path(argv[-1])
                            self_test=mode=='screen_failure'
                            code='import pathlib,sys;pathlib.Path('+repr(str(require_path))+').write_bytes(bytes.fromhex('+repr(screen().hex())+'));sys.exit('+('1' if self_test else '0')+')'
                        if label!='screenshot':code='import sys;sys.stdout.buffer.write(bytes.fromhex('+repr(data.hex())+'));sys.stdout.flush()'
                    return super().spawn(label,[sys.executable,'-c',code],seconds)
            s=PythonSession(owner,DEVICE,time.monotonic()+300)
            before={sig:__import__('signal').getsignal(sig) for sig in (__import__('signal').SIGINT,__import__('signal').SIGTERM)}
            with patch.object(w,'OBSERVER_DELAY',.03),patch.object(w,'PRODUCT',built),patch.object(w,'ROOT',output),patch.object(w.Path,'home',return_value=home):
                if mode in ('timeout','signal','flood','dead_exit','persist_test_cancel','persist_observer_cancel','finish_cancel','pending_end','screen_failure'):
                    with self.assertRaises((RuntimeError,ValueError)):s.run()
                else:s.run()
            for row in s.rows:
                if 'hostPID' not in row:continue
                if mode=='dead_exit' and not row['cleanupConfirmed']:
                    self.assertTrue(owner.stopped);continue
                self.assertTrue(row['cleanupConfirmed'])
                self.assertFalse(w.group_exists(row['hostPID']))
            owner.value['actuallyStarted']=[row['label'] for row in s.rows if 'hostPID' in row]
            owner.value['ownedScreenLeftovers']=len(list(output.glob('owned-screen-*')))
            for sig,handler in before.items():self.assertEqual(__import__('signal').getsignal(sig),handler)
        return owner,dispatched

    def test_complete_observation_chain_runs_once_while_test_pipe_stays_live(self):
        owner,commands=self.run_session('observe')
        self.assertEqual(commands,['test','lifecycle','pid-before','sample','pid-after','screenshot'])
        self.assertEqual(owner.value['caseOutcome']['result'],'passed')
        self.assertIn('app-sample.txt',owner.retained);self.assertIn('copy-screen.png',owner.retained)
        self.assertFalse(owner.stopped)

    def test_normal_progress_does_not_sample_or_capture(self):
        owner,commands=self.run_session('normal')
        self.assertEqual(commands,['test'])
        self.assertEqual(owner.value['observationStatus'],'copy-interaction-resumed-before-observation')

    def test_test_timeout_stops_owned_group_without_observation(self):
        owner,commands=self.run_session('timeout')
        self.assertTrue(owner.stopped);self.assertEqual(commands,['test'])

    def test_cancellation_is_recorded_until_owned_cleanup_finishes(self):
        owner,commands=self.run_session('signal')
        self.assertTrue(owner.stopped);self.assertEqual(commands,['test'])

    def test_flood_stops_at_byte_cap_and_preserves_only_bounded_output(self):
        owner,commands=self.run_session('flood')
        self.assertTrue(owner.stopped);self.assertEqual(commands,['test'])
        self.assertLessEqual(sum(len(raw) for raw in owner.retained.values()),w.CAPS['test'])

    def test_buffered_late_tap_and_missing_actual_clock_start_no_observer(self):
        for mode in ('late','missing_clock'):
            owner,commands=self.run_session(mode)
            self.assertEqual(commands,['test']);self.assertEqual(owner.value['actuallyStarted'],['test'])
            self.assertEqual(owner.value['observationStatus'],'insufficient-original-case-window-no-observer')

    def test_dead_xctest_with_open_descendant_pipe_cannot_launch_lifecycle(self):
        owner,commands=self.run_session('dead_exit')
        self.assertEqual(commands,['test']);self.assertTrue(owner.stopped)

    def test_sigterm_during_test_admission_persistence_prevents_popen(self):
        owner,commands=self.run_session('persist_test_cancel')
        self.assertEqual(owner.value['actuallyStarted'],[]);self.assertIsNotNone(owner.cancelled)

    def test_sigterm_during_observer_handoff_persistence_prevents_popen(self):
        owner,commands=self.run_session('persist_observer_cancel')
        self.assertEqual(owner.value['actuallyStarted'],['test','lifecycle','pid-before'])
        self.assertIsNotNone(owner.cancelled)

    def test_readable_case_end_during_handoff_is_drained_before_next_popen(self):
        owner,commands=self.run_session('pending_end')
        self.assertEqual(owner.value['actuallyStarted'],['test','lifecycle','pid-before'])
        self.assertTrue(owner.stopped)

    def test_close_time_cancellation_is_transferred_to_owner(self):
        owner,commands=self.run_session('finish_cancel')
        self.assertIsNotNone(owner.cancelled);self.assertTrue(owner.stopped)
        self.assertEqual(owner.value['actuallyStarted'],['test'])

    def test_screen_file_requires_successful_terminal_producer(self):
        owner,commands=self.run_session('screen_failure')
        self.assertNotIn('copy-screen.png',owner.retained);self.assertEqual(owner.value['ownedScreenLeftovers'],1)
        self.assertTrue(owner.stopped)


class AncestorAliasTests(unittest.TestCase):
    def test_all_owned_fixture_roots_canonicalize_ancestor_aliases(self):
        # Model macOS temporary-root aliases on any host. The leaf itself is a
        # normal directory; only its ancestor is a symlink. Runtime identity
        # checks remain strict and must still reject an aliased executable.
        original = tempfile.TemporaryDirectory
        test = self
        class AliasedTemporaryDirectory:
            def __init__(self,*args,**kwargs):
                self.inner=original(*args,**kwargs)
                root=Path(self.inner.name).resolve();actual=root/'actual';actual.mkdir()
                alias=root/'alias';alias.symlink_to(actual,target_is_directory=True)
                (actual/'case').mkdir();self.name=str(alias/'case')
                test.assertFalse(Path(self.name).is_symlink())
                test.assertNotEqual(Path(self.name),Path(self.name).resolve())
            def __enter__(self):return self.name
            def __exit__(self,*args):self.cleanup()
            def cleanup(self):self.inner.cleanup()
        with patch.object(tempfile,'TemporaryDirectory',AliasedTemporaryDirectory):
            binding=BindingTests()
            binding.test_process_is_bound_to_owned_device_installed_product_and_dylib()
            binding.test_process_rejects_foreign_pid_device_and_link()
            binding.test_owned_screenshot_file_is_regular_bounded_and_identity_bound()
            with tempfile.TemporaryDirectory() as tmp:
                home,actual,built,raw=binding.make_product(Path(tmp))
                alias=home.parent/'home-alias';alias.symlink_to(home,target_is_directory=True)
                aliased_raw=raw.replace(str(home).encode(),str(alias).encode())
                with self.assertRaisesRegex(ValueError,'linked-or-missing-app-executable'):
                    w.parse_process(aliased_raw,123,DEVICE,built,alias)
            multiplex=MultiplexTests()
            multiplex.test_complete_observation_chain_runs_once_while_test_pipe_stays_live()
            multiplex.test_sigterm_during_observer_handoff_persistence_prevents_popen()
            multiplex.test_screen_file_requires_successful_terminal_producer()
            for method in ('test_no_cleanup_commands_after_uncertainty',
                           'test_artifact_validation_is_filesystem_only_and_rejects_symlink'):
                admission=AdmissionTests();admission.setUp()
                try:
                    self.assertEqual(admission.root,admission.root.resolve())
                    getattr(admission,method)()
                finally:admission.tearDown()


if __name__=='__main__':unittest.main()
