"""Portable scheduling oracles only. No Apple/XCTest execution is simulated as proof."""
import ast
import copy
import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import watch_failure_continuation as gate

ROOT = Path(__file__).resolve().parents[1]
DEVICE = 'A27B0B42-B2B4-47AC-B255-929BD8221964'
SHA = 'a' * 40
COMMAND = ['xcodebuild', 'test-without-building', '-resultBundlePath', gate.BUNDLE]
FAILED = 'WatchWorkflowTests/testEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0'


def line(identifier, result=None, seconds=1):
    cls, method = identifier.removesuffix('()').split('/')
    ending = 'started.' if result is None else f'{result} ({seconds:.3f} seconds).'
    return f"Test Case '-[TouchColorWatchUITests.{cls} {method}]' {ending}\n"


def fixture():
    counts = {'passedTests': 9, 'failedTests': 1, 'skippedTests': 1, 'expectedFailures': 0}
    capture = gate.WatchCaseLifecycle()
    for identifier in gate.NORMAL_CASES:
        capture.record(line(identifier))
        capture.record(line(identifier, 'failed' if identifier == FAILED else 'skipped' if identifier == gate.SKIPPED_CASE else 'passed'))
    summary = dict(counts, totalTestCount=11, result='Failed', startTime=110., finishTime=190.,
                   devicesAndConfigurations=[dict(counts, device={'deviceId': DEVICE, 'platform': 'watchOS Simulator',
                       'osVersion': '27.0', 'architecture': 'arm64'}, testPlanConfiguration={'configurationId': '1', 'configurationName': 'Test Scheme Action'})],
                   testFailures=[{'targetName': gate.TARGET, 'testIdentifierString': FAILED, 'failureText': 'Original failure retained verbatim',
                                  'testIdentifierURL': 'test://com.apple.xcode/TouchColorWatch/' + gate.TARGET + '/' + FAILED.removesuffix('()')}])
    stage = {'command': COMMAND.copy(), 'exit': 65, 'raw_exit': 65, 'started': True, 'timed_out': False,
             'process_group_gone': True, 'capture_reader_finished': True, 'reader_errors': [], 'cleanup_error': None,
             'started_at': datetime.datetime.fromtimestamp(100, datetime.timezone.utc).isoformat(),
             'finished_at': datetime.datetime.fromtimestamp(200, datetime.timezone.utc).isoformat(),
             'elapsed_seconds': 100., 'wall_elapsed_seconds': 100., 'timeout_seconds': 840,
             'compiler_errors': ['original unclassified diagnostic'], 'watch_case_lifecycle': capture.report}
    checkpoint = {'available': True, 'sha': SHA, 'device': {'udid': DEVICE}, 'products': {'sha256': 'b' * 64}}
    return stage, summary, checkpoint


