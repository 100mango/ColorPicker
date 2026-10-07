"""Source and synthetic evidence checks only; no Swift/AppKit execution claim."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

from test_mac_reset_source_helpers import restore_english_setup
import mac_launch_comparison as comparison
import mac_passive_lifecycle as passive
from test_mac_passive_lifecycle import bound, envelope, event

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / 'scripts/fixtures/mac-ea9-scene-baseline.json').read_bytes())
NAMES = ('sceneBody', 'windowContentEntered', 'windowContentReturned', 'colorWindowBody')
ENUM = '''    enum SceneCheckpoint: String {
        case sceneBody, windowContentEntered, windowContentReturned, colorWindowBody
    }
'''
METHOD = '''    // First evaluation only, through the existing token-gated instance and bounds.
    // A late or omitted checkpoint stays omitted; it is never retried.
    func checkpoint(_ value: SceneCheckpoint) {
        guard !stopped, checkpoints.insert(value).inserted else { return }
        record(value.rawValue, sampleApp: false)
    }
'''


def projection(text, debug):
    """Evaluate only the exact DEBUG directives present in these two sources."""
    active = [True]
    conditions = []
    output = []
    for line in text.splitlines(keepends=True):
        directive = line.strip()
        if directive.startswith('#if '):
            if directive != '#if DEBUG':
                raise ValueError('unreviewed conditional compilation directive')
            conditions.append(debug)
            active.append(active[-1] and debug)
        elif directive == '#else':
            conditions[-1] = not conditions[-1]
            active[-1] = active[-2] and conditions[-1]
        elif directive == '#endif':
            active.pop()
            conditions.pop()
        elif directive.startswith('#elseif '):
            raise ValueError('unreviewed conditional compilation directive')
        elif active[-1]:
            output.append(line)
    if len(active) != 1:
        raise ValueError('unbalanced compilation directives')
    return ''.join(output)


def without_checkpoints(text):
    """Undo the reviewed metadata-only statements and equivalent local binding."""
    for name in NAMES:
        text = re.sub(r'^\s*let _ = MacPassiveLifecycle\.shared\?\.checkpoint\(\.' + name + r'\)\n', '', text, flags=re.M)
    text = text.replace('            let content = ColorWindow(library: library)\n',
                        '            ColorWindow(library: library)\n')
    text = text.replace('            content\n', '')
    text = text.replace(ENUM, '')
    text = text.replace('    private var checkpoints: Set<SceneCheckpoint> = []\n', '')
    text = text.replace(METHOD, '')
    text = text.replace(', sampleApp: Bool = true) {', ') {')
    text = text.replace('if elapsed <= 10 && sampleApp {', 'if elapsed <= 10 {')
    return text


def checkpoint(name, sequence=2, elapsed=.2):
    value = event(event=name, sequence=sequence, epoch=100 + elapsed, elapsed=elapsed)
    value.pop('product')
    value.pop('app')
    return value


class SourceContracts(unittest.TestCase):
    def test_exact_ea9_baseline_identity(self):
        self.assertEqual(BASELINE['parent'], 'ea9da854f4658b36a28a3b80f6f48e06185cfedb')
        self.assertEqual(BASELINE['parent_tree'], '141bcec9a89e74ebf519b513a7042a2503fe84d4')

    def test_release_projection_is_byte_identical(self):
        for path, hashes in BASELINE['projections'].items():
            with self.subTest(path=path):
                text = projection((ROOT / path).read_text(), False)
                self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), hashes['release'])
                self.assertNotIn('MacPassiveLifecycle', text)

    def test_debug_no_token_equivalence_preserves_original_view_expression(self):
        for path, hashes in BASELINE['projections'].items():
            with self.subTest(path=path):
                text = projection((ROOT / path).read_text(), True)
                normalized = without_checkpoints(text)
                self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), hashes['debug'])
        # There is no wrapper, altered StateObject initializer, scene ID, or closure return.
        text = projection((ROOT / 'TouchColorMac/TouchColorMacApp.swift').read_text(), True)
        content = text.split('WindowGroup("TouchColor") {', 1)[1].split('.defaultSize', 1)[0]
        self.assertEqual(content.count('ColorWindow(library: library)'), 1)
        self.assertEqual(content.count('            content\n'), 1)
        self.assertNotIn('return ', content)
        positions = [content.index(x) for x in [
            'checkpoint(.windowContentEntered)', 'let content = ColorWindow',
            '.background(NativeWindowMinimumSize())', '.overlay(alignment:',
            'checkpoint(.windowContentReturned)', '            content\n']]
        self.assertEqual(positions, sorted(positions))

    def test_all_new_calls_are_optional_on_existing_token_gated_instance(self):
        combined = ''.join(projection((ROOT / path).read_text(), True) for path in BASELINE['projections'])
        calls = re.findall(r'let _ = MacPassiveLifecycle\.shared\?\.checkpoint\(\.(\w+)\)', combined)
        self.assertCountEqual(calls, NAMES)
        self.assertEqual(combined.count('.checkpoint('), 4)
        app = (ROOT / 'TouchColorMac/TouchColorMacApp.swift').read_text()
        guard = app.split('static func startIfEnabled()', 1)[1].split('private init(', 1)[0]
        for token in ['UUID(uuidString: token)?.uuidString == token', 'suite.hasPrefix("TouchColor.mac-ui.")',
                      'arguments.contains("--ui-test-reset")', 'shared = value; value.start()']:
            self.assertIn(token, guard)
        self.assertIn(ENUM, app)
        self.assertIn(METHOD, app)
        self.assertEqual(app.count('sampleApp: false'), 1)
        self.assertEqual(app.count('census()'), 2)  # Declaration and original record call only.

    def test_existing_observation_limits_and_queries_not_increased(self):
        app = (ROOT / 'TouchColorMac/TouchColorMacApp.swift').read_text()
        for token in ['[1.0, 5.0, 10.0]', 'if elapsed > 10 && !final', 'sequence < 23',
                      'data.count + 22 <= 4096', 'final ? 12288 : 8192', 'windows.prefix(4)',
                      'identities.count < 16', 'if elapsed <= 10 && sampleApp { row["app"] = census() }']:
            self.assertIn(token, app)
        self.assertEqual(passive.RAW_LIMIT, 512 * 1024)
        self.assertEqual(passive.OUTPUT_LIMIT, 128 * 1024)
        self.assertEqual(passive.SECONDS, 30)
        self.assertEqual(comparison.LIMIT, 3_000_000)
        self.assertEqual(comparison.EVIDENCE_SECONDS, 180)
        self.assertIn('TouchColorMac/ColorWindow.swift', comparison.SOURCES)

    def test_workflow_controller_test_build_and_model_bytes_frozen(self):
        for path, digest in BASELINE['protected'].items():
            with self.subTest(path=path):
                raw = (ROOT / path).read_bytes()
                if path == 'scripts/job_budget.py':
                    # The single-case successor adds exactly one closed budget identity.
                    raw = raw.replace(b", 'mac-scene-checkpoints': 25", b'').replace(b", 'mac-scene-reset-only': 25", b'')
                if path == 'TouchColorMacUITests/TouchColorMacUITests.swift':
                    raw = restore_english_setup(raw.decode()).encode()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_original_single_english_command_is_unchanged(self):
        argv = comparison.test_command()
        self.assertEqual([x for x in argv if x.startswith('-only-testing:')],
                         ['-only-testing:TouchColorMacUITests/TouchColorMacUITests/' + passive.CASES[0]])
        self.assertEqual(comparison.ARGS, ['--ui-test-reset', '-AppleLanguages', '(en)', '-AppleLocale', 'en_US'])
        self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance') + 1], '120')
        self.assertEqual(argv[argv.index('-parallel-testing-enabled') + 1], 'NO')
        self.assertEqual(argv[-1], 'test-without-building')
        self.assertNotIn('retry', ' '.join(argv))


class CheckpointEvidence(unittest.TestCase):
    def project(self, values, receipts=None):
        return passive.project(passive.encode([envelope(x) for x in values]), receipts or [bound()])

    def test_four_names_are_closed_metadata_only_events(self):
        values = [event()] + [checkpoint(name, index + 2, .2 + index * .1) for index, name in enumerate(NAMES)]
        row = self.project(values)[0]
        self.assertEqual(set(passive.SCENE_CHECKPOINTS), set(NAMES))
        self.assertEqual([x['event'] for x in row['events'][1:]], list(NAMES))
        self.assertTrue(all('app' not in x for x in row['events'][1:]))
        self.assertEqual(comparison.observation(row), 'unknown')
        self.assertTrue(row['absence_is_not_proof'])

    def test_every_checkpoint_rejects_a_second_hit(self):
        for name in NAMES:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'duplicate scene checkpoint'):
                self.project([event(), checkpoint(name), checkpoint(name, 3, .3)])

    def test_one_shot_scope_is_per_owned_pid_and_token(self):
        first = bound()
        second = {**first, 'pid': 346, 'token': 'BBBBBBBB-BBBB-CCCC-DDDD-EEEEEEEEEEEE'}
        a = checkpoint('sceneBody')
        b = {**a, 'pid': second['pid'], 'token': second['token']}
        second_envelope = envelope(b)
        second_envelope['processID'] = second['pid']
        rows = passive.project(passive.encode([envelope(a), second_envelope]), [first, second])
        self.assertEqual([len(row['events']) for row in rows], [1, 1])

    def test_metadata_checkpoint_cannot_add_app_or_other_fields(self):
        for field, value in [('app', {'present': False}), ('product', {}), ('launchIsDefault', 'reportedTrue'),
                             ('checkpoint', True), ('workspaceReady', True)]:
            wrong = checkpoint(NAMES[0]); wrong[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.project([event(), wrong])

    def test_identity_path_pid_token_and_time_fences_apply_to_checkpoints(self):
        for key, value in [('pid', 346), ('token', 'BBBBBBBB-BBBB-CCCC-DDDD-EEEEEEEEEEEE'),
                           ('launch', 'bad'), ('epoch', 121.), ('elapsed', 10.1), ('sequence', 25),
                           ('late', True), ('v', True), ('event', 'sceneReady')]:
            wrong = checkpoint(NAMES[0]); wrong[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.project([event(), wrong])
        raw = envelope(checkpoint(NAMES[0])); raw['processImagePath'] = '/Other.app/Contents/MacOS/TouchColor'
        with self.assertRaises(ValueError):
            passive.project(passive.encode([raw]), [bound()])

    def test_old_events_still_require_original_census(self):
        for name in passive.EVENTS - passive.SCENE_CHECKPOINTS - {'appInit'}:
            wrong = checkpoint(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.project([event(), wrong])

    def test_original_late_final_omission_is_unchanged(self):
        final = checkpoint('final', 3, 10.1)
        final.update(late=True, omittedRecords=1)
        row = self.project([event(), checkpoint('sceneBody'), final])[0]
        self.assertTrue(row['final_observed'])
        self.assertNotIn('app', row['events'][-1])
        self.assertEqual(row['events'][-1]['omittedRecords'], 1)
        self.assertEqual(comparison.observation(row), 'unknown')

    def test_checkpoint_order_is_not_invented_when_records_are_missing(self):
        # A partial log may begin at any first-hit checkpoint; preserve the gap.
        row = self.project([checkpoint('colorWindowBody', 6, .6)])[0]
        self.assertEqual(row['sequence_gaps'], [1, 2, 3, 4, 5])
        self.assertFalse(row['app_header_observed'])
        self.assertEqual(comparison.observation(row), 'unknown')
        self.assertNotIn('sceneBody', [x['event'] for x in row['events']])

    def test_checkpoint_absence_in_historical_rows_stays_unknown(self):
        row = self.project([event()])[0]
        self.assertEqual(len(row['events']), 1)
        self.assertEqual(comparison.observation(row), 'unknown')
        self.assertFalse(any(x['event'] in passive.SCENE_CHECKPOINTS for x in row['events']))

    def test_native_failure_disappearing_is_not_release_acceptance(self):
        # Checkpoint presence carries no inferred functional status or acceptance.
        row = self.project([event(), checkpoint('colorWindowBody')])[0]
        self.assertNotIn('acceptance', row)
        self.assertNotIn('contactOutcome', row)
        self.assertEqual(comparison.observation(row), 'unknown')


class OneShotGateModel(unittest.TestCase):
    """Exercise the new gate synthetically; the exact Swift method is pinned above."""
    def simulate(self, calls, enabled=True, stopped=False, sequence=1, byte_count=200):
        seen, emitted = set(), []
        omitted = 0
        for name, elapsed, size in calls:
            if not enabled or stopped or name in seen:
                continue
            seen.add(name)
            if elapsed > 10 or sequence >= 23 or size + 22 > 4096 or byte_count + size + 22 > 8192:
                omitted += 1
                continue
            sequence += 1; byte_count += size + 22; emitted.append(name)
        return emitted, omitted, sequence, byte_count

    def test_each_checkpoint_is_one_shot_across_repeated_body_evaluations(self):
        calls = [(name, 1., 300) for _ in range(5) for name in NAMES]
        emitted, omitted, sequence, size = self.simulate(calls)
        self.assertEqual(emitted, list(NAMES)); self.assertEqual(omitted, 0)
        self.assertEqual(sequence, 5); self.assertLessEqual(size, 8192)

    def test_disabled_and_stopped_instances_emit_nothing(self):
        calls = [(name, 1., 300) for name in NAMES]
        for kwargs in [{'enabled': False}, {'stopped': True}]:
            self.assertEqual(self.simulate(calls, **kwargs), ([], 0, 1, 200))

    def test_late_and_exhausted_checkpoints_are_omitted_once_without_retry(self):
        for kwargs, time, size in [({}, 10.001, 300), ({'sequence': 23}, 1., 300),
                                   ({'byte_count': 8100}, 1., 300), ({}, 1., 4075)]:
            calls = [('sceneBody', time, size), ('sceneBody', 2., 10)]
            emitted, omitted, _, _ = self.simulate(calls, **kwargs)
            self.assertEqual(emitted, []); self.assertEqual(omitted, 1)

    def test_exact_deadline_does_not_expand_existing_ten_second_rule(self):
        self.assertEqual(self.simulate([('sceneBody', 10., 300)])[0], ['sceneBody'])
        self.assertEqual(self.simulate([('sceneBody', 10.0001, 300)])[0], [])


if __name__ == '__main__':
    unittest.main()
