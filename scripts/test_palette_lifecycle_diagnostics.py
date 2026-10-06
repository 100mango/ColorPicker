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


# The parent observes this exact file as producer readiness. Publish a complete
# synthetic owned PID, never the intermediate empty file from write_text.
PRODUCER_PID_PUBLICATION = ('Path("producer.pid.tmp").write_text(str(os.getpid()))\n'
                            'os.replace("producer.pid.tmp", "producer.pid")\n')

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
    def test_producer_pid_is_unobservable_until_complete_atomic_publication(self):
        # Exercise the exact producer statement with a deterministic observation
        # after open/truncation and before data write, then before rename.
        old = Path.cwd()
        observations = []
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                def observed_write(path, text):
                    self.assertEqual(path, Path('producer.pid.tmp'))
                    with path.open('w') as stream:
                        observations.append((Path('producer.pid').exists(), path.read_text()))
                        stream.write(text); stream.flush()
                        observations.append((Path('producer.pid').exists(), path.read_text()))
                    return len(text)
                with patch.object(Path, 'write_text', new=observed_write):
                    exec(PRODUCER_PID_PUBLICATION, {'Path': Path, 'os': os})
                self.assertEqual(observations, [(False, ''), (False, str(os.getpid()))])
                self.assertEqual(int(Path('producer.pid').read_text()), os.getpid())
                self.assertFalse(Path('producer.pid.tmp').exists())
            finally:
                os.chdir(old)

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
                                + PRODUCER_PID_PUBLICATION
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


