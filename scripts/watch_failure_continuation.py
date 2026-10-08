"""Schedule independent Watch coverage without reclassifying a failed result.

Exit 65 remains a failure. Only complete, consistent result/lifecycle evidence,
no recorded timeout, and unchanged source/products/owned destination permit the
existing largest-text scope to start. This is not assertion-kind certification.
"""
import datetime
import hashlib
import json
import math
import re
import os
import stat
import time
from pathlib import Path
import subprocess

from bounded_process import run_captured

BUNDLE = 'build/watch-ui.xcresult'
TARGET = 'TouchColorWatchUITests'
SKIPPED_CASE = 'WatchPairedTransferTests/testForegroundSendAcceptReceiptAndBothLocalStatesAfterRelaunch()'
NORMAL_CASES = (
    'WatchWorkflowTests/testNativeRGBEditSaveDuplicateAndOfflineRelaunch()',
    'WatchWorkflowTests/testChineseColorEditorSave()',
    'WatchWorkflowTests/testRealPhotoPickerSimulatorUnavailableAndCloseKeepsPalette()',
    'WatchWorkflowTests/testOfficialAccessibilitySavedListSendAndCancel()',
    'WatchWorkflowTests/testOfficialAccessibilityHomeAndColorEditor()',
    'WatchWorkflowTests/testExplicitOfflineTransferRequestSurvivesRelaunchUntilUserCancels()',
    'WatchWorkflowTests/testRealDigitalCrownChangesRGBComponent()',
    'WatchWorkflowTests/testHomeListDigitalCrownFromColdLaunch()',
    'WatchWorkflowTests/testEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()',
    'WatchWorkflowTests/testTouchEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder()',
    SKIPPED_CASE,
)
COUNTS = ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures')
MAX_SUMMARY_BYTES = 500_000
TIMEOUT = re.compile(r'exceeded execution time allowance|execution time.*exceeded|\btimed? out\b|\btime[ -]?out\b|test may have hung', re.I)


def _require(condition, reason):
    if not condition: raise ValueError(reason)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _timestamp(value):
    parsed = datetime.datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None, 'command timestamp has no timezone')
    return parsed.timestamp()


def _counts(value):
    for key in COUNTS:
        _require(type(value.get(key)) is int and value[key] >= 0, 'invalid count: ' + key)
    return {key: value[key] for key in COUNTS}


def _stage(stage, command, cleanup_unconfirmed):
    _require(not cleanup_unconfirmed, 'prior cleanup is unconfirmed')
    _require(type(stage.get('exit')) is int and stage['exit'] == 65, 'normal exit is not 65')
    _require(stage.get('command') == command, 'normal command does not match')
    _require(stage.get('started') is True, 'normal command was not confirmed started')
    _require(stage.get('process_group_gone') is True, 'owned process-group cleanup is unconfirmed')
    _require(stage.get('capture_reader_finished') is True, 'capture-reader cleanup is unconfirmed')
    _require(stage.get('reader_errors') == [] and stage.get('cleanup_error') is None,
             'normal command cleanup is contradictory')
    _require(stage.get('timed_out') is False, 'normal command timeout state is unknown or timed out')
    _require(stage.get('raw_exit') == 65 and type(stage['raw_exit']) is int,
             'exit 65 was synthesized rather than returned by xcodebuild')
    _require(not stage.get('budget_incomplete'), 'normal command budget is incomplete')
    start, finish = _timestamp(stage['started_at']), _timestamp(stage['finished_at'])
    elapsed, wall, limit = (stage.get(key) for key in ('elapsed_seconds', 'wall_elapsed_seconds', 'timeout_seconds'))
    _require(all(_number(value) for value in (elapsed, wall, limit)), 'invalid command timing')
    _require(0 < finish - start <= 840 and 0 < elapsed < limit <= 840 and 0 < wall < limit,
             'normal command reached its bound or has invalid timing')
    _require(abs(wall - elapsed) <= 1 and abs((finish - start) - wall) <= 1,
             'command clocks contradict each other')
    return start, finish


