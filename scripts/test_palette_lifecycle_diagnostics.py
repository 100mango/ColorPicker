import copy
import io
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import palette_lifecycle_diagnostics as d

TOKEN = '11111111-1111-4111-8111-111111111111'
PRESENTATION = '22222222-2222-4222-8222-222222222222'
IDENTITY = {'family': 'iPhoneLarge', 'udid': 'D2B249EB-2AC1-445A-BE5C-E80D6FBCCDF5',
            'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 10.0}
CASE = {'case': d.CASE, 'token': TOKEN, 'started': 100.125, 'epoch': 134.75,
        'pid': 32708, 'event': 'failed'}
SOURCE = {'sha': 'e' * 40, 'workflow_sha': 'e' * 40, 'files': {}}


# Synthetic format fixtures only, not captured target-runner capability proof.
HELP = {
    'spawn': b'Usage: simctl spawn <device> <path to executable> [<argv 1> <argv 2> ... <argv n>]\n',
    'show': (b'usage: log show [options] <archive>\n   or: log show [options]\n\noptions:\n'
             b'    --style <style>                 Output format (valid: syslog, json, compact)\n'
             b'    --start <date>                  Start timestamp\n'
             b'    --end <date>                    End timestamp\n'
             b'    --predicate <predicate>         Filter events using the given predicate\n'),
    'predicates': (b'valid predicate fields:\n    processID    (integer)\n'
                   b'    process      (string)\n    eventMessage (string)\n'),
}


def entry(event='appeared', sequence=1, epoch=120.0, presentation=PRESENTATION):
    value = dict(event=event, token=TOKEN, pid=32708, epoch=epoch,
                 presentation=presentation, sequence=sequence)
    value.update({key: False for key in d.BOOL_FIELDS})
    value.update({key: 'none' for key in d.TYPE_FIELDS})
    value['controller'] = 'PhonePaletteImportController'
    value['visible'] = True
    return {'processID': 32708, 'processImagePath': '/private/path/TouchColor.app/TouchColor',
            'eventMessage': d.PREFIX + json.dumps(value),
            'unretainedSecret': '/personal/path/not-for-output'}


def marker(value):
    return '2026-10-04 22:58:20.959303+0000 TouchColorUITests-Runner[29963:87375] PALETTE_CASE ' + json.dumps(value)


def ready_retainer():
    parser = d.CaseRetainer()
    parser.line("Test Case '" + d.XCTEST_CASE + "' started.")
    parser.line(marker(dict(CASE, event='started', pid=0, epoch=CASE['started'])))
    return parser


class RetentionTests(unittest.TestCase):
    def test_historical_failed_pid_survives_later_tests_and_relaunches(self):
        parser = ready_retainer()
        parser.line(marker(CASE))
        parser.line("Test Case '" + d.XCTEST_CASE + "' failed (34.330 seconds).")
        parser.line("Test Case '-[TouchColorUITests testLater]' started.")
        parser.line('Terminate com.mango.touchColor:32708')
        parser.line('Requesting snapshot of accessibility hierarchy for app with pid 55668')
        self.assertEqual(parser.result()['case']['pid'], 32708)

    def test_duplicate_mismatched_or_missing_metadata_never_falls_back(self):
        mutations = [dict(CASE, token='33333333-3333-4333-8333-333333333333'),
                     dict(CASE, started=99), dict(CASE, pid=0), dict(CASE, pid=True),
                     dict(CASE, epoch=400), dict(CASE, case='testOther')]
        for value in mutations:
            parser = ready_retainer()
            parser.line(marker(value))
            self.assertEqual(parser.result()['status'], 'rejected-case-metadata')
        parser = ready_retainer()
        parser.line(marker(CASE)); parser.line(marker(CASE))
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')
        parser = ready_retainer(); parser.line(marker(CASE))
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')

    def test_repeated_target_and_duplicate_json_keys_are_rejected(self):
        parser = ready_retainer()
        parser.line("Test Case '" + d.XCTEST_CASE + "' started.")
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')
        parser = ready_retainer()
        parser.line(marker(CASE).replace('"pid": 32708', '"pid": 32708, "pid": 33046'))
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')

    def test_another_runner_or_no_start_cannot_bind(self):
        parser = ready_retainer()
        parser.line(marker(CASE).replace('TouchColorUITests-Runner', 'UnrelatedApp'))
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')
        parser = d.CaseRetainer(); parser.line(marker(CASE))
        self.assertEqual(parser.result()['status'], 'rejected-case-metadata')

    def test_retainer_does_not_swallow_cancelled_source_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd(); os.chdir(directory)
            try:
                Path('build').mkdir()
                Path('build/iPhoneLarge-simulator.json').write_text(json.dumps(IDENTITY))
                stopped = d.CaptureStopped('interrupted-by-signal-15', True, signal.SIGTERM)
                with patch.object(d, 'source_identity', side_effect=stopped):
                    with self.assertRaises(d.CaptureStopped): d.retain('iPhoneLarge')
                self.assertFalse(Path('build/iPhoneLarge-palette-case.json').exists())
            finally:
                os.chdir(previous)

    def test_case_without_failure_remains_gap(self):
        parser = ready_retainer()
        parser.line("Test Case '" + d.XCTEST_CASE + "' passed (12.000 seconds).")
        self.assertEqual(parser.result(), {'status': 'no-target-failure'})

    def test_load_rejects_source_udid_time_stale_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd(); os.chdir(directory)
            try:
                Path('build').mkdir(); path = Path('build/iPhoneLarge-palette-case.json')
                value = {'status': 'bound-failure', 'identity': IDENTITY, 'source': SOURCE,
                         'case': CASE, 'capture_started': 99, 'capture_ended': 135}
                with patch.object(d, 'source_identity', return_value=SOURCE):
                    path.write_text(json.dumps(value))
                    self.assertEqual(d.load_case(IDENTITY)['case']['pid'], 32708)
                    changes = [('identity', dict(IDENTITY, udid=TOKEN)), ('source', {}),
                               ('status', 'no-target-failure'), ('capture_started', 101), ('capture_ended', 134)]
                    for key, replacement in changes:
                        path.write_text(json.dumps(dict(value, **{key: replacement})))
                        with self.assertRaises(ValueError): d.load_case(IDENTITY)
                    path.unlink(); (Path('build')/'external').write_text(json.dumps(value))
                    path.symlink_to('external')
                    with self.assertRaises(ValueError): d.load_case(IDENTITY)
            finally:
                os.chdir(previous)


class ReceiptTests(unittest.TestCase):
    def test_only_allowlisted_fields_are_retained_and_presentation_ids_stay_distinct(self):
        values = [entry('appeared', 1), entry('close-action-received', 2, 122),
                  entry('close-dismiss-completed', 3, 123),
                  entry('appeared', 1, 130, TOKEN)]
        rows = d.lifecycle_rows(json.dumps(values), CASE)
        self.assertEqual(len(rows), 4)
        self.assertNotEqual(rows[0]['presentation'], rows[-1]['presentation'])
        encoded = json.dumps(rows)
        self.assertNotIn('/private', encoded)
        self.assertNotIn('unretainedSecret', encoded)
        self.assertNotIn('processImagePath', encoded)

    def test_wrong_pid_app_token_time_or_field_type_rejects_whole_receipt(self):
        mutations = [('pid', 33046), ('token', PRESENTATION), ('epoch', 99), ('epoch', 135),
                     ('visible', 'true'), ('controller', 'OtherController'), ('event', 'invented'),
                     ('presentation', '../private'), ('sequence', True), ('presenter', '/private/path')]
        for key, replacement in mutations:
            record = entry(); value = json.loads(record['eventMessage'][len(d.PREFIX):])
            value[key] = replacement; record['eventMessage'] = d.PREFIX + json.dumps(value)
            with self.assertRaises((ValueError, TypeError)):
                d.lifecycle_rows(json.dumps([record]), CASE)
        for key, replacement in [('processID', 33046), ('processID', True),
                                 ('processImagePath', '/Unrelated.app/TouchColor'), ('eventMessage', '<private>')]:
            with self.assertRaises(ValueError):
                d.lifecycle_rows(json.dumps([dict(entry(), **{key: replacement})]), CASE)

    def test_duplicate_extra_missing_redacted_or_oversized_receipts_are_rejected(self):
        with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([entry(), entry()]), CASE)
        with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([entry()] * 25), CASE)
        for operation in ('extra', 'missing'):
            record = entry(); value = json.loads(record['eventMessage'][len(d.PREFIX):])
            if operation == 'extra': value['secret'] = 'do not emit'
            else: del value['token']
            record['eventMessage'] = d.PREFIX + json.dumps(value)
            with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([record]), CASE)

    def test_exact_server_side_pid_app_token_and_time_filter(self):
        command = d.log_command(IDENTITY, CASE)
        self.assertEqual(command[:6], ['xcrun', 'simctl', 'spawn', IDENTITY['udid'], 'log', 'show'])
        predicate = command[command.index('--predicate') + 1]
        for fragment in ['processID == 32708', 'process == "TouchColor"', 'BEGINSWITH "PALETTE_LIFECYCLE "', TOKEN]:
            self.assertIn(fragment, predicate)
        self.assertIn('1970-01-01 00:01:40+0000', command)
        self.assertIn('1970-01-01 00:02:15+0000', command)
        self.assertNotIn('--last', command)


