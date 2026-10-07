import json
from pathlib import Path
import re
import unittest

from watch_diagnostics import (ListFrameDiagnostics, summarize_editor_lifecycle, log_lookback,
    MAX_PROCESSES, MAX_EVENTS_PER_PROCESS, MAX_EVENT_JSON_BYTES, MAX_LIFECYCLE_JSON_BYTES,
    MAX_FRAME_RECORDS, MAX_FRAMES_PER_CASE, MAX_FRAME_REPORT_BYTES)

ROOT = Path(__file__).resolve().parents[1]


def event(pid, case, kind='focus', extra=''):
    return (f'2026-10-04 16:00:00.000 Df TouchColor[{pid}:abc] '
            f'[com.mango.touchColor.WatchDiagnostics:editor] WATCH_EDITOR {kind} '
            f'case={case} id=00000000-0000-0000-0000-000000000000 visible=false {extra}')


def frame(case='case', phase='before'):
    return {'case': case, 'phase': phase, 'viewport': [0, 0, 162, 197],
            'snapshotMilliseconds': 25, 'rows': [{'id': 'watch.editor', 'frame': [2, 47.5, 158, 44]}]}


class WatchDiagnosticsTests(unittest.TestCase):
    def test_late_lifecycle_survives_repetitive_exhaustion(self):
        lines = [event(1, 'return', 'appear')]
        lines += [event(1, 'return', extra=f'focused=true number={i}') for i in range(200)]
        lines += [event(1, 'return', 'disappear', 'dropped=184')]
        result = summarize_editor_lifecycle('\n'.join(lines))
        group = result['processes'][0]
        self.assertEqual(group['matched_events'], 202)
        self.assertEqual(len(group['events']), MAX_EVENTS_PER_PROCESS)
        self.assertIn('WATCH_EDITOR appear ', group['events'][0])
        self.assertIn('WATCH_EDITOR disappear ', group['events'][-1])
        self.assertEqual(group['app_dropped_events'], 184)
        self.assertTrue(result['truncated'])

    def test_test_and_pid_each_isolate_retention(self):
        lines = [event(pid, case) for pid, case in [(1, 'first'), (2, 'first'), (2, 'second')]]
        result = summarize_editor_lifecycle('\n'.join(lines))
        self.assertEqual([(g['pid'], g['case']) for g in result['processes']],
                         [(1, 'first'), (2, 'first'), (2, 'second')])
        self.assertFalse(result['truncated'])

    def test_unscoped_or_foreign_log_is_not_retained(self):
        lines = [event(1, 'owned'), event(2, 'wrong').replace('TouchColor[', 'Unrelated['),
                 event(3, 'wrong').replace('WatchDiagnostics:editor', 'Private:editor'),
                 'WATCH_EDITOR unexpected password=do-not-retain']
        result = summarize_editor_lifecycle('\n'.join(lines))
        self.assertEqual(len(result['processes']), 1)
        self.assertEqual(result['unparsed_events'], 3)
        self.assertNotIn('do-not-retain', json.dumps(result))

    def test_process_event_and_encoded_byte_caps_are_hard(self):
        lines = [event(pid, 'c' * 120, extra='"\\\u2603' * 400)
                 for pid in range(MAX_PROCESSES + 2) for _ in range(MAX_EVENTS_PER_PROCESS + 1)]
        result = summarize_editor_lifecycle('\n'.join(lines))
        self.assertEqual(len(result['processes']), MAX_PROCESSES)
        self.assertEqual(result['overflow_process_events'], 2 * (MAX_EVENTS_PER_PROCESS + 1))
        for group in result['processes']:
            self.assertEqual(len(group['events']), MAX_EVENTS_PER_PROCESS)
            self.assertTrue(all(len(json.dumps(line).encode()) <= MAX_EVENT_JSON_BYTES for line in group['events']))
        self.assertLessEqual(len(json.dumps({'watch_editor_lifecycle': result}, indent=2).encode()), MAX_LIFECYCLE_JSON_BYTES)

    def test_frame_capture_preserves_actual_data_and_is_finite(self):
        capture = ListFrameDiagnostics()
        value = frame()
        capture.record('WATCH_LIST_FRAME ' + json.dumps(value) + '\n')
        self.assertEqual(capture.report['records'], [value])
        for case in ('case', 'second', 'third'):
            for _ in range(MAX_FRAMES_PER_CASE + 1):
                capture.record('WATCH_LIST_FRAME ' + json.dumps(frame(case)))
        self.assertEqual(len(capture.report['records']), MAX_FRAME_RECORDS)
        self.assertEqual(capture.report['omitted_records'], 1 + 3 * (MAX_FRAMES_PER_CASE + 1) - MAX_FRAME_RECORDS)
        self.assertLessEqual(len(json.dumps(capture.report).encode()), MAX_FRAME_REPORT_BYTES)

    def test_frame_rejects_unexpected_data_and_nonfinite_values(self):
        capture = ListFrameDiagnostics()
        values = [frame() for _ in range(5)]
        values[0]['rows'][0]['label'] = 'private color'
        values[1]['viewport'][1] = float('nan')
        values[2]['rows'][0]['id'] = 'unrelated.private'
        values[3]['snapshotMilliseconds'] = -1
        values[4]['case'] = 'x' * 5000
        for value in values:
            capture.record('WATCH_LIST_FRAME ' + json.dumps(value))
        capture.record('WATCH_LIST_FRAME not JSON')
        self.assertEqual(capture.report['invalid_records'], 6)
        self.assertEqual(capture.report['records'], [])

    def test_maximum_sized_valid_frames_fit_declared_budget(self):
        capture = ListFrameDiagnostics()
        for i in range(MAX_FRAME_RECORDS):
            value = frame('case' + str(i // MAX_FRAMES_PER_CASE))
            value['case'] += 'x' * 150
            value['phase'] = 'x' * 160
            value['rows'] = [{'id': 'watch.color.' + str(row), 'frame': [1.23456789, 2.23456789, 3.23456789, 4.23456789]} for row in range(24)]
            capture.record('WATCH_LIST_FRAME ' + json.dumps(value))
        self.assertGreater(len(capture.report['records']), 0)
        self.assertEqual(len(capture.report['records']) + capture.report['omitted_records'], MAX_FRAME_RECORDS)
        self.assertEqual(capture.report['invalid_records'], 0)
        self.assertLessEqual(len(json.dumps({'watch_list_frames': capture.report}, indent=2).encode()), MAX_FRAME_REPORT_BYTES)

    def test_lookback_tracks_exact_source_job_duration_with_margin(self):
        self.assertEqual(log_lookback(25), '27m')
        self.assertEqual(log_lookback(45), '47m')
        for invalid in (0, 61, True, '45'):
            with self.assertRaises(ValueError): log_lookback(invalid)
        driver = (ROOT / 'scripts/test_extra_platforms.py').read_text()
        self.assertIn("lookback=log_lookback(EXPECTED_MINUTES['watch'])", driver)
        self.assertIn("'--last',lookback", driver)
        self.assertIn('subsystem == "com.mango.touchColor.WatchDiagnostics"', driver)

    def test_original_crown_and_fresh_touch_preserve_palette_actions_and_assertions(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        crown = source.split('func testEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()', 1)[1].split('    @MainActor func testTouch', 1)[0]
        touch = source.split('func testTouchEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()', 1)[1].rsplit('\n}', 1)[0]
        crown_suffix = crown[crown.index('        func back()'):].replace('try reach(', 'reach(').strip()
        touch_suffix = touch[touch.index('        func back()'):].replace('Native Watch touch edit', 'Native Watch edit').replace('try reach(', 'reach(').strip()
        # Only the touch home-List reset/readback navigation changes. Palette
        # actions, exact values, duplicate deletion and relaunch assertions match.
        crown_suffix = crown_suffix.replace('        for _ in 0..<4 { app.swipeDown() }\n', '')
        crown_suffix = crown_suffix.replace('for _ in 0..<6 where !app.buttons["watch.color.1"].exists { app.swipeUp() }', 'try reachSavedColorByTouch("watch.color.1", tap: false)')
        self.assertEqual(crown_suffix, touch_suffix)
        self.assertIn('for attempt in 0..<12', crown)
        self.assertIn('rotateDigitalCrown(delta: above ? 0.1 : -0.1)', crown)
        self.assertIn('XCTAssertTrue(button.isHittable, app.debugDescription); button.tap()', crown)
        self.assertNotIn('rotateDigitalCrown', touch)
        self.assertNotIn('XCTExpectFailure', source)
        self.assertNotIn('XCTSkip', crown + touch)
        self.assertIn('continueAfterFailure = false', source)
        self.assertIn('"TouchColor.watch-ui.\\(UUID())"', source)

    def test_cold_control_does_not_open_editor_or_change_delta(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        cold = source.split('func testHomeListDigitalCrownFromColdLaunch()', 1)[1].split('    @MainActor func testEdit', 1)[0]
        self.assertIn('for attempt in 0..<12', cold)
        self.assertIn('rotateDigitalCrown(delta: -0.1)', cold)
        self.assertIn('XCTAssertTrue(target.isHittable, app.debugDescription)', cold)
        self.assertNotIn('app.buttons["watch.editor"].tap()', cold)
        self.assertNotIn('swipe', cold)
        self.assertIn('name.contains("Chinese") ? 240 : 120', source)

    def test_frames_use_one_snapshot_not_remote_property_scans(self):
        source = (ROOT / 'TouchColorWatchUITests/WatchWorkflowTests.swift').read_text()
        helper = source.split('func logHomeListFrame(', 1)[1].split('    @MainActor func testHome', 1)[0]
        self.assertEqual(helper.count('app.snapshot()'), 1)
        self.assertNotIn('app.buttons', helper)
        self.assertNotIn('app.frame', helper)
        self.assertIn('visited <= 512', helper)
        self.assertIn('XCTAssertLessThanOrEqual(rows.count, 24)', helper)
        self.assertIn('XCTAssertLessThanOrEqual(data.count, 4096)', helper)

    def test_lifecycle_counters_and_focus_measurements_are_separate(self):
        source = (ROOT / 'TouchColorWatch/WatchViews.swift').read_text()
        diagnostic = source.split('@MainActor private enum WatchEditorDiagnostics', 1)[1].split('#endif', 1)[0]
        self.assertNotIn('focused: Bool = false', diagnostic)
        self.assertIn('focused: Bool? = nil', diagnostic)
        self.assertIn('"lifecycle": 32', diagnostic)
        self.assertIn('"focusHidden": 16', diagnostic)
        self.assertIn('"writeHidden": 16', diagnostic)
        for method in ('appeared', 'disappeared', 'writeback'):
            line = next(line for line in diagnostic.splitlines() if 'static func ' + method in line)
            self.assertNotIn('focused:', line)
        # Crown eligibility is stable; hidden-editor lifecycle cleanup remains.
        self.assertIn('.focusable(true).focused($crownFocused)', source)
        self.assertIn('editorIsVisible = false; crownFocused = false', source)


if __name__ == '__main__': unittest.main()
