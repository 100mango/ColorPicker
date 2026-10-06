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

# Synthetic driver observer: acknowledge only after the actual capture handler
# returns. Different pending signals need not run in the parent's send order.
FIRST_SIGNAL_OBSERVER = r'''
original_signal = signal.signal
def observe_signal(number, handler):
    if getattr(handler, '__name__', None) == 'interrupted':
        def handled(signum, frame):
            handler(signum, frame)
            if not Path('signal.handled').exists():
                Path('signal.handled.tmp').write_text(str(signum))
                os.replace('signal.handled.tmp', 'signal.handled')
        return original_signal(number, handled)
    return original_signal(number, handler)
signal.signal = observe_signal
'''

TOKEN = '11111111-1111-4111-8111-111111111111'
PRESENTATION = '22222222-2222-4222-8222-222222222222'
IDENTITY = {'family': 'iPhoneLarge', 'udid': 'D2B249EB-2AC1-445A-BE5C-E80D6FBCCDF5',
            'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 10.0}
CASE = {'case': d.CASE, 'token': TOKEN, 'started': 100.125, 'epoch': 134.75,
        'pid': 32708, 'event': 'failed'}
SOURCE = {'sha': 'e' * 40, 'workflow_sha': 'e' * 40, 'files': {},
          'run': {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}}
CONTEXT = {'sha': 'e' * 40, 'workflow_sha': 'e' * 40, 'run_id': '123', 'run_attempt': '1',
           'completion_group': 'iphone-large', 'family': 'iPhoneLarge'}
INTERVAL = {'started': 99.0, 'ended': 500.0, 'source': CONTEXT, 'receipt_sha256': 'a' * 64, 'receipt_bytes': 1000}


def retained(cases=(CASE,)):
    return {'status': 'bound-failure', 'source': SOURCE, 'identity': IDENTITY,
            'capture_started': 98.0, 'capture_ended': 501.0, 'command_interval': INTERVAL,
            'cases': [{'case': name, 'status': 'bound-failure', 'failure': case}
                      if (case := next((item for item in cases if item['case'] == name), None))
                      else {'case': name, 'status': 'no-target-failure'} for name in d.CASES]}


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
        self.assertEqual(parser.result()['cases'][0]['failure']['pid'], 32708)

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
        self.assertEqual(parser.result()['status'], 'no-target-failure')
        self.assertEqual(parser.result()['cases'][0]['status'], 'no-target-failure')

    def test_load_rejects_source_udid_time_stale_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd(); os.chdir(directory)
            try:
                Path('build').mkdir(); path = Path('build/iPhoneLarge-palette-case.json')
                value = retained()
                with patch.object(d, 'source_identity', return_value=SOURCE), patch.object(d, 'command_interval', return_value=INTERVAL):
                    path.write_text(json.dumps(value))
                    self.assertEqual(d.load_case(IDENTITY)['cases'][0]['failure']['pid'], 32708)
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


class RejectionReasonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = Path.cwd(); os.chdir(self.directory.name)
        Path('build').mkdir()
        self.path = Path('build/iPhoneLarge-palette-case.json')
        self.identity_path = Path('build/iPhoneLarge-simulator.json')
        self.identity_path.write_text(json.dumps(IDENTITY))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        os.chdir(self.previous); self.directory.cleanup()

    def retain(self, text='', source=SOURCE):
        options = {'side_effect': source} if isinstance(source, BaseException) else {'return_value': source}
        with patch.object(d, 'source_identity', **options), \
                patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(text.encode()))), \
                patch.object(sys, 'stdout', io.TextIOWrapper(io.BytesIO())):
            d.retain('iPhoneLarge')
        raw = self.path.read_bytes()
        self.assertLessEqual(len(raw), 12 * 1024)
        self.assertNotIn(b'SENTINEL_PRIVATE', raw)
        return json.loads(raw)

    def collect(self, value=None, source=SOURCE):
        if value is not None:
            self.path.write_text(json.dumps(value))
        calls = []
        def runner(command, **options):
            calls.append(command)
            raise AssertionError('Rejection must not run help/query')
        options = {'side_effect': source} if isinstance(source, BaseException) else {'return_value': source}
        with patch.object(d, 'source_identity', **options), patch.object(d, 'command_interval') as interval:
            result = d.collect_lifecycle(IDENTITY, runner)
        self.assertEqual(calls, [])
        interval.assert_not_called()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['events'], [])
        self.assertNotIn('query_argv', result)
        self.assertNotIn('SENTINEL_PRIVATE', json.dumps(result))
        return result

    def rejected(self, reason='retainer-case-parse-rejected'):
        return {'status': 'rejected-case-metadata', 'rejection_reason': reason,
                'identity': IDENTITY, 'source': SOURCE, 'capture_started': 98., 'capture_ended': 501.}

    def test_each_retainer_stage_emits_only_a_closed_reason_and_consumer_checks_ownership(self):
        started = "Test Case '" + d.XCTEST_CASE + "' started.\n"
        fixtures = [
            ('retainer-stale-metadata', '', SOURCE, 'case-identity-unverified'),
            ('retainer-identity-rejected', '', SOURCE, 'case-identity-unverified'),
            ('retainer-source-rejected', '', ValueError('SENTINEL_PRIVATE'), 'case-source-unverified'),
            ('retainer-source-exit-unconfirmed', '', d.CaptureStopped('SENTINEL_PRIVATE', False), 'case-source-unverified'),
            ('retainer-case-parse-rejected', marker(CASE) + '\n', SOURCE, 'retainer-case-parse-rejected'),
            ('retainer-case-incomplete', started, SOURCE, 'retainer-case-incomplete'),
        ]
        self.assertEqual({row[0] for row in fixtures}, d.RETENTION_REJECTIONS)
        for reason, text, source, consumer_reason in fixtures:
            with self.subTest(reason=reason):
                self.path.unlink(missing_ok=True)
                self.identity_path.write_text(json.dumps(IDENTITY))
                if reason == 'retainer-stale-metadata': self.path.write_text('{}')
                if reason == 'retainer-identity-rejected': self.identity_path.write_text('{"SENTINEL_PRIVATE":true}')
                value = self.retain(text, source)
                self.assertEqual(value['status'], 'rejected-case-metadata')
                self.assertEqual(value['rejection_reason'], reason)
                result = self.collect()
                self.assertEqual(result['reason'], consumer_reason)
                self.assertTrue(result['simulator_commands_completed'])
                if reason in d.UNVERIFIED_SOURCE_REJECTIONS | d.UNVERIFIED_IDENTITY_REJECTIONS:
                    self.assertEqual(result['reported_unverified_retention_reason'], reason)
                else:
                    self.assertNotIn('reported_unverified_retention_reason', result)

    def test_historical_absence_stays_unknown_and_other_existing_fallbacks_stay_closed(self):
        value = self.rejected(); del value['rejection_reason']
        self.assertEqual(self.collect(value)['reason'], 'retainer-rejection-unknown')
        self.path.unlink()
        self.assertEqual(self.collect()['reason'], 'no-current-case-metadata')
        self.path.write_text('{')
        self.assertEqual(self.collect()['reason'], 'invalid-or-unavailable-evidence')
        self.assertEqual(self.collect(self.rejected(), ValueError('SENTINEL_PRIVATE'))['reason'],
                         'invalid-or-unavailable-evidence')
        passed = dict(retained(), status='no-target-failure')
        self.assertEqual(self.collect(passed)['reason'], 'invalid-or-unavailable-evidence')

    def test_unknown_malformed_reasons_and_forged_downgrades_are_rejected(self):
        for reason in (None, True, 7, [], {}, 'SENTINEL_PRIVATE', 'retainer-rejection-unknown'):
            with self.subTest(reason=reason):
                self.assertEqual(self.collect(self.rejected(reason))['reason'], 'invalid-retention-rejection')
        # Reasons cannot decorate a success/failure envelope, erase its failed
        # row with a status edit, or claim a source-stage failure after binding.
        values = [dict(retained(), rejection_reason='retainer-case-parse-rejected'),
                  dict(retained(), status='rejected-case-metadata', rejection_reason='retainer-case-parse-rejected'),
                  dict(self.rejected(), cases=[]), dict(self.rejected(), extra='SENTINEL_PRIVATE')]
        values += [self.rejected(reason) for reason in d.RETENTION_REJECTIONS
                   if reason not in {'retainer-case-parse-rejected', 'retainer-case-incomplete'}]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(self.collect(value)['reason'], 'invalid-retention-rejection')

    def test_owned_reason_requires_exact_source_identity_and_current_capture_interval(self):
        for key, replacement, expected in (
                ('identity', None, 'case-identity-unverified'),
                ('identity', dict(IDENTITY, udid=TOKEN), 'case-identity-unverified'),
                ('source', None, 'case-source-unverified'),
                ('source', dict(SOURCE, sha='b' * 40), 'case-source-unverified'),
                ('source', dict(SOURCE, files={'changed': 'b' * 64}), 'case-source-unverified'),
                ('source', dict(SOURCE, run={'GITHUB_RUN_ID': '124', 'GITHUB_RUN_ATTEMPT': '1'}), 'case-source-unverified'),
                ('capture_started', 0., 'invalid-or-unavailable-evidence'),
                ('capture_ended', 97., 'invalid-or-unavailable-evidence'),
                ('capture_ended', float('inf'), 'invalid-or-unavailable-evidence')):
            with self.subTest(key=key, replacement=replacement):
                self.assertEqual(self.collect(dict(self.rejected(), **{key: replacement}))['reason'], expected)

    def test_failed_invalid_then_passed_normal_retains_original_failed_case_without_reason(self):
        second = dict(CASE, case=d.CASES[1], token='33333333-3333-4333-8333-333333333333',
                      event='started', started=375., epoch=375., pid=0)
        parser = ready_retainer()
        parser.line(marker(CASE)); parser.line("Test Case '" + d.XCTEST_CASE + "' failed (34.330 seconds).")
        parser.line("Test Case '" + d.XCTEST_CASES[d.CASES[1]] + "' started.")
        parser.line(marker(second)); parser.line("Test Case '" + d.XCTEST_CASES[d.CASES[1]] + "' passed (25.000 seconds).")
        value = parser.result()
        self.assertEqual(value, {'status': 'bound-failure', 'cases': [
            {'case': CASE['case'], 'status': 'bound-failure', 'failure': CASE},
            {'case': d.CASES[1], 'status': 'no-target-failure'}]})
        value.update(identity=IDENTITY, source=SOURCE, capture_started=98., capture_ended=501.)
        self.path.write_text(json.dumps(value))
        with patch.object(d, 'source_identity', return_value=SOURCE), patch.object(d, 'command_interval', return_value=INTERVAL):
            self.assertEqual(d.failed_cases(d.load_case(IDENTITY)), [CASE])

    def test_cancellation_and_unconfirmed_capture_do_not_become_reason_only_success(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            for cleanup in (False, True):
                with self.subTest(signal=signum, cleanup=cleanup):
                    error = d.CaptureStopped('SENTINEL_PRIVATE', cleanup, signum)
                    with self.assertRaises(d.CaptureStopped) as raised:
                        self.retain(source=error)
                    self.assertIs(raised.exception, error)
                    self.assertFalse(self.path.exists())
                    result = self.collect(self.rejected(), source=error)
                    self.assertEqual(result['reason'], 'command-exit-unconfirmed')
                    self.assertFalse(result['simulator_commands_completed'])
                    self.assertIs(result['host_client_cleanup_confirmed'], cleanup)
                    self.path.unlink()

    def test_verified_rejection_reaches_existing_runtime_frame_without_new_capture(self):
        import uikit_runtime_diagnostics as runtime
        self.path.write_text(json.dumps(self.rejected()))
        with patch.object(d, 'source_identity', return_value=SOURCE), \
                patch.object(runtime, 'owned_crashes', return_value={'reports': []}), \
                patch.object(runtime, 'service_runner', side_effect=AssertionError('No service capture')):
            result = runtime.collect(IDENTITY, Path(self.directory.name))
        frame = runtime.framed_record(result)
        self.assertLessEqual(len(frame.encode()) + 128, runtime.MAX_OUTPUT_BYTES)
        emitted = json.loads(frame[len(runtime.FRAME):])
        self.assertEqual(emitted['palette_lifecycle'], {
            'status': 'unavailable', 'reason': 'retainer-case-parse-rejected',
            'simulator_commands_completed': True, 'events': []})
        self.assertTrue(emitted['simulator_commands_completed'])

    def test_null_source_hint_preserves_source_checks_and_unavailable_runtime_frame(self):
        import uikit_runtime_diagnostics as runtime
        for path in d.SOURCES:
            target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('source fixture')
        for reason in d.UNVERIFIED_SOURCE_REJECTIONS:
            with self.subTest(reason=reason):
                self.path.write_text(json.dumps(dict(self.rejected(reason), source=None)))
                calls = []
                def runner(command, **options):
                    calls.append((command, options))
                    self.assertEqual(command[0], 'git')
                    return subprocess.CompletedProcess(command, 0, SOURCE['sha'].encode()
                        if command == ['git', 'rev-parse', 'HEAD'] else b'', b'')
                with patch.dict(os.environ, {'GITHUB_SHA': SOURCE['sha'], 'GITHUB_WORKFLOW_SHA': SOURCE['sha'],
                        **SOURCE['run']}), patch.object(d, 'command_interval', side_effect=AssertionError('No command proof')):
                    result = d.collect_lifecycle(IDENTITY, runner)
                self.assertEqual([row[0] for row in calls], [
                    ['git', 'rev-parse', 'HEAD'], ['git', 'diff', '--quiet', 'HEAD', '--']])
                self.assertEqual([row[1] for row in calls], [{'seconds': 3, 'cap': 4096}] * 2)
                self.assertEqual(result, {'status': 'unavailable', 'events': [], 'simulator_commands_completed': True,
                    'reason': 'case-source-unverified', 'reported_unverified_retention_reason': reason})
                with patch.object(d, 'collect_lifecycle', return_value=result), \
                        patch.object(runtime, 'owned_crashes', return_value={'reports': []}):
                    framed = runtime.framed_record(runtime.collect(IDENTITY, Path(self.directory.name)))
                self.assertEqual(json.loads(framed[len(runtime.FRAME):])['palette_lifecycle'], result)
                self.assertLessEqual(len(framed.encode()) + 128, runtime.MAX_OUTPUT_BYTES)
                self.assertEqual(d.MAX_RECORD, 12 * 1024)

    def test_unverified_hint_drops_foreign_malformed_historical_and_forged_records(self):
        base = dict(self.rejected('retainer-source-rejected'), source=None)
        changes = [
            {'identity': None}, {'identity': dict(IDENTITY, udid=TOKEN)},
            {'source': SOURCE}, {'source': dict(SOURCE, sha='b' * 40)}, {'source': {}},
            {'status': 'bound-failure'}, {'cases': []}, {'extra': 'SENTINEL_PRIVATE'},
            {'capture_started': 0.}, {'capture_started': True}, {'capture_ended': 97.},
            {'capture_ended': time.time() + 3600}, {'capture_ended': float('inf')},
        ] + [{'rejection_reason': reason} for reason in (
            None, [], {}, True, 'SENTINEL_PRIVATE', 'retainer-rejection-unknown',
            'retainer-case-incomplete', 'retainer-case-parse-rejected', 'retainer-identity-rejected', 'retainer-stale-metadata')]
        values = [dict(base, **change) for change in changes]
        values += [{key: value for key, value in base.items() if key != missing}
                   for missing in ('source', 'identity', 'capture_started', 'capture_ended', 'rejection_reason')]
        for value in values:
            with self.subTest(value=value):
                self.assertNotIn('reported_unverified_retention_reason', self.collect(value))
        for source in (ValueError('SENTINEL_PRIVATE'), d.CaptureStopped('SENTINEL_PRIVATE', False, signal.SIGTERM)):
            result = self.collect(base, source=source)
            self.assertNotIn('reported_unverified_retention_reason', result)
            if isinstance(source, d.CaptureStopped):
                self.assertFalse(result['simulator_commands_completed'])
                self.assertEqual(result['reason'], 'command-exit-unconfirmed')

    def test_null_identity_hints_keep_identity_rejected_without_source_or_simulator_query(self):
        import uikit_runtime_diagnostics as runtime
        for reason in d.UNVERIFIED_IDENTITY_REJECTIONS:
            with self.subTest(reason=reason):
                value = dict(self.rejected(reason), identity=None, source=None)
                self.path.write_text(json.dumps(value))
                with patch.object(d, 'source_identity', side_effect=AssertionError('Unowned source check')) as source, \
                        patch.object(d, 'command_interval', side_effect=AssertionError('No command proof')):
                    result = d.collect_lifecycle(IDENTITY, runner=lambda *a, **k: self.fail('No query'))
                source.assert_not_called()
                self.assertEqual(result, {'status': 'unavailable', 'events': [], 'simulator_commands_completed': True,
                    'reason': 'case-identity-unverified', 'reported_unverified_retention_reason': reason})
                with patch.object(d, 'collect_lifecycle', return_value=result), \
                        patch.object(runtime, 'owned_crashes', return_value={'reports': []}):
                    framed = runtime.framed_record(runtime.collect(IDENTITY, Path(self.directory.name)))
                self.assertEqual(json.loads(framed[len(runtime.FRAME):])['palette_lifecycle'], result)
                self.assertLessEqual(len(framed.encode()) + 128, runtime.MAX_OUTPUT_BYTES)

    def test_null_identity_hint_rejects_inconsistent_stages_bindings_envelopes_and_times(self):
        for reason in d.UNVERIFIED_IDENTITY_REJECTIONS:
            base = dict(self.rejected(reason), identity=None, source=None)
            changes = [
                {'identity': IDENTITY}, {'identity': dict(IDENTITY, udid=TOKEN)}, {'identity': {}},
                {'source': SOURCE}, {'source': dict(SOURCE, sha='b' * 40)}, {'source': {}},
                {'status': 'bound-failure'}, {'cases': []}, {'extra': 'SENTINEL_PRIVATE'},
                {'capture_started': 0.}, {'capture_started': True}, {'capture_ended': 97.},
                {'capture_ended': time.time() + 3600}, {'capture_ended': float('inf')},
            ] + [{'rejection_reason': label} for label in (
                None, [], {}, True, 'SENTINEL_PRIVATE', 'retainer-rejection-unknown',
                'retainer-case-incomplete', 'retainer-case-parse-rejected',
                'retainer-source-rejected', 'retainer-source-exit-unconfirmed')]
            values = [dict(base, **change) for change in changes]
            values += [{key: item for key, item in base.items() if key != missing}
                       for missing in ('source', 'identity', 'capture_started', 'capture_ended', 'rejection_reason')]
            for value in values:
                with self.subTest(reason=reason, value=value):
                    self.assertNotIn('reported_unverified_retention_reason', self.collect(value))


class ReceiptTests(unittest.TestCase):
    def test_only_allowlisted_fields_are_retained_and_presentation_ids_stay_distinct(self):
        values = [entry('appeared', 1), entry('close-action-received', 2, 122),
                  entry('close-dismiss-completed', 3, 123),
                  entry('appeared', 1, 130, TOKEN)]
        rows = d.lifecycle_rows(json.dumps(values), [CASE])
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
                d.lifecycle_rows(json.dumps([record]), [CASE])
        for key, replacement in [('processID', 33046), ('processID', True),
                                 ('processImagePath', '/Unrelated.app/TouchColor'), ('eventMessage', '<private>')]:
            with self.assertRaises(ValueError):
                d.lifecycle_rows(json.dumps([dict(entry(), **{key: replacement})]), [CASE])

    def test_duplicate_extra_missing_redacted_or_oversized_receipts_are_rejected(self):
        with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([entry(), entry()]), [CASE])
        with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([entry()] * 25), [CASE])
        for operation in ('extra', 'missing'):
            record = entry(); value = json.loads(record['eventMessage'][len(d.PREFIX):])
            if operation == 'extra': value['secret'] = 'do not emit'
            else: del value['token']
            record['eventMessage'] = d.PREFIX + json.dumps(value)
            with self.assertRaises(ValueError): d.lifecycle_rows(json.dumps([record]), [CASE])

    def test_exact_server_side_pid_app_token_and_time_filter(self):
        command = d.log_command(IDENTITY, [CASE])
        self.assertEqual(command[:6], ['xcrun', 'simctl', 'spawn', IDENTITY['udid'], 'log', 'show'])
        predicate = command[command.index('--predicate') + 1]
        for fragment in ['processID == 32708', 'process == "TouchColor"', 'BEGINSWITH "PALETTE_LIFECYCLE "', TOKEN]:
            self.assertIn(fragment, predicate)
        self.assertIn('1970-01-01 00:01:40+0000', command)
        self.assertIn('1970-01-01 00:02:15+0000', command)
        self.assertNotIn('--last', command)


