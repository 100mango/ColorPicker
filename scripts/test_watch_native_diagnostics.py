"""Portable synthetic contracts only; not Xcode 27 or Watch diagnostic proof."""
from pathlib import Path
import copy
import hashlib
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
import watch_native_diagnostics as n
import watch_xcresult_stack as old
from ios_watch_archive_capture import capture, CaptureStopped
from test_watch_xcresult_stack import inputs, objects, owner, stack, attachment, obj, val, ref, array, DEVICE, START, END, STAMP

ROOT = Path(__file__).resolve().parents[1]

def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'tEXt', b'private\0DO_NOT_PUBLISH') + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'')

def fixtures(screen=True, diagnostic=True):
    result = objects([])
    action = result[None]['actions']['_values'][0]['actionResult']
    if diagnostic:
        action['diagnosticsRef'] = ref('diagnostics-1')
    images = [attachment(name=val('Screenshot'), uniformTypeIdentifier=val('public.png'), payloadRef=ref('png-1'))] if screen else []
    result['summary-1']['identifier'] = val(old.TEST + '()')
    result['summary-1']['activitySummaries'] = array(obj('ActionTestActivitySummary',
        title=val('Tap "watch.edit.copy" Button'), start=val('2026-10-07T22:01:00+00:00'), attachments=array(*images)))
    return result

class Reader:
    def __init__(self, values=None, *, help_stderr=False, version='Xcode 27.0\nBuild version 27A266a\n', omit=None, payload=None):
        self.values = values if values is not None else fixtures()
        self.calls = []
        self.help_stderr, self.version, self.omit = help_stderr, version, omit
        self.payload = stack() if payload is None else payload

    def __call__(self, command, **options):
        self.calls.append((command, options))
        if options.get('guard'):
            options['guard']()
        help_call = False
        if command == ['xcodebuild', '-version']:
            data, help_call = self.version.encode(), True
        elif command == ['xcodebuild', '-help']:
            data, help_call = b'Usage: xcodebuild\n -collect-test-diagnostics on-failure|never\n', True
        elif command[:3] == ['xcrun', 'xcresulttool', 'help']:
            usage = 'xcresulttool ' + ' '.join(command[3:])
            data = (usage + '\n --path --output-path --device-id --legacy --id --format json --type file\n').encode()
            help_call = True
        elif command[:4] == ['xcrun', 'xcresulttool', 'get', 'object']:
            key = command[command.index('--id') + 1] if '--id' in command else None
            data = json.dumps(self.values[key]).encode()
        elif '--export-png' in command:
            Path(command[-1]).write_bytes(png()); data = b''
        elif '--export-diagnostics' in command:
            folder = Path(command[-1])
            (folder / 'TouchColor-hang.spindump').write_bytes(self.payload)
            # Unrelated environment text stays private and is never a candidate.
            (folder / 'system-environment.log').write_text('DO_NOT_PUBLISH_ENV')
            data = b''
        else:
            raise AssertionError('Unapproved synthetic command: ' + repr(command))
        if self.omit and help_call:
            data = data.replace(self.omit.encode(), b'')
        if options.get('guard'):
            options['guard']()
        return subprocess.CompletedProcess(command, 0, b'' if self.help_stderr and help_call else data,
                                           data if self.help_stderr and help_call else b'')

