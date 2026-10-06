#!/usr/bin/env python3
"""Portable runner-lease scheduling/identity regressions; no Apple execution claim."""
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from bounded_process import stop_group
import capture_simulator_checkpoint as checkpoint
from vision_suites import CASES

ROOT = Path(__file__).resolve().parent.parent
DEVICE = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
LEASE = '11111111-2222-3333-4444-555555555555'
REQUEST = '66666666-7777-8888-9999-AAAAAAAAAAAA'
RUNNER = 'com.mango.touchColor.TouchColorVisionUITests.xctrunner'


def swift_method(source, name):
    match = re.search(r'^    .*func ' + re.escape(name) + r'\([^\n]*\{', source, re.M)
    if not match: raise ValueError(name)
    end = re.search(r'^    }$', source[match.end():], re.M)
    if not end: raise ValueError(name + ' boundary')
    return source[match.start():match.end() + end.end()]


class RunnerLeaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT/'TouchColorVisionUITests/VisionWorkflowTests.swift').read_text()

    def test_every_case_uses_binding_before_launch_with_no_conditional_case_scope(self):
        setup = swift_method(self.source, 'setUpWithError')
        self.assertLess(setup.index('app = nil'), setup.index('try bindCaptureRunner()'))
        self.assertLess(setup.index('try bindCaptureRunner()'), setup.index('app = XCUIApplication()'))
        self.assertLess(setup.index('try bindCaptureRunner()'), setup.index('app.launch()'))
        self.assertEqual(self.source.count('try bindCaptureRunner()'), 1)
        self.assertNotIn('if ', setup.split('try bindCaptureRunner()')[0])
        for method, _ in CASES.values():
            self.assertIn('func ' + method + '()', self.source)
            self.assertNotIn('bindCaptureRunner', swift_method(self.source, method))
        self.assertNotIn('TOUCHCOLOR_PHOTOS_RUNNER_READY', self.source)
        self.assertNotIn('TouchColor-runner-', swift_method(self.source, 'photo'))

    def test_new_lease_is_only_accepted_after_bounded_exact_ack(self):
        binding = swift_method(self.source, 'bindCaptureRunner')
        self.assertIn('let lease = UUID()', binding)
        self.assertIn('options: .atomic', binding)
        self.assertIn('TOUCHCOLOR_VISION_RUNNER_READY', binding)
        self.assertIn('timeout: 60) == .completed else', binding)
        self.assertEqual(binding.count('throw NSError('), 2)
        for proof in ['binding?["success"] as? Bool == true',
                      'binding?["lease"] as? String == lease.uuidString',
                      'binding?["runner"] as? String == runner']:
            self.assertLess(binding.index(proof), binding.index('captureLease = lease'))
        self.assertIn('if !accepted { removeOwnedTemporaryFileIfPresent(request) }', binding)
        self.assertLess(binding.index('captureLease = lease'), binding.index('accepted = true'))

    def test_owned_cleanup_checks_existence_without_accepting_failed_binding(self):
        cleanup=swift_method(self.source,'removeOwnedTemporaryFileIfPresent')
        self.assertLess(cleanup.index('fileExists(atPath: url.path)'),cleanup.index('try? FileManager.default.removeItem(at: url)'))
        self.assertEqual(self.source.count('FileManager.default.removeItem'),1)
        for method in ('bindCaptureRunner','capture','tearDownWithError'):
            self.assertIn('removeOwnedTemporaryFileIfPresent',swift_method(self.source,method))
        binding=swift_method(self.source,'bindCaptureRunner')
        self.assertIn('Current runner binding timed out before UI work',binding)
        self.assertIn('Current runner binding acknowledgement did not match',binding)
        self.assertEqual(binding.count('throw NSError('),2)
        self.assertLess(binding.index('binding?["success"]'),binding.index('captureLease = lease'))
        # Source order preserves failed writes and malformed/mismatched ack as failures.
        self.assertLess(binding.index('defer {'),binding.index('.write(to: request'))
        self.assertIn('if !accepted { removeOwnedTemporaryFileIfPresent(request) }',binding)

    def test_only_outer_hosted_and_binding_allowances_change(self):
        source=(ROOT/'scripts/test_extra_platforms.py').read_text()
        self.assertIn('hosted_code=run(hosted_command,600,required=False)',source)
        self.assertIn("'-default-test-execution-time-allowance','180' if kind=='vision'",source)
        self.assertIn("'-maximum-test-execution-time-allowance','360' if kind=='vision'",source)
        self.assertNotIn('hosted_code=run(hosted_command,360',source)
        from job_budget import JobBudget,create_record
        from test_job_budget import Clock
        clock=Clock()
        env={'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_JOB_MINUTES':'35','GITHUB_SHA':'a'*40,
             'TOUCHCOLOR_JOB_STARTED_EPOCH':str(clock.wall),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(clock.mono)}
        budget=JobBudget(create_record(env,wall=lambda:clock.wall,monotonic=lambda:clock.mono),wall=lambda:clock.wall,monotonic=lambda:clock.mono)
        self.assertEqual(budget.remaining(),1500)
        # Actual pre-hosted cost rounded up224s; two600s outer grants leave76s work.
        clock.mono+=224
        self.assertEqual(budget.admit('hosted',600,minimum=420,cleanup=0),600)
        clock.mono+=600
        self.assertEqual(budget.admit('UI',600,minimum=420,cleanup=0),600)
        self.assertEqual(budget.remaining()-600,76)
        clock.mono+=257
        from job_budget import BudgetExhausted
        with self.assertRaises(BudgetExhausted):budget.admit('UI',600,minimum=420,cleanup=0)

    def test_unbound_setup_cannot_request_teardown_capture(self):
        teardown = swift_method(self.source, 'tearDownWithError')
        self.assertLess(teardown.index('if let app {'), teardown.index('capture("Native Vision failure")'))
        self.assertIn('> 0 && captureLease != nil', teardown)
        self.assertIn('captureLease = nil', teardown)
        capture = swift_method(self.source, 'capture')
        prefix = capture[:capture.index('let id = UUID()')]
        self.assertIn('guard let captureLease else', prefix)
        self.assertIn('XCTFail(', prefix)
        self.assertIn('return', prefix)
        self.assertIn('"lease": captureLease.uuidString', capture)
        self.assertIn('timeout: 85', capture)
        self.assertNotIn('?? ""', capture.split('"lease":')[1])

    def test_app_only_relaunch_preserves_lease_and_original_case_assertions(self):
        method = swift_method(self.source, 'testRealPastePrecisionZoomPaletteAndRelaunch')
        self.assertIn('app.terminate(); app.launchArguments', method)
        self.assertNotIn('captureLease', method)
        # Exact base-532 method bytes protect all functional assertions and case caps.
        expected = {
            'testRealPhotosImport': '8325efdf7eb1b04a1bc649019168ac77c94b92a0b50338e15c4cafb11ac4fccd',
            'testRealPastePrecisionZoomPaletteAndRelaunch': '227f3baccb8cceb5df2f8e31cae60fb8c53ab879156599619fb6e176de6485fe',
            'testNativeExportSaveAndReopenActualPNG': '832ebabe13bcf22c75a9cb0e5f42630f38f447fa2fd8e9fb2ac1ffab3fb188d9',
            'testNativePaletteExportReopensActualChangedSelectionAndDuplicates': '1e385b26cc0c83f604a860c88858b71e715536950e6621ab5d9c21b015fa1f4d',
            'testRealFilesPickerSelectsExportedPNG': '4d0ed7d8995c2db33ed495de3d746e398b35b98a94db1b1b87d4d6b6d60b5547',
            'testChinesePasteAndPrecisionControls': 'b74d2d66703efb2267990945519b811be5fc0065bffaecf89d45370659902df5',
            'testNativeFileAndPhotosCancelRepeatedly': 'd6b39c5894bbe1629e5d28e96750ae5d04b55744e65197bed9fa6afdb5a4d3dc',
            'testOfficialAccessibilityEmptyAndPastedCanvas': '21771b14cd49cd65f4a18f33e647fbb0e673d43d20b41cbce94442622853d28e',
            'testOfficialAccessibilityCorruptPasteRetainsPreviousSource': '8c3bb9cf9d27568bec531e079563e0b280926397ea693e2fc13db2003837c0a8',
        }
        self.assertEqual(set(expected), {method for method, _ in CASES.values()})
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256(swift_method(self.source, name).encode()).hexdigest(), digest)

    def test_capture_helper_changes_only_owned_lookup_15_to_30(self):
        self.assertEqual(hashlib.sha256((ROOT/'scripts/capture_simulator_checkpoint.py').read_bytes().replace(b"device,runner_identifier,'data'],text=True,timeout=30)",b"device,runner_identifier,'data'],text=True,timeout=15)",1)).hexdigest(),
                         '204bdb363a3345d92527dba66e7865e86243a37ba35b2f0d1af829c1e7c07a47')


class RunnerLeaseDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.prime = Mock(return_value={'success': True, 'lease': LEASE})
        self.capture = Mock(return_value={'success': True})
        self.fail = Mock(return_value={'success': False, 'acknowledged': False})
        source = (ROOT/'scripts/test_extra_platforms.py').read_text()
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        self.state = dict(Path=Path, datetime=datetime, time=time, json=json, re=re, threading=threading,
                          os=os, subprocess=subprocess, stop_group=stop_group, print=lambda *a, **k: None,
                          kind='vision', device={'udid': DEVICE}, out=Path(self.temp.name),
                          prime_container=self.prime, capture_checkpoint=self.capture, fail_cached_capture=self.fail,
                          report={'captures': [], 'stages': [], 'ui_runner_identifier': RUNNER})
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'actual-native-run', 'exec'), self.state)

    def run_lines(self, *lines):
        script = '\n'.join('print(' + repr(line) + ', flush=True)' for line in lines)
        with patch('job_budget.enabled_budget', return_value=None):
            return self.state['run']([sys.executable, '-c', script], 3, required=False)

    def test_all_nine_rows_prime_then_capture_with_no_late_lookup_route(self):
        for case in CASES:
            with self.subTest(case=case), patch.dict(os.environ, {'TOUCHCOLOR_VISION_CASE': case}):
                order = []
                self.prime.side_effect = lambda *a: order.append('prime') or {'success': True}
                self.capture.side_effect = lambda *a, **k: order.append('capture') or {'success': True}
                self.assertEqual(self.run_lines('TOUCHCOLOR_VISION_RUNNER_READY ' + LEASE,
                                               'TOUCHCOLOR_CAPTURE_REQUEST ' + REQUEST), 0)
                self.assertEqual(order, ['prime', 'capture'])
                self.prime.assert_called_with(DEVICE, RUNNER, LEASE)
                self.assertIs(self.capture.call_args.kwargs['require_primed'], True)
                self.assertTrue(self.capture.call_args.kwargs['may_start']())
                stage = self.state['report']['stages'][-1]
                self.assertTrue(stage['process_group_gone']); self.assertTrue(stage['capture_reader_finished'])
        self.fail.assert_not_called()

    def test_outer_timeout_before_case_output_is_incomplete_without_ui_binding(self):
        # The74cc paste row emitted no Test Suite/Case or runner-ready before
        # its360s outer stop. Exercise the same run path with a short local clock.
        with patch('job_budget.enabled_budget',return_value=None):
            code=self.state['run']([sys.executable,'-c','import time; time.sleep(3)'],.05,required=False)
        self.assertEqual(code,124)
        stage=self.state['report']['stages'][-1]
        self.assertTrue(stage['started']);self.assertTrue(stage['timed_out'])
        self.prime.assert_not_called();self.capture.assert_not_called()
        self.assertNotIn('vision_hosted_result',self.state['report'])

    def test_unknown_binding_cleanup_stops_capture_and_next_command(self):
        error = subprocess.TimeoutExpired('synthetic lookup', 15); error.cleanup_confirmed = False
        self.prime.side_effect = error
        self.assertEqual(self.run_lines('TOUCHCOLOR_VISION_RUNNER_READY ' + LEASE,
                                       'TOUCHCOLOR_CAPTURE_REQUEST ' + REQUEST), 124)
        self.capture.assert_not_called()
        self.assertIs(self.fail.call_args.kwargs['require_primed'], True)
        with patch('job_budget.enabled_budget', return_value=None), patch.object(subprocess, 'Popen') as start:
            self.assertEqual(self.state['run'](['never-start'], 3, required=False), 124)
        start.assert_not_called()
        self.assertFalse(self.state['report']['runner_container_cache']['success'])

    def test_capture_exception_can_only_acknowledge_through_primed_path(self):
        self.capture.side_effect = ValueError('Current lease is missing')
        self.assertEqual(self.run_lines('TOUCHCOLOR_CAPTURE_REQUEST ' + REQUEST), 0)
        self.assertIs(self.capture.call_args.kwargs['require_primed'], True)
        self.assertIs(self.fail.call_args.kwargs['require_primed'], True)
        self.assertFalse(self.state['report']['captures'][-1]['success'])
        self.prime.assert_not_called()

    def test_each_test_invocation_renews_binding_even_on_same_device(self):
        next_lease = str(uuid.uuid4()).upper()
        self.run_lines('TOUCHCOLOR_VISION_RUNNER_READY ' + LEASE)
        self.run_lines('TOUCHCOLOR_VISION_RUNNER_READY ' + next_lease)
        self.assertEqual([call.args for call in self.prime.call_args_list],
                         [(DEVICE, RUNNER, LEASE), (DEVICE, RUNNER, next_lease)])


class RunnerLeaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name)/'Devices').resolve()
        self.container = self.root/DEVICE/'data/Containers/Data/Application'/str(uuid.uuid4()).upper()
        (self.container/'tmp').mkdir(parents=True)
        self.lease_file = self.container/'tmp'/('TouchColor-runner-' + LEASE + '.json')
        self.lease_file.write_text(json.dumps({'id': LEASE, 'runner': RUNNER}))
        self.request = self.container/'tmp'/('TouchColor-capture-' + REQUEST + '.json')
        self.write_request(REQUEST, LEASE)
        checkpoint._containers.clear(); checkpoint._bindings.clear()
        self.addCleanup(checkpoint._containers.clear); self.addCleanup(checkpoint._bindings.clear)

    def write_request(self, identifier, lease):
        request = self.container/'tmp'/('TouchColor-capture-' + identifier + '.json')
        request.write_text(json.dumps({'id': identifier, 'name': 'Native Vision synthetic checkpoint', 'runner': RUNNER, 'lease': lease}))
        return request

    def prime(self, lease=LEASE):
        with patch.object(checkpoint, 'check_output', return_value=str(self.container)) as lookup:
            result = checkpoint.prime_container(DEVICE, RUNNER, lease, device_root=self.root)
        lookup.assert_called_once_with(['xcrun', 'simctl', 'get_app_container', DEVICE, RUNNER, 'data'], text=True, timeout=30)
        return result

    def blocked_capture(self, request=REQUEST):
        with patch.object(checkpoint, 'check_output') as lookup, patch.object(checkpoint, 'run_captured') as command:
            try:
                result = checkpoint.capture(DEVICE, RUNNER, request, self.container/'images', require_primed=True)
            except (OSError, ValueError):
                result = {'success': False}
            failure = checkpoint.fail_cached_capture(DEVICE, RUNNER, request, 'Rejected stale capture', require_primed=True)
        self.assertFalse(result['success']); self.assertFalse(failure['acknowledged'])
        lookup.assert_not_called(); command.assert_not_called()
        self.assertFalse((self.container/'tmp'/('TouchColor-capture-' + request + '.ack')).exists())

    def test_missing_binding_does_not_discover_container_or_start_command(self):
        self.blocked_capture()

    def test_removed_lease_does_not_relookup_or_acknowledge(self):
        self.prime(); self.lease_file.unlink(); self.blocked_capture()

    def test_wrong_lease_runner_or_device_does_not_relookup(self):
        self.prime()
        for description in [{'id': LEASE, 'runner': 'other.runner'}, {'id': REQUEST, 'runner': RUNNER}]:
            self.lease_file.write_text(json.dumps(description)); self.blocked_capture()
        self.lease_file.write_text(json.dumps({'id': LEASE, 'runner': RUNNER}))
        with patch.object(checkpoint, 'check_output') as lookup, patch.object(checkpoint, 'run_captured') as command:
            with self.assertRaises(ValueError):
                checkpoint.capture(REQUEST, RUNNER, REQUEST, self.container/'images', require_primed=True)
        lookup.assert_not_called(); command.assert_not_called()

    def test_failed_new_binding_cannot_fall_back_to_previous_valid_lease(self):
        self.prime()
        next_lease = str(uuid.uuid4()).upper()
        with self.assertRaises(ValueError): self.prime(next_lease)
        self.write_request(REQUEST, next_lease); self.blocked_capture()

    def test_new_test_binding_rejects_previous_lease_requests(self):
        self.prime()
        next_lease = str(uuid.uuid4()).upper()
        (self.container/'tmp'/('TouchColor-runner-' + next_lease + '.json')).write_text(json.dumps({'id': next_lease, 'runner': RUNNER}))
        self.prime(next_lease); self.blocked_capture()

    def test_replaced_container_or_linked_nonce_fails_without_command(self):
        self.prime()
        old = self.container.with_name(self.container.name + '-old'); self.container.rename(old)
        (self.container/'tmp').mkdir(parents=True)
        self.lease_file.write_text(json.dumps({'id': LEASE, 'runner': RUNNER}))
        self.write_request(REQUEST, LEASE); self.blocked_capture()
        self.prime()
        self.lease_file.unlink(); self.lease_file.symlink_to(old/'tmp'/self.lease_file.name)
        self.blocked_capture()

    def test_symlinked_temporary_root_builds_the_real_fixture_canonically(self):
        with tempfile.TemporaryDirectory() as folder:
            parent=Path(folder).resolve();physical=parent/'physical';physical.mkdir()
            alias=parent/'alias';alias.symlink_to(physical, target_is_directory=True)
            class AliasedTemporaryDirectory:
                name=str(alias)
                def cleanup(self): pass # The enclosing real temporary directory owns cleanup.
            nested=RunnerLeaseIdentityTests('test_fresh_runner_container_requires_new_priming_and_rejects_old_request')
            try:
                with patch.object(tempfile,'TemporaryDirectory',return_value=AliasedTemporaryDirectory()):
                    nested.setUp()
                self.assertEqual(nested.root,physical/'Devices')
                nested.test_fresh_runner_container_requires_new_priming_and_rejects_old_request()
            finally:
                nested.doCleanups()

    def test_fresh_runner_container_requires_new_priming_and_rejects_old_request(self):
        self.prime()
        previous = self.container
        self.container = self.container.with_name(str(uuid.uuid4()).upper())
        (self.container/'tmp').mkdir(parents=True)
        next_lease = str(uuid.uuid4()).upper()
        (self.container/'tmp'/('TouchColor-runner-' + next_lease + '.json')).write_text(json.dumps({'id': next_lease, 'runner': RUNNER}))
        next_request = str(uuid.uuid4()).upper()
        self.write_request(next_request, next_lease)
        # The new runner's request is absent in the old cached container.
        self.blocked_capture(next_request)
        self.prime(next_lease)
        self.assertEqual(checkpoint._containers[(DEVICE, RUNNER)], self.container)
        self.assertEqual(checkpoint._bindings[(DEVICE, RUNNER)]['lease'], next_lease)
        self.write_request(REQUEST, LEASE); self.blocked_capture()
        self.assertTrue(previous.is_dir())

    def test_same_runner_lease_reused_across_app_only_relaunch_checkpoints(self):
        self.prime()
        def screenshot(command, **options):
            self.assertEqual(options['timeout'], 20)
            Path(command[-1]).write_bytes(b'synthetic screenshot')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(checkpoint, 'check_output') as lookup, patch.object(checkpoint, 'run_captured', side_effect=screenshot) as command:
            for identifier in [REQUEST, str(uuid.uuid4()).upper()]:
                self.write_request(identifier, LEASE)
                result = checkpoint.capture(DEVICE, RUNNER, identifier, self.container/'images', require_primed=True)
                self.assertTrue(result['success'])
        lookup.assert_not_called(); self.assertEqual(command.call_count, 2)
        self.assertEqual(checkpoint._bindings[(DEVICE, RUNNER)]['lease'], LEASE)


if __name__ == '__main__': unittest.main()
