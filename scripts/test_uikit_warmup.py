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


class UIKitWarmupTests(unittest.TestCase):
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

    def test_real_preparation_sequence_and_fixture_contents_remain_required(self):
        controller = self.controller()
        controller.prepare('prepare')
        self.assertEqual([call[0][2] for call in self.calls],
                         ['list', 'boot', 'bootstatus', 'install', 'launch', 'terminate',
                          'install', 'launch', 'get_app_container', 'terminate', 'spawn', 'TouchColor.xcodeproj'])
        self.assertTrue(all(0 < timeout <= 240 for _, timeout in self.calls))
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

    def test_preparation_dispatch_occurs_before_unbounded_legacy_selection(self):
        source = Path(warmup.__file__).with_name('test_simulators.sh').read_text()
        self.assertLess(source.index('exec python3'), source.index('xcrun simctl list devices available'))
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


if __name__ == '__main__':
    unittest.main()
