"""Synthetic filesystem-only About census tests; no native UI success claim."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

import secondary_about_evidence as proof
from native_text_rows import row

SHA = 'a' * 40
DEVICE = '11111111-1111-4111-8111-111111111111'
ROOT = Path(__file__).resolve().parents[1]
PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic portable fixture' + b'\x00\x00\x00\x00IEND\xaeB`\x82'


def bound(platform='tv', phase='normal', case='chinese', profile='smallest'):
    if platform in ('vision', 'watch'):
        return row(platform, phase, case if platform == 'vision' else '', profile if platform == 'watch' else '', SHA)
    return {'schema': 1, 'platform': platform, 'phase': 'normal', 'case': '', 'profile': '',
            'source_sha': SHA, 'evidence_bytes': 3_000_000 if platform == 'mac' else 2_000_000}


class Fixture:
    def __init__(self, root, platform='tv', phase='normal', case='chinese', fallback=False):
        self.root = root; self.binding = bound(platform, phase, case); self.groups = {}; self.images = []; self.audits = []
        self.run = {'sha': SHA, 'platform': platform, 'captures': []}
        if fallback: self.run['public_trait_layout'] = {'result': 'diagnostic'}
        self.specs = proof.requirements(self.binding, fallback)
        for spec in self.specs:
            item = self.add(spec['folder'], spec['method'], spec['title'], PNG, '.png', 11)
            self.images.append(item)
            if platform == 'vision':
                self.run['captures'].append({'name': spec['title'], 'success': True, 'file': Path(item).name,
                    **({'system_text_size': 'accessibility-extra-extra-extra-large'} if phase == 'system-largest' else {})})
            if spec['audit']:
                folder = spec['folder'] if platform != 'vision' else ('vision-ui-screenshots' if phase == 'normal' else 'vision-largest-text-screenshots')
                if platform == 'mac':
                    audit_id = str(uuid.uuid4()).upper()
                    title = 'Native Mac accessibility issue audit summary ' + audit_id
                    raw = ('Audit-ID: ' + audit_id + '\nState: secondary About ' + spec['context'] + '\nIssues: 0\nRecorded failures: 0\n').encode()
                else:
                    title = proof.audit_title(platform, spec['context'])
                    raw = proof.encoded({'schema': 1, 'state': 'secondary About ' + spec['context'], 'imageName': spec['title'],
                        'testName': '-[' + spec['method'].replace('/', ' ').removesuffix('()') + ']', 'outcome': 'passed'})
                self.audits.append(self.add(folder, spec['method'], title, raw, '.txt', 12))
            summary = {'result': 'Passed', 'failedTests': 0, 'testFailures': [], 'startTime': 10, 'finishTime': 20,
                'devicesAndConfigurations': [{'device': {'deviceId': DEVICE, 'platform': {'mac': 'macOS', 'tv': 'tvOS Simulator',
                    'watch': 'watchOS Simulator', 'vision': 'visionOS Simulator'}[platform], 'architecture': 'arm64', 'osVersion': '27.0'}}]}
            (root / spec['summary']).write_bytes(proof.encoded(summary))
        self.save()

    def add(self, folder, method, title, raw, suffix, timestamp):
        path = self.root / folder; path.mkdir(exist_ok=True)
        name = str(uuid.uuid4()).upper() + suffix; (path / name).write_bytes(raw)
        item = {'exportedFileName': name, 'suggestedHumanReadableName': title, 'timestamp': timestamp,
                'deviceId': DEVICE, 'configurationName': 'Default'}
        self.groups.setdefault(folder, []).append({'testIdentifier': method, 'attachments': [item]})
        return folder + '/' + name

    def save(self):
        for folder, groups in self.groups.items(): (self.root / folder / 'manifest.json').write_bytes(proof.encoded(groups))
        if self.binding['platform'] != 'mac': (self.root / (self.binding['platform'] + '-runtime.json')).write_bytes(proof.encoded(self.run))

    def prepare(self): return proof.prepare(self.root, self.binding)


class SecondaryAboutEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {}, clear=True); env.start(); self.addCleanup(env.stop)

    def test_closed_checkpoint_inventory_and_unchanged_caps(self):
        for p, count in [('mac', 6), ('tv', 8), ('watch', 6), ('vision', 2)]:
            self.assertEqual(len(proof.requirements(bound(p))), count)
        self.assertEqual(len(proof.requirements(bound('watch', 'system-largest'))), 4)
        self.assertEqual(len(proof.requirements(bound('watch', 'system-largest'), True)), 6)
        self.assertEqual(proof.requirements(bound('vision', case='paste-relaunch')), [])
        self.assertEqual(bound('mac')['evidence_bytes'], 3_000_000)
        self.assertEqual(bound('tv')['evidence_bytes'], 2_000_000)
        self.assertEqual(bound('watch', 'system-largest')['evidence_bytes'], 600_000)
        self.assertEqual(bound('vision', case='canvas-audit')['evidence_bytes'], 650_000)

    def test_every_selected_phase_preserves_census_and_defers_largest_to_real_gate(self):
        for p, phase, case, fallback in [('mac', 'normal', '', False), ('tv', 'normal', '', False),
                ('watch', 'normal', '', False), ('watch', 'system-largest', '', False),
                ('watch', 'system-largest', '', True), ('vision', 'normal', 'chinese', False),
                ('vision', 'normal', 'canvas-audit', False), ('vision', 'system-largest', 'canvas-audit', False)]:
            with self.subTest(platform=p, phase=phase, case=case, fallback=fallback), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root, p, phase, case, fallback); fixture.prepare()
                before = (root / proof.REPORT).read_bytes()
                # This fixture supplies pixels only. The established actual
                # setting/result validator is a separate dependency, not a
                # success inferred from fallback screenshots or this census.
                with patch('native_text_evidence.accepted', return_value=not fallback) as gate:
                    self.assertEqual(proof.complete(root), not fallback)
                    if phase == 'system-largest': gate.assert_called_once_with(root, fixture.binding, fixture.run)
                    else: gate.assert_not_called()
                self.assertEqual((root / proof.REPORT).read_bytes(), before)
                self.assertLess(len(before), proof.MAX_REPORT)

    def test_absent_capture_at_collection_cannot_pass(self):
        fixture = Fixture(self.root); victim = fixture.images[0]
        (self.root / victim).unlink(); fixture.prepare()
        self.assertFalse(proof.complete(self.root))

    def test_tv_silent_post_collection_trim_is_detected_without_preventing_packet_read(self):
        fixture = Fixture(self.root); fixture.prepare(); victim = fixture.images[0]
        (self.root / victim).unlink()
        path = self.root / 'tv-screenshots/manifest.json'; groups = proof.strict(path.read_bytes())
        for group in groups: group['attachments'] = [a for a in group['attachments'] if a['exportedFileName'] != Path(victim).name]
        path.write_bytes(proof.encoded(groups))
        self.assertFalse(proof.complete(self.root)); self.assertTrue((self.root / proof.REPORT).is_file())

    def test_missing_receipt_failed_audit_or_failed_suite_stays_incomplete(self):
        for failure in ('missing', 'recorded', 'suite'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root)
                if failure == 'missing': (root / fixture.audits[0]).unlink()
                elif failure == 'recorded':
                    path = root / fixture.audits[0]; value = proof.strict(path.read_bytes()); value['outcome'] = 'failed'; path.write_bytes(proof.encoded(value))
                else:
                    path = root / 'tv-summary.json'; value = proof.strict(path.read_bytes()); value['result'] = 'Failed'; value['failedTests'] = 1; path.write_bytes(proof.encoded(value))
                fixture.prepare(); self.assertFalse(proof.complete(root))

    def test_mac_existing_exact_state_summary_requires_zero_recorded_failures(self):
        fixture = Fixture(self.root, 'mac'); path = self.root / fixture.audits[0]
        path.write_bytes(path.read_bytes().replace(b'Recorded failures: 0', b'Recorded failures: 1'))
        fixture.prepare(); self.assertFalse(proof.complete(self.root))

    def test_duplicate_wrong_method_wrong_device_and_out_of_order_fail(self):
        for mutation in ('duplicate', 'method', 'device', 'time', 'title'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); groups = fixture.groups['tv-screenshots']
                if mutation == 'duplicate':
                    spec = fixture.specs[0]; fixture.add(spec['folder'], spec['method'], spec['title'], PNG, '.png', 11)
                elif mutation == 'method': groups[0]['testIdentifier'] = 'TVWorkflowTests/other()'
                elif mutation == 'device': groups[0]['attachments'][0]['deviceId'] = 'another-device'
                elif mutation == 'time': groups[1]['attachments'][0]['timestamp'] = 10.5
                else: groups[0]['attachments'][0]['suggestedHumanReadableName'] += ' wrong title'
                fixture.save(); fixture.prepare(); self.assertFalse(proof.complete(root))

    def test_vision_needs_matching_successful_held_capture(self):
        for mutation in ('missing', 'failed', 'wrong-phase'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root, 'vision')
                if mutation == 'missing': fixture.run['captures'].pop(0)
                elif mutation == 'failed': fixture.run['captures'][0]['success'] = False
                else: fixture.run['captures'][0]['system_text_size'] = 'largest'
                fixture.save(); fixture.prepare(); self.assertFalse(proof.complete(root))

    def test_mutated_bytes_outcome_or_manifest_never_validate(self):
        for mutation in ('image', 'receipt', 'summary', 'manifest'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); fixture.prepare()
                if mutation == 'image': path = root / fixture.images[0]
                elif mutation == 'receipt': path = root / fixture.audits[0]
                elif mutation == 'summary': path = root / 'tv-summary.json'
                else:
                    path = root / 'tv-screenshots/manifest.json'; groups = proof.strict(path.read_bytes()); groups[0]['attachments'][0]['deviceId'] = 'foreign'; path.write_bytes(proof.encoded(groups))
                if mutation != 'manifest': path.write_bytes(path.read_bytes() + b' ')
                with self.assertRaises(ValueError): proof.complete(root)

    def test_original_mac_five_keep_priority_and_new_six_have_only_one_small_hook(self):
        source = (ROOT / 'scripts/retain_mac_evidence.py').read_text()
        self.assertLess(source.index('for state in REQUESTED:'), source.index('secondary = selected_paths(root)'))
        self.assertLess(source.index('secondary = selected_paths(root)'), source.index('projection_error = None'))
        self.assertIn('MAX_IMAGES = 16', source); self.assertIn('MAX_PNG = 500_000', source)
        self.assertIn('LIMIT = 3_000_000', source)

    def test_mac_selector_preserves_original_five_before_six_new_images_and_exposes_omission(self):
        import retain_mac_evidence as keep
        from test_retain_mac_evidence import Fixture as MacFixture, SOURCE, png
        for secondary_size in (50_000, 400_000):
            with self.subTest(secondary_size=secondary_size), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); old = MacFixture(root, image_size=350_000)
                added = []
                for spec in proof.requirements(bound('mac')):
                    group = {'testIdentifier': spec['method'], 'attachments': []}
                    old.groups['screenshots'].append(group)
                    added.append(old.add(group, spec['title'], png(secondary_size), '.png', 200))
                    if spec['audit']:
                        identity = str(uuid.uuid4()).upper()
                        old.add(group, 'Native Mac accessibility issue audit summary ' + identity,
                            ('Audit-ID: ' + identity + '\nState: secondary About ' + spec['context'] +
                             '\nIssues: 0\nRecorded failures: 0\n').encode(), '.txt', 201)
                old.save(); proof.prepare(root, bound('mac')); before = (root / proof.REPORT).read_bytes()
                result = keep.retain(root, SOURCE)
                self.assertTrue(result['complete']); self.assertTrue(keep.validate_selection(root)['complete'])
                for name in old.images.values(): self.assertEqual((root / name).read_bytes(), old.raw[name])
                self.assertEqual((root / proof.REPORT).read_bytes(), before)
                self.assertLessEqual(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()), keep.LIMIT)
                if secondary_size == 50_000: self.assertTrue(all((root / name).is_file() for name in added))
                else:
                    self.assertTrue(any(not (root / name).is_file() for name in added))
                    self.assertFalse(proof.complete(root))

    def test_watch_selector_keeps_original_requirements_and_sidecar_bytes(self):
        import native_text_evidence as keep
        from test_native_text_evidence import Fixture as NativeFixture
        old = NativeFixture(self.root, phase='normal', profile='smallest')
        original_root = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        new = Fixture(self.root, 'watch')
        old_groups = old.manifests['watch-ui-screenshots/manifest.json']
        new.groups['watch-ui-screenshots'] += old_groups
        new.save()
        for name, raw in original_root.items(): (self.root / name).write_bytes(raw)
        new.prepare(); receipt = (self.root / proof.REPORT).read_bytes()
        result = keep.retain(self.root)
        self.assertTrue(result['complete']); self.assertTrue(proof.complete(self.root))
        self.assertEqual((self.root / proof.REPORT).read_bytes(), receipt)
        self.assertTrue(set(old.images + new.images + new.audits) <= set(result['requiredFiles']))

    def test_actual_watch_largest_gate_rejects_unsupported_wrong_size_or_fallback_pixels(self):
        from test_native_text_evidence import Fixture as NativeFixture
        for mutation in ('passed', 'unsupported', 'wrong-size', 'failed', 'fallback', 'readback', 'restore'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); old = NativeFixture(root, phase='system-largest', profile='smallest')
                original_root = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
                new = Fixture(root, 'watch', 'system-largest', fallback=mutation == 'fallback')
                new.groups['watch-largest-text-screenshots'] += old.manifests['watch-largest-text-screenshots/manifest.json']
                new.run = old.runtime
                setting = new.run['largest_system_text']
                if mutation == 'unsupported': setting.update(status='original_value_not_recognized', original_raw='unsupported', ui_executed=False)
                elif mutation == 'wrong-size': setting['observed_largest'] = 'large'
                elif mutation == 'failed': new.run['largest_text_outcome'] = {'result': 'failed'}
                elif mutation == 'fallback': new.run['public_trait_layout'] = {'system_propagation_verified': False, 'ui_exit': 0}
                elif mutation == 'readback': setting['operations'][4]['output'] = 'large\n'
                elif mutation == 'restore': setting['observed_restored'] = 'small'
                new.save()
                for name, raw in original_root.items():
                    if name != 'watch-runtime.json': (root / name).write_bytes(raw)
                new.prepare(); before = {path: (root / path).read_bytes() for path in new.images + new.audits}
                self.assertEqual(proof.complete(root), mutation == 'passed')
                for path, raw in before.items(): self.assertEqual((root / path).read_bytes(), raw)

    def test_vision_largest_pixels_without_actual_qualification_never_complete(self):
        fixture = Fixture(self.root, 'vision', 'system-largest', 'canvas-audit')
        fixture.run.update(result='passed', tests='passed', native_text_row=fixture.binding)
        fixture.save(); fixture.prepare()
        self.assertFalse(proof.complete(self.root))
        with patch('native_text_evidence.accepted', return_value=False) as gate:
            self.assertFalse(proof.complete(self.root)); gate.assert_called_once()

    def test_receipt_accepts_only_exact_unprefixed_or_known_target_module_name(self):
        for platform in ('tv', 'watch', 'vision'):
            for prefix in ('', proof.TEST_TARGETS[platform] + '.', 'Foreign.', proof.TEST_TARGETS[platform] + '.Extra.'):
                with self.subTest(platform=platform, prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); fixture = Fixture(root, platform)
                    for name in fixture.audits:
                        path = root / name; value = proof.strict(path.read_bytes())
                        value['testName'] = value['testName'].replace('-[', '-[' + prefix, 1)
                        path.write_bytes(proof.encoded(value))
                    fixture.prepare()
                    self.assertEqual(proof.complete(root), prefix in ('', proof.TEST_TARGETS[platform] + '.'))

    def test_receipt_wrong_row_or_requirement_inventory_is_rejected(self):
        fixture = Fixture(self.root); fixture.prepare(); path = self.root / proof.REPORT
        record = proof.strict(path.read_bytes()); record['entries'].pop(); path.write_bytes(proof.encoded(record))
        with self.assertRaisesRegex(ValueError, 'requirement inventory'): proof.complete(self.root)

    def test_symlink_and_oversized_receipt_fail_closed(self):
        for mutation in ('symlink', 'oversized'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); path = root / fixture.audits[0]
                if mutation == 'symlink': path.unlink(); path.symlink_to(root / fixture.audits[1])
                else: path.write_bytes(b'x' * (proof.MAX_AUDIT + 1))
                with self.assertRaises(ValueError): fixture.prepare()

    def test_prepare_is_single_use_and_non_target_vision_is_unchanged(self):
        fixture = Fixture(self.root); fixture.prepare()
        with self.assertRaises(ValueError): fixture.prepare()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root, 'vision', case='paste-relaunch')
            self.assertIsNone(fixture.prepare()); self.assertIsNone(proof.complete(root))

    def test_required_overlay_fails_missing_census_and_rejects_wrong_source(self):
        env = {'TOUCHCOLOR_SECONDARY_EVIDENCE_REQUIRED': '1', 'TOUCHCOLOR_JOB_PLATFORM': 'tv',
               'GITHUB_SHA': SHA, 'GITHUB_WORKFLOW_SHA': SHA, 'TOUCHCOLOR_EVIDENCE_LIMIT': '2000000'}
        with patch.dict(os.environ, env): self.assertFalse(proof.complete(self.root))
        fixture = Fixture(self.root); fixture.prepare()
        with patch.dict(os.environ, {**env, 'GITHUB_SHA': 'b' * 40, 'GITHUB_WORKFLOW_SHA': 'b' * 40}):
            with self.assertRaisesRegex(ValueError, 'another row/source'): proof.complete(self.root)

    def test_final_guard_emits_false_but_preserves_safe_partial_upload(self):
        fixture = Fixture(self.root); fixture.prepare(); (self.root / fixture.images[0]).unlink()
        path = self.root / 'tv-screenshots/manifest.json'; groups = proof.strict(path.read_bytes())
        for group in groups: group['attachments'] = [a for a in group['attachments'] if (path.parent / a['exportedFileName']).exists()]
        path.write_bytes(proof.encoded(groups)); output = self.root.parent / (self.root.name + '-output')
        self.addCleanup(lambda: output.unlink(missing_ok=True))
        for optimized in (False, True):
            output.unlink(missing_ok=True)
            result = subprocess.run([sys.executable] + (['-O'] if optimized else []) + [str(ROOT / 'scripts/validate_evidence.py'), str(self.root), '2000000'],
                env={**os.environ, 'GITHUB_OUTPUT': str(output), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('secondary_evidence_complete=false\n', output.read_text())
            self.assertTrue((self.root / proof.REPORT).is_file())


if __name__ == '__main__': unittest.main()
