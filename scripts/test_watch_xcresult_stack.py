"""Synthetic metadata/stack tests. These are not native diagnostic evidence."""
import copy
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import watch_xcresult_stack as d

DEVICE = '11111111-1111-4111-8111-111111111111'
PHONE = '22222222-2222-4222-8222-222222222222'
SHA = 'a' * 40
START = '2026-10-07T22:00:00+00:00'
END = '2026-10-07T22:03:00+00:00'
STAMP = '2026-10-07T22:02:00+00:00'

def val(x): return {'_value': x}
def obj(typ, **kwargs): return {'_type': {'_name': typ}, **kwargs}
def ref(x): return obj('Reference', id=val(x))
def array(*x): return {'_values': list(x)}
def owner(): return {'sha': SHA, 'case': d.TEST, 'pid': 321, 'device': DEVICE,
                     'start': d.timestamp(START), 'end': d.timestamp(END)}

def inputs():
    status = dict(exit=0, raw_exit=0, started=True, timed_out=False,
                  process_group_gone=True, capture_reader_finished=True)
    command = ['xcodebuild', 'test-without-building', '-configuration', 'Debug', '-destination',
               'platform=watchOS Simulator,id=' + DEVICE, '-collect-test-diagnostics', 'never',
               '-default-test-execution-time-allowance', '120', '-resultBundlePath', d.BUNDLE,
               '-only-testing:' + d.SUITE + '/' + d.TEST]
    test = dict(status, exit=65, raw_exit=65, command=command, started_at=START, finished_at=END)
    stages = [test] + [dict(status, command=['xcrun', 'simctl', action, device])
                      for action in ('shutdown', 'delete') for device in (DEVICE, PHONE)]
    runtime = dict(sha=SHA, result='failed', active_command=None, device={'udid': DEVICE}, stages=stages,
                   owned_watch_devices=[{'role': 'watch', 'udid': DEVICE}, {'role': 'phone', 'udid': PHONE}],
                   watch_editor_lifecycle={'exit': 0, 'processes': [{'case': d.CASE, 'pid': 321}]})
    return runtime, {'sha': SHA, 'tree': 'b' * 40, 'clean': True}

def attachment(**kwargs):
    node = obj('ActionTestAttachment', name=val('TouchColor [321] spindump'), filename=val('TouchColor-321.txt'),
               uniformTypeIdentifier=val('public.plain-text'), timestamp=val(STAMP), payloadRef=ref('payload-1'))
    node.update(kwargs)
    return node

def objects(attachments=None):
    return {
        None: obj('ActionsInvocationRecord', actions=array(obj('ActionRecord',
            runDestination={'targetDeviceRecord': {'identifier': val(DEVICE)}}, actionResult={'testsRef': ref('tests-1')}))),
        'tests-1': obj('ActionTestPlanRunSummaries', summaries=array(obj('ActionTestableSummary',
            targetName=val(d.SUITE), tests=array(obj('ActionTestMetadata', identifier=val(d.TEST + '()'),
                                                 testStatus=val('Failure'), summaryRef=ref('summary-1')))))),
        'summary-1': obj('ActionTestSummary', activitySummaries=array(obj('ActionTestActivitySummary',
            title=val('Wait for ' + d.APP + ' pid 321 to idle'), attachments=array(*(attachments if attachments is not None else [attachment()])))))
    }

def stack():
    return (f'Process: TouchColor [321]\nPath: /Users/runner/Library/Developer/CoreSimulator/Devices/{DEVICE}'
            '/data/Containers/Bundle/Application/33333333-3333-4333-8333-333333333333/TouchColor.app/TouchColor\n'
            f'Identifier: {d.APP}\nDate/Time: 2026-10-07 22:02:00 +0000\n'
            'Call graph:\n    80 Thread_123 DispatchQueue_1: com.apple.main-thread (serial)\n'
            '    + 80 main (in TouchColor) + 4 [0x1234]\n'
            '    + 80 updateFocus (in SwiftUI) + 8 [0x1238]\n'
            '    80 Thread_124 unrelated queue\n    + 80 private worker (in TouchColor) [0x5555]\n'
            'Binary Images:\nSECRET_BINARY_CONTENT\n').encode()

