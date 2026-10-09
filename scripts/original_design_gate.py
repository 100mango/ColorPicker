#!/usr/bin/env python3
"""One owned, unsigned SE3 -> iPad simulator gate. Never a release/design approval."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
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
HOSTED_SOURCES = {
    'ColorPickerTests': 'ColorPickerTests/ColorPickerTests.m',
    'TCPhotoImportTests': 'ColorPickerTests/TCPhotoImportTests.swift',
    'TCPhotoImportLifecycleTests': 'ColorPickerTests/TCPhotoImportLifecycleTests.m',
}
DEVICE_NAMES = ('iPhone SE (3rd generation)', 'iPad mini (A17 Pro)')


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
    def __init__(self, expected_sha):
        self.expected_sha = expected_sha
        self.deadline = time.monotonic() + 35 * 60
        self.uncertain_simulator = False
        self.owned = []
        self.commands = []
        self.devices = []
        WORK.mkdir(parents=True, exist_ok=True)
        EVIDENCE.mkdir(parents=True, exist_ok=True)

    def command(self, name, argv, seconds, *, simulator=False, allow_failure=False):
        from bounded_process import group_exists, stop_group
        require(not simulator or not self.uncertain_simulator, 'An uncertain simulator command blocks further simulator actions')
        remaining = self.deadline - time.monotonic() - 25
        require(remaining >= 1, 'Whole-job operation budget exhausted')
        timeout = min(seconds, remaining)
        path = WORK / 'logs' / (name + '.log'); path.parent.mkdir(parents=True, exist_ok=True)
        record = {'name': name, 'argv': argv, 'started': time.time(), 'simulator': simulator,
                  'started_monotonic': time.monotonic(), 'timeout_seconds': timeout}
        self.commands.append(record)
        print('ORIGINAL_DESIGN_COMMAND_BEGIN ' + json.dumps({k: record[k] for k in ('name', 'started', 'timeout_seconds', 'simulator')}), flush=True)
        process = None
        try:
            with path.open('wb') as output:
                process = subprocess.Popen(argv, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                code = process.wait(timeout=timeout)
            require(not group_exists(process.pid), 'Owned command descendants outlived the command')
            record.update(exit_code=code, host_group_exit_confirmed=True, finished=time.time())
        except BaseException as error:
            confirmed = stop_group(process, grace=10) if process is not None else True
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
                available = max(0, 20 * 1024 * 1024 - sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file()))
                retained = tail[-available:] if available else b''
                record.update(log_bytes=total, log_sha256=digest.hexdigest(), log_tail_truncated=total > len(retained), log_retained_bytes=len(retained))
                (EVIDENCE / (name + '.log')).write_bytes(retained)
            record['elapsed_seconds'] = max(0, time.monotonic() - record['started_monotonic'])
            write_json(EVIDENCE / 'commands.json', self.commands)
            print('ORIGINAL_DESIGN_COMMAND_END ' + json.dumps({k: record.get(k) for k in ('name', 'finished', 'elapsed_seconds', 'exit_code', 'error', 'host_group_exit_confirmed')}), flush=True)
        require(allow_failure or code == 0, name + ' failed; see its bounded log')
        require(path.stat().st_size <= 8 * 1024 * 1024 or name == 'build', 'Command output exceeded the explicit parsing limit')
        return code, path

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

    def run_tests(self, label, device, suite, selectors, expected_names):
        result = WORK / (label + '-' + suite + '.xcresult')
        require(not result.exists(), 'Refusing to reuse a previous result bundle')
        command = ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-configuration', 'Debug',
                   '-destination', 'platform=iOS Simulator,id=' + device, '-derivedDataPath', str(WORK / 'derived'),
                   '-resultBundlePath', str(result), '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
                   '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '120',
                   '-maximum-test-execution-time-allowance', '180', *['-only-testing:' + s for s in selectors], 'CODE_SIGNING_ALLOWED=NO', 'test-without-building']
        began = time.time()
        code, log = self.command(label + '-' + suite, command, 600, simulator=True, allow_failure=True)
        finished = time.time()
        raw = self.text(label + '-' + suite + '-summary', ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(result)])
        summary = json.loads(raw)
        write_json(EVIDENCE / (label + '-' + suite + '-summary.json'), summary)
        # Preserve screenshot evidence even when a real assertion failed.
        if suite == 'ui':
            self.export_screenshots(label, result, require_complete=code == 0)
        qualify_summary(summary, expected_count=len(expected_names), device=device, began=began, finished=finished, exit_code=code)
        qualify_cases(log.read_text(errors='replace'), expected_names)

    def export_screenshots(self, label, result, *, require_complete):
        destination = WORK / (label + '-raw-attachments')
        self.command(label + '-attachments', ['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result),
                                             '--output-path', str(destination)], 60)
        def records(value):
            if isinstance(value, dict):
                if 'exportedFileName' in value: yield value
                for child in value.values(): yield from records(child)
            elif isinstance(value, list):
                for child in value: yield from records(child)
        rows = list(records(json.loads((destination / 'manifest.json').read_text())))
        names = ['01-original-home', '02-original-empty-library', '03-original-photo-sampled',
                 '04-original-saved-library', '05-secondary-privacy-policy', '06-original-live-unavailable']
        kept = []
        for name in names + ['original-design-failure']:
            matches = [row for row in rows if any(name in value for value in row.values() if isinstance(value, str))]
            if name == 'original-design-failure': matches = matches[:1]
            else:
                require(len(matches) <= 1 and (not require_complete or len(matches) == 1), 'Missing or duplicate named screenshot: ' + name)
            for row in matches:
                source = (destination / row['exportedFileName']).resolve()
                require(source.is_relative_to(destination.resolve()) and not source.is_symlink(), 'Unsafe attachment path')
                require(0 < source.stat().st_size <= 2 * 1024 * 1024, 'Screenshot exceeds per-image budget')
                data = source.read_bytes(); require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'Expected lossless PNG evidence')
                total = sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file())
                require(total + len(data) <= 24 * 1024 * 1024 - 64 * 1024, 'Evidence package budget exceeded')
                target = EVIDENCE / (label + '-' + name + '.png'); target.write_bytes(data)
                kept.append({'name': name, 'path': target.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        write_json(EVIDENCE / (label + '-screenshots.json'), kept)

    def main(self):
        require(sys.platform == 'darwin', 'This gate requires the xcode-27 cloud runner')
        require(os.environ.get('GITHUB_EVENT_NAME') == 'push' and os.environ.get('GITHUB_REF') == 'refs/heads/touchcolor-original-design',
                'Only the root-controlled original-design branch push may activate this gate')
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
        require(len(hosted) == 29 and len(ui) == 5, 'Reviewed testcase inventory changed; update the explicit gate before execution')
        fixture = WORK / 'original-design-six-colors.png'; fixture.write_bytes(fixture_png())
        write_json(EVIDENCE / 'fixture.json', {'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'width': 300, 'height': 200,
                                             'colors': ['#ff0000', '#00ff00', '#0000ff', '#00ffff', '#ff00ff', '#ffff00']})
        app = WORK / 'derived/Build/Products/Debug-iphonesimulator/TouchColor.app'
        require(app.is_dir(), 'Exact built app is missing')
        for index, name in enumerate(DEVICE_NAMES):
            found = [d for d in types if d['name'] == name]
            require(len(found) == 1, 'Required simulator device type missing: ' + name)
            label = 'se3' if index == 0 else 'ipad-mini'
            owned_name = 'TouchColor-Original-' + label + '-' + uuid.uuid4().hex[:12]
            device = self.text(label + '-create', ['xcrun', 'simctl', 'create', owned_name, found[0]['identifier'], runtime[0]['identifier']], simulator=True)
            require(re.fullmatch(r'[0-9A-Fa-f-]{36}', device) is not None, 'Invalid created simulator identity')
            self.owned.append(device)
            self.devices.append({'name': name, 'owned_name': owned_name, 'udid': device, 'runtime': runtime[0]})
            write_json(EVIDENCE / 'devices.json', self.devices)
            self.command(label + '-boot', ['xcrun', 'simctl', 'boot', device], 45, simulator=True)
            self.await_owned_boot(label, device, owned_name)
            self.command(label + '-install', ['xcrun', 'simctl', 'install', device, str(app)], 90, simulator=True)
            self.run_tests(label, device, 'hosted', ['TouchColorTests/' + c for c in HOSTED_SOURCES], hosted)
            self.command(label + '-seed', ['xcrun', 'simctl', 'addmedia', device, str(fixture)], 60, simulator=True)
            self.run_tests(label, device, 'ui', ['TouchColorUITests/' + UI_CLASS], ui)
            self.command(label + '-shutdown', ['xcrun', 'simctl', 'shutdown', device], 60, simulator=True)
            self.command(label + '-delete', ['xcrun', 'simctl', 'delete', device], 45, simulator=True)
            self.owned.remove(device)
        self.command('clean-end', ['git', 'diff', '--exit-code', 'HEAD', '--'], 30)

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
    budget = 24 * 1024 * 1024
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
    parser.add_argument('--admit-evidence', action='store_true')
    args = parser.parse_args()
    if args.admit_evidence:
        admit_evidence(); return 0
    require(args.expected_sha is not None, 'Supply --expected-sha')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Native gate interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    gate = Gate(args.expected_sha); passed = False; error = None
    try:
        gate.main(); passed = True
    except BaseException as failure:
        error = str(failure)[:1000]
    finally:
        gate.cleanup()
        total = sum(p.stat().st_size for p in EVIDENCE.rglob('*') if p.is_file())
        passed = passed and not gate.owned and not gate.uncertain_simulator and total <= 24 * 1024 * 1024
        write_json(EVIDENCE / 'acceptance.json', {'functional_passed': passed, 'error': error, 'source_sha': args.expected_sha,
                   'pending_owned_devices': gate.owned, 'simulator_uncertain': gate.uncertain_simulator, 'evidence_bytes': total,
                   'visual_comparison': 'not automatically accepted; inspect six named screenshots per device against original design',
                   'release_claim': False})
    if error: print(error, file=sys.stderr)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