class NativeDiagnosticsTests(unittest.TestCase):
    def preflight(self, reader=None):
        report = {'phase': 'pending', 'calls': 0, 'seconds_spent': 0, 'metadata_bytes': 0}
        reader = reader or Reader()
        budget = n.Budget(report, 0, reader, now=lambda: 1)
        with patch.dict(os.environ, {'DEVELOPER_DIR': '/Applications/Xcode_27.app/Contents/Developer', 'TOUCHCOLOR_WATCH_LIVE_SAMPLE': '0'}):
            n.preflight(budget, report)
        return report, reader

    def exercise(self, reader=None):
        reader = reader or Reader()
        report, reader = self.preflight(reader)
        budget = n.Budget(report, 0, reader, now=lambda: 1)
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / old.BUNDLE).mkdir(parents=True); out = root / 'out'; out.mkdir()
            try:
                os.chdir(root)
                n.collect(budget, report, owner(), out, root)
                files = {p.name: p.read_bytes() for p in out.iterdir()}
                leftovers = list(root.glob('watch-stack-*'))
            finally:
                os.chdir(cwd)
        return report, files, leftovers, reader

    def test_installed_help_stdout_and_stderr_are_both_accepted(self):
        for stderr in (False, True):
            with self.subTest(stderr=stderr):
                report, reader = self.preflight(Reader(help_stderr=stderr))
                self.assertEqual(report['phase'], 'preflight-verified')
                self.assertEqual(len(reader.calls), 5)
                self.assertEqual(set(report['help']), {'xcodebuild', 'diagnostics', 'get-object', 'export-object'})
                self.assertIn('on-failure', report['help']['xcodebuild']['excerpt'])

    def test_preflight_rejects_wrong_version_and_missing_on_failure(self):
        for reader in (Reader(version='Xcode 26.0\nBuild version 26A1\n'), Reader(omit='on-failure')):
            with self.subTest(reader=reader), self.assertRaises(RuntimeError):
                self.preflight(reader)
            self.assertFalse(any('test-without-building' in c for c, _ in reader.calls))

    def test_absent_device_flag_uses_official_owned_bundle_export(self):
        report, files, leftovers, reader = self.exercise(Reader(omit='--device-id'))
        self.assertEqual(set(files), {n.STACK, n.SCREEN})
        self.assertFalse(report['action_diagnostics']['device_scoped_export'])
        self.assertEqual(report['action_diagnostics']['export_scope'], 'owned-result-bundle')
        exports = [command for command, _ in reader.calls if '--export-diagnostics' in command]
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0][-2], 'owned-bundle')
        self.assertEqual(leftovers, [])

    def test_official_export_argv_uses_optional_filter_only_when_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'RUNNER_TEMP': directory}), patch.object(n.resource, 'setrlimit'):
                for selector in ('owned-bundle', DEVICE):
                    with old.private_payload_directory(root) as folder, patch.object(n.os, 'execvp') as execute:
                        n.bounded_export('diagnostics', selector, str(folder))
                        argv = execute.call_args.args[1]
                        self.assertEqual(argv[:4], ['xcrun', 'xcresulttool', 'export', 'diagnostics'])
                        self.assertEqual(argv[argv.index('--path') + 1], old.BUNDLE)
                        self.assertEqual('--device-id' in argv, selector == DEVICE)

    def test_on_failure_must_be_on_collect_diagnostics_help_line(self):
        class Misleading(Reader):
            def __call__(self, command, **options):
                result = super().__call__(command, **options)
                if command == ['xcodebuild', '-help']:
                    return subprocess.CompletedProcess(command, 0, b'-collect-test-diagnostics never\n-retry-tests-on-failure\n', b'')
                return result
        with self.assertRaises(RuntimeError):
            self.preflight(Misleading())

    def test_budget_never_renews_metadata_calls_or_preflight_time(self):
        for state in ({'calls': n.MAX_CALLS}, {'metadata_bytes': n.MAX_METADATA}, {'seconds_spent': 23}):
            with self.subTest(state=state):
                report = {'calls': 0, 'metadata_bytes': 0, 'seconds_spent': 0, **state}
                reader = Reader(); budget = n.Budget(report, 0, reader, now=lambda: 1)
                with self.assertRaises(RuntimeError): budget.run(['xcodebuild', '-version'], cap=4096, help_output=True)
                self.assertEqual(reader.calls, [])

    def test_original_clock_reserve_is_still_required(self):
        reader = Reader(); budget = n.Budget({}, 0, reader, now=lambda: 2370)
        with self.assertRaises(RuntimeError): budget.run(['xcodebuild', '-version'], cap=4096, help_output=True)
        self.assertEqual(reader.calls, [])

    def test_binding_accepts_only_explicit_new_mode(self):
        runtime, source = inputs()
        command = runtime['stages'][0]['command']; command[command.index('-collect-test-diagnostics') + 1] = 'on-failure'
        self.assertEqual(old.binding(runtime, source, source, source['sha'], diagnostic_mode='on-failure')['pid'], 321)
        with self.assertRaises(ValueError): old.binding(runtime, source, source, source['sha'])
        with self.assertRaises(ValueError): old.binding(runtime, source, source, source['sha'], diagnostic_mode='anything')

    def test_action_diagnostics_and_case_screen_produce_only_two_sanitized_files(self):
        report, files, leftovers, reader = self.exercise()
        self.assertEqual(report['phase'], 'complete')
        self.assertFalse(report['qualified'])
        self.assertEqual(set(files), {n.STACK, n.SCREEN})
        self.assertNotIn(b'DO_NOT_PUBLISH', files[n.SCREEN])
        self.assertNotIn('DO_NOT_PUBLISH_ENV', json.dumps(report))
        self.assertNotIn('system-environment.log', json.dumps(report))
        self.assertNotIn(b'/Users/', files[n.STACK])
        self.assertNotIn(b'SECRET_BINARY_CONTENT', files[n.STACK])
        self.assertEqual(leftovers, [])
        self.assertTrue(report['raw_cleanup_confirmed'])
        exported = [c for c, _ in reader.calls if '--export-diagnostics' in c]
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0][-2], DEVICE)

    def test_action_reference_absent_still_keeps_native_case_screenshot(self):
        report, files, leftovers, reader = self.exercise(Reader(fixtures(diagnostic=False)))
        self.assertEqual(set(files), {n.SCREEN})
        self.assertEqual(report['evidence'], 'action-diagnostics-reference-missing')
        self.assertFalse(any('--export-diagnostics' in c for c, _ in reader.calls))
        self.assertEqual(leftovers, [])

    def test_second_same_device_action_and_build_diagnostics_are_rejected(self):
        for mode in ('second-action', 'build-diagnostics'):
            values = fixtures()
            first = values[None]['actions']['_values'][0]
            if mode == 'second-action':
                extra = copy.deepcopy(first); extra['actionResult'].pop('testsRef')
                values[None]['actions']['_values'].append(extra)
            else:
                first['buildResult'] = {'diagnosticsRef': ref('another-reference')}
            reader = Reader(values)
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): self.exercise(reader)
            self.assertFalse(any('--export-diagnostics' in command for command, _ in reader.calls))

    def test_no_screenshot_does_not_block_action_stack(self):
        report, files, leftovers, _ = self.exercise(Reader(fixtures(screen=False)))
        self.assertEqual(set(files), {n.STACK})
        self.assertEqual(report['screenshot']['state'], 'no-native-png-after-copy')

    def test_only_runner_stack_is_not_relabelled_app(self):
        payload = stack().replace(b'Process: TouchColor [321]', b'Process: TouchColorWatchUITests-Runner [321]')
        report, files, leftovers, _ = self.exercise(Reader(payload=payload))
        self.assertEqual(set(files), {n.SCREEN})
        self.assertEqual(report['app_stack']['state'], 'not-extracted')

    def test_multprocess_text_exposes_only_validated_target_section(self):
        raw = b'Process: Other [777]\nENV_SECRET\n' + stack() + b'\nProcess: Other [888]\nPRIVATE_EMAIL\n'
        text = n.extract_app_stack(raw, owner())
        self.assertIn('com.apple.main-thread', text)
        self.assertNotIn('ENV_SECRET', text)
        self.assertNotIn('PRIVATE_EMAIL', text)

    def test_wrong_pid_device_bundle_time_and_duplicate_app_reject(self):
        payloads = [stack().replace(b'TouchColor [321]', b'TouchColor [999]'),
                    stack().replace(DEVICE.encode(), b'99999999-9999-4999-8999-999999999999'),
                    stack().replace(old.APP.encode(), b'com.foreign.app'),
                    stack().replace(b'2026-10-07 22:02:00', b'2026-10-07 21:02:00'), stack() + stack()]
        for raw in payloads:
            with self.subTest(raw=raw[:60]), self.assertRaises(RuntimeError): n.extract_app_stack(raw, owner())

    def test_selected_stack_read_enforces_smaller_cap_before_io(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'hang.txt').write_bytes(b'x' * 32)
            with patch('watch_diagnostic_files.os.read') as read:
                with self.assertRaisesRegex(RuntimeError, 'tree_selection_bytes_limit'):
                    n.read_private_file(root, 'hang.txt', max_bytes=31)
                read.assert_not_called()

    def test_pre_copy_and_unknown_activity_are_not_failed_copy_screen(self):
        for change in ('earlier', 'no-copy'):
            values = fixtures()
            activity = values['summary-1']['activitySummaries']['_values'][0]
            if change == 'earlier': activity['attachments']['_values'][0]['timestamp'] = val('2026-10-07T22:00:30+00:00')
            else: activity['title'] = val('Some unrelated action')
            report, files, leftovers, _ = self.exercise(Reader(values))
            self.assertNotIn(n.SCREEN, files)
            self.assertIn(n.STACK, files)

    def test_latest_screenshot_tie_is_rejected(self):
        values = fixtures(); activity = values['summary-1']['activitySummaries']['_values'][0]
        other = copy.deepcopy(activity['attachments']['_values'][0]); other['payloadRef'] = ref('another-png')
        activity['attachments']['_values'].append(other)
        with self.assertRaisesRegex(RuntimeError, 'ambiguous-latest'): self.exercise(Reader(values))

    def test_raw_directory_is_removed_after_export_failure(self):
        class Failing(Reader):
            def __call__(self, command, **options):
                result = super().__call__(command, **options)
                if '--export-diagnostics' in command:
                    raise CaptureStopped('byte-limit', True)
                return result
        cwd = Path.cwd(); reader = Failing(); report, _ = self.preflight(reader)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / old.BUNDLE).mkdir(parents=True); out = root / 'out'; out.mkdir()
            try:
                os.chdir(root)
                with self.assertRaises(CaptureStopped): n.collect(n.Budget(report, 0, reader, now=lambda: 1), report, owner(), out, root)
                self.assertEqual(list(root.glob('watch-stack-*')), [])
                self.assertTrue(report['raw_cleanup_confirmed'])
                self.assertTrue((out / n.SCREEN).exists())
            finally: os.chdir(cwd)

    def cancellation_during_directory_cleanup(self, capture_cancelled):
        cwd = Path.cwd()
        original_cleanup = tempfile.TemporaryDirectory.cleanup
        reader = Reader(fixtures(screen=False))
        report, _ = self.preflight(reader)
        def runner(command, **options):
            result = reader(command, **options)
            if capture_cancelled and '--export-diagnostics' in command:
                raise CaptureStopped('interrupted', False, signal.SIGTERM)
            return result
        def cleanup(folder):
            if Path(folder.name).name.startswith('watch-stack-'):
                os.kill(os.getpid(), signal.SIGTERM)
            original_cleanup(folder)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / old.BUNDLE).mkdir(parents=True); out = root / 'out'; out.mkdir()
            try:
                os.chdir(root)
                with self.assertRaises(old.DiagnosticCancelled), old.cancellation_guard(), patch.object(tempfile.TemporaryDirectory, 'cleanup', cleanup):
                    n.collect(n.Budget(report, 0, runner, now=lambda: 1), report, owner(), out, root)
                self.assertEqual(list(root.glob('watch-stack-*')), [])
                self.assertTrue(report['raw_cleanup_confirmed'])
                if capture_cancelled:
                    self.assertIs(report['diagnostic_cleanup_confirmed'], False)
                    self.assertEqual(report['cancelled_signal'], signal.SIGTERM)
            finally:
                os.chdir(cwd)

    def test_first_sigterm_during_directory_cleanup_keeps_cleanup_result(self):
        self.cancellation_during_directory_cleanup(False)

    def test_capture_failure_then_sigterm_during_cleanup_preserves_unknown_group(self):
        self.cancellation_during_directory_cleanup(True)

    def test_capture_guard_stops_owned_process_and_does_not_wait_for_pipes(self):
        calls = [0]
        def guard():
            calls[0] += 1
            if calls[0] > 1: raise RuntimeError('directory-byte-limit')
        with self.assertRaises(CaptureStopped) as caught:
            capture([sys.executable, '-c', 'import time; time.sleep(30)'], seconds=2, cap=64, guard=guard)
        self.assertTrue(caught.exception.cleanup_confirmed)

    def test_guard_failure_before_spawn_runs_nothing(self):
        with patch('ios_watch_archive_capture.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                capture(['not-called'], seconds=1, cap=64, guard=lambda: (_ for _ in ()).throw(RuntimeError('directory-file-limit')))
            spawn.assert_not_called()

    def test_cancel_during_initial_guard_does_not_spawn(self):
        def guard():
            os.kill(os.getpid(), signal.SIGTERM)
        with patch('ios_watch_archive_capture.subprocess.Popen') as spawn:
            with self.assertRaises(CaptureStopped) as caught:
                capture(['not-called'], seconds=1, cap=64, guard=guard)
            spawn.assert_not_called()
            self.assertTrue(caught.exception.cleanup_confirmed)
            self.assertEqual(caught.exception.cancelled_signal, signal.SIGTERM)

    def test_product_and_selected_ui_case_are_frozen(self):
        expected = {'TouchColorWatch/WatchViews.swift': '7b696e4af3646ddf83ba9bd096cf43bdec0bc983',
                    'TouchColorWatchUITests/WatchWorkflowTests.swift': 'e4727baaca2bfca8af4f719c5257fc92818e45f0'}
        for path, digest in expected.items():
            raw = (ROOT / path).read_bytes()
            self.assertEqual(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(), digest)

    def test_native_runner_keeps_original_case_caps_and_no_live_sampler(self):
        source = (ROOT / 'scripts/test_extra_platforms.py').read_text()
        self.assertIn("'-collect-test-diagnostics','on-failure'", source)
        self.assertIn('normal_code=run(normal_command,840,required=False)', source)
        self.assertIn("FOCUSED_CASE='TouchColorWatchUITests/WatchWorkflowTests/testTouchCopyEntryTouchAndCrownRemainResponsive'", source)
        self.assertIn("live=LiveSample(report,command,device) if watch_cases is not None and report.get('watch_live_sample_enabled',True) else None", source)
        workflow = (ROOT / '.github/workflows/watch-focused-case.yml').read_text()
        self.assertIn("TOUCHCOLOR_WATCH_LIVE_SAMPLE: '0'", workflow)
        self.assertIn('timeout-minutes: 42', workflow)
        self.assertIn('timeout-minutes: 45', workflow)
        self.assertIn("RUNTIME_OUTCOME']=='success'", workflow)
        self.assertNotIn('continue-on-error', workflow)
        self.assertIn('unapproved diagnostic artifact member', workflow)

if __name__ == '__main__':
    unittest.main()
