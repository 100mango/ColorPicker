#!/usr/bin/env python3
"""One owned, unsigned device per independent matrix job. Never a release/design approval."""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import stat
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/original-design'
EVIDENCE = WORK / 'evidence'
RUNTIME_VERSION = '27.0'
BOOTSTATUS_TIMEOUT_SECONDS = 300  # One bounded preparation; no automatic retry or escalating timeout.
BUNDLE_ID = 'com.mango.touchColor'
UI_CLASS = 'TouchColorOriginalDesignUITests'
BOOTSTRAP_TEST = 'testPhotosLibraryBootstrapCanCancelWithoutSelecting'
UI_PHASE_TESTS = {
    'ui-independent': {
        'testOriginalHomeTabsAndRepeatedPhotoPickerCancellation',
        'testNativePrivacyContentAndActionsFromEmptyLibrary',
        'testLiveUnavailableCannotSaveAndReturnsToOriginalHome',
    },
    'ui-seeded': {
        'testRealPhotoSaveRelaunchDelete',
        'testDelayedImportCancellationPreservesSavedColor',
        'testNativePrivacyBackgroundClosePreservesRealSavedColor',
    },
}
UI_PHASE_IMAGES = {
    'ui-independent': ['01-original-home', '02-original-empty-library',
                       '05-secondary-privacy-policy', '06-original-live-unavailable'],
    'ui-seeded': ['03-original-photo-sampled', '04-original-saved-library'],
}
UI_TOTAL_BUDGETS = {'execution': 600, 'summary': 30, 'attachments': 60, 'picker-trace': 30}
HOSTED_SOURCES = {
    'ColorPickerTests': 'ColorPickerTests/ColorPickerTests.m',
    'TCPhotoImportTests': 'ColorPickerTests/TCPhotoImportTests.swift',
    'TCPhotoImportLifecycleTests': 'ColorPickerTests/TCPhotoImportLifecycleTests.m',
}
DEVICE_NAMES = {'se3': 'iPhone SE (3rd generation)', 'ipad-mini': 'iPad mini (A17 Pro)'}
CONTROLLER_TIMEOUT_SECONDS = 23 * 60
EVIDENCE_BUDGET_BYTES = 12 * 1024 * 1024  # Two jobs together retain at most the original 24 MiB.
HOST_DIAGNOSTIC_PHASE_SECONDS = 20  # Charged to the unchanged controller deadline.
HOST_DIAGNOSTIC_LOG_BYTES = 256 * 1024
LANE_BRANCHES = {'full': 'touchcolor-original-design', 'seeded-only': 'touchcolor-seeded-evidence'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def fixture_png():
    width, height = 300, 200
    colors = [bytes(c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255),
                                (0, 255, 255), (255, 0, 255), (255, 255, 0)]]
    rows = b''.join(b'\0' + b''.join(colors[(y // 100) * 3 + x // 100]
                    for x in range(width)) for y in range(height))
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def fixture_observation(path):
    """Read only the generated host file, without following a final symlink."""
    def metadata(value):
        return {key: getattr(value, 'st_' + key) for key in
                ('dev', 'ino', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns')}
    result = {'path': str(path), 'observed_at': time.time()}
    try:
        before = path.lstat()
        result.update(lstat=metadata(before), permission_mode=oct(stat.S_IMODE(before.st_mode)),
                      parent_lstat=metadata(path.parent.lstat()))
        require(stat.S_ISREG(before.st_mode), 'Fixture is not a regular non-symlink file')
        require(before.st_size <= 1024 * 1024, 'Fixture exceeds the diagnostic read limit')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            result['fstat'] = metadata(opened)
            require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                    'Fixture identity changed while opening')
            data = stream.read(1024 * 1024 + 1)
            require(len(data) <= 1024 * 1024, 'Fixture grew beyond the diagnostic read limit')
            after = os.fstat(stream.fileno())
        result.update(fstat_after=metadata(after), bytes_read=len(data), sha256=hashlib.sha256(data).hexdigest(),
                      matches_generated_fixture=data == fixture_png(),
                      stable_during_read=metadata(opened) == metadata(after), status='observed')
    except Exception as error:
        result.update(status='unavailable', error=str(error)[:300])
    return result


def testcase_names(path):
    source = path.read_text()
    rows = re.findall(r'-\s*\(void\)\s*(test[A-Za-z0-9_]+)\s*\{|\bfunc\s+(test[A-Za-z0-9_]+)\s*\(', source)
    return {objective_c or swift for objective_c, swift in rows}


def qualify_summary(summary, *, expected_count, device, began, finished, exit_code):
    fields = ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests', 'expectedFailures')
    require(all(type(summary.get(k)) is int and summary[k] >= 0 for k in fields), 'Invalid test counts')
    require(summary['totalTestCount'] == expected_count and summary['passedTests'] == expected_count,
            'Expected complete selected test inventory did not pass')
    require(all(summary[k] == 0 for k in fields[2:]), 'Failed, skipped or expected-failure test is not a pass')
    require(summary.get('result') == 'Passed' and exit_code == 0, 'Command and XCTest outcome disagree')
    require(all(type(summary.get(k)) in (int, float) and math.isfinite(summary[k]) for k in ('startTime', 'finishTime')),
            'Missing finite test interval')
    require(began <= summary['startTime'] <= summary['finishTime'] <= finished, 'Stale or foreign test summary')
    rows = summary.get('devicesAndConfigurations')
    require(isinstance(rows, list) and len(rows) == 1, 'Ambiguous result destination')
    row = rows[0]
    require(row.get('device', {}).get('deviceId') == device and
            row['device'].get('platform') == 'iOS Simulator' and row['device'].get('osVersion') == RUNTIME_VERSION,
            'Result belongs to another simulator/runtime')
    require(all(row.get(k) == summary[k] for k in fields[1:]), 'Per-device totals contradict summary')


def qualify_cases(log, expected_names):
    rows = re.findall(r"^Test Case ['\"].*?\b(test[A-Za-z0-9_]+)\b.*?\b(passed|failed|skipped)\b", log, re.M)
    require(len(rows) == len(expected_names), 'Incomplete or duplicate testcase terminal records')
    require({name for name, _ in rows} == expected_names, 'Wrong testcase selection executed')
    require(all(outcome == 'passed' for _, outcome in rows), 'A raw testcase outcome contradicts success')


class Gate:
    def __init__(self, expected_sha, device_label, lane='full'):
        require(device_label in DEVICE_NAMES, 'Exactly one reviewed device must be selected')
        require(lane in LANE_BRANCHES, 'Unknown qualification lane')
        require(lane == 'full' or device_label == 'ipad-mini', 'Seeded-only evidence is scoped to iPad mini')
        self.lane = lane
        self.seed_timeout_seconds = 120 if lane == 'seeded-only' else 60
        self.expected_sha = expected_sha
        self.device_label = device_label
        self.deadline = time.monotonic() + CONTROLLER_TIMEOUT_SECONDS
        self.uncertain_simulator = False
        self.owned = []
        self.commands = []
        self.devices = []
        self.ui_budgets = dict(UI_TOTAL_BUDGETS)
        self.ui_phase_results = {phase: {'status': 'not_run', 'expected_tests': sorted(names)}
                                 for phase, names in UI_PHASE_TESTS.items()}
        self.ui_screenshots = []
        WORK.mkdir(parents=True, exist_ok=True)
        EVIDENCE.mkdir(parents=True, exist_ok=True)

    def command(self, name, argv, seconds, *, simulator=False, allow_failure=False,
                output_limit_bytes=None, cleanup_grace=10):
        from bounded_process import group_exists, stop_group
        require(not simulator or not self.uncertain_simulator, 'An uncertain simulator command blocks further simulator actions')
        remaining = self.deadline - time.monotonic() - 25
        require(remaining >= 1, 'Whole-job operation budget exhausted')
        timeout = min(seconds, remaining)
        path = WORK / 'logs' / (name + '.log'); path.parent.mkdir(parents=True, exist_ok=True)
        record = {'name': name, 'argv': argv, 'started': time.time(), 'simulator': simulator,
                  'started_monotonic': time.monotonic(), 'timeout_seconds': timeout}
        if output_limit_bytes is not None:
            require(not simulator and 0 < output_limit_bytes <= HOST_DIAGNOSTIC_LOG_BYTES,
                    'Output-limited observations must be bounded host-only commands')
            record['output_limit_bytes'] = output_limit_bytes
            record['cleanup_grace_seconds_per_signal'] = cleanup_grace
        self.commands.append(record)
        print('ORIGINAL_DESIGN_COMMAND_BEGIN ' + json.dumps({k: record[k] for k in ('name', 'started', 'timeout_seconds', 'simulator')}), flush=True)
        process = None
        try:
            with path.open('wb') as output:
                options = {}
                if output_limit_bytes is not None:
                    # Limit this child only. No shell, daemon or machine setting.
                    options['preexec_fn'] = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit_bytes, output_limit_bytes))
                process = subprocess.Popen(argv, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True, **options)
                code = process.wait(timeout=timeout)
            require(not group_exists(process.pid), 'Owned command descendants outlived the command')
            record.update(exit_code=code, host_group_exit_confirmed=True, finished=time.time())
        except BaseException as error:
            confirmed = stop_group(process, grace=cleanup_grace) if process is not None else True
            record.update(error=str(error)[:300], host_group_exit_confirmed=confirmed, finished=time.time())
            if simulator:
                self.uncertain_simulator = True
            raise
        finally:
            if path.exists():
                digest = hashlib.sha256(); total = 0; tail = b''
                with path.open('rb') as stream:
                    while True:
                        block = stream.read(64 * 1024)
                        if not block: break
                        total += len(block); digest.update(block); tail = (tail + block)[-512 * 1024:]
                available = max(0, (EVIDENCE_BUDGET_BYTES - 4 * 1024 * 1024) - sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file()))
                retained = tail[-available:] if available else b''
                record.update(log_bytes=total, log_sha256=digest.hexdigest(), log_tail_truncated=total > len(retained), log_retained_bytes=len(retained))
                if output_limit_bytes is not None:
                    record['output_limit_reached'] = total >= output_limit_bytes
                (EVIDENCE / (name + '.log')).write_bytes(retained)
            record['elapsed_seconds'] = max(0, time.monotonic() - record['started_monotonic'])
            write_json(EVIDENCE / 'commands.json', self.commands)
            print('ORIGINAL_DESIGN_COMMAND_END ' + json.dumps({k: record.get(k) for k in ('name', 'finished', 'elapsed_seconds', 'exit_code', 'error', 'host_group_exit_confirmed')}), flush=True)
        require(allow_failure or code == 0, name + ' failed; see its bounded log')
        require(path.stat().st_size <= 8 * 1024 * 1024 or name == 'build', 'Command output exceeded the explicit parsing limit')
        return code, path

    def seed_host_diagnostics(self, label, device, fixture, phase, began, finished):
        """No device RPC: bounded host observations, never a readiness assertion."""
        deadline = min(time.monotonic() + HOST_DIAGNOSTIC_PHASE_SECONDS, self.deadline - 25)
        receipt = {'source_sha': self.expected_sha, 'owned_device': device, 'phase': phase,
                   'simulator_uncertain': self.uncertain_simulator, 'started': time.time(),
                   'phase_budget_seconds': HOST_DIAGNOSTIC_PHASE_SECONDS,
                   'fixture': fixture_observation(fixture), 'observations': [],
                   'claim': 'Host observations only; missing logs are not service health or callback evidence'}
        path = EVIDENCE / (label + '-seed-host-' + phase + '.json')
        try:
            usage = os.statvfs(WORK)
            receipt['resources'] = {'cpu_count': os.cpu_count(), 'load_average': list(os.getloadavg()),
                                    'filesystem_available_bytes': usage.f_bavail * usage.f_frsize}
        except Exception as error:
            receipt['resources'] = {'status': 'unavailable', 'error': str(error)[:300]}
        # Explicit UTC offsets avoid interpreting runner-local dates as UTC.
        stamp = lambda value: datetime.datetime.fromtimestamp(value, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S%z')
        start, end = stamp(math.floor(began)), stamp(math.ceil(finished))
        predicate = ('process == "CoreSimulatorService" OR process == "simdiskimaged" OR '
                     'process == "simctl" OR subsystem BEGINSWITH "com.apple.CoreSimulator" OR '
                     'eventMessage CONTAINS[c] "' + device + '"')
        commands = [
            ('processes', ['/bin/ps', '-axo', 'pid,ppid,pcpu,pmem,rss,state,etime,comm'], 3),
            ('memory', ['/usr/bin/vm_stat'], 3),
            ('log', ['/usr/bin/log', 'show', '--style', 'compact', '--info', '--debug', '--timezone', 'UTC',
                     '--start', start, '--end', end, '--predicate', predicate], 8),
        ]
        receipt['log_window'] = {'start': start, 'end': end, 'predicate': predicate}
        write_json(path, receipt)
        try:
            for kind, argv, ceiling in commands:
                # Two seconds reserve for the two one-second group-stop phases.
                seconds = min(ceiling, deadline - time.monotonic() - 2)
                row = {'kind': kind, 'argv': argv}
                receipt['observations'].append(row)
                if seconds < 1:
                    row.update(status='unavailable', error='Diagnostic/controller budget exhausted; command not launched')
                    continue
                count = len(self.commands)
                try:
                    code, _ = self.command(label + '-seed-host-' + phase + '-' + kind, argv, seconds,
                                           simulator=False, allow_failure=True,
                                           output_limit_bytes=HOST_DIAGNOSTIC_LOG_BYTES, cleanup_grace=1)
                    record = self.commands[-1]
                    row.update(status='captured' if code == 0 and record.get('log_bytes', 0) > 0 and
                               not record.get('output_limit_reached') and not record.get('log_tail_truncated')
                               else 'unavailable_or_partial', exit_code=code)
                except Exception as error:
                    row.update(status='unavailable', error=str(error)[:300])
                except BaseException as error:
                    row.update(status='interrupted', error=str(error)[:300])
                    raise
                finally:
                    if len(self.commands) > count:
                        row['command'] = self.commands[-1]
                        if not self.commands[-1].get('host_group_exit_confirmed', False):
                            # Also run on cancellation: never let outer cleanup
                            # act on a device beside an unconfirmed host group.
                            self.uncertain_simulator = True
                            row['stop_reason'] = 'Host diagnostic process-group exit unconfirmed; device actions blocked'
                    write_json(path, receipt)
                if 'stop_reason' in row:
                    raise RuntimeError(row['stop_reason'])
        finally:
            receipt.update(finished=time.time(), simulator_uncertain=self.uncertain_simulator)
            write_json(path, receipt)

    def seed_fixture(self, label, device, fixture):
        now = time.time()
        self.seed_host_diagnostics(label, device, fixture, 'before', now - 30, now)
        began = time.time()
        try:
            self.command(label + '-seed', ['xcrun', 'simctl', 'addmedia', device, str(fixture)], self.seed_timeout_seconds, simulator=True)
        except BaseException:
            finished = time.time()
            try:
                self.seed_host_diagnostics(label, device, fixture, 'after', began, finished)
            except BaseException:
                # Keep the exact seed failure, including cancellation, even if
                # secondary host diagnostics are interrupted or unavailable.
                pass
            raise
        self.seed_host_diagnostics(label, device, fixture, 'after', began, time.time())

    def await_owned_boot(self, label, device, owned_name):
        # Reuse the exact c664 public-output parser. A timely zero exit alone is
        # not readiness, and readiness is not an app/test completion claim.
        from uikit_managed_tests import completed_bootstatus
        _, path = self.command(label + '-ready', ['xcrun', 'simctl', 'bootstatus', device, '-b'],
                               BOOTSTATUS_TIMEOUT_SECONDS, simulator=True)
        try:
            proof = completed_bootstatus(path.read_text(), {'name': owned_name, 'device': device})
        except Exception:
            self.uncertain_simulator = True
            raise
        write_json(EVIDENCE / (label + '-ready.json'), {'device': device, 'owned_name': owned_name,
                   'budget_seconds': BOOTSTATUS_TIMEOUT_SECONDS, 'command': self.commands[-1], 'bootstatus': proof,
                   'claim': 'owned bootstatus observation only; hosted/UI tests remain required'})

    def text(self, name, argv, seconds=30, **kwargs):
        _, path = self.command(name, argv, seconds, **kwargs)
        return path.read_text(errors='replace').strip()

    def ui_command(self, budget, name, argv, **kwargs):
        """Both UI phases share each original UI-stage allowance, not two copies."""
        seconds = self.ui_budgets[budget]
        require(seconds >= 1, 'Shared UI ' + budget + ' budget exhausted; no command launched')
        began = time.monotonic()
        try:
            return self.command(name, argv, seconds, **kwargs)
        finally:
            self.ui_budgets[budget] = max(0, seconds - max(0, time.monotonic() - began))

    def run_tests(self, label, device, suite, selectors, expected_names):
        require(suite in ('hosted', 'bootstrap') or suite in UI_PHASE_TESTS, 'Unknown or unsplit test phase')
        if suite not in UI_PHASE_TESTS:
            return self.execute_tests(label, device, suite, selectors, expected_names)
        require(expected_names == UI_PHASE_TESTS[suite], 'Wrong UI phase inventory')
        row = self.ui_phase_results[suite]
        require(row['status'] == 'not_run', 'A UI phase must never execute twice')
        row.update(status='running', started=time.time())
        try:
            self.execute_tests(label, device, suite, selectors, expected_names)
            row['status'] = 'passed'
        except BaseException as error:
            row.update(status='failed', error=str(error)[:300])
            raise
        finally:
            row['finished'] = time.time()
            write_json(EVIDENCE / (label + '-ui-phases.json'),
                       {'phases': self.ui_phase_results, 'remaining_seconds': self.ui_budgets})

    def execute_tests(self, label, device, suite, selectors, expected_names):
        ui_phase = suite in UI_PHASE_TESTS
        result = WORK / (label + '-' + suite + '.xcresult')
        require(not result.exists(), 'Refusing to reuse a previous result bundle')
        command = ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-configuration', 'Debug',
                   '-destination', 'platform=iOS Simulator,id=' + device, '-derivedDataPath', str(WORK / 'derived'),
                   '-resultBundlePath', str(result), '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
                   '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '120',
                   '-maximum-test-execution-time-allowance', '180', *['-only-testing:' + s for s in selectors], 'CODE_SIGNING_ALLOWED=NO', 'test-without-building']
        began = time.time()
        if ui_phase:
            code, log = self.ui_command('execution', label + '-' + suite, command, simulator=True, allow_failure=True)
        else:
            code, log = self.command(label + '-' + suite, command, 600, simulator=True, allow_failure=True)
        finished = time.time()
        summary_command = ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(result)]
        if ui_phase:
            _, summary_path = self.ui_command('summary', label + '-' + suite + '-summary', summary_command)
            raw = summary_path.read_text()
        else:
            raw = self.text(label + '-' + suite + '-summary', summary_command)
        summary = json.loads(raw)
        write_json(EVIDENCE / (label + '-' + suite + '-summary.json'), summary)
        if ui_phase:
            self.ui_phase_results[suite]['observed_counts'] = {key: summary.get(key) for key in
                ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests', 'expectedFailures')}
        # Preserve screenshot evidence even when a real assertion failed.
        if ui_phase or suite == 'bootstrap':
            self.export_screenshots(label if ui_phase else label + '-bootstrap', result,
                                    require_complete=code == 0, bootstrap=suite == 'bootstrap',
                                    phase=suite if ui_phase else None)
            # XCTest is terminal and attachments are safe before this optional
            # bounded observation. Missing log transport is never 'no callback'.
            trace_command = ['xcrun', 'simctl', 'spawn', device, 'log', 'show', '--style', 'compact', '--info', '--debug',
                             '--last', '15m', '--predicate', 'eventMessage BEGINSWITH "TC_PICKER_TRACE"']
            if ui_phase:
                trace_code, trace = self.ui_command('picker-trace', label + '-' + suite + '-picker-trace',
                                                   trace_command, simulator=True, allow_failure=True)
            else:
                trace_code, trace = self.command(label + '-' + suite + '-picker-trace', trace_command,
                                                 30, simulator=True, allow_failure=True)
            write_json(EVIDENCE / (label + '-' + suite + '-picker-trace.json'),
                       {'device': device, 'source_sha': self.expected_sha, 'exit_code': trace_code,
                        'evidence': 'available' if trace_code == 0 and 'TC_PICKER_TRACE event=' in trace.read_text(errors='replace') else 'missing',
                        'missing_semantics': 'Transport absent is not proof a delegate callback did not occur'})
        qualify_summary(summary, expected_count=len(expected_names), device=device, began=began, finished=finished, exit_code=code)
        qualify_cases(log.read_text(errors='replace'), expected_names)

    def export_screenshots(self, label, result, *, require_complete, bootstrap=False, phase=None):
        prefix = label + ('-' + phase if phase else '')
        destination = WORK / (prefix + '-raw-attachments')
        argv = ['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result), '--output-path', str(destination)]
        if phase:
            self.ui_command('attachments', prefix + '-attachments', argv)
        else:
            self.command(prefix + '-attachments', argv, 60)
        def records(value):
            if isinstance(value, dict):
                if 'exportedFileName' in value: yield value
                for child in value.values(): yield from records(child)
            elif isinstance(value, list):
                for child in value: yield from records(child)
        rows = list(records(json.loads((destination / 'manifest.json').read_text())))
        names = ['01-original-home', '02-original-empty-library', '03-original-photo-sampled',
                 '04-original-saved-library', '05-secondary-privacy-policy', '06-original-live-unavailable']
        if bootstrap: names = ['bootstrap-picker-ready']
        if phase: names = UI_PHASE_IMAGES[phase]
        diagnostics = ['bootstrap-cancel-before'] if bootstrap else ['picker-cancel-before-1', 'picker-cancel-before-2'] if phase == 'ui-independent' else []
        kept = []
        for name in names + diagnostics + ['original-design-failure']:
            matches = [row for row in rows if any(name in value for value in row.values() if isinstance(value, str))]
            if name == 'original-design-failure': matches = matches[:1]
            else:
                require(len(matches) <= 1 and (not require_complete or name not in names or len(matches) == 1), 'Missing or duplicate named screenshot: ' + name)
            for row in matches:
                source = (destination / row['exportedFileName']).resolve()
                require(source.is_relative_to(destination.resolve()) and not source.is_symlink(), 'Unsafe attachment path')
                require(0 < source.stat().st_size <= 2 * 1024 * 1024, 'Screenshot exceeds per-image budget')
                data = source.read_bytes(); require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'Expected lossless PNG evidence')
                total = sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file())
                require(total + len(data) <= EVIDENCE_BUDGET_BYTES - 64 * 1024, 'Evidence package budget exceeded')
                target = EVIDENCE / (label + '-' + name + '.png')
                require(not target.exists(), 'A phase must not overwrite an existing screenshot')
                target.write_bytes(data)
                kept.append({'name': name, 'path': target.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        write_json(EVIDENCE / (prefix + '-screenshots.json'), kept)
        if phase: self.ui_screenshots.extend(kept)

    def qualify_ui_completion(self, label):
        if self.lane == 'seeded-only':
            require(self.ui_phase_results['ui-independent'] ==
                    {'status': 'not_run', 'expected_tests': sorted(UI_PHASE_TESTS['ui-independent'])},
                    'Seeded-only evidence must not credit independent UI tests')
            seeded = self.ui_phase_results['ui-seeded']
            require(seeded['status'] == 'passed' and seeded['expected_tests'] == sorted(UI_PHASE_TESTS['ui-seeded']),
                    'The exact three seeded UI tests must pass')
            names = [item['name'] for item in self.ui_screenshots]
            require(sorted(names) == sorted(UI_PHASE_IMAGES['ui-seeded']),
                    'Seeded-only evidence requires exactly its two distinct named images')
            write_json(EVIDENCE / (label + '-screenshots.json'), self.ui_screenshots)
            return
        require(all(row['status'] == 'passed' for row in self.ui_phase_results.values()), 'Both UI phases must pass')
        tests = [name for row in self.ui_phase_results.values() for name in row['expected_tests']]
        require(len(tests) == len(set(tests)) == 6, 'UI testcase inventory must total six without duplicates')
        names = [item['name'] for item in self.ui_screenshots]
        required = sum(UI_PHASE_IMAGES.values(), [])
        require(len(required) == len(set(required)) == 6, 'The UI contract requires six distinct named images')
        require(len(names) == len(set(names)), 'Duplicate screenshot names across UI phases')
        require(sorted(name for name in names if name in required) == sorted(required), 'Incomplete six-image UI evidence')
        write_json(EVIDENCE / (label + '-screenshots.json'), self.ui_screenshots)

    def main(self):
        require(sys.platform == 'darwin', 'This gate requires the xcode-27 cloud runner')
        require(os.environ.get('GITHUB_EVENT_NAME') == 'push' and os.environ.get('GITHUB_REF') == 'refs/heads/' + LANE_BRANCHES[self.lane],
                'Only the root-controlled branch push for the selected lane may activate this gate')
        if self.lane == 'seeded-only':
            require(os.environ.get('GITHUB_WORKFLOW_REF') ==
                    '100mango/ColorPicker/.github/workflows/original-design-seeded.yml@refs/heads/touchcolor-seeded-evidence',
                    'The seeded-only lane requires its exact workflow and branch')
        require(os.environ.get('GITHUB_REPOSITORY') == '100mango/ColorPicker', 'Wrong repository')
        require(re.fullmatch(r'[0-9a-f]{40}', self.expected_sha) is not None, 'Supply a full expected source SHA')
        require(os.environ.get('GITHUB_SHA') == self.expected_sha and os.environ.get('GITHUB_WORKFLOW_SHA') == self.expected_sha,
                'Workflow and source must be the same explicit revision')
        require(self.text('source-sha', ['git', 'rev-parse', 'HEAD']) == self.expected_sha, 'Wrong checked-out source')
        self.command('clean-start', ['git', 'diff', '--exit-code', 'HEAD', '--'], 30)
        version = self.text('toolchain', ['xcodebuild', '-version'])
        require('Xcode 27.0' in version, 'Expected the dedicated xcode-27 toolchain')
        self.command('project-regenerate', ['python3', 'scripts/generate_project.py'], 30)
        self.command('project-unchanged', ['git', 'diff', '--exit-code', '--', 'TouchColor.xcodeproj'], 30)
        require(UI_CLASS + '.m' in (ROOT / 'TouchColor.xcodeproj/project.pbxproj').read_text(), 'New UI test is absent from the built target')
        self.command('preserved-design-source', ['python3', 'scripts/verify_original_design_source.py'], 30)
        self.command('gate-self-tests', ['python3', 'scripts/test_original_design_gate.py'], 30)
        self.command('build', ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-configuration', 'Debug',
                              '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', str(WORK / 'derived'),
                              '-jobs', '2', 'CODE_SIGNING_ALLOWED=NO', 'build-for-testing'], 720)
        runtimes = json.loads(self.text('runtimes', ['xcrun', 'simctl', 'list', 'runtimes', '-j'], simulator=True))['runtimes']
        runtime = [r for r in runtimes if r.get('isAvailable') and r.get('version') == RUNTIME_VERSION and r['identifier'].split('.')[-1].startswith('iOS-')]
        require(len(runtime) == 1, 'Exactly one available iOS 27.0 runtime is required')
        types = json.loads(self.text('device-types', ['xcrun', 'simctl', 'list', 'devicetypes', '-j'], simulator=True))['devicetypes']
        hosted = set().union(*(testcase_names(ROOT / path) for path in HOSTED_SOURCES.values()))
        ui = testcase_names(ROOT / 'TouchColorUITests' / (UI_CLASS + '.m'))
        require(BOOTSTRAP_TEST in ui, 'The separately selected bootstrap is missing')
        ui.remove(BOOTSTRAP_TEST)
        require(len(hosted) == 29 and len(ui) == 6, 'Reviewed testcase inventory changed; update the explicit gate before execution')
        require(ui == set().union(*UI_PHASE_TESTS.values()), 'All six UI cases must belong to the reviewed dependency phases')
        fixture = WORK / 'original-design-six-colors.png'; fixture.write_bytes(fixture_png())
        write_json(EVIDENCE / 'fixture.json', {'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'width': 300, 'height': 200,
                                             'colors': ['#ff0000', '#00ff00', '#0000ff', '#00ffff', '#ff00ff', '#ffff00']})
        app = WORK / 'derived/Build/Products/Debug-iphonesimulator/TouchColor.app'
        require(app.is_dir(), 'Exact built app is missing')
        self.run_device(types, runtime[0], app, fixture, hosted, ui)
        self.command('clean-end', ['git', 'diff', '--exit-code', 'HEAD', '--'], 30)

    def run_device(self, types, runtime, app, fixture, hosted, ui):
        require(ui == set().union(*UI_PHASE_TESTS.values()), 'All six UI cases must be assigned exactly once')
        label = self.device_label
        name = DEVICE_NAMES[label]
        found = [d for d in types if d['name'] == name]
        require(len(found) == 1, 'Required simulator device type missing: ' + name)
        owned_name = 'TouchColor-Original-' + label + '-' + uuid.uuid4().hex[:12]
        device = self.text(label + '-create', ['xcrun', 'simctl', 'create', owned_name, found[0]['identifier'], runtime['identifier']], simulator=True)
        require(re.fullmatch(r'[0-9A-Fa-f-]{36}', device) is not None, 'Invalid created simulator identity')
        self.owned.append(device)
        self.devices.append({'label': label, 'name': name, 'owned_name': owned_name, 'udid': device, 'runtime': runtime})
        write_json(EVIDENCE / 'devices.json', self.devices)
        self.command(label + '-boot', ['xcrun', 'simctl', 'boot', device], 45, simulator=True)
        self.await_owned_boot(label, device, owned_name)
        # Each selected test-without-building operation installs its exact build
        # products on the fresh UUID. Seeded-only starts with real UI bootstrap;
        # it cannot depend on an earlier hosted run or another simulator.
        if self.lane == 'full':
            self.run_tests(label, device, 'hosted', ['TouchColorTests/' + c for c in HOSTED_SOURCES], hosted)
        self.run_tests(label, device, 'bootstrap', ['TouchColorUITests/' + UI_CLASS + '/' + BOOTSTRAP_TEST], {BOOTSTRAP_TEST})
        independent = UI_PHASE_TESTS['ui-independent']
        if self.lane == 'full':
            self.run_tests(label, device, 'ui-independent', ['TouchColorUITests/' + UI_CLASS + '/' + name for name in sorted(independent)], independent)
        self.seed_fixture(label, device, fixture)
        seeded = ui - independent
        self.run_tests(label, device, 'ui-seeded', ['TouchColorUITests/' + UI_CLASS + '/' + name for name in sorted(seeded)], seeded)
        self.qualify_ui_completion(label)
        self.command(label + '-shutdown', ['xcrun', 'simctl', 'shutdown', device], 60, simulator=True)
        self.command(label + '-delete', ['xcrun', 'simctl', 'delete', device], 45, simulator=True)
        self.owned.remove(device)

    def cleanup(self):
        # Never issue more simulator commands after a timed-out/uncertain action.
        if self.uncertain_simulator:
            return
        for device in self.owned[:]:
            try:
                self.command('cleanup-' + device + '-shutdown', ['xcrun', 'simctl', 'shutdown', device], 45, simulator=True, allow_failure=True)
                self.command('cleanup-' + device + '-delete', ['xcrun', 'simctl', 'delete', device], 45, simulator=True)
                self.owned.remove(device)
            except Exception:
                break



def admit_evidence(source=EVIDENCE, destination=WORK / 'published'):
    """Physical upload ceiling. An over-budget gate retains only bounded diagnostics."""
    require(source.is_dir() and not source.is_symlink(), 'Evidence directory is unavailable or linked')
    require(not destination.exists(), 'Do not reuse a previous admitted artifact tree')
    destination.mkdir(parents=True)
    files = sorted(p for p in source.rglob('*') if p.is_file())
    require(all(not p.is_symlink() and not any(parent.is_symlink() for parent in p.parents) for p in files), 'Linked evidence is not publishable')
    require(all(p.suffix in ('.json', '.log', '.png') for p in files), 'Unexpected artifact type; no raw xcresults are admitted')
    budget = EVIDENCE_BUDGET_BYTES
    complete = sum(p.stat().st_size for p in files) <= budget - 64 * 1024
    kept = []; omitted = []; used = 0
    if not complete:
        files.sort(key=lambda p: (p.suffix != '.json', not any(word in p.name for word in ('ui', 'hosted', 'build')), p.name))
    for path in files:
        relative = path.relative_to(source)
        size = path.stat().st_size
        allowance = budget - 64 * 1024 - used if complete else 4 * 1024 * 1024 - used
        if (not complete and path.suffix == '.png') or size > allowance:
            omitted.append({'path': str(relative), 'bytes': size}); continue
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target); used += size
        kept.append({'path': str(relative), 'bytes': size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    write_json(destination / 'artifact-admission.json', {'complete': complete, 'limit_bytes': budget,
               'source_bytes': sum(p.stat().st_size for p in files), 'retained_bytes': used, 'kept': kept, 'omitted': omitted,
               'claim': 'Complete bounded evidence' if complete else 'Budget exceeded; screenshots omitted; no visual acceptance claim'})
    require(sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()) <= budget, 'Internal artifact budget error')
    return complete


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha')
    parser.add_argument('--device', choices=tuple(DEVICE_NAMES), required=True)
    parser.add_argument('--admit-evidence', action='store_true')
    parser.add_argument('--lane', choices=tuple(LANE_BRANCHES), default='full')
    args = parser.parse_args()
    if args.admit_evidence:
        admit_evidence(); return 0
    require(args.expected_sha is not None, 'Supply --expected-sha')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Native gate interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    gate = Gate(args.expected_sha, args.device, args.lane); passed = False; error = None
    try:
        gate.main(); passed = True
    except BaseException as failure:
        error = str(failure)[:1000]
    finally:
        gate.cleanup()
        total = sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file())
        passed = passed and not gate.owned and not gate.uncertain_simulator and total <= EVIDENCE_BUDGET_BYTES - 128 * 1024
        write_json(EVIDENCE / 'acceptance.json', {'functional_passed': passed and args.lane == 'full',
                   'scope': 'selected device only; both matrix jobs must pass' if args.lane == 'full' else
                            'partial-scoped: fresh iPad bootstrap and three seeded UI cases only; private qualification must review any composition',
                   'lane': args.lane, 'scoped_passed': passed,
                   'scope_status': ('full-passed' if passed else 'full-failed') if args.lane == 'full' else
                                   ('partial-scoped-passed' if passed else 'partial-scoped-failed'),
                   'omitted_phases': [] if args.lane == 'full' else ['hosted', 'ui-independent'],
                   'selected_inventory': {'hosted': 29, 'ui': 6, 'bootstrap': 1} if args.lane == 'full' else
                                         {'hosted': 0, 'ui': 3, 'bootstrap': 1},
                   'seed_timeout_seconds': 60 if args.lane == 'full' else 120,
                   'device_label': args.device, 'device_name': DEVICE_NAMES[args.device], 'required_devices': list(DEVICE_NAMES),
                   'reviewed_inventory': {'hosted': 29, 'ui': 6},
                   'bootstrap_inventory': 1,
                   'ui_phases': gate.ui_phase_results, 'ui_remaining_budget_seconds': gate.ui_budgets,
                   'photos_preparation': 'real PHPicker bootstrap before addmedia; no cold Photos-service claim',
                   'error': error, 'source_sha': args.expected_sha,
                   'pending_owned_devices': gate.owned, 'simulator_uncertain': gate.uncertain_simulator, 'evidence_bytes': total,
                   'visual_comparison': ('not automatically accepted; inspect six named screenshots per device against original design'
                                         if args.lane == 'full' else
                                         'not automatically accepted; inspect bootstrap and two seeded images; four independent UI images are absent from this run'),
                   'release_claim': False})
    if error: print(error, file=sys.stderr)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
