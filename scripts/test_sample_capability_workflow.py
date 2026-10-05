"""Portable contract tests for the isolated one-job phase-0 workflow only."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import run_sample_capability_ci as ci


class WorkflowContractTests(unittest.TestCase):
    def test_only_initial_diagnostic_push_one_standard_five_minute_job(self):
        text = (ci.ROOT / ci.WORKFLOW).read_text()
        self.assertIn('on:\n  push:\n    branches: [codex/sample-capability-probe]\npermissions:', text)
        self.assertNotIn('workflow_dispatch', text)
        self.assertNotIn('pull_request', text)
        self.assertNotIn('schedule:', text)
        self.assertEqual(text.count('    runs-on:'), 1)
        self.assertIn('    runs-on: xcode-27\n    timeout-minutes: 5\n', text)
        self.assertIn("if: github.event.created == false && github.event.forced == false && github.event.before == 'a6ea406d51e38319b76d19a5a5417b72cec857f4' && github.run_attempt == 1", text)
        self.assertNotIn('matrix:', text)
        self.assertIn('cancel-in-progress: false', text)

    def test_pinned_actions_and_no_persisted_credentials_or_custom_secrets(self):
        text = (ci.ROOT / ci.WORKFLOW).read_text()
        actions = [line.strip() for line in text.splitlines() if 'uses:' in line]
        self.assertEqual(actions, [
            'uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683',
            'uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'])
        self.assertIn('permissions:\n  contents: read\n', text)
        self.assertIn('persist-credentials: false', text)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('secrets:', text)

    def test_exact_source_and_ref_workflow_guards(self):
        text = (ci.ROOT / ci.WORKFLOW).read_text()
        for guard in ('test "$GITHUB_REF" = refs/heads/codex/sample-capability-probe',
                      'test "$GITHUB_WORKFLOW_SHA" = "$GITHUB_SHA"',
                      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
                      'test "$(git rev-parse HEAD^)" = ' + ci.BASE,
                      'test -z "$(git status --porcelain=v1 --untracked-files=all)"'):
            self.assertIn(guard, text)
        self.assertIn('root="$(pwd -P)"', text)
        self.assertIn('/usr/bin/python3 -I -S', text)
        self.assertIn('os.path.realpath(sys.executable)', text)
        self.assertNotIn('chmod', text)

    def test_frozen_helpers_identical(self):
        for name, expected in ci.FROZEN.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ci.ROOT / name).read_bytes()).hexdigest(), expected)

    def test_existing_full_workflows_cannot_match_diagnostic_push(self):
        for name in ('apple-platforms.yml', 'ios.yml'):
            text = (ci.ROOT / '.github/workflows' / name).read_text()
            triggers = text.split('permissions:', 1)[0]
            self.assertIn('on:\n  push:\n    branches: [codex/platform-integration]\n  workflow_dispatch:\n', triggers)
            self.assertNotIn('sample-capability-probe', triggers)
            self.assertNotIn('pull_request', triggers)

    def test_receipt_allowlist_budget_and_one_day_retention(self):
        text = (ci.ROOT / ci.WORKFLOW).read_text()
        self.assertIn("if: always() && steps.probe.outputs.artifact_ready == 'true'", text)
        self.assertIn('retention-days: 1', text)
        self.assertIn('compression-level: 0', text)
        self.assertIn('if-no-files-found: error', text)
        self.assertEqual(set(ci.CAPS), {'normal.json', 'optimized.json', 'capability.json', 'receipt.json'})
        self.assertLessEqual(sum(ci.CAPS.values()) + 4096, 128000)
        self.assertEqual(ci.TOTAL_CAP, 128000)

    def test_artifact_guard_rejects_names_links_permissions_and_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / 'receipt.json'
            path.write_bytes(b'{}\n')
            path.chmod(0o600)
            self.assertEqual(ci.artifact_guard(directory), 3)
            path.write_bytes(b'x' * (ci.CAPS['receipt.json'] + 1))
            with self.assertRaises(ci.Closed):
                ci.artifact_guard(directory)
            path.write_bytes(b'{}\n')
            path.chmod(0o644)
            with self.assertRaises(ci.Closed):
                ci.artifact_guard(directory)
            path.chmod(0o600)
            alias = directory / 'capability.json'
            alias.symlink_to(path)
            with self.assertRaises(ci.Closed):
                ci.artifact_guard(directory)
            alias.unlink()
            unknown = directory / 'raw.log'
            unknown.write_bytes(b'forbidden')
            with self.assertRaises(ci.Closed):
                ci.artifact_guard(directory)

    def test_serialized_receipt_bound_and_explicit_twenty_seven_test_contract(self):
        with self.assertRaises(ci.Closed):
            ci.encode_receipt({'body': 'x' * 12000}, 12000)
        import inspect
        self.assertIn("summary['testsRun'] == 27", inspect.getsource(ci.child_operation))
        self.assertIn("not summary['skipped']", inspect.getsource(ci.child_operation))
        self.assertNotIn('TextTestRunner', inspect.getsource(ci._perform_tests))

    def test_unexpected_wrapper_overrun_never_hard_kills_or_claims_exit(self):
        child = Mock()
        with patch.object(ci.subprocess, 'Popen', return_value=child), \
                patch.object(ci, 'DEADLINES', {'normal': 0.1}), \
                patch.object(ci, 'DEFER_GRACE', 0.1), \
                patch.object(ci, 'FINAL_GRACE', 0.1), \
                patch.object(ci.time, 'monotonic', side_effect=[0, 2, 2, 3]):
            result = ci.run_owned_operation('normal', Path('/unused'), Path('/unused/output'))
        self.assertEqual(result, {'returncode': None, 'cancelled': False,
                                  'overrun': True, 'childExited': False})
        child.send_signal.assert_called_once_with(signal.SIGTERM)
        child.kill.assert_not_called()
        child.terminate.assert_not_called()

    def test_main_stops_after_unconfirmed_child_and_never_uploads_live_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'github-output'
            with patch.dict(os.environ, {'RUNNER_TEMP': temporary, 'GITHUB_OUTPUT': str(output)}), \
                    patch.object(ci, 'source_guard', return_value={'fixed': 'source'}), \
                    patch.object(ci, 'digest', return_value={'fixed': 'identity'}), \
                    patch.object(ci.sys, 'platform', 'darwin'), \
                    patch.object(ci.sys, 'executable', str(Path(sys.executable).resolve())), \
                    patch.object(ci, 'run_owned_operation', return_value={'returncode': None,
                        'cancelled': False, 'overrun': True, 'childExited': False}) as run, \
                    patch.object(ci.shutil, 'rmtree') as cleanup:
                self.assertEqual(ci.main(), 1)
                run.assert_called_once()
                cleanup.assert_not_called()
            self.assertFalse(output.exists())

    def test_runner_never_exposes_target_or_fallback(self):
        text = (ci.ROOT / 'scripts/run_sample_capability_ci.py').read_text()
        self.assertEqual(text.count("'--inspect-installed-help'"), 1)
        self.assertNotIn('sudo', text)
        self.assertNotIn('shell=True', text)
        self.assertNotIn('os.chmod', text)
        self.assertNotIn('TOOL_OWNERS =', text)
        self.assertIn("'sampleCliAttempts': 0", text)
        self.assertIn("receipt['sampleCliAttempts'] = 1", text)
        self.assertEqual(ci.DEADLINES, {'normal': 20.0, 'optimized': 20.0, 'help': 12.0})
        self.assertEqual(ci.DEFER_GRACE, 8.0)
        self.assertEqual(ci.FINAL_GRACE, 8.0)
        self.assertNotIn('process.kill(', text)
        self.assertNotIn('pthread_sigmask', text)
        self.assertIn("first_failure = first_failure or", text)

class FixedOperationContainmentTests(unittest.TestCase):
    def exercise(self, mode, trigger, phase):
        # Only test-side code substitutes an owned synthetic body into the actual
        # fixed child wrapper. The real parent argv builder/controller is used.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            output = directory / ('capability.json' if mode == 'help' else mode + '.json')
            producer_pid = directory / 'owned-producer.pid'
            active = directory / 'active'
            cleanup = directory / 'cleanup'
            reaped = directory / 'reaped.json'
            child = directory / 'owned-child.py'
            controller = directory / 'owned-controller.py'
            result = directory / 'controller.json'
            child.write_text(f'''
import json, os, pathlib, signal, sys, time
sys.path.insert(0, {str(ci.ROOT / 'scripts')!r})
import run_sample_capability_ci as ci
p = ci.probe
python = str(pathlib.Path(sys.executable).resolve())
p.TOOL_OWNERS = frozenset((0, os.getuid(), os.stat(python).st_uid))
ci.DEADLINES = dict.fromkeys(ci.DEADLINES, {0.2 if trigger == 'deadline' and phase == 'active' else 0.7 if trigger == 'deadline' else 10.0})
original_stop = p._stop_owned_unreaped_group

def stop(process):
    pathlib.Path({str(cleanup)!r}).write_text('ready')
    time.sleep(0.35)
    value = original_stop(process)
    try:
        os.waitpid(process.pid, os.WNOHANG)
        was_reaped = False
    except ChildProcessError:
        was_reaped = True
    pathlib.Path({str(reaped)!r}).write_text(json.dumps({{'cleanup': value, 'reaped': was_reaped}}))
    return value
p._stop_owned_unreaped_group = stop

def fixture(*ignored):
    source = "import os,pathlib,signal,time; " + \\
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); " + \\
        "pathlib.Path({str(producer_pid)!r}).write_text(str(os.getpid())); " + \\
        "pathlib.Path({str(active)!r}).write_text('ready'); time.sleep(30)"
    p.run_bounded([python, '-I', '-S', '-c', source], pathlib.Path({str(directory)!r}),
                  interpreter=python, timeout=0.55)
    raise RuntimeError('Cancellation was not delivered')
ci._perform_tests = fixture
ci._perform_help = fixture
raise SystemExit(ci.child_operation(sys.argv[2], pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4])))
''')
            controller.write_text(f'''
import json, pathlib, sys
sys.path.insert(0, {str(ci.ROOT / 'scripts')!r})
import run_sample_capability_ci as ci
ci.OPERATION_SCRIPT = pathlib.Path({str(child)!r})
ci.DEADLINES = dict.fromkeys(ci.DEADLINES, {0.2 if trigger == 'deadline' and phase == 'active' else 0.7 if trigger == 'deadline' else 10.0})
answer = ci.run_owned_operation({mode!r}, pathlib.Path({str(directory)!r}), pathlib.Path({str(output)!r}))
pathlib.Path({str(result)!r}).write_text(json.dumps(answer))
''')
            proc = subprocess.Popen([str(Path(sys.executable).resolve()), '-I', '-S', '-B',
                                     str(controller)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if trigger != 'deadline':
                marker = active if phase == 'active' else cleanup
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), 'Owned operation never reached the requested phase')
                proc.send_signal(signal.SIGINT if trigger == 'interrupt' else signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=12), 0)
            answer = json.loads(result.read_text())
            self.assertTrue(answer['childExited'])
            self.assertFalse(answer['overrun'])
            self.assertNotEqual(answer['returncode'], 0)
            self.assertEqual(answer['cancelled'], trigger != 'deadline')
            self.assertEqual(json.loads(reaped.read_text()), {'cleanup': True, 'reaped': True})
            pid = int(producer_pid.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            report = json.loads(output.read_text())
            self.assertEqual(report['status'], 'unavailable')
            reason = report['reason'] if mode == 'help' else report['firstFailure']
            self.assertEqual(reason, 'operation_deadline' if trigger == 'deadline' else 'operation_cancelled')
            if mode == 'help':
                self.assertFalse(report['captureAttempted'])
                self.assertFalse(report['targetCreated'])
                self.assertNotIn('help', report)
            else:
                self.assertFalse(report['passed'])
                self.assertTrue(report['ownedCleanupConfirmed'])

    def test_deadline_during_active_producer_and_cleanup_all_fixed_modes(self):
        for mode in ('normal', 'optimized', 'help'):
            for phase in ('active', 'cleanup'):
                with self.subTest(mode=mode, phase=phase):
                    self.exercise(mode, 'deadline', phase)

    def test_interrupt_during_active_producer_and_cleanup_all_fixed_modes(self):
        for mode in ('normal', 'optimized', 'help'):
            for phase in ('active', 'cleanup'):
                with self.subTest(mode=mode, phase=phase):
                    self.exercise(mode, 'interrupt', phase)

    def test_terminate_during_active_producer_and_cleanup_all_fixed_modes(self):
        for mode in ('normal', 'optimized', 'help'):
            for phase in ('active', 'cleanup'):
                with self.subTest(mode=mode, phase=phase):
                    self.exercise(mode, 'terminate', phase)


if __name__ == '__main__':
    unittest.main()
