"""Synthetic post-hosted handoff regressions; never execute an Apple command."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import palette_lifecycle_diagnostics as capture_module
import uikit_managed_device as device_module
import uikit_managed_tests as managed
from test_uikit_managed_device import ManagedFixture, NEW, OTHER
from uikit_runtime_diagnostics import MAX_OUTPUT_BYTES, MAX_PREPARATION_OUTPUT_BYTES


class FixtureHandoff(ManagedFixture):
    def setUp(self):
        super().setUp()
        self.create()
        self.binding = device_module.read_binding('iPadMini')
        self.setup = {'schema': 1, 'binding': self.binding, 'products': {'synthetic': True}}
        self.identity_bytes = self.paths()[0].read_bytes()
        self.binding_bytes = self.paths()[1].read_bytes()
        fields = {'result': 'Passed', 'totalTestCount': 53, 'passedTests': 53,
                  'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0,
                  'qualified': True, 'device': NEW}
        self.hosted = {'schema': 1, 'suite': 'TouchColorTests', 'setup': self.setup, 'qualified': True,
            'command': {'status': 'timely_exit', 'exit_code': 0, 'host_cleanup_confirmed': True},
            'summary': {'status': 'complete', 'fields': fields}}
        self.hosted_path = managed.record_path('iPadMini', 'TouchColorTests')
        self.hosted_path.write_text(json.dumps(self.hosted))
        self.container = Path('build/synthetic-container').resolve()
        documents = self.container / 'Documents'; documents.mkdir(parents=True)
        (documents / 'TouchColor-Ordered-Colors.json').write_text('["#445566", "#445566", "#AABBCC"]')
        self.states = ['Shutdown', 'Booted']
        self.inventories = []
        self.calls = []
        self.action = None
        self.output = io.StringIO()
        self.tick = 100
        self.controller = managed.ManagedWarmup('iPadMini', started=100, clock=lambda: self.tick,
                                                host_runner=self.runner)

    def runner(self, command, *, timeout):
        self.calls.append((list(command), timeout))
        self.assertTrue(self.controller.pending.is_file())
        self.tick += .01
        if self.action:
            returned = self.action(command, timeout)
            if returned is not None:
                return returned
        if command == ['git', 'rev-parse', 'HEAD']:
            output = self.binding['context']['sha']
        elif command == device_module.READBACK:
            output = json.dumps(self.inventories.pop(0) if self.inventories else self.after(state=self.states.pop(0)))
        elif command[:3] == ['xcrun', 'simctl', 'get_app_container']:
            output = str(self.container)
        else:
            output = ''
        if command[:3] == ['xcrun', 'simctl', 'addmedia']:
            self.assertTrue(Path(command[-1]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        return subprocess.CompletedProcess(command, 0, output, '')

    def run_seed(self):
        import contextlib
        with patch.object(managed, 'ManagedWarmup', return_value=self.controller), \
                patch.object(managed, 'load_setup', return_value=copy.deepcopy(self.setup)), \
                contextlib.redirect_stdout(self.output):
            return managed.fixture_seed('iPadMini', started=100)

    def operations(self):
        return [command[2] if command[:2] == ['xcrun', 'simctl'] else command[0]
                for command, _ in self.calls]

    def failure(self):
        lines = [line for line in self.output.getvalue().splitlines()
                 if line.startswith('UIKIT_PREPARATION_FAILURE:')]
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0].split(':', 1)[1])

    def no_seed(self):
        self.assertFalse(managed.record_path('iPadMini', 'fixtures').exists())
        self.assertFalse(Path('build/iPadMini-fixture-seeded').exists())
        self.assertNotIn('addmedia', self.operations())

    def assert_binding_unchanged(self):
        self.assertEqual(self.paths()[0].read_bytes(), self.identity_bytes)
        self.assertEqual(self.paths()[1].read_bytes(), self.binding_bytes)

    def test_shutdown_boots_once_waits_once_and_revalidates_same_booted(self):
        self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus', 'list',
            'install', 'launch', 'get_app_container', 'terminate', 'spawn', 'xcodebuild', 'addmedia'])
        grants = {command[2]: grant for command, grant in self.calls if command[:2] == ['xcrun', 'simctl']}
        self.assertEqual(grants['boot'], 180)
        self.assertEqual(grants['bootstatus'], 240)
        self.assertEqual(grants['install'], 90)
        self.assertFalse(self.controller.pending.exists())
        managed.require_fixtures('iPadMini', self.setup)
        self.assert_binding_unchanged()
        self.assertNotIn('UIKIT_PREPARATION_FAILURE:', self.output.getvalue())

    def test_already_booted_needs_no_boot_or_readiness_command(self):
        self.states = ['Booted']
        self.run_seed()
        self.assertEqual(self.operations()[:4], ['git', 'git', 'list', 'install'])
        self.assertNotIn('boot', self.operations()); self.assertNotIn('bootstatus', self.operations())
        self.assert_binding_unchanged()

    def test_hosted_cleanup_must_be_confirmed_before_any_command(self):
        self.hosted['command']['host_cleanup_confirmed'] = None
        self.hosted_path.write_text(json.dumps(self.hosted))
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.calls, []); self.no_seed()

    def test_hosted_failure_must_not_reach_inventory_or_boot(self):
        self.hosted['qualified'] = False
        self.hosted_path.write_text(json.dumps(self.hosted))
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.calls, []); self.no_seed()

    def test_source_mismatch_must_not_reach_inventory(self):
        self.action = lambda command, timeout: (subprocess.CompletedProcess(command, 0, 'foreign', '')
                                               if command[0] == 'git' else None)
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git']); self.no_seed()

    def test_unknown_state_stops_before_boot_install_or_seed(self):
        self.states = ['Booting']
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_duplicate_owned_inventory_is_not_selected(self):
        inventory = self.after(); inventory['devices'][device_module.RUNTIME] *= 2
        self.inventories = [inventory]
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_revalidated_shutdown_stops_before_install(self):
        self.states = ['Shutdown', 'Shutdown']
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_revalidated_different_uuid_stops_before_install(self):
        changed = self.after(state='Booted'); changed['devices'][device_module.RUNTIME][0]['udid'] = OTHER
        self.inventories = [self.after(), changed]
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_duplicate_state_key_stops_before_boot(self):
        def duplicate(command, timeout):
            if command == device_module.READBACK:
                raw = json.dumps(self.after()).replace('"state": "Shutdown"',
                                                       '"state": "Shutdown", "state": "Booted"')
                return subprocess.CompletedProcess(command, 0, raw, '')
        self.action = duplicate
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_duplicate_revalidated_owned_uuid_stops_before_install(self):
        changed = self.after(state='Booted'); changed['devices'][device_module.RUNTIME] *= 2
        self.inventories = [self.after(), changed]
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations()[-1], 'list'); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_current_binding_reader_keeps_unchanged_original_contract(self):
        self.states = ['Shutdown', 'Booted']
        state = device_module.read_managed_device_state('iPadMini', self.controller.command,
                                                       self.controller.require_time)
        self.assertEqual(state, {'binding': self.binding, 'state': 'Shutdown'})
        binding = device_module.read_managed_device('iPadMini', self.controller.command,
                                                    self.controller.require_time)
        self.assertEqual(binding, self.binding)
        self.assertEqual(set(binding['identity']), {'family', 'udid', 'runtime', 'started'})

    def test_binding_change_after_boot_stops_before_readiness(self):
        def mutate(command, timeout):
            if command[2:3] == ['boot']:
                self.paths()[0].write_text('{}')
        self.action = mutate
        with self.assertRaises(Exception): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_files_value_assertion_remains_required(self):
        (self.container / 'Documents/TouchColor-Ordered-Colors.json').write_text('["#445566"]')
        with self.assertRaises(managed.WarmupFailed): self.run_seed()
        self.no_seed()

    def test_extra_files_assertion_remains_required(self):
        (self.container / 'Documents/unrelated').write_text('not a fixture')
        with self.assertRaises(managed.WarmupFailed): self.run_seed()
        self.no_seed()

    def fail_at(self, operation, kind):
        def fail(command, timeout):
            if command[2:3] != [operation]: return None
            if kind == 'late':
                self.tick += timeout
                return subprocess.CompletedProcess(command, 0, '', 'Invalid device state\n')
            if kind == 'nonzero':
                return subprocess.CompletedProcess(command, 149, '', 'Unable to install app in current state: Shutdown\n')
            error = capture_module.CaptureStopped('duration-limit', kind == 'known_cleanup')
            if kind == 'unknown_cleanup': error.cleanup_confirmed = None
            error.stderr_prefix = b'Invalid device state\n'
            error.stderr_observed_bytes = len(error.stderr_prefix)
            raise error
        self.action = fail
        with self.assertRaises(Exception): self.run_seed()
        self.assertEqual(self.operations()[-1], operation)
        self.assertTrue(self.controller.pending.exists()); self.no_seed()
        previous = list(self.calls)
        with self.assertRaises(Exception): self.controller.command(device_module.READBACK, 30)
        self.assertEqual(self.calls, previous)
        return self.failure()

    def test_nonzero_boot_is_terminal_and_retains_exact_stderr(self):
        failure = self.fail_at('boot', 'nonzero')
        self.assertEqual(failure['command']['exit_code'], 149)
        self.assertTrue(failure['command']['host_cleanup_confirmed'])
        self.assertTrue(failure['stderr']['stream_complete'])
        self.assertFalse(failure['stderr']['truncated'])
        self.assertEqual(failure['stderr']['text'], 'Unable to install app in current state: Shutdown')

    def test_terminal_failure_cannot_emit_a_second_preparation_frame(self):
        self.fail_at('boot', 'nonzero')
        previous = list(self.calls)
        with self.assertRaises(ValueError):
            self.controller.fixture_command(['xcrun', 'simctl', 'boot', NEW], 180)
        self.assertEqual(self.calls, previous)
        self.failure()  # Still exactly one bounded frame.

    def test_nonzero_readiness_is_terminal(self): self.fail_at('bootstatus', 'nonzero')
    def test_nonzero_install_is_terminal(self): self.fail_at('install', 'nonzero')
    def test_late_boot_is_terminal(self): self.fail_at('boot', 'late')
    def test_late_readiness_is_terminal(self): self.fail_at('bootstatus', 'late')
    def test_unknown_boot_cleanup_is_terminal(self): self.fail_at('boot', 'unknown_cleanup')
    def test_unknown_readiness_cleanup_is_terminal(self): self.fail_at('bootstatus', 'unknown_cleanup')
    def test_unconfirmed_boot_cleanup_is_terminal(self): self.fail_at('boot', 'unconfirmed_cleanup')
    def test_unconfirmed_readiness_cleanup_is_terminal(self): self.fail_at('bootstatus', 'unconfirmed_cleanup')
    def test_confirmed_host_cleanup_does_not_authorize_boot_continuation(self):
        failure = self.fail_at('boot', 'known_cleanup')
        self.assertIs(failure['command']['host_cleanup_confirmed'], True)
        self.assertFalse(failure['stderr']['stream_complete'])
        self.assertEqual(failure['simulator_completion'], 'not_inferred')

    def test_boot_and_readiness_consume_original_fixture_clock(self):
        def advance(command, timeout):
            if command[2:3] == ['boot']: self.tick += 179
            if command[2:3] == ['bootstatus']: self.tick += 239
        self.action = advance
        self.run_seed()
        self.assertEqual(self.controller.deadline, 700)
        self.assertEqual(self.operations().count('boot'), 1)
        self.assertEqual(self.operations().count('bootstatus'), 1)

    def test_near_deadline_boot_grant_is_clipped_and_no_readiness_after_expiry(self):
        self.tick = 679
        def advance(command, timeout):
            if command[2:3] == ['boot']: self.tick += timeout
        self.action = advance
        with self.assertRaises(Exception): self.run_seed()
        self.assertEqual(self.operations()[-1], 'boot')
        self.assertAlmostEqual(self.calls[-1][1], .97)
        self.assertTrue(self.controller.pending.exists()); self.no_seed()

    def test_expired_marker_write_never_dispatches_boot(self):
        original = Path.open
        controller = self.controller
        fixture = self
        class DelayedMarker:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def write(self, data):
                fixture.tick += 181
                return self.stream.write(data)
            def __exit__(self, *args): self.stream.close()
        def opening(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            if path == controller.pending and args == ('x',) and len(fixture.calls) == 3:
                return DelayedMarker(stream)
            return stream
        with patch.object(Path, 'open', new=opening), self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list'])
        self.assertTrue(self.controller.pending.exists()); self.no_seed()
        failure = self.failure()
        self.assertIsNone(failure['command']['exit_code'])
        self.assertFalse(failure['stderr']['available'])

    def test_marker_overhead_is_subtracted_from_boot_grant(self):
        original = Path.open
        controller = self.controller
        fixture = self
        class DelayedMarker:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def write(self, data):
                fixture.tick += 10
                return self.stream.write(data)
            def __exit__(self, *args): self.stream.close()
        def opening(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            if path == controller.pending and args == ('x',) and len(fixture.calls) == 3:
                return DelayedMarker(stream)
            return stream
        with patch.object(Path, 'open', new=opening): self.run_seed()
        boot = next(grant for command, grant in self.calls if command[2:3] == ['boot'])
        self.assertAlmostEqual(boot, 170)
        self.assertEqual(self.controller.deadline, 700)

    def test_late_revalidated_inventory_stops_before_install(self):
        reads = []
        def late(command, timeout):
            if command == device_module.READBACK:
                reads.append(command)
                if len(reads) == 2: self.tick += timeout
        self.action = late
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations()[-1], 'list'); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_failure_before_dispatch_retains_unknown_stderr_and_cleanup(self):
        def fail(command, timeout):
            if command[2:3] == ['boot']: raise OSError('SECRET_SENTINEL')
        self.action = fail
        with self.assertRaises(OSError): self.run_seed()
        value = self.failure()
        self.assertFalse(value['stderr']['available'])
        self.assertIsNone(value['command']['host_cleanup_confirmed'])
        self.assertNotIn('SECRET_SENTINEL', self.output.getvalue())
        self.no_seed()

    def test_failed_install_evidence_is_bound_and_redacted_with_hashes(self):
        raw = (b'An error was encountered processing the command (domain=com.apple.CoreSimulator.SimError, code=405):\n'
               b'Unable to install app in current state: Shutdown\n'
               b'/Users/private/path token=SECRET_SENTINEL\n')
        def fail(command, timeout):
            if command[2:3] == ['install']:
                result = subprocess.CompletedProcess(command, 149, '', raw.decode())
                result.stderr_prefix = raw; result.stderr_observed_bytes = len(raw)
                return result
        self.action = fail
        with self.assertRaises(Exception): self.run_seed()
        failure = self.failure()
        self.assertEqual(failure['source'], self.binding['context'])
        self.assertEqual(failure['deviceId'], NEW)
        self.assertEqual(failure['command']['argv'], self.calls[-1][0])
        self.assertEqual(failure['stderr']['captured_prefix_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(failure['stderr']['omitted_lines'], 1)
        self.assertNotIn('SECRET_SENTINEL', self.output.getvalue())
        self.assertNotIn('/Users/private', self.output.getvalue())

    def test_bounded_stderr_prefix_and_frame_share_existing_total(self):
        raw = b'Invalid device state\n' * 1000
        observation = {'argv': ['xcrun', 'simctl', 'boot', NEW], 'exit_code': 1,
            'host_cleanup_confirmed': True, 'stderr_complete': True,
            'stderr_prefix': raw[:4096], 'stderr_observed_bytes': len(raw)}
        line = managed.preparation_failure(self.binding, observation, 'WarmupFailed')
        failure = json.loads(line.split(':', 1)[1])
        self.assertTrue(failure['stderr']['truncated'])
        self.assertEqual(failure['stderr']['captured_prefix_bytes'], 4096)
        self.assertLessEqual(len(line.encode()) + 128, MAX_PREPARATION_OUTPUT_BYTES)
        self.assertEqual(MAX_OUTPUT_BYTES + MAX_PREPARATION_OUTPUT_BYTES, 32768)

    def test_unknown_incomplete_tail_cannot_be_mistaken_for_safe_error(self):
        raw = b'Invalid device state'
        observation = {'argv': ['xcrun', 'simctl', 'boot', NEW], 'exit_code': None,
            'host_cleanup_confirmed': None, 'stderr_complete': False,
            'stderr_prefix': raw, 'stderr_observed_bytes': len(raw)}
        value = json.loads(managed.preparation_failure(self.binding, observation, 'CaptureStopped').split(':', 1)[1])
        self.assertEqual(value['stderr']['text'], '')
        self.assertEqual(value['stderr']['omitted_lines'], 1)


class CaptureFailureEvidence(unittest.TestCase):
    def test_new_handoff_regressions_are_in_existing_canonical_prerequisite(self):
        source = (Path(__file__).resolve().parents[1]/'.github/workflows/ios.yml').read_text()
        prerequisite = source.split('  compile-prerequisites:\n', 1)[1].split('  compatibility:\n', 1)[0]
        command = next(line for line in prerequisite.splitlines() if 'PYTHONPATH=scripts python3 -m unittest ' in line)
        self.assertEqual(command.split().count('test_uikit_fixture_handoff'), 1)
        for module in ('test_uikit_runtime_diagnostics', 'test_palette_lifecycle_diagnostics',
                       'test_uikit_picker_geometry', 'test_uikit_warmup', 'test_uikit_managed_device',
                       'test_uikit_managed_tests', 'test_uikit_palette_readiness'):
            self.assertIn(module, command.split())

    def test_overflow_chunk_is_observed_but_prefix_stays_within_cap(self):
        command = [sys.executable, '-c', "import os;os.write(2,b'123456')"]
        with self.assertRaises(capture_module.CaptureStopped) as raised:
            capture_module.capture(command, seconds=3, cap=5)
        error = raised.exception
        self.assertEqual(str(error), 'byte-limit')
        self.assertTrue(error.cleanup_confirmed)
        self.assertEqual(error.stderr_observed_bytes, 6)
        self.assertEqual(error.stderr_prefix, b'12345')

    def test_actual_owned_capture_retains_bounded_prefix_without_complete_claim(self):
        command = [sys.executable, '-c',
            "import sys,time;sys.stderr.write('Invalid device state\\n' * 1000);sys.stderr.flush();time.sleep(5)"]
        with self.assertRaises(capture_module.CaptureStopped) as raised:
            capture_module.capture(command, seconds=.2, cap=1000000)
        error = raised.exception
        self.assertTrue(error.cleanup_confirmed)
        self.assertEqual(len(error.stderr_prefix), 4096)
        self.assertEqual(error.stderr_observed_bytes, 21000)

    def test_setup_capture_preserves_original_stderr_bytes_before_utf8_decoding(self):
        raw = b'Invalid device state\n\xff'
        with patch.object(managed, 'capture', return_value=subprocess.CompletedProcess([], 149, b'', raw)):
            result = managed.setup_capture(['synthetic'], 1)
        self.assertEqual(result.stderr_prefix, raw)
        self.assertEqual(result.stderr_observed_bytes, len(raw))


if __name__ == '__main__': unittest.main()
