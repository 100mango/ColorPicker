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
                worker = gate.Gate('a' * 40, 'se3')
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
                    worker = gate.Gate('a' * 40, 'se3'); worker.owned = ['U']
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
                worker = gate.Gate('a' * 40, 'se3')
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
    def test_split_photo_flows_keep_every_persistence_and_cancellation_assertion(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        def method(name, next_name):
            return source.split('- (void)' + name + ' {', 1)[1].split('- (void)' + next_name, 1)[0]
        save = method('testRealPhotoSaveRelaunchDelete', 'testDelayedImportCancellationPreservesSavedColor')
        cancel = method('testDelayedImportCancellationPreservesSavedColor', 'testNativePrivacyContentAndActionsFromEmptyLibrary')
        self.assertIn('[self launchReset:YES extra:nil]', save)
        self.assertIn('[self sampleAndSaveRed]', save)
        self.assertEqual(save.count('[self.app terminate]; [self launchReset:NO extra:nil]'), 2)
        self.assertIn('[self deleteOnlySavedColor:table]', save)
        self.assertIn('[self assertRedHistory:[self openLibrary] count:0]', save)
        for required in ['--ui-test-delay-photo-import', '[self sampleAndSaveRed]', '[self selectOnlySeededPhoto]',
                         'photo.import.cancel', 'late.inverted=YES', 'timeout:9', 'count:1', '[self deleteOnlySavedColor:table]']:
            self.assertIn(required, cancel)
        self.assertIn('len(hosted) == 29 and len(ui) == 6', Path(gate.__file__).read_text())
        self.assertIn("'-default-test-execution-time-allowance', '120'", Path(gate.__file__).read_text())
        self.assertEqual(gate.BOOTSTATUS_TIMEOUT_SECONDS, 300)
        home = source.split('- (void)assertHomeUsable {', 1)[1].split('- (void)tap:', 1)[0]
        for control in ['choose', 'take', 'live']:
            self.assertEqual(home.count(control + '.frame'), 1)
        self.assertIn('XCTAssertGreaterThanOrEqual(frame.size.height,44)', home)
        self.assertEqual(home.count('XCTAssertEqualWithAccuracy('), 2)
        self.assertEqual(home.count('XCTAssertLessThan('), 3)

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
        self.assertEqual(len(gate.testcase_names(root / 'TouchColorUITests/TouchColorOriginalDesignUITests.m') - {gate.BOOTSTRAP_TEST}), 6)
        for required in ['privacy.body.zh-Hans', 'privacy.body.en', 'original.about.close', 'original.back', 'photo.import.cancel', '#ff00ff', '#ff0000']:
            self.assertIn(required, source)
        for stale in ['privacy.retry', 'privacy.error', 'self.app.webViews', '@"--ui-test-image"', 'returnToPaletteFrom:']:
            self.assertNotIn(stale, source)

    def test_matrix_is_exact_two_independent_jobs_with_distinct_evidence(self):
        workflow = (gate.ROOT / '.github/workflows/original-design-gate.yml').read_text()
        for required in ['device: [se3, ipad-mini]', 'fail-fast: false', 'max-parallel: 2',
                         'timeout-minutes: 25', 'runs-on: xcode-27', 'ref: ${{ github.sha }}',
                         'EXPECTED_SHA: ${{ github.sha }}', 'DEVICE_LABEL: ${{ matrix.device }}',
                         '--expected-sha "$EXPECTED_SHA" --device "$DEVICE_LABEL"',
                         'name: touchcolor-original-design-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.device }}']:
            self.assertIn(required, workflow)
        self.assertEqual(workflow.count('runs-on:'), 1)
        self.assertNotIn('continue-on-error', workflow)
        self.assertNotIn('strategy.job-total', workflow)
        self.assertEqual(gate.CONTROLLER_TIMEOUT_SECONDS, 23 * 60)
        self.assertEqual(len(gate.DEVICE_NAMES), 2)
        self.assertEqual(gate.EVIDENCE_BUDGET_BYTES * len(gate.DEVICE_NAMES), 24 * 1024 * 1024)
        source = Path(gate.__file__).read_text()
        self.assertIn("parser.add_argument('--device', choices=tuple(DEVICE_NAMES), required=True)", source)
        self.assertIn("'scope': 'selected device only; both matrix jobs must pass'", source)
        self.assertIn("'required_devices': list(DEVICE_NAMES)", source)
        self.assertIn("'reviewed_inventory': {'hosted': 29, 'ui': 6}", source)

    def test_explicit_device_rejects_missing_unknown_or_all_selection(self):
        for label in [None, '', 'all', 'iphone', 'se3,ipad-mini']:
            with self.assertRaises(RuntimeError): gate.Gate('a' * 40, label)

    def test_each_job_runs_only_its_owned_selected_device_and_full_inventory(self):
        from unittest.mock import patch
        types = [dict(name=name, identifier='type.' + label) for label, name in gate.DEVICE_NAMES.items()]
        runtime = {'identifier': 'owned-runtime'}
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for label, name in gate.DEVICE_NAMES.items():
                with patch.object(gate, 'WORK', root / label), patch.object(gate, 'EVIDENCE', root / label / 'evidence'):
                    worker = gate.Gate('a' * 40, label)
                    with patch.object(worker, 'text', return_value=owned) as create, patch.object(worker, 'command') as command, patch.object(worker, 'await_owned_boot') as ready, patch.object(worker, 'run_tests') as tests:
                        worker.run_device(types, runtime, root / 'app', root / 'fixture.png', {'hosted'}, {'ui'})
                    create.assert_called_once()
                    args = create.call_args.args
                    self.assertEqual(args[0], label + '-create')
                    self.assertEqual(args[1][-2:], ['type.' + label, 'owned-runtime'])
                    ready.assert_called_once_with(label, owned, worker.devices[0]['owned_name'])
                    self.assertEqual([call.args[0] for call in command.call_args_list], [label + suffix for suffix in ['-boot', '-seed', '-shutdown', '-delete']])
                    self.assertEqual([call.args[2] for call in tests.call_args_list], ['hosted', 'bootstrap', 'ui'] if label == 'ipad-mini' else ['hosted', 'ui'])
                    self.assertEqual([call.args[-1] for call in tests.call_args_list], [{'hosted'}, {gate.BOOTSTRAP_TEST}, {'ui'}] if label == 'ipad-mini' else [{'hosted'}, {'ui'}])
                    self.assertEqual(worker.devices[0]['name'], name)
                    self.assertEqual(worker.owned, [])

    def test_device_failure_is_not_swallowed_or_followed_by_other_device(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'text', return_value=owned) as create, patch.object(worker, 'command') as command, patch.object(worker, 'await_owned_boot'), patch.object(worker, 'run_tests', side_effect=RuntimeError('test failed')):
                    with self.assertRaisesRegex(RuntimeError, 'test failed'):
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type.se3'}], {'identifier': 'owned-runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, {'ui'})
                    create.assert_called_once()
                    self.assertEqual([call.args[0] for call in command.call_args_list], ['se3-boot'])
                self.assertEqual(worker.owned, [owned])

    def test_hosted_managed_install_preserves_exact_build_device_and_budget(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); log = root / 'hosted.log'
            log.write_text("Test Case '-[Suite testA]' passed (0.1 seconds).\n")
            summary = self.summary(); summary['totalTestCount'] = 1; summary['passedTests'] = 1
            summary['devicesAndConfigurations'][0]['passedTests'] = 1
            summary['devicesAndConfigurations'][0]['device']['deviceId'] = owned
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'command', return_value=(0, log)) as command, patch.object(worker, 'text', return_value=json.dumps(summary)), patch.object(gate.time, 'time', side_effect=[100, 130]):
                    worker.run_tests('se3', owned, 'hosted', ['TouchColorTests/Suite/testA'], {'testA'})
                command.assert_called_once()
                name, argv, ceiling = command.call_args.args
                self.assertEqual(name, 'se3-hosted'); self.assertEqual(ceiling, 600)
                self.assertEqual(command.call_args.kwargs, {'simulator': True, 'allow_failure': True})
                for flag, value in [('-project', 'TouchColor.xcodeproj'), ('-scheme', 'TouchColor'),
                                    ('-configuration', 'Debug'), ('-destination', 'platform=iOS Simulator,id=' + owned),
                                    ('-derivedDataPath', str(root / 'derived')), ('-resultBundlePath', str(root / 'se3-hosted.xcresult')),
                                    ('-parallel-testing-enabled', 'NO'), ('-default-test-execution-time-allowance', '120'),
                                    ('-maximum-test-execution-time-allowance', '180')]:
                    self.assertEqual(argv[argv.index(flag) + 1], value)
                self.assertIn('test-without-building', argv)
                self.assertIn('-only-testing:TouchColorTests/Suite/testA', argv)
                self.assertIn('CODE_SIGNING_ALLOWED=NO', argv)
                self.assertNotIn('simctl', argv)
        source = Path(gate.__file__).read_text()
        self.assertNotIn("['xcrun', 'simctl', 'install'", source)
        self.assertIn("os.environ.get('GITHUB_SHA') == self.expected_sha", source)
        self.assertIn("self.text('source-sha', ['git', 'rev-parse', 'HEAD']) == self.expected_sha", source)
        self.assertIn("app = WORK / 'derived/Build/Products/Debug-iphonesimulator/TouchColor.app'", source)
        self.assertIn("require(app.is_dir(), 'Exact built app is missing')", source)

    def test_hosted_install_uncertainty_blocks_bootstrap_seed_ui_and_cleanup(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'ipad-mini')
                def tests(*unused):
                    worker.uncertain_simulator = True
                    raise RuntimeError('managed install or hosted execution uncertain')
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'command') as command, patch.object(worker, 'await_owned_boot'), patch.object(worker, 'run_tests', side_effect=tests) as runs:
                    with self.assertRaisesRegex(RuntimeError, 'hosted execution uncertain'):
                        worker.run_device([{'name': gate.DEVICE_NAMES['ipad-mini'], 'identifier': 'ipad-type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, {'ui'})
                    worker.cleanup()
                    self.assertEqual([call.args[2] for call in runs.call_args_list], ['hosted'])
                    self.assertEqual([call.args[0] for call in command.call_args_list], ['ipad-mini-boot'])
                self.assertEqual(worker.owned, [owned])
                self.assertTrue(worker.uncertain_simulator)

    def test_controller_deadline_prevents_launch_after_23_minutes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.time, 'monotonic', return_value=100):
                worker = gate.Gate('a' * 40, 'ipad-mini')
                self.assertEqual(worker.deadline, 1480)
            with patch.object(gate.time, 'monotonic', return_value=1456), patch.object(gate.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                    worker.command('past-deadline', ['fixture'], 300, simulator=True)
                process.assert_not_called()

    def test_per_device_upload_budget_cannot_double_workflow_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'evidence'; source.mkdir()
            with (source / 'over-device-budget.png').open('wb') as stream: stream.truncate(13 * 1024 * 1024)
            (source / 'acceptance.json').write_text('{"functional_passed":false}')
            self.assertFalse(gate.admit_evidence(source, root / 'published'))
            receipt = json.loads((root / 'published/artifact-admission.json').read_text())
            self.assertEqual(receipt['limit_bytes'], 12 * 1024 * 1024)
            self.assertFalse((root / 'published/over-device-budget.png').exists())

    def test_acceptance_leaves_room_for_receipt_and_upload_admission(self):
        import sys
        from unittest.mock import patch
        class Worker:
            owned = []
            uncertain_simulator = False
            def __init__(self, *args): pass
            def main(self): pass
            def cleanup(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with (root / 'near-ceiling.log').open('wb') as stream:
                stream.truncate(gate.EVIDENCE_BUDGET_BYTES - 100 * 1024)
            with patch.object(gate, 'EVIDENCE', root), patch.object(gate, 'Gate', Worker), patch.object(gate.signal, 'signal'), patch.object(sys, 'argv', ['gate', '--expected-sha', 'a' * 40, '--device', 'se3']):
                self.assertEqual(gate.main(), 1)
            receipt = json.loads((root / 'acceptance.json').read_text())
            self.assertFalse(receipt['functional_passed'])
            self.assertEqual(receipt['device_label'], 'se3')
            self.assertEqual(receipt['required_devices'], ['se3', 'ipad-mini'])

    def test_privacy_split_preserves_content_actions_lifecycle_and_real_data(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        content = source.split('- (void)testNativePrivacyContentAndActionsFromEmptyLibrary {', 1)[1].split('- (void)testNativePrivacyBackgroundClosePreservesRealSavedColor', 1)[0]
        lifecycle = source.split('- (void)testNativePrivacyBackgroundClosePreservesRealSavedColor {', 1)[1].split('- (void)testLiveUnavailable', 1)[0]
        for case in [content, lifecycle]:
            self.assertIn('[self launchReset:YES extra:nil]', case)
            self.assertIn('[self tap:@"original.about"]', case)
            self.assertIn('[self tap:@"privacyPolicy"]', case)
            self.assertIn('[self tap:@"privacy.close"]', case)
            self.assertIn('[self waitAbsent:content]', case)
            self.assertIn('[self tap:@"original.picker"]; [self assertHomeUsable]', case)
        for required in ['count:0', '[self assertLocalPolicyBody]', 'privacy.contact', 'privacy.externalPolicy',
                         '[self revealPrivacyAction:button inScrollView:actions]', 'XCTAssertTrue(button.enabled)',
                         'XCTAssertTrue(button.hittable)', 'privacy.externalError', '05-secondary-privacy-policy']:
            self.assertIn(required, content)
        for forbidden in ['sampleAndSaveRed', '[self tap:@"privacy.contact"]', '[self tap:@"privacy.externalPolicy"]', '[button tap]']:
            self.assertNotIn(forbidden, content)
        for required in ['[self sampleAndSaveRed]', 'pressButton:XCUIDeviceButtonHome', '[self.app activate]',
                         'Foreground restoration must retain', '[self tap:@"original.about.close"]',
                         '[self deleteOnlySavedColor:self.app.tables[@"colorHistory"]]']:
            self.assertIn(required, lifecycle)
        self.assertEqual(lifecycle.count('count:1'), 3)
        self.assertEqual(content.count('05-secondary-privacy-policy'), 1)
        self.assertNotIn('executionTimeAllowance', source)

    def trace_guard(self):
        spec = importlib.util.spec_from_file_location('preservation', gate.ROOT / 'scripts/verify_original_design_source.py')
        guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
        return guard

    def test_reviewed_debug_blocks_reconstruct_entire_original_app_source(self):
        guard = self.trace_guard()
        source = (gate.ROOT / 'ColorPicker/ColorMainViewController.m').read_text()
        stripped = guard.strip_picker_trace(source)
        self.assertEqual(hashlib.sha256(stripped.encode()).hexdigest(), 'ac08d2198bfe31e429b32fc69340cdf49fe3e08fe10721eb808a39d4efb85461')
        self.assertEqual(len(guard.PICKER_TRACE_BLOCKS), 5)
        for block in guard.PICKER_TRACE_BLOCKS:
            self.assertTrue(block.startswith('\n#if DEBUG // TC_PICKER_TRACE_BEGIN'))
            self.assertIn('#endif // TC_PICKER_TRACE_END', block)
        contract = json.loads((gate.ROOT / 'scripts/fixtures/original-design-preservation.json').read_text())
        for key, expected in contract['protected_methods'].items():
            name, signature = key.split(':', 1)
            if name == 'ColorMainViewController.m':
                self.assertEqual(hashlib.sha256(guard.method(stripped, signature).encode()).hexdigest(), expected)
        self.assertNotIn('TC_PICKER_TRACE', stripped)

    def test_unreviewed_or_changed_trace_cannot_bypass_original_hash_guard(self):
        guard = self.trace_guard()
        source = (gate.ROOT / 'ColorPicker/ColorMainViewController.m').read_text()
        for changed in [source.replace('event:@"delegate"', 'event:@"altered"'),
                        source + guard.PICKER_TRACE_BLOCKS[1],
                        source + '\n#if DEBUG // TC_PICKER_TRACE_BEGIN unreviewed\n#endif\n']:
            with self.assertRaises(RuntimeError): guard.strip_picker_trace(changed)
        changed = source.replace('NSUInteger dismissalGeneration = ++self.selectionGeneration;', 'NSUInteger dismissalGeneration = self.selectionGeneration;')
        reconstructed = guard.strip_picker_trace(changed)
        self.assertNotEqual(hashlib.sha256(reconstructed.encode()).hexdigest(), 'ac08d2198bfe31e429b32fc69340cdf49fe3e08fe10721eb808a39d4efb85461')

    def test_cancel_diagnostic_still_taps_once_and_requires_ten_second_absence(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        cancel = source.split('- (void)cancelPickerOnce:', 1)[1].split('- (void)testPhotosLibraryBootstrap', 1)[0]
        self.assertEqual(cancel.count('[cancel tap]'), 1)
        self.assertIn('[self waitAbsent:cancel]', cancel)
        self.assertIn('CGRectEqualToRect(firstFrame,secondFrame)', cancel)
        self.assertIn('secondSample-firstSample>=0.25', cancel)
        self.assertLess(cancel.index('[self capture:name]'), cancel.index('[cancel tap]'))
        self.assertIn('ORIGINAL_PICKER_CANCEL_SINGLE_TAP', cancel)
        absence = source.split('- (void)waitAbsent:', 1)[1].split('- (XCUIElement *)openLibrary', 1)[0]
        self.assertIn('exists == false', absence)
        self.assertIn('timeout:10', absence)
        self.assertIn('AX may hide the source; missing is not proof', source)
        self.assertNotIn('coordinateWithNormalizedOffset', cancel)

    def test_cancel_samples_are_separate_and_fail_closed(self):
        import re
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        cancel = source.split('- (void)cancelPickerOnce:', 1)[1].split('- (void)testPhotosLibraryBootstrap', 1)[0]
        self.assertEqual(cancel.count('waitForExistenceWithTimeout:5'), 1)
        self.assertEqual(cancel.count('cancel.enabled'), 1)
        self.assertEqual(cancel.count('cancel.hittable'), 1)
        self.assertEqual(cancel.count('self.app.windows.firstMatch.frame'), 1)
        self.assertEqual(cancel.count('cancel.frame'), 2)
        self.assertNotIn('predicate', cancel)
        self.assertNotIn('sleep', cancel)
        self.assertNotIn('XCTWaiter', cancel)
        positions = [cancel.index(token) for token in [
            'CGRect window=', 'CGRect firstFrame=', 'NSTimeInterval firstSample=',
            '[self capture:name]', '[self recordAppPickerTrace:@"before-cancel"]',
            'NSTimeInterval secondSample=', 'CGRect secondFrame=', 'BOOL stable=',
            'if (!stable)', '[cancel tap]']]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('CGRectContainsRect(window,CGRectInset(firstFrame,1,1))', cancel)
        # Every failed precondition exits the helper; continueAfterFailure is
        # not relied upon to prevent a tap after missing or moving geometry.
        failed = re.findall(r'XCTFail\([^;]*;\s*return;', cancel)
        self.assertEqual(len(failed), 4)
        self.assertEqual(cancel.count('XCTFail('), 4)
        self.assertTrue(all(cancel.index(check) < cancel.index('[cancel tap]') for check in failed))

    def test_bootstrap_is_separate_and_never_selects_or_deletes_photos(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        bootstrap = source.split('- (void)' + gate.BOOTSTRAP_TEST + ' {', 1)[1].split('- (void)testOriginalHomeTabs', 1)[0]
        for required in ['[self launchReset:YES extra:nil]', 'photosView_content_scroll_view', 'bootstrap-picker-ready',
                         'bootstrap-cancel-before', '[self cancelPickerOnce:cancel', '[self assertHomeUsable]', 'count:0']:
            self.assertIn(required, bootstrap)
        for forbidden in ['selectOnlySeededPhoto', 'sampleAndSaveRed', 'delete', 'authorization', 'requestAuthorization']:
            self.assertNotIn(forbidden, bootstrap)
        runner = Path(gate.__file__).read_text()
        self.assertIn('ui.remove(BOOTSTRAP_TEST)', runner)
        self.assertIn("if label == 'ipad-mini':", runner)
        self.assertIn("['TouchColorUITests/' + UI_CLASS + '/' + name for name in sorted(ui)]", runner)
        self.assertIn("['xcrun', 'simctl', 'addmedia', device, str(fixture)], 60", runner)
        self.assertIn("'bootstrap_inventory': 1 if args.device == 'ipad-mini' else 0", runner)
        self.assertIn('no cold Photos-service claim', runner)

    def test_failed_bootstrap_never_starts_addmedia_or_acceptance_ui(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'ipad-mini')
                def tests(label, device, suite, selectors, names):
                    if suite == 'bootstrap': raise RuntimeError('bootstrap failure')
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'command') as command, patch.object(worker, 'await_owned_boot'), patch.object(worker, 'run_tests', side_effect=tests) as runs:
                    with self.assertRaisesRegex(RuntimeError, 'bootstrap failure'):
                        worker.run_device([{'name': gate.DEVICE_NAMES['ipad-mini'], 'identifier': 'ipad-type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, {'ui'})
                    self.assertEqual([call.args[2] for call in runs.call_args_list], ['hosted', 'bootstrap'])
                    self.assertEqual([call.args[0] for call in command.call_args_list], ['ipad-mini-boot'])
                self.assertEqual(worker.owned, [owned])

    def test_trace_capture_is_owned_read_only_bounded_and_missing_is_not_no_callback(self):
        source = Path(gate.__file__).read_text()
        trace = source.split("trace_code, trace = self.command", 1)[1].split('qualify_summary(summary', 1)[0]
        self.assertIn("['xcrun', 'simctl', 'spawn', device, 'log', 'show'", trace)
        self.assertIn('TC_PICKER_TRACE', trace)
        self.assertIn('30, simulator=True, allow_failure=True', trace)
        self.assertIn("else 'missing'", trace)
        self.assertIn('Transport absent is not proof a delegate callback did not occur', trace)
        self.assertLess(source.index('self.export_screenshots(label if'), source.index('trace_code, trace = self.command'))
        self.assertEqual(gate.BOOTSTATUS_TIMEOUT_SECONDS, 300)
        self.assertEqual(gate.CONTROLLER_TIMEOUT_SECONDS, 23 * 60)

if __name__ == '__main__':
    unittest.main(verbosity=2)
