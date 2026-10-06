"""Retain one failed phone palette case and query only its app lifecycle receipts.

No logging configuration, log archive, process inventory or fallback query. The
query is unavailable unless target help confirms this one documented route.
Acquisition and both pipes have finite caps, before JSON parsing/retention.
"""
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

CASE = 'testInvalidPalettePastePreservesHistory'
XCTEST_CASE = '-[TouchColorUITests ' + CASE + ']'
PREFIX = 'PALETTE_LIFECYCLE '
MARKER = re.compile(r'TouchColorUITests-Runner\[[1-9][0-9]*:[0-9]+\] PALETTE_CASE (\{.*\})$')
SOURCES = ('TouchColorPhoneCompanion/PhonePaletteImportController.swift',
           'TouchColorUITests/TouchColorUITests.m', 'TouchColorUITests/TCPaletteUIHelpers.m',
           'scripts/palette_lifecycle_diagnostics.py', 'scripts/test_simulators.sh')
BOOL_FIELDS = ('visible', 'dismissing', 'navigationDismissing', 'transition', 'busy', 'finished')
TYPE_FIELDS = ('controller', 'presenter', 'presented', 'navigationPresenter', 'navigationPresented')
EVENTS = {'appeared', 'file-present-requested', 'file-present-completed',
          'close-action-received', 'close-dismiss-completed', 'disappeared', 'finished'}
MAX_RECORD = 12 * 1024


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
    errors = bytearray()
    stderr_observed_bytes = 0
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
                if key.fileobj is process.stderr:
                    stderr_observed_bytes += len(data)
                if total > cap:
                    if key.fileobj is process.stderr:
                        # Count the already-read overflow chunk, but retain only
                        # the prefix that still fits the original capture cap.
                        errors.extend(data[:max(0, min(4096-len(errors), cap+len(data)-total))])
                    raise RuntimeError('byte-limit')
                if key.fileobj is process.stdout:
                    output.extend(data)
                else:
                    errors.extend(data)
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
        result = runner(arguments, seconds=3, cap=4096)
        require(result.returncode == 0 and result.stdout.decode().strip() == expected, 'Unverified source')
    run = {key: os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}
    require(all(re.fullmatch('[1-9][0-9]{0,19}', value) for value in run.values()), 'Missing current run identity')
    return {'sha': sha, 'workflow_sha': sha, 'run': run,
            'files': {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCES}}


def validate_case(value):
    require(isinstance(value, dict) and set(value) == {'case', 'token', 'event', 'started', 'epoch', 'pid'}, 'Invalid case fields')
    require(value['case'] == CASE and valid_uuid(value['token']), 'Wrong case/token')
    require(value['event'] in ('started', 'failed'), 'Wrong case event')
    require(number(value['started']) and number(value['epoch']) and
            0 < value['started'] <= value['epoch'] <= value['started'] + 240, 'Invalid case time')
    require(type(value['pid']) is int and (value['pid'] == 0 if value['event'] == 'started'
            else 1 <= value['pid'] <= 2**31 - 1), 'Missing observed app PID')
    return value


class CaseRetainer:
    def __init__(self):
        self.active = False
        self.seen = False
        self.begin = None
        self.failure = None
        self.ended = False
        self.rejected = False

    def line(self, line):
        if self.rejected:
            return
        try:
            if line.rstrip().endswith("Test Case '" + XCTEST_CASE + "' started."):
                require(not self.seen, 'Repeated target case')
                self.seen = self.active = True
            if 'PALETTE_CASE ' in line:
                match = MARKER.search(line.rstrip())
                require(match is not None and self.active, 'Unbound case marker')
                value = validate_case(strict_json(match.group(1)))
                if value['event'] == 'started':
                    require(self.begin is None and self.failure is None, 'Duplicate start')
                    self.begin = value
                else:
                    require(self.begin is not None and self.failure is None, 'Duplicate/unbound failure')
                    require(all(value[key] == self.begin[key] for key in ('token', 'started', 'case')), 'Mismatched failure')
                    self.failure = value
            if ("Test Case '" + XCTEST_CASE + "' failed (") in line:
                require(self.active and self.failure is not None, 'Missing failed-case metadata')
                self.active = False
                self.ended = True
            elif ("Test Case '" + XCTEST_CASE + "' passed (") in line:
                require(self.active and self.failure is None, 'Inconsistent case outcome')
                self.active = False
        except (ValueError, TypeError, KeyError):
            self.rejected = True

    def result(self):
        if self.rejected or (self.failure is not None and not self.ended):
            return {'status': 'rejected-case-metadata'}
        if self.failure is None:
            return {'status': 'no-target-failure'}
        return {'status': 'bound-failure', 'case': self.failure}


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


def load_case(identity):
    path = Path('build') / (identity['family'] + '-palette-case.json')
    if not path.is_file():
        return None
    require(not path.is_symlink() and not path.parent.is_symlink(), 'Unsafe case metadata path')
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD + 1)
    require(len(raw) <= MAX_RECORD, 'Oversized case metadata')
    value = strict_json(raw)
    require(value.get('identity') == identity, 'Case belongs to another owned simulator')
    require(value.get('source') == source_identity(), 'Case belongs to another source')
    require(value.get('status') == 'bound-failure', 'Case unavailable')
    case = validate_case(value['case'])
    require(case['event'] == 'failed' and number(value['capture_started']) and number(value['capture_ended']) and
            identity['started'] <= value['capture_started'] <= case['started'] <= case['epoch'] <= value['capture_ended'] <= time.time(),
            'Case outside current test execution')
    return value


