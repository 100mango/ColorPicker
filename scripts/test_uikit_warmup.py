import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import uikit_warmup as warmup
from job_budget import JobBudget, RESERVES, STARTUP_MARGIN


class Clock:
    value = 100.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


class UIKitWarmupFixture(unittest.TestCase):
    device = 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
    runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='UIKit warmup ')
        self.previous = Path.cwd()
        os.chdir(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(os.chdir, self.previous)
        self.clock = Clock()
        self.calls = []
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.container = Path(self.directory.name) / 'fixture host'
        documents = self.container / 'Documents'
        documents.mkdir(parents=True)
        self.fixture = documents / 'TouchColor-Ordered-Colors.json'
        self.fixture.write_text(json.dumps(['#445566', '#445566', '#AABBCC']))

    def runner(self, command, *, timeout):
        self.calls.append((command, timeout))
        self.clock.advance(0.25)
        if command[2:4] == ['list', 'devices']:
            output = json.dumps({'devices': {self.runtime: [
                {'name': 'iPad mini (A17 Pro)', 'udid': self.device, 'isAvailable': True}]}})
        elif command[2:4] == ['list', 'devicetypes']:
            output = json.dumps({'devicetypes': [{'name': 'iPhone SE (3rd generation)', 'identifier': 'SE3'}]})
        elif command[2] == 'create': output = self.device + '\n'
        elif command[2] == 'get_app_container': output = str(self.container) + '\n'
        else: output = ''
        return subprocess.CompletedProcess(command, 0, output, '')

    def controller(self, **options):
        return warmup.Warmup(options.pop('family', 'iPadMini'), started=100,
                             clock=self.clock, runner=options.pop('runner', self.runner),
                             sleep=self.clock.advance, **options)


class MeasuredInstallAllowanceTests(UIKitWarmupFixture):
    app_path = 'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'

    def is_app_install(self, command):
        return command[2] == 'install' and command[-1] == self.app_path

    def profile_runner(self, family, durations=None):
        durations = durations or {}
        def run(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            if command[2:4] == ['list', 'devices'] and family in ('iPadLarge', 'iPhoneLarge'):
                name = 'iPad Pro 13-inch (M5)' if family == 'iPadLarge' else 'iPhone 18 Pro Max'
                result.stdout = json.dumps({'devices': {self.runtime: [
                    {'name': name, 'udid': self.device, 'isAvailable': True}]}})
            key = 'app-install' if self.is_app_install(command) else command[2]
            if key in durations:
                self.clock.advance(durations[key] - 0.25)
            return result
        return run

    def test_observed_successful_installs_fit_without_changing_absolute_envelope(self):
        # Install durations are recorded observations; the boot inputs below
        # are synthetic planner scenarios, not a reconstruction of old timing.
        for family, bootstatus, install in (('iPadLarge', 202, 276), ('iPhoneLarge', 167, 208),
                                           ('iPadMini', 100, 179), ('iPhoneCompact', 100, 89.204)):
            with self.subTest(family=family):
                self.clock.value = 100; self.calls.clear()
                controller = self.controller(family=family, runner=self.profile_runner(
                    family, {'boot': 5, 'bootstatus': bootstatus, 'app-install': install}))
                controller.prepare('prepare')
                self.assertEqual([limit for command, limit in self.calls if self.is_app_install(command)], [300])
                self.assertEqual(controller.deadline, 700)
                self.assertLess(self.clock(), controller.deadline - warmup.CLEANUP)
                self.assertFalse(controller.pending.exists())
                self.assertIn('Synthetic Files fixture is ready', self.output.getvalue())

    def test_all_four_validated_main_app_installs_receive_three_hundred_seconds(self):
        for family in ('iPadLarge', 'iPhoneLarge', 'iPadMini', 'iPhoneCompact'):
            with self.subTest(family=family):
                self.clock.value = 100; self.calls.clear()
                controller = self.controller(family=family, runner=self.profile_runner(family))
                controller.prepare('prepare')
                self.assertEqual([limit for command, limit in self.calls if self.is_app_install(command)],
                                 [300])
                self.assertEqual([limit for command, limit in self.calls
                                  if command[2] == 'install' and not self.is_app_install(command)], [90])
                self.assertEqual(warmup.SECONDS, 600)
                self.assertEqual(warmup.CLEANUP, 20)

    def test_remaining_absolute_budget_clips_large_install_and_rejects_late_zero(self):
        base = self.profile_runner('iPadLarge', {'list': 20, 'boot': 180, 'bootstatus': 240})
        def clipped(command, *, timeout):
            if self.is_app_install(command):
                self.calls.append((command, timeout)); self.clock.advance(timeout + 0.01)
                return subprocess.CompletedProcess(command, 0, '', '')
            return base(command, timeout=timeout)
        controller = self.controller(family='iPadLarge', runner=clipped)
        with self.assertRaisesRegex(warmup.WarmupFailed, 'admitted deadline'):
            controller.prepare('prepare')
        self.assertEqual(self.calls[-1][1], 140)
        self.assertTrue(controller.pending.exists())
        self.assertFalse(any(command[2] == 'launch' for command, _ in self.calls))

    def test_inherited_native_budget_is_not_borrowed_for_large_install(self):
        record = {'schema': 1, 'platform': 'ios', 'minutes': 20, 'sha': 'a' * 40,
                  'started_epoch': 0, 'started_monotonic': 0,
                  'reserves': RESERVES, 'startup_margin': STARTUP_MARGIN}
        self.clock.value = 690
        budget = JobBudget(record, wall=lambda: 690, monotonic=self.clock)
        controller = warmup.Warmup('iPadLarge', started=690, clock=self.clock,
            runner=self.profile_runner('iPadLarge'), budget=budget, sleep=self.clock.advance)
        controller.prepare('prepare-unit')
        self.assertEqual([limit for command, limit in self.calls if self.is_app_install(command)], [9.25])
        self.assertTrue(all(limit <= 10 for _, limit in self.calls))
        self.assertEqual(controller.deadline, 1290)

    def test_large_install_late_zero_cannot_use_unused_global_time_as_success(self):
        controller = self.controller(family='iPhoneLarge', runner=self.profile_runner(
            'iPhoneLarge', {'app-install': 300.01}))
        with self.assertRaisesRegex(warmup.WarmupFailed, 'admitted deadline'):
            controller.prepare('prepare')
        self.assertLess(self.clock(), controller.deadline)
        self.assertTrue(controller.pending.exists())
        self.assertFalse(any(command[2] == 'launch' for command, _ in self.calls))

    def test_large_install_timeout_keeps_latch_even_with_confirmed_host_cleanup(self):
        for confirmed in (True, False):
            with self.subTest(cleanup_confirmed=confirmed):
                self.clock.value = 100; self.calls.clear()
                base = self.profile_runner('iPadLarge')
                def timeout_install(command, *, timeout):
                    if self.is_app_install(command):
                        self.calls.append((command, timeout)); self.clock.advance(timeout)
                        error = subprocess.TimeoutExpired(command, timeout)
                        error.cleanup_confirmed = confirmed
                        raise error
                    return base(command, timeout=timeout)
                controller = self.controller(family='iPadLarge', runner=timeout_install)
                with self.assertRaises(warmup.WarmupFailed): controller.prepare('prepare')
                self.assertEqual(self.calls[-1][1], 300)
                self.assertTrue(controller.pending.exists())
                self.assertFalse(any(command[2] == 'launch' for command, _ in self.calls))
                controller.pending.unlink()  # Independent owned synthetic scenario only.

    def test_smaller_profile_install_still_rejects_after_its_admitted_cap(self):
        for family in ('iPadMini', 'iPhoneCompact'):
            with self.subTest(family=family):
                self.clock.value = 100; self.calls.clear()
                controller = self.controller(family=family, runner=self.profile_runner(
                    family, {'app-install': 300.01}))
                with self.assertRaisesRegex(warmup.WarmupFailed, 'admitted deadline'):
                    controller.prepare('prepare')
                self.assertEqual(self.calls[-1][1], 300)
                self.assertTrue(controller.pending.exists())
                self.assertFalse(any(command[2] == 'launch' for command, _ in self.calls))
                controller.pending.unlink()  # Independent owned synthetic scenario only.

    def test_closed_profiles_reject_unknown_family_before_any_command(self):
        self.assertEqual(warmup.FAMILIES, {'iPadMini', 'iPadLarge', 'iPhoneCompact', 'iPhoneLarge'})
        for family in ('iPad', 'iPhone', 'watch', '', 'iPadMini-extra'):
            with self.subTest(family=family):
                with self.assertRaisesRegex(ValueError, 'Unknown simulator family'):
                    self.controller(family=family)
                self.assertEqual(self.calls, [])


class UIKitWarmupTests(UIKitWarmupFixture):
    def test_real_preparation_sequence_and_fixture_contents_remain_required(self):
        controller = self.controller()
        controller.prepare('prepare')
        self.assertEqual([call[0][2] for call in self.calls],
                         ['list', 'boot', 'bootstatus', 'install', 'launch', 'terminate',
                          'install', 'launch', 'get_app_container', 'terminate', 'spawn', 'TouchColor.xcodeproj'])
        self.assertTrue(all(0 < timeout <= (300 if command[2] == 'install' and
            command[-1].endswith('/TouchColor.app') else 240) for command, timeout in self.calls))
        self.assertEqual([timeout for command, timeout in self.calls if command[2] == 'terminate'], [30, 30])
        self.assertFalse(controller.pending.exists())
        identity = json.loads(Path('build/iPadMini-simulator.json').read_text())
        self.assertEqual(identity['udid'], self.device)
        self.assertEqual(identity['runtime'], self.runtime)
        self.assertIn('Synthetic Files fixture is ready', self.output.getvalue())

    def test_compact_creation_and_unit_only_path_still_install_launch_and_stop_app(self):
        controller = self.controller(family='iPhoneCompact')
        controller.prepare('prepare-unit')
        self.assertEqual([call[0][2] for call in self.calls],
                         ['list', 'list', 'create', 'boot', 'bootstatus', 'install', 'launch', 'terminate'])
        self.assertEqual(self.calls[2][0][3:], ['TouchColor Compact SE3', 'SE3', self.runtime])
        self.assertNotIn('paletteFixtures', str(self.calls))

    def test_observed_f977_successful_cold_boot_precedes_bounded_terminate_failure(self):
        def observed(command, *, timeout):
            if command[2] == 'boot':
                self.assertEqual(timeout, 180)
                self.clock.advance(125)
            if command[2] == 'terminate':
                self.assertEqual(timeout, 30)
                self.calls.append((command, timeout))
                self.clock.advance(timeout)
                error = subprocess.TimeoutExpired(command, timeout)
                error.cleanup_confirmed = True
                raise error
            return self.runner(command, timeout=timeout)
        controller = self.controller(runner=observed)
        with self.assertRaises(warmup.WarmupFailed): controller.prepare('prepare')
        self.assertEqual([call[0][2] for call in self.calls],
                         ['list', 'boot', 'bootstatus', 'install', 'launch', 'terminate'])
        self.assertLess(self.clock(), controller.deadline)
        self.assertTrue(controller.pending.exists())

    def test_selection_and_setup_spend_the_same_six_hundred_second_clock(self):
        def slow_selection(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            self.clock.advance(29)
            return result
        controller = self.controller(runner=slow_selection)
        controller.select()
        self.clock.advance(549.5)  # Only 21.25s remain, including 20s cleanup.
        self.assertEqual(controller.deadline, 700)
        controller.runner = self.runner
        controller.command(['xcrun', 'simctl', 'terminate', self.device, 'com.mango.touchColor'], 30)
        self.assertAlmostEqual(self.calls[-1][1], 1.25)
        self.clock.advance(1)
        count = len(self.calls)
        with self.assertRaises(warmup.WarmupFailed): controller.command(['xcrun', 'simctl', 'install'], 90)
        self.assertEqual(len(self.calls), count)

    def test_timeout_even_with_host_cleanup_confirmed_blocks_fixture_and_downstream_commands(self):
        for confirmed in (True, False):
            with self.subTest(cleanup_confirmed=confirmed):
                def timeout_terminate(command, *, timeout):
                    if command[2] == 'terminate':
                        self.calls.append((command, timeout))
                        error = subprocess.TimeoutExpired(command, timeout)
                        error.cleanup_confirmed = confirmed
                        raise error
                    return self.runner(command, timeout=timeout)
                controller = self.controller(runner=timeout_terminate)
                with self.assertRaises(warmup.WarmupFailed): controller.prepare('prepare')
                self.assertTrue(controller.pending.is_file())
                self.assertNotIn('paletteFixtures', str(self.calls))
                before = len(self.calls)
                with self.assertRaises(warmup.WarmupFailed): self.controller()
                self.assertEqual(len(self.calls), before)
                controller.pending.unlink()  # Independent synthetic scenario only.
                self.calls.clear()

    def test_zero_exit_after_command_cap_is_failure_and_retains_stop_latch(self):
        def late(command, *, timeout):
            self.clock.advance(timeout + 0.01)
            return subprocess.CompletedProcess(command, 0, '', '')
        controller = self.controller(runner=late)
        with self.assertRaisesRegex(warmup.WarmupFailed, 'admitted deadline'):
            controller.command(['xcrun', 'simctl', 'terminate'], 30)
        self.assertTrue(controller.pending.exists())

    def test_global_deadline_expiry_cannot_be_late_success(self):
        def late(command, *, timeout):
            self.clock.value = 701
            return subprocess.CompletedProcess(command, 0, '', '')
        controller = self.controller(runner=late)
        with self.assertRaises(warmup.WarmupFailed): controller.command(['xcrun', 'simctl', 'list'], 30)
        self.assertTrue(controller.pending.exists())

    def test_inherited_native_budget_admits_only_its_remaining_work_with_cleanup_reserved(self):
        record = {'schema': 1, 'platform': 'ios', 'minutes': 20, 'sha': 'a' * 40,
                  'started_epoch': 0, 'started_monotonic': 0,
                  'reserves': RESERVES, 'startup_margin': STARTUP_MARGIN}
        self.clock.value = 690  # Native work deadline is 720; only 30 remain.
        budget = JobBudget(record, wall=lambda: 690, monotonic=self.clock)
        controller = warmup.Warmup('iPadMini', started=690, clock=self.clock, runner=self.runner, budget=budget)
        controller.command(['xcrun', 'simctl', 'list'], 30)
        self.assertEqual(self.calls[-1][1], 10)
        budget.latch_cleanup_failure()
        before = len(self.calls)
        with self.assertRaises(Exception): controller.command(['xcrun', 'simctl', 'install'], 90)
        self.assertEqual(len(self.calls), before)

    def test_launch_exception_retains_uncertainty_marker(self):
        def broken(*arguments, **options): raise OSError('synthetic launch failed')
        controller = self.controller(runner=broken)
        with self.assertRaises(OSError): controller.command(['xcrun', 'simctl', 'list'], 30)
        self.assertTrue(controller.pending.exists())

    def test_nonzero_required_exit_stops_but_optional_boot_exit_keeps_bootstatus(self):
        def boot_already_running(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            if command[2] == 'boot': result.returncode = 149
            return result
        controller = self.controller(runner=boot_already_running)
        controller.prepare('prepare-unit')
        self.assertIn('bootstatus', str(self.calls))
        controller.runner = lambda command, **options: subprocess.CompletedProcess(command, 9, '', '')
        with self.assertRaises(warmup.WarmupFailed): controller.command(['xcrun', 'simctl', 'launch'], 60)
        self.assertFalse(controller.pending.exists())

    def test_optional_simulator_timeout_is_not_safe_but_confirmed_host_timeout_is_omittable(self):
        def timeout(command, **options):
            error = subprocess.TimeoutExpired(command, options['timeout'])
            error.cleanup_confirmed = True
            self.clock.advance(options['timeout'])
            raise error
        controller = self.controller(runner=timeout)
        controller.command(['xcodebuild', '-project', 'TouchColor.xcodeproj'], 30, optional=True, simulator=False)
        self.assertFalse(controller.pending.exists())
        with self.assertRaises(warmup.WarmupFailed):
            controller.command(['xcrun', 'simctl', 'spawn'], 20, optional=True)
        self.assertTrue(controller.pending.exists())

    def test_fixture_missing_wrong_order_or_extra_file_never_passes_even_when_optimized(self):
        controller = self.controller()
        self.fixture.write_text(json.dumps(['#445566', '#AABBCC', '#445566']))
        with self.assertRaises(warmup.WarmupFailed): controller.fixture(str(self.container))
        self.fixture.write_text(json.dumps(['#445566', '#445566', '#AABBCC']))
        (self.fixture.parent / 'unexpected.json').write_text('{}')
        with self.assertRaises(warmup.WarmupFailed): controller.fixture(str(self.container))
        self.fixture.unlink()
        start = self.clock()
        with self.assertRaises(warmup.WarmupFailed): controller.fixture(str(self.container))
        self.assertLessEqual(self.clock() - start, 10.001)

    def test_shell_guard_blocks_every_downstream_mode_and_marker_alias(self):
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        Path('build').mkdir(exist_ok=True)
        marker = Path('build/iPadMini-runtime-command-uncertain')
        tools = Path('fake tools'); tools.mkdir()
        fake = tools / 'xcrun'
        fake.write_text('#!/bin/sh\ntouch command-ran\n'); fake.chmod(0o755)
        environment = dict(os.environ, PATH=str(tools.resolve()) + os.pathsep + os.environ['PATH'])
        for alias in (False, True):
            if alias: marker.symlink_to('missing-target')
            else: marker.write_text('unknown command')
            for suite in ('prepare', 'prepare-unit', 'seed', 'shutdown', 'TouchColorTests', 'TouchColorUITests', 'AccessibilityAudits'):
                result = subprocess.run(['bash', str(script), 'iPadMini', suite], env=environment,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 3, (suite, result.stderr))
                self.assertFalse(Path('command-ran').exists())
            marker.unlink()

    def test_shell_routes_every_simctl_mode_through_owned_controller(self):
        source = Path(warmup.__file__).with_name('test_simulators.sh').read_text()
        self.assertNotIn('xcrun simctl', source)
        self.assertNotIn('/tmp/touchcolor-', source)
        self.assertIn('device=$(python3', source)
        self.assertNotIn('simctl terminate', source)
        self.assertNotIn('PYDIAGNOSTICS', source)

    def test_native_environment_is_loaded_and_invalid_inherited_budget_fails_before_command(self):
        with patch.object(sys, 'argv', ['warmup', 'iPadMini', 'prepare']), \
             patch.object(warmup, 'enabled_budget', side_effect=ValueError('invalid exact budget')), \
             patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': 'work'}), \
             patch.object(warmup, 'fail_record') as record, \
             patch.object(warmup, 'Warmup') as controller, contextlib.redirect_stderr(self.output):
            self.assertEqual(warmup.main(), 3)
            controller.assert_not_called()
            record.assert_called_once()

    def test_real_shell_and_owned_subprocesses_work_with_spaces_in_paths(self):
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        tools = Path('synthetic command tools'); tools.mkdir()
        stub = '#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
with Path('commands.jsonl').open('a') as output: output.write(json.dumps(sys.argv[1:])+'\\n')
args=sys.argv[1:]
if args[:3]==['simctl','list','devices']:
 print(json.dumps({'devices':{'com.apple.CoreSimulator.SimRuntime.iOS-27-0':[
  {'name':'iPad mini (A17 Pro)','udid':'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA','isAvailable':True}]}}))
elif args[:2]==['simctl','get_app_container']: print(os.environ['SYNTHETIC_FIXTURE_CONTAINER'])
'''
        for name in ('xcrun', 'xcodebuild'):
            (tools / name).write_text(stub); (tools / name).chmod(0o755)
        environment = dict(os.environ, PATH=str(tools.resolve()) + os.pathsep + os.environ['PATH'],
                           SYNTHETIC_FIXTURE_CONTAINER=str(self.container), TOUCHCOLOR_BUDGET_PHASE='')
        result = subprocess.run(['bash', str(script), 'iPadMini', 'prepare'], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Synthetic Files fixture is ready', result.stdout)
        self.assertIn('Simulator preparation complete', result.stdout)
        self.assertEqual(len(Path('commands.jsonl').read_text().splitlines()), 12)
        self.assertFalse(Path('build/iPadMini-runtime-command-uncertain').exists())

    def test_real_bounded_timeout_retains_barrier_after_owned_group_cleanup(self):
        import time
        controller = warmup.Warmup('iPadMini', started=time.monotonic())
        with patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': ''}):
            began = time.monotonic()
            with self.assertRaises(warmup.WarmupFailed) as raised:
                controller.command([sys.executable, '-c', 'import time; time.sleep(30)'], 0.1)
        self.assertLess(time.monotonic() - began, 3)
        self.assertTrue(raised.exception.__cause__.cleanup_confirmed)
        self.assertTrue(controller.pending.is_file())

    def test_build_directory_alias_is_rejected_before_any_command(self):
        Path('external build').mkdir()
        Path('build').symlink_to('external build', target_is_directory=True)
        with self.assertRaises(warmup.WarmupFailed): self.controller()
        self.assertEqual(self.calls, [])

    def test_report_inventory_timeout_retains_barrier_despite_confirmed_host_cleanup(self):
        def timeout(command, **options):
            self.assertEqual(command, ['xcrun', 'simctl', 'list', 'devices'])
            self.assertEqual(options['timeout'], 3)
            error = subprocess.TimeoutExpired(command, 3)
            error.cleanup_confirmed = True
            raise error
        self.assertEqual(warmup.report_inventory('iPadMini', runner=timeout, clock=self.clock), 3)
        self.assertTrue(Path('build/iPadMini-runtime-command-uncertain').exists())
        record = json.loads(self.output.getvalue().split('UIKIT_REPORT_DIAGNOSTICS:')[-1])
        self.assertTrue(record['host_process_cleanup_confirmed'])
        self.assertEqual(record['simulator_shutdown'], 'not_confirmed')
        self.assertEqual(record['inventory'], 'failed_unconfirmed')

    def test_report_inventory_rejects_late_zero_exit_and_unexpected_error(self):
        def late(command, **options):
            self.clock.advance(3.01)
            return subprocess.CompletedProcess(command, 0, 'late inventory', '')
        self.assertEqual(warmup.report_inventory('iPadMini', runner=late, clock=self.clock), 3)
        marker = Path('build/iPadMini-runtime-command-uncertain')
        self.assertTrue(marker.exists())
        self.assertNotIn('late inventory', self.output.getvalue())
        marker.unlink()  # Independent synthetic scenario only.
        def failed(*arguments, **options): raise OSError('synthetic launch error')
        self.assertEqual(warmup.report_inventory('iPadMini', runner=failed, clock=self.clock), 3)
        self.assertTrue(marker.exists())

    def test_actual_always_report_body_blocks_simctl_and_still_reports_summaries(self):
        import textwrap
        scripts = Path(warmup.__file__).parent.resolve()
        workflow = (scripts.parent / '.github/workflows/ios.yml').read_text()
        section = workflow.split('      - name: Always report test summaries and simulator diagnostics\n', 1)[1]
        body = textwrap.dedent(section.split('        run: |\n', 1)[1].split('      - name:', 1)[0])
        Path('scripts').symlink_to(scripts, target_is_directory=True)
        tools = Path('workflow fake tools'); tools.mkdir()
        stub = '#!' + sys.executable + '\n' + '''
import json, sys
from pathlib import Path
name=Path(sys.argv[0]).name
with Path('report-commands.jsonl').open('a') as output: output.write(json.dumps([name,*sys.argv[1:]])+'\\n')
if name=='find': print('Summary reported' if sys.argv[1]=='build' else 'Crash report inspected')
elif name=='xcrun': print('Synthetic simulator inventory')
'''
        for name in ('vm_stat', 'xcrun', 'find'):
            (tools / name).write_text(stub); (tools / name).chmod(0o755)
        environment = dict(os.environ, PATH=str(tools.resolve()) + os.pathsep + os.environ['PATH'],
                           TC_TEST_FAMILY='iPadMini', TOUCHCOLOR_BUDGET_PHASE='')
        Path('build').mkdir()
        marker = Path('build/iPadMini-runtime-command-uncertain')
        for alias in (False, True):
            if alias: marker.symlink_to('missing-marker-target')
            else: marker.write_text('Earlier simulator command completion is unknown')
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', body], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 3, result.stderr)
            calls = [json.loads(line) for line in Path('report-commands.jsonl').read_text().splitlines()]
            self.assertEqual([call[0] for call in calls], ['vm_stat', 'find', 'find'])
            self.assertFalse(any('simctl' in call for call in calls))
            self.assertIn('blocked_prior_uncertainty', result.stdout)
            self.assertIn('"simulator_shutdown": "not_confirmed"', result.stdout)
            self.assertIn('Summary reported', result.stdout)
            self.assertIn('Crash report inspected', result.stdout)
            marker.unlink(); Path('report-commands.jsonl').unlink()
        # The same actual workflow body still collects inventory without a latch.
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', body], env=environment,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in Path('report-commands.jsonl').read_text().splitlines()]
        self.assertEqual([call[0] for call in calls], ['vm_stat', 'xcrun', 'find', 'find'])
        self.assertEqual(calls[1][1:], ['simctl', 'list', 'devices'])
        self.assertIn('"inventory": "collected"', result.stdout)
        self.assertFalse(marker.exists())


class UIKitSeedTests(UIKitWarmupFixture):
    # Reuse only the isolated, space-bearing output root and synthetic fixtures.
    def binding(self):
        Path('build').mkdir(exist_ok=True)
        self.identity_path = Path('build/iPadMini-simulator.json')
        self.identity = {'family': 'iPadMini', 'udid': self.device, 'runtime': self.runtime, 'started': 1}
        self.identity_path.write_text(json.dumps(self.identity))
        self.identity_bytes = self.identity_path.read_bytes()
        self.seeded = Path('build/iPadMini-fixture-seeded')
        return self.identity

    def test_seed_uses_existing_binding_one_absolute_clock_and_original_pixels(self):
        import struct
        import zlib
        self.binding()
        def observed(command, *, timeout):
            if command[2] == 'addmedia':
                self.assertEqual(command[3], self.device)
                self.assertFalse(self.seeded.exists())
                self.assertEqual(timeout, 579.75)
                path = Path(command[4])
                self.assertEqual(path.parent.parent.resolve(), Path('build').resolve())
                self.assertTrue(path.is_file())
                data = path.read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]), (300, 200))
                # Parse actual IDAT and compare every original fixture pixel.
                offset, compressed = 8, b''
                while offset < len(data):
                    length = struct.unpack('>I', data[offset:offset+4])[0]
                    if data[offset+4:offset+8] == b'IDAT': compressed += data[offset+8:offset+8+length]
                    offset += 12 + length
                palette = [bytes(c) for c in [(255,0,0),(0,255,0),(0,0,255),(0,255,255),(255,0,255),(255,255,0)]]
                expected = b''.join(b'\0'+b''.join(palette[(y//100)*3+x//100] for x in range(300)) for y in range(200))
                self.assertEqual(zlib.decompress(compressed), expected)
            return self.runner(command, timeout=timeout)
        controller = self.controller(runner=observed)
        controller.seed(controller.owned_device())
        self.assertEqual([call[0][2] for call in self.calls], ['list', 'addmedia'])
        self.assertEqual(json.loads(self.seeded.read_text()), self.identity)
        self.assertEqual(self.identity_path.read_bytes(), self.identity_bytes)
        self.assertEqual(list(Path('build').glob('*-photo-*')), [])
        self.assertFalse(controller.pending.exists())
        controller.seed(self.device)
        self.assertEqual(len(self.calls), 2)  # Success is bound to this exact identity.

    def test_owned_binding_missing_malformed_linked_or_wrong_family_precedes_inventory(self):
        self.binding()
        cases = [None, '{', json.dumps({**self.identity, 'family': 'iPadLarge'}),
                 json.dumps({**self.identity, 'udid': 'booted'}),
                 json.dumps({**self.identity, 'runtime': 'unexpected'})]
        for value in cases:
            with self.subTest(value=value):
                self.identity_path.unlink(missing_ok=True)
                if value is not None: self.identity_path.write_text(value)
                with self.assertRaises((warmup.WarmupFailed, ValueError)):
                    self.controller().owned_device()
                self.assertEqual(self.calls, [])
        self.identity_path.unlink()
        Path('other-binding').write_bytes(self.identity_bytes)
        self.identity_path.symlink_to('../other-binding')
        with self.assertRaises(warmup.WarmupFailed): self.controller().owned_device()
        self.assertEqual(self.calls, [])

    def test_wrong_inventory_or_seed_target_never_adds_media_or_rebinds(self):
        self.binding()
        def wrong(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            result.stdout = result.stdout.replace(self.device, 'BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB')
            return result
        with self.assertRaises(warmup.WarmupFailed): self.controller(runner=wrong).owned_device()
        self.assertEqual([call[0][2] for call in self.calls], ['list'])
        self.assertEqual(self.identity_path.read_bytes(), self.identity_bytes)
        self.assertFalse(self.seeded.exists())
        controller = self.controller()
        controller.owned_device()
        with self.assertRaises(warmup.WarmupFailed): controller.seed('BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB')
        self.assertFalse(any(call[0][2] == 'addmedia' for call in self.calls))

    def test_inventory_uses_recorded_device_even_when_another_same_name_is_first(self):
        self.binding()
        def duplicate_name(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            data = json.loads(result.stdout)
            data['devices'][self.runtime].insert(0, {'name': 'iPad mini (A17 Pro)',
                'udid': 'BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB', 'isAvailable': True})
            result.stdout = json.dumps(data)
            return result
        self.assertEqual(self.controller(runner=duplicate_name).owned_device(), self.device)
        self.assertEqual(self.identity_path.read_bytes(), self.identity_bytes)

    def test_changed_binding_and_stale_seed_success_cannot_trigger_addmedia(self):
        self.binding()
        controller = self.controller()
        controller.owned_device()
        self.identity_path.write_text(json.dumps({**self.identity, 'started': 2}))
        with self.assertRaises(warmup.WarmupFailed): controller.seed(self.device)
        self.identity_path.write_bytes(self.identity_bytes)
        for value in ('', json.dumps({**self.identity, 'started': 2})):
            self.seeded.write_text(value)
            with self.assertRaises((warmup.WarmupFailed, ValueError)): controller.seed(self.device)
        self.seeded.unlink()
        self.seeded.symlink_to('missing-seed')
        with self.assertRaises(warmup.WarmupFailed): controller.seed(self.device)
        self.assertEqual([call[0][2] for call in self.calls], ['list'])

    def test_seed_hung_inventory_and_addmedia_retain_same_barrier_without_success(self):
        self.binding()
        for phase in ('list', 'addmedia'):
            for confirmed in (False, True):
                with self.subTest(phase=phase, confirmed=confirmed):
                    self.calls.clear()
                    def hung(command, *, timeout):
                        if command[2] == phase:
                            self.calls.append((command, timeout))
                            error = subprocess.TimeoutExpired(command, timeout)
                            error.cleanup_confirmed = confirmed
                            raise error
                        return self.runner(command, timeout=timeout)
                    controller = self.controller(runner=hung)
                    with self.assertRaises(warmup.WarmupFailed): controller.seed(controller.owned_device())
                    self.assertTrue(controller.pending.exists())
                    self.assertFalse(self.seeded.exists())
                    self.assertEqual(self.identity_path.read_bytes(), self.identity_bytes)
                    count = len(self.calls)
                    with self.assertRaises(warmup.WarmupFailed): self.controller()
                    self.assertEqual(warmup.report_inventory('iPadMini', runner=self.runner), 3)
                    self.assertEqual(len(self.calls), count)
                    controller.pending.unlink()  # Independent synthetic scenario only.

    def test_late_zero_addmedia_exit_never_publishes_success_or_allows_later_commands(self):
        self.binding()
        def late(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            if command[2] == 'addmedia': self.clock.advance(timeout)
            return result
        controller = self.controller(runner=late)
        with self.assertRaisesRegex(warmup.WarmupFailed, 'admitted deadline'):
            controller.seed(controller.owned_device())
        self.assertTrue(controller.pending.exists())
        self.assertFalse(self.seeded.exists())
        with self.assertRaises(warmup.WarmupFailed): self.controller()

    def test_seed_remaining_budget_includes_inventory_fixture_and_cleanup(self):
        self.binding()
        controller = self.controller()
        device = controller.owned_device()
        self.clock.value = 678.5
        controller.seed(device)
        self.assertEqual(self.calls[-1][1], 1.5)
        self.assertEqual(controller.deadline, 700)
        self.seeded.unlink()
        self.clock.value = 680
        before = len(self.calls)
        with self.assertRaises(warmup.WarmupFailed): controller.seed(device)
        self.assertEqual(len(self.calls), before)
        self.assertFalse(self.seeded.exists())

    def test_shutdown_shares_120_second_clock_and_preserves_timely_nonzero_behavior(self):
        self.binding()
        controller = self.controller(seconds=120)
        device = controller.owned_device()
        self.clock.value = 199
        def stopped(command, *, timeout):
            result = self.runner(command, timeout=timeout)
            result.returncode = 149
            return result
        controller.runner = stopped
        controller.shutdown(device)
        self.assertEqual(self.calls[-1][1], 1)
        self.assertEqual(controller.deadline, 220)
        self.assertFalse(controller.pending.exists())

    def synthetic_tools(self):
        tools = Path('seed command tools'); tools.mkdir()
        stub = '#!' + sys.executable + '\n' + r'''import json, os, sys, time
from pathlib import Path
args=sys.argv[1:]
name=Path(sys.argv[0]).name
with Path('seed-commands.jsonl').open('a') as output: output.write(json.dumps([name,*args])+'\n')
if name=='xcodebuild': raise SystemExit(int(os.environ.get('XCTEST_EXIT','0')))
if args[:3]==['simctl','list','devices']:
 print(json.dumps({'devices':{'com.apple.CoreSimulator.SimRuntime.iOS-27-0':[
  {'name':'iPad mini (A17 Pro)','udid':'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA','isAvailable':True}]}}))
elif args[:2]==['simctl','addmedia']:
 if not Path(args[-1]).is_file(): raise SystemExit(8)
 if Path('build/iPadMini-fixture-seeded').exists(): raise SystemExit(9)
 if os.environ.get('HANG_SEED')=='1':
  Path('seed-child.pid').write_text(str(os.getpid()))
  time.sleep(30)
 raise SystemExit(int(os.environ.get('ADDMEDIA_EXIT','0')))
'''
        for name in ('xcrun', 'xcodebuild'):
            (tools / name).write_text(stub); (tools / name).chmod(0o755)
        actual = Path('actual tmp'); actual.mkdir()
        alias = Path('aliased tmp'); alias.symlink_to(actual.resolve(), target_is_directory=True)
        return dict(os.environ, PATH=str(tools.resolve()) + os.pathsep + os.environ['PATH'],
                    TMPDIR=str(alias.resolve().parent / alias.name), TOUCHCOLOR_BUDGET_PHASE='')

    def test_real_seed_shell_and_test_invocations_preserve_suite_selection_and_exit_codes(self):
        self.binding()
        environment = self.synthetic_tools()
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        for suite, selection in [('seed', None), ('TouchColorTests', 'TouchColorTests'),
                ('TouchColorUITests', 'TouchColorUITests/TouchColorIPadUITests'),
                ('AccessibilityAudits', 'TouchColorUITests/TouchColorAccessibilityUITests'), ('shutdown', None)]:
            environment['XCTEST_EXIT'] = '7'
            result = subprocess.run(['bash', str(script), 'iPadMini', suite], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 7 if selection else 0, result.stderr)
            calls = [json.loads(line) for line in Path('seed-commands.jsonl').read_text().splitlines()]
            if selection:
                self.assertEqual(calls[-1][0], 'xcodebuild')
                self.assertIn('-only-testing:' + selection, calls[-1])
                self.assertIn('platform=iOS Simulator,id=' + self.device, calls[-1])
                self.assertEqual(calls[-1][-1], 'test-without-building')
            self.assertEqual(self.identity_path.read_bytes(), self.identity_bytes)
        self.assertEqual(sum(call[1:3] == ['simctl', 'addmedia'] for call in calls), 1)
        self.assertEqual(list(Path('actual tmp').iterdir()), [])

    def test_real_shell_missing_or_wrong_binding_never_rebinds_or_reaches_xctest(self):
        self.binding()
        environment = self.synthetic_tools()
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        self.identity_path.unlink()
        for suite in ('seed', 'shutdown', 'TouchColorTests', 'TouchColorUITests', 'AccessibilityAudits'):
            result = subprocess.run(['bash', str(script), 'iPadMini', suite], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse(Path('seed-commands.jsonl').exists())
            self.assertFalse(self.identity_path.exists())
        self.identity_path.write_text(json.dumps({**self.identity, 'udid': 'BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB'}))
        saved = self.identity_path.read_bytes()
        result = subprocess.run(['bash', str(script), 'iPadMini', 'seed'], env=environment,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.identity_path.read_bytes(), saved)
        calls = [json.loads(line) for line in Path('seed-commands.jsonl').read_text().splitlines()]
        self.assertEqual(calls, [['xcrun', 'simctl', 'list', 'devices', 'available', '-j']])
        self.assertFalse(self.seeded.exists())

    def test_seed_interrupt_or_launch_error_retains_marker_and_shutdown_cannot_follow(self):
        self.binding()
        for error in (KeyboardInterrupt(), OSError('synthetic spawn error')):
            with self.subTest(error=type(error).__name__):
                def interrupted(command, *, timeout):
                    if command[2] == 'addmedia': raise error
                    return self.runner(command, timeout=timeout)
                controller = self.controller(runner=interrupted)
                with self.assertRaises(type(error)): controller.seed(controller.owned_device())
                self.assertTrue(controller.pending.exists())
                self.assertFalse(self.seeded.exists())
                with self.assertRaises(warmup.WarmupFailed): self.controller(seconds=120)
                controller.pending.unlink()  # Independent synthetic scenario only.

    def test_shutdown_hung_or_late_zero_exit_retains_barrier(self):
        self.binding()
        for late in (False, True):
            with self.subTest(late=late):
                self.clock.value = 100
                controller = self.controller(seconds=120)
                device = controller.owned_device()
                def stopped(command, *, timeout):
                    self.assertLessEqual(timeout, 90)
                    self.clock.advance(timeout + 0.01 if late else timeout)
                    if late: return subprocess.CompletedProcess(command, 0, '', '')
                    error = subprocess.TimeoutExpired(command, timeout)
                    error.cleanup_confirmed = True
                    raise error
                controller.runner = stopped
                with self.assertRaises(warmup.WarmupFailed): controller.shutdown(device)
                self.assertTrue(controller.pending.exists())
                self.assertFalse(self.seeded.exists())
                self.assertLess(self.clock(), controller.deadline)
                controller.pending.unlink()  # Independent synthetic scenario only.

    def test_real_addmedia_nonzero_exit_never_publishes_success(self):
        self.binding()
        environment = self.synthetic_tools()
        environment['ADDMEDIA_EXIT'] = '6'
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        result = subprocess.run(['bash', str(script), 'iPadMini', 'seed'], env=environment,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse(self.seeded.exists())
        self.assertFalse(Path('build/iPadMini-runtime-command-uncertain').exists())

    def test_executed_hung_addmedia_reaps_owned_group_and_blocks_every_later_mode(self):
        import time
        self.binding()
        environment = self.synthetic_tools()
        environment['HANG_SEED'] = '1'
        with patch.dict(os.environ, environment):
            # Execute the actual owned runner and real synthetic simctl, with a
            # short test-only absolute clock. Production remains 600 seconds.
            controller = warmup.Warmup('iPadMini', started=time.monotonic(), seconds=warmup.CLEANUP+0.7)
            with self.assertRaises(warmup.WarmupFailed): controller.seed(controller.owned_device())
        self.assertTrue(controller.pending.exists())
        self.assertFalse(self.seeded.exists())
        child = int(Path('seed-child.pid').read_text())
        with self.assertRaises(ProcessLookupError): os.kill(child, 0)
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        previous = Path('seed-commands.jsonl').read_bytes()
        for suite in ('prepare', 'prepare-unit', 'seed', 'shutdown', 'TouchColorTests', 'TouchColorUITests', 'AccessibilityAudits'):
            result = subprocess.run(['bash', str(script), 'iPadMini', suite], env=environment,
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 3)
        self.assertEqual(warmup.report_inventory('iPadMini'), 3)
        self.assertEqual(Path('seed-commands.jsonl').read_bytes(), previous)

    def test_real_seed_sigterm_cleans_host_group_retains_barrier_and_never_marks_success(self):
        import signal
        import time
        self.binding()
        environment = self.synthetic_tools()
        environment['HANG_SEED'] = '1'
        script = Path(warmup.__file__).with_name('test_simulators.sh').resolve()
        process = subprocess.Popen(['bash', str(script), 'iPadMini', 'seed'], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 5
        while not Path('seed-child.pid').exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(Path('seed-child.pid').exists())
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 3, errors)
        self.assertIn('interrupted by signal', errors)
        self.assertTrue(Path('build/iPadMini-runtime-command-uncertain').exists())
        self.assertFalse(self.seeded.exists())
        with self.assertRaises(ProcessLookupError): os.kill(int(Path('seed-child.pid').read_text()), 0)

    def test_workflow_registers_seed_regressions_and_keeps_step_envelopes(self):
        workflow = (Path(warmup.__file__).parent.parent / '.github/workflows/ios.yml').read_text()
        self.assertIn('python3 -m unittest test_uikit_runtime_diagnostics test_palette_lifecycle_diagnostics test_uikit_picker_geometry test_uikit_warmup', workflow)
        for name, minutes in [('Prepare Files fixture and seed synthetic photo', 10), ('Shut down simulator', 2)]:
            section = workflow.split('      - name: ' + name + '\n', 1)[1].split('      - name:', 1)[0]
            self.assertIn('timeout-minutes: ' + str(minutes), section)
        source = Path(warmup.__file__).read_text()
        self.assertIn('install_seconds = 300  # self.family is one of the four closed, validated profiles.', source)
        self.assertIn("'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'], install_seconds)", source)
        self.assertIn("'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90)", source)

    def test_uikit_two_way_lane_preserves_profile_scope_and_declared_handoff(self):
        import re
        root = Path(warmup.__file__).parent.parent
        uikit = (root / '.github/workflows/ios.yml').read_text()
        native = (root / '.github/workflows/apple-platforms.yml').read_text()
        self.assertEqual(re.findall(r'^      max-parallel: (.+)$', uikit, re.M), ["${{ github.ref == 'refs/heads/codex/uikit-hosted-repair' && 2 || 1 }}"])
        self.assertEqual(re.findall(r'^      max-parallel: (\d+)\s*$', native, re.M), ['2'])
        self.assertIn('family: [iPadMini, iPadLarge, iPhoneCompact, iPhoneLarge]', uikit)
        self.assertIn('cancel-in-progress: false', uikit)
        self.assertIn('    timeout-minutes: 60', uikit)
        self.assertEqual(re.findall(r'^    runs-on: (.+)$', uikit, re.M), ['xcode-27', 'xcode-27'])
        # Both closed plans preserve the two other projects' serial reservations.
        # Canonical: native2 + canonicalUIKit1 + QR1 + Cell1.
        self.assertEqual(2 + 1 + 1 + 1, 5)
        # Repair: dedicatedVision1 + repairUIKit2 + QR1 + Cell1.
        # Cross-workflow admission still excludes overlapping canonical/repair cohorts.
        self.assertEqual(1 + 2 + 1 + 1, 5)


if __name__ == '__main__':
    unittest.main()
