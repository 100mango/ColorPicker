"""Non-native adversarial harness contract tests; no Apple tools are launched."""
import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ios_watch_phone_smoke as smoke
from ios_watch_archive_capture import CaptureStopped

CASE = 'CelluloidUITests/CelluloidUITests/testProductionWatchPhotosEmptyAndReturn'
DEVICE = 'A2E0E7B0-0A3B-47D3-94E5-309F3614E54A'
SHA = 'a' * 40
BASE = 'b' * 40
TREE = 'c' * 40
CONFIG = dict(repository='100mango/Celluloid', project='Celluloid-iOS-Watch.xcodeproj',
              scheme='Celluloid', base=BASE, case=CASE, expected_changes=['A\tScripts/ios_watch_phone_smoke.py'])
ENV = dict(GITHUB_EVENT_NAME='push', GITHUB_REPOSITORY=CONFIG['repository'], GITHUB_REF=smoke.BRANCH,
           GITHUB_RUN_ATTEMPT='1', GITHUB_SHA=SHA, GITHUB_WORKFLOW_SHA=SHA,
           GITHUB_WORKFLOW_REF=CONFIG['repository'] + '/' + smoke.WORKFLOW + '@' + smoke.BRANCH,
           GITHUB_RUN_ID='42', DEVELOPER_DIR='/Applications/Xcode_27.app/Contents/Developer')


def raw(case=CASE, state='passed'):
    target, cls, method = case.split('/')
    name = '-[' + target + '.' + cls + ' ' + method + ']'
    return ("Test Case '" + name + "' started.\nTest Case '" + name + "' " + state +
            ' (0.100 seconds).\nExecuted 1 test, with 0 failures (0 unexpected) in 0.100 (0.100) seconds\n** TEST EXECUTE SUCCEEDED **\n').encode()


def summary(device=DEVICE):
    return dict(result='Passed', totalTestCount=1, passedTests=1, failedTests=0, skippedTests=0,
                expectedFailures=0, testFailures=[], startTime=1.0, finishTime=2.0,
                devicesAndConfigurations=[dict(passedTests=1, failedTests=0, skippedTests=0,
                expectedFailures=0, device=dict(deviceId=device, modelName=smoke.DEVICE_MODEL,
                platform='iOS Simulator', osVersion='27.0', osBuildNumber='24A434', architecture='arm64'))])


class RawTests(unittest.TestCase):
    def test_accepts_exact_case(self):
        self.assertEqual(smoke.verify_raw(raw(), b'', CASE)['passed'], 1)

    def test_accepts_objc_unqualified_class(self):
        text = raw().replace(b'CelluloidUITests.CelluloidUITests', b'CelluloidUITests')
        self.assertEqual(smoke.verify_raw(text, b'', CASE)['executions'], 1)

    def test_rejects_empty_filter_miss(self):
        for value in (b'', b'** TEST EXECUTE SUCCEEDED **', raw().replace(b'Executed 1 test', b'Executed 0 tests')):
            with self.subTest(value=value), self.assertRaises(smoke.Rejected):
                smoke.verify_raw(value, b'', CASE)

    def test_rejects_skip_fail_duplicate_wrong(self):
        values = [raw(state='skipped'), raw(state='failed'), raw() + raw(),
                  raw().replace(b'testProductionWatchPhotosEmptyAndReturn', b'testOther')]
        for value in values:
            with self.subTest(value=value), self.assertRaises(smoke.Rejected):
                smoke.verify_raw(value, b'', CASE)

    def test_rejects_other_case(self):
        value = raw() + raw('Other/Other/testOther')
        with self.assertRaises(smoke.Rejected):
            smoke.verify_raw(value, b'', CASE)

    def test_rejects_errors_and_bad_terminal(self):
        for out, err in [(raw(), b'file.swift:7: error: failure'), (raw().replace(b'TEST EXECUTE SUCCEEDED', b'TEST EXECUTE FAILED'), b'')]:
            with self.subTest(out=out), self.assertRaises(smoke.Rejected):
                smoke.verify_raw(out, err, CASE)

    def test_rejects_build_legacy_duplicate_and_mixed_terminals(self):
        for value in (raw().replace(b'TEST EXECUTE SUCCEEDED', b'TEST BUILD SUCCEEDED'),
                      raw().replace(b'TEST EXECUTE SUCCEEDED', b'TEST SUCCEEDED'),
                      raw() + b'** TEST EXECUTE SUCCEEDED **\n',
                      raw() + b'** TEST SUCCEEDED **\n',
                      raw() + b'** TEST BUILD SUCCEEDED **\n'):
            with self.subTest(value=value), self.assertRaises(smoke.Rejected):
                smoke.verify_raw(value, b'', CASE)


