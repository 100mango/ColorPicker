import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('design_gate', Path(__file__).with_name('original_design_gate.py'))
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

class OriginalDesignGateTests(unittest.TestCase):
    def summary(self):
        counts = {'passedTests': 4, 'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}
        return dict(totalTestCount=4, result='Passed', startTime=110, finishTime=120, **counts,
                    devicesAndConfigurations=[dict(device={'deviceId': 'owned-device', 'platform': 'iOS Simulator', 'osVersion': '27.0'}, **counts)])
    def qualify(self, summary, **overrides):
        fields = dict(expected_count=4, device='owned-device', began=100, finished=130, exit_code=0)
        fields.update(overrides)
        gate.qualify_summary(summary, **fields)
    def test_complete_owned_summary_passes(self):
        self.qualify(self.summary())
    def test_failure_skip_expected_failure_cannot_be_passed(self):
        for field in ['failedTests', 'skippedTests', 'expectedFailures']:
            value = self.summary(); value[field] = 1
            with self.assertRaises(RuntimeError): self.qualify(value)
    def test_partial_foreign_or_stale_summary_is_rejected(self):
        for mutation in [lambda v: v.update(totalTestCount=3),
                         lambda v: v.update(startTime=99),
                         lambda v: v.update(finishTime=float('nan')),
                         lambda v: v['devicesAndConfigurations'][0]['device'].update(deviceId='another-device'),
                         lambda v: v['devicesAndConfigurations'][0].update(passedTests=3)]:
            value = self.summary(); mutation(value)
            with self.assertRaises(RuntimeError): self.qualify(value)
    def test_nonzero_command_cannot_have_successful_summary(self):
        with self.assertRaises(RuntimeError): self.qualify(self.summary(), exit_code=65)
    def test_objc_and_swift_zero_argument_tests_are_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Tests'
            path.write_text('- (void)testObjectiveC { }\nfunc testSwift() async throws { }\n- (void)helper { }')
            self.assertEqual(gate.testcase_names(path), {'testObjectiveC', 'testSwift'})
    def test_raw_case_inventory_rejects_missing_duplicate_and_false_green(self):
        passed = "Test Case '-[Suite testA]' passed (0.1 seconds).\nTest Case '-[Suite testB]' passed (0.1 seconds).\n"
        gate.qualify_cases(passed, {'testA', 'testB'})
        for log in [passed.splitlines()[0], passed + passed, passed.replace('testB', 'testC'), passed.replace('passed', 'failed', 1)]:
            with self.assertRaises(RuntimeError): gate.qualify_cases(log, {'testA', 'testB'})
    def test_synthetic_fixture_is_exact_original_six_color_png(self):
        import struct, zlib
        raw = gate.fixture_png(); self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II', raw[16:24]), (300, 200))
        offset = 8; compressed = b''
        while offset < len(raw):
            size = struct.unpack('>I', raw[offset:offset+4])[0]
            kind = raw[offset+4:offset+8]
            if kind == b'IDAT': compressed += raw[offset+8:offset+8+size]
            offset += size + 12
        pixels = zlib.decompress(compressed)
        def color(x, y): return pixels[y * 901 + 1 + x * 3:y * 901 + 1 + x * 3 + 3]
        self.assertEqual(color(45, 50), bytes([255, 0, 0]))
        self.assertEqual(color(150, 100), bytes([255, 0, 255]))
    def test_admission_retains_small_package_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'evidence'; source.mkdir()
            (source / 'sample.png').write_bytes(b'png')
            (source / 'acceptance.json').write_text('{}')
            self.assertTrue(gate.admit_evidence(source, root / 'published'))
            receipt = json.loads((root / 'published/artifact-admission.json').read_text())
            self.assertTrue(receipt['complete']); self.assertEqual(receipt['omitted'], [])
    def test_admission_overflow_omits_images_and_stays_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'evidence'; source.mkdir()
            with (source / 'oversized.png').open('wb') as stream: stream.truncate(25 * 1024 * 1024)
            (source / 'acceptance.json').write_text('{"functional_passed":false}')
            self.assertFalse(gate.admit_evidence(source, root / 'published'))
            receipt = json.loads((root / 'published/artifact-admission.json').read_text())
            self.assertFalse(receipt['complete']); self.assertEqual(receipt['omitted'][0]['path'], 'oversized.png')
            self.assertFalse((root / 'published/oversized.png').exists())
            self.assertLess(sum(p.stat().st_size for p in (root / 'published').rglob('*') if p.is_file()), 24 * 1024 * 1024)
    def test_owned_temp_fixture_canonicalizes_system_parent_alias(self):
        # macOS may expose tempfile roots through /var -> /private/var. Resolve
        # only the test-owned fixture root; production link guards stay strict.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            owned = root / 'owned'; owned.mkdir()
            alias = root / 'system-temp-alias'; alias.symlink_to(owned, target_is_directory=True)
            source = alias / 'evidence'; source.mkdir()
            (source / 'acceptance.json').write_text('{}')
            with self.assertRaises(RuntimeError): gate.admit_evidence(source, owned / 'rejected')
            self.assertTrue(gate.admit_evidence(source.resolve(), owned / 'published'))

    def test_admission_rejects_linked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'evidence'; source.mkdir()
            (root / 'other.log').write_text('foreign')
            (source / 'linked.log').symlink_to(root / 'other.log')
            with self.assertRaises(RuntimeError): gate.admit_evidence(source, root / 'published')
    def test_bootstatus_budget_is_single_bounded_preparation(self):
        self.assertEqual(gate.BOOTSTATUS_TIMEOUT_SECONDS, 300)
        source = Path(gate.__file__).read_text()
        self.assertEqual(source.count("self.await_owned_boot(label, device, owned_name)"), 1)
        self.assertIn("if self.uncertain_simulator:\n            return", source)

    def test_owned_boot_accepts_known_cell_output_and_records_identity(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); raw = root / 'ready.log'
            raw.write_text('Monitoring boot status for Owned (U).\nDevice already booted, nothing to do.\n\n')
            with patch.object(gate, 'WORK', root / 'work'), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40)
                worker.commands = [{'name': 'se3-ready', 'exit_code': 0}]
                with patch.object(worker, 'command', return_value=(0, raw)) as command:
                    worker.await_owned_boot('se3', 'U', 'Owned')
                    command.assert_called_once_with('se3-ready', ['xcrun', 'simctl', 'bootstatus', 'U', '-b'], 300, simulator=True)
                proof = json.loads((root / 'evidence/se3-ready.json').read_text())
                self.assertEqual(proof['device'], 'U')
                self.assertEqual(proof['bootstatus']['completion_kind'], 'already_booted_no_work')
                self.assertFalse(worker.uncertain_simulator)

    def test_owned_boot_rejects_empty_partial_or_foreign_and_blocks_cleanup(self):
        from unittest.mock import patch
        variants = ['', 'Monitoring boot status for Other (V).\nDevice already booted, nothing to do.\n\n',
                    'Monitoring boot status for Owned (U).\n[2026-10-09 01:53:00 +0000] Status=1, isTerminal=NO, Elapsed=00:12.\n\tPreparing\n\n']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); raw = root / 'ready.log'
            for text in variants:
                raw.write_text(text)
                with patch.object(gate, 'WORK', root / 'work'), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                    worker = gate.Gate('a' * 40); worker.owned = ['U']
                    with patch.object(worker, 'command', return_value=(0, raw)) as command:
                        with self.assertRaises(ValueError): worker.await_owned_boot('se3', 'U', 'Owned')
                        worker.cleanup()
                        self.assertEqual(command.call_count, 1, 'Unknown readiness must block every later simulator action')
                    self.assertTrue(worker.uncertain_simulator)

    def test_command_emits_bounded_begin_and_end_timing(self):
        import contextlib, io, sys, types
        from unittest.mock import patch
        class Process:
            pid = 123456
            def __init__(self, argv, **kwargs): kwargs['stdout'].write(b'fixture output')
            def wait(self, timeout): return 0
        bounded = types.SimpleNamespace(group_exists=lambda pid: False, stop_group=lambda process, grace: True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); output = io.StringIO()
            with patch.object(gate, 'WORK', root / 'work'), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.subprocess, 'Popen', Process), patch.dict(sys.modules, {'bounded_process': bounded}), contextlib.redirect_stdout(output):
                worker = gate.Gate('a' * 40)
                code, _ = worker.command('fixture-stage', ['fixture-only'], 300)
            self.assertEqual(code, 0)
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith('ORIGINAL_DESIGN_COMMAND_BEGIN '))
            self.assertTrue(lines[1].startswith('ORIGINAL_DESIGN_COMMAND_END '))
            self.assertEqual(worker.commands[0]['timeout_seconds'], 300)
            self.assertGreaterEqual(worker.commands[0]['elapsed_seconds'], 0)

    def test_import_lifecycle_adapter_preserves_every_other_original_byte(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'ColorPickerTests/TCPhotoImportLifecycleTests.m').read_text()
        start = text.index('// Locate the same real cancellation action independently')
        end = text.index('@interface TCPhotoImportLifecycleTests : XCTestCase', start)
        text = text[:start] + text[end:]
        new = '''    UIButton *cancel=TCVisibleImportCancel(palette.view);
    XCTAssertNotNil(cancel,@"The real loading Cancel action must remain visible and reachable in the restored design");
    XCTAssertTrue(cancel.enabled);'''
        old = '    XCTAssertTrue([[palette.navigationItem.rightBarButtonItems valueForKey:@"accessibilityIdentifier"] containsObject:@"photo.import.cancel"]);'
        self.assertEqual(text.count(new), 1)
        text = text.replace(new, old)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), '9ab82653389d0baa4f713ed758ced976d4910ee8687fca5af078b6bf7e0bb994')
    def test_photo_fixture_is_selected_by_unique_bounded_content_not_position(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        start = source.index('- (void)selectOnlySeededPhoto {')
        end = source.index('- (void)sampleAndSaveRed {', start)
        selection = source[start:end]
        for required in ['TCDesignRecognitionControl(NO)', 'TCDesignRecognitionControl(YES)', 'candidates.count,16u',
                         'TCDesignFixtureThumbnail(candidate.screenshot.image)', 'matches.count,1u',
                         'TCDesignFixtureThumbnail(fixture.screenshot.image)', '[fixture tap]']:
            self.assertIn(required, selection)
        self.assertNotIn('[photos.firstMatch tap]', selection)
        self.assertNotIn('photos.count,1u', selection)
        self.assertIn('const CGPoint probes[5]', source)
        self.assertIn('colors[row*3+column]', source)
        self.assertIn('>8) return NO', source)
        self.assertIn('contains:@"#ff00ff"', source)
        self.assertIn('contains:@"#ff0000"', source)

    def test_privacy_suite_uses_exact_current_native_contract(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        self.assertEqual(len(gate.testcase_names(root / 'TouchColorUITests/TouchColorOriginalDesignUITests.m')), 4)
        for required in ['privacy.body.zh-Hans', 'privacy.body.en', 'original.about.close', 'original.back', 'photo.import.cancel', '#ff00ff', '#ff0000']:
            self.assertIn(required, source)
        for stale in ['privacy.retry', 'privacy.error', 'self.app.webViews', '@"--ui-test-image"', 'returnToPaletteFrom:']:
            self.assertNotIn(stale, source)

if __name__ == '__main__':
    unittest.main(verbosity=2)