class AcquisitionTests(unittest.TestCase):
    def value(self):
        return {'case': CASE, 'source': SOURCE}

    def runner(self, calls, output=None, help_ok=True):
        def run(command, **options):
            calls.append((command, options))
            raw = HELP[command[-1]] if 'help' in command else output or b'[]'
            if not help_ok: raw = b'unsupported'
            # Public help is permitted to use stderr; never print it.
            return subprocess.CompletedProcess(command, 64 if 'help' in command else 0,
                                               b'' if 'help' in command else raw, raw if 'help' in command else b'')
        return run

    def test_help_then_one_query_with_explicit_duration_and_acquisition_caps(self):
        calls = []
        with patch.object(d, 'load_case', return_value=self.value()):
            result = d.collect_lifecycle(IDENTITY, self.runner(calls, json.dumps([entry()]).encode()))
        self.assertEqual(result['status'], 'receipts-retained')
        self.assertEqual(len(calls), 4)
        self.assertEqual([options['cap'] for _, options in calls], [32768, 32768, 32768, 262144])
        self.assertEqual([options['seconds'] for _, options in calls], [3, 3, 3, 8])
        self.assertEqual(result['failed_pid'], 32708)

    def test_unavailable_help_or_case_never_queries_or_tries_alternate_flags(self):
        for value in (None, self.value()):
            calls = []
            with patch.object(d, 'load_case', return_value=value):
                result = d.collect_lifecycle(IDENTITY, self.runner(calls, help_ok=False))
            self.assertEqual(len(calls), 0 if value is None else 1)
            self.assertEqual(result['status'], 'unavailable')
            self.assertTrue(result['simulator_commands_completed'])

    def test_empty_logs_are_explicit_observation_gap_not_nondelivery(self):
        with patch.object(d, 'load_case', return_value=self.value()):
            result = d.collect_lifecycle(IDENTITY, self.runner([]))
        self.assertEqual(result['status'], 'observation-gap')
        self.assertEqual(result['reason'], 'absence-does-not-prove-nondelivery')

    def test_natural_nonzero_query_exit_is_gap_without_raw_stderr(self):
        def runner(command, **options):
            if 'help' in command: return self.runner([])(command, **options)
            return subprocess.CompletedProcess(command, 1, b'personal output', b'private /path')
        with patch.object(d, 'load_case', return_value=self.value()):
            result = d.collect_lifecycle(IDENTITY, runner)
        self.assertEqual(result['reason'], 'query-failed')
        self.assertNotIn('private', json.dumps(result))

    def test_timeout_or_output_limit_never_proves_simulator_exit(self):
        for reason in ('duration-limit', 'byte-limit'):
            def runner(*args, **kwargs): raise d.CaptureStopped(reason, True)
            with patch.object(d, 'load_case', return_value=self.value()):
                result = d.collect_lifecycle(IDENTITY, runner)
            self.assertFalse(result['simulator_commands_completed'])
            self.assertTrue(result['host_client_cleanup_confirmed'])

    def test_late_zero_help_and_query_exit_preserve_uncertainty(self):
        for late_at in (1, 2, 3, 4):
            clock = [0.0]
            calls = []
            normal = self.runner(calls)
            def runner(command, **options):
                result = normal(command, **options)
                if len(calls) == late_at: clock[0] += options['seconds'] + .01
                return result
            with patch.object(d, 'load_case', return_value=self.value()), patch.object(d.time, 'monotonic', side_effect=lambda: clock[0]):
                result = d.collect_lifecycle(IDENTITY, runner)
            self.assertFalse(result['simulator_commands_completed'])
            self.assertEqual(len(calls), late_at)

    def test_real_capture_stops_stdout_and_stderr_floods_at_cap(self):
        for fd in (1, 2):
            before = time.monotonic()
            with self.assertRaises(d.CaptureStopped) as raised:
                d.capture([sys.executable, '-c', f'import os;\nwhile True: os.write({fd},b"x"*4096)'], seconds=2, cap=8192)
            self.assertEqual(str(raised.exception), 'byte-limit')
            self.assertTrue(raised.exception.cleanup_confirmed)
            self.assertLess(time.monotonic() - before, 5)

    def test_real_capture_deadline_and_success(self):
        before = time.monotonic()
        with self.assertRaises(d.CaptureStopped) as raised:
            d.capture([sys.executable, '-c', 'import time;time.sleep(30)'], seconds=.1, cap=8192)
        self.assertEqual(str(raised.exception), 'duration-limit')
        self.assertLess(time.monotonic() - before, 5)
        result = d.capture([sys.executable, '-c', 'print("fixture")'], seconds=1, cap=128)
        self.assertEqual(result.stdout, b'fixture\n')
        self.assertEqual(result.returncode, 0)