class AcquisitionTests(unittest.TestCase):
    def value(self):
        return retained()

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
        self.assertEqual(result['cases'][0]['pid'], 32708)

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

    def test_unknown_complete_help_layout_uses_only_reviewed_fixed_query(self):
        calls = []
        def runner(command, **options):
            calls.append(command)
            raw = HELP[command[-1]] if 'help' in command else b'[]'
            if command[-1] == 'predicates':
                raw = raw.replace(b'    process      (string)\n', b'')
            return subprocess.CompletedProcess(command, 0, raw, b'')
        with patch.object(d, 'load_case', return_value=retained()):
            result = d.collect_lifecycle(IDENTITY, runner)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['query_route'], 'fixed-query-compatibility')
        self.assertEqual(calls[-1], d.log_command(IDENTITY, [CASE]))

    def test_rejected_help_never_starts_query_or_alternate_command(self):
        for bad_kind in HELP:
            calls = []
            def runner(command, **options):
                calls.append(command)
                kind = command[-1]
                return subprocess.CompletedProcess(command, 0, b'unsupported: ' + HELP[kind] if kind == bad_kind else HELP[kind], b'')
            with patch.object(d, 'load_case', return_value=retained()):
                result = d.collect_lifecycle(IDENTITY, runner)
            self.assertEqual(result['reason'], 'help-command-error')
            self.assertEqual(len(calls), ['spawn', 'show', 'predicates'].index(bad_kind) + 1)