def log_command(identity, case):
    # Date arguments are rounded outward by at most one second. Each event's exact
    # app timestamp is checked again before retaining any field.
    start = datetime.datetime.fromtimestamp(math.floor(case['started']), datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(math.ceil(case['epoch']), datetime.timezone.utc)
    predicate = ('processID == %d AND process == "TouchColor" AND eventMessage BEGINSWITH "PALETTE_LIFECYCLE " '
                 'AND eventMessage CONTAINS "%s"' % (case['pid'], case['token']))
    return ['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'show', '--style', 'json',
            '--start', start.strftime('%Y-%m-%d %H:%M:%S%z'), '--end', end.strftime('%Y-%m-%d %H:%M:%S%z'),
            '--predicate', predicate]


def lifecycle_rows(raw, case):
    records = strict_json(raw)
    require(isinstance(records, list) and len(records) <= 24, 'Unexpected log record count')
    rows, seen = [], set()
    expected = set(BOOL_FIELDS + TYPE_FIELDS) | {'event', 'token', 'pid', 'epoch', 'presentation', 'sequence'}
    for record in records:
        require(isinstance(record, dict) and type(record.get('processID')) is int and record['processID'] == case['pid'], 'Wrong process receipt')
        require(record.get('processImagePath', '').endswith('/TouchColor.app/TouchColor'), 'Wrong app receipt')
        message = record.get('eventMessage')
        require(isinstance(message, str) and message.startswith(PREFIX), 'Wrong message receipt')
        value = strict_json(message[len(PREFIX):])
        require(isinstance(value, dict) and set(value) == expected, 'Wrong lifecycle fields')
        require(value['token'] == case['token'] and type(value['pid']) is int and value['pid'] == case['pid'], 'Wrong correlation')
        require(valid_uuid(value['presentation']) and type(value['sequence']) is int and 1 <= value['sequence'] <= 24, 'Wrong presentation identity')
        require(value['event'] in EVENTS and value['controller'] == 'PhonePaletteImportController', 'Wrong event/controller')
        require(number(value['epoch']) and case['started'] <= value['epoch'] <= case['epoch'], 'Outside test window')
        require(all(type(value[key]) is bool for key in BOOL_FIELDS), 'Wrong lifecycle boolean')
        require(all(isinstance(value[key], str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_.]{0,79}', value[key]) for key in TYPE_FIELDS), 'Wrong lifecycle type')
        key = (value['presentation'], value['sequence'])
        require(key not in seen, 'Duplicate lifecycle receipt')
        seen.add(key)
        rows.append(value)
    rows.sort(key=lambda value: (value['epoch'], value['presentation'], value['sequence']))
    require(len(json.dumps(rows).encode()) <= MAX_RECORD, 'Oversized sanitized receipt')
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


def collect_lifecycle(identity, runner=capture):
    result = {'status': 'unavailable', 'simulator_commands_completed': True, 'events': []}
    # 35 seconds including source checks, help, query and a 4-second cleanup
    # reserve. This fits beside the existing 3+20-second service query in 2min.
    deadline = time.monotonic() + 35
    try:
        value = load_case(identity)
        if value is None:
            result['reason'] = 'no-current-case-metadata'
            return result
        case = value['case']
        result.update({'case': CASE, 'source_sha': value['source']['sha'], 'token': case['token'],
                       'failed_pid': case['pid'], 'started': case['started'], 'failed': case['epoch']})
        commands = [(['xcrun', 'simctl', 'help', 'spawn'], 'spawn'),
                    (['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'help', 'show'], 'show'),
                    (['xcrun', 'simctl', 'spawn', identity['udid'], 'log', 'help', 'predicates'], 'predicates')]
        for command, kind in commands:
            granted = min(3, deadline - time.monotonic() - 4)
            require(granted > 0, 'No help budget')
            began = time.monotonic()
            process = runner(command, seconds=granted, cap=32 * 1024)
            if time.monotonic() - began > granted:
                raise CaptureStopped('late-help-exit', True)
            if not confirmed_help(kind, process):
                result['reason'] = 'documented-route-not-confirmed'
                return result
        granted = min(8, deadline - time.monotonic() - 4)
        require(granted > 0, 'No query budget')
        began = time.monotonic()
        process = runner(log_command(identity, case), seconds=granted, cap=256 * 1024)
        if time.monotonic() - began > granted:
            raise CaptureStopped('late-query-exit', True)
        if process.returncode != 0:
            result['reason'] = 'query-failed'
            return result
        result['events'] = lifecycle_rows(process.stdout, case)
        result['status'] = 'receipts-retained' if result['events'] else 'observation-gap'
        result['reason'] = 'absence-does-not-prove-nondelivery'
    except CaptureStopped as error:
        result.update({'reason': 'command-exit-unconfirmed', 'simulator_commands_completed': False,
                       'host_client_cleanup_confirmed': error.cleanup_confirmed})
    except (ValueError, OSError, TypeError, KeyError, UnicodeError):
        result['reason'] = 'invalid-or-unavailable-evidence'
    return result


if __name__ == '__main__':
    require(len(sys.argv) == 3 and sys.argv[1] == 'retain', 'Expected retain and phone family')
    retain(sys.argv[2])