class HelpGrammarTests(unittest.TestCase):
    def confirms(self, kind, raw, code=0):
        return d.confirmed_help(kind, subprocess.CompletedProcess([], code, raw, b''))

    def test_documented_record_shapes_and_stderr_are_recognized(self):
        for kind, raw in HELP.items():
            self.assertTrue(self.confirms(kind, raw))
            self.assertTrue(d.confirmed_help(kind, subprocess.CompletedProcess([], 64, b'', raw)))

    def test_process_id_is_not_the_process_key_and_bare_mentions_fail(self):
        self.assertFalse(self.confirms('predicates', HELP['predicates'].replace(b'    process      (string)\n', b'')))
        for kind, raw in [('spawn', b'spawn device'), ('show', b'--style json --start --end --predicate'),
                          ('predicates', b'processID process eventMessage')]:
            self.assertFalse(self.confirms(kind, raw))

    def test_unsupported_prose_vetoes_positive_records(self):
        for kind, raw in HELP.items():
            for warning in (b'unsupported: ', b'error: ', b'not supported: '):
                self.assertFalse(self.confirms(kind, warning + raw))
        self.assertFalse(self.confirms('show', b'unsupported: --style json --start --end --predicate'))

    def test_partial_wrong_section_duplicate_or_wrong_typed_keys_fail(self):
        for kind, raw in [
            ('show', HELP['show'].replace(b'options:', b'examples:')),
            ('show', HELP['show'].replace(b'usage: log show', b'usage: log stream')),
            ('show', HELP['show'].replace(b'json, ', b'')),
            ('show', HELP['show'] + b'    --start <date> Duplicate option\n'),
            ('predicates', HELP['predicates'].replace(b'valid predicate fields:', b'examples:')),
            ('predicates', HELP['predicates'].replace(b'processID    (integer)', b'processID    (string)')),
            ('predicates', HELP['predicates'] + b'    process (string)\n'),
            ('spawn', b'Usage: simctl spawn <device>'),
        ]:
            self.assertFalse(self.confirms(kind, raw))

    def test_missing_exact_process_key_stops_after_three_help_calls(self):
        calls = []
        def runner(command, **options):
            calls.append(command)
            raw = HELP[command[-1]]
            if command[-1] == 'predicates':
                raw = raw.replace(b'    process      (string)\n', b'')
            return subprocess.CompletedProcess(command, 0, raw, b'')
        with patch.object(d, 'load_case', return_value={'case': CASE, 'source': SOURCE}):
            result = d.collect_lifecycle(IDENTITY, runner)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['reason'], 'documented-route-not-confirmed')
        self.assertTrue(all('help' in command for command in calls))

    def test_rejected_help_never_starts_query_or_alternate_command(self):
        for bad_kind in HELP:
            calls = []
            def runner(command, **options):
                calls.append(command)
                kind = command[-1]
                return subprocess.CompletedProcess(command, 0, b'unsupported: ' + HELP[kind] if kind == bad_kind else HELP[kind], b'')
            with patch.object(d, 'load_case', return_value={'case': CASE, 'source': SOURCE}):
                result = d.collect_lifecycle(IDENTITY, runner)
            self.assertEqual(result['reason'], 'documented-route-not-confirmed')
            self.assertEqual(len(calls), ['spawn', 'show', 'predicates'].index(bad_kind) + 1)


