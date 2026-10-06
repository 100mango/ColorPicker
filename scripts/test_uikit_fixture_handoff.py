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
        fields = {'result': 'Passed', 'totalTestCount': 54, 'passedTests': 54,
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
        self.bootstatus = ('Monitoring boot status for '+self.binding['receipt']['requested_name']+' ('+NEW+').\n'
            '[2026-10-06 01:04:59 +0000] Status=4, isTerminal=NO, Elapsed=00:47.\n'
            '\tWaiting on System App\n\n'
            '[2026-10-06 01:05:15 +0000] Status=4294967295, isTerminal=YES, Elapsed=01:03.\n'
            '\tFinished\n\n')
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
        elif command[:3] == ['xcrun', 'simctl', 'bootstatus']:
            output = self.bootstatus
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

    def test_shutdown_boots_once_observes_completion_without_postboot_global_inventory(self):
        self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus',
            'install', 'launch', 'get_app_container', 'terminate', 'addmedia'])
        grants = {command[2]: grant for command, grant in self.calls if command[:2] == ['xcrun', 'simctl']}
        self.assertEqual(grants['boot'], 180)
        self.assertEqual(grants['bootstatus'], 240)
        self.assertLessEqual(grants['install'], 90)
        self.assertAlmostEqual(grants['install'], 90)
        self.assertFalse(self.controller.pending.exists())
        managed.require_fixtures('iPadMini', self.setup)
        self.assert_binding_unchanged()
        self.assertNotIn('UIKIT_PREPARATION_FAILURE:', self.output.getvalue())

    def test_container_scope_and_omitted_diagnostic_preserve_required_command_order(self):
        self.run_seed()
        app = 'com.mango.touchColor.tests.paletteFixtures'
        expected = [
            (['xcrun', 'simctl', 'install', NEW,
              'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90),
            (['xcrun', 'simctl', 'launch', '--terminate-running-process', NEW, app], 60),
            (['xcrun', 'simctl', 'get_app_container', NEW, app, 'data'], 60),
            (['xcrun', 'simctl', 'terminate', NEW, app], 30)]
        for (argv, grant), (expected_argv, cap) in zip(self.calls[5:9], expected):
            self.assertEqual(argv, expected_argv)
            self.assertAlmostEqual(grant, cap)
        self.assertEqual(self.operations().count('get_app_container'), 1)
        self.assertFalse(any('xcodebuild' in argv or '-showdestinations' in argv or 'launchctl' in argv for argv, _ in self.calls))
        output = self.output.getvalue()
        self.assertEqual(output.count('Optional simulator service listing diagnostic: not collected\n'), 1)
        self.assertEqual(output.count('Optional destination enumeration diagnostic: not collected\n'), 1)
        self.assertLess(output.index('Synthetic Files fixture is ready'),
                        output.index('Optional destination enumeration diagnostic: not collected'))
        self.assertLess(output.index('Optional destination enumeration diagnostic: not collected'),
                        output.index('Synthetic photo seed complete'))
        self.assertEqual(self.controller.deadline, 700)
        managed.require_fixtures('iPadMini', self.setup)

    def container_admission_at(self, remaining):
        self.tick = self.controller.deadline - remaining - 1
        def at_launch(command, timeout):
            if command[2:3] == ['launch']:
                self.tick = self.controller.deadline - remaining
        self.action = at_launch

    def test_container_admission_accepts_exact_full_sixty_and_twenty_cleanup(self):
        self.container_admission_at(80)
        self.run_seed()
        self.assertAlmostEqual(next(grant for argv, grant in self.calls if argv[2:3] == ['get_app_container']), 60)
        self.assertEqual(self.controller.deadline, 700)
        managed.require_fixtures('iPadMini', self.setup)

    def test_container_admission_accepts_just_above_full_sixty_and_twenty_cleanup(self):
        self.container_admission_at(80.001)
        self.run_seed()
        self.assertAlmostEqual(next(grant for argv, grant in self.calls if argv[2:3] == ['get_app_container']), 60)
        self.assertEqual(self.controller.deadline, 700)

    def test_container_admission_rejects_just_below_full_grant_before_dispatch(self):
        self.container_admission_at(79.999)
        with patch.object(self.controller, 'fixture') as fixture, \
                self.assertRaisesRegex(ValueError, 'Full fixture container lookup and cleanup cannot fit'):
            self.run_seed()
        fixture.assert_not_called()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus', 'install', 'launch'])
        self.assertFalse(self.controller.pending.exists())  # The refused query was never started.
        self.assertEqual(self.controller.deadline, 700)
        self.no_seed(); self.assert_binding_unchanged()

    def delayed_container_marker(self, seconds):
        original = Path.open
        fixture = self
        class DelayedMarker:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def write(self, data):
                fixture.tick += seconds
                return self.stream.write(data)
            def __exit__(self, *args): self.stream.close()
        def opening(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            if path == fixture.controller.pending and args == ('x',) and fixture.operations()[-1:] == ['launch']:
                return DelayedMarker(stream)
            return stream
        return patch.object(Path, 'open', new=opening)

    def assert_container_fenced(self):
        self.assertTrue(self.controller.pending.exists())
        self.no_seed(); self.assert_binding_unchanged()
        previous = list(self.calls)
        with self.assertRaises(Exception): self.controller.command(device_module.READBACK, 30)
        with self.assertRaises(Exception): self.controller.shutdown(NEW)
        with self.assertRaises(managed.WarmupFailed):
            managed.ManagedWarmup('iPadMini', started=100, clock=lambda: self.tick, host_runner=self.runner)
        self.assertEqual(self.calls, previous)
        self.assertNotIn('Synthetic Files fixture is ready', self.output.getvalue())
        self.assertEqual(self.controller.deadline, 700)

    def test_container_marker_overhead_reduces_sixty_without_reset_or_cleanup_lending(self):
        self.container_admission_at(80)
        with self.delayed_container_marker(10): self.run_seed()
        self.assertEqual(next(grant for argv, grant in self.calls if argv[2:3] == ['get_app_container']), 50)
        self.assertEqual(self.controller.deadline, 700)
        managed.require_fixtures('iPadMini', self.setup)

    def test_container_expired_marker_stops_before_spawn_and_retains_fence(self):
        self.container_admission_at(80)
        with self.delayed_container_marker(60), self.assertRaisesRegex(ValueError, 'entry expired before capture'):
            self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus', 'install', 'launch'])
        self.assert_container_fenced()

    def container_failure(self, *, cleanup=None, late=None, unavailable=False):
        def fail(command, timeout):
            if command[2:3] != ['get_app_container']: return None
            if late is not None:
                self.tick = self.controller.operation_deadline + late
                return subprocess.CompletedProcess(command, 0, str(self.container), '')
            if unavailable: raise OSError('Synthetic lookup launch failure')
            error = capture_module.CaptureStopped('duration-limit', cleanup)
            raise error
        self.action = fail
        with self.assertRaises((capture_module.CaptureStopped, ValueError, OSError)): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus',
            'install', 'launch', 'get_app_container'])
        self.assertAlmostEqual(self.calls[-1][1], 60)
        self.assert_container_fenced()

    def test_container_timeout_with_confirmed_host_cleanup_never_continues(self):
        self.container_failure(cleanup=True)

    def test_container_timeout_with_unconfirmed_host_cleanup_never_continues(self):
        self.container_failure(cleanup=False)

    def test_container_timeout_with_unknown_host_cleanup_never_continues(self):
        self.container_failure(cleanup=None)

    def test_container_launch_exception_retains_uncertainty_fence(self):
        self.container_failure(unavailable=True)

    def test_container_zero_exit_at_absolute_deadline_is_terminal(self):
        self.container_failure(late=0)

    def test_container_zero_exit_after_absolute_deadline_is_terminal(self):
        self.container_failure(late=.001)

    def test_container_timely_result_after_old_thirty_second_cap_preserves_fixture_checks(self):
        def slow(command, timeout):
            if command[2:3] == ['get_app_container']: self.tick += 45
        self.action = slow
        self.run_seed()
        self.assertAlmostEqual(self.calls[7][1], 60)
        self.assertEqual(self.operations().count('get_app_container'), 1)
        self.assertIn('Synthetic Files fixture is ready', self.output.getvalue())
        self.assertEqual(self.controller.deadline, 700)
        managed.require_fixtures('iPadMini', self.setup)

    def test_already_booted_needs_no_boot_or_readiness_command(self):
        self.states = ['Booted']
        self.run_seed()
        self.assertEqual(self.operations()[:4], ['git', 'git', 'list', 'install'])
        self.assertNotIn('boot', self.operations()); self.assertNotIn('bootstatus', self.operations())
        self.assertEqual(self.controller.fixture_readiness['basis'], 'owned_booted_inventory_snapshot_only')
        self.assertIsNone(self.controller.fixture_readiness['completion'])
        self.assertEqual(self.controller.fixture_readiness['operations'], [])
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

    def test_missing_completion_stops_before_install(self):
        self.bootstatus = ''
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_foreign_bootstatus_uuid_stops_before_install(self):
        self.bootstatus = self.bootstatus.replace(NEW, OTHER)
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus']); self.no_seed()
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

    def test_duplicate_bootstatus_terminal_stops_before_install(self):
        self.bootstatus += self.bootstatus
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations()[-1], 'bootstatus'); self.no_seed()
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

    def test_launch_known_host_cleanup_is_retained_without_continuation(self):
        failure = self.fail_at('launch', 'known_cleanup')
        self.assertIs(failure['command']['host_cleanup_confirmed'], True)
        self.assertIsNone(failure['command']['exit_code'])
        self.assertEqual(failure['command']['argv'], ['xcrun', 'simctl', 'launch',
            '--terminate-running-process', NEW, 'com.mango.touchColor.tests.paletteFixtures'])
        self.assertEqual(failure['simulator_completion'], 'not_inferred')
        self.assertFalse(failure['stderr']['stream_complete'])
        self.assertNotIn('get_app_container', self.operations())
        self.assertNotIn('terminate', self.operations())
        self.assert_binding_unchanged()

    def test_launch_unknown_host_cleanup_stays_null(self):
        failure = self.fail_at('launch', 'unknown_cleanup')
        self.assertIsNone(failure['command']['host_cleanup_confirmed'])
        self.assertEqual(failure['source'], self.binding['context'])
        self.assertEqual(failure['deviceId'], NEW)
        self.assertNotIn('get_app_container', self.operations())

    def test_launch_unconfirmed_host_cleanup_stays_false(self):
        failure = self.fail_at('launch', 'unconfirmed_cleanup')
        self.assertIs(failure['command']['host_cleanup_confirmed'], False)
        self.assertIsNone(failure['command']['exit_code'])
        self.assertNotIn('get_app_container', self.operations())

    def test_launch_late_return_stops_with_original_deadline_and_observation(self):
        failure = self.fail_at('launch', 'late')
        self.assertEqual(failure['command']['exit_code'], 0)
        self.assertIs(failure['command']['host_cleanup_confirmed'], True)
        self.assertGreaterEqual(failure['command']['returned_monotonic'],
                                failure['command']['deadline_monotonic'])
        self.assertEqual(self.controller.deadline, 700)
        self.assertNotIn('get_app_container', self.operations())

    def test_launch_known_failure_keeps_exit_and_no_retry(self):
        failure = self.fail_at('launch', 'nonzero')
        self.assertEqual(failure['command']['exit_code'], 149)
        self.assertIs(failure['command']['host_cleanup_confirmed'], True)
        self.assertTrue(failure['stderr']['stream_complete'])
        self.assertEqual(self.operations().count('launch'), 1)

    def test_launch_allowlist_is_only_exact_owned_fixture_at_sixty(self):
        self.controller.bind_owned_device(self.binding)
        exact = ['xcrun', 'simctl', 'launch', '--terminate-running-process', NEW,
                 'com.mango.touchColor.tests.paletteFixtures']
        for argv, seconds in [(exact[:-1]+['com.mango.touchColor'],60),
                              (exact[:4]+[OTHER,exact[-1]],60), (exact,61),
                              (exact+['--extra'],60), (exact[:3]+exact[4:],60)]:
            with self.subTest(argv=argv, seconds=seconds), self.assertRaisesRegex(ValueError, 'Unexpected fixture evidence command'):
                self.controller.fixture_command(argv,seconds)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.controller.pending.exists())

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

    def test_late_initial_inventory_stops_before_boot(self):
        def late(command, timeout):
            if command == device_module.READBACK: self.tick += timeout
        self.action = late
        with self.assertRaises(ValueError): self.run_seed()
        self.assertEqual(self.operations(), ['git', 'git', 'list']); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_binding_change_after_readiness_stops_before_install(self):
        def mutate(command, timeout):
            if command[2:3] == ['bootstatus']: self.paths()[1].write_text('{}')
        self.action = mutate
        with self.assertRaises(Exception): self.run_seed()
        self.assertEqual(self.operations()[-1], 'bootstatus'); self.no_seed()
        self.assertTrue(self.controller.pending.exists())

    def test_recognized_already_booted_form_preserves_distinct_observation(self):
        self.bootstatus = self.bootstatus.split('\n', 1)[0] + '\nDevice already booted, nothing to do.\n\n'
        self.run_seed()
        proof = self.controller.fixture_readiness
        self.assertEqual(proof['basis'], 'owned_bootstatus_completion_observation_only')
        self.assertEqual(proof['completion']['completion_kind'], 'already_booted_no_work')
        self.assertNotIn('terminal_status', proof['completion'])
        self.assertEqual(self.operations().count('list'), 1)
        managed.require_fixtures('iPadMini', self.setup)

    def test_new_receipt_binds_exact_commands_hashes_and_completion_without_state_claim(self):
        self.run_seed()
        value = json.loads(managed.record_path('iPadMini', 'fixtures').read_text())
        self.assertEqual(value['schema'], 2)
        proof = value['readiness']
        self.assertEqual(proof['binding_sha256'], self.binding['receipt_sha256'])
        self.assertEqual(proof['basis'], 'owned_bootstatus_completion_observation_only')
        self.assertEqual(proof['completion']['stdout_sha256'], hashlib.sha256(self.bootstatus.encode()).hexdigest())
        self.assertEqual(proof['completion']['stdout_bytes'], len(self.bootstatus.encode()))
        self.assertEqual(proof['completion']['terminal_message'], 'Finished')
        self.assertNotIn('state', proof)
        for op, verb in zip(proof['operations'], ('boot', 'bootstatus')):
            self.assertEqual(op['argv'][2], verb)
            self.assertEqual(op['argv'][3], NEW)
            self.assertEqual(op['exit_code'], 0)
            self.assertIs(op['host_cleanup_confirmed'], True)
            self.assertLess(op['returned_monotonic'], op['deadline_monotonic'])

    def test_old_fixture_receipt_cannot_be_upgraded(self):
        self.run_seed()
        managed.record_path('iPadMini', 'fixtures').write_text(json.dumps(
            {'schema': 1, 'setup': self.setup, 'complete': True}))
        with self.assertRaises(ValueError): managed.require_fixtures('iPadMini', self.setup)

    def test_conflicting_or_late_completion_receipts_fail(self):
        self.run_seed()
        original = self.controller.fixture_readiness
        changes = [lambda v: v.update(device=OTHER),
            lambda v: v.update(binding_sha256='0'*64),
            lambda v: v.update(basis='Booted'),
            lambda v: v['operations'][1].update(host_cleanup_confirmed=None),
            lambda v: v['operations'][1].update(exit_code=149),
            lambda v: v['operations'][1].update(argv=['xcrun','simctl','bootstatus',OTHER,'-b']),
            lambda v: v['operations'][1].update(returned_monotonic=v['operations'][1]['deadline_monotonic']),
            lambda v: v['completion'].update(terminal_status=1),
            lambda v: v['completion'].update(isTerminal=False),
            lambda v: v['completion'].update(stdout_bytes=0)]
        for change in changes:
            value = copy.deepcopy(original); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                managed.validate_fixture_readiness(value, self.setup)

    def test_unknown_mixed_malformed_foreign_bootstatus_never_authorizes_install(self):
        raw = self.bootstatus
        variants = [raw.replace(self.binding['receipt']['requested_name'], 'Foreign name'),
            raw.replace('4294967295', '4'), raw.replace('isTerminal=YES', 'isTerminal=NO'),
            raw.replace('\tFinished', '\tNot Finished'), raw.replace('Elapsed=01:03', 'Elapsed=01:99'),
            raw+'Device already booted, nothing to do.\n\n', raw.rstrip(), raw.replace('\tWaiting on System App','\tFinished'),
            raw+'extra\n', raw.replace('Status=4, isTerminal=NO', 'Status=4, isTerminal=YES'),
            raw.replace('\tWaiting on System App', '\tbad\x00detail'), 'x'*65537]
        for value in variants:
            with self.subTest(raw=value), self.assertRaises(ValueError):
                managed.completed_bootstatus(value, {'name':self.binding['receipt']['requested_name'], 'device':NEW})

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
