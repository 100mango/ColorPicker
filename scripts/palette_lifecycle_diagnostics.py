"""Observe two closed phone palette cases with one bounded fixed log query.

No logging configuration, log archive, process inventory or fallback query.
Complete safe help with an unknown layout permits the same reviewed query;
permission/errors and uncertain completion stop acquisition.
"""
import base64
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import uuid

from atomic_json import write_json
from bounded_process import group_exists, stop_group

CASES = ('testInvalidPalettePastePreservesHistory', 'testPalettePasteReviewAcceptAndRelaunch')
CASE = CASES[0]
XCTEST_CASE = '-[TouchColorUITests ' + CASE + ']'
XCTEST_CASES = {case: '-[TouchColorUITests ' + case + ']' for case in CASES}
PREFIX = 'PALETTE_LIFECYCLE '
MARKER = re.compile(r'TouchColorUITests-Runner\[[1-9][0-9]*:[0-9]+\] PALETTE_CASE (\{.*\})$')
SOURCES = ('TouchColorPhoneCompanion/PhonePaletteImportController.swift',
           'TouchColorUITests/TouchColorUITests.m', 'TouchColorUITests/TCPaletteUIHelpers.m',
           'scripts/palette_lifecycle_diagnostics.py', 'scripts/test_simulators.sh')
BOOL_FIELDS = ('visible', 'dismissing', 'navigationDismissing', 'transition', 'busy', 'finished',
               'selectionExists', 'selectionNonempty', 'buttonEnabled')
TYPE_FIELDS = ('controller', 'presenter', 'presented', 'navigationPresenter', 'navigationPresented')
EVENTS = {'appeared', 'file-present-requested', 'file-present-completed',
          'close-action-received', 'close-dismiss-completed', 'disappeared', 'finished',
          'accept-enter', 'apply-applied'}
MAX_RECORD = 12 * 1024
MAX_HELP_LOG_BYTES = 136 * 1024
HELP_FRAME = 'PALETTE_HELP_RECEIPT:'
MAX_ACQUISITION_BYTES = 360 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False, 'Nonfinite JSON'))


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_uuid(value):
    return isinstance(value, str) and re.fullmatch('[0-9A-F-]{36}', value) and str(uuid.UUID(value)).upper() == value


class CaptureStopped(RuntimeError):
    def __init__(self, reason, cleanup_confirmed, cancelled_signal=None):
        super().__init__(reason)
        self.cleanup_confirmed = cleanup_confirmed
        self.cancelled_signal = cancelled_signal