class SummaryTests(unittest.TestCase):
    def test_accepts_one_owned_phone(self):
        self.assertEqual(smoke.verify_summary(summary(), DEVICE)['counts']['passedTests'], 1)

    def test_rejects_invalid_counts(self):
        for key in ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests', 'expectedFailures'):
            for value in (True, -1, 2):
                data = summary(); data[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(smoke.Rejected):
                    smoke.verify_summary(data, DEVICE)

    def test_rejects_wrong_device_runtime_and_model(self):
        for key, value in [('deviceId', '0' * 36), ('osVersion', '26.0'), ('platform', 'watchOS Simulator'), ('modelName', 'other')]:
            data = summary(); data['devicesAndConfigurations'][0]['device'][key] = value
            with self.subTest(key=key), self.assertRaises(smoke.Rejected):
                smoke.verify_summary(data, DEVICE)

    def test_rejects_multiple_devices_and_unfinalized_result(self):
        for key, value in [('result', 'Failed'), ('finishTime', 0), ('startTime', float('nan')), ('testFailures', [{}]), ('devicesAndConfigurations', [])]:
            data = summary(); data[key] = value
            with self.subTest(key=key), self.assertRaises(smoke.Rejected):
                smoke.verify_summary(data, DEVICE)


class LogsTests(unittest.TestCase):
    def test_log_retention_bound_and_full_hash_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            stdout = b'a' * 8_000_000 + b'\nfile.swift:8: error: middle diagnostic\n' + b'b' * 7_000_000
            stderr = b'tail issue\n'
            info = smoke.retain_logs(out, stdout, stderr, True)
            self.assertLessEqual(sum(p.stat().st_size for p in out.iterdir()), smoke.RETAIN_CAP)
            self.assertIn('complete', info['hash_scope'])
            self.assertIn(b'middle diagnostic', (out / 'test.errors.log').read_bytes())
            self.assertIn(b'TRUNCATED', (out / 'test.stdout.log').read_bytes())

    def test_stopped_capture_claims_prefix_only(self):
        with tempfile.TemporaryDirectory() as folder:
            info = smoke.retain_logs(Path(folder), b'x', b'error: fail', False)
            self.assertFalse(info['capture_complete'])
            self.assertEqual(info['hash_scope'], 'captured prefixes only')

    def test_utf8_expansion_retention_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            info = smoke.retain_logs(Path(folder), b'\xff' * 200000, b'\xfe' * 200000, True)
            self.assertLessEqual(sum(row['bytes'] for row in info['retained'].values()), smoke.RETAIN_CAP)


class CommandTests(unittest.TestCase):
    def test_one_phone_case_no_watch_retry_or_signing(self):
        command = smoke.test_command(CONFIG, Path('/tmp/owned'), DEVICE)
        self.assertEqual(command[:2], ['xcodebuild', 'test-without-building'])
        self.assertEqual([arg for arg in command if arg.startswith('-only-testing:')], ['-only-testing:' + CASE])
        self.assertEqual(command.count('-destination'), 1)
        self.assertIn('platform=iOS Simulator,id=' + DEVICE, command)
        self.assertNotIn('-retry-tests-on-failure', command)
        self.assertNotIn('watchOS Simulator', ' '.join(command))
        self.assertIn('CODE_SIGNING_ALLOWED=NO', command)
        self.assertEqual(command[command.index('-test-iterations') + 1], '1')

    def test_source_fail_closed_on_event_attempt_branch(self):
        for key, value in [('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_WORKFLOW_SHA', BASE)]:
            env = dict(ENV); env[key] = value
            with self.subTest(key=key), self.assertRaises(smoke.Rejected):
                smoke.source_identity(CONFIG, env, lambda *a: self.fail('must reject before git'))

    def test_duplicate_json_keys_rejected_under_optimized_python(self):
        with self.assertRaises(smoke.Rejected):
            json.loads('{"a":1,"a":2}', object_pairs_hook=smoke.unique)

    def test_build_uses_generic_simulator_and_same_products_and_case(self):
        work = Path('/tmp/owned')
        build = smoke.build_command(CONFIG, work)
        test = smoke.test_command(CONFIG, work, DEVICE)
        self.assertEqual(build[:2], ['xcodebuild', 'build-for-testing'])
        self.assertEqual(build.count('-destination'), 1)
        self.assertEqual(build[build.index('-destination') + 1], 'generic/platform=iOS Simulator')
        self.assertNotIn(DEVICE, ' '.join(build))
        self.assertNotIn('-resultBundlePath', build)
        for flag in ('-project', '-scheme', '-configuration', '-derivedDataPath', '-clonedSourcePackagesDirPath'):
            self.assertEqual(build[build.index(flag) + 1], test[test.index(flag) + 1])
        self.assertEqual([arg for arg in build if arg.startswith('-only-testing:')], ['-only-testing:' + CASE])
        for command in (build, test):
            self.assertIn('-onlyUsePackageVersionsFromResolvedFile', command)
            self.assertIn('CODE_SIGNING_ALLOWED=NO', command)
            self.assertIn('CODE_SIGNING_REQUIRED=NO', command)
            self.assertEqual(command[command.index('-jobs') + 1], '2')
            self.assertNotIn('-retry-tests-on-failure', command)
            self.assertNotIn('watchOS Simulator', ' '.join(command))

    def test_real_config_fixes_failed_parent_three_modifications_and_original_case(self):
        config = json.loads(Path(smoke.__file__).with_name('ios_watch_phone_smoke_config.json').read_bytes())
        self.assertEqual(config['base'], '3e9a2a476726107aae9c11aad69d8ce196970bc8')
        self.assertEqual(config['expected_changes'], [
            'M\tscripts/ios_watch_phone_smoke.py',
            'M\tscripts/ios_watch_phone_smoke_config.json',
            'M\tscripts/test_ios_watch_phone_smoke.py'])
        self.assertEqual(config['repository'], '100mango/ColorPicker')
        self.assertEqual(config['project'], 'TouchColor-iOS-Watch.xcodeproj')
        self.assertEqual(config['scheme'], 'TouchColor')
        self.assertEqual(config['case'], 'TouchColorUITests/TouchColorUITests/testProductionWatchInboxEmptyAndReturn')
        self.assertEqual(smoke.BRANCH, 'refs/heads/codex/ios-watch-phone-smoke')
        self.assertEqual(smoke.RUNTIME, 'com.apple.CoreSimulator.SimRuntime.iOS-27-0')
        self.assertEqual(smoke.DEVICE_TYPE, 'com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation')
        self.assertEqual(smoke.DEVICE_MODEL, 'iPhone SE (3rd generation)')
        self.assertEqual(smoke.FIXED_FILES, ('report.json', 'phases.jsonl', 'test.stdout.log',
                         'test.stderr.log', 'test.errors.log', 'xcresult-summary.json'))
        self.assertEqual(smoke.PHASE_END, dict(prepare=180, build=480, device=530, test=840,
                         proof=900, cleanup=990, source_after=1020, evidence=1040))
        self.assertEqual(smoke.REPORT_CAP, 256 * 1024)

    def test_source_identity_rejects_wrong_parent_or_any_extra_changed_path(self):
        def identity(command):
            if command[:3] == ['git', 'rev-parse', 'HEAD']:return (SHA + '\n').encode()
            if command[:2] == ['git', 'rev-list']:return (SHA + ' ' + BASE + '\n').encode()
            if command[:2] == ['git', 'status']:return b''
            if command[:2] == ['git', 'diff']:return ('\n'.join(CONFIG['expected_changes']) + '\n').encode()
            return (TREE + '\n').encode()
        self.assertTrue(smoke.source_identity(CONFIG, ENV, identity)['clean'])
        for bad in ('parent', 'merge-parent', 'extra-change', 'wrong-status'):
            def changed(command):
                if command[:2] == ['git', 'rev-list']:
                    if bad == 'parent':return (SHA + ' ' + 'd' * 40 + '\n').encode()
                    if bad == 'merge-parent':return (SHA + ' ' + BASE + ' ' + 'd' * 40 + '\n').encode()
                if command[:2] == ['git', 'diff']:
                    if bad == 'extra-change':return identity(command) + b'M\tproduction.swift\n'
                    if bad == 'wrong-status':return identity(command).replace(b'A\t', b'M\t')
                return identity(command)
            with self.subTest(bad=bad), self.assertRaises(smoke.Rejected):
                smoke.source_identity(CONFIG, ENV, changed)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name) / 'checkout'; self.root.mkdir()
        self.temp = Path(self.sandbox.name) / 'temp'; self.temp.mkdir()
        self.output = self.temp / 'ios-watch-phone-smoke-evidence'; self.output.mkdir()
        (self.output / 'report.json').write_text(json.dumps(dict(started_monotonic=100.0, qualified=False)))
        for name in smoke.FIXED_FILES[1:]:
            (self.output / name).write_bytes(b'')
        scheme = self.root / CONFIG['project'] / 'xcshareddata/xcschemes/Celluloid.xcscheme'
        scheme.parent.mkdir(parents=True)
        scheme.write_text('<Scheme><TestAction><Testables><TestableReference><BuildableReference BlueprintName="CelluloidUITests" /></TestableReference></Testables></TestAction><LaunchAction><BuildableProductRunnable><BuildableReference BlueprintName="Celluloid" /></BuildableProductRunnable></LaunchAction></Scheme>')
        self.env = dict(ENV, RUNNER_TEMP=str(self.temp))
        self.calls = []
        self.build_code = 0
        self.build_output = b'** TEST BUILD SUCCEEDED **\n'
        self.build_errors = b''
        self.build_failure = None
        self.build_elapsed = 0
        self.cleanup_failures = {}
        self.test_code = 0
        self.test_output = raw()
        self.summary_data = summary()
        self.failure = None
        self.fail_summary = False
        self.dirty_after = False
        self.clean_checks = 0
        self.now = 100.0

    def clock(self):
        return self.now

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        self.assertGreater(kwargs['seconds'], 0)
        self.assertIn(kwargs['cleanup_grace'], [2, 10])
        out = b''
        if command[:3] == ['git', 'rev-parse', 'HEAD']: out = (SHA + '\n').encode()
        elif command[:2] == ['git', 'rev-list']: out = (SHA + ' ' + BASE + '\n').encode()
        elif command[:2] == ['git', 'status']:
            self.clean_checks += 1
            if self.dirty_after and self.clean_checks == 2:out = b' M production.swift\n'
        elif command[:2] == ['git', 'diff']: out = ('\n'.join(CONFIG['expected_changes']) + '\n').encode()
        elif command[:3] == ['git', 'rev-parse', 'HEAD^{tree}']:out = (TREE + '\n').encode()
        elif command == ['xcodebuild', '-version']:out = b'Xcode 27.0\nBuild version 27A266a\n'
        elif command[:2] == ['xcodebuild', 'build-for-testing']:
            self.now += self.build_elapsed
            if self.build_failure is not None:raise self.build_failure
            return subprocess.CompletedProcess(command, self.build_code, self.build_output, self.build_errors)
        elif command[:3] == ['xcrun', 'simctl', 'create']:out = (DEVICE + '\n').encode()
        elif command[:2] == ['xcrun', 'simctl'] and command[2] in self.cleanup_failures:
            failure = self.cleanup_failures[command[2]]
            if isinstance(failure, BaseException):raise failure
            return subprocess.CompletedProcess(command, failure, b'', b'cleanup failed')
        elif command[:2] == ['xcodebuild', 'test-without-building']:
            (self.temp / 'ios-watch-phone-smoke-work/Phone.xcresult').mkdir()
            if self.failure is not None:raise self.failure
            return subprocess.CompletedProcess(command, self.test_code, self.test_output, b'')
        elif command[:2] == ['xcrun', 'xcresulttool']:
            if self.fail_summary:raise RuntimeError('summary-export-failed')
            out = json.dumps(self.summary_data).encode()
        return subprocess.CompletedProcess(command, 0, out, b'')

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            result = smoke.execute(CONFIG, env=self.env, root=self.root, runner=self.runner, clock=self.clock)
        self.stdout = stream.getvalue()
        return result

    def test_happy_path_one_native_test_and_clean_source(self):
        result = self.execute()
        self.assertTrue(result['qualified'], result)
        tests = [command for command, _ in self.calls if command[:2] == ['xcodebuild', 'test-without-building']]
        self.assertEqual(len(tests), 1)
        simctl = [command[2] for command, _ in self.calls if command[:2] == ['xcrun', 'simctl']]
        self.assertEqual(simctl, ['create', 'shutdown', 'delete'])
        self.assertEqual(result['source_before'], result['source_after'])
        self.assertIn('command-start', self.stdout)
        self.assertIn('finished', (self.output / 'phases.jsonl').read_text())

    def assert_no_device_or_test(self, result):
        self.assertFalse(result['qualified'])
        self.assertNotIn('device', result)
        self.assertNotIn('raw_proof', result)
        self.assertNotIn('summary_proof', result)
        self.assertNotIn('test_log', result)
        self.assertFalse(any(command[:2] == ['xcrun', 'simctl'] for command, _ in self.calls))
        self.assertFalse(any(command[:2] == ['xcodebuild', 'test-without-building'] for command, _ in self.calls))
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), b'')

    def test_exact_build_create_test_order_without_manual_boot_install_or_retry(self):
        result = self.execute()
        self.assertTrue(result['qualified'], result)
        commands = [command for command, _ in self.calls]
        builds = [i for i, command in enumerate(commands) if command[:2] == ['xcodebuild', 'build-for-testing']]
        creates = [i for i, command in enumerate(commands) if command[:3] == ['xcrun', 'simctl', 'create']]
        tests = [i for i, command in enumerate(commands) if command[:2] == ['xcodebuild', 'test-without-building']]
        self.assertEqual((len(builds), len(creates), len(tests)), (1, 1, 1))
        self.assertLess(builds[0], creates[0])
        self.assertLess(creates[0], tests[0])
        self.assertEqual(commands[creates[0]][-2:], [smoke.DEVICE_TYPE, smoke.RUNTIME])
        self.assertEqual([c[2] for c in commands if c[:2] == ['xcrun', 'simctl']], ['create', 'shutdown', 'delete'])
        self.assertFalse(any(c[:2] == ['xcodebuild', 'test'] for c in commands))
        self.assertEqual(result['device']['id'], DEVICE)
        self.assertFalse(result['device']['pairing_requested'])
        self.assertTrue(result['build_for_testing_complete'])
        self.assertEqual([r['phase'] for r in result['commands'] if r['command'][:2] == ['xcodebuild', 'build-for-testing']], ['build'])

    def test_nonzero_build_prevents_device_and_test_despite_success_markers(self):
        self.build_code = 65
        self.build_output = raw() + b'** TEST BUILD SUCCEEDED **\n'
        result = self.execute()
        self.assert_no_device_or_test(result)
        self.assertNotIn('build_for_testing_complete', result)
        self.assertIn('command-nonzero:65', json.dumps(result['failures']))

    def test_build_timeout_retains_diagnostics_and_prevents_device_and_test(self):
        error = CaptureStopped('duration-limit', True)
        error.stdout_prefix = b'build prefix\n' + b'x' * 10000 + b'\nlast build output'
        error.stderr_capture = b'error: build timeout\n' + b'y' * 10000 + b'\nlast build error'
        self.build_failure = error
        result = self.execute()
        self.assert_no_device_or_test(result)
        receipt = next(r for r in result['commands'] if r['phase'] == 'build')
        self.assertFalse(receipt['complete'])
        self.assertTrue(receipt['owned_cleanup_confirmed'])
        self.assertEqual(receipt['hash_scope'], 'captured prefixes only')
        self.assertEqual(receipt['stdout_sha256'], hashlib.sha256(error.stdout_prefix).hexdigest())
        self.assertEqual(receipt['stderr_sha256'], hashlib.sha256(error.stderr_capture).hexdigest())
        self.assertIn('build prefix', receipt['stdout'])
        self.assertIn('last build output', receipt['stdout'])
        self.assertIn('error: build timeout', receipt['stderr'])
        self.assertIn('last build error', receipt['stderr'])
        self.assertLessEqual(len(receipt['stdout'].encode()), 4096)
        self.assertLessEqual(len(receipt['stderr'].encode()), 4096)
        self.assertLessEqual((self.output / 'report.json').stat().st_size, smoke.REPORT_CAP)

    def test_build_unconfirmed_cleanup_prevents_device_and_test(self):
        self.build_failure = CaptureStopped('descendant-exit-unconfirmed', False)
        result = self.execute()
        self.assert_no_device_or_test(result)
        self.assertIn(False, [r.get('owned_cleanup_confirmed') for r in result['commands']])

    def test_late_build_return_prevents_device_and_test(self):
        self.build_elapsed = 300
        result = self.execute()
        self.assert_no_device_or_test(result)
        self.assertIn('command-late-return', json.dumps(result['failures']))

    def test_build_success_without_test_records_is_not_runtime_proof(self):
        self.build_output = raw()
        self.test_output = b'** TEST EXECUTE SUCCEEDED **\n'
        result = self.execute()
        self.assertTrue(result['build_for_testing_complete'])
        self.assertFalse(result['qualified'])
        self.assertNotIn('raw_proof', result)
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), self.test_output)

    def test_large_build_diagnostics_preserve_prefix_tail_and_report_cap(self):
        self.build_output = b'build-prefix\n' + b'\x00' * 100000 + b'\nbuild-tail'
        self.build_errors = b'error-prefix\n' + b'\xff' * 100000 + b'\nerror-tail'
        self.summary_data['diagnostic'] = '\x00' * 20000
        result = self.execute()
        self.assertTrue(result['qualified'], result)
        receipt = next(r for r in result['commands'] if r['phase'] == 'build')
        self.assertEqual(receipt['hash_scope'], 'complete original streams')
        self.assertEqual(receipt['stdout_sha256'], hashlib.sha256(self.build_output).hexdigest())
        self.assertEqual(receipt['stderr_sha256'], hashlib.sha256(self.build_errors).hexdigest())
        for key, first, last in [('stdout', 'build-prefix', 'build-tail'), ('stderr', 'error-prefix', 'error-tail')]:
            self.assertIn(first, receipt[key])
            self.assertIn(last, receipt[key])
            self.assertIn('TRUNCATED', receipt[key])
            self.assertLessEqual(len(receipt[key].encode()), 4096)
        self.assertLessEqual((self.output / 'report.json').stat().st_size, smoke.REPORT_CAP)
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), raw())

    def test_build_and_test_grants_keep_original_outer_phase_deadlines(self):
        self.build_elapsed = 299
        result = self.execute()
        self.assertTrue(result['qualified'], result)
        for command, options in self.calls:
            receipt = next(r for r in result['commands'] if r['command'] == command)
            if command[:2] == ['xcodebuild', 'build-for-testing']:
                self.assertEqual(options['seconds'], 300)
                self.assertEqual(options['cap'], smoke.RAW_CAP)
                self.assertEqual(receipt['cleanup_reserve_seconds'], 20)
            elif command[:2] == ['xcodebuild', 'test-without-building']:
                self.assertEqual(options['seconds'], 521)
                self.assertEqual(receipt['cleanup_reserve_seconds'], 20)
        self.assertEqual(smoke.PHASE_END['test'], 840)
        self.assertEqual(smoke.PHASE_END['evidence'], 1040)

    def test_shutdown_nonzero_is_not_tolerated_even_when_delete_succeeds(self):
        self.cleanup_failures['shutdown'] = 149
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertEqual([(r['action'], r['confirmed']) for r in result['simulator_cleanup']], [('shutdown', False), ('delete', True)])
        self.assertIn('owned-simulator-cleanup-not-confirmed', json.dumps(result['failures']))

    def test_shutdown_timeout_is_not_tolerated_even_when_process_exit_confirmed(self):
        self.cleanup_failures['shutdown'] = CaptureStopped('duration-limit', True)
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertEqual([(r['action'], r['confirmed']) for r in result['simulator_cleanup']], [('shutdown', False), ('delete', True)])
        receipt = next(r for r in result['commands'] if r['command'][:3] == ['xcrun', 'simctl', 'shutdown'])
        self.assertTrue(receipt['owned_cleanup_confirmed'])
        self.assertFalse(receipt['complete'])

    def test_delete_unconfirmed_cleanup_stays_red_after_test_pass(self):
        self.cleanup_failures['delete'] = CaptureStopped('descendant-exit-unconfirmed', False)
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertEqual([(r['action'], r['confirmed']) for r in result['simulator_cleanup']], [('shutdown', True), ('delete', False)])

    def test_nonzero_stays_red_with_passing_markers_and_summary(self):
        self.test_code = 65
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertTrue(result.get('raw_proof'))
        self.assertTrue((self.output / 'test.stdout.log').read_bytes())

    def test_proof_failure_retains_logs_and_cleanup(self):
        self.fail_summary = True
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), raw())
        self.assertTrue(all(row['confirmed'] for row in result['simulator_cleanup']))

    def test_timeout_retains_prefix_and_never_succeeds(self):
        error = CaptureStopped('duration-limit', True)
        error.stdout_prefix = b'partial stdout\n'; error.stderr_capture = b'error: timeout\n'
        self.failure = error
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertFalse(result['test_log']['capture_complete'])
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), error.stdout_prefix)
        self.assertEqual(sum(command[:2] == ['xcodebuild', 'test-without-building'] for command, _ in self.calls), 1)

    def test_unconfirmed_process_cleanup_stays_red(self):
        error = CaptureStopped('descendant-exit-unconfirmed', False)
        error.stdout_prefix = raw(); error.stderr_capture = b''
        self.failure = error
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertIn(False, [row.get('owned_cleanup_confirmed') for row in result['commands']])

    def test_source_change_stays_red_after_successful_test(self):
        self.dirty_after = True
        result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertIn('source-dirty', json.dumps(result['failures']))

    def test_skipped_case_cannot_hide_missing_entry(self):
        self.test_output = raw(state='skipped')
        result = self.execute()
        self.assertFalse(result['qualified'])

    def test_report_packing_failure_preserves_separate_logs(self):
        original = smoke.json_bytes
        def packing(value):
            if isinstance(value, dict) and 'commands' in value:raise RuntimeError('synthetic-packing-failure')
            return original(value)
        with patch.object(smoke, 'json_bytes', packing):
            result = self.execute()
        self.assertFalse(result['qualified'])
        self.assertIn('synthetic-packing-failure', (self.output / 'report.json').read_text())
        self.assertEqual((self.output / 'test.stdout.log').read_bytes(), raw())
        self.assertIn('phase-start', (self.output / 'phases.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