class HostedGateSchedulingContracts(unittest.TestCase):
    """Portable source/state models; actual UIKit event ordering remains unrun."""
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.swift = (self.root/'TouchColorPhoneCompanion/Tests/PhonePaletteImportTests.swift').read_text()
        self.objc = (self.root/'ColorPickerTests/TCAdaptiveLayoutTests.m').read_text()

    def test_product_and_unrelated_close_methods_are_unchanged(self):
        import hashlib
        self.assertEqual(hashlib.sha256((self.root/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_bytes()).hexdigest(),
                         '32de83ef1894d1f2c73f1976a380f2295bf542eb99e16efd41e3ad84960248f1')
        self.assertEqual(hashlib.sha256(self.swift.split('    func testCancelledFileSelectionAndUnsupportedPasteRejectLatePriorRead()', 1)[1].encode()).hexdigest(),
                         'f3cb0b39635819efea36defdcc6b17f865e410c7f74edbdb9f940beff1f9430e')

    def test_real_swift_close_gate_body_stays_byte_exact(self):
        import hashlib
        body=self.swift.split('    func testActualCloseBarActionDismissesFullScreenErrorAndRejectsLateResult()',1)[1].split('    func testOriginalIOSImportIsPresentWithoutCompanion',1)[0]
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),'ff08fdc43c4cf6a1932591fade35e7e6ed2830bb307b1a0d4b0445e8857b8a4e')

    def test_controller_and_workspace_geometry_assertions_are_byte_exact(self):
        import hashlib
        locks = [('- (void)assertViewReadable:', '- (void)exerciseSize:', '2c68865a1a333b67b511b65f478d73e3f178449e550473ff91c62dacbd354a49'),
                 ('- (void)exerciseSize:', '- (void)test320x568', '732fee239a3ddcaa1f441e22005d517981b5e2749bb74b6402c071f47fea6219'),
                 ('        XCTAssertEqualWithAccuracy(navigation.view.bounds.size.width', '        check(controller);', '04644ce5c3ab3f367c068fe4d2b9c6b87c0933872d1a3c88cc796affc549e15a'),
                 ('            [workspace.view.window layoutIfNeeded];[workspace.view layoutIfNeeded];[canvas.view layoutIfNeeded];', '\n@end', 'ca845fe2838d998cb12d622616d2930b8a6de249e26c3bb79492b85ae88b1265')]
        for start,end,expected in locks:
            start_index=self.objc.index(start)
            actual=self.objc[start_index:self.objc.index(end,start_index)]
            if start == '- (void)exerciseSize:':
                staged = '''                NSArray *expectedSources=@[@"choosePhoto",@"takePhoto",@"liveColor",@"palette.import.open"];
                UIStackView *sourceButtons=[main valueForKey:@"sourceButtons"];
                XCTAssertEqualObjects([sourceButtons.arrangedSubviews valueForKey:@"accessibilityIdentifier"],expectedSources);
                XCTAssertNil(TCLayoutView(main.view,@"watch.inbox.open"));
                for (NSString *identifier in expectedSources) {'''
                self.assertEqual(actual.count(staged),1)
                actual=actual.replace(staged,'                for (NSString *identifier in @[@"choosePhoto",@"takePhoto",@"liveColor",@"palette.import.open",@"watch.inbox.open"]) {')
            self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),expected)

    def test_swift_gates_preserve_waiter_relative_three_seconds(self):
        self.assertEqual(self.swift.count('timeout: 3)'), 3)
        for phase in ('owner', 'presentation', 'dismissal'):
            self.assertIn('let '+phase+'Action = ProcessInfo.processInfo.systemUptime', self.swift)
            self.assertIn('let '+phase+'Returned = ProcessInfo.processInfo.systemUptime', self.swift)
            self.assertIn('let '+phase+'Wait = ProcessInfo.processInfo.systemUptime', self.swift)
            self.assertIn('let '+phase+'WaitReturned = ProcessInfo.processInfo.systemUptime', self.swift)
        self.assertNotIn('actionStarted + 3', self.swift)
        self.assertNotIn('dismissalDeadline', self.swift)
        self.assertNotIn('XCTNSPredicateExpectation', self.swift)

    def test_swift_dismissal_is_armed_before_real_action_and_state_before_clock(self):
        callback=self.swift.split('owner.onNextAppearance =', 1)[1].split('        defer { owner.onNextAppearance', 1)[0]
        self.assertLess(callback.index('owner.presentedViewController == nil'),callback.index('dismissalEvent = ProcessInfo'))
        self.assertIn('owner.viewIfLoaded?.window === window',callback)
        self.assertIn('if dismissalState { dismissed.fulfill() }',callback)
        self.assertLess(self.swift.index('owner.onNextAppearance ='),self.swift.index('UIApplication.shared.sendAction'))
        self.assertIn('let next = onNextAppearance; onNextAppearance = nil; next?()',self.swift)
        for kept in ('XCTAssertNil(owner.presentedViewController)', 'content.apply(.success(late), name: "late.json", token: token)',
                     'XCTAssertNil(content.selection, "Dismissal invalidates a previously issued import generation")',
                     'XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), original)'):
            self.assertIn(kept,self.swift)

    def test_unknown_swift_readiness_stops_dependent_actions_without_skip(self):
        for phase in ('owner','presentation','dismissal'):
            self.assertIn('guard '+phase+'Timely',self.swift)
            self.assertIn('$0 >= '+phase+'Action && $0 < '+phase+'Wait + 3',self.swift)
            self.assertIn('phase='+phase+' ',self.swift)
        self.assertLess(self.swift.index('guard presentationTimely'),self.swift.index('let token = content.begin()'))
        self.assertLess(self.swift.index('guard dismissalTimely'),self.swift.index('content.apply(.success(late)'))
        self.assertNotIn('XCTSkip',self.swift)

    def test_objc_owner_is_real_one_shot_event_and_geometry_is_guarded(self):
        self.assertIn('void (^observed)(void)=self.onAppearance; self.onAppearance=nil;',self.objc)
        self.assertIn('if (observed) observed();',self.objc)
        self.assertLess(self.objc.index('host.onAppearance=^'),self.objc.index('[window makeKeyAndVisible]'))
        self.assertNotIn('predicateWithFormat:@"appeared == true"',self.objc)
        self.assertIn('waitForExpectations:@[appeared] timeout:15',self.objc)
        self.assertLess(self.objc.index('if (waited!=XCTWaiterResultCompleted || !eventTimely || !observedAttached || !attached)'),self.objc.index('        check(controller);'))
        self.assertIn('- (void)setUp { [super setUp]; self.hostedGateUnproved=NO; }',self.objc)
        self.assertIn('if (self.hostedGateUnproved)',self.objc)

    def test_coordinator_callback_and_fallback_are_not_conflated(self):
        settle=self.objc.split('- (BOOL)settleWorkspace:',1)[1].split('- (void)testNativeWorkspace',1)[0]
        self.assertIn('if (qualifyingEvent && !fulfilled)',settle)
        self.assertNotIn('qualifyingEvent && attached',settle)
        self.assertLess(settle.index('fulfilled=YES;'),settle.index('[settled fulfill]'))
        self.assertEqual(settle.count('[settled fulfill]'),1)
        self.assertIn('observe(@"transition-completion",context.isCancelled ? 1 : 0,!context.isCancelled)',settle)
        self.assertIn('@"registration-rejected-main-turn" : @"no-coordinator-main-turn",-1,transition==nil',settle)
        self.assertIn('waitForExpectations:@[settled] timeout:15',settle)
        self.assertIn('closed=YES;',settle)
        self.assertIn('if (closed) return;',settle)
        self.assertEqual(self.objc.count('if (![self settleWorkspace:'),3)

    def test_attachment_observation_spends_only_original_phase_remaining_time(self):
        settle=self.objc.split('- (BOOL)settleWorkspace:',1)[1].split('- (void)testNativeWorkspace',1)[0]
        self.assertIn('NSTimeInterval phaseDeadline=waitStarted+15, responsivenessDeadline=waitStarted+3;',settle)
        self.assertIn('BOOL eventTimely=fulfilled && observed>=actionStarted && observed<phaseDeadline;',settle)
        self.assertIn('if (waited==XCTWaiterResultCompleted && eventTimely)',settle)
        self.assertIn('NSTimeInterval remaining=MAX(0,phaseDeadline-NSProcessInfo.processInfo.systemUptime);',settle)
        self.assertIn('if (remaining>0) attachmentResult=[XCTWaiter waitForExpectations:@[attachment] timeout:remaining];',settle)
        self.assertIn('BOOL attachmentTimely=observedAttached && attachmentObserved>=observed && attachmentObserved<phaseDeadline;',settle)
        predicate=settle.split('predicateWithBlock:',1)[1].split('}] object:expected]',1)[0]
        self.assertIn('workspace.viewIfLoaded.window!=nil && expected.viewIfLoaded.window==workspace.viewIfLoaded.window',predicate)
        self.assertLess(predicate.index('BOOL attached='),predicate.index('NSTimeInterval sampleTime='))
        self.assertIn('if (!attached) return NO;',predicate)
        self.assertIn('if (!observedAttached)',predicate)
        self.assertIn('observedAttached=YES; attachmentObserved=sampleTime;',predicate)
        self.assertIn('return sampleTime<phaseDeadline;',predicate)
        self.assertLess(settle.index('waitForExpectations:@[settled]'),settle.index('predicateWithBlock:'))
        self.assertLess(settle.index('waitForExpectations:@[attachment]'),settle.index('closed=YES;'))
        self.assertEqual(settle.count('timeout:15'),1)
        self.assertEqual(settle.count('phaseDeadline='),1)
        self.assertNotIn('actionStarted+3',settle)
        geometry=self.objc.split('- (void)testNativeWorkspace',1)[1]
        self.assertNotIn('waitForExpectations:',geometry)
        self.assertNotIn('XCTNSPredicateExpectation',geometry)

    @staticmethod
    def column_phase(events, samples, *, wait=102.0, action=100.0, current=True, completed=True, attachment_completed=True):
        # Portable ordering model, not UIKit execution. Callback state is logged
        # but cannot discard a genuine event; only later attachment proves readiness.
        observed=None; kind=None; count=0
        for event_kind, event_time, callback_attached, cancelled in events:
            qualifies=(event_kind=='transition-completion' and not cancelled) or event_kind=='no-coordinator-main-turn'
            if qualifies and observed is None:
                observed=event_time; kind=event_kind; count+=1
        deadline=wait+15
        event_timely=observed is not None and action<=observed<deadline
        attachment=None
        if event_timely and completed:
            attachment=next((at for at, attached in samples if attached and at>=max(wait,observed)),None)
        proved=completed and event_timely and attachment_completed and attachment is not None and attachment<deadline and current
        responsive=attachment is not None and attachment<wait+3
        return {'proved':proved,'responsive':responsive,'observed':observed,'kind':kind,'count':count,'attachment':attachment}

    def test_real_completion_before_attachment_is_retained(self):
        # Mini 03bf: noncancelled callback was detached at +56 ms. A later
        # within-deadline attachment sample is required; final state alone is not proof.
        events=[('transition-completion',100.056,False,False)]
        result=self.column_phase(events,[(100.060,False),(100.080,True)],wait=100.042)
        self.assertTrue(result['proved'])
        self.assertEqual((result['count'],result['observed'],result['attachment']),(1,100.056,100.080))
        self.assertFalse(self.column_phase(events,[],wait=100.042,current=True)['proved'])
        self.assertFalse(self.column_phase(events,[(100.080,True)],wait=100.042,current=False)['proved'])

    def test_attachment_at_or_after_functional_deadline_stays_unproved(self):
        events=[('transition-completion',116.8,False,False)]
        self.assertTrue(self.column_phase(events,[(116.999999,True)])['proved'])
        for at in (117.0,117.000001,131.799999):
            with self.subTest(attachment=at):
                self.assertFalse(self.column_phase(events,[(at,True)])['proved'])
        # A completed callback or waiter cannot reset the functional phase.
        for at in (117.0,117.000001):
            self.assertFalse(self.column_phase([('transition-completion',at,True,False)],[(at,True)])['proved'])
        self.assertTrue(self.column_phase([('transition-completion',101.0,False,False)],[(102.1,True)])['proved'])
        self.assertFalse(self.column_phase([('transition-completion',99.9,True,False)],[(102.1,True)])['proved'])

    def test_rejected_registration_requires_an_actual_noncancelled_callback(self):
        rejected=[('registration-rejected-main-turn',102.0,True,False)]
        result=self.column_phase(rejected,[(102.1,True)])
        self.assertEqual((result['proved'],result['count'],result['observed']),(False,0,None))
        result=self.column_phase(rejected+[('transition-completion',102.1,False,False)],[(102.2,True)])
        self.assertEqual((result['proved'],result['count'],result['kind']),(True,1,'transition-completion'))
        self.assertFalse(self.column_phase(rejected+[('transition-completion',102.1,True,True)],[(102.2,True)])['proved'])

    def test_duplicates_do_not_refill_or_retime_completion(self):
        events=[('transition-completion',102.1,False,False),('transition-completion',104.9,True,False)]
        result=self.column_phase(events,[(104.95,True)])
        self.assertEqual((result['proved'],result['count'],result['observed']),(True,1,102.1))
        self.assertFalse(self.column_phase(events,[(117.0,True)])['proved'])
        cancelled=[('transition-completion',102.0,True,True)]
        self.assertEqual(self.column_phase(cancelled,[(102.1,True)])['count'],0)
        self.assertEqual(self.column_phase(cancelled+events,[(104.95,True)])['count'],1)

    def test_no_coordinator_fallback_is_distinct_and_still_requires_attachment(self):
        events=[('no-coordinator-main-turn',102.1,False,False)]
        result=self.column_phase(events,[(102.2,True)])
        self.assertEqual((result['proved'],result['kind']),(True,'no-coordinator-main-turn'))
        for samples in ([],[(102.2,False)],[(117.0,True)]):
            self.assertFalse(self.column_phase(events,samples)['proved'])

    @staticmethod
    def owner_phase(event, *, wait=102.0, action=100.0, attached_at_event=True, current=True, completed=True):
        event_timely=event is not None and action<=event<wait+15
        proof=event if event is not None and attached_at_event and event>=action else None
        return {'proved':completed and event_timely and attached_at_event and current,
                'responsive':proof is not None and proof<wait+3}

    def test_owner_absolute_deadline_rejects_completed_without_timely_state_proof(self):
        owner=self.objc.split('- (void)withController:',1)[1].split('- (void)assertViewReadable:',1)[0]
        self.assertIn('NSTimeInterval phaseDeadline=waitStarted+15, responsivenessDeadline=waitStarted+3;',owner)
        self.assertIn('BOOL eventTimely=observed>=actionStarted && observed<phaseDeadline;',owner)
        self.assertIn('if (waited!=XCTWaiterResultCompleted || !eventTimely || !observedAttached || !attached)',owner)
        callback=owner.split('host.onAppearance=^{',1)[1].split('    };',1)[0]
        self.assertLess(callback.index('observedAttached='),callback.index('observed=NSProcessInfo'))
        self.assertIn('current.viewIfLoaded.window==window && window.rootViewController==current',callback)
        for event in (None,99.999999,117.0,117.000001):
            self.assertFalse(self.owner_phase(event,completed=True)['proved'])
        for options in ({'attached_at_event':False},{'current':False},{'completed':False}):
            self.assertFalse(self.owner_phase(113.0,**options)['proved'])
        self.assertTrue(self.owner_phase(116.999999)['proved'])
        self.assertTrue(self.owner_phase(101.0)['proved'])

    def test_compact_late_owner_is_functional_but_retains_three_second_miss(self):
        # Actual 03bf event clock, not the later GitHub log ingestion timestamp.
        result=self.owner_phase(1417.393361,wait=1405.772130,action=1405.686686)
        self.assertEqual(result,{'proved':True,'responsive':False})
        # Completed is insufficient for missing landscape/column observations.
        self.assertFalse(self.owner_phase(None,wait=1400.073622,action=1399.999130)['proved'])
        self.assertFalse(self.column_phase([],[],wait=1417.473238,action=1417.434346)['proved'])

    def test_owner_three_second_boundary_is_diagnostic_not_functional_failure(self):
        self.assertEqual(self.owner_phase(104.999999),{'proved':True,'responsive':True})
        for event in (105.0,105.000001,113.621231,116.999999):
            self.assertEqual(self.owner_phase(event),{'proved':True,'responsive':False})
        self.assertEqual(self.owner_phase(117.0),{'proved':False,'responsive':False})

    def test_column_three_second_miss_never_claims_responsiveness(self):
        events=[('transition-completion',102.1,False,False)]
        self.assertTrue(self.column_phase(events,[(104.999999,True)])['responsive'])
        for attachment in (105.0,105.000001,113.621231,116.999999):
            result=self.column_phase(events,[(attachment,True)])
            self.assertTrue(result['proved'])
            self.assertFalse(result['responsive'])
        late_event=[('transition-completion',113.0,False,False)]
        self.assertTrue(self.column_phase(late_event,[(116.9,True)])['proved'])
        self.assertFalse(self.column_phase(late_event,[(116.9,True)])['responsive'])

    def test_column_completed_results_do_not_replace_event_attachment_or_current_state(self):
        events=[('transition-completion',113.0,False,False)]
        for samples in ([],[(114.0,False)],[(117.0,True)]):
            self.assertFalse(self.column_phase(events,samples)['proved'])
        for options in ({'current':False},{'completed':False},{'attachment_completed':False}):
            self.assertFalse(self.column_phase(events,[(114.0,True)],**options)['proved'])
        # Callback at +14.8 leaves only .2 seconds, not another 15-second window.
        late=[('transition-completion',116.8,False,False)]
        self.assertFalse(self.column_phase(late,[(117.1,True)])['proved'])

    def test_owned_phase_logs_retain_proof_and_waiter_timings_and_three_second_miss(self):
        for start,end in (('- (void)withController:','- (void)assertViewReadable:'),
                          ('- (BOOL)settleWorkspace:','- (void)testNativeWorkspace')):
            body=self.objc.split(start,1)[1].split(end,1)[0]
            self.assertIn('BOOL responsive=proofObserved>=actionStarted && proofObserved<responsivenessDeadline;',body)
            self.assertIn('proofObserved>=0 ? proofObserved-actionStarted : -1',body)
            self.assertIn('proofObserved>=0 ? proofObserved-waitStarted : -1',body)
            self.assertIn('waitReturned-waitStarted',body)
            self.assertIn('responsive ? @"proved" : @"missed"',body)
            for field in ('HOSTED_UI_GATE','proof=%.6f','actionToProof=%.6f','waitToProof=%.6f',
                          'waitElapsed=%.6f','waitReturned=%.6f','responsivenessDeadline=%.6f','responsiveness3=%@'):
                self.assertIn(field,body)
            guard=body.split('if (waited!=XCTWaiterResultCompleted',1)[1].split('{',1)[0]
            self.assertNotIn('responsive',guard)

    def test_original_gate_bounds_and_reviewed_staged_swift_inventory(self):
        import hashlib
        self.assertEqual(self.objc.count('timeout:15'),2)
        self.assertEqual(self.objc.count('phaseDeadline=waitStarted+15'),2)
        self.assertEqual(self.objc.count('responsivenessDeadline=waitStarted+3'),2)
        self.assertEqual(hashlib.sha256(self.swift.encode()).hexdigest(),
                         '6a25635f308ebb13b0385fd971b5d1b133a50154624d70759d1f34618c29530b')
        managed=(self.root/'scripts/uikit_managed_tests.py').read_text()
        self.assertIn("'TouchColorTests': (600, 500, 53)",managed)
        self.assertIn("'-default-test-execution-time-allowance', '180', '-maximum-test-execution-time-allowance', '240'",managed)

    def test_attachment_failure_blocks_later_geometry_and_actions(self):
        body=self.objc.split('- (void)testNativeWorkspace',1)[1]
        self.assertIn('BOOL canvasAttached=canvas.viewIfLoaded.window!=nil && canvas.viewIfLoaded.window==workspace.viewIfLoaded.window;',body)
        self.assertIn('XCTAssertTrue(canvasAttached,@"Canvas must be attached before comparing column geometry")',body)
        self.assertIn('if (!canvasAttached)',body)
        self.assertLess(body.index('readiness=unproved'),body.index('NSLog(@"SPLIT_GEOMETRY'))

    def test_completed_wait_with_lost_attachment_records_explicit_failure(self):
        for start, end, guard in (
            ('- (void)withController:', '- (void)exerciseSize:', 'if (waited!=XCTWaiterResultCompleted || !eventTimely || !observedAttached || !attached)'),
            ('- (BOOL)settleWorkspace:', '- (void)testNativeWorkspace', 'if (waited!=XCTWaiterResultCompleted || !eventTimely || attachmentResult!=XCTWaiterResultCompleted || !attachmentTimely || !attached)'),
        ):
            body = self.objc.split(start, 1)[1].split(end, 1)[0]
            rejected = body.split(guard, 1)[1].split('return', 1)[0]
            self.assertIn('XCTFail(', rejected)
            self.assertLess(rejected.index('XCTFail('), rejected.index('hostedGateUnproved=YES'))
        # Completed alone cannot authorize dependent geometry after detachment.
        for waited, observed, attached in ((True, True, False), (True, False, True), (False, True, True)):
            unproved = not waited or not observed or not attached
            failures = int(unproved)
            dependent = not unproved
            self.assertEqual((failures, dependent), (1, False))

    def test_swift_late_events_do_not_advance_after_void_waiter(self):
        for phase in ('owner', 'presentation', 'dismissal'):
            line = ('let '+phase+'Timely = '+phase+'Event.map { $0 >= '+phase+'Action && $0 < '+phase+'Wait + 3 } ?? false')
            self.assertIn(line, self.swift)
            branch = self.swift.split('guard '+phase+'Timely', 1)[1].split('return', 1)[0]
            self.assertIn('XCTFail(', branch)
        def qualifies(event, action=100.0, wait=102.0, observed_state=True, current_state=True):
            return event is not None and action <= event < wait + 3 and observed_state and current_state
        # A real event before waiting is valid; no action-start +3 SLA is added.
        for event in (100.0, 101.0, 104.999999):
            self.assertTrue(qualifies(event))
        # Late observation, exact deadline and absence stay failed, even if state is now correct.
        for event in (None, 99.999999, 105.0, 105.000001, 110.0):
            self.assertFalse(qualifies(event))
        self.assertFalse(qualifies(104.0, observed_state=False))
        self.assertFalse(qualifies(104.0, current_state=False))

    def test_no_additional_retry_synthetic_lifecycle_or_animation_change(self):
        self.assertEqual(self.swift.count('owner.present('),1)
        self.assertEqual(self.swift.count('UIApplication.shared.sendAction('),1)
        self.assertEqual(self.objc.count('performWithoutAnimation:'),1)  # Existing workspace operation only.
        for text in (self.swift,self.objc):
            self.assertNotIn('sleep(',text)
            self.assertNotIn('setAnimationsEnabled',text)
            self.assertNotIn('timeout: 10',text)
            self.assertNotIn('timeout:10',text)


if __name__ == '__main__':
    unittest.main()