def capture(command, *, seconds, cap, cleanup_grace=2):
    """Cap stdout+stderr while reading, and stop only the owned host group.

    Lifecycle calls reserve two 2-second cleanup phases; the predecessor
    Files-service call preserves its existing two 10-second cleanup phases.
    Forced cleanup never proves simulator-side exit, even if host cleanup succeeds.
    """
    require(cleanup_grace in (2, 10), 'Unexpected owned cleanup reserve')
    deadline = time.monotonic() + seconds
    cancelled = [None]
    previous = {}
    process = None
    stopped = None
    output, errors = bytearray(), bytearray()
    stdout_observed_bytes = stderr_observed_bytes = 0
    selector = selectors.DefaultSelector()

    def interrupted(signum, frame):
        # As in the seed controller, defer further termination signals through
        # the finite owned cleanup reserve. Recording instead of raising also
        # closes the Popen-to-ownership-assignment cancellation race.
        if cancelled[0] is None:
            cancelled[0] = signum

    def check_cancelled():
        if cancelled[0] is not None:
            raise RuntimeError('interrupted-by-signal-' + str(cancelled[0]))

    try:
        # Install before spawning. Never leave an owned producer under the
        # default SIGTERM action; restore the caller's handlers after cleanup.
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        check_cancelled()
        output, errors = bytearray(), bytearray()
        total = 0
        for pipe in (process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('duration-limit')
            for key, _ in selector.select(min(remaining, .05)):
                check_cancelled()
                data = os.read(key.fileobj.fileno(), min(4096, cap + 1 - total))
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                destination = output if key.fileobj is process.stdout else errors
                if key.fileobj is process.stdout:
                    stdout_observed_bytes += len(data)
                else:
                    stderr_observed_bytes += len(data)
                destination.extend(data[:max(0, cap + len(data) - total)])
                if total > cap:
                    raise RuntimeError('byte-limit')
        check_cancelled()
        if time.monotonic() > deadline:
            raise RuntimeError('late-exit')
        if group_exists(process.pid):
            raise RuntimeError('descendant-exit-unconfirmed')
        result = subprocess.CompletedProcess(command, process.returncode, bytes(output), bytes(errors))
    except BaseException as error:
        if process is None:
            raise
        # Reuse the reviewed owned-group protocol and the caller's unchanged
        # reserve. Record-only handlers remain active throughout this call, so
        # even the first signal during timeout/byte-limit cleanup cannot escape.
        confirmed = stop_group(process, grace=cleanup_grace)
        reason = str(error) if type(error) is RuntimeError else type(error).__name__
        stopped = CaptureStopped(reason, confirmed, cancelled[0])
        # Preserve only bounded failure evidence already read by this capture.
        # A stopped producer never proves the complete stderr stream was seen.
        stopped.stdout_prefix = bytes(output)
        stopped.stdout_observed_bytes = stdout_observed_bytes
        stopped.stderr_capture = bytes(errors)
        stopped.stderr_prefix = bytes(errors[:4096])
        stopped.stderr_observed_bytes = stderr_observed_bytes
        raise stopped from None
    finally:
        selector.close()
        if process is not None:
            process.stdout.close()
            process.stderr.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if cancelled[0] is not None:
            if stopped is not None:
                # Include a signal received during final pipe/selector cleanup.
                stopped.cancelled_signal = cancelled[0]
            elif process is None:
                raise CaptureStopped('interrupted-before-spawn', True, cancelled[0]) from None
    if cancelled[0] is not None:
        # Cancellation concurrent with a natural exit is still not successful.
        raise CaptureStopped('interrupted-by-signal-' + str(cancelled[0]), True, cancelled[0])
    return result


def source_identity(runner=capture):
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Missing source SHA')
    require(os.environ.get('GITHUB_WORKFLOW_SHA') == sha, 'Workflow/source mismatch')
    for arguments, expected in ((['git', 'rev-parse', 'HEAD'], sha),
                                (['git', 'diff', '--quiet', 'HEAD', '--'], '')):
        began = time.monotonic()
        result = runner(arguments, seconds=3, cap=4096)
        if time.monotonic() - began > 3:
            raise CaptureStopped('late-source-exit', True)
        require(result.returncode == 0 and result.stdout.decode().strip() == expected, 'Unverified source')
    run = {key: os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}
    require(all(re.fullmatch('[1-9][0-9]{0,19}', value) for value in run.values()), 'Missing current run identity')
    return {'sha': sha, 'workflow_sha': sha, 'run': run,
            'files': {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCES}}


def validate_case(value):
    require(isinstance(value, dict) and set(value) == {'case', 'token', 'event', 'started', 'epoch', 'pid'}, 'Invalid case fields')
    require(value['case'] in CASES and valid_uuid(value['token']), 'Wrong case/token')
    require(value['event'] in ('started', 'failed'), 'Wrong case event')
    require(number(value['started']) and number(value['epoch']) and
            0 < value['started'] <= value['epoch'] <= value['started'] + 240, 'Invalid case time')
    require(type(value['pid']) is int and (value['pid'] == 0 if value['event'] == 'started'
            else 1 <= value['pid'] <= 2**31 - 1), 'Missing observed app PID')
    return value


class CaseRetainer:
    def __init__(self):
        self.active = None
        self.states = {case: {'seen': False, 'begin': None, 'failure': None, 'ended': False}
                       for case in CASES}
        self.rejected = False

    def line(self, line):
        if self.rejected:
            return
        try:
            for case, name in XCTEST_CASES.items():
                if line.rstrip().endswith("Test Case '" + name + "' started."):
                    state = self.states[case]
                    require(self.active is None and not state['seen'], 'Repeated/overlapping target case')
                    state['seen'] = True
                    self.active = case
            if 'PALETTE_CASE ' in line:
                match = MARKER.search(line.rstrip())
                require(match is not None and self.active is not None, 'Unbound case marker')
                value = validate_case(strict_json(match.group(1)))
                require(value['case'] == self.active, 'Crossed testcase marker')
                state = self.states[self.active]
                if value['event'] == 'started':
                    require(state['begin'] is None and state['failure'] is None, 'Duplicate start')
                    require(all(other['begin'] is None or other['begin']['token'] != value['token']
                                for other in self.states.values()), 'Repeated testcase token')
                    state['begin'] = value
                else:
                    require(state['begin'] is not None and state['failure'] is None, 'Duplicate/unbound failure')
                    require(all(value[key] == state['begin'][key] for key in ('token', 'started', 'case')), 'Mismatched failure')
                    state['failure'] = value
            for case, name in XCTEST_CASES.items():
                for outcome in ('failed', 'passed'):
                    if ("Test Case '" + name + "' " + outcome + " (") in line:
                        state = self.states[case]
                        require(self.active == case and state['begin'] is not None and
                                (state['failure'] is not None) == (outcome == 'failed'), 'Inconsistent case outcome')
                        self.active = None
                        state['ended'] = True
        except (ValueError, TypeError, KeyError):
            self.rejected = True

    def result(self):
        if self.rejected or self.active is not None:
            return {'status': 'rejected-case-metadata'}
        cases = []
        for case, state in self.states.items():
            row = {'case': case, 'status': 'not-observed'}
            if state['ended']:
                row['status'] = 'bound-failure' if state['failure'] else 'no-target-failure'
                if state['failure']:
                    row['failure'] = state['failure']
            cases.append(row)
        return {'status': 'bound-failure' if any(row['status'] == 'bound-failure' for row in cases)
                else 'no-target-failure', 'cases': cases}


def retain(family):
    # This pipe preserves xcodebuild output, retaining no general test transcript.
    from uikit_runtime_diagnostics import read_identity
    require(family in {'iPhoneLarge', 'iPhoneCompact'}, 'Phone-only lifecycle diagnostic')
    path = Path('build') / (family + '-palette-case.json')
    started = time.time()
    parser = CaseRetainer()
    identity, source = None, None
    try:
        require(not path.exists() and not path.is_symlink(), 'Refusing stale case metadata')
        identity = read_identity(family)
        source = source_identity()
    except CaptureStopped as error:
        if error.cancelled_signal is not None:
            raise  # Explicit cancellation must not become a long-lived drain.
        parser.rejected = True
    except (ValueError, OSError, TypeError, KeyError, UnicodeError):
        # Still drain the pipe so a metadata failure never terminates xcodebuild.
        # Replace any stale regular record below with rejected metadata.
        parser.rejected = True
    # A line is bounded independently of arbitrary raw xcodebuild output. Oversize
    # lines are passed through but never parsed as metadata.
    fragment = bytearray()
    oversize = False
    while True:
        chunk = sys.stdin.buffer.read1(4096)
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        for part in chunk.splitlines(keepends=True):
            if not oversize:
                fragment.extend(part)
                if len(fragment) > 4096:
                    fragment.clear()
                    oversize = True
            if part.endswith(b'\n'):
                if not oversize:
                    parser.line(fragment.decode('utf-8', errors='replace'))
                fragment.clear()
                oversize = False
    if fragment:
        parser.line(fragment.decode('utf-8', errors='replace'))
    result = parser.result()
    result.update({'identity': identity, 'source': source, 'capture_started': started, 'capture_ended': time.time()})
    write_json(path, result, limit=MAX_RECORD)


def command_interval(identity, source):
    """Read the existing selected command receipt; retainer lifetime is not its interval."""
    from uikit_managed_tests import read_regular, record_path, test_argv, STEPS, CLEANUP, SUMMARY
    from uikit_managed_device import read_binding
    from uikit_completion import selection
    selected = selection(identity['family'], 'TouchColorUITests')
    require(selected is not None, 'Selected functional command proof unavailable')
    binding = read_binding(identity['family'])
    context = binding['context']
    require(binding['identity'] == identity and context['sha'] == source['sha'] and
            context['workflow_sha'] == source['workflow_sha'] and
            context['run_id'] == source['run']['GITHUB_RUN_ID'] and
            context['run_attempt'] == source['run']['GITHUB_RUN_ATTEMPT'], 'Foreign functional command source')
    raw = read_regular(record_path(identity['family'], 'TouchColorUITests'), 32768)
    value = strict_json(raw)
    require(isinstance(value, dict) and isinstance(value.get('setup'), dict) and
            isinstance(value.get('command'), dict) and isinstance(value.get('timing'), dict),
            'Malformed functional command receipt')
    require(value.get('schema') == 3 and type(value.get('schema')) is int and
            value.get('suite') == 'TouchColorUITests' and value.get('selection') == selected and
            value.get('setup', {}).get('binding') == binding and
            value.get('summary_qualification_only') is True and
            value.get('case_identity_basis') == 'fixed_executed_argv_and_complete_summary' and
            value.get('per_case_log_reconciliation') == 'pending_external_review', 'Wrong functional command receipt')
    command, timing = value.get('command', {}), value.get('timing', {})
    require(command.get('status') == 'timely_exit' and command.get('host_cleanup_confirmed') is True and
            type(command.get('exit_code')) is int and command['exit_code'] in (0, 65) and
            command.get('argv') == test_argv(identity['family'], 'TouchColorUITests', identity['udid']),
            'Unconfirmed or wrong functional command')
    keys = ('phase_started_monotonic', 'phase_deadline_monotonic', 'admitted_monotonic',
            'command_origin_monotonic', 'command_wall_started', 'command_wall_finished')
    require(all(number(timing.get(key)) for key in keys), 'Missing functional command timing')
    times = [command.get(key) for key in ('started_monotonic', 'finished_monotonic', 'deadline_monotonic')]
    seconds, grant = STEPS['TouchColorUITests'][:2]
    require(all(number(item) for item in times) and
            0 <= timing['phase_started_monotonic'] <= timing['admitted_monotonic'] <=
            timing['command_origin_monotonic'] <= times[0] <= times[1] < times[2] and
            timing['phase_deadline_monotonic'] == timing['phase_started_monotonic'] + seconds and
            times[2] == timing['command_origin_monotonic'] + grant and
            timing['admitted_monotonic'] + grant + 2 * CLEANUP + SUMMARY < timing['phase_deadline_monotonic'] and
            identity['started'] <= timing['command_wall_started'] <= timing['command_wall_finished'] <= time.time(),
            'Invalid original functional command interval')
    return {'source': context, 'receipt_sha256': hashlib.sha256(raw).hexdigest(), 'receipt_bytes': len(raw),
            'started': timing['command_wall_started'], 'ended': timing['command_wall_finished']}


def load_case(identity, runner=capture):
    from uikit_managed_tests import read_regular
    path = Path('build') / (identity['family'] + '-palette-case.json')
    if not path.exists() and not path.is_symlink():
        return None
    value = strict_json(read_regular(path, MAX_RECORD))
    require(isinstance(value, dict), 'Malformed case retention')
    require(value.get('identity') == identity, 'Case belongs to another owned simulator')
    require(value.get('source') == source_identity(runner), 'Case belongs to another source')
    require(value.get('status') == 'bound-failure', 'Case unavailable')
    rows = value.get('cases')
    require(isinstance(rows, list) and len(rows) == 2 and all(isinstance(row, dict) for row in rows) and
            [row.get('case') for row in rows] == list(CASES), 'Wrong two-case schema')
    command = command_interval(identity, value['source'])
    require(number(value['capture_started']) and number(value['capture_ended']) and
            identity['started'] <= value['capture_started'] <= value['capture_ended'] <= time.time(),
            'Invalid case retention interval')
    tokens, cases = set(), []
    for row in rows:
        require(row['status'] in ('bound-failure', 'no-target-failure', 'not-observed') and
                set(row) == ({'case', 'status', 'failure'} if row['status'] == 'bound-failure' else {'case', 'status'}),
                'Invalid case envelope')
        if row['status'] != 'bound-failure':
            continue
        case = validate_case(row['failure'])
        require(case['case'] == row['case'] and case['event'] == 'failed' and case['token'] not in tokens and
                value['capture_started'] <= case['started'] <= case['epoch'] <= value['capture_ended'] and
                command['started'] <= case['started'] <= case['epoch'] <= command['ended'],
                'Case outside actual functional command or crossed identity')
        tokens.add(case['token']); cases.append(case)
    require(cases, 'No current failed case')
    value['command_interval'] = command
    return value


def failed_cases(value):
    return [row['failure'] for row in value['cases'] if row['status'] == 'bound-failure']


def log_command(identity, cases):
    # One explicitly broader outer union. Every event is rechecked against its
    # own exact <=240-second case interval, inside the original functional argv.
    require(1 <= len(cases) <= 2, 'Wrong query branch count')
    start = datetime.datetime.fromtimestamp(math.floor(min(case['started'] for case in cases)), datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(math.ceil(max(case['epoch'] for case in cases)), datetime.timezone.utc)
    branches = ['(processID == %d AND eventMessage CONTAINS "%s")' % (case['pid'], case['token']) for case in cases]
    predicate = ('process == "TouchColor" AND eventMessage BEGINSWITH "PALETTE_LIFECYCLE " AND (' +
                 ' OR '.join(branches) + ')')
    return ['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'show', '--style', 'json',
            '--start', start.strftime('%Y-%m-%d %H:%M:%S%z'), '--end', end.strftime('%Y-%m-%d %H:%M:%S%z'),
            '--predicate', predicate]


def case_envelopes(value):
    rows = []
    for row in value['cases']:
        item = {'case': row['case'], 'status': row['status']}
        if row['status'] == 'bound-failure':
            case = row['failure']
            item.update({key: case[key] for key in ('token', 'pid', 'started', 'epoch')})
            item['controller'] = 'PhonePaletteImportController'
        rows.append(item)
    return rows


class ObservationOverflow(ValueError):
    pass


def lifecycle_rows(raw, cases):
    records = strict_json(raw)
    require(isinstance(records, list), 'Unexpected log record shape')
    if len(records) > 24:
        raise ObservationOverflow('combined-event-limit')
    rows, seen = [], set()
    expected = set(BOOL_FIELDS + TYPE_FIELDS) | {'event', 'token', 'pid', 'epoch', 'presentation', 'sequence'}
    for record in records:
        require(isinstance(record, dict) and type(record.get('processID')) is int, 'Wrong process receipt')
        require(isinstance(record.get('processImagePath'), str) and
                record['processImagePath'].endswith('/TouchColor.app/TouchColor'), 'Wrong app receipt')
        message = record.get('eventMessage')
        require(isinstance(message, str) and message.startswith(PREFIX), 'Wrong message receipt')
        value = strict_json(message[len(PREFIX):])
        require(isinstance(value, dict) and set(value) == expected, 'Wrong lifecycle fields')
        matches = [case for case in cases if value['token'] == case['token'] and
                   type(value['pid']) is int and value['pid'] == case['pid'] == record['processID']]
        require(len(matches) == 1, 'Wrong or ambiguous case correlation')
        case = matches[0]; case_index = CASES.index(case['case'])
        require(valid_uuid(value['presentation']) and type(value['sequence']) is int and 1 <= value['sequence'] <= 24, 'Wrong presentation identity')
        require(value['event'] in EVENTS and value['controller'] == 'PhonePaletteImportController', 'Wrong event/controller')
        require(number(value['epoch']) and case['started'] <= value['epoch'] <= case['epoch'], 'Outside own test window')
        require(all(type(value[key]) is bool for key in BOOL_FIELDS), 'Wrong lifecycle boolean')
        require(all(isinstance(value[key], str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_.]{0,79}', value[key]) for key in TYPE_FIELDS), 'Wrong lifecycle type')
        key = (value['presentation'], value['sequence'])
        require(key not in seen, 'Duplicate lifecycle receipt')
        seen.add(key)
        rows.append({'case_index': case_index, **{key: item for key, item in value.items()
                                               if key not in ('token', 'pid', 'controller')}})
    rows.sort(key=lambda value: (value['epoch'], value['case_index'], value['presentation'], value['sequence']))
    return rows


def confirmed_help(kind, process):
    """Recognize complete usage/option/typed-key records, never keyword prose.

    These parsers accept a deliberately narrow documented help layout. They do
    not claim the target tool uses that layout; an unknown layout is unavailable.
    """
    if process.returncode not in (0, 64) or len(process.stdout) + len(process.stderr) > 32 * 1024:
        return False
    try:
        text = (process.stdout + b'\n' + process.stderr).decode('utf-8')
    except UnicodeError:
        return False
    if re.search(r'\b(?:unsupported|unrecognized|unavailable|unknown (?:option|key|command|format)|invalid option|not[^\n]*(?:supported|available|recognized|implemented))\b|^\s*(?:log:\s*)?error:', text, re.I | re.M):
        return False
    lines = text.splitlines()
    if kind == 'spawn':
        usage = [line.strip() for line in lines if line.lstrip().startswith('Usage:')]
        return len(usage) == 1 and re.fullmatch(
            r'Usage: simctl spawn (?:\[[^\n\]]+\] )*<device> <path to executable> '
            r'\[<argv 1> <argv 2> \.\.\. <argv n>\]', usage[0]) is not None
    if kind == 'show':
        usage = [line.strip() for line in lines if line.lstrip().startswith('usage:')]
        if len(usage) != 1 or usage[0] not in ('usage: log show [options]', 'usage: log show [options] <archive>'):
            return False
        headers = [index for index, line in enumerate(lines) if line.strip() == 'options:']
        if len(headers) != 1:
            return False
        options = {}
        for line in lines[headers[0] + 1:]:
            if not line.strip():
                continue
            if not line[0].isspace():
                break
            match = re.fullmatch(r'\s+(--[a-z-]+)\s+<([a-z]+)>\s+(.+)', line)
            if match and match[1] in {'--style', '--start', '--end', '--predicate'}:
                if match[1] in options:
                    return False
                options[match[1]] = (match[2], match[3])
        expected = {'--style': 'style', '--start': 'date', '--end': 'date', '--predicate': 'predicate'}
        if set(options) != set(expected) or any(options[key][0] != value for key, value in expected.items()):
            return False
        formats = re.findall(r'\(valid:\s*([a-z]+(?:\s*,\s*[a-z]+)*)\)', options['--style'][1])
        return len(formats) == 1 and 'json' in re.split(r'\s*,\s*', formats[0])
    if kind == 'predicates':
        headers = [index for index, line in enumerate(lines) if line.strip() == 'valid predicate fields:']
        if len(headers) != 1:
            return False
        fields = {}
        for line in lines[headers[0] + 1:]:
            if not line.strip():
                continue
            if not line[0].isspace():
                break
            match = re.fullmatch(r'\s+([A-Za-z][A-Za-z0-9]{0,79})\s+\(([a-z ]{1,32})\)\s*', line)
            if match is None or match[1] in fields:
                return False
            fields[match[1]] = match[2]
        return all(fields.get(key) == value for key, value in
                   {'processID': 'integer', 'process': 'string', 'eventMessage': 'string'}.items())
    return False


def help_commands(identity):
    return [(['xcrun', 'simctl', 'help', 'spawn'], 'spawn'),
            (['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'help', 'show'], 'show'),
            (['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'help', 'predicates'], 'predicates')]


def help_has_error(process):
    if type(process.returncode) is not int or process.returncode not in (0, 64):
        return True
    try:
        text = (process.stdout + b'\n' + process.stderr).decode('utf-8')
    except UnicodeError:
        return True
    if not text.strip():
        return True
    # Complete help may discuss failed operations. Only diagnostic-shaped lines
    # are error evidence; prose keywords neither establish failure nor support.
    diagnostic = re.compile(
        r'^(?:(?:log|simctl|xcrun):\s*)?(?:error(?::|\s+Domain=)|'
        r'(?:unsupported|unrecognized|unavailable)(?::|$| (?:option|flag|argument|key|command|format)\b)|'
        r'unknown (?:option|flag|argument|key|command|format)\b|invalid option\b|'
        r'not (?:supported|available|recognized|implemented)\b|permission denied\b|'
        r'operation not permitted\b|access denied\b|insufficient privileges\b|must be root\b|'
        r'not authorized\b|failed to\b|failure:|'
        r'an error was encountered processing the command\b|'
        r'(?:access to logs|this (?:command|operation)) requires? (?:administrator|root) privileges\b)|'
        r'^(?:log|simctl|xcrun):\s*(?:failed|failure)\b', re.I)
    return any(diagnostic.search(line.strip()) is not None for line in text.splitlines())



def stream_receipt(raw, *, complete, observed=None):
    return {'base64': base64.b64encode(raw).decode('ascii'), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'complete': complete,
            'observed_bytes': len(raw) if observed is None else observed}


def emit_help_receipts(records):
    require(len(records) == 3, 'Expected three fixed help stages')
    lines = [HELP_FRAME + json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in records]
    require(sum(len(line.encode()) + 128 for line in lines) <= MAX_HELP_LOG_BYTES,
            'Complete help framing exceeds phone allocation')
    for line in lines:
        print(line, end='', flush=True)


def collect_lifecycle(identity, runner=capture):
    result = {'status': 'unavailable', 'simulator_commands_completed': True, 'events': []}
    # One original 35s acquisition, including 2x3s source checks, 3x3s help,
    # one <=8s query and the unchanged two 2s owned cleanup phases.
    deadline = time.monotonic() + 35
    help_records = []
    acquired = 0
    def bounded(command, *, seconds, cap):
        nonlocal acquired
        granted = min(seconds, deadline - time.monotonic() - 4)
        require(granted > 0, 'No shared acquisition budget')
        process = runner(command, seconds=granted, cap=cap)
        count = len(process.stdout) + len(process.stderr)
        acquired += count
        if count > cap or acquired > MAX_ACQUISITION_BYTES:
            error = CaptureStopped('byte-limit', True)
            error.stdout_prefix = process.stdout[:cap]
            error.stderr_capture = process.stderr[:max(0, cap - len(error.stdout_prefix))]
            error.stdout_observed_bytes = len(process.stdout)
            error.stderr_observed_bytes = len(process.stderr)
            raise error
        return process
    try:
        value = load_case(identity, runner=bounded)
        if value is None:
            result['reason'] = 'no-current-case-metadata'
            return result
        cases = failed_cases(value)
        envelopes = case_envelopes(value)
        interval = value['command_interval']
        result.update({'source_sha': value['source']['sha'], 'cases': envelopes,
                       'functional_command': {key: item for key, item in interval.items() if key != 'source'},
                       'query_window': {'case_union_started': min(case['started'] for case in cases),
                                        'case_union_ended': max(case['epoch'] for case in cases),
                                        'query_started': math.floor(min(case['started'] for case in cases)),
                                        'query_ended': math.ceil(max(case['epoch'] for case in cases)),
                                        'scope': 'outer_union_only_each_event_uses_own_case_window'}})
        for command, kind in help_commands(identity):
            help_records.append({'schema': 1, 'family': identity['family'], 'deviceId': identity['udid'],
                'source': interval['source'], 'stage': kind, 'argv': command, 'status': 'not_requested',
                'exit_code': None, 'started_monotonic': None, 'deadline_monotonic': None,
                'returned_monotonic': None, 'complete': False, 'recognized_layout': False,
                'stdout': stream_receipt(b'', complete=False), 'stderr': stream_receipt(b'', complete=False)})
        recognized = True
        for row in help_records:
            granted = min(3, deadline - time.monotonic() - 4)
            require(granted > 0, 'No help budget')
            began = time.monotonic()
            row.update(status='running', started_monotonic=began, deadline_monotonic=began + granted)
            try:
                process = bounded(row['argv'], seconds=granted, cap=32 * 1024)
            except CaptureStopped as error:
                row.update(status='incomplete', returned_monotonic=time.monotonic(),
                           host_client_cleanup_confirmed=error.cleanup_confirmed,
                           stdout=stream_receipt(getattr(error, 'stdout_prefix', b''), complete=False,
                               observed=getattr(error, 'stdout_observed_bytes', 0)),
                           stderr=stream_receipt(getattr(error, 'stderr_capture', getattr(error, 'stderr_prefix', b'')),
                               complete=False, observed=getattr(error, 'stderr_observed_bytes', 0)))
                raise
            finished = time.monotonic()
            row.update(exit_code=process.returncode, returned_monotonic=finished,
                       stdout=stream_receipt(process.stdout, complete=True),
                       stderr=stream_receipt(process.stderr, complete=True))
            if finished > began + granted:
                row['status'] = 'late-exit'
                raise CaptureStopped('late-help-exit', True)
            row.update(status='complete', complete=True,
                       recognized_layout=confirmed_help(row['stage'], process))
            if help_has_error(process):
                row['status'] = 'complete-error'
                result['reason'] = 'help-command-error'
                return result
            recognized = recognized and row['recognized_layout']
        # Unknown layout alone does not authorize new argv or prove support.
        # This is the one source-reviewed compatibility attempt, never fallback.
        result['query_route'] = 'recognized-help' if recognized else 'fixed-query-compatibility'
        granted = min(8, deadline - time.monotonic() - 4)
        require(granted > 0, 'No query budget')
        began = time.monotonic()
        result['query_argv'] = log_command(identity, cases)
        process = bounded(result['query_argv'], seconds=granted, cap=256 * 1024)
        if time.monotonic() - began > granted:
            raise CaptureStopped('late-query-exit', True)
        if process.returncode != 0 or help_has_error(process):
            result['reason'] = 'query-failed'
            return result
        events = lifecycle_rows(process.stdout, cases)
        observation = {'cases': envelopes, 'events': events}
        if len(json.dumps(observation, sort_keys=True, separators=(',', ':')).encode()) > MAX_RECORD:
            raise ObservationOverflow('sanitized-byte-limit')
        require(time.monotonic() <= deadline, 'Observation exceeded original acquisition clock')
        result['events'] = events
        result['status'] = 'receipts-retained' if events else 'observation-gap'
        result['reason'] = 'absence-does-not-prove-nondelivery'
    except ObservationOverflow as error:
        result.update(status='unknown', reason=str(error), events=[], observation_complete=False)
    except CaptureStopped as error:
        result.update({'reason': 'command-exit-unconfirmed', 'simulator_commands_completed': False,
                       'host_client_cleanup_confirmed': error.cleanup_confirmed})
    except (ValueError, OSError, TypeError, KeyError, UnicodeError):
        result['reason'] = 'invalid-or-unavailable-evidence'
    finally:
        if help_records:
            emit_help_receipts(help_records)
            # Host output is bounded by bytes inside the existing diagnostic
            # tail. A late write cannot preserve a successful observation under
            # the original clock, or undo an already observed command exit.
            if time.monotonic() > deadline and result['status'] in ('receipts-retained', 'observation-gap'):
                result.update(status='unavailable', reason='help-output-exceeded-original-clock',
                              events=[], observation_complete=False)
    return result


if __name__ == '__main__':
    require(len(sys.argv) == 3 and sys.argv[1] == 'retain', 'Expected retain and phone family')
    retain(sys.argv[2])