def decision(stage, command, summary, before, after, *, sha, device, cleanup_unconfirmed=False):
    """No failure text, known-error allowlist, retry, or green-result conversion."""
    result = {'allowed': False, 'reason': 'incomplete scheduling evidence'}
    try:
        start, finish = _stage(stage, command, cleanup_unconfirmed)
        _require(isinstance(summary, dict), 'missing structured result summary')
        counts = _counts(summary)
        _require(summary.get('result') == 'Failed', 'summary is not failed')
        _require(type(summary.get('totalTestCount')) is int and summary['totalTestCount'] == len(NORMAL_CASES),
                 'normal test inventory count is incomplete or mismatched')
        _require(counts['failedTests'] > 0 and counts['expectedFailures'] == 0
                 and counts['skippedTests'] == 1
                 and sum(counts.values()) == len(NORMAL_CASES), 'summary counts contradict the required scope')
        rows = summary.get('devicesAndConfigurations')
        _require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
                 'summary destination/configuration is ambiguous')
        row = rows[0]
        _require(_counts(row) == counts, 'destination counts contradict summary')
        expected_device = {'deviceId': device, 'platform': 'watchOS Simulator', 'osVersion': '27.0', 'architecture': 'arm64'}
        _require(isinstance(row.get('device'), dict) and all(row['device'].get(k) == v for k, v in expected_device.items()),
                 'summary device/runtime/architecture mismatch')
        configuration = {'configurationId': '1', 'configurationName': 'Test Scheme Action'}
        _require(row.get('testPlanConfiguration') == configuration, 'unexpected test configuration')
        s, f = summary.get('startTime'), summary.get('finishTime')
        _require(_number(s) and _number(f) and start <= s < f <= finish,
                 'result is incomplete, stale or outside the command lifetime')
        _require(not recorded_timeout(summary), 'structured result records a timeout')
        _require(not recorded_timeout(stage.get('compiler_errors', [])), 'normal diagnostics record a timeout')
        failures = summary.get('testFailures')
        _require(isinstance(failures, list) and len(failures) == counts['failedTests'],
                 'missing or duplicate summary failures')
        failure_ids = []
        for failure in failures:
            _require(isinstance(failure, dict) and failure.get('targetName') == TARGET,
                     'failure target mismatch')
            identifier = failure.get('testIdentifierString')
            _require(identifier in NORMAL_CASES and identifier != SKIPPED_CASE, 'unknown failed test')
            expected_url = 'test://com.apple.xcode/TouchColorWatch/' + TARGET + '/' + identifier.removesuffix('()')
            _require(failure.get('testIdentifierURL') == expected_url, 'failure identifier URL mismatch')
            failure_ids.append(identifier)
        _require(len(set(failure_ids)) == len(failure_ids), 'duplicate failed test')
        _require(isinstance(before, dict) and before.get('available') is True and before == after,
                 'source, built products or owned device unavailable/changed')
        _require(before.get('sha') == sha and before.get('device', {}).get('udid') == device,
                 'checkpoint source/device mismatch')
        capture = stage.get('watch_case_lifecycle')
        _require(isinstance(capture, dict) and capture.get('invalid') == 0
                 and type(capture.get('invalid')) is int and capture.get('overflow') is False
                 and capture.get('timeout_records') == [], 'case lifecycle incomplete or timeout recorded')
        cases = capture.get('cases')
        _require(isinstance(cases, list) and len(cases) == len(NORMAL_CASES), 'case completion inventory incomplete')
        observed = set(); failed = set(); totals = dict.fromkeys(COUNTS, 0); total_duration = 0
        for case in cases:
            _require(isinstance(case, dict), 'invalid case record')
            identifier = case.get('identifier')
            _require(identifier in NORMAL_CASES and identifier not in observed, 'duplicate or foreign case record')
            observed.add(identifier)
            duration = case.get('duration_seconds')
            cap = 240 if 'Chinese' in identifier else 120
            _require(_number(duration) and 0 <= duration < cap, 'case reached its execution allowance')
            total_duration += duration
            _require(case.get('started') is True, 'case finish lacks a start')
            status = case.get('result')
            if status == 'skipped':
                _require(identifier == SKIPPED_CASE, 'unexpected skipped case')
                totals['skippedTests'] += 1
            elif status in ('passed', 'failed'):
                _require(identifier != SKIPPED_CASE, 'dedicated paired case did not skip')
                totals['passedTests' if status == 'passed' else 'failedTests'] += 1
                if status == 'failed': failed.add(identifier)
            else: raise ValueError('nonterminal or unknown case result')
        _require(total_duration <= f - s + len(NORMAL_CASES) * 0.001, 'case durations exceed result lifetime')
        _require(capture.get('active') is None and observed == set(NORMAL_CASES), 'case execution was partial')
        _require(totals == counts and failed == set(failure_ids), 'case outcomes contradict structured summary')
        result.update(allowed=True, reason='independent_coverage_after_failed_normal_ui',
                      original_exit=65, original_result='failed', failed_tests=sorted(failed))
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        result['reason'] = str(error)[:500]
    return result