class TwoCaseObservationTests(unittest.TestCase):
    def setUp(self):
        self.second = dict(CASE, case=d.CASES[1], token='33333333-3333-4333-8333-333333333333',
                           pid=33046, started=375.0, epoch=409.349)
        self.value = retained((CASE, self.second))

    def run_collection(self, value=None, output=b'[]', helper=None):
        import contextlib
        calls, frames = [], io.StringIO()
        def runner(command, **options):
            calls.append((command, options))
            if helper is not None and 'help' in command:
                return helper(command, options)
            return subprocess.CompletedProcess(command, 0, HELP[command[-1]] if 'help' in command else output, b'')
        with patch.object(d, 'load_case', return_value=value or self.value), contextlib.redirect_stdout(frames):
            result = d.collect_lifecycle(IDENTITY, runner)
        rows = [json.loads(line[len(d.HELP_FRAME):]) for line in frames.getvalue().splitlines()]
        return result, calls, rows, frames.getvalue()

    def record_for(self, case, event='accept-enter', sequence=1, **changes):
        record = entry(event, sequence, case['started'] + 1,
                       PRESENTATION if case == CASE else '44444444-4444-4444-8444-444444444444')
        value = json.loads(record['eventMessage'][len(d.PREFIX):])
        value.update(token=case['token'], pid=case['pid']); value.update(changes)
        record.update(processID=case['pid'], eventMessage=d.PREFIX + json.dumps(value))
        return record

    def test_two_cases_retain_independent_observed_pid_token_and_outcome(self):
        parser = d.CaseRetainer()
        for case in (CASE, self.second):
            name = d.XCTEST_CASES[case['case']]
            parser.line("Test Case '" + name + "' started.")
            parser.line(marker(dict(case, event='started', pid=0, epoch=case['started'])))
            parser.line(marker(case))
            parser.line("Test Case '" + name + "' failed (34.330 seconds).")
        self.assertEqual(d.failed_cases(parser.result()), [CASE, self.second])
        self.assertEqual(len({row['token'] for row in d.failed_cases(parser.result())}), 2)

    def test_crossed_case_token_pid_or_repeated_case_fails_closed(self):
        for case in (dict(self.second, case=CASE['case']), dict(self.second, token=CASE['token'])):
            parser = ready_retainer()
            parser.line(marker(CASE)); parser.line("Test Case '" + d.XCTEST_CASE + "' failed (34.330 seconds).")
            parser.line("Test Case '" + d.XCTEST_CASES[d.CASES[1]] + "' started.")
            parser.line(marker(dict(case, event='started', pid=0, epoch=case['started'])))
            self.assertEqual(parser.result()['status'], 'rejected-case-metadata')
        for changes in ({'token': CASE['token']}, {'pid': CASE['pid']}, {'epoch': 200.0}, {'epoch': CASE['started'] + 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                d.lifecycle_rows(json.dumps([self.record_for(self.second, **changes)]), [CASE, self.second])

    def test_one_query_uses_closed_or_branches_and_explicit_broader_union(self):
        records = [self.record_for(CASE), self.record_for(self.second)]
        result, calls, _, _ = self.run_collection(output=json.dumps(records).encode())
        self.assertEqual(len(calls), 4)
        self.assertEqual([item[1]['cap'] for item in calls], [32768, 32768, 32768, 262144])
        self.assertEqual(calls[-1][0], d.log_command(IDENTITY, [CASE, self.second]))
        predicate = calls[-1][0][-1]
        self.assertEqual(predicate.count(' OR '), 1)
        self.assertIn('(processID == 32708 AND eventMessage CONTAINS "' + CASE['token'] + '")', predicate)
        self.assertIn('(processID == 33046 AND eventMessage CONTAINS "' + self.second['token'] + '")', predicate)
        self.assertAlmostEqual(result['query_window']['case_union_ended'] - result['query_window']['case_union_started'], 309.224)
        self.assertEqual(result['query_window']['query_ended'] - result['query_window']['query_started'], 310)
        self.assertEqual(result['query_argv'], calls[-1][0])
        self.assertEqual([event['case_index'] for event in result['events']], [0, 1])
        self.assertNotIn('token', result['events'][0]); self.assertNotIn('pid', result['events'][0])
        self.assertNotIn('controller', result['events'][0])
        self.assertEqual(result['cases'][0]['controller'], 'PhonePaletteImportController')

    def test_passed_case_never_borrows_failed_cases_identity(self):
        result, calls, _, _ = self.run_collection(retained((self.second,)))
        self.assertEqual(result['cases'][0], {'case': CASE['case'], 'status': 'no-target-failure'})
        self.assertNotIn('32708', calls[-1][0][-1]); self.assertNotIn(CASE['token'], calls[-1][0][-1])
        self.assertNotIn(' OR ', calls[-1][0][-1])

    def test_complete_unknown_layout_retains_all_three_full_streams_and_exact_stage(self):
        import base64, hashlib
        def helper(command, options):
            return subprocess.CompletedProcess(command, 0, b'Installed help layout\n' + b'x' * 16362,
                                                b'Supplemental help\n' + b'y' * 16365)
        result, calls, rows, text = self.run_collection(helper=helper)
        self.assertEqual(result['query_route'], 'fixed-query-compatibility')
        self.assertEqual(len(rows), 3); self.assertEqual(len(calls), 4)
        self.assertLessEqual(len(text.encode()) + 3 * 128, 136 * 1024)
        for row, (argv, _) in zip(rows, calls):
            self.assertEqual(row['argv'], argv)
            self.assertEqual(row['stage'], argv[-1]); self.assertTrue(row['complete'])
            self.assertEqual(row['source'], CONTEXT); self.assertEqual(row['exit_code'], 0)
            self.assertLessEqual(row['started_monotonic'], row['returned_monotonic'])
            self.assertLessEqual(row['returned_monotonic'], row['deadline_monotonic'])
            for stream in ('stdout', 'stderr'):
                raw = base64.b64decode(row[stream]['base64'], validate=True)
                self.assertEqual(len(raw), row[stream]['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row[stream]['sha256'])
                self.assertTrue(row[stream]['complete'])

    def test_complete_help_prose_about_failed_operations_does_not_stop_fixed_query(self):
        prose = b'\nThis reference documents successful and failed log operations.\n'
        process = subprocess.CompletedProcess([], 0, HELP['show'] + prose, b'')
        self.assertTrue(d.confirmed_help('show', process))
        self.assertFalse(d.help_has_error(process))
        for code in (0, 64):
            def helper(command, options):
                return subprocess.CompletedProcess(command, code, HELP[command[-1]] + prose, b'')
            result, calls, rows, _ = self.run_collection(helper=helper)
            self.assertEqual(result['status'], 'observation-gap')
            self.assertEqual(result['query_route'], 'recognized-help')
            self.assertEqual(len(calls), 4)
            self.assertEqual(calls[-1][0], d.log_command(IDENTITY, [CASE, self.second]))
            self.assertTrue(all(row['complete'] for row in rows))

    def test_failure_prose_is_distinct_from_explicit_command_diagnostics(self):
        for text in (b'This reference documents a failure and failed operations.',
                     b'The example explains a permission denied result.',
                     b'When an option is unsupported, consult the documentation.',
                     b'Error handling is documented below.', b'Unsupported options are described below.'):
            self.assertFalse(d.help_has_error(subprocess.CompletedProcess([], 0, HELP['show'] + b'\n' + text, b'')))
        for text in (b'log: failed to open log store', b'Failed to open log store', b'failure: unavailable store',
                     b'log: failure opening store', b'simctl: error: blocked',
                     b'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=1):'):
            for code in (0, 64):
                self.assertTrue(d.help_has_error(subprocess.CompletedProcess([], code, HELP['show'], text)))
        self.assertTrue(d.help_has_error(subprocess.CompletedProcess([], 1, HELP['show'], b'')))

    def test_late_help_emission_downgrades_observation_without_changing_completed_commands(self):
        original_emit = d.emit_help_receipts
        for output in (b'[]', json.dumps([self.record_for(CASE)]).encode()):
            for finished in (35.0, 35.001):
                clock = [0.0]
                def emit(records):
                    original_emit(records)
                    clock[0] = finished
                with patch.object(d.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(d, 'emit_help_receipts', side_effect=emit):
                    result, calls, rows, _ = self.run_collection(output=output)
                self.assertEqual(len(calls), 4); self.assertEqual(len(rows), 3)
                self.assertTrue(result['simulator_commands_completed'])
                self.assertTrue(all(row['complete'] for row in rows))
                if finished > 35:
                    self.assertEqual(result['status'], 'unavailable')
                    self.assertEqual(result['reason'], 'help-output-exceeded-original-clock')
                    self.assertEqual(result['events'], [])
                    self.assertFalse(result['observation_complete'])
                else:
                    self.assertEqual(result['status'], 'observation-gap' if output == b'[]' else 'receipts-retained')

    def test_late_host_emission_cannot_clear_existing_command_uncertainty(self):
        original_emit = d.emit_help_receipts
        clock = [0.0]
        def emit(records):
            original_emit(records); clock[0] = 35.001
        def stopped(command, options):
            raise d.CaptureStopped('duration-limit', True)
        with patch.object(d.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(d, 'emit_help_receipts', side_effect=emit):
            result, calls, _, _ = self.run_collection(helper=stopped)
        self.assertEqual(len(calls), 1)
        self.assertFalse(result['simulator_commands_completed'])
        self.assertEqual(result['reason'], 'command-exit-unconfirmed')

    def test_permission_error_nonzero_and_uncertainty_stop_future_commands_but_frame_three_stages(self):
        for error in (b'Permission denied', b'Operation not permitted', b'error: blocked', b'unknown option --style', b'log: Must be root to run this command',
                      b'log: insufficient privileges', b'Access to logs requires administrator privileges.'):
            def helper(command, options):
                return subprocess.CompletedProcess(command, 0, HELP['spawn'], error)
            result, calls, rows, _ = self.run_collection(helper=helper)
            self.assertEqual(len(calls), 1); self.assertEqual(result['reason'], 'help-command-error')
            self.assertEqual([row['status'] for row in rows], ['complete-error', 'not_requested', 'not_requested'])
            self.assertTrue(rows[0]['stderr']['complete'])
        def stopped(command, options):
            error = d.CaptureStopped('byte-limit', True)
            error.stdout_prefix = b'x' * 32768; error.stdout_observed_bytes = 32769
            raise error
        result, calls, rows, _ = self.run_collection(helper=stopped)
        self.assertEqual(len(calls), 1); self.assertFalse(result['simulator_commands_completed'])
        self.assertFalse(rows[0]['complete']); self.assertFalse(rows[0]['stdout']['complete'])
        self.assertEqual(rows[0]['stdout']['observed_bytes'], 32769)
        self.assertEqual(rows[0]['stdout']['bytes'], 32768)

    def test_combined_24_event_envelopes_fit_but_actual_serialized_overflow_is_unknown(self):
        records = [self.record_for(CASE if i < 12 else self.second, sequence=i % 12 + 1,
                                  event='accept-enter' if i % 2 else 'apply-applied') for i in range(24)]
        result, _, _, _ = self.run_collection(output=json.dumps(records).encode())
        self.assertEqual(result['status'], 'receipts-retained'); self.assertEqual(len(result['events']), 24)
        self.assertEqual(result['events'][0]['sequence'], 1); self.assertEqual(result['events'][-1]['sequence'], 12)
        measured = len(json.dumps({key: result[key] for key in ('cases', 'events')}, separators=(',', ':'), sort_keys=True).encode())
        self.assertLessEqual(measured, 12288)
        for record in records:
            value = json.loads(record['eventMessage'][len(d.PREFIX):])
            value.update({key: 'X' * 80 for key in d.TYPE_FIELDS if key != 'controller'})
            record['eventMessage'] = d.PREFIX + json.dumps(value)
        result, _, _, _ = self.run_collection(output=json.dumps(records).encode())
        self.assertEqual(result['status'], 'unknown'); self.assertEqual(result['reason'], 'sanitized-byte-limit')
        self.assertEqual(result['events'], []); self.assertFalse(result['observation_complete'])
        result, _, _, _ = self.run_collection(output=json.dumps(records + [records[0]]).encode())
        self.assertEqual(result['reason'], 'combined-event-limit'); self.assertEqual(result['events'], [])

    def test_guard_states_and_late_apply_are_preserved_without_mutation_or_inference(self):
        states = [
            dict(busy=False, selectionExists=True, selectionNonempty=True, buttonEnabled=True),
            dict(busy=True, selectionExists=True, selectionNonempty=True, buttonEnabled=False),
            dict(busy=False, selectionExists=False, selectionNonempty=False, buttonEnabled=False),
            dict(busy=False, selectionExists=True, selectionNonempty=False, buttonEnabled=False),
            dict(busy=False, selectionExists=True, selectionNonempty=True, buttonEnabled=True),
        ]
        records = [self.record_for(CASE, sequence=index + 1, epoch=CASE['started'] + index + 1,
                                  event='apply-applied' if index == 4 else 'accept-enter', **state)
                   for index, state in enumerate(states)]
        original = copy.deepcopy(records)
        rows = d.lifecycle_rows(json.dumps(records), [CASE])
        self.assertEqual(records, original)
        self.assertEqual([row['event'] for row in rows], ['accept-enter'] * 4 + ['apply-applied'])
        for row, state in zip(rows, states):
            self.assertEqual({key: row[key] for key in state}, state)
            self.assertNotIn('guard_passed', row)
            self.assertNotIn('nondelivery', row)

    def test_malformed_log_shapes_return_explicit_unavailable(self):
        for raw in (b'null', b'[null]', json.dumps([dict(entry(), processImagePath=None)]).encode()):
            result, calls, _, _ = self.run_collection(output=raw)
            self.assertEqual(len(calls), 4)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['reason'], 'invalid-or-unavailable-evidence')
            self.assertEqual(result['events'], [])

    def test_three_help_framing_fits_with_maximum_run_identity_and_split_padding(self):
        import contextlib
        import uikit_managed_device as managed
        import uikit_completion as completion
        maximum_context = dict(CONTEXT, repository=managed.REPOSITORY, ref=completion.REF,
            workflow_ref=completion.WORKFLOW, run_id='9' * 20, run_attempt='9' * 20,
            event='workflow_dispatch', job='completion', full_original_row=False)
        value = copy.deepcopy(self.value); value['command_interval']['source'] = maximum_context
        def helper(command, options):
            return subprocess.CompletedProcess(command, 64, b'x' * 16384, b'y' * 16384)
        result, _, frames, text = self.run_collection(value, helper=helper)
        self.assertEqual(result['query_route'], 'fixed-query-compatibility')
        self.assertEqual(len(frames), 3)
        self.assertEqual(sum(row['stdout']['bytes'] + row['stderr']['bytes'] for row in frames), 96 * 1024)
        self.assertLessEqual(len(text.encode()) + 128 * 3, d.MAX_HELP_LOG_BYTES)

    def test_collector_load_checks_sources_once_and_shared_clock_cannot_reset(self):
        import contextlib
        clock, calls = [0.0], []
        def load(identity, runner):
            for argv in (['git', 'rev-parse', 'HEAD'], ['git', 'diff', '--quiet', 'HEAD', '--']):
                runner(argv, seconds=3, cap=4096)
            return self.value
        def runner(command, **options):
            calls.append((command, options)); clock[0] += options['seconds']
            raw = b'x' * 4096 if command[0] == 'git' else HELP[command[-1]] if 'help' in command else b'[]'
            return subprocess.CompletedProcess(command, 0, raw, b'')
        with patch.object(d, 'load_case', side_effect=load), patch.object(d.time, 'monotonic', side_effect=lambda: clock[0]), \
                contextlib.redirect_stdout(io.StringIO()):
            result = d.collect_lifecycle(IDENTITY, runner)
        self.assertEqual(result['status'], 'observation-gap'); self.assertEqual(len(calls), 6)
        self.assertEqual(sum(item[1]['cap'] for item in calls), 360 * 1024)
        self.assertEqual([item[1]['seconds'] for item in calls], [3, 3, 3, 3, 3, 8])
        self.assertEqual(clock[0], 23); self.assertLessEqual(clock[0] + 4, 35)


class FunctionalCommandIntervalTests(unittest.TestCase):
    def setUp(self):
        import uikit_managed_tests as managed
        self.managed = managed
        self.binding = {'identity': IDENTITY, 'context': CONTEXT}
        self.selected = {'group': 'iphone-large', 'suite': 'TouchColorUITests',
                         'cases': ['TouchColorUITests/TouchColorUITests/' + case for case in d.CASES],
                         'kind': 'selected_completion', 'full_target': False, 'full_original_row': False}
        with patch.object(managed, 'selection', return_value=self.selected):
            argv = managed.test_argv('iPhoneLarge', 'TouchColorUITests', IDENTITY['udid'])
        self.value = {'schema': 3, 'suite': 'TouchColorUITests', 'selection': self.selected,
            'setup': {'binding': self.binding}, 'summary_qualification_only': True,
            'case_identity_basis': 'fixed_executed_argv_and_complete_summary',
            'per_case_log_reconciliation': 'pending_external_review',
            'command': {'status': 'timely_exit', 'host_cleanup_confirmed': True, 'exit_code': 65,
                        'argv': argv, 'started_monotonic': 12.0, 'finished_monotonic': 320.0, 'deadline_monotonic': 1111.0},
            'timing': {'phase_started_monotonic': 0.0, 'phase_deadline_monotonic': 1200.0,
                       'admitted_monotonic': 10.0, 'command_origin_monotonic': 11.0,
                       'command_wall_started': 99.0, 'command_wall_finished': 500.0}}

    def read(self, value=None, binding=None):
        import uikit_managed_device as device
        import uikit_completion as completion
        raw = json.dumps(value or self.value).encode()
        with patch.object(self.managed, 'selection', return_value=self.selected), \
                patch.object(completion, 'selection', return_value=self.selected), \
                patch.object(self.managed, 'read_regular', return_value=raw), \
                patch.object(device, 'read_binding', return_value=binding or self.binding):
            return d.command_interval(IDENTITY, SOURCE)

    def test_actual_immutable_functional_argv_interval_is_hashed(self):
        import hashlib
        result = self.read()
        self.assertEqual((result['started'], result['ended']), (99., 500.))
        raw = json.dumps(self.value).encode()
        self.assertEqual(result['receipt_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['receipt_bytes'], len(raw))

    def test_wrong_source_run_identity_argv_exit_or_admission_never_infers_command(self):
        for branch, key, replacement in (
            ('command', 'argv', ['xcodebuild']), ('command', 'exit_code', True),
            ('command', 'status', 'forced_exit'), ('command', 'host_cleanup_confirmed', False),
            ('command', 'deadline_monotonic', 1112.), ('command', 'finished_monotonic', 1112.),
            ('timing', 'phase_deadline_monotonic', 1201.), ('timing', 'command_wall_finished', 98.),
            ('timing', 'admitted_monotonic', 150.), ('timing', 'command_wall_started', float('inf'))):
            value = copy.deepcopy(self.value); value[branch][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError): self.read(value)
        for key, replacement in (('sha', 'b' * 40), ('run_id', '124')):
            binding = copy.deepcopy(self.binding); binding['context'][key] = replacement
            with self.assertRaises(ValueError): self.read(binding=binding)

    def test_malformed_receipt_and_case_shapes_fail_closed(self):
        for key in ('setup', 'command', 'timing'):
            value = copy.deepcopy(self.value); value[key] = None
            with self.subTest(key=key), self.assertRaises(ValueError): self.read(value)
        import uikit_managed_tests as managed
        for value in (None, [], dict(retained(), cases=[None, {}])):
            with patch.object(Path, 'exists', return_value=True), \
                    patch.object(managed, 'read_regular', return_value=json.dumps(value).encode()), \
                    patch.object(d, 'source_identity', return_value=SOURCE), self.assertRaises(ValueError):
                d.load_case(IDENTITY)

    def test_retainer_window_cannot_substitute_for_actual_command_window(self):
        value = retained(); value['capture_started'] = 90.; value['capture_ended'] = 700.
        with tempfile.TemporaryDirectory() as folder:
            old = Path.cwd(); os.chdir(folder)
            try:
                Path('build').mkdir(); Path('build/iPhoneLarge-palette-case.json').write_text(json.dumps(value))
                for interval in (dict(INTERVAL, started=101.), dict(INTERVAL, ended=130.)):
                    with patch.object(d, 'source_identity', return_value=SOURCE), \
                            patch.object(d, 'command_interval', return_value=interval), self.assertRaises(ValueError):
                        d.load_case(IDENTITY)
            finally: os.chdir(old)


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

    def test_first_signal_ack_follows_real_handler_and_preserves_first_observation(self):
        from types import SimpleNamespace
        old = Path.cwd(); calls = []; registered = {}
        def register(number, handler):
            prior = registered.get(number); registered[number] = handler; return prior
        signal_fixture = SimpleNamespace(signal=register)
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                exec(FIRST_SIGNAL_OBSERVER, {'signal': signal_fixture, 'Path': Path, 'os': os})
                def interrupted(number, frame):
                    if not calls: self.assertFalse(Path('signal.handled').exists())
                    calls.append(number)
                signal_fixture.signal(signal.SIGTERM, interrupted)
                self.assertFalse(Path('signal.handled').exists())
                original_write = Path.write_text
                def publication(path, value):
                    self.assertEqual(calls, [signal.SIGTERM])
                    self.assertFalse(Path('signal.handled').exists())
                    return original_write(path, value)
                with patch.object(Path, 'write_text', new=publication):
                    registered[signal.SIGTERM](signal.SIGTERM, None)
                self.assertEqual(Path('signal.handled').read_text(), str(signal.SIGTERM.value))
                signal_fixture.signal(signal.SIGINT, interrupted)
                registered[signal.SIGINT](signal.SIGINT, None)
                self.assertEqual(calls, [signal.SIGTERM, signal.SIGINT])
                self.assertEqual(Path('signal.handled').read_text(), str(signal.SIGTERM.value))
                sentinel = lambda *arguments: None
                signal_fixture.signal(signal.SIGINT, sentinel)
                self.assertIs(registered[signal.SIGINT], sentinel)
                self.assertFalse(Path('signal.handled.tmp').exists())
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
original_collect=d.collect_lifecycle
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
# Supply only synthetic retained case metadata; exercise the real remaining
# app collector and its first bounded help command through runtime.main.
d.load_case=lambda identity, **options: {'cases': [{'case': d.CASES[0], 'status': 'bound-failure', 'failure': {'case': d.CASES[0], 'token': '11111111-1111-4111-8111-111111111111', 'pid': 32708, 'started': 100.125, 'epoch': 134.75}}, {'case': d.CASES[1], 'status': 'no-target-failure'}], 'source': {'sha': 'e'*40}, 'command_interval': {'started': 99, 'ended': 135, 'source': {'sha': 'e'*40, 'completion_group': 'iphone-large'}}}
d.collect_lifecycle=lambda identity: original_collect(identity, runner=observe_capture)
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
            source = driver.read_text()
            marker = 'before={number:signal.getsignal(number)'
            self.assertEqual(source.count(marker), 1)
            driver.write_text(source.replace(marker, FIRST_SIGNAL_OBSERVER + '\n' + marker, 1))
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
                # Keep the original parent deadline. Do not send a different
                # signal until the real first callback has actually completed.
                acknowledgement = root/'signal.handled'
                while not acknowledgement.exists() and time.monotonic() < deadline:
                    if process.poll() is not None: break
                    time.sleep(.01)
                self.assertTrue(acknowledgement.exists())
                self.assertEqual(int(acknowledgement.read_text()), int(first_signal))
                # Repeat both cancellation signals during the TERM-ignoring
                # producer's finite cleanup phase. They must neither abort it
                # nor start another cleanup allowance.
                for number in (first_signal, signal.SIGINT, signal.SIGTERM, first_signal):
                    process.send_signal(number)
                    time.sleep(.035)
                output, errors = process.communicate(timeout=9 if entry else 6)
                self.assertEqual(process.returncode, 0, errors.decode(errors='replace'))
                result = json.loads((root/'result.json').read_text())
                self.assertNotIn('unexpected_success', result)
                self.assertTrue(result['cleanup_confirmed'], result)
                self.assertEqual(result['cancelled_signal'], int(first_signal), result)
                self.assertTrue(result['handlers_restored'], result)
                self.assertEqual(result['cleanup_calls'], [{'grace': 2}])
                self.assertLess(result['elapsed'], 7.8 if entry else 4.8, result)
                if entry:
                    self.assertTrue(result['marker_preserved'])
                    self.assertTrue(result['safe_output_absent'])
                    self.assertEqual(len(result['calls']), 1)
                    self.assertEqual(result['calls'][0]['seconds'], 3)
                    self.assertNotIn('cleanup_grace', result['calls'][0])  # Original collector uses capture's two-second default.
                    self.assertEqual(result['calls'][0]['cap'], 32 * 1024)
                    self.assertEqual(result['calls'][0]['command'], ['xcrun','simctl','help','spawn'])
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

    def test_full_entry_sigterm_during_collector_help(self):
        self.probe('active', signal.SIGTERM, entry=True)

    def test_full_entry_sigint_during_collector_help(self):
        self.probe('active', signal.SIGINT, entry=True)

    def test_full_entry_first_sigterm_during_collector_cleanup(self):
        self.probe('timeout', signal.SIGTERM, entry=True)

    def test_full_entry_first_sigint_during_collector_cleanup(self):
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
    def test_release_projection_matches_fixed_pre_observation_source(self):
        import hashlib
        app = (Path(__file__).resolve().parents[1]/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_bytes()
        projected, active, parents = [], True, []
        for line in app.splitlines(keepends=True):
            directive = line.strip()
            if directive == b'#if DEBUG':
                parents.append(active)
                active = False
            elif directive == b'#else':
                self.assertTrue(parents)
                active = parents[-1] and not active
            elif directive == b'#endif':
                self.assertTrue(parents)
                active = parents.pop()
            else:
                self.assertFalse(directive.startswith(b'#if'), 'Unreviewed conditional')
                if active:
                    projected.append(line)
        self.assertFalse(parents)
        projection = b''.join(projected)
        self.assertEqual(len(projection), 10879)
        self.assertEqual(hashlib.sha256(projection).hexdigest(),
                         'cc623ea646e6a6c22a879ddd0b36a67a8ce168738aef1766221c5527eb0d9a5f')

    def test_only_two_debug_observations_and_three_boolean_reads_are_added(self):
        import hashlib
        app = (Path(__file__).resolve().parents[1]/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_text()
        token_binding = ('        let arguments = ProcessInfo.processInfo.arguments\n'
                         '        let token: UUID?\n'
                         '        if let index = arguments.firstIndex(of: "--ui-test-palette-lifecycle-token"),\n'
                         '           arguments.indices.contains(index + 1) { token = UUID(uuidString: arguments[index + 1]) }\n'
                         '        else { token = nil }\n'
                         '        guard !requiresToken || token != nil else { return }\n')
        additions = ('        if let token {\n'
                     '            fields["selectionExists"] = selection != nil\n'
                     '            fields["selectionNonempty"] = !(selection?.colors.isEmpty ?? true)\n'
                     '            fields["buttonEnabled"] = addButton?.isEnabled ?? false\n')
        original_binding = ('        let arguments = ProcessInfo.processInfo.arguments\n'
                            '        if let index = arguments.firstIndex(of: "--ui-test-palette-lifecycle-token"),\n'
                            '           arguments.indices.contains(index + 1), let token = UUID(uuidString: arguments[index + 1]) {\n')
        self.assertEqual(app.count(token_binding), 1)
        self.assertEqual(app.count(additions), 1)
        self.assertLess(app.index(token_binding), app.index('        func typeName('))
        # Missing/invalid tokens cannot admit either new event or new fields.
        restored = app.replace(', requiresToken: Bool = false', '')
        restored = restored.replace(token_binding, '').replace(additions, original_binding)
        for event in ('accept-enter', 'apply-applied'):
            observation = '#if DEBUG\n        tracePresentation("' + event + '", requiresToken: true)\n#endif\n'
            self.assertEqual(restored.count(observation), 1)
            restored = restored.replace(observation, '')
        # Exact inverse locks all earlier no-token DEBUG events and metadata.
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),
                         '32de83ef1894d1f2c73f1976a380f2295bf542eb99e16efd41e3ad84960248f1')
        accept = app.split('    @objc private func accept() {\n', 1)[1].split('    @objc private func close()', 1)[0]
        self.assertTrue(accept.startswith('#if DEBUG\n        tracePresentation("accept-enter", requiresToken: true)\n#endif\n'
                                         '        guard !busy, let selection, !selection.colors.isEmpty else { return }\n'))
        apply = app.split('    func apply(_ result: Result<PaletteSelection, Error>, name: String, token: UInt64) {\n', 1)[1].split('    func chooseFile()', 1)[0]
        self.assertTrue(apply.startswith('        guard gate.accepts(token) else { return }; busy = false\n'))
        self.assertTrue(apply.endswith('        reload()\n#if DEBUG\n        tracePresentation("apply-applied", requiresToken: true)\n#endif\n    }\n'))

    def test_exact_two_case_bindings_preserve_started_failed_marker_schema(self):
        import re
        test = (Path(__file__).resolve().parents[1]/'TouchColorUITests/TouchColorUITests.m').read_text()
        bindings = test.split('    self.paletteLifecycleCase=@{\n', 1)[1].split('    }[self.name];', 1)[0]
        self.assertEqual(re.findall(r'@"-\[TouchColorUITests ([^\]]+)\]":@"([^"]+)"', bindings),
                         [(name, name) for name in ('testInvalidPalettePastePreservesHistory',
                                                   'testPalettePasteReviewAcceptAndRelaunch')])
        setup = test.split('- (void)setUp {', 1)[1].split('- (void)revealControl:', 1)[0]
        token = setup.split('    if (self.paletteLifecycleCase) {\n', 1)[1].split('\n    }', 1)[0]
        self.assertIn('self.paletteLifecycleToken=NSUUID.UUID.UUIDString;', token)
        self.assertIn('self.paletteLifecycleStarted=NSDate.date.timeIntervalSince1970;', token)
        self.assertIn('@[@"--ui-test-palette-lifecycle-token",self.paletteLifecycleToken]', token)
        self.assertIn('[self emitPaletteLifecycleCase:@"started" pid:@0];', token)
        self.assertEqual(test.count('self.paletteLifecycleToken=NSUUID.UUID.UUIDString;'), 1)
        marker = test.split('- (void)emitPaletteLifecycleCase:', 1)[1].split('- (void)setUp', 1)[0]
        self.assertEqual(re.findall(r'@"(\w+)":', marker), ['event', 'case', 'token', 'started', 'epoch', 'pid'])
        self.assertIn('@"case":self.paletteLifecycleCase', marker)
        self.assertEqual(test.count('[self emitPaletteLifecycleCase:@"failed" pid:pid];'), 1)

    def test_failure_pid_requires_current_launch_token_and_reuses_original_snapshot(self):
        import hashlib
        test = (Path(__file__).resolve().parents[1]/'TouchColorUITests/TouchColorUITests.m').read_text()
        issue = test.split('- (void)recordIssue:(XCTIssue *)issue {\n', 1)[1].split('- (void)emitScreenshot:', 1)[0]
        binding = ('        NSArray<NSString *> *arguments=self.app.launchArguments;\n'
                   '        NSUInteger tokenIndex=[arguments indexOfObject:@"--ui-test-palette-lifecycle-token"];\n'
                   '        BOOL launchBound=[arguments containsObject:@"--ui-test-palette-lifecycle"] && tokenIndex!=NSNotFound &&\n'
                   '            tokenIndex+1<arguments.count && [arguments[tokenIndex+1] isEqualToString:self.paletteLifecycleToken];\n')
        self.assertEqual(issue.count(binding), 1)
        self.assertIn('NSNumber *pid=@0;\n        if (matches.count==1 && launchBound) pid=', issue)
        self.assertEqual(issue.count('self.app.debugDescription'), 1)
        restored = issue.replace(binding, '').replace('if (matches.count==1 && launchBound)', 'if (matches.count==1)')
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),
                         '90ee4ede6bc703b31786e070b69ede696e2f879ead125e37b5a91f0b50e7135c')
        # The final normal-case relaunch intentionally has no observation token.
        helper = (Path(__file__).resolve().parents[1]/'TouchColorUITests/TCPaletteUIHelpers.m').read_text()
        normal = helper.split('- (void)exercisePalettePasteReviewAcceptAndRelaunch:', 1)[1].split('- (void)exerciseInvalidPalettePastePreservesHistory:', 1)[0]
        self.assertIn('[app terminate];app.launchArguments=@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];[app launch];', normal)

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
        self.close = self.swift.split('    func testActualCloseBarActionDismissesFullScreenErrorAndRejectsLateResult()', 1)[1].split('    func testOriginalIOSImportIsPresentWithoutCompanion', 1)[0]
        start = self.swift.index('    func testActualAddColorsBarActionAppendsDuplicateSelectionAndDismisses()')
        self.accept = self.swift[start:self.swift.index('    func testActualCloseBarActionDismissesFullScreenErrorAndRejectsLateResult()', start)]

    def test_product_and_unrelated_close_methods_are_unchanged(self):
        import hashlib
        self.assertEqual(hashlib.sha256((self.root/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_bytes()).hexdigest(),
                         '9174667d6dd918f5f8d10ab17e1d3beba08f08d7083387db74c9f18c759cbf97')
        self.assertEqual(hashlib.sha256(self.swift.split('    func testCancelledFileSelectionAndUnsupportedPasteRejectLatePriorRead()', 1)[1].encode()).hexdigest(),
                         'f3cb0b39635819efea36defdcc6b17f865e410c7f74edbdb9f940beff1f9430e')

    def test_real_swift_close_gate_body_stays_byte_exact(self):
        import hashlib
        body=self.close
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),'ff08fdc43c4cf6a1932591fade35e7e6ed2830bb307b1a0d4b0445e8857b8a4e')

    def test_add_colors_reuses_real_host_and_original_three_second_gates(self):
        body = self.accept
        self.assertEqual(self.swift.count('func testActualAddColorsBarActionAppendsDuplicateSelectionAndDismisses()'), 1)
        # The scene, real appearance callback, full-screen host, timing proof and
        # fail-closed presentation gates are copied exactly from the locked Close case.
        def host(text):
            return text.split('        let scene =', 1)[1].split('        let token =', 1)[0].split('        let selected =', 1)[0]
        self.assertEqual(host(body).replace('HOSTED_UI_GATE case=add-colors ', 'HOSTED_UI_GATE '), host(self.close))
        self.assertEqual(body.count('timeout: 3)'), 3)
        self.assertEqual(body.count('owner.present('), 1)
        self.assertEqual(body.count('UIApplication.shared.sendAction('), 1)
        for phase in ('owner', 'presentation', 'dismissal'):
            for clock in ('Action', 'Returned', 'Wait', 'WaitReturned'):
                self.assertIn('let '+phase+clock+' = ProcessInfo.processInfo.systemUptime', body)
            self.assertIn('$0 >= '+phase+'Action && $0 < '+phase+'Wait + 3', body)
            rejected = body.split('guard '+phase+'Timely', 1)[1].split('return', 1)[0]
            self.assertIn('XCTFail(', rejected)
        callback = body.split('owner.onNextAppearance =', 1)[1].split('        defer { owner.onNextAppearance', 1)[0]
        self.assertLess(callback.index('owner.presentedViewController == nil'), callback.index('dismissalEvent = ProcessInfo'))
        self.assertIn('owner.viewIfLoaded?.window === window', callback)
        self.assertIn('if dismissalState { dismissed.fulfill() }', callback)
        self.assertLess(body.index('owner.onNextAppearance ='), body.index('UIApplication.shared.sendAction'))
        self.assertIn('guard dismissalTimely, dismissalState, dismissalAbsent else', body)
        self.assertIn('XCTAssertNil(owner.presentedViewController)', body)
        for forbidden in ('XCTSkip', 'XCTNSPredicateExpectation', '.viewDidAppear(', '.viewDidDisappear(',
                          '.beginAppearanceTransition(', '.endAppearanceTransition(', '.accept(', '.close(', '.dismiss('):
            self.assertNotIn(forbidden, body)

    def test_add_colors_dispatches_real_item_and_preserves_exact_duplicate_history(self):
        body = self.accept
        for required in ('let original: [String: Any] = ["colorArray": [String](), "unrelatedPreference": "untouched"]',
                         'defaults.setPersistentDomain(original, forName: suite)',
                         'let duplicateColors = ["#123456", "#123456"]',
                         'content.apply(.success(selected), name: "duplicates.json", token: token)',
                         'XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), [])',
                         'XCTAssertEqual(defaults.persistentDomain(forName: suite) as NSDictionary?, original as NSDictionary)',
                         'let add = try XCTUnwrap(content.navigationItem.rightBarButtonItem)',
                         'let action = try XCTUnwrap(add.action)',
                         'XCTAssertEqual(add.accessibilityIdentifier, "palette.import.accept")',
                         'XCTAssertTrue(add.isEnabled)', 'XCTAssertTrue(add.target === content)',
                         'XCTAssertEqual(action, NSSelectorFromString("accept"))',
                         'XCTAssertTrue(content.responds(to: action))',
                         'let dispatched = UIApplication.shared.sendAction(action, to: add.target, from: add, for: nil)',
                         'XCTAssertTrue(dispatched)', 'XCTAssertFalse(add.isEnabled)',
                         'XCTAssertEqual(defaults.string(forKey: "unrelatedPreference"), "untouched")'):
            self.assertIn(required, body)
        self.assertLess(body.index('guard presentationTimely'), body.index('let token = content.begin()'))
        self.assertLess(body.index('XCTAssertTrue(add.isEnabled)'), body.index('UIApplication.shared.sendAction'))
        dispatched = body.split('let dispatched =', 1)[1].split('let dismissalWait =', 1)[0]
        self.assertIn('XCTAssertFalse(add.isEnabled)', dispatched)
        self.assertIn('XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), duplicateColors)', dispatched)
        self.assertLess(body.index('guard dismissalTimely'), body.index('content.apply(.success(late)'))
        late = body.split('content.apply(.success(late), name: "late.json", token: token)', 1)[1]
        self.assertIn('XCTAssertEqual(content.selection, selected,', late)
        self.assertIn('XCTAssertFalse(add.isEnabled)', late)
        self.assertIn('XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), duplicateColors)', late)
        self.assertIn('["colorArray": duplicateColors, "unrelatedPreference": "untouched"] as NSDictionary', late)

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
            if start == '- (void)exerciseSize:':
                # Only the retired web-error layout is replaced by the reviewed
                # native body/actions block. Every other geometry byte retains
                # its existing inverse lock; the new block also has an exact pin.
                begin = actual.index('            [self withController:[TCPrivacyViewController new]')
                finish = actual.index('            }];', begin) + len('            }];')
                native_policy = actual[begin:finish]
                self.assertEqual(hashlib.sha256(native_policy.encode()).hexdigest(), '56dd60c0cd7f1146043da268ef4b0dab79596253728de86f89f1f4559265f1a9')
                previous_policy = '            [self withController:[TCMinimumLayoutPolicy new] size:size style:appearance.integerValue check:^(UIViewController *controller) {\n                [controller.view layoutIfNeeded];\n                UIScrollView *error=(UIScrollView *)TCLayoutView(controller.view,@"privacy.errorScroll");\n                UIButton *retry=(UIButton *)TCLayoutView(controller.view,@"privacy.retry");\n                XCTAssertFalse(error.hidden,@"The native failure state must be visible before layout is measured");\n                XCTAssertGreaterThanOrEqual(retry.bounds.size.height,44);\n                [self assertViewReadable:retry inScroll:error];\n                XCTAssertEqualObjects(controller.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"privacy.close");\n            }];'
                actual = actual[:begin] + previous_policy + actual[finish:]
            self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),expected)

    def test_swift_gates_preserve_waiter_relative_three_seconds(self):
        self.assertEqual(self.close.count('timeout: 3)'), 3)
        for phase in ('owner', 'presentation', 'dismissal'):
            self.assertIn('let '+phase+'Action = ProcessInfo.processInfo.systemUptime', self.close)
            self.assertIn('let '+phase+'Returned = ProcessInfo.processInfo.systemUptime', self.close)
            self.assertIn('let '+phase+'Wait = ProcessInfo.processInfo.systemUptime', self.close)
            self.assertIn('let '+phase+'WaitReturned = ProcessInfo.processInfo.systemUptime', self.close)
        self.assertNotIn('actionStarted + 3', self.close)
        self.assertNotIn('dismissalDeadline', self.close)
        self.assertNotIn('XCTNSPredicateExpectation', self.close)

    def test_swift_dismissal_is_armed_before_real_action_and_state_before_clock(self):
        callback=self.close.split('owner.onNextAppearance =', 1)[1].split('        defer { owner.onNextAppearance', 1)[0]
        self.assertLess(callback.index('owner.presentedViewController == nil'),callback.index('dismissalEvent = ProcessInfo'))
        self.assertIn('owner.viewIfLoaded?.window === window',callback)
        self.assertIn('if dismissalState { dismissed.fulfill() }',callback)
        self.assertLess(self.close.index('owner.onNextAppearance ='),self.close.index('UIApplication.shared.sendAction'))
        self.assertIn('let next = onNextAppearance; onNextAppearance = nil; next?()',self.swift)
        for kept in ('XCTAssertNil(owner.presentedViewController)', 'content.apply(.success(late), name: "late.json", token: token)',
                     'XCTAssertNil(content.selection, "Dismissal invalidates a previously issued import generation")',
                     'XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), original)'):
            self.assertIn(kept,self.close)

    def test_unknown_swift_readiness_stops_dependent_actions_without_skip(self):
        for phase in ('owner','presentation','dismissal'):
            self.assertIn('guard '+phase+'Timely',self.close)
            self.assertIn('$0 >= '+phase+'Action && $0 < '+phase+'Wait + 3',self.close)
            self.assertIn('phase='+phase+' ',self.close)
        self.assertLess(self.close.index('guard presentationTimely'),self.close.index('let token = content.begin()'))
        self.assertLess(self.close.index('guard dismissalTimely'),self.close.index('content.apply(.success(late)'))
        self.assertNotIn('XCTSkip',self.close)

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
        self.assertEqual(hashlib.sha256(self.swift.replace(self.accept, '', 1).encode()).hexdigest(),
                         '6a25635f308ebb13b0385fd971b5d1b133a50154624d70759d1f34618c29530b')
        managed=(self.root/'scripts/uikit_managed_tests.py').read_text()
        self.assertIn("'TouchColorTests': (600, 500, 54)",managed)
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
            self.assertIn(line, self.close)
            branch = self.close.split('guard '+phase+'Timely', 1)[1].split('return', 1)[0]
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
        self.assertEqual(self.close.count('owner.present('),1)
        self.assertEqual(self.close.count('UIApplication.shared.sendAction('),1)
        self.assertEqual(self.objc.count('performWithoutAnimation:'),1)  # Existing workspace operation only.
        for text in (self.swift,self.objc):
            self.assertNotIn('sleep(',text)
            self.assertNotIn('setAnimationsEnabled',text)
            self.assertNotIn('timeout: 10',text)
            self.assertNotIn('timeout:10',text)


if __name__ == '__main__':
    unittest.main()
