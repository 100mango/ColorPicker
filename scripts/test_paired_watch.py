#!/usr/bin/env python3
"""Prepared paired-simulator foreground E2E; register both UI tests before enabling CI.

The host only pairs/boots/installs and coordinates two real XCTest processes. Palette
messages and receipts must travel through production WatchConnectivity sendMessage.
Background transferUserInfo and Watch Photos remain separate physical-device gates.
"""
import collections
import datetime
import json
from pathlib import Path
import plistlib
import re
import subprocess
import threading
import time
import uuid
from bounded_process import run_captured, stop_group

OUT = Path('build/paired-runtime')
OUT.mkdir(parents=True, exist_ok=True)
report = {'result': 'not run', 'stages': [], 'transport': 'production foreground sendMessage', 'devices': []}
created = []
pair = None
phone_process = None
watch_process = None

def run(command, timeout, required=True):
    if report.get('cleanup_unconfirmed'):
        if required: raise RuntimeError('Prior child exit is unconfirmed; refusing new paired work')
        return ''
    start = time.monotonic()
    wall_start = time.time()
    active = {'command': command, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'started_monotonic': start, 'timeout_seconds': timeout}
    def checkpoint(phase):
        active.update(phase=phase, monotonic_elapsed=round(time.monotonic()-start, 3), wall_elapsed=round(time.time()-wall_start, 3))
        report['active_command'] = active
        (OUT/'runtime.json').write_text(json.dumps(report, indent=2)+'\n')
        print('PAIRED_COMMAND_CHECKPOINT', json.dumps(active), flush=True)
    checkpoint('starting')
    try:
        result = run_captured(command, timeout, checkpoint=checkpoint)
        output, code, diagnostic = result.stdout, result.returncode, (result.stdout+result.stderr)[-8000:]
    except subprocess.TimeoutExpired as error:
        confirmed = bool(getattr(error, 'cleanup_confirmed', False))
        if not confirmed: report['cleanup_unconfirmed'] = True
        code, output, diagnostic = 124, '', 'Command timed out; process-group exit confirmed: ' + str(confirmed)
    report['stages'].append({'command': command, 'exit': code, 'seconds': round(time.monotonic()-start, 2),
                             'wall_seconds': round(time.time()-wall_start, 2), 'diagnostic': diagnostic})
    report['active_command'] = None
    print('PAIRED_STAGE', json.dumps(report['stages'][-1]), flush=True)
    if required and code:
        raise RuntimeError('Paired prerequisite failed: ' + ' '.join(command))
    return output.strip()

def configured_test_run(directory):
    candidates = list((Path(directory)/'Build/Products').glob('*.xctestrun'))
    assert len(candidates) == 1, 'Expected exactly one generated test run'
    source = candidates[0]
    value = plistlib.loads(source.read_bytes())
    count = 0
    def visit(node):
        nonlocal count
        if isinstance(node, dict):
            if 'TestBundlePath' in node:
                node.setdefault('EnvironmentVariables', {})['TOUCHCOLOR_PAIRED_E2E'] = '1'
                count += 1
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    assert count > 0, 'No test target environment found'
    # Keep __TESTROOT__ expansion identical to Xcode's generated product location.
    destination = source.with_name(source.stem + '-paired.xctestrun')
    destination.write_bytes(plistlib.dumps(value))
    return destination

class RunningTests:
    def __init__(self, label, command):
        self.label = label
        self.ready = threading.Event()
        self.markers = []
        self.tail = collections.deque(maxlen=1000)
        self.tail_lock = threading.Lock()
        self.started = time.monotonic(); self.wall_started = time.time()
        self.stop_requested = False; self.cleanup_confirmed = None
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
    def read(self):
        for line in self.process.stdout:
            with self.tail_lock:
                self.tail.append(line[-4000:])
            if 'TOUCHCOLOR_PAIRED_' in line:
                marker = re.search(r'TOUCHCOLOR_PAIRED_[A-Z_]+', line)
                if marker:
                    self.markers.append(marker.group(0)); print(marker.group(0), flush=True)
                    if marker.group(0) == 'TOUCHCOLOR_PAIRED_PHONE_READY': self.ready.set()
    def stop(self):
        if self.stop_requested: return self.cleanup_confirmed
        self.stop_requested = True
        def checkpoint(phase):
            state = {'test': self.label, 'phase': phase, 'pid': self.process.pid,
                     'monotonic_elapsed': round(time.monotonic()-self.started, 3),
                     'wall_elapsed': round(time.time()-self.wall_started, 3)}
            report['test_cleanup'] = state
            (OUT/'runtime.json').write_text(json.dumps(report, indent=2)+'\n')
            print('PAIRED_TEST_CLEANUP', json.dumps(state), flush=True)
        self.cleanup_confirmed = stop_group(self.process, checkpoint=checkpoint)
        if not self.cleanup_confirmed: report['cleanup_unconfirmed'] = True
        return self.cleanup_confirmed
    def finish(self, timeout):
        try: code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired: self.stop(); code = 124
        self.reader.join(timeout=5)
        with self.tail_lock:
            tail = ''.join(self.tail)[-128_000:]
        (OUT/(self.label+'-test-tail.log')).write_text(tail)
        report[self.label] = {'exit': code, 'markers': self.markers, 'cleanup_confirmed': self.cleanup_confirmed,
                              'monotonic_seconds': round(time.monotonic()-self.started, 3),
                              'wall_seconds': round(time.time()-self.wall_started, 3)}
        return code