def recorded_timeout(value):
    # This is a conservative negative scheduling veto, never a failure-kind
    # allowlist. Summary retains diagnostics the console may have omitted.
    pending = [value]; visited = 0
    while pending:
        current = pending.pop(); visited += 1
        _require(visited <= 20_000, 'diagnostic structure exceeds finite bound')
        if isinstance(current, str) and TIMEOUT.search(current): return True
        if isinstance(current, dict): pending.extend(current.values())
        elif isinstance(current, list): pending.extend(current)
    return False


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, val in values:
            _require(key not in result, 'duplicate JSON key')
            result[key] = val
        return result
    def invalid(value): raise ValueError('nonfinite JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class WatchCaseLifecycle:
    """Bounded standard XCTest terminal records, not a typed failure classifier.

    The exact-device xcresult summary independently reconciles these records.
    Unrecognized/partial case lines, retries and recorded timeouts stop later UI.
    """
    def __init__(self):
        self.report = {'cases': [], 'active': None, 'invalid': 0, 'overflow': False, 'timeout_records': []}

    def record(self, line):
        # Negative timeout evidence is never used as positive proof of a kind of
        # failure. Keep the diagnostic itself; unknown failures remain failures.
        if TIMEOUT.search(line):
            if len(self.report['timeout_records']) < 8:
                self.report['timeout_records'].append(line.rstrip()[:500])
            else: self.report['overflow'] = True
        if not line.startswith('Test Case '): return
        if len(line.encode('utf-8')) > 2048:
            self.report['invalid'] += 1; return
        match = re.fullmatch(r"Test Case '-\[TouchColorWatchUITests\.(\w+) (\w+)\]' (started\.|(passed|failed|skipped) \(([0-9]+(?:\.[0-9]+)?) seconds\)\.)\s*", line)
        if match is None:
            self.report['invalid'] += 1; return
        identifier = match[1] + '/' + match[2] + '()'
        if identifier not in NORMAL_CASES:
            self.report['invalid'] += 1; return
        if match[3] == 'started.':
            if self.report['active'] is not None or any(case['identifier'] == identifier for case in self.report['cases']):
                self.report['invalid'] += 1
            self.report['active'] = identifier
            return
        if len(self.report['cases']) >= len(NORMAL_CASES):
            self.report['overflow'] = True; return
        self.report['cases'].append({'identifier': identifier, 'result': match[4],
            'duration_seconds': float(match[5]), 'started': self.report['active'] == identifier})
        if self.report['active'] != identifier: self.report['invalid'] += 1
        self.report['active'] = None


def product_fingerprint(root, *, clock=time.monotonic):
    """Read-only, finite fingerprint of the existing build-for-testing products."""
    from job_budget import enabled_budget
    budget = enabled_budget()
    if budget is not None: budget.admit('Watch product fingerprint', 20, minimum=20, cleanup=0)
    root = Path(root)
    _require(root.is_dir() and not root.is_symlink(), 'built products unavailable')
    started = clock(); files = 0; size = 0; digest = hashlib.sha256()
    _require(any(root.glob('*.xctestrun')), 'build-for-testing invocation missing')
    required = ('Debug-watchsimulator/TouchColor.app/TouchColor',
                'Debug-watchsimulator/TouchColorWatchUITests-Runner.app/PlugIns/TouchColorWatchUITests.xctest/TouchColorWatchUITests')
    _require(all((root / name).is_file() for name in required), 'required Watch products missing')
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs.sort(); names.sort()
        for name in list(dirs):
            if (Path(folder) / name).is_symlink(): names.append(name); dirs.remove(name)
        for name in sorted(names):
            path = Path(folder) / name; info = path.lstat(); files += 1
            _require(files <= 8192 and clock() - started < 20, 'product fingerprint exceeded finite bound')
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode() + b'\0' + str(stat.S_IMODE(info.st_mode)).encode() + b'\0')
            if stat.S_ISLNK(info.st_mode):
                _require(path.resolve().is_relative_to(root.resolve()), 'product symlink escapes build products')
                digest.update(b'link\0' + os.readlink(path).encode() + b'\0')
            else:
                _require(stat.S_ISREG(info.st_mode), 'nonregular product')
                size += info.st_size
                _require(size <= 1024 ** 3, 'product bytes exceeded finite bound')
                digest.update(str(info.st_size).encode() + b'\0')
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        _require(clock() - started < 20, 'product fingerprint exceeded finite bound')
                        digest.update(chunk)
                after = path.lstat()
                _require((info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
                         'product changed during fingerprint')
            digest.update(b'\0')
    return {'sha256': digest.hexdigest(), 'files': files, 'bytes': size}


def checkpoint(report, *, device, runtime, runner=run_captured):
    """Snapshot exact source, built products, and one already-owned booted device."""
    try:
        def command(args):
            value = runner(args, text=True, timeout=15)
            _require(value.returncode == 0, 'checkpoint command failed')
            return value.stdout
        sha = command(['git', 'rev-parse', 'HEAD']).strip()
        command(['git', 'diff', '--exit-code', 'HEAD', '--'])
        inventory = strict_json(command(['xcrun', 'simctl', 'list', 'devices', 'available', '-j']))
        matches = [(r, row) for r, rows in inventory['devices'].items() for row in rows if row.get('udid') == device]
        _require(len(matches) == 1 and matches[0][0] == runtime, 'owned device missing or runtime changed')
        row = matches[0][1]
        _require(row.get('state') == 'Booted' and row.get('isAvailable') is True, 'owned device unavailable')
        return {'available': True, 'sha': sha, 'runtime': runtime,
                'device': {key: row.get(key) for key in ('udid', 'state', 'isAvailable', 'deviceTypeIdentifier')},
                'products': product_fingerprint('build/watch-tests/Build/Products')}
    except Exception as error:
        latch_unknown_cleanup(report, error)
        return {'available': False, 'reason': str(error)[:400]}


def latch_unknown_cleanup(report, error):
    from job_budget import BudgetExhausted
    if isinstance(error, (subprocess.TimeoutExpired, BudgetExhausted)):
        if getattr(error, 'cleanup_confirmed', False) is not True: report['cleanup_unconfirmed'] = True
    elif not isinstance(error, (ValueError, UnicodeError, KeyError, TypeError)):
        report['cleanup_unconfirmed'] = True


def inspect_failure(report, stage, command, before, *, sha, device, runtime, runner=run_captured):
    """All subprocesses stay in the existing work budget, with owned cleanup."""
    try:
        _stage(stage, command, report.get('cleanup_unconfirmed', False))
        value = runner(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', BUNDLE],
                       text=True, timeout=30)
        _require(value.returncode == 0, 'structured summary extraction failed')
        raw = (value.stdout or '').encode('utf-8')
        _require(len(raw) <= MAX_SUMMARY_BYTES and not value.stderr, 'summary output incomplete or unexpected')
        summary = strict_json(raw)
        answer = decision(stage, command, summary, before, before, sha=sha, device=device,
                          cleanup_unconfirmed=report.get('cleanup_unconfirmed', False))
        if answer['allowed']:
            after = checkpoint(report, device=device, runtime=runtime, runner=runner)
            answer = decision(stage, command, summary, before, after, sha=sha, device=device,
                              cleanup_unconfirmed=report.get('cleanup_unconfirmed', False))
            answer['after'] = after
        answer.update(summary_sha256=hashlib.sha256(raw).hexdigest(), summary_bytes=len(raw))
        return answer
    except Exception as error:
        latch_unknown_cleanup(report, error)
        return {'allowed': False, 'reason': 'scheduling proof unavailable: ' + str(error)[:400]}


def record_failure(report, phase, error):
    """First failure remains the headline; every later failure is also retained."""
    failure = {'phase': phase, 'error': str(error)}
    failures = report.setdefault('failures', [])
    if failure not in failures: failures.append(failure)
    report['result'] = 'failed'
    report['error'] = failures[0]['error']


def require_no_failures(report):
    if report.get('failures'):
        report['result'] = 'failed'
        report['error'] = report['failures'][0]['error']
        raise RuntimeError(report['error'])