class Reader:
    def __init__(self, values=None): self.values, self.calls = values or objects(), []
    def __call__(self, command, **options):
        self.calls.append((command, options))
        if command[:3] == ['xcrun', 'xcresulttool', 'help']:
            data = b'--legacy --path --id --format json --type file --output-path'
        elif command[:4] == ['xcrun', 'xcresulttool', 'get', 'object']:
            key = command[command.index('--id') + 1] if '--id' in command else None
            data = json.dumps(self.values[key]).encode()
        elif command[0] == sys.executable and '--bounded-export' in command:
            Path(command[-1]).write_bytes(stack()); data = b''
        else: raise AssertionError('Unapproved diagnostic command: ' + repr(command))
        return subprocess.CompletedProcess(command, 0, data, b'')

class StackTests(unittest.TestCase):
    def test_source_and_native_completion_binding(self):
        runtime, source = inputs()
        self.assertEqual(d.binding(runtime, source, copy.deepcopy(source), SHA), owner())

    def test_rejects_source_process_destination_and_cleanup_mutations(self):
        mutations = [lambda r,s: s.update(sha='c'*40), lambda r,s: r.update(sha='c'*40),
                     lambda r,s: r.update(result='passed'), lambda r,s: r.update(active_command={}),
                     lambda r,s: r.update(cleanup_unconfirmed=True),
                     lambda r,s: r['stages'][0].update(exit=0),
                     lambda r,s: r['stages'][0].update(raw_exit=0),
                     lambda r,s: r['stages'][0].update(timed_out=True),
                     lambda r,s: r['stages'][0].update(process_group_gone=False),
                     lambda r,s: r['stages'][0].update(capture_reader_finished=False),
                     lambda r,s: r['stages'][1].update(exit=1),
                     lambda r,s: r['device'].update(udid=PHONE),
                     lambda r,s: r['watch_editor_lifecycle'].update(exit=1),
                     lambda r,s: r['stages'][0]['command'].__setitem__(r['stages'][0]['command'].index('-resultBundlePath') + 1, 'build/foreign.xcresult'),
                     lambda r,s: r['watch_editor_lifecycle']['processes'].append({'case': d.CASE, 'pid': 999}),
                     lambda r,s: r['stages'][0]['command'].append('-only-testing:Foreign/case')]
        for change in mutations:
            runtime, source = inputs(); after = copy.deepcopy(source); change(runtime, source)
            with self.subTest(change=change), self.assertRaises((ValueError, IndexError)):
                d.binding(runtime, source, after, SHA)

    def test_verified_help_before_collection(self):
        reader = Reader(); report = {}; budget = d.Budget(report, 0, reader, now=lambda: 1)
        d.preflight(budget, report)
        self.assertEqual(report['phase'], 'preflight-verified'); self.assertEqual(len(report['help']), 2)
        self.assertEqual([c[0][-2:] for c in reader.calls], [['get', 'object'], ['export', 'object']])
        with self.assertRaises(ValueError): d.preflight(budget, report)

    def test_unsupported_help_stops_without_guessing(self):
        calls = []
        def runner(command, **options):
            calls.append(command); return subprocess.CompletedProcess(command, 0, b'--path --id', b'')
        report = {}; budget = d.Budget(report, 0, runner, now=lambda: 1)
        with self.assertRaises(ValueError): d.preflight(budget, report)
        self.assertEqual(len(calls), 1)
        self.assertIn('--path', report['help']['get']['text'])

    def test_permission_error_and_oversize_output_do_not_trigger_fallback(self):
        for code, stdout, stderr in ((1, b'', b'Permission denied'), (0, b'x'*65, b'')):
            seen = []
            def runner(command, **options):
                seen.append(command); return subprocess.CompletedProcess(command, code, stdout, stderr)
            budget = d.Budget({}, 0, runner, now=lambda: 1)
            with self.assertRaises(ValueError): budget.run(['only-command'], cap=64)
            self.assertEqual(seen, [['only-command']])

    def test_cumulative_clock_count_and_original_job_reserve_are_not_renewed(self):
        clock = [0.0]; calls = []
        def runner(command, **options):
            calls.append(command); clock[0] += 8; return subprocess.CompletedProcess(command, 0, b'', b'')
        report = {}; budget = d.Budget(report, 0, runner, now=lambda: clock[0])
        for _ in range(3): budget.run(['mock'])
        with self.assertRaises(ValueError): budget.run(['mock'])
        budget.finish(); self.assertEqual(report['seconds_spent'], 24)
        resumed = d.Budget(report, 0, runner, now=lambda: clock[0])
        with self.assertRaises(ValueError): resumed.run(['mock'])
        for data in ({'calls': 8}, {'seconds_spent': float('nan')}, {'seconds_spent': -1}):
            with self.assertRaises(ValueError): d.Budget(data, 0, runner, now=lambda: 2390).run(['mock'])
        self.assertEqual(len(calls), 3)

    def test_metadata_requires_its_own_app_and_owner_not_parent_activity(self):
        bad = [attachment(name=val('spindump'), filename=val('generic.txt')),
               attachment(name=val('TouchColor spindump'), filename=val('unrelated321suffix.txt')),
               attachment(name=val('TouchColorWatchUITests-Runner [321] spindump'), filename=val('runner.txt')),
               attachment(name=val(d.APP + '.xctrunner [321] spindump'), filename=val('runner.txt')),
               attachment(name=val('TouchColor [999] spindump'), filename=val('TouchColor-999.txt')),
               attachment(uniformTypeIdentifier=val('public.png'))]
        for row in bad:
            candidates, inventory = d.attachment_candidates(objects([row])['summary-1'], owner())
            self.assertEqual(candidates, []); self.assertEqual(len(inventory), 1)

    def test_metadata_time_graph_and_attachment_count_fail_closed(self):
        with self.assertRaises(ValueError): d.attachment_candidates(objects([attachment(timestamp=val(START.replace('22:00', '21:00')))])['summary-1'], owner())
        with self.assertRaises(ValueError): d.attachment_candidates(objects([attachment()]*33)['summary-1'], owner())
        node = 0
        for _ in range(34): node = {'child': node}
        with self.assertRaises(ValueError): list(d.walk(node))
        with self.assertRaises(ValueError): list(d.walk([0]*8193))
        with self.assertRaises(ValueError): d.reference({'ref': ref('bad ID\n')}, 'ref')

    def test_exported_payload_must_match_pid_bundle_device_and_text(self):
        for raw in (stack().replace(b'[321]', b'[999]'), stack().replace(d.APP.encode(), b'other.app'),
                    stack().replace(DEVICE.encode(), PHONE.encode()), stack()+b'\x00',
                    stack().replace(b'22:02:00 +0000', b'21:02:00 +0000'),
                    stack().replace(b'com.apple.main-thread', b'worker'), b'\xff\xfe'):
            with self.subTest(raw=raw[:40]), self.assertRaises((ValueError, UnicodeError)):
                d.main_thread_text(raw, owner(), d.timestamp(STAMP))

    def test_only_main_frames_retained(self):
        text = d.main_thread_text(stack(), owner(), d.timestamp(STAMP))
        self.assertIn('updateFocus', text)
        self.assertNotIn('private worker', text); self.assertNotIn('SECRET_BINARY', text)
        self.assertNotIn('/Users/runner', text)

    def test_concatenated_process_headers_are_never_combined(self):
        foreign = b'Process: ForeignApp [999]\nPath: /private/other\nIdentifier: other.app\n'
        raw = stack().replace(b'Call graph:', foreign + b'Call graph:')
        with self.assertRaises(ValueError): d.main_thread_text(raw, owner(), d.timestamp(STAMP))
        raw = stack().replace(b'Call graph:', b'  ' + foreign.replace(b'\n', b'\n  ') + b'Call graph:')
        with self.assertRaises(ValueError): d.main_thread_text(raw, owner(), d.timestamp(STAMP))

    def test_owned_path_rejects_traversal_and_other_container_shapes(self):
        raw = stack().replace((DEVICE + '/data/').encode(), (DEVICE + '/../../OTHER-DEVICE/data/').encode())
        with self.assertRaises(ValueError): d.main_thread_text(raw, owner(), d.timestamp(STAMP))
        raw = stack().replace(b'/data/Containers/', b'/./data/Containers/')
        with self.assertRaises(ValueError): d.main_thread_text(raw, owner(), d.timestamp(STAMP))

    def test_hex_bearing_strings_paths_emails_and_trailing_text_are_not_frames(self):
        secret = b'    + 80 private diagnostic string 0x1238 /Users/private/file secret@example.com\n'
        extra = b'    + 80 validSymbol (in TouchColor) + 4 [0x1234] secret@example.com\n'
        raw = stack().replace(b'    + 80 main', secret + extra + b'    + 80 main')
        result = d.main_thread_text(raw, owner(), d.timestamp(STAMP))
        self.assertNotIn('secret', result); self.assertNotIn('/Users/', result)
        self.assertNotIn('diagnostic string', result)
        self.assertIn('updateFocus', result)

    def test_sigterm_after_export_unwinds_private_payload_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                reader = Reader(); report = {'phase': 'preflight-verified', 'calls': 2}
                budget = d.Budget(report, 0, reader, now=lambda: 1)
                def interrupted(*args):
                    try: os.kill(os.getpid(), signal.SIGTERM)
                    finally: os.kill(os.getpid(), signal.SIGTERM)
                with self.assertRaises(d.DiagnosticCancelled), d.cancellation_guard(), patch.object(d, 'main_thread_text', interrupted):
                    d.collect(budget, report, owner(), Path(directory))
                self.assertEqual(list(Path(directory).glob('watch-stack-*')), [])
                self.assertNotIn('main_thread', report)
            finally: os.chdir(old)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def cancellation_in_cleanup(self, capture_cancelled):
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            original_cleanup = tempfile.TemporaryDirectory.cleanup
            try:
                os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                reader = Reader(); report = {'phase': 'preflight-verified', 'calls': 2}
                def runner(command, **options):
                    answer = reader(command, **options)
                    if capture_cancelled and '--bounded-export' in command:
                        raise d.CaptureStopped('interrupted', False, signal.SIGTERM)
                    return answer
                budget = d.Budget(report, 0, runner, now=lambda: 1)
                def cleanup(folder):
                    if Path(folder.name).name.startswith('watch-stack-'):
                        os.kill(os.getpid(), signal.SIGTERM)
                    original_cleanup(folder)
                with self.assertRaises(d.DiagnosticCancelled), d.cancellation_guard(), patch.object(tempfile.TemporaryDirectory, 'cleanup', cleanup):
                    d.collect(budget, report, owner(), Path(directory))
                self.assertEqual(list(Path(directory).glob('watch-stack-*')), [])
                self.assertNotIn('main_thread', report)
                if capture_cancelled:
                    self.assertIs(report['diagnostic_cleanup_confirmed'], False)
                    self.assertEqual(report['cancelled_signal'], signal.SIGTERM)
            finally: os.chdir(old)

    def test_first_sigterm_during_cleanup_is_delivered_after_payload_deletion(self):
        self.cancellation_in_cleanup(False)

    def test_capture_cancellation_and_repeated_sigterm_during_cleanup_keep_failure(self):
        self.cancellation_in_cleanup(True)

    def exercise(self, values):
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                reader = Reader(values); report = {'phase': 'preflight-verified', 'calls': 2}
                budget = d.Budget(report, 0, reader, now=lambda: 1)
                d.collect(budget, report, owner(), Path(directory))
                return report, reader.calls
            finally: os.chdir(old)

    def test_single_identified_text_object_is_only_export(self):
        report, calls = self.exercise(objects())
        self.assertEqual(report['evidence'], 'owned app main-thread stack')
        exports = [c for c,o in calls if '--bounded-export' in c]
        self.assertEqual(len(exports), 1); self.assertEqual(exports[0][-2], 'payload-1')
        self.assertFalse(report['qualified'])
        self.assertLess(len(json.dumps(report).encode()), d.MAX_REPORT)

    def test_no_eligible_attachment_exports_nothing(self):
        report, calls = self.exercise(objects([]))
        self.assertEqual(report['evidence'], 'no app/PID/device-bound text stack in metadata')
        self.assertFalse(any('--bounded-export' in c for c,o in calls))

    def test_explicit_app_hang_without_metadata_pid_gets_one_bounded_header_check(self):
        node = attachment(name=val('App Hang'), filename=val('app-hang.txt'))
        candidates, inventory = d.attachment_candidates(objects([node])['summary-1'], owner())
        self.assertEqual(len(candidates), 1); self.assertFalse(inventory[0]['owner_metadata'])
        report, calls = self.exercise(objects([node]))
        self.assertEqual(report['evidence'], 'owned app main-thread stack')
        self.assertEqual(sum('--bounded-export' in c for c,o in calls), 1)

    def test_foreign_device_bundle_case_and_ambiguous_payload_rejected(self):
        for mode in ('device', 'bundle', 'case', 'multiple'):
            data = objects()
            if mode == 'device': data[None]['actions']['_values'][0]['runDestination']['targetDeviceRecord']['identifier'] = val(PHONE)
            if mode == 'bundle': data['tests-1']['summaries']['_values'][0]['targetName'] = val('OtherTests')
            if mode == 'case': data['tests-1']['summaries']['_values'][0]['tests']['_values'][0]['identifier'] = val('Other/test')
            if mode == 'multiple': data = objects([attachment(), attachment(payloadRef=ref('payload-2'))])
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.exercise(data)

    def test_file_reader_rejects_symlinks_hardlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'file'; p.write_bytes(b'abcd')
            self.assertEqual(d.read(p, 4), b'abcd')
            with self.assertRaises(ValueError): d.read(p, 3)
            link = Path(directory)/'link'; link.symlink_to(p)
            with self.assertRaises(ValueError): d.read(link, 4)
            hard = Path(directory)/'hard'; os.link(p, hard)
            with self.assertRaises(ValueError): d.read(p, 4)

    def test_export_child_applies_kernel_file_limit_and_exact_command(self):
        with tempfile.TemporaryDirectory(prefix='watch-stack-') as directory:
            folder = Path(directory); p = folder/'payload.txt'
            with (patch.dict(os.environ, RUNNER_TEMP=str(folder.parent)), patch.object(d.resource, 'setrlimit') as limit,
                  patch.object(d.os, 'execvp', side_effect=RuntimeError('exec inspected')) as execute):
                with self.assertRaisesRegex(RuntimeError, 'exec inspected'): d.bounded_export('payload-1', str(p))
                limit.assert_called_once_with(d.resource.RLIMIT_FSIZE, (d.MAX_TEXT, d.MAX_TEXT))
                self.assertEqual(execute.call_args.args[1][-4:], ['--type', 'file', '--output-path', str(p)])
                self.assertIn('--legacy', execute.call_args.args[1])

    def test_kernel_file_limit_bounds_real_local_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'limited'
            code = 'import resource,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(128,128));open(sys.argv[1],"wb",buffering=0).write(b"x"*129)'
            completed = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, timeout=5)
            self.assertLessEqual(path.stat().st_size, 128)

if __name__ == '__main__': unittest.main()
