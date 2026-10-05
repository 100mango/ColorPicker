"""Portable contracts and real owned-host adversaries; never invokes Apple tools."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

import mini_direct_xctest as m
from job_budget import create_record, JobBudget, BudgetExhausted

SOURCE = Path(__file__).resolve().parents[1]
ENV = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': m.REF,
       'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': m.WORKFLOW,
       'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS', 'RUNNER_ENVIRONMENT': 'github-hosted',
       'GITHUB_JOB': 'mini-direct-xctest', 'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40,
       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
       'TOUCHCOLOR_JOB_PLATFORM': 'ios', 'TOUCHCOLOR_JOB_LANE': 'mini-direct-xctest',
       'TOUCHCOLOR_JOB_MINUTES': '20', 'TOUCHCOLOR_BUDGET_PHASE': 'work'}
IDENTITY = {'family': 'iPadMini', 'udid': 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE',
            'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 1}


class Temporary(unittest.TestCase):
    def setUp(self):
        self.old = Path.cwd(); self.temp = tempfile.TemporaryDirectory(); os.chdir(self.temp.name)
        self.env = patch.dict(os.environ, ENV, clear=True); self.env.start()
        os.environ['TOUCHCOLOR_JOB_STARTED_EPOCH'] = str(time.time())
        os.environ['TOUCHCOLOR_JOB_STARTED_MONOTONIC'] = str(time.monotonic())
        self.budget = JobBudget(create_record())
        self.enabled = patch.object(m, 'enabled_budget', return_value=self.budget); self.enabled.start()

    def tearDown(self):
        self.enabled.stop(); self.env.stop(); os.chdir(self.old); self.temp.cleanup()

    def diagnostic(self):
        d = m.Diagnostic(); d.identity = dict(IDENTITY)
        return d


class IdentityAndBudget(Temporary):
    def test_exact_hosted_push_identity(self):
        self.assertEqual(m.require_job(), 'a' * 40)
        for key in ENV:
            if key.startswith('GITHUB_') or key in ('RUNNER_OS', 'RUNNER_ENVIRONMENT'):
                with self.subTest(key=key), patch.dict(os.environ, {key: 'wrong'}):
                    with self.assertRaises(ValueError): m.require_job()

    def test_original_720_second_work_envelope(self):
        self.assertAlmostEqual(self.budget.remaining(), 720, delta=.2)
        self.assertEqual(sum(self.budget.record['reserves'].values()), 450)
        self.assertEqual(self.budget.record['startup_margin'], 30)

    def test_no_partial_xctest_window(self):
        d = self.diagnostic(); d.budget.hard_deadline = time.monotonic() + 450 + 319
        with patch.object(m, 'read_identity', return_value=IDENTITY), patch.object(m, 'observe') as observe:
            with self.assertRaises(BudgetExhausted): d.execute()
        observe.assert_not_called(); self.assertFalse(m.PENDING.exists())

    def test_full_allowance_and_permanent_marker(self):
        d = self.diagnostic()
        value = {'status': 'command_exit_observed', 'observed_command_exit': 0, 'host_cleanup_confirmed': True}
        with patch.object(m, 'read_identity', return_value=IDENTITY), patch.object(m, 'observe', return_value=(value, {})) as observe:
            d.execute()
        observe.assert_called_once_with(m.test_argv(IDENTITY['udid']), 300,
                                       work_deadline=d.budget.hard_deadline - 450 - 20)
        self.assertTrue(m.PENDING.exists()); self.assertTrue(m.STOP.exists())
        self.assertFalse(d.report['warmup_accepted']); self.assertFalse(d.report['full_row_accepted'])

    def test_persistence_cannot_steal_test_time(self):
        d = self.diagnostic()
        def consume(): d.budget.hard_deadline = time.monotonic() + 450 + 319
        with patch.object(m, 'read_identity', return_value=IDENTITY), patch.object(d, 'persist', side_effect=consume), patch.object(m, 'observe') as observe:
            with self.assertRaises(BudgetExhausted): d.execute()
        observe.assert_not_called(); self.assertTrue(m.PENDING.exists())

    def test_changed_owned_identity_rejected(self):
        d = self.diagnostic()
        with patch.object(m, 'read_identity', return_value={}), patch.object(m, 'observe') as observe:
            with self.assertRaises(ValueError): d.execute()
        observe.assert_not_called()

    def test_no_second_diagnostic(self):
        self.diagnostic()
        with self.assertRaises(ValueError): m.Diagnostic()

    def test_wrong_budget_lane_rejected(self):
        self.budget.record['lane'] = 'other'
        with self.assertRaises(ValueError): m.Diagnostic()

    def test_prior_uncertainty_rejected(self):
        Path('build').mkdir(); m.PENDING.write_text('stop')
        with self.assertRaises(Exception): m.Diagnostic()

    def test_setup_failure_leaves_permanent_stop(self):
        d = self.diagnostic()
        with patch.object(d, 'prepare', side_effect=ValueError('setup failed')), patch.object(d, 'execute') as execute:
            self.assertEqual(d.run(), 3)
        execute.assert_not_called(); self.assertTrue(m.PENDING.exists())
        self.assertEqual(json.loads((m.ROOT / 'receipt.json').read_text())['status'], 'failed_or_incomplete')

    def test_preparation_preserves_original_template_sequence(self):
        d = self.diagnostic(); self.assertEqual(d.warmup.deadline, m.STARTED + 600)
        d.warmup = Mock(); d.warmup.select.return_value = IDENTITY['udid']
        def command(args, seconds, **kwargs):
            if args == ['git', 'rev-parse', 'HEAD']: return 'a' * 40
            if args == ['xcodebuild', '-version']: return 'Xcode 27.0\nBuild version 27A266a\n'
            return ''
        d.warmup.command.side_effect = command
        with patch.object(m, 'read_identity', return_value=IDENTITY), patch.object(m, 'products', return_value={'exact': 'product'}):
            d.prepare()
        d.warmup.select.assert_called_once_with()
        calls = d.warmup.command.call_args_list
        self.assertIn(unittest.mock.call(m.BUILD, 300, simulator=False), calls)
        device_calls = [(c.args, c.kwargs) for c in calls if c.args[0][:2] == ['xcrun', 'simctl']]
        self.assertEqual(device_calls, [
            ((['xcrun', 'simctl', 'boot', IDENTITY['udid']], 180), {'optional': True}),
            ((['xcrun', 'simctl', 'bootstatus', IDENTITY['udid'], '-b'], 240), {}),
            ((['xcrun', 'simctl', 'install', IDENTITY['udid'],
               'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'], 300), {})])

    def test_setup_timeout_keeps_uncertainty_and_blocks_xctest(self):
        d = self.diagnostic()
        with patch.object(m, 'capture', side_effect=m.CaptureStopped('duration-limit', True)), patch.object(d, 'execute') as execute:
            self.assertEqual(d.run(), 3)
        execute.assert_not_called(); self.assertTrue(m.PENDING.exists())
        self.assertEqual(d.report['preparation_commands'][0]['reason'], 'duration-limit')

    def test_cleanup_uncertainty_latches_no_host_summary(self):
        d = self.diagnostic(); d.report['xctest'] = {'host_cleanup_confirmed': False}
        with patch.object(m, 'capture') as capture: d.host_summary()
        capture.assert_not_called()
        self.assertEqual(d.report['summary']['status'], 'unavailable_cleanup_or_cancellation')

    def test_no_result_bundle_is_not_test_failure(self):
        d = self.diagnostic(); d.report['xctest'] = {'host_cleanup_confirmed': True}
        d.host_summary(); self.assertEqual(d.report['summary']['status'], 'unavailable_result_bundle')

    def test_host_summary_is_separate_aggregate(self):
        d = self.diagnostic(); d.report['xctest'] = {'host_cleanup_confirmed': True}; m.RESULT.mkdir()
        result = subprocess.CompletedProcess([], 0, b'{"result":"Passed","passedTests":1,"arbitrary":"ignored"}', b'')
        with patch.object(m, 'capture', return_value=result) as capture: d.host_summary()
        self.assertEqual(d.report['summary']['fields'], {'result': 'Passed', 'passedTests': 1})
        self.assertNotIn('simctl', capture.call_args.args[0]); self.assertEqual(capture.call_args.kwargs['seconds'], 3)

    def test_host_summary_unavailable_after_timeout(self):
        d = self.diagnostic(); d.report['xctest'] = {'host_cleanup_confirmed': True}; m.RESULT.mkdir()
        with patch.object(m, 'capture', side_effect=m.CaptureStopped('duration-limit', True)):
            d.host_summary()
        self.assertEqual(d.report['summary']['status'], 'unavailable')
        self.assertFalse(d.budget.cleanup_unconfirmed)

    def test_host_summary_cleanup_failure_is_latched(self):
        d = self.diagnostic(); d.report['xctest'] = {'host_cleanup_confirmed': True}; m.RESULT.mkdir()
        with patch.object(m, 'capture', side_effect=m.CaptureStopped('duration-limit', False)):
            d.host_summary()
        self.assertTrue(d.budget.cleanup_unconfirmed)

    def test_case_failure_or_success_still_ends_diagnostic(self):
        for exit_code in (0, 65):
            with self.subTest(exit_code=exit_code):
                d = m.Diagnostic.__new__(m.Diagnostic); d.budget = self.budget; d.report = {}
                with patch.object(d, 'prepare'), patch.object(d, 'execute'), patch.object(d, 'host_summary'), patch.object(d, 'persist'):
                    Path('build').mkdir(exist_ok=True)
                    self.assertEqual(d.run(), 3)
                    self.assertTrue(m.PENDING.exists())


class SetupAbsoluteDeadline(Temporary):
    def harness(self, *, start=500.0, work_end=720.0):
        d = self.diagnostic(); tick = [start]
        d.warmup.clock = lambda: tick[0]; d.warmup.deadline = 600.0
        d.budget.monotonic = lambda: tick[0]; d.budget.hard_deadline = work_end + 450.0
        d.persist = lambda: None
        return d, tick

    def command(self, d, seconds=300):
        return d.warmup.command(['host-only-deadline-proof'], seconds, simulator=False)

    def test_reviewer_expired_persistence_starts_no_capture(self):
        d, tick = self.harness(); d.persist = lambda: tick.__setitem__(0, 601.0)
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture') as capture:
            with self.assertRaisesRegex(ValueError, 'expired_after_persistence'): self.command(d)
        capture.assert_not_called(); self.assertTrue(m.PENDING.exists())
        self.assertEqual(d.report['preparation_commands'][0]['absolute_deadline'], 580.0)

    def test_persistence_consumes_existing_allowance(self):
        d, tick = self.harness(); d.persist = lambda: tick.__setitem__(0, 550.0)
        answer = subprocess.CompletedProcess([], 0, b'ok', b'')
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture', return_value=answer) as capture:
            self.assertEqual(self.command(d), 'ok')
        self.assertEqual(capture.call_args.kwargs['seconds'], 30.0)
        self.assertFalse(m.PENDING.exists())

    def test_original_job_work_boundary_wins(self):
        d, tick = self.harness(work_end=560.0); d.persist = lambda: tick.__setitem__(0, 530.0)
        answer = subprocess.CompletedProcess([], 0, b'ok', b'')
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture', return_value=answer) as capture:
            self.command(d)
        self.assertEqual(capture.call_args.kwargs['seconds'], 10.0)
        self.assertEqual(d.report['preparation_commands'][0]['absolute_deadline'], 540.0)

    def test_admitted_command_bound_wins(self):
        d, tick = self.harness(); d.persist = lambda: tick.__setitem__(0, 505.0)
        answer = subprocess.CompletedProcess([], 0, b'ok', b'')
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture', return_value=answer) as capture:
            self.command(d, seconds=10)
        self.assertEqual(capture.call_args.kwargs['seconds'], 5.0)
        self.assertEqual(d.report['preparation_commands'][0]['absolute_deadline'], 510.0)

    def test_expired_runner_entry_starts_no_capture(self):
        d, tick = self.harness(start=581.0)
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture') as capture:
            with self.assertRaisesRegex(ValueError, 'expired_before_persistence'):
                d.setup_runner(['host-only-expired-entry'], timeout=80)
        capture.assert_not_called()

    def test_expiry_immediately_before_capture_is_rejected(self):
        d, tick = self.harness()
        ticks = iter([500.0, 500.0, 570.0, 601.0, 601.0])
        with patch.object(m.time, 'monotonic', side_effect=lambda: next(ticks)), patch.object(m, 'capture') as capture:
            with self.assertRaisesRegex(ValueError, 'expired_before_capture'):
                d.setup_runner(['host-only-expiring-entry'], timeout=80)
        capture.assert_not_called()

    def test_late_return_retains_stop_and_blocks_next_command(self):
        d, tick = self.harness(work_end=560.0)
        def late_capture(command, **kwargs):
            tick[0] = 541.0
            return subprocess.CompletedProcess(command, 0, b'late result', b'')
        with patch.object(m.time, 'monotonic', side_effect=lambda: tick[0]), patch.object(m, 'capture', side_effect=late_capture) as capture:
            with self.assertRaisesRegex(ValueError, 'returned_after_deadline'): self.command(d)
            self.assertTrue(m.PENDING.exists())
            with self.assertRaises(Exception): self.command(d)
        capture.assert_called_once()
        event = d.report['preparation_commands'][0]
        self.assertEqual(event['exit'], 0); self.assertTrue(event['host_cleanup_confirmed'])
        self.assertEqual(event['reason'], 'setup_capture_returned_after_deadline')

    def test_real_owned_setup_timeout_preserves_marker(self):
        d = self.diagnostic(); original = m.capture
        with patch.object(m, 'capture', wraps=original) as capture:
            with self.assertRaises(m.CaptureStopped) as stopped:
                d.warmup.command([sys.executable, '-c', 'import time;time.sleep(30)'], .08, simulator=False)
            self.assertTrue(stopped.exception.cleanup_confirmed); self.assertTrue(m.PENDING.exists())
            with self.assertRaises(FileExistsError):
                d.warmup.command([sys.executable, '-c', 'print("never started")'], 1, simulator=False)
        capture.assert_called_once()
        self.assertLess(capture.call_args.kwargs['seconds'], .08)
        self.assertTrue(d.report['preparation_commands'][0]['host_cleanup_confirmed'])


class ConsoleLifecycle(unittest.TestCase):
    def parser(self, *lines):
        p = m.CaseObservation()
        for line in lines: p.feed((line + '\n').encode())
        return p.result()

    def test_exact_case_pass(self):
        r = self.parser("Test Case '" + m.CASE_LABEL + "' started.", "Test Case '" + m.CASE_LABEL + "' passed (2.000 seconds).")
        self.assertEqual((r['status'], r['outcome']), ('completed', 'passed'))

    def test_failure_not_exit_status(self):
        r = self.parser("Test Case '" + m.CASE_LABEL + "' started.", "Test Case '" + m.CASE_LABEL + "' failed (240.000 seconds).")
        self.assertEqual(r['outcome'], 'failed')

    def test_start_only_is_incomplete(self):
        self.assertEqual(self.parser("Test Case '" + m.CASE_LABEL + "' started.")['status'], 'started_without_end')

    def test_wrong_or_repeated_case_conflicts(self):
        for lines in [("Test Case '-[Other test]' started.",),
                      ("Test Case '" + m.CASE_LABEL + "' started.",) * 2,
                      ("Test Case '" + m.CASE_LABEL + "' passed (1 seconds).",)]:
            self.assertEqual(self.parser(*lines)['status'], 'conflicting')

    def test_split_lines_and_giant_lines(self):
        p = m.CaseObservation(); raw = ("Test Case '" + m.CASE_LABEL + "' started.\n").encode()
        for c in raw: p.feed(bytes([c]))
        self.assertEqual(p.result()['started'], 1)
        p.feed(b'x' * 100000 + b'\n'); self.assertEqual(len(p.partial), 0)
        self.assertEqual(p.result()['started'], 1)

    def test_unterminated_line_never_proves_case_start(self):
        p = m.CaseObservation(); p.feed(("Test Case '" + m.CASE_LABEL + "' started.").encode())
        self.assertEqual(p.result()['status'], 'unobserved'); self.assertTrue(p.result()['partial_line_omitted'])


class RealOwnedProcesses(unittest.TestCase):
    def run_host(self, program, seconds=2, **kwargs):
        return m.observe([sys.executable, '-c', program], seconds, **kwargs)

    def test_zero_exit_is_not_case_execution(self):
        value, data = self.run_host('print("no test")')
        self.assertEqual(value['observed_command_exit'], 0)
        self.assertEqual(value['case']['status'], 'unobserved')
        self.assertTrue(value['host_cleanup_confirmed']); self.assertEqual(data['stdout'], b'no test\n')

    def test_nonzero_exit_is_distinct_from_case(self):
        value, _ = self.run_host('raise SystemExit(65)')
        self.assertEqual(value['status'], 'command_exit_observed'); self.assertEqual(value['observed_command_exit'], 65)

    def test_actual_timeout_reaps_owned_process(self):
        value, _ = self.run_host('import time; time.sleep(30)', .08)
        self.assertEqual(value['status'], 'failed_or_incomplete'); self.assertIsNone(value['observed_command_exit'])
        self.assertTrue(value['host_cleanup_confirmed']); self.assertFalse(m.group_exists(value['pid']))
        self.assertLess(value['elapsed_seconds'], 2)

    def test_case_pass_before_hang_stays_command_incomplete(self):
        lines = "Test Case '" + m.CASE_LABEL + "' started.\nTest Case '" + m.CASE_LABEL + "' passed (1.000 seconds)."
        value, _ = self.run_host('import time; print(' + repr(lines) + ',flush=True);time.sleep(30)', .15)
        self.assertEqual(value['case']['outcome'], 'passed'); self.assertIsNone(value['observed_command_exit'])
        self.assertEqual(value['simulator_completion'], 'unconfirmed')

    def test_real_case_output_with_nonzero_command(self):
        lines = "Test Case '" + m.CASE_LABEL + "' started.\nTest Case '" + m.CASE_LABEL + "' passed (1.000 seconds)."
        value, _ = self.run_host('print(' + repr(lines) + ');raise SystemExit(65)')
        self.assertEqual(value['case']['outcome'], 'passed'); self.assertEqual(value['observed_command_exit'], 65)

    def test_output_flood_is_capped_and_reaped(self):
        value, output = self.run_host('import os;\nwhile True: os.write(1,b"x"*4096)')
        self.assertEqual(value['reason'], 'output_limit'); self.assertLessEqual(len(output['stdout']), 65536)
        self.assertTrue(value['host_cleanup_confirmed']); self.assertFalse(m.group_exists(value['pid']))

    def test_simultaneous_stdout_stderr_drained(self):
        value, output = self.run_host('import os;\nfor i in range(200): os.write(1,b"o"*1024);os.write(2,b"e"*1024)')
        self.assertEqual(value['observed_command_exit'], 0)
        self.assertEqual(value['output']['stdout']['raw_bytes'], 204800)
        self.assertEqual(len(output['stderr']), 16384)

    def test_cancellation_during_owned_command(self):
        before = signal.getsignal(signal.SIGTERM)
        timer = threading.Timer(.1, lambda: os.kill(os.getpid(), signal.SIGTERM)); timer.start()
        try: value, _ = self.run_host('import time;time.sleep(30)')
        finally: timer.join()
        self.assertEqual(value['signal'], signal.SIGTERM); self.assertTrue(value['host_cleanup_confirmed'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)

    def test_cleanup_uncertainty_is_not_natural_exit(self):
        def uncertain(process, grace):
            self.assertEqual(grace, 10); m.stop_group(process, grace=.1); return False
        value, _ = self.run_host('import time;time.sleep(30)', .08, stopper=uncertain)
        self.assertFalse(value['host_cleanup_confirmed']); self.assertEqual(value['simulator_completion'], 'unconfirmed')

    def test_cleanup_exception_is_retained_as_uncertainty(self):
        def broken_cleanup(process, grace):
            m.stop_group(process, grace=.1)
            raise PermissionError('synthetic cleanup denial after test-owned cleanup')
        value, _ = self.run_host('import time;time.sleep(30)', .08, stopper=broken_cleanup)
        self.assertFalse(value['host_cleanup_confirmed']); self.assertEqual(value['cleanup_error'], 'PermissionError')

    def test_spawn_failure_leaves_cleanup_unknown(self):
        value, _ = m.observe(['missing'], 1, popen=Mock(side_effect=OSError('spawn failed')))
        self.assertTrue(value['attempted']); self.assertFalse(value['owned']); self.assertIsNone(value['host_cleanup_confirmed'])

    def test_real_parent_and_descendant_are_reaped_together(self):
        program = '''import subprocess,sys,signal,time
child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
def end(signum, frame):
    child.wait(timeout=1)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, end)
print(child.pid, flush=True)
time.sleep(30)
'''
        value, output = self.run_host(program, .15)
        self.assertTrue(value['host_cleanup_confirmed']); self.assertIsNone(value['observed_command_exit'])
        self.assertFalse(m.group_exists(value['pid']))
        with self.assertRaises(ProcessLookupError): os.kill(int(output['stdout'].strip()), 0)

    def test_term_ignoring_host_requires_bounded_kill(self):
        def faster_test_cleanup(process, grace):
            self.assertEqual(grace, 10)
            return m.stop_group(process, grace=.05)
        value, _ = self.run_host('import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)',
                                 .1, stopper=faster_test_cleanup)
        self.assertTrue(value['host_cleanup_confirmed']); self.assertEqual(value['final_host_exit'], -signal.SIGKILL)
        self.assertIsNone(value['observed_command_exit'])

    def test_late_spawn_gets_no_new_window(self):
        tick = [0.0]
        def late_spawn(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs); tick[0] = 301.0; return process
        value, _ = self.run_host('import time;time.sleep(30)', 300, clock=lambda: tick[0], popen=late_spawn)
        self.assertEqual(value['reason'], 'command_deadline'); self.assertTrue(value['host_cleanup_confirmed'])

    def test_delayed_entry_refuses_partial_window_before_spawn(self):
        popen = Mock()
        value, _ = m.observe(['never started'], 300, work_deadline=319, clock=lambda: 20, popen=popen)
        popen.assert_not_called(); self.assertFalse(value['attempted'])
        self.assertTrue(value['host_cleanup_confirmed']); self.assertEqual(value['reason'], 'full_command_window_unavailable')


class SafeFiles(Temporary):
    def test_bounded_regular_file(self):
        p = Path('a'); p.write_bytes(b'abc'); self.assertEqual(m.read_file(p, 3), b'abc')
        with self.assertRaises(ValueError): m.read_file(p, 2)

    def test_link_and_hardlink_rejected(self):
        Path('a').write_bytes(b'abc'); Path('b').symlink_to('a')
        with self.assertRaises(ValueError): m.read_file(Path('b'), 3)
        os.link('a', 'c')
        with self.assertRaises(ValueError): m.read_file(Path('a'), 3)

    def test_fifo_rejected_without_blocking(self):
        os.mkfifo('a')
        with self.assertRaises(ValueError): m.read_file(Path('a'), 3)

    def test_staging_exact_allowlist_only(self):
        self.diagnostic(); (m.ROOT / 'stdout.bin').write_bytes(b'safe')
        Path('build/private').write_bytes(b'never upload'); m.stage()
        files = {p.name for p in Path('build/mini-direct-upload').iterdir()}
        self.assertNotIn('private', files); self.assertIn('iPadMini-direct-xctest-stdout.bin', files)

    def test_staging_rejects_oversize_and_symlink(self):
        self.diagnostic(); (m.ROOT / 'stdout.bin').write_bytes(b'x' * 65537)
        with self.assertRaises(ValueError): m.stage()

    def test_staging_rejects_linked_source(self):
        self.diagnostic(); Path('private').write_bytes(b'private')
        (m.ROOT / 'stdout.bin').symlink_to(Path('private').resolve())
        with self.assertRaises(ValueError): m.stage()

    def product_tree(self):
        root = Path('build/simulator/Build/Products')
        (root / 'Debug-iphonesimulator/TouchColorUITests-Runner.app').mkdir(parents=True)
        (root / 'TouchColor_iphonesimulator27.0-arm64.xctestrun').write_bytes(b'configuration')
        (root / 'Debug-iphonesimulator/TouchColorUITests-Runner.app/code').write_bytes(b'runner')
        return root

    def test_product_fingerprint_binds_runner_and_configuration(self):
        root = self.product_tree()
        with patch.object(m, 'product_identity', return_value={'app': 'test'}):
            before = m.products()
            (root / 'Debug-iphonesimulator/TouchColorUITests-Runner.app/code').write_bytes(b'changed runner')
            after = m.products()
        self.assertNotEqual(before['tree_sha256'], after['tree_sha256'])

    def test_product_fingerprint_rejects_links(self):
        root = self.product_tree(); (root / 'linked').symlink_to('/tmp', target_is_directory=True)
        with self.assertRaises(ValueError): m.products()

    def test_product_fingerprint_requires_one_configuration(self):
        root = self.product_tree(); (root / 'second.xctestrun').write_bytes(b'extra')
        with self.assertRaises(ValueError): m.products()

    def test_product_fingerprint_does_not_reset_its_deadline(self):
        self.product_tree(); ticks = iter([0, 11])
        with self.assertRaises(ValueError): m.products(clock=lambda: next(ticks))


class SourceContracts(unittest.TestCase):
    def test_exact_build_argv_with_logging_only_quiet(self):
        self.assertEqual(m.BUILD, ['xcodebuild', '-quiet', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor',
                                 '-configuration', 'Debug', '-destination', 'generic/platform=iOS Simulator',
                                 '-derivedDataPath', 'build/simulator', 'build-for-testing'])
        self.assertFalse(any('CODE_SIGNING' in part for part in m.BUILD))

    def test_unchanged_case_allowances_and_selection(self):
        args = m.test_argv(IDENTITY['udid'])
        self.assertEqual(args[args.index('-default-test-execution-time-allowance') + 1], '180')
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance') + 1], '240')
        self.assertEqual([a for a in args if a.startswith('-only-testing:')], ['-only-testing:' + m.CASE])
        self.assertEqual(args[-1], 'test-without-building')

    def test_no_new_device_lifecycle_or_fixture_operation(self):
        source = (SOURCE / 'scripts/mini_direct_xctest.py').read_text()
        for action in ('launch', 'terminate', 'shutdown', 'delete', 'erase', 'addmedia', 'spawn', 'create'):
            self.assertNotIn("'simctl', '" + action + "'", source)
        self.assertNotIn('PaletteFixtures.app', source)
        self.assertIn('device = w.select()', source)

    def test_exact_case_source_and_setup_are_unchanged_dependencies(self):
        test = (SOURCE / 'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        self.assertIn('- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }', test)
        self.assertIn('[self.app launch];', test)
        self.assertIn('self.continueAfterFailure=NO;', test)

    def test_workflow_single_push_only_original_job(self):
        import yaml
        value = yaml.load((SOURCE / '.github/workflows/mini-direct-xctest.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(value['on'], {'push': {'branches': ['codex/mini-direct-xctest']}})
        self.assertEqual(list(value['jobs']), ['mini-direct-xctest'])
        job = value['jobs']['mini-direct-xctest']; self.assertEqual(job['timeout-minutes'], '20')
        self.assertEqual(job['runs-on'], 'xcode-27'); self.assertNotIn('strategy', job)
        index = next(i for i, s in enumerate(job['steps']) if s.get('run') == 'python3 scripts/mini_direct_xctest.py diagnose')
        tail = job['steps'][index + 1:]
        self.assertEqual(len(tail), 3)
        self.assertFalse(any('simctl' in str(s) or 'xcodebuild' in str(s) for s in tail))

    def test_every_existing_workflow_excludes_proposed_branch(self):
        import yaml
        files = [p for p in (SOURCE / '.github/workflows').glob('*.yml') if p.name != 'mini-direct-xctest.yml']
        self.assertEqual(len(files), 4)
        for path in files:
            value = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            branches = value['on']['push']['branches']
            self.assertNotIn('codex/mini-direct-xctest', branches)
            self.assertFalse(any('*' in branch or '!' in branch for branch in branches))


class BuildQuietRegression(Temporary):
    def test_real_byte_limit_fixture_and_only_logging_delta(self):
        raw = (SOURCE / 'scripts/fixtures/mini-direct-67ba9e-byte-limit.json').read_bytes()
        fixture = json.loads(raw)
        self.assertEqual(fixture['sha'], '67ba9e823c817679fc40f7fcd2f83a79d13d0d37')
        self.assertEqual(fixture['run_id'], '37342854262')
        stage = fixture['preparation_commands'][-1]
        self.assertEqual(stage['reason'], 'byte-limit')
        self.assertIsNone(stage['exit'])
        self.assertTrue(stage['host_cleanup_confirmed'])
        self.assertEqual(stage['elapsed_seconds'], 95.797)
        self.assertEqual(stage['allowance_seconds'], 300)
        self.assertEqual([part for part in m.BUILD if part != '-quiet'], fixture['build_argv'])
        self.assertEqual(m.BUILD.count('-quiet'), 1)
        self.assertNotIn('-quiet', m.test_argv(IDENTITY['udid']))

    def test_build_byte_limit_still_stops_before_device_or_xctest(self):
        d = self.diagnostic(); commands = []
        def capture(command, **kwargs):
            commands.append(command)
            self.assertEqual(kwargs['cap'], 1_000_000)
            self.assertEqual(kwargs['cleanup_grace'], 10)
            if command == m.BUILD: raise m.CaptureStopped('byte-limit', True)
            output = b'a' * 40 + b'\n' if command[:2] == ['git', 'rev-parse'] else (
                b'Xcode 27.0\nBuild version 27A266a\n' if command == ['xcodebuild', '-version'] else b'')
            return subprocess.CompletedProcess(command, 0, output, b'')
        with patch.object(m, 'capture', side_effect=capture), patch.object(d, 'execute') as execute:
            self.assertEqual(d.run(), 3)
        self.assertEqual(commands[-1], m.BUILD)
        self.assertEqual(len(commands), 4)
        execute.assert_not_called()
        self.assertTrue(m.PENDING.exists()); self.assertTrue(m.STOP.exists())
        self.assertFalse(d.report['warmup_accepted']); self.assertFalse(d.report['full_row_accepted'])
        self.assertEqual(d.report['preparation_commands'][-1]['reason'], 'byte-limit')

    def test_quiet_build_retains_nonzero_exit_and_warning_error_bytes(self):
        d = self.diagnostic()
        value = subprocess.CompletedProcess(m.BUILD, 65, b'warning: test warning\n', b'error: test error\n')
        with patch.object(m, 'capture', return_value=value) as capture:
            result = d.setup_runner(m.BUILD, timeout=300)
        self.assertEqual(result.returncode, 65)
        self.assertEqual((m.ROOT / 'build-stdout.bin').read_bytes(), b'warning: test warning\n')
        self.assertEqual((m.ROOT / 'build-stderr.bin').read_bytes(), b'error: test error\n')
        self.assertEqual(capture.call_args.kwargs['cap'], 1_000_000)
        self.assertLessEqual(capture.call_args.kwargs['seconds'], 300)
        self.assertEqual(d.report['preparation_commands'][-1]['exit'], 65)


if __name__ == '__main__': unittest.main()
