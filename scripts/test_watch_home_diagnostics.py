import hashlib
import json
from pathlib import Path
import unittest
from watch_home_diagnostics import (COLD_CASE, EVENTS, MAX_REPORT_BYTES, summarize_home_notifications)

ROOT = Path(__file__).resolve().parents[1]


def event(kind='appear', counts=None, omitted=None, pid=42, **changes):
    value = dict(case=COLD_CASE, pid=pid, uptimeMilliseconds=12,
                 event=kind, counts=counts or [1, 0, 0, 0],
                 omitted=omitted or [0, 0, 0, 0], saturated=False, terminal=False)
    value.update(changes)
    return ('2026-10-05 02:00:00.000 Df TouchColor[' + str(pid) + ':abc] '
            '[com.mango.touchColor.WatchDiagnostics:home] WATCH_HOME ' + json.dumps(value, separators=(',', ':')))


class HomeDiagnosticsTests(unittest.TestCase):
    def test_exact_cold_and_rgb_test_file_is_frozen(self):
        data = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'dea14e485da6362a72f5899e09299651699e32f7d7f95d2aed34f22e1bcd1a52')
        source = data.decode()
        for name, sha in [('testHomeListDigitalCrownFromColdLaunch', '88fa1a296a636c8332dbb56a3c25e40a95750f810e13d9cfa9141405e3147d14'),
                          ('testRealDigitalCrownChangesRGBComponent', '846f404ac51fb6d998e2e56428af80e4cb6cd6e5705546c821521188edbe25bb')]:
            start = source.rfind('\n', 0, source.index('func ' + name)) + 1
            end = source.index('\n    }\n', start) + 7
            self.assertEqual(hashlib.sha256(source[start:end].encode()).hexdigest(), sha)

    def test_observer_has_no_view_invalidations_or_focus_behavior(self):
        code = (ROOT / 'TouchColorWatch/WatchHomeDiagnostics.swift').read_text()
        self.assertTrue(code.startswith('#if DEBUG\n'))
        self.assertTrue(code.endswith('#endif\n'))
        for token in ('@Published', '@State', 'ObservableObject', '.send(', 'Task {', 'Timer', 'focus', 'digitalCrown', 'WatchPalette(', 'WatchTransfer('):
            self.assertNotIn(token, code)
        self.assertIn('private static let limits: [UInt32] = [4, 4, 8, 8]', code)
        self.assertIn('UInt32.max', code)
        self.assertIn('counts[index] <= limits[index] + 1', code)
        self.assertIn('payload.utf8.count <= 512', code)
        self.assertIn('private static let enabled = testCase == "' + COLD_CASE + '"', code)
        home = (ROOT / 'TouchColorWatch/WatchViews.swift').read_text().split('struct WatchSwatch')[0]
        self.assertEqual(home.count('.onReceive('), 2)
        self.assertIn('.onReceive(palette.objectWillChange)', home)
        self.assertIn('.onReceive(transfer.objectWillChange)', home)
        self.assertNotIn('@State', home)
        for token in ('focusable', 'prefersDefaultFocus', 'digitalCrownRotation', '.id('): self.assertNotIn(token, home)

    def test_separate_counters_and_log_timestamp_pid_are_preserved(self):
        lines = [event(), event('palette', [1, 0, 1, 0]), event('transfer', [1, 0, 1, 1]),
                 event('palette', [1, 0, 9, 1], [0, 0, 1, 0]),
                 event('disappear', [1, 1, 55, 13], [0, 0, 47, 5])]
        result = summarize_home_notifications('\n'.join(lines))
        self.assertEqual(result['invalid_records'], 0)
        self.assertEqual(result['counter_order'], EVENTS)
        self.assertEqual(result['records'][-1]['omitted'], [0, 0, 47, 5])
        self.assertEqual(result['records'][0]['pid'], 42)
        self.assertEqual(result['records'][0]['log_timestamp'], '2026-10-05 02:00:00.000 Df')
        self.assertTrue(result['counts_are_lower_bounds'])
        self.assertFalse(result['terminal_snapshot'])
        self.assertTrue(result['truncated'])

    def test_app_snapshot_is_never_promoted_to_terminal_or_exhaustive(self):
        result = summarize_home_notifications(event())
        self.assertFalse(result['truncated'])
        self.assertFalse(result['terminal_snapshot'])
        self.assertTrue(result['counts_are_lower_bounds'])
        result = summarize_home_notifications(event(terminal=True))
        self.assertEqual(result['invalid_records'], 1)

    def test_rejects_nonmonotonic_impossible_or_private_records(self):
        cases = [event(counts=[1, 0, True, 0]), event(counts=[1, 0, 2**32, 0]),
                 event(omitted=[0, 0, 1, 0]), event(secret='private'), event(pid=-1),
                 event(uptimeMilliseconds=-1), event('palette'), event(saturated=1),
                 event().replace('TouchColor[', 'Unrelated['),
                 event().replace('"pid":42', '"pid":43')]
        result = summarize_home_notifications('\n'.join(cases))
        self.assertEqual(result['invalid_records'], len(cases))
        self.assertEqual(result['records'], [])
        self.assertNotIn('private', json.dumps(result))
        result = summarize_home_notifications(event('palette', [1, 0, 2, 0]) + '\n' + event('palette', [1, 0, 1, 0]))
        self.assertEqual(result['invalid_records'], 1)

    def test_bound_and_omissions_remain_explicit(self):
        result = summarize_home_notifications('\n'.join(event(pid=n+1) for n in range(1000)))
        self.assertEqual(len(result['records']), 28)
        self.assertEqual(result['omitted_records'], 972)
        self.assertLessEqual(len(json.dumps(result, separators=(',', ':')).encode()), MAX_REPORT_BYTES)
        self.assertTrue(result['truncated'])

    def test_worst_counter_encoding_respects_actual_runtime_indentation(self):
        row = event('palette', [2**32-1]*4, [2**32-1]*4, pid=2**31-1,
                    saturated=True, uptimeMilliseconds=2**63-1)
        result = summarize_home_notifications('\n'.join([row]*100))
        self.assertLessEqual(len(json.dumps({'watch_home_notifications': result}, indent=2).encode()), MAX_REPORT_BYTES)
        self.assertEqual(len(result['records']) + result['omitted_records'], 100)

    def test_no_foreign_case_can_be_a_cold_observation(self):
        result = summarize_home_notifications(event(case='wrong'))
        self.assertEqual(result['foreign_records'], 1)
        self.assertEqual(result['records'], [])
        with self.assertRaises(ValueError): summarize_home_notifications('', expected_case='wrong')

    def test_counter_saturation_is_retained_without_an_exhaustive_claim(self):
        result = summarize_home_notifications(event('palette', [1, 0, 2**32-1, 0], [0, 0, 2**32-1, 0], saturated=True))
        self.assertEqual(result['invalid_records'], 0)
        self.assertTrue(result['records'][0]['saturated'])
        self.assertTrue(result['counts_are_lower_bounds'])

    def test_existing_log_capture_reuses_same_subsystem_and_timeout(self):
        code = (ROOT / 'scripts/test_extra_platforms.py').read_text()
        self.assertIn('summarize_home_notifications(lifecycle.stdout)', code)
        self.assertIn("'--predicate','subsystem == \"com.mango.touchColor.WatchDiagnostics\"'],text=True,timeout=15)", code)


if __name__ == '__main__': unittest.main()
