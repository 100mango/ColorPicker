"""Synthetic metadata/stack tests. These are not native diagnostic evidence."""
import copy
import hashlib
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
    def test_streaming_inventory_filters_thousands_of_unrelated_names_before_retention(self):
        unrelated = [attachment(name=val('DO_NOT_RETAIN_UNRELATED'), filename=val('PRIVATE_SCREENSHOT.png'),
                                uniformTypeIdentifier=val('public.png')) for _ in range(2000)]
        for tail in ([], [attachment()]):
            values = objects(unrelated + tail)
            self.assertLess(len(json.dumps(values['summary-1']).encode()), d.MAX_SELECTED_SUMMARY)
            report, calls = self.exercise(values)
            inventory = report['attachments']
            self.assertEqual(inventory['total'], 2000 + len(tail))
            self.assertEqual(inventory['nonqualifying'], 2000)
            self.assertEqual(inventory['qualifying'], len(tail))
            self.assertEqual(len(inventory['candidates']), len(tail))
            self.assertIs(inventory['complete'], True)
            self.assertEqual(sum('--bounded-export' in command for command, options in calls), len(tail))
            self.assertNotIn('DO_NOT_RETAIN_UNRELATED', json.dumps(report))
            self.assertNotIn('PRIVATE_SCREENSHOT', json.dumps(report))
            self.assertLess(len(json.dumps(report).encode()), d.MAX_REPORT)

    def test_streaming_inventory_detects_separated_ambiguity_and_qualifying_overflow(self):
        unrelated = [attachment(name=val('IRRELEVANT'), uniformTypeIdentifier=val('public.png')) for _ in range(2000)]
        cases = [(objects([attachment()] + unrelated + [attachment(payloadRef=ref('payload-2'))]),
                  'multiple app stack candidates', 2002, 2, 2),
                 (objects([attachment(payloadRef=ref('payload-' + str(i))) for i in range(17)] + unrelated[:20]),
                  'too many qualifying app stack candidates', 37, 17, 16)]
        for values, reason, total, qualifying, retained in cases:
            with self.subTest(reason=reason):
                report, calls = self.exercise(values, failure=reason)
                inventory = report['attachments']
                self.assertEqual((inventory['total'], inventory['qualifying'], len(inventory['candidates'])),
                                 (total, qualifying, retained))
                self.assertIs(inventory['complete'], True)
                self.assertEqual(report['selected_summary_traversals'][-1]['terminal_reason'], 'complete')
                self.assertFalse(any('--bounded-export' in command for command, options in calls))

    def test_streaming_eligible_timestamp_and_reference_failures_remain_fatal(self):
        bad = [(attachment(timestamp=val('2026-10-07T21:00:00+00:00')), 'timestamp is outside'),
               (attachment(payloadRef=ref('bad id')), 'invalid object reference'),
               (attachment(timestamp=val('not-a-time')), 'Invalid isoformat')]
        for node, reason in bad:
            with self.subTest(reason=reason):
                report, calls = self.exercise(objects([attachment(), node, attachment()]), failure=reason)
                inventory = report['attachments']
                self.assertEqual(inventory['total'], 2)
                self.assertEqual(inventory['qualifying'], 2)
                self.assertIs(inventory['complete'], False)
                self.assertEqual(report['selected_summary_traversals'][-1]['terminal_reason'], 'consumer-stopped')
                self.assertFalse(any('--bounded-export' in command for command, options in calls))

    def test_streaming_late_deadline_after_candidate_keeps_partial_counts_and_never_exports(self):
        clock = [0.0]; original_timestamp = d.timestamp
        def timestamp(value):
            result = original_timestamp(value)
            if value == STAMP: clock[0] = 51
            return result
        unrelated = [attachment(name=val('IRRELEVANT'), uniformTypeIdentifier=val('public.png')) for _ in range(2000)]
        with patch.object(d, 'timestamp', timestamp):
            report, calls = self.exercise(objects([attachment()] + unrelated), failure='diagnostic-wall-clock', now=lambda: clock[0])
        inventory = report['attachments']
        self.assertEqual(inventory['qualifying'], 1)
        self.assertLess(inventory['total'], 2001)
        self.assertIs(inventory['complete'], False)
        self.assertEqual(report['selected_summary_traversals'][-1]['terminal_reason'], 'diagnostic-wall-clock')
        self.assertFalse(any('--bounded-export' in command for command, options in calls))

    def test_summary_envelope_maximum_width_and_one_over_nodes(self):
        self.assertEqual((d.MAX_SUMMARY_NODES, d.MAX_SUMMARY_DEPTH), (524288, 524287))
        raw = b'[' + b'0,' * 524286 + b'0]'
        self.assertEqual(len(raw), 1048575)
        report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: 1)
        self.assertEqual(list(d.walk_selected_summary(json.loads(raw), budget, 'object-inventory')), [])
        stats = report['selected_summary_traversals'][0]
        self.assertEqual(stats['nodes_visited'], 524288)
        self.assertEqual(stats['max_depth'], 1)
        self.assertEqual(stats['terminal_reason'], 'complete')
        self.assertEqual(stats['raw_byte_cap'], 1048576)
        with self.assertRaisesRegex(ValueError, 'node-limit'):
            list(d.walk_selected_summary([0] * 524288, budget, 'attachment-discovery'))
        self.assertEqual(report['selected_summary_traversals'][1]['nodes_visited'], 524289)
        self.assertEqual(report['selected_summary_traversals'][1]['terminal_reason'], 'node-limit')

    def test_recursive_summary_unknown_fields_keep_tail_attachment_and_no_context(self):
        data = objects()
        nested = {'unknownFutureField': {'nested': [attachment()]}}
        for _ in range(100):
            nested = obj('ActionTestActivitySummary', title=val('PRIVATE_ANCESTOR_VALUE'), subactivities=array(nested))
        data['summary-1'] = obj('ActionTestSummary', activitySummaries=array(nested))
        report, calls = self.exercise(data)
        self.assertEqual(report['evidence'], 'owned app main-thread stack')
        self.assertEqual(sum('--bounded-export' in command for command, options in calls), 1)
        graphs = report['selected_summary_traversals']
        self.assertEqual([row['stage'] for row in graphs], ['object-inventory', 'attachment-discovery'])
        self.assertTrue(all(row['max_depth'] > 32 and row['terminal_reason'] == 'complete' for row in graphs))
        self.assertEqual(graphs[0]['nodes_visited'], graphs[1]['nodes_visited'])
        self.assertNotIn('PRIVATE_ANCESTOR_VALUE', json.dumps(report))
        budget = d.Budget({}, 0, Reader(), now=lambda: 1)
        self.assertTrue(all(context == () for node, context in d.walk_selected_summary(data['summary-1'], budget, 'object-inventory')))

    def test_summary_node_and_depth_rejections_have_fixed_separate_telemetry(self):
        for name, limit, expected in (('MAX_SUMMARY_NODES', 2, 'node-limit'), ('MAX_SUMMARY_DEPTH', 1, 'depth-limit')):
            report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: 1)
            with patch.object(d, name, limit), self.assertRaisesRegex(ValueError, expected):
                list(d.walk_selected_summary({'outer': {'inner': 'PRIVATE_VALUE'}}, budget, 'object-inventory'))
            stats = report['selected_summary_traversals'][0]
            self.assertEqual(stats['terminal_reason'], expected)
            self.assertEqual(stats['nodes_visited'], 3)
            self.assertEqual(stats['max_depth'], 2)
            self.assertNotIn('PRIVATE_VALUE', json.dumps(report))

    def test_summary_passes_share_deadline_and_leave_export_reserve_enforced(self):
        clock = [0.0]; report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: clock[0])
        list(d.walk_selected_summary({'first': 0}, budget, 'object-inventory'))
        clock[0] = 51
        with self.assertRaisesRegex(ValueError, 'diagnostic-wall-clock'):
            list(d.walk_selected_summary({'second': 0}, budget, 'attachment-discovery'))
        self.assertEqual(report['selected_summary_traversals'][1]['nodes_visited'], 0)
        with self.assertRaisesRegex(ValueError, 'wall-clock budget'):
            budget.run(['must-not-export'])
        report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: 2401)
        with self.assertRaisesRegex(ValueError, 'original-evidence-clock'):
            list(d.walk_selected_summary({}, budget, 'object-inventory'))
        self.assertEqual(report['selected_summary_traversals'][0]['terminal_reason'], 'original-evidence-clock')

    def test_summary_periodic_deadline_stops_wide_graph_with_small_report(self):
        clock = [0.0]; report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: clock[0])
        nodes = d.walk_selected_summary({'items': [0] * 2000}, budget, 'object-inventory')
        next(nodes); clock[0] = 51
        with self.assertRaisesRegex(ValueError, 'diagnostic-wall-clock'): list(nodes)
        stats = report['selected_summary_traversals'][0]
        self.assertEqual(stats['nodes_visited'], 256)
        self.assertEqual(stats['terminal_reason'], 'diagnostic-wall-clock')
        self.assertLess(len(json.dumps(report).encode()), 1024)

    def test_summary_consumer_stop_and_extra_traversal_have_fixed_telemetry(self):
        report = {}; budget = d.Budget(report, 0, Reader(), now=lambda: 1)
        nodes = d.walk_selected_summary({'items': [0]}, budget, 'object-inventory')
        next(nodes); nodes.close()
        self.assertEqual(report['selected_summary_traversals'][0]['terminal_reason'], 'consumer-stopped')
        for stage in ('other', 'object-inventory'):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, 'invalid summary traversal stage|too many'):
                if stage == 'object-inventory': report['selected_summary_traversals'].append({})
                list(d.walk_selected_summary({}, budget, stage))

    def test_summary_consumer_signal_closes_iterator_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        report = {}; reader = Reader(); budget = d.Budget(report, 0, reader, now=lambda: 1)
        def interrupted(node): os.kill(os.getpid(), signal.SIGTERM)
        with d.cancellation_guard(), patch.object(d, 'kind', interrupted):
            with self.assertRaises(d.DiagnosticCancelled):
                d.object_json(budget, 'summary-1', role='selected-failure-summary')
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.assertEqual(report['selected_summary_traversals'][0]['terminal_reason'], 'consumer-stopped')
        self.assertEqual(report['objects'][0]['state'], 'read-complete')
        self.assertFalse(any('--bounded-export' in command for command, options in reader.calls))

    def test_decoder_depth_exception_is_distinct_without_changing_recursion_limit(self):
        report = {}; reader = Reader(); budget = d.Budget(report, 0, reader, now=lambda: 1)
        original = sys.getrecursionlimit()
        with patch.object(d.json, 'loads', side_effect=RecursionError('private parser detail')):
            with self.assertRaisesRegex(ValueError, '^metadata JSON parser depth limit$'):
                d.object_json(budget, 'summary-1', role='selected-failure-summary')
        self.assertEqual(sys.getrecursionlimit(), original)
        record = report['objects'][0]
        self.assertEqual(record['state'], 'read-complete')
        self.assertEqual(record['parse_result'], 'parser-depth-limit')
        self.assertIn('bytes', record); self.assertIn('sha256', record)
        self.assertNotIn('selected_summary_traversals', report)
        self.assertNotIn('private parser detail', json.dumps(report))

    def test_root_and_test_plan_still_use_original_graph_limits(self):
        for role, key in (('invocation', None), ('test-plan', 'tests-1')):
            value = 0
            for _ in range(34): value = {'child': value}
            reader = Reader({key: value}); report = {}; budget = d.Budget(report, 0, reader, now=lambda: 1)
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'metadata graph exceeds node/depth cap'):
                d.object_json(budget, key, role=role)
            self.assertEqual(reader.calls[0][1]['cap'], 262144)
            self.assertNotIn('selected_summary_traversals', report)

    def test_large_selected_summary_keeps_one_bounded_owned_stack_export(self):
        data = objects()
        summary = data['summary-1']
        summary['padding'] = ''
        summary['padding'] = 'x' * (d.MAX_SELECTED_SUMMARY - len(json.dumps(summary).encode()))
        raw = json.dumps(summary).encode()
        self.assertEqual(len(raw), 1048576)
        report, calls = self.exercise(data)
        self.assertEqual([options['cap'] for command, options in calls], [262144, 262144, 1048576, 8192])
        self.assertEqual(report['evidence'], 'owned app main-thread stack')
        self.assertEqual(sum('--bounded-export' in command for command, options in calls), 1)
        self.assertFalse(report['qualified'])
        record = report['objects'][-1]
        self.assertEqual(record['role'], 'selected-failure-summary')
        self.assertEqual(record['cap'], 1048576)
        self.assertEqual(record['state'], 'inspected')
        self.assertEqual(record['bytes'], len(raw))
        self.assertEqual(record['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotIn('padding', json.dumps(report))
        self.assertLess(len(json.dumps(report).encode()), 65536)

    def test_other_metadata_and_oversized_selected_summary_fail_without_retry(self):
        for role, object_id, cap in (('invocation', None, 262144), ('test-plan', 'tests-1', 262144),
                                     ('selected-failure-summary', 'summary-1', 1048576)):
            report, calls = {}, []
            def reader(command, **options):
                calls.append((command, options))
                return subprocess.CompletedProcess(command, 0, b'x' * (cap + 1), b'')
            budget = d.Budget(report, 0, reader, now=lambda: 1)
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'byte contract'):
                d.object_json(budget, object_id, role=role)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]['cap'], cap)
            self.assertEqual(report['objects'], [{'role': role, 'cap': cap, 'state': 'requested'}])

    def test_complete_read_digest_precedes_json_and_graph_validation(self):
        deep = {'private': 'DO_NOT_RETAIN'}
        for _ in range(34): deep = {'child': deep}
        inputs = [b'{"invalid_json": "DO_NOT_RETAIN"', json.dumps(deep).encode(),
                  json.dumps(['DO_NOT_RETAIN'] * 8193).encode()]
        for raw in inputs:
            report = {}
            def reader(command, **options): return subprocess.CompletedProcess(command, 0, raw, b'')
            budget = d.Budget(report, 0, reader, now=lambda: 1)
            with (self.subTest(size=len(raw)), patch.object(d, 'MAX_SUMMARY_NODES', 8192),
                  patch.object(d, 'MAX_SUMMARY_DEPTH', 32), self.assertRaises(ValueError)):
                d.object_json(budget, 'summary-1', role='selected-failure-summary')
            record = report['objects'][0]
            self.assertEqual(record, {'role': 'selected-failure-summary', 'cap': 1048576,
                'state': 'read-complete', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'parse_result': 'invalid-json' if raw == inputs[0] else 'decoded'})
            self.assertNotIn('DO_NOT_RETAIN', json.dumps(report))

    def test_invalid_metadata_roles_stop_before_any_command(self):
        for role, object_id in (('other', 'summary-1'), ('invocation', 'summary-1'),
                                ('test-plan', None), ('selected-failure-summary', None)):
            report = {}; reader = Reader(); budget = d.Budget(report, 0, reader, now=lambda: 1)
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'object role'):
                d.object_json(budget, object_id, role=role)
            self.assertEqual(reader.calls, []); self.assertNotIn('objects', report)

    def test_larger_summary_read_requires_prior_unique_failed_case_selection(self):
        for mutation in ('passed', 'other-case', 'duplicate'):
            data = objects()
            cases = data['tests-1']['summaries']['_values'][0]['tests']['_values']
            if mutation == 'passed': cases[0]['testStatus'] = val('Success')
            if mutation == 'other-case': cases[0]['identifier'] = val('Other/case')
            if mutation == 'duplicate': cases.append(copy.deepcopy(cases[0]))
            with tempfile.TemporaryDirectory() as directory:
                old = Path.cwd()
                try:
                    os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                    report = {'phase': 'preflight-verified', 'calls': 2}; reader = Reader(data)
                    budget = d.Budget(report, 0, reader, now=lambda: 1)
                    with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'selected failure'):
                        d.collect(budget, report, owner(), Path(directory))
                    self.assertEqual([options['cap'] for command, options in reader.calls], [262144, 262144])
                    self.assertEqual([row['role'] for row in report['objects']], ['invocation', 'test-plan'])
                finally: os.chdir(old)

    def test_metadata_read_byte_limit_keeps_role_and_confirmed_cleanup(self):
        report = {}
        def reader(command, **options): raise d.CaptureStopped('byte-limit', True, None)
        budget = d.Budget(report, 0, reader, now=lambda: 1)
        with self.assertRaises(d.CaptureStopped):
            d.object_json(budget, 'summary-1', role='selected-failure-summary')
        self.assertEqual(report['objects'], [{'role': 'selected-failure-summary', 'cap': 1048576, 'state': 'requested'}])
        self.assertIs(report['diagnostic_cleanup_confirmed'], True)
        self.assertEqual(report['calls'], 1)

    def test_large_summary_does_not_expand_payload_or_other_limits(self):
        self.assertEqual((d.MAX_META, d.MAX_TEXT, d.MAX_REPORT, d.TOTAL_SECONDS, d.MAX_CALLS),
                         (262144, 262144, 65536, 50, 8))
        data = objects(); data['summary-1']['padding'] = 'x' * 262144
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                report = {'phase': 'preflight-verified', 'calls': 2}; reader = Reader(data)
                def oversize_payload(command, **options):
                    result = reader(command, **options)
                    if '--bounded-export' in command: Path(command[-1]).write_bytes(b'x' * 262145)
                    return result
                budget = d.Budget(report, 0, oversize_payload, now=lambda: 1)
                with self.assertRaisesRegex(ValueError, 'input exceeds byte cap'):
                    d.collect(budget, report, owner(), Path(directory))
                self.assertEqual(list(Path(directory).glob('watch-stack-*')), [])
                self.assertNotIn('main_thread', report); self.assertNotIn('payload_bytes', report)
                self.assertTrue(all(options['seconds'] == 8 and options['cleanup_grace'] == 10
                                    for command, options in reader.calls))
            finally: os.chdir(old)

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
            self.assertEqual(candidates, []); self.assertEqual(inventory, {'total': 1, 'nonqualifying': 1, 'qualifying': 0, 'candidates': [], 'complete': True})

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

    def exercise(self, values, failure=None, now=None):
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory); Path(d.BUNDLE).mkdir(parents=True)
                reader = Reader(values); report = {'phase': 'preflight-verified', 'calls': 2}
                budget = d.Budget(report, 0, reader, now=now or (lambda: 1))
                if failure:
                    with self.assertRaisesRegex(ValueError, failure): d.collect(budget, report, owner(), Path(directory))
                else: d.collect(budget, report, owner(), Path(directory))
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
        self.assertEqual(len(candidates), 1); self.assertFalse(inventory['candidates'][0]['owner_metadata'])
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