class CancellationTests(unittest.TestCase):
    def probe(self, phase, first_signal, *, entry=False):
        """Own both driver and producer; never signal an inventory-derived PID."""
        import ctypes
        libc = None
        old_subreaper = None
        if sys.platform.startswith('linux'):
            # Safely reap a producer even if this regression ever kills its
            # driver. This affects only the test process and is restored below.
            libc = ctypes.CDLL(None, use_errno=True)
            old_subreaper = ctypes.c_int()
            self.assertEqual(libc.prctl(37, ctypes.byref(old_subreaper), 0, 0, 0), 0)
            self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            producer = root / 'producer.py'
            producer.write_text('import os,signal,time\nfrom pathlib import Path\n'
                                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                                'Path("producer.pid").write_text(str(os.getpid()))\n'
                                + ('while True: os.write(1,b"x"*4096)\n' if phase == 'bytes' else 'time.sleep(30)\n'))
            driver = root / 'driver.py'
            driver.write_text(r'''
import json,os,signal,sys,time
from pathlib import Path
import palette_lifecycle_diagnostics as d
phase=sys.argv[1]
original_stop=d.stop_group
cleanup_calls=[]
def owned_stop(process, **options):
    cleanup_calls.append(options)
    Path('cleanup.started').write_text(str(time.monotonic()))
    return original_stop(process, **options)
d.stop_group=owned_stop
if phase == 'spawn':
    original_popen=d.subprocess.Popen
    def spawn(*args, **kwargs):
        process=original_popen(*args, **kwargs)
        deadline=time.monotonic()+3
        while not Path('producer.pid').exists() and time.monotonic()<deadline: time.sleep(.01)
        os.kill(os.getpid(), signal.SIGTERM)
        return process
    d.subprocess.Popen=spawn
before={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT)}
started=time.monotonic()
try:
    d.capture([sys.executable,'producer.py'], seconds=.3 if phase == 'timeout' else 4, cap=8192)
    result={'unexpected_success':True}
except d.CaptureStopped as error:
    result={'reason':str(error),'cleanup_confirmed':error.cleanup_confirmed,
            'cancelled_signal':error.cancelled_signal}
result.update(elapsed=time.monotonic()-started, cleanup_calls=cleanup_calls,
              handlers_restored=all(signal.getsignal(number)==handler for number,handler in before.items()))
Path('result.json').write_text(json.dumps(result))
''')
            if entry:
                (root/'build').mkdir()
                (root/'build/iPhoneLarge-simulator.json').write_text(json.dumps(IDENTITY))
                tools = root/'tools'; tools.mkdir()
                executable = tools/'xcrun'
                executable.write_text('#!' + sys.executable + '\n' + producer.read_text())
                executable.chmod(0o755)
                driver.write_text(r'''
import json,os,signal,sys,time
from pathlib import Path
import palette_lifecycle_diagnostics as d
import uikit_runtime_diagnostics as runtime
result={}; cleanup_calls=[]; calls=[]
original_stop=d.stop_group
original_capture=d.capture
def owned_stop(process, **options):
    cleanup_calls.append(options)
    Path('cleanup.started').write_text(str(time.monotonic()))
    return original_stop(process, **options)
def observe_capture(command, **options):
    calls.append({'command':command,**options})
    try:
        return original_capture(command, **options)
    except d.CaptureStopped as error:
        result.update(reason=str(error),cleanup_confirmed=error.cleanup_confirmed,cancelled_signal=error.cancelled_signal)
        raise
d.stop_group=owned_stop;d.capture=observe_capture
before={number:signal.getsignal(number) for number in (signal.SIGTERM,signal.SIGINT)}
started=time.monotonic()
os.environ['GITHUB_OUTPUT']=str(Path('github-output').resolve())
sys.argv=['fixture','iPhoneLarge']
try:
    runtime.main()
    result['unexpected_success']=True
except SystemExit as error:
    result['entry_exit']=str(error)
result.update(elapsed=time.monotonic()-started,cleanup_calls=cleanup_calls,calls=calls,
              marker_preserved=Path('build/iPhoneLarge-runtime-command-uncertain').exists(),
              safe_output_absent=not Path('github-output').exists(),
              handlers_restored=all(signal.getsignal(number)==handler for number,handler in before.items()))
Path('result.json').write_text(json.dumps(result))
''')
            environment = dict(os.environ, PYTHONPATH=str(Path(d.__file__).parent))
            if entry:
                environment['PATH'] = str(root/'tools') + os.pathsep + environment['PATH']
            process = subprocess.Popen([sys.executable, str(driver), phase], cwd=root, env=environment,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            producer_pid = None
            try:
                deadline = time.monotonic() + 5
                while not (root/'producer.pid').exists() and time.monotonic() < deadline:
                    if process.poll() is not None: break
                    time.sleep(.01)
                self.assertTrue((root/'producer.pid').exists())
                producer_pid = int((root/'producer.pid').read_text())
                if phase == 'active':
                    process.send_signal(first_signal)
                while not (root/'cleanup.started').exists() and time.monotonic() < deadline:
                    if process.poll() is not None: break
                    time.sleep(.01)
                self.assertTrue((root/'cleanup.started').exists())
                if phase in ('timeout', 'bytes'):
                    process.send_signal(first_signal)
                # Repeat both cancellation signals during the TERM-ignoring
                # producer's finite cleanup phase. They must neither abort it
                # nor start another cleanup allowance.
                for number in (first_signal, signal.SIGINT, signal.SIGTERM, first_signal):
                    process.send_signal(number)
                    time.sleep(.035)
                output, errors = process.communicate(timeout=25 if entry else 6)
                self.assertEqual(process.returncode, 0, errors.decode(errors='replace'))
                result = json.loads((root/'result.json').read_text())
                self.assertNotIn('unexpected_success', result)
                self.assertTrue(result['cleanup_confirmed'], result)
                self.assertEqual(result['cancelled_signal'], int(first_signal), result)
                self.assertTrue(result['handlers_restored'], result)
                self.assertEqual(result['cleanup_calls'], [{'grace': 10 if entry else 2}])
                self.assertLess(result['elapsed'], 23.8 if entry else 4.8, result)
                if entry:
                    self.assertTrue(result['marker_preserved'])
                    self.assertTrue(result['safe_output_absent'])
                    self.assertEqual(len(result['calls']), 1)
                    self.assertEqual(result['calls'][0]['seconds'], 3)
                    self.assertEqual(result['calls'][0]['cleanup_grace'], 10)
                    self.assertEqual(result['calls'][0]['cap'], 65536)
                    self.assertEqual(result['calls'][0]['command'], ['xcrun','simctl','spawn',IDENTITY['udid'],'launchctl','list'])
                    self.assertIn(b'"simulator_commands_completed":false', output)
                with self.assertRaises(ProcessLookupError): os.kill(producer_pid, 0)
                with self.assertRaises(ProcessLookupError): os.killpg(producer_pid, 0)
                return result
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=2)
                if producer_pid is not None:
                    try: os.killpg(producer_pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    reap_deadline = time.monotonic() + 2
                    while time.monotonic() < reap_deadline:
                        try:
                            reaped, _ = os.waitpid(producer_pid, os.WNOHANG)
                        except ChildProcessError:
                            break
                        if reaped == producer_pid:
                            break
                        time.sleep(.01)
                    else:
                        self.fail('Supervisor could not reap its producer within two seconds')
                if libc is not None:
                    libc.prctl(36, old_subreaper.value, 0, 0, 0)

    def test_sigterm_active_and_repeated_during_cleanup(self):
        self.assertIn('interrupted-by-signal', self.probe('active', signal.SIGTERM)['reason'])

    def test_sigint_active_and_repeated_during_cleanup(self):
        self.assertIn('interrupted-by-signal', self.probe('active', signal.SIGINT)['reason'])

    def test_first_sigterm_during_timeout_cleanup(self):
        self.assertEqual(self.probe('timeout', signal.SIGTERM)['reason'], 'duration-limit')

    def test_first_sigint_during_timeout_cleanup(self):
        self.assertEqual(self.probe('timeout', signal.SIGINT)['reason'], 'duration-limit')

    def test_first_sigint_during_output_cap_cleanup(self):
        self.assertEqual(self.probe('bytes', signal.SIGINT)['reason'], 'byte-limit')

    def test_sigterm_between_spawn_and_owned_process_assignment(self):
        self.assertIn('interrupted-by-signal', self.probe('spawn', signal.SIGTERM)['reason'])

    def test_full_entry_sigterm_during_service_operation(self):
        self.probe('active', signal.SIGTERM, entry=True)

    def test_full_entry_sigint_during_service_operation(self):
        self.probe('active', signal.SIGINT, entry=True)

    def test_full_entry_first_sigterm_during_service_cleanup(self):
        self.probe('timeout', signal.SIGTERM, entry=True)

    def test_full_entry_first_sigint_during_service_cleanup(self):
        self.probe('timeout', signal.SIGINT, entry=True)

    def test_full_entry_first_sigterm_during_output_cap_cleanup(self):
        self.probe('bytes', signal.SIGTERM, entry=True)

    def test_full_entry_first_sigint_during_output_cap_cleanup(self):
        self.probe('bytes', signal.SIGINT, entry=True)

    def test_normal_capture_restores_callers_handlers(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
        result = d.capture([sys.executable, '-c', 'print("fixture")'], seconds=1, cap=128)
        self.assertEqual(result.returncode, 0)
        for number, handler in before.items():
            self.assertEqual(signal.getsignal(number), handler)


class SourceBoundaryTests(unittest.TestCase):
    def test_no_new_ax_pid_query_and_release_behavior_unchanged(self):
        root = Path(__file__).resolve().parent.parent
        app = (root/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_text()
        test = (root/'TouchColorUITests/TouchColorUITests.m').read_text()
        self.assertIn('NSString *failureDescription=self.app.debugDescription;', test)
        self.assertNotIn('self.app.processID', test)
        debug = app.split('#if DEBUG', 1)[1].split('#endif', 1)[0]
        self.assertIn('--ui-test-palette-lifecycle-token', debug)
        self.assertIn('private let lifecyclePresentation', debug)
        self.assertIn('dismiss(animated: true) {', app)
        self.assertNotIn('log config', (root/'scripts/palette_lifecycle_diagnostics.py').read_text())


if __name__ == '__main__':
    unittest.main()
