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

    def test_host_fixture_observation_records_exact_identity_without_changes(self):
        import os, stat
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.png'; path.write_bytes(gate.fixture_png()); path.chmod(0o640)
            before = path.stat(); observed = gate.fixture_observation(path)
            self.assertEqual(observed['status'], 'observed')
            self.assertEqual(observed['permission_mode'], '0o640')
            self.assertEqual(observed['lstat']['uid'], os.getuid())
            self.assertEqual(observed['lstat']['gid'], before.st_gid)
            self.assertEqual(observed['fstat']['ino'], before.st_ino)
            self.assertEqual(observed['bytes_read'], 1675)
            self.assertEqual(observed['sha256'], '6190ef70ec7da8b038c026cb8ffc0fc03b40a67ebdc6a382ee68b502135874ba')
            self.assertTrue(observed['matches_generated_fixture'])
            self.assertTrue(observed['stable_during_read'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_host_fixture_observation_never_follows_link_or_reads_oversized_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'target'; target.write_bytes(b'not the synthetic fixture')
            link = root / 'fixture.png'; link.symlink_to(target)
            large = root / 'large.png'
            with large.open('wb') as stream: stream.truncate(1024 * 1024 + 1)
            for path in [link, large, root / 'missing.png']:
                with patch.object(gate.os, 'open') as opened:
                    result = gate.fixture_observation(path)
                self.assertEqual(result['status'], 'unavailable'); opened.assert_not_called()
                self.assertNotIn('sha256', result)

    def test_host_diagnostics_use_only_capped_host_reads_after_simulator_uncertainty(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); fixture = root / 'fixture.png'; fixture.write_bytes(gate.fixture_png())
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3'); worker.uncertain_simulator = True
                def command(name, argv, seconds, **kwargs):
                    worker.commands.append({'name': name, 'host_group_exit_confirmed': True, 'log_bytes': 10})
                    return 0, root / 'unused'
                with patch.object(worker, 'command', side_effect=command) as calls:
                    worker.seed_host_diagnostics('se3', 'OWNED-UUID', fixture, 'after', 100, 160)
                self.assertEqual(calls.call_count, 3)
                for call in calls.call_args_list:
                    self.assertFalse(call.kwargs['simulator'])
                    self.assertTrue(call.kwargs['allow_failure'])
                    self.assertEqual(call.kwargs['output_limit_bytes'], 256 * 1024)
                    self.assertEqual(call.kwargs['cleanup_grace'], 1)
                    self.assertLessEqual(call.args[2], 8)
                    self.assertNotIn('simctl', call.args[1])
                    self.assertNotIn('spawn', call.args[1])
                    self.assertNotIn('sudo', call.args[1])
                self.assertEqual(calls.call_args_list[0].args[1], ['/bin/ps', '-axo', 'pid,ppid,pcpu,pmem,rss,state,etime,comm'])
                log = calls.call_args_list[2].args[1]
                self.assertEqual(log[:2], ['/usr/bin/log', 'show'])
                self.assertEqual(log[log.index('--start') + 1], '1970-01-01 00:01:40+0000')
                self.assertEqual(log[log.index('--end') + 1], '1970-01-01 00:02:40+0000')
                self.assertIn('CoreSimulator', log[-1]); self.assertIn('OWNED-UUID', log[-1])
                receipt = json.loads((root / 'evidence/se3-seed-host-after.json').read_text())
                self.assertTrue(receipt['simulator_uncertain'])
                self.assertEqual(receipt['phase_budget_seconds'], 20)
                self.assertIn('not service health', receipt['claim'])
                self.assertTrue(worker.uncertain_simulator)

    def test_host_diagnostic_timeout_with_confirmed_cleanup_is_explicit_and_best_effort(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                def command(name, *args, **kwargs):
                    worker.commands.append({'name': name, 'host_group_exit_confirmed': True, 'error': 'diagnostic timeout'})
                    raise gate.subprocess.TimeoutExpired('host-only', 3)
                with patch.object(worker, 'command', side_effect=command) as calls:
                    worker.seed_host_diagnostics('se3', 'U', root / 'missing.png', 'before', 100, 130)
                self.assertEqual(calls.call_count, 3)
                self.assertFalse(worker.uncertain_simulator)
                receipt = json.loads((root / 'evidence/se3-seed-host-before.json').read_text())
                self.assertTrue(all(row['status'] == 'unavailable' for row in receipt['observations']))
                self.assertTrue(all(row['command']['host_group_exit_confirmed'] for row in receipt['observations']))

    def test_host_diagnostic_budget_exhaustion_launches_nothing(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3'); worker.deadline = gate.time.monotonic() + 25
                with patch.object(worker, 'command') as calls:
                    worker.seed_host_diagnostics('se3', 'U', root / 'fixture.png', 'after', 100, 130)
                calls.assert_not_called()
                receipt = json.loads((root / 'evidence/se3-seed-host-after.json').read_text())
                self.assertEqual(len(receipt['observations']), 3)
                self.assertTrue(all('not launched' in row['error'] for row in receipt['observations']))

    def test_diagnostic_receipt_persistence_failure_stops_before_new_seed(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(gate, 'write_json', side_effect=OSError('evidence cannot be retained')), patch.object(worker, 'command') as command:
                    with self.assertRaisesRegex(OSError, 'evidence cannot be retained'):
                        worker.seed_fixture('se3', 'U', root / 'fixture.png')
                command.assert_not_called()
                self.assertFalse(worker.uncertain_simulator)

    def test_empty_capped_or_unretained_host_output_is_not_complete_diagnostics(self):
        from unittest.mock import patch
        for fields in [{'log_bytes': 0}, {'log_bytes': 100, 'output_limit_reached': True},
                       {'log_bytes': 100, 'log_tail_truncated': True, 'log_retained_bytes': 0}]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                    worker = gate.Gate('a' * 40, 'se3')
                    def command(name, *args, **kwargs):
                        worker.commands.append(dict(name=name, host_group_exit_confirmed=True, **fields))
                        return 0, root / 'unused'
                    with patch.object(worker, 'command', side_effect=command):
                        worker.seed_host_diagnostics('se3', 'U', root / 'fixture.png', 'before', 100, 130)
                    receipt = json.loads((root / 'evidence/se3-seed-host-before.json').read_text())
                    self.assertTrue(all(row['status'] == 'unavailable_or_partial' for row in receipt['observations']))

    def test_host_phase_consumes_at_most_its_own_and_controller_budget(self):
        from unittest.mock import patch
        for remaining, expected in [(1000, [3, 3, 8]), (37, [3, 3])]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); clock = [100.0]
                with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.time, 'monotonic', side_effect=lambda: clock[0]):
                    worker = gate.Gate('a' * 40, 'se3'); worker.deadline = clock[0] + remaining
                    def command(name, argv, seconds, **kwargs):
                        clock[0] += seconds + 2  # Worst-case two signal cleanup reserves.
                        worker.commands.append({'name': name, 'host_group_exit_confirmed': True, 'log_bytes': 10})
                        return 0, root / 'unused'
                    with patch.object(worker, 'command', side_effect=command) as calls:
                        worker.seed_host_diagnostics('se3', 'U', root / 'fixture.png', 'after', 100, 130)
                    self.assertEqual([call.args[2] for call in calls.call_args_list], expected)
                    self.assertLessEqual(clock[0], min(120, worker.deadline - 25))

    def test_receipt_failure_after_successful_seed_never_starts_dependent_ui(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'await_owned_boot'), patch.object(worker, 'run_tests') as tests, patch.object(worker, 'seed_host_diagnostics', side_effect=[None, OSError('receipt unavailable')]), patch.object(worker, 'command') as calls:
                    with self.assertRaisesRegex(OSError, 'receipt unavailable'):
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type.se3'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                self.assertEqual([call.args[0] for call in calls.call_args_list], ['se3-boot', 'se3-seed'])
                self.assertEqual([call.args[2] for call in tests.call_args_list], ['hosted', 'bootstrap', 'ui-independent'])
                self.assertFalse(worker.uncertain_simulator)

    def test_host_diagnostic_unconfirmed_group_aborts_seed_and_device_cleanup(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3'); worker.owned = ['U']
                def command(name, *args, **kwargs):
                    worker.commands.append({'name': name, 'host_group_exit_confirmed': False})
                    raise RuntimeError('diagnostic group remains')
                with patch.object(worker, 'command', side_effect=command) as calls:
                    with self.assertRaisesRegex(RuntimeError, 'Host diagnostic process-group exit unconfirmed'):
                        worker.seed_fixture('se3', 'U', root / 'fixture.png')
                    worker.cleanup()
                self.assertEqual(calls.call_count, 1)
                self.assertTrue(worker.uncertain_simulator)
                receipt = json.loads((root / 'evidence/se3-seed-host-before.json').read_text())
                self.assertIn('device actions blocked', receipt['observations'][0]['stop_reason'])

    def test_interrupted_host_diagnostic_still_blocks_cleanup_when_group_unconfirmed(self):
        from unittest.mock import patch
        for interruption in [KeyboardInterrupt('stop'), SystemExit('stop')]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                    worker = gate.Gate('a' * 40, 'se3'); worker.owned = ['U']
                    def command(name, *args, **kwargs):
                        worker.commands.append({'name': name, 'host_group_exit_confirmed': False})
                        raise interruption
                    with patch.object(worker, 'command', side_effect=command) as calls:
                        with self.assertRaises(type(interruption)) as caught:
                            worker.seed_fixture('se3', 'U', root / 'fixture.png')
                        worker.cleanup()
                    self.assertIs(caught.exception, interruption)
                    self.assertEqual(calls.call_count, 1)
                    self.assertTrue(worker.uncertain_simulator)
                    receipt = json.loads((root / 'evidence/se3-seed-host-before.json').read_text())
                    self.assertIn('device actions blocked', receipt['observations'][0]['stop_reason'])

    def test_diagnostic_raw_output_is_capped_in_child_without_changing_parent_limit(self):
        import contextlib, io, sys
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); before = gate.resource.getrlimit(gate.resource.RLIMIT_FSIZE)
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), contextlib.redirect_stdout(io.StringIO()):
                worker = gate.Gate('a' * 40, 'se3')
                code, path = worker.command('host-output-cap', [sys.executable, '-c', 'import os; os.write(1, b"x" * (1024 * 1024)); os.write(1,b"y")'],
                                            3, allow_failure=True, output_limit_bytes=256 * 1024, cleanup_grace=1)
            self.assertNotEqual(code, 0)
            self.assertLessEqual(path.stat().st_size, 256 * 1024)
            self.assertTrue(worker.commands[-1]['output_limit_reached'])
            self.assertTrue(worker.commands[-1]['host_group_exit_confirmed'])
            self.assertFalse(worker.uncertain_simulator)
            self.assertEqual(gate.resource.getrlimit(gate.resource.RLIMIT_FSIZE), before)

    def test_seed_still_runs_exactly_once_with_unchanged_command_and_budget(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'seed_host_diagnostics') as diagnostic, patch.object(worker, 'command') as command:
                    worker.seed_fixture('se3', 'U', root / 'fixture.png')
                command.assert_called_once_with('se3-seed', ['xcrun', 'simctl', 'addmedia', 'U', str(root / 'fixture.png')], 60, simulator=True)
                self.assertEqual([call.args[3] for call in diagnostic.call_args_list], ['before', 'after'])
                self.assertEqual(gate.CONTROLLER_TIMEOUT_SECONDS, 23 * 60)

    def test_original_seed_failure_survives_secondary_diagnostic_exception_or_interrupt(self):
        from unittest.mock import patch
        for secondary in [RuntimeError('host diagnostics failed'), KeyboardInterrupt('host diagnostic interrupted')]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                    worker = gate.Gate('a' * 40, 'se3'); original = gate.subprocess.TimeoutExpired('exact-original-addmedia', 60)
                    with patch.object(worker, 'seed_host_diagnostics', side_effect=[None, secondary]), patch.object(worker, 'command', side_effect=original) as command:
                        with self.assertRaises(gate.subprocess.TimeoutExpired) as caught:
                            worker.seed_fixture('se3', 'U', root / 'fixture.png')
                    self.assertIs(caught.exception, original); command.assert_called_once()

    def test_pre_seed_cancellation_never_launches_addmedia(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'seed_host_diagnostics', side_effect=KeyboardInterrupt('stop')), patch.object(worker, 'command') as command:
                    with self.assertRaises(KeyboardInterrupt): worker.seed_fixture('se3', 'U', root / 'fixture.png')
                command.assert_not_called()

    def test_seed_uncertainty_preserves_prior_ui_but_never_starts_dependent_ui_or_cleanup(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                def command(name, argv, *args, **kwargs):
                    if name == 'se3-seed':
                        worker.uncertain_simulator = True
                        raise gate.subprocess.TimeoutExpired(argv, 60)
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'await_owned_boot'), patch.object(worker, 'run_tests') as tests, patch.object(worker, 'seed_host_diagnostics') as diagnostic, patch.object(worker, 'command', side_effect=command) as calls:
                    with self.assertRaises(gate.subprocess.TimeoutExpired):
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type.se3'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                    worker.cleanup()
                self.assertEqual([call.args[0] for call in calls.call_args_list], ['se3-boot', 'se3-seed'])
                self.assertEqual([call.args[2] for call in tests.call_args_list], ['hosted', 'bootstrap', 'ui-independent'])
                self.assertEqual([call.args[3] for call in diagnostic.call_args_list], ['before', 'after'])
                self.assertTrue(worker.uncertain_simulator); self.assertEqual(worker.owned, [owned])

    def test_dependency_phases_cover_all_six_cases_once_without_changing_bodies(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        independent = gate.UI_PHASE_TESTS['ui-independent']; seeded = gate.UI_PHASE_TESTS['ui-seeded']
        self.assertEqual(len(independent), 3); self.assertEqual(len(seeded), 3)
        self.assertFalse(independent & seeded)
        self.assertEqual(independent | seeded, gate.testcase_names(gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m') - {gate.BOOTSTRAP_TEST})
        guard = self.trace_guard()
        for case in independent:
            body = guard.method(source, '- (void)' + case)
            self.assertNotIn('sampleAndSaveRed', body)
            self.assertNotIn('selectOnlySeededPhoto', body)
        for case in seeded:
            self.assertIn('sampleAndSaveRed', guard.method(source, '- (void)' + case))
        method = Path(gate.__file__).read_text().split('    def run_device(', 1)[1].split('    def cleanup(', 1)[0]
        positions = [method.index(x) for x in ["device, 'hosted'", "device, 'bootstrap'", "device, 'ui-independent'", 'self.seed_fixture(', "device, 'ui-seeded'", 'self.qualify_ui_completion(']]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(method.count("device, 'bootstrap'"), 1)

    def test_ui_and_evidence_budgets_are_shared_not_multiplied_by_two_phases(self):
        from unittest.mock import patch
        self.assertEqual(gate.UI_TOTAL_BUDGETS, {'execution': 600, 'summary': 30, 'attachments': 60, 'picker-trace': 30})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); clock = [100.0]
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.time, 'monotonic', side_effect=lambda: clock[0]):
                worker = gate.Gate('a' * 40, 'se3')
                def command(*args, **kwargs): clock[0] += 5; return 0, root / 'log'
                with patch.object(worker, 'command', side_effect=command) as calls:
                    for key, ceiling in gate.UI_TOTAL_BUDGETS.items():
                        worker.ui_command(key, 'first-' + key, ['host-fixture'])
                        self.assertEqual(calls.call_args.args[2], ceiling)
                        worker.ui_command(key, 'second-' + key, ['host-fixture'])
                        self.assertEqual(calls.call_args.args[2], ceiling - 5)
                        self.assertEqual(worker.ui_budgets[key], ceiling - 10)
                worker.ui_budgets['execution'] = 0.9
                with patch.object(worker, 'command') as command:
                    with self.assertRaisesRegex(RuntimeError, 'Shared UI execution budget exhausted'):
                        worker.ui_command('execution', 'no-launch', ['xcodebuild'])
                command.assert_not_called()

    def test_ui_budget_is_charged_even_when_command_is_interrupted(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); clock = [100.0]
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.time, 'monotonic', side_effect=lambda: clock[0]):
                worker = gate.Gate('a' * 40, 'se3'); original = KeyboardInterrupt('stop')
                def command(*args, **kwargs): clock[0] += 12; raise original
                with patch.object(worker, 'command', side_effect=command):
                    with self.assertRaises(KeyboardInterrupt) as caught: worker.ui_command('execution', 'ui', ['fixture'])
                self.assertIs(caught.exception, original); self.assertEqual(worker.ui_budgets['execution'], 588)

    def test_ui_phase_records_pass_failure_unrun_and_rejects_duplicate_execution(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with patch.object(worker, 'execute_tests') as execute:
                    worker.run_tests('se3', 'U', 'ui-independent', [], gate.UI_PHASE_TESTS['ui-independent'])
                    self.assertEqual(worker.ui_phase_results['ui-independent']['status'], 'passed')
                    self.assertEqual(worker.ui_phase_results['ui-seeded']['status'], 'not_run')
                    with self.assertRaisesRegex(RuntimeError, 'never execute twice'):
                        worker.run_tests('se3', 'U', 'ui-independent', [], gate.UI_PHASE_TESTS['ui-independent'])
                    with self.assertRaisesRegex(RuntimeError, 'Unknown or unsplit'):
                        worker.run_tests('se3', 'U', 'ui', [], set().union(*gate.UI_PHASE_TESTS.values()))
                    self.assertEqual(execute.call_count, 1)
                original = RuntimeError('seeded test assertion failed')
                with patch.object(worker, 'execute_tests', side_effect=original):
                    with self.assertRaises(RuntimeError) as caught:
                        worker.run_tests('se3', 'U', 'ui-seeded', [], gate.UI_PHASE_TESTS['ui-seeded'])
                self.assertIs(caught.exception, original)
                receipt = json.loads((root / 'evidence/se3-ui-phases.json').read_text())
                self.assertEqual(receipt['phases']['ui-independent']['status'], 'passed')
                self.assertEqual(receipt['phases']['ui-seeded']['status'], 'failed')

    def test_independent_ui_failure_stops_before_seed_and_dependent_ui(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                def execute(label, device, suite, *args):
                    if suite == 'ui-independent': raise RuntimeError('independent assertion failure')
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'command'), patch.object(worker, 'await_owned_boot'), patch.object(worker, 'execute_tests', side_effect=execute) as calls, patch.object(worker, 'seed_fixture') as seed:
                    with self.assertRaisesRegex(RuntimeError, 'independent assertion failure'):
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                seed.assert_not_called()
                self.assertEqual([call.args[2] for call in calls.call_args_list], ['hosted', 'bootstrap', 'ui-independent'])
                self.assertEqual(worker.ui_phase_results['ui-independent']['status'], 'failed')
                self.assertEqual(worker.ui_phase_results['ui-seeded']['status'], 'not_run')

    def test_seed_failure_retains_three_prior_ui_cases_and_declares_three_unrun(self):
        from unittest.mock import patch
        owned = '01234567-89AB-CDEF-0123-456789ABCDEF'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                def seed(*args): worker.uncertain_simulator = True; raise gate.subprocess.TimeoutExpired('addmedia', 60)
                with patch.object(worker, 'text', return_value=owned), patch.object(worker, 'command') as commands, patch.object(worker, 'await_owned_boot'), patch.object(worker, 'execute_tests') as cases, patch.object(worker, 'seed_fixture', side_effect=seed):
                    with self.assertRaises(gate.subprocess.TimeoutExpired):
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                    worker.cleanup()
                receipt = json.loads((root / 'evidence/se3-ui-phases.json').read_text())['phases']
                self.assertEqual(receipt['ui-independent']['status'], 'passed')
                self.assertEqual(len(receipt['ui-independent']['expected_tests']), 3)
                self.assertEqual(receipt['ui-seeded']['status'], 'not_run')
                self.assertEqual(len(receipt['ui-seeded']['expected_tests']), 3)
                self.assertEqual([call.args[2] for call in cases.call_args_list], ['hosted', 'bootstrap', 'ui-independent'])
                self.assertEqual([call.args[0] for call in commands.call_args_list], ['se3-boot'])

    def test_phase_screenshots_are_disjoint_retained_and_globally_complete(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                def export(budget, name, argv, **kwargs):
                    self.assertEqual(budget, 'attachments')
                    destination = Path(argv[argv.index('--output-path') + 1]); destination.mkdir()
                    phase = 'ui-independent' if 'ui-independent' in name else 'ui-seeded'
                    rows = []
                    for image in gate.UI_PHASE_IMAGES[phase]:
                        filename = image + '.png'; (destination / filename).write_bytes(gate.fixture_png())
                        rows.append({'exportedFileName': filename, 'name': image})
                    (destination / 'manifest.json').write_text(json.dumps(rows))
                    return 0, root / 'log'
                with patch.object(worker, 'ui_command', side_effect=export) as calls:
                    worker.export_screenshots('se3', root / 'one.xcresult', require_complete=True, phase='ui-independent')
                    first = (root / 'evidence/se3-ui-independent-screenshots.json').read_bytes()
                    self.assertEqual(len(worker.ui_screenshots), 4)
                    worker.export_screenshots('se3', root / 'two.xcresult', require_complete=True, phase='ui-seeded')
                self.assertEqual((root / 'evidence/se3-ui-independent-screenshots.json').read_bytes(), first)
                self.assertTrue((root / 'evidence/se3-ui-seeded-screenshots.json').exists())
                self.assertNotEqual(calls.call_args_list[0].args[1], calls.call_args_list[1].args[1])
                self.assertEqual(len(list((root / 'evidence').glob('*.png'))), 6)
                for row in worker.ui_phase_results.values(): row['status'] = 'passed'
                worker.qualify_ui_completion('se3')
                self.assertEqual(len(json.loads((root / 'evidence/se3-screenshots.json').read_text())), 6)
                worker.ui_screenshots.append(dict(worker.ui_screenshots[0]))
                with self.assertRaisesRegex(RuntimeError, 'Duplicate screenshot'): worker.qualify_ui_completion('se3')

    def test_incomplete_phase_or_missing_global_image_never_qualifies(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                with self.assertRaisesRegex(RuntimeError, 'Both UI phases'): worker.qualify_ui_completion('se3')
                for row in worker.ui_phase_results.values(): row['status'] = 'passed'
                worker.ui_screenshots = [{'name': name} for name in sum(gate.UI_PHASE_IMAGES.values(), [])[:-1]]
                with self.assertRaisesRegex(RuntimeError, 'Incomplete six-image'): worker.qualify_ui_completion('se3')

    def test_global_ui_case_inventory_rejects_duplicate_across_phases(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'):
                worker = gate.Gate('a' * 40, 'se3')
                for row in worker.ui_phase_results.values(): row['status'] = 'passed'
                worker.ui_phase_results['ui-seeded']['expected_tests'][0] = worker.ui_phase_results['ui-independent']['expected_tests'][0]
                with self.assertRaisesRegex(RuntimeError, 'UI testcase inventory'):
                    worker.qualify_ui_completion('se3')

    def test_both_ui_phases_use_shared_execution_summary_attachment_and_trace_allowances(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate, 'WORK', root), patch.object(gate, 'EVIDENCE', root / 'evidence'), patch.object(gate.time, 'time', return_value=100):
                worker = gate.Gate('a' * 40, 'se3'); selections = []
                def ui_command(budget, name, argv, **kwargs):
                    path = root / (name + '.log')
                    if budget == 'execution':
                        selected = {value.rsplit('/', 1)[-1] for value in argv if value.startswith('-only-testing:')}
                        selections.append(selected)
                        self.assertEqual(argv[argv.index('-destination') + 1], 'platform=iOS Simulator,id=U')
                        self.assertIn('test-without-building', argv)
                        self.assertEqual(argv[argv.index('-default-test-execution-time-allowance') + 1], '120')
                        self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance') + 1], '180')
                        path.write_text(''.join("Test Case '-[Suite " + case + "]' passed (0.1 seconds).\n" for case in sorted(selected)))
                    elif budget == 'summary':
                        summary = self.summary(); summary.update(totalTestCount=3, passedTests=3, startTime=100, finishTime=100)
                        summary['devicesAndConfigurations'][0]['passedTests'] = 3
                        summary['devicesAndConfigurations'][0]['device']['deviceId'] = 'U'
                        path.write_text(json.dumps(summary))
                    else: path.write_text('TC_PICKER_TRACE event=delegate')
                    return 0, path
                with patch.object(worker, 'ui_command', side_effect=ui_command) as commands, patch.object(worker, 'export_screenshots') as exports:
                    for phase, selected in gate.UI_PHASE_TESTS.items():
                        selectors = ['TouchColorUITests/' + gate.UI_CLASS + '/' + name for name in sorted(selected)]
                        worker.run_tests('se3', 'U', phase, selectors, selected)
                self.assertEqual([c.args[0] for c in commands.call_args_list], ['execution', 'summary', 'picker-trace'] * 2)
                self.assertEqual([c.kwargs['phase'] for c in exports.call_args_list], list(gate.UI_PHASE_TESTS))
                self.assertEqual(len(set().union(*selections)), 6)
                self.assertTrue(all(row['observed_counts']['passedTests'] == 3 for row in worker.ui_phase_results.values()))

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

    def workflow_sources(self):
        return {path.name: path.read_text() for path in (gate.ROOT / '.github/workflows').iterdir()
                if path.is_file() and path.suffix in ('.yml', '.yaml')}

    def assert_fixed_workflow_headers(self, sources):
        # A strict contract for these six checked-in headers, not a YAML parser.
        # The native runner needs only Python's standard library for this gate.
        expected = {
            'apple-platforms.yml': ('platform-integration', True, 'touchcolor-platforms-${{ github.ref }}'),
            'mac-watch-repair.yml': ('mac-watch-repair', False, 'touchcolor-platforms-refs/heads/platform-integration'),
            'ios.yml': ('ios-original-release', True, 'touchcolor-ios-${{ github.ref }}'),
            'ios-completion.yml': ('ios-original-completion', True, 'touchcolor-ios-refs/heads/ios-original-release'),
            'ios-original-archive.yml': ('ios-original-archive', True, 'touchcolor-ios-original-archive'),
            'original-design-gate.yml': ('touchcolor-original-design', False, 'touchcolor-original-design-${{ github.ref }}'),
        }
        self.assertEqual(set(sources), set(expected))
        matched = []
        for filename, raw in sources.items():
            branch, manual, group = expected[filename]
            name, newline, rest = raw.partition('\n')
            self.assertEqual(newline, '\n')
            self.assertRegex(name, r'^name: [A-Za-z0-9 -]+$')
            # Reject duplicate/unknown top-level keys, document boundaries and aliases.
            top_level = [line for line in raw.splitlines()
                         if line and not line[0].isspace() and not line.startswith('#')]
            self.assertEqual(top_level, [name, 'on:', 'permissions:', 'concurrency:', 'jobs:'])
            header, separator, body = rest.partition('jobs:\n')
            self.assertEqual(separator, 'jobs:\n')
            self.assertTrue(body.strip())
            allowed = ('on:\n  push:\n    branches: [' + branch + ']\n'
                       + ('  workflow_dispatch:\n' if manual else '')
                       + 'permissions:\n  contents: read\nconcurrency:\n  group: ' + group
                       + '\n  cancel-in-progress: false\n')
            self.assertEqual(header, allowed)
            self.assertNotIn('codex/', raw)
            if branch == 'touchcolor-original-design': matched.append(filename)
        self.assertEqual(matched, ['original-design-gate.yml'])
        for canonical, followup in [('apple-platforms.yml', 'mac-watch-repair.yml'),
                                    ('ios.yml', 'ios-completion.yml')]:
            branch, _, group = expected[canonical]
            self.assertIn('${{ github.ref }}', group)
            self.assertEqual(expected[followup][2], group.replace('${{ github.ref }}', 'refs/heads/' + branch))

    def test_only_original_design_workflow_matches_its_push_branch(self):
        sources = self.workflow_sources()
        self.assert_fixed_workflow_headers(sources)

    def test_fixed_workflow_headers_reject_unknown_duplicate_or_broadened_structure(self):
        sources = self.workflow_sources()
        for filename, raw in sources.items():
            mutations = [
                raw.replace('on:\n', 'on:\n  pull_request:\n', 1),
                raw.replace('on:\n', 'on:\non:\n', 1),
                raw.replace('  push:\n', '  push:\n  push:\n', 1),
                raw.replace('    branches: [', '    branches: [foreign, ', 1),
                raw.replace('    branches: [', '    branches: []\n    branches: [', 1),
                raw.replace('on:\n', 'on: &routes\n', 1),
                raw.replace('  push:\n', '  push: *routes\n', 1),
                raw.replace('concurrency:\n', 'concurrency:\nconcurrency:\n', 1),
                raw.replace('  group: ', '  group: alias\n  group: ', 1),
                raw.replace('concurrency:\n', 'concurrency: *shared\n', 1),
                raw.replace('  group: ', '  group: &shared ', 1),
                raw.replace('contents: read', 'contents: write', 1),
                raw.replace('cancel-in-progress: false', 'cancel-in-progress: true', 1),
                raw + '\non:\n  schedule: []\n',
                '---\n' + raw,
                raw + '\n---\non: {push: {branches: [foreign]}}\n',
            ]
            for index, changed in enumerate(mutations):
                with self.subTest(filename=filename, mutation=index), self.assertRaises(AssertionError):
                    self.assert_fixed_workflow_headers({**sources, filename: changed})
        with self.assertRaises(AssertionError):
            self.assert_fixed_workflow_headers({**sources, 'unknown.yml': sources['original-design-gate.yml']})
        with self.assertRaises(AssertionError):
            self.assert_fixed_workflow_headers({name: raw for name, raw in sources.items() if name != 'ios.yml'})

    def test_workflow_inventory_rejects_unexpected_yaml_suffix_file(self):
        from unittest.mock import patch
        sources = self.workflow_sources()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            directory = root / '.github/workflows'
            directory.mkdir(parents=True)
            for filename, raw in sources.items(): (directory / filename).write_text(raw)
            with patch.object(gate, 'ROOT', root):
                self.test_only_original_design_workflow_matches_its_push_branch()
                (directory / 'unknown.yaml').write_text(sources['original-design-gate.yml'])
                with self.assertRaises(AssertionError):
                    self.test_only_original_design_workflow_matches_its_push_branch()

    def test_workflow_route_guard_does_not_import_optional_yaml(self):
        import builtins
        from unittest.mock import patch
        original_import = builtins.__import__
        def without_yaml(name, *args, **kwargs):
            if name == 'yaml' or name.startswith('yaml.'):
                raise ModuleNotFoundError("No module named 'yaml'")
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_yaml):
            with self.assertRaises(ModuleNotFoundError): builtins.__import__('yaml')
            self.test_only_original_design_workflow_matches_its_push_branch()

    def test_workflow_route_guard_runs_without_site_packages(self):
        import os, subprocess, sys
        environment = dict(os.environ)
        environment.pop('PYTHONPATH', None)
        completed = subprocess.run(
            [sys.executable, '-S', str(Path(__file__).resolve()),
             'OriginalDesignGateTests.test_only_original_design_workflow_matches_its_push_branch'],
            cwd=gate.ROOT, env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_original_design_runtime_rejects_other_routes_before_commands(self):
        from unittest.mock import patch
        controller = object.__new__(gate.Gate)
        controller.expected_sha = 'a' * 40
        environment = {'GITHUB_REPOSITORY': '100mango/ColorPicker',
                       'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/touchcolor-original-design',
                       'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40}
        rejected = ('refs/heads/platform-integration', 'refs/heads/mac-watch-repair',
                    'refs/heads/ios-original-release', 'refs/heads/ios-original-completion',
                    'refs/heads/ios-original-archive', 'refs/heads/main',
                    'refs/heads/codex/platform-integration', 'refs/heads/codex/mac-watch-repair',
                    'refs/heads/codex/ios-original-release', 'refs/heads/codex/ios-original-completion',
                    'refs/heads/codex/ios-original-archive', 'refs/heads/codex/touchcolor-original-design')
        changes = [{'GITHUB_REF': ref} for ref in rejected]
        changes.extend({'GITHUB_EVENT_NAME': event} for event in ('workflow_dispatch', 'pull_request', 'workflow_run', 'schedule'))
        for changed in changes:
            with self.subTest(changed=changed), patch.dict(gate.os.environ, {**environment, **changed}, clear=True), \
                    patch.object(gate.sys, 'platform', 'darwin'), \
                    patch.object(controller, 'text') as text, patch.object(controller, 'command') as command:
                with self.assertRaisesRegex(RuntimeError, 'Only the root-controlled'): controller.main()
                text.assert_not_called(); command.assert_not_called()
        class ReachedSourceVerification(Exception): pass
        with patch.dict(gate.os.environ, environment, clear=True), patch.object(gate.sys, 'platform', 'darwin'), \
                patch.object(controller, 'text', side_effect=ReachedSourceVerification) as text:
            with self.assertRaises(ReachedSourceVerification): controller.main()
            text.assert_called_once_with('source-sha', ['git', 'rev-parse', 'HEAD'])

    def test_workflow_targets_only_ipad_probe_without_claiming_both_devices(self):
        workflow = (gate.ROOT / '.github/workflows/original-design-gate.yml').read_text()
        for required in ['device: [ipad-mini]', 'fail-fast: false', 'max-parallel: 1',
                         'timeout-minutes: 25', 'runs-on: xcode-27', 'ref: ${{ github.sha }}',
                         'EXPECTED_SHA: ${{ github.sha }}', 'DEVICE_LABEL: ${{ matrix.device }}',
                         '--expected-sha "$EXPECTED_SHA" --device "$DEVICE_LABEL"',
                         'name: touchcolor-original-design-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.device }}']:
            self.assertIn(required, workflow)
        self.assertEqual(workflow.count('device: [ipad-mini]'), 1)
        self.assertNotIn('device: [se3]', workflow)
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
                    with patch.object(worker, 'text', return_value=owned) as create, patch.object(worker, 'command') as command, patch.object(worker, 'await_owned_boot') as ready, patch.object(worker, 'run_tests') as tests, patch.object(worker, 'seed_fixture') as seed, patch.object(worker, 'qualify_ui_completion') as completion:
                        worker.run_device(types, runtime, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                    create.assert_called_once()
                    args = create.call_args.args
                    self.assertEqual(args[0], label + '-create')
                    self.assertEqual(args[1][-2:], ['type.' + label, 'owned-runtime'])
                    ready.assert_called_once_with(label, owned, worker.devices[0]['owned_name'])
                    self.assertEqual([call.args[0] for call in command.call_args_list], [label + suffix for suffix in ['-boot', '-shutdown', '-delete']])
                    seed.assert_called_once_with(label, owned, root / 'fixture.png')
                    self.assertEqual([call.args[2] for call in tests.call_args_list], ['hosted', 'bootstrap', 'ui-independent', 'ui-seeded'])
                    self.assertEqual([call.args[-1] for call in tests.call_args_list], [{'hosted'}, {gate.BOOTSTRAP_TEST}, gate.UI_PHASE_TESTS['ui-independent'], gate.UI_PHASE_TESTS['ui-seeded']])
                    completion.assert_called_once_with(label)
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
                        worker.run_device([{'name': gate.DEVICE_NAMES['se3'], 'identifier': 'type.se3'}], {'identifier': 'owned-runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
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
                        worker.run_device([{'name': gate.DEVICE_NAMES['ipad-mini'], 'identifier': 'ipad-type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
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
            ui_phase_results = {}
            ui_budgets = dict(gate.UI_TOTAL_BUDGETS)
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
                         'bootstrap-cancel-before', '[self dismissPhotoPickerOnceWithAttachment:', '[self assertHomeUsable]', 'count:0']:
            self.assertIn(required, bootstrap)
        for forbidden in ['selectOnlySeededPhoto', 'sampleAndSaveRed', 'delete', 'authorization', 'requestAuthorization']:
            self.assertNotIn(forbidden, bootstrap)
        runner = Path(gate.__file__).read_text()
        self.assertIn('ui.remove(BOOTSTRAP_TEST)', runner)
        self.assertNotIn("if label == 'ipad-mini':", runner)
        self.assertIn("['TouchColorUITests/' + UI_CLASS + '/' + name for name in sorted(seeded)]", runner)
        self.assertIn("['xcrun', 'simctl', 'addmedia', device, str(fixture)], 60", runner)
        self.assertIn("'bootstrap_inventory': 1", runner)
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
                        worker.run_device([{'name': gate.DEVICE_NAMES['ipad-mini'], 'identifier': 'ipad-type'}], {'identifier': 'runtime'}, root / 'app', root / 'fixture.png', {'hosted'}, set().union(*gate.UI_PHASE_TESTS.values()))
                    self.assertEqual([call.args[2] for call in runs.call_args_list], ['hosted', 'bootstrap'])
                    self.assertEqual([call.args[0] for call in command.call_args_list], ['ipad-mini-boot'])
                self.assertEqual(worker.owned, [owned])

    def test_native_picker_readiness_matches_each_surface(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        ready = source.split('- (BOOL)waitForPhotoPickerSurface {', 1)[1].split('- (void)dismissPopoverOnceWithAttachment:', 1)[0]
        self.assertIn('UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad', ready)
        for required in ['XCUIElementTypePopover', 'PopoverDismissRegion', 'photosView_content_scroll_view']:
            self.assertIn(required, ready)
        self.assertIn('} else if (![self.app.buttons[@"Cancel"].firstMatch waitForExistenceWithTimeout:10])', ready)
        for method, end in [('selectOnlySeededPhoto', 'sampleAndSaveRed'),
                            ('testPhotosLibraryBootstrapCanCancelWithoutSelecting', 'testOriginalHomeTabsAndRepeatedPhotoPickerCancellation'),
                            ('testOriginalHomeTabsAndRepeatedPhotoPickerCancellation', 'deleteOnlySavedColor')]:
            body = source.split('- (void)' + method, 1)[1].split('- (void)' + end, 1)[0]
            self.assertIn('if (![self waitForPhotoPickerSurface]) return;', body)
            self.assertNotIn('buttons[@"Cancel"]', body)
        routing = source.split('- (void)dismissPhotoPickerOnceWithAttachment:', 1)[1].split('- (void)cancelPickerOnce:', 1)[0]
        self.assertIn('UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad', routing)
        self.assertIn('[self dismissPopoverOnceWithAttachment:name]', routing)
        self.assertIn('[self cancelPickerOnce:self.app.buttons[@"Cancel"].firstMatch attachment:name]', routing)

    def test_popover_dismissal_is_one_stable_primary_tap_outside_controls(self):
        import re
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        body = source.split('- (void)dismissPopoverOnceWithAttachment:', 1)[1].split('- (void)dismissPhotoPickerOnceWithAttachment:', 1)[0]
        self.assertEqual(body.count('popover.frame'), 2)
        self.assertEqual(body.count('snapshotWithError:&snapshotError'), 1)
        self.assertNotIn('region.frame', body)
        self.assertNotIn('self.app.windows.firstMatch.frame', body)
        self.assertNotIn('self.app.buttons[identifier].frame', body)
        self.assertEqual(body.count('] tap]'), 1)
        for forbidden in ['[region tap]', 'buttons[@"Close"]', 'buttons[@"Cancel"]', 'sleep', 'dismissViewController', 'swipe']:
            self.assertNotIn(forbidden, body)
        for identifier in ['choosePhoto', 'takePhoto', 'liveColor', 'original.picker', 'original.library']:
            self.assertIn('@"' + identifier + '"', body)
        for required in ['CGRectIntersection(CGRectInset(window,24,24),CGRectInset(regionFrame,24,24))',
                         'CGRectGetMaxY(firstFrame)+24', 'CGRectGetMaxY(value.CGRectValue)+24',
                         'CGRectContainsPoint(window,point)', 'CGRectContainsPoint(regionFrame,point)',
                         '!CGRectContainsPoint(CGRectInset(firstFrame,-12,-12),point)',
                         '!CGRectContainsPoint(CGRectInset(value.CGRectValue,-12,-12),point)',
                         'CGRectEqualToRect(firstFrame,secondFrame)', 'secondSample-firstSample<0.25',
                         '[self waitAbsent:popover]', 'XCTAssertFalse(self.app.scrollViews[@"photosView_content_scroll_view"].exists']:
            self.assertIn(required, body)
        order=[body.index(token) for token in ['snapshotWithError:&snapshotError', 'CGRect firstFrame=', 'NSTimeInterval firstSample=', '[self capture:name]',
            '[self recordAppPickerTrace:@"before-popover-dismiss"]', 'NSTimeInterval secondSample=', 'CGRect secondFrame=', 'ORIGINAL_PICKER_POPOVER_SINGLE_TAP', '] tap]', '[self waitAbsent:popover]']]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(re.findall(r'XCTFail\([^;]*;\s*return;', body)), body.count('XCTFail('))
        self.assertGreater(body.count('XCTFail('), 0)

    def test_local_snapshot_contract_keeps_live_popover_queries_and_bounded_unique_frames(self):
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        body = source.split('- (void)dismissPopoverOnceWithAttachment:', 1)[1].split('- (void)dismissPhotoPickerOnceWithAttachment:', 1)[0]
        for token in ['[self.app.windows.firstMatch snapshotWithError:&snapshotError]',
                      '!snapshot || snapshotError || snapshot.elementType!=XCUIElementTypeWindow',
                      'NSMutableArray<id<XCUIElementSnapshot>>', 'index<pending.count',
                      'children.count>2048-pending.count', '[pending addObjectsFromArray:children]',
                      'if (frames[key])', 'if (!TCDesignFiniteRect(frame))',
                      'frames.count!=7', 'XCUIElementTypeOther', 'XCUIElementTypeButton',
                      'CGRect firstFrame=popover.frame', 'CGRect secondFrame=popover.frame']:
            self.assertIn(token, body)
        for token in ['key=@"popover"', 'snapshotWithAttributes', '_XCT', 'valueForKey:',
                      'popover.exists', 'region.exists', 'cached', 'while (']:
            self.assertNotIn(token, body)
        # Only this helper changes. All seven testcase bodies, original home
        # checks and phone Cancel implementation remain exact baseline bytes.
        before, rest = source.split('- (void)dismissPopoverOnceWithAttachment:', 1)
        _, after = rest.split('- (void)dismissPhotoPickerOnceWithAttachment:', 1)
        unchanged = before + '<IPAD_DISMISS_HELPER>' + after
        self.assertEqual(hashlib.sha256(unchanged.encode()).hexdigest(), '35655c8dbd89495fa8860242b5d345dc3a91bf6e794ce4b8f09eb27f73f73413')

    @staticmethod
    def snapshot_fixture():
        # Portable model of immutable local XCUIElementSnapshot attributes;
        # neither this model nor source checks claim native SDK execution.
        controls = [('choosePhoto',(219.8,613,304.5,76.5)), ('takePhoto',(219.8,692.5,304.5,76.5)),
                    ('liveColor',(219.8,772,304.5,76.5)), ('original.picker',(216,97,156,44)),
                    ('original.library',(372,97,156,44))]
        return {'type':'Window', 'id':'', 'frame':(0,0,744,1133), 'children':[
            {'type':'Other','id':'PopoverDismissRegion','frame':(0,0,744,1133),'children':[]},
            *[{'type':'Button','id':name,'frame':frame,'children':[]} for name,frame in controls]]}

    @staticmethod
    def snapshot_model(root, error=False):
        import math
        identifiers={'choosePhoto','takePhoto','liveColor','original.picker','original.library'}
        if root is None or error or root['type']!='Window': raise ValueError('snapshot')
        frames={}; pending=[root]; index=0
        while index<len(pending):
            node=pending[index]; index+=1
            key=('window' if node['type']=='Window' else
                 'region' if node['type']=='Other' and node['id']=='PopoverDismissRegion' else
                 node['id'] if node['type']=='Button' and node['id'] in identifiers else None)
            if key:
                if key in frames: raise ValueError('duplicate')
                frame=node['frame']
                if not all(math.isfinite(x) for x in frame) or min(frame[2:])<=0: raise ValueError('frame')
                frames[key]=frame
            children=node['children']
            if len(children)>2048-len(pending): raise ValueError('inventory bound')
            pending.extend(children)
        if len(frames)!=7 or not {'window','region'} <= frames.keys(): raise ValueError('missing')
        return frames

    def test_snapshot_model_rejects_missing_duplicate_wrong_type_invalid_and_oversized_nodes(self):
        root=self.snapshot_fixture(); self.assertEqual(len(self.snapshot_model(root)),7)
        # A missing remote Photos subtree is valid: all geometry here is local.
        root['children'].append({'type':'Popover','id':'','frame':(0,0,0,0),'children':[]})
        self.assertEqual(len(self.snapshot_model(root)),7)
        for index in range(6):
            bad=self.snapshot_fixture(); bad['children'].pop(index)
            with self.subTest(missing=index), self.assertRaises(ValueError): self.snapshot_model(bad)
            bad=self.snapshot_fixture(); bad['children'].append(copy.deepcopy(bad['children'][index]))
            with self.subTest(duplicate=index), self.assertRaises(ValueError): self.snapshot_model(bad)
            bad=self.snapshot_fixture(); bad['children'][index]['type']='StaticText'
            with self.subTest(wrong_type=index), self.assertRaises(ValueError): self.snapshot_model(bad)
        for index in range(7):
            for frame in [(float('nan'),0,1,1),(0,float('inf'),1,1),(0,0,0,1),(0,0,1,-1)]:
                bad=self.snapshot_fixture(); node=bad if index==0 else bad['children'][index-1]; node['frame']=frame
                with self.subTest(index=index,frame=frame), self.assertRaises(ValueError): self.snapshot_model(bad)
        for root,error in [(None,False),(self.snapshot_fixture(),True),({'type':'Other'},False)]:
            with self.subTest(root=root,error=error), self.assertRaises(ValueError): self.snapshot_model(root,error)
        bad=self.snapshot_fixture(); bad['children'].append(copy.deepcopy(bad))
        with self.assertRaisesRegex(ValueError,'duplicate'): self.snapshot_model(bad)
        filler={'type':'Other','id':'unrelated','frame':(0,0,0,0),'children':[]}
        edge=self.snapshot_fixture(); edge['children'] += [filler] * (2048-7)
        self.assertEqual(len(self.snapshot_model(edge)),7)
        edge['children'].append(filler)
        with self.assertRaisesRegex(ValueError,'inventory bound'): self.snapshot_model(edge)
        # No shallow depth assumption: 64 unrelated ancestors remain bounded.
        deep=self.snapshot_fixture(); child=deep['children'].pop()
        for _ in range(64): child={**filler,'children':[child]}
        deep['children'].append(child); self.assertEqual(len(self.snapshot_model(deep)),7)

    @staticmethod
    def dismissal_point_model(frames, first=(10,32,724,581), second=(10,32,724,581), gap=0.25):
        import math
        def finite(r): return all(math.isfinite(x) for x in r) and min(r[2:])>0
        def contains(r,p,padding=0): return r[0]-padding<=p[0]<=r[0]+r[2]+padding and r[1]-padding<=p[1]<=r[1]+r[3]+padding
        def rect_inside(outer,inner): return contains(outer,(inner[0]+1,inner[1]+1)) and contains(outer,(inner[0]+inner[2]-1,inner[1]+inner[3]-1))
        window=frames['window'];region=frames['region'];controls=[v for k,v in frames.items() if k not in ('window','region')]
        if not all(finite(x) for x in [window,region,first,*controls]): raise ValueError('frame')
        if not all(rect_inside(window,x) for x in [first,*controls]): raise ValueError('outside')
        left=max(window[0]+24,region[0]+24);top=max(window[1]+24,region[1]+24)
        right=min(window[0]+window[2]-24,region[0]+region[2]-24);bottom=min(window[1]+window[3]-24,region[1]+region[3]-24)
        safe=(left,top,right-left,bottom-top);top=max(top,first[1]+first[3]+24,*[c[1]+c[3]+24 for c in controls])
        band=(left,top,right-left,bottom-top)
        if not finite(safe) or not finite(band): raise ValueError('no empty band')
        point=((left+right)/2,(top+bottom)/2)
        if not all(contains(x,point) for x in [window,region,safe]) or any(contains(x,point,12) for x in [first,*controls]): raise ValueError('unsafe point')
        if first!=second or gap<0.25: raise ValueError('unstable')
        return point

    def test_snapshot_geometry_model_preserves_point_and_rejects_unsafe_or_moving_bounds(self):
        frames=self.snapshot_model(self.snapshot_fixture());self.assertEqual(self.dismissal_point_model(frames),(372,990.75))
        mutations=[('window',(0,0,0,1133)),('region',(1000,0,744,1133)),
                   ('region',(0,0,744,610)),('liveColor',(0,1000,744,120)),
                   ('choosePhoto',(-100,600,20,20))]
        for key,value in mutations:
            bad=dict(frames);bad[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): self.dismissal_point_model(bad)
        for first,second,gap in [((10,32,724,1080),(10,32,724,1080),0.25),
                                 ((10,32,724,581),(10,33,724,581),0.25),
                                 ((10,32,724,581),(10,32,724,581),0.249),
                                 ((float('nan'),32,724,581),(10,32,724,581),0.25)]:
            with self.subTest(first=first,second=second,gap=gap), self.assertRaises(ValueError): self.dismissal_point_model(frames,first,second,gap)

    def test_snapshot_failure_diagnostics_are_whitelisted_bounded_and_before_every_local_failure(self):
        import re
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        body = source.split('- (void)dismissPopoverOnceWithAttachment:', 1)[1].split('- (void)dismissPhotoPickerOnceWithAttachment:', 1)[0]
        self.assertEqual(body.count('snapshotWithError:&snapshotError'),1)
        self.assertEqual(body.count('popover.frame'),2)
        self.assertEqual(body.count('] tap]'),1)
        self.assertIn('snapshot=[self.app.windows.firstMatch snapshotWithError:&snapshotError]',body)
        for token in ['[controlIdentifiers arrayByAddingObject:@"PopoverDismissRegion"]',
                      'if (diagnosticCounts[identifier])', 'samples.count<2',
                      '@"type":@(node.elementType)', '@"frame":diagnosticFrame(node.frame)',
                      'text.length<=128', 'header.length<=1024', 'row.length<=1024',
                      'visited=%lu queued=%lu complete=%d', 'windows=%lu matchedFrames=%lu',
                      'scope=first-window', 'traversalComplete=YES',
                      'recordGeometryDiagnostic(@"missing-required-inventory")']:
            self.assertIn(token,body)
        self.assertLess(body.index('if (diagnosticCounts[identifier])'),body.index('if (node.elementType==XCUIElementTypeWindow) key='))
        self.assertEqual(len(re.findall(r'recordGeometryDiagnostic\([^;]*;\s*XCTFail\(',body)),body.count('XCTFail('))
        for token in ['node.label','node.value','debugDescription','dictionaryRepresentation',
                      'snapshotError.domain','snapshotError.description','snapshotError.localizedDescription',
                      'frames=%@','pending=%@','children=%@','snapshot=%@','self.app snapshotWithError']:
            self.assertNotIn(token,body)
        self.assertNotIn('required: %@",snapshotError',body)

    def test_diagnostic_fixture_drops_unowned_data_and_caps_samples_and_frame_text(self):
        # This is a portable logger-format model, not native XCTest execution.
        import math
        whitelist=['choosePhoto','takePhoto','liveColor','original.picker','original.library','PopoverDismissRegion']
        counts={key:0 for key in whitelist}; samples={key:[] for key in whitelist}
        def observe(identifier,type_number,frame,**unowned):
            if identifier not in counts:return
            counts[identifier]+=1
            if len(samples[identifier])<2:
                rendered='{'+','.join(format(float(x),'.17g') for x in frame)+'}'
                samples[identifier].append({'type':type_number,'frame':rendered if len(rendered)<=128 else 'frame-format-out-of-bound'})
        observe('private-photo-name',9,(0,0,1,1),label='private-content',value='private-value')
        observe('choosePhoto',9,(0,0,1,1),label='private-content',value='private-value')
        observe('choosePhoto',48,(math.nan,math.inf,-math.inf,0))
        observe('choosePhoto',9,(1e308,-1e308,1e-308,1e-308))
        self.assertEqual(counts['choosePhoto'],3);self.assertEqual(len(samples['choosePhoto']),2)
        self.assertEqual(samples['choosePhoto'][1]['type'],48,'Wrong-type occurrence remains observable')
        self.assertEqual(counts['PopoverDismissRegion'],0,'Missing target is explicitly zero')
        for key in whitelist[1:]:observe(key,9,(1e308,-1e308,1e-308,1e-308))
        rows=[json.dumps({'identifier':key,'count':counts[key],'samples':samples[key]},sort_keys=True) for key in whitelist]
        self.assertTrue(all(len(row)<=1024 for row in rows))
        self.assertTrue(all(len(sample['frame'])<=128 for values in samples.values() for sample in values))
        output='\n'.join(rows)
        for forbidden in ['private-photo-name','private-content','private-value','label','value','children']:
            self.assertNotIn(forbidden,output)
        self.assertEqual(set(counts),set(whitelist));self.assertEqual(set(samples),set(whitelist))

    def test_popover_primary_point_fits_observed_ipad_geometry(self):
        # Same bounded geometry expressed from the actual run-37883561875 AX
        # frames; this is a calculation check, not a substitute for a native tap.
        window=(0,0,744,1133); region=window; popover=(10,32,724,581)
        controls=[(219.8,613,304.5,76.5),(219.8,692.5,304.5,76.5),
                  (219.8,772,304.5,76.5),(216,97,156,44),(372,97,156,44)]
        safe=(24,24,696,1085)
        top=max(safe[1],popover[1]+popover[3]+24,*[c[1]+c[3]+24 for c in controls])
        point=(safe[0]+safe[2]/2,(top+safe[1]+safe[3])/2)
        self.assertEqual(point,(372,990.75))
        def inside(r,p,padding=0):
            return r[0]-padding<=p[0]<=r[0]+r[2]+padding and r[1]-padding<=p[1]<=r[1]+r[3]+padding
        self.assertTrue(inside(window,point)); self.assertTrue(inside(region,point)); self.assertTrue(inside(safe,point))
        self.assertFalse(inside(popover,point,12))
        self.assertTrue(all(not inside(c,point,12) for c in controls))
        self.assertTrue(inside(popover,(window[2]/2,window[3]/2)), 'Blind region center would be inside Photos')

    def test_permissionless_bootstrap_precedes_seeding_on_both_devices(self):
        runner = Path(gate.__file__).read_text()
        method = runner.split('    def run_device(', 1)[1].split('    def cleanup(', 1)[0]
        self.assertLess(method.index("device, 'hosted'"), method.index("device, 'bootstrap'"))
        self.assertLess(method.index("device, 'bootstrap'"), method.index("self.seed_fixture(label, device, fixture)"))
        self.assertNotIn("if label == 'ipad-mini'", method)
        self.assertIn("'bootstrap_inventory': 1", runner)
        self.assertNotIn("else 'addmedia after hosted tests'", runner)
        for forbidden in ['privacy grant', 'requestAuthorization', 'PHPhotoLibrary', 'simctl erase']:
            self.assertNotIn(forbidden, method)
        source = (gate.ROOT / 'TouchColorUITests/TouchColorOriginalDesignUITests.m').read_text()
        repeated = source.split('- (void)testOriginalHomeTabsAndRepeatedPhotoPickerCancellation', 1)[1].split('- (void)deleteOnlySavedColor', 1)[0]
        self.assertIn('attempt<2', repeated)
        self.assertIn('[self assertHomeUsable]', repeated)
        self.assertIn('[self assertRedHistory:table count:0]', repeated)

    def test_trace_capture_is_owned_read_only_bounded_and_missing_is_not_no_callback(self):
        source = Path(gate.__file__).read_text()
        trace = source.split("trace_command = ", 1)[1].split('qualify_summary(summary', 1)[0]
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