try:
    # This script remains intentionally disabled until the coordinated source merge.
    for project, marker in [('TouchColor.xcodeproj/project.pbxproj', 'PhonePairedTransferTests.swift'), ('TouchColorWatch.xcodeproj/project.pbxproj', 'WatchPairedTransferTests.swift')]:
        assert marker in Path(project).read_text(), 'Paired UI test target registration pending: ' + marker
    report['sha'] = run(['git', 'rev-parse', 'HEAD'], 10)
    for target, platform, directory in [('TouchColor', 'iOS', 'paired-phone'), ('TouchColorWatch', 'watchOS', 'paired-watch')]:
        run(['xcodebuild', '-quiet', '-project', target+'.xcodeproj', '-scheme', target, '-configuration', 'Debug', '-destination', 'generic/platform='+platform+' Simulator', '-derivedDataPath', 'build/'+directory, 'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO', 'build-for-testing'], 420)
    devices = json.loads(run(['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 30))['devices']
    selected = {}
    for role, suffix, prefix in [('phone', 'iOS-27-0', 'iPhone'), ('watch', 'watchOS-27-0', 'Apple Watch')]:
        runtime, template = next((runtime, device) for runtime, rows in devices.items() if runtime.endswith(suffix) for device in rows if device.get('isAvailable') and device['name'].startswith(prefix))
        identifier = run(['xcrun', 'simctl', 'create', 'TouchColor-paired-'+role, template['deviceTypeIdentifier'], runtime], 60)
        uuid.UUID(identifier); created.append(identifier); selected[role] = identifier
        report['devices'].append({'role': role, 'id': identifier, 'runtime': runtime, 'type': template['deviceTypeIdentifier']})
    candidate_pair = run(['xcrun', 'simctl', 'pair', selected['watch'], selected['phone']], 60)
    uuid.UUID(candidate_pair); pair = candidate_pair
    run(['xcrun', 'simctl', 'pair_activate', pair], 60)
    for role in ('phone', 'watch'):
        run(['xcrun', 'simctl', 'boot', selected[role]], 120)
        run(['xcrun', 'simctl', 'bootstatus', selected[role], '-b'], 420)
        product = 'Debug-iphonesimulator' if role == 'phone' else 'Debug-watchsimulator'
        run(['xcrun', 'simctl', 'install', selected[role], 'build/paired-'+role+'/Build/Products/'+product+'/TouchColor.app'], 120)
    def command(role, test):
        path = configured_test_run('build/paired-'+role)
        platform = 'iOS' if role == 'phone' else 'watchOS'
        return ['xcodebuild', '-xctestrun', str(path), '-destination', 'platform='+platform+' Simulator,id='+selected[role], '-resultBundlePath', 'build/paired-'+role+'.xcresult', '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never', '-test-timeouts-enabled', 'YES', '-maximum-test-execution-time-allowance', '240', '-only-testing:'+test, 'test-without-building']
    phone_process = RunningTests('phone', command('phone', 'TouchColorUITests/PhonePairedTransferTests/testIncomingForegroundTransferReviewAcceptAndRelaunch'))
    assert phone_process.ready.wait(timeout=120), 'Phone never reached the real inbox review readiness marker'
    watch_process = RunningTests('watch', command('watch', 'TouchColorWatchUITests/WatchPairedTransferTests/testForegroundSendAcceptReceiptAndBothLocalStatesAfterRelaunch'))
    watch_exit = watch_process.finish(240)
    phone_exit = phone_process.finish(120)
    assert watch_exit == 0 and phone_exit == 0, 'Paired UI execution failed'
    assert 'TOUCHCOLOR_PAIRED_WATCH_RELAUNCH_VERIFIED' in watch_process.markers
    assert 'TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED' in phone_process.markers
    report['result'] = 'passed'
except Exception as error:
    report['result'] = 'failed'; report['error'] = str(error)
finally:
    for process in [watch_process, phone_process]:
        if process:
            process.stop()
            if process.label not in report: process.finish(1)
            else: report[process.label]['cleanup_confirmed'] = process.cleanup_confirmed
    if not report.get('cleanup_unconfirmed'):
        for device in reversed(created): run(['xcrun', 'simctl', 'shutdown', device], 60, required=False)
        if pair: run(['xcrun', 'simctl', 'unpair', pair], 60, required=False)
        for device in reversed(created): run(['xcrun', 'simctl', 'delete', device], 60, required=False)
    else:
        report['simulator_cleanup'] = 'No further commands on the unhealthy disposable VM; job teardown remains authoritative'
    (OUT/'runtime.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PAIRED_RESULT', json.dumps(report), flush=True)
if report['result'] != 'passed': raise SystemExit(1)