class WatchContinuationTests(unittest.TestCase):
    def check(self, stage=None, summary=None, before=None, after=None, **kwargs):
        s, r, c = fixture()
        return gate.decision(s if stage is None else stage, COMMAND, r if summary is None else summary,
                             c if before is None else before, c if after is None else after,
                             sha=SHA, device=DEVICE, **kwargs)

    def test_complete_failed_65_can_schedule_but_is_not_reclassified(self):
        answer = self.check()
        self.assertTrue(answer['allowed'])
        self.assertEqual(answer['original_exit'], 65)
        self.assertEqual(answer['original_result'], 'failed')
        self.assertNotIn('assertion', answer['reason'])

    def test_crash_and_unknown_diagnostics_remain_failures_not_an_allowlist(self):
        for text in ('XCTAssertTrue failed', 'Crash diagnostic retained', 'Unrecognized failure'):
            stage, summary, _ = fixture()
            stage['compiler_errors'] = [text]; summary['testFailures'][0]['failureText'] = text
            original = copy.deepcopy((stage, summary))
            self.assertTrue(self.check(stage=stage, summary=summary)['allowed'])
            self.assertEqual((stage, summary), original)

    def test_non65_synthesized_timeout_unstarted_or_unclean_stage_stops(self):
        for key, bad in [('exit', 0), ('exit', 124), ('exit', -9), ('exit', True), ('raw_exit', 0),
                         ('started', False), ('timed_out', True), ('timed_out', None),
                         ('process_group_gone', False), ('process_group_gone', 1),
                         ('capture_reader_finished', None), ('capture_reader_finished', False),
                         ('reader_errors', ['OSError']), ('cleanup_error', 'unknown'), ('budget_incomplete', 'expired')]:
            with self.subTest(key=key, bad=bad):
                stage, _, _ = fixture(); stage[key] = bad
                self.assertFalse(self.check(stage=stage)['allowed'])
        self.assertFalse(self.check(cleanup_unconfirmed=True)['allowed'])

    def test_changed_command_stops(self):
        stage, _, _ = fixture(); stage['command'] += ['-retry-tests-on-failure']
        self.assertFalse(self.check(stage=stage)['allowed'])

    def test_stage_and_summary_clocks_reject_stale_future_nonfinite_and_cap(self):
        for key, bad in [('elapsed_seconds', 840), ('elapsed_seconds', -1), ('elapsed_seconds', True),
                         ('wall_elapsed_seconds', 150), ('timeout_seconds', 900), ('elapsed_seconds', float('nan')),
                         ('started_at', '1970-01-01T00:00:00'), ('finished_at', 'invalid')]:
            stage, _, _ = fixture(); stage[key] = bad
            self.assertFalse(self.check(stage=stage)['allowed'], (key, bad))
        for key, bad in [('startTime', 99), ('finishTime', 201), ('finishTime', 109), ('finishTime', float('inf')), ('startTime', True)]:
            _, summary, _ = fixture(); summary[key] = bad
            self.assertFalse(self.check(summary=summary)['allowed'])

    def test_counts_are_exact_integers_and_reconcile_destination(self):
        for key, bad in [('totalTestCount', True), ('totalTestCount', 9), ('passedTests', 8), ('failedTests', 0),
                         ('expectedFailures', 1), ('skippedTests', 2), ('passedTests', 9.0), ('failedTests', -1)]:
            _, summary, _ = fixture(); summary[key] = bad
            self.assertFalse(self.check(summary=summary)['allowed'])
        _, summary, _ = fixture(); summary['devicesAndConfigurations'][0]['passedTests'] = 8
        self.assertFalse(self.check(summary=summary)['allowed'])

    def test_exact_device_runtime_architecture_and_configuration(self):
        for key in ('deviceId', 'platform', 'osVersion', 'architecture'):
            _, summary, _ = fixture(); summary['devicesAndConfigurations'][0]['device'][key] = 'other'
            self.assertFalse(self.check(summary=summary)['allowed'])
        for rows in ([], [{}, {}]):
            _, summary, _ = fixture(); summary['devicesAndConfigurations'] = rows
            self.assertFalse(self.check(summary=summary)['allowed'])
        _, summary, _ = fixture(); summary['devicesAndConfigurations'][0]['testPlanConfiguration']['configurationId'] = '2'
        self.assertFalse(self.check(summary=summary)['allowed'])

    def test_missing_duplicate_mismatched_failure_records_stop(self):
        for change in ('missing', 'duplicate', 'target', 'identifier', 'url'):
            _, summary, _ = fixture()
            if change == 'missing': summary['testFailures'] = []
            elif change == 'duplicate': summary['testFailures'] *= 2
            else: summary['testFailures'][0][{'target': 'targetName', 'identifier': 'testIdentifierString', 'url': 'testIdentifierURL'}[change]] = 'foreign'
            self.assertFalse(self.check(summary=summary)['allowed'])

    def test_unavailable_changed_products_source_or_device_stop(self):
        for changed in ({'available': False}, {'available': True, 'sha': SHA}, dict(fixture()[2], sha='c' * 40)):
            self.assertFalse(self.check(after=changed)['allowed'])
        _, _, changed = fixture(); changed['device']['udid'] = 'foreign'
        self.assertFalse(self.check(before=changed, after=changed)['allowed'])

    def test_terminal_scope_missing_duplicate_foreign_or_contradictory_stops(self):
        for change in ('missing', 'duplicate', 'foreign', 'no_start', 'wrong_result', 'unknown', 'active', 'overflow'):
            stage, _, _ = fixture(); capture = stage['watch_case_lifecycle']; cases = capture['cases']
            if change == 'missing': cases.pop()
            elif change == 'duplicate': cases[1] = copy.deepcopy(cases[0])
            elif change == 'foreign': cases[0]['identifier'] = 'Other/test()'
            elif change == 'no_start': cases[0]['started'] = False
            elif change == 'wrong_result': cases[0]['result'] = 'skipped'
            elif change == 'unknown': cases[0]['result'] = 'running'
            elif change == 'active': capture['active'] = FAILED
            else: capture['overflow'] = True
            self.assertFalse(self.check(stage=stage)['allowed'], change)

    def test_recorded_timeout_rejects_even_finalized_result(self):
        for text in ('exceeded execution time allowance of 2 minutes.', 'Timed out after 120 seconds', 'Infrastructure timeout'):
            stage, _, _ = fixture(); capture = gate.WatchCaseLifecycle(); capture.report = stage['watch_case_lifecycle']
            capture.record(text)
            self.assertFalse(self.check(stage=stage)['allowed'])

    def test_summary_or_compiler_only_timeout_vetoes_completion(self):
        for target in ('failure', 'warning', 'insight', 'compiler'):
            stage, summary, _ = fixture()
            diagnostic = 'Test execution time exceeded execution time allowance of 120 seconds'
            if target == 'failure': summary['testFailures'][0]['failureText'] = diagnostic
            elif target == 'compiler': stage['compiler_errors'] = [diagnostic]
            else: summary[target] = [{'message': diagnostic}]
            self.assertFalse(self.check(stage=stage, summary=summary)['allowed'])

    def test_per_case_cap_and_impossible_total_duration_reject(self):
        for seconds in (120, 121, -1, float('nan'), True):
            stage, _, _ = fixture(); stage['watch_case_lifecycle']['cases'][0]['duration_seconds'] = seconds
            self.assertFalse(self.check(stage=stage)['allowed'])
        stage, _, _ = fixture()
        for case in stage['watch_case_lifecycle']['cases']: case['duration_seconds'] = 10
        self.assertFalse(self.check(stage=stage)['allowed'])

    def test_parser_rejects_retry_duplicate_mismatch_and_unknown_format(self):
        for lines in ([line(FAILED, 'failed')], [line(FAILED), line(FAILED)],
                      [line(FAILED), line(gate.NORMAL_CASES[0], 'failed')],
                      ["Test Case unknown syntax\n"], ["Test Case " + 'x' * 2048]):
            capture = gate.WatchCaseLifecycle()
            for value in lines: capture.record(value)
            self.assertGreater(capture.report['invalid'], 0)

    def test_command_echo_timeout_flags_do_not_report_a_timeout(self):
        capture = gate.WatchCaseLifecycle()
        capture.record('Command line invocation:\n')
        capture.record('    xcodebuild test-without-building -test-timeouts-enabled YES -default-test-execution-time-allowance 120 -maximum-test-execution-time-allowance 240\n')
        self.assertEqual(capture.report['timeout_records'], [])
        self.assertEqual(capture.report['invalid'], 0)

    def test_parser_is_bounded_and_ignores_unrelated_output(self):
        capture = gate.WatchCaseLifecycle()
        for _ in range(1000): capture.record('ordinary retained diagnostic\n')
        self.assertEqual(capture.report['invalid'], 0)
        for _ in range(100): capture.record(line(FAILED, 'failed'))
        for _ in range(100): capture.record('test timeout\n')
        self.assertEqual(len(capture.report['cases']), 11)
        self.assertEqual(len(capture.report['timeout_records']), 8)
        self.assertTrue(capture.report['overflow'])
        self.assertLess(len(json.dumps(capture.report).encode()), 16 * 1024)

    def test_strict_json_rejects_duplicate_boolean_counts_and_nonfinite(self):
        for raw in ('{"failedTests":1,"failedTests":0}', '{"duration":NaN}', '{"time":Infinity}'):
            with self.assertRaises(ValueError): gate.strict_json(raw)

    def test_invalid_stage_does_not_launch_summary_or_checkpoint(self):
        stage, _, before = fixture(); stage['timed_out'] = True; runner = Mock()
        answer = gate.inspect_failure({}, stage, COMMAND, before, sha=SHA, device=DEVICE, runtime=RUNTIME, runner=runner)
        self.assertFalse(answer['allowed']); runner.assert_not_called()

    def test_partial_summary_stops_before_device_or_product_queries(self):
        stage, summary, before = fixture(); summary['totalTestCount'] = 9
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(summary), ''))
        with patch.object(gate, 'checkpoint') as checkpoint:
            answer = gate.inspect_failure({}, stage, COMMAND, before, sha=SHA, device=DEVICE, runtime=RUNTIME, runner=runner)
        self.assertFalse(answer['allowed']); checkpoint.assert_not_called(); self.assertEqual(runner.call_count, 1)

    def test_summary_command_cleanup_unknown_blocks_everything(self):
        stage, _, before = fixture()
        for error in (RuntimeError('unknown runner failure'), subprocess.TimeoutExpired([], 30)):
            report = {}; runner = Mock(side_effect=error)
            answer = gate.inspect_failure(report, stage, COMMAND, before, sha=SHA, device=DEVICE, runtime=RUNTIME, runner=runner)
            self.assertFalse(answer['allowed']); self.assertTrue(report['cleanup_unconfirmed'])
        error = subprocess.TimeoutExpired([], 30); error.cleanup_confirmed = True; report = {}
        self.assertFalse(gate.inspect_failure(report, stage, COMMAND, before, sha=SHA, device=DEVICE, runtime=RUNTIME, runner=Mock(side_effect=error))['allowed'])
        self.assertNotIn('cleanup_unconfirmed', report)

    def test_completed_summary_and_unchanged_checkpoint_allow_scheduling(self):
        stage, summary, before = fixture(); runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(summary), ''))
        with patch.object(gate, 'checkpoint', return_value=before):
            answer = gate.inspect_failure({}, stage, COMMAND, before, sha=SHA, device=DEVICE, runtime=RUNTIME, runner=runner)
        self.assertTrue(answer['allowed']); self.assertEqual(len(answer['summary_sha256']), 64)

    def products(self, folder):
        root = Path(folder)
        for name in ('example.xctestrun', 'Debug-watchsimulator/TouchColor.app/TouchColor',
                     'Debug-watchsimulator/TouchColorWatchUITests-Runner.app/PlugIns/TouchColorWatchUITests.xctest/TouchColorWatchUITests'):
            p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'fixture')
        return root

    def test_products_changes_and_missing_inputs_are_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.products(folder); original = gate.product_fingerprint(root)
            (root / 'example.xctestrun').write_bytes(b'changed')
            self.assertNotEqual(original, gate.product_fingerprint(root))
            (root / 'example.xctestrun').unlink()
            with self.assertRaises(ValueError): gate.product_fingerprint(root)

    def test_product_symlink_escape_and_deadline_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.products(folder); (root / 'escape').symlink_to('/tmp')
            with self.assertRaises(ValueError): gate.product_fingerprint(root)
            (root / 'escape').unlink()
            clock = Mock(side_effect=[0, 21])
            with self.assertRaises(ValueError): gate.product_fingerprint(root, clock=clock)

    def test_failure_ledger_keeps_original_and_largest_failures(self):
        report = {}; gate.record_failure(report, 'normal', 'original 65'); gate.record_failure(report, 'largest', 'later failure')
        self.assertEqual(report['error'], 'original 65')
        self.assertEqual([row['error'] for row in report['failures']], ['original 65', 'later failure'])
        report['result'] = 'passed'
        with self.assertRaisesRegex(RuntimeError, 'original 65'): gate.require_no_failures(report)
        self.assertEqual(report['result'], 'failed')

    def execute_driver_tail(self, *, normal=65, allowed=True, largest_error=None):
        source = ast.parse((ROOT / 'scripts/test_extra_platforms.py').read_text())
        outer = next(node for node in source.body if isinstance(node, ast.Try))
        index = next(i for i, node in enumerate(outer.body) if isinstance(node, ast.If)
                     and "xctest_summary_scope" in ast.unparse(node))
        # Execute the real source branch and completion/error policy with only
        # native processes substituted. This is a scheduling oracle, not XCTest.
        code = ast.Module(body=[ast.Try(body=outer.body[index:], handlers=outer.handlers, orelse=[], finalbody=[]), source.body[-1]], type_ignores=[])
        ast.fix_missing_locations(code)
        stage, _, before = fixture(); report = {'sha': SHA, 'stages': []}
        def run(command, timeout, required=True):
            item = copy.deepcopy(stage); item['command'] = command
            result = normal if gate.BUNDLE in command else 0; item['exit'] = result
            report['stages'].append(item)
            if result and required: raise RuntimeError('stage failed')
            return result
        largest = Mock(side_effect=largest_error, return_value={'status': 'largest_ui_passed'})
        env = dict(kind='watch', report=report, test_common=['xcodebuild', 'test-without-building'], test_arguments=[],
                   device={'udid': DEVICE}, runtime=RUNTIME, WATCH_UI_BUNDLE=gate.BUNDLE,
                   watch_checkpoint=Mock(return_value=before), run=run, inspect_watch_failure=Mock(return_value={'allowed': allowed, 'reason': 'fixture'}),
                   record_failure=gate.record_failure, require_no_failures=gate.require_no_failures,
                   applicable_cases=lambda *args: ('testChineseColorEditorSave',), os=__import__('os'), json=json,
                   TouchSizeRunner=lambda _: type('Runner', (), {'cleanup_unconfirmed': False})(), Path=Path,
                   project='TouchColorWatch.xcodeproj', name='TouchColorWatch', platform='watchOS', out=Path('unused'),
                   run_largest=largest, qualified=lambda _: True, photo_seed_failed=False, subprocess=subprocess)
        with self.assertRaises(SystemExit) as ended:
            exec(compile(code, '<actual driver tail>', 'exec'), env)
        self.assertEqual(ended.exception.code, 1)
        return report, largest

    def test_actual_driver_schedules_largest_and_still_exits_failed(self):
        report, largest = self.execute_driver_tail()
        largest.assert_called_once()
        self.assertEqual(largest.call_args.kwargs, {'timeout': 600})
        self.assertEqual(report['normal_watch_ui']['exit'], 65)
        self.assertEqual(report['tests'], 'failed')
        self.assertEqual(report['largest_text_outcome']['result'], 'passed')
        self.assertEqual(report['result'], 'failed')

    def test_actual_driver_largest_error_does_not_erase_original(self):
        report, largest = self.execute_driver_tail(largest_error=RuntimeError('largest failed'))
        largest.assert_called_once()
        self.assertEqual(largest.call_args.kwargs, {'timeout': 600})
        self.assertEqual(report['largest_text_outcome']['error'], 'largest failed')
        self.assertTrue(report['error'].startswith('Stage failed with exit 65:'))
        self.assertEqual([v['phase'] for v in report['failures']], ['watch-normal-ui', 'largest-text'])
        self.assertEqual(report['result'], 'failed')

    def test_actual_driver_blocked_failure_never_starts_largest(self):
        report, largest = self.execute_driver_tail(allowed=False)
        largest.assert_not_called(); self.assertEqual(report['largest_text_outcome']['result'], 'not_started')
        self.assertEqual(report['normal_watch_ui']['exit'], 65)

    def test_scope_source_allowances_and_fresh_state_remain_exact(self):
        import re
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        names = set(re.findall(r'func (test\w+)\(', source)) - {'testPublicLargestTraitChineseColorEditorSave'}
        self.assertEqual(set(gate.NORMAL_CASES), {'WatchWorkflowTests/' + name + '()' for name in names} | {gate.SKIPPED_CASE})
        self.assertIn('name.contains("Chinese") ? 240 : 120', source)
        self.assertIn('TouchColor.watch-ui.\\(UUID())', source)
        driver = (ROOT / 'scripts/test_extra_platforms.py').read_text()
        self.assertIn('normal_code=run(normal_command,840,required=False)', driver)
        self.assertIn('size_runner,timeout=600,**deferred)', driver)
        self.assertIn("deferred={'defer_vision_summary':True,'source_sha':report['sha']} if kind=='vision' else {}", driver)
        self.assertNotIn('WatchContinuationObserver', driver)


if __name__ == '__main__': unittest.main()
