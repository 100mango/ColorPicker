"""Closed canonical UIKit hosted-first setup and three complete XCTest targets.

A configured fresh UUID and built product digest are not an installed-byte seal.
Only a timely full hosted result permits the original Files/Photos preparation.
"""
import time
STARTED = time.monotonic()
import hashlib
import json
import math
import os
import re
from pathlib import Path
import signal
import stat
import subprocess
import sys

from atomic_json import write_json
from bounded_process import group_exists, stop_group
from palette_lifecycle_diagnostics import capture, strict_json, require
from uikit_managed_device import (create_owned_device, read_binding, read_managed_device,
                                  read_managed_device_state, require_job)
from uikit_runtime_diagnostics import MAX_PREPARATION_OUTPUT_BYTES
from uikit_warmup import Warmup, WarmupFailed, interrupted

# Existing workflow step ceilings. The whole command grant must fit, plus both
# owned-cleanup tails and the result reader; entry never resets this clock.
STEPS = {'TouchColorTests': (600, 500, 53), 'TouchColorUITests': (1200, 1100, None),
         'AccessibilityAudits': (720, 620, 7)}
CLEANUP, SUMMARY = 20, 20


def read_regular(path, cap, *, allow_empty=False):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Linked local evidence')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                (0 if allow_empty else 1) <= before.st_size <= cap,
                'Unsafe local evidence')
        raw = bytearray()
        while len(raw) <= cap:
            block = os.read(fd, min(65536, cap + 1 - len(raw)))
            if not block: break
            raw.extend(block)
        after = os.fstat(fd)
        require(len(raw) == before.st_size and all(getattr(before, k) == getattr(after, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')),
                'Local evidence changed during read')
        return bytes(raw)
    finally:
        os.close(fd)


class ProductInventoryError(ValueError):
    def __init__(self, observation):
        self.observation = dict(observation)
        super().__init__('Product inventory ' + observation['reason'])


def product_identity(clock=time.monotonic, *, post_test_deadline=None, observation=None):
    """Hash the unchanged full product trees; diagnostics are not identity bytes.

    Only the post-command host scan receives 20 seconds, clipped to the caller's
    original phase minus its summary/cleanup tail. Initial scans retain 10.
    File reads remain cooperative: a late read is rejected before hashing or
    further work, and a late final hash is rejected before returning an identity.
    """
    began = clock(); seconds = 10 if post_test_deadline is None else 20
    deadline = min(began + seconds, post_test_deadline) if post_test_deadline is not None else began + seconds
    value = {'schema': 1, 'stage': 'initial' if post_test_deadline is None else 'post_test',
             'status': 'scanning', 'complete': False, 'reason': None, 'safety_detail': None,
             'files': 0, 'bytes': 0, 'directories': 0, 'directory_entries': 0,
             'started_monotonic': began, 'deadline_monotonic': deadline,
             'elapsed_seconds': 0., 'allowance_seconds': seconds,
             'granted_seconds': max(0., deadline - began),
             'limits': {'directory_entries': 8192, 'files': 8192,
                        'bytes': 1024**3, 'file_bytes': 128 * 1024 * 1024}}
    digest = hashlib.sha256()
    def publish():
        if observation is not None:
            observation.clear(); observation.update(value)
    def fail(reason, detail=None):
        value.update(status='failed', reason=reason, safety_detail=detail,
                     elapsed_seconds=max(0., clock() - began))
        publish()
        raise ProductInventoryError(value)
    def check_time():
        now = clock(); value['elapsed_seconds'] = max(0., now - began)
        if now >= deadline:
            fail('phase_deadline' if post_test_deadline is not None and
                 post_test_deadline <= began + seconds else 'elapsed_limit')
    def safe(condition, detail):
        if not condition: fail('safety', detail)
    def walk_error(error):
        fail('safety', 'unreadable_directory')
    try:
        check_time()
        roots = (Path('build/simulator/Build/Products'), Path('build/palette-fixtures/Build/Products'))
        safe(len(list(roots[0].glob('*.xctestrun'))) == 1, 'test_configuration')
        for path in (roots[0] / 'Debug-iphonesimulator/TouchColor.app',
                     roots[0] / 'Debug-iphonesimulator/TouchColorUITests-Runner.app',
                     roots[1] / 'Debug-iphonesimulator/PaletteFixtures.app'):
            safe(path.is_dir() and not path.is_symlink(), 'missing_or_linked_product')
        for root in roots:
            safe(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), 'unsafe_tree')
            for parent, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
                value['directories'] += 1
                value['directory_entries'] = len(directories) + len(files)
                if value['directory_entries'] > 8192: fail('directory_entries_limit')
                check_time()
                safe(not any((Path(parent) / p).is_symlink() for p in directories), 'linked_directory')
                directories.sort()
                for name in sorted(files):
                    check_time()
                    path = Path(parent) / name
                    try: raw = read_regular(path, 128 * 1024 * 1024, allow_empty=True)
                    except (ValueError, OSError): fail('safety', 'unsafe_or_unreadable_file')
                    value['files'] += 1; value['bytes'] += len(raw)
                    if value['files'] > 8192: fail('file_count_limit')
                    if value['bytes'] > 1024**3: fail('total_bytes_limit')
                    check_time()
                    digest.update(path.as_posix().encode() + b'\0' + str(len(raw)).encode() + b'\0' + raw)
                    check_time()
        check_time()
    except ProductInventoryError:
        raise
    except (WarmupFailed, KeyboardInterrupt):
        fail('interrupted')
    except (ValueError, OSError):
        fail('safety', 'unreadable_tree')
    value.update(status='complete', complete=True); publish()
    return {'tree_sha256': digest.hexdigest(), 'files': value['files'], 'bytes': value['bytes'],
            'claim': 'built_product_bytes_only'}


def record_path(family, suffix):
    return Path('build') / (family + '-managed-' + suffix + '.json')


def load_setup(family):
    binding = read_binding(family)
    value = strict_json(read_regular(record_path(family, 'setup'), 16384))
    require(set(value) == {'schema', 'binding', 'products'} and type(value['schema']) is int and value['schema'] == 1 and
            value['binding'] == binding, 'Configured setup belongs to another binding')
    require(value['products'] == product_identity(), 'Built test/fixture products changed')
    return value


def verify_source(warmup, context):
    # All commands consume the caller's original step clock and stop latch.
    require(warmup.command(['git', 'rev-parse', 'HEAD'], 30, simulator=False).strip() == context['sha'],
            'Checkout differs from workflow source')
    require(warmup.command(['git', 'diff', '--quiet', 'HEAD', '--'], 30, simulator=False).strip() == '',
            'Tracked source differs from tested checkout')


def configure(family, started=STARTED):
    context = require_job(family)
    warmup = ManagedWarmup(family, started=started)
    path = record_path(family, 'setup')
    require(not path.exists() and not path.is_symlink(), 'No repeated configuration')
    verify_source(warmup, context)
    products = product_identity()
    create_owned_device(warmup)
    binding = read_binding(family)
    warmup.require_time()
    write_json(path, {'schema': 1, 'binding': binding, 'products': products}, limit=16384)
    warmup.require_time()
    print('UIKIT_MANAGED_CONFIGURED:' + json.dumps({'family': family, 'device': binding['identity']['udid'],
          'products': products, 'pretest_boot_completion': 'not_requested',
          'pretest_installed_bytes': 'not_observed'}, sort_keys=True), flush=True)


def require_hosted(family, setup):
    value = strict_json(read_regular(record_path(family, 'TouchColorTests'), 32768))
    require(type(value.get('schema')) is int and value['schema'] == 1 and value.get('suite') == 'TouchColorTests' and
            value.get('setup') == setup and value.get('qualified') is True and
            value.get('command', {}).get('status') == 'timely_exit' and
            value.get('command', {}).get('exit_code') == 0 and
            value.get('command', {}).get('host_cleanup_confirmed') is True,
            'Full timely hosted success is required before fixture preparation')
    fields = value.get('summary', {}).get('fields', {})
    skips = 1 if family.startswith('iPhone') else 0
    expected = {'result': 'Passed', 'totalTestCount': 53, 'passedTests': 53 - skips,
                'failedTests': 0, 'skippedTests': skips, 'expectedFailures': 0,
                'qualified': True, 'device': setup['binding']['identity']['udid']}
    require(value.get('summary', {}).get('status') == 'complete' and 'error' not in value and
            all(type(fields.get(k)) is type(v) and fields[k] == v for k, v in expected.items()),
            'Hosted receipt does not contain the required complete passing counts')
    return value


def setup_capture(command, timeout):
    result = capture(command, seconds=timeout, cap=1_000_000, cleanup_grace=10)
    result.stderr_prefix = result.stderr[:4096]
    result.stderr_observed_bytes = len(result.stderr)
    result.stdout = result.stdout.decode('utf-8', errors='replace')
    result.stderr = result.stderr.decode('utf-8', errors='replace')
    return result


def preparation_failure(binding, observation, error_type):
    """One terminal app-scoped stderr frame; unknown text is never disclosed.

    Preserve recognized simctl state/error lines exactly, with an explicit gap
    for everything else. Prefix hashes refer to original captured bytes, not to
    the allowlisted text. Neither host cleanup nor stderr proves daemon state.
    """
    observation = dict(observation)
    raw = observation.pop('stderr_prefix', None)
    observed = observation.pop('stderr_observed_bytes', None)
    complete = observation.pop('stderr_complete')
    text = ''; omitted = None
    if type(raw) is bytes:
        require(len(raw) <= 4096, 'Preparation stderr prefix exceeds bound')
        domains = (r'com\.apple\.CoreSimulator\.SimError|NSPOSIXErrorDomain|NSCocoaErrorDomain|'
                   r'NSOSStatusErrorDomain|MIInstallerErrorDomain|IXUserPresentableErrorDomain')
        safe = re.compile(r'(?:An error was encountered processing the command \(domain=(?:' +
            domains + r'), code=-?[0-9]{1,10}\):|Unable to (?:boot device|install app) in current state: '
            r'(?:Shutdown|Booted|Booting|Shutting Down)|Invalid device state)')
        # An incomplete last line could hide a sensitive suffix; omit it.
        decoded = raw.decode('utf-8', errors='replace')
        lines = decoded.splitlines(keepends=True)
        kept = [line.rstrip('\r\n') for line in lines if
                (line.endswith(('\r', '\n')) or (complete and observed == len(raw)))
                and safe.fullmatch(line.rstrip('\r\n'))]
        text = '\n'.join(kept)
        omitted = len(lines) - len(kept)
    stderr = {'available': raw is not None, 'observed_bytes': observed,
        'captured_prefix_bytes': len(raw) if raw is not None else None,
        'captured_prefix_sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None,
        'stream_complete': complete, 'truncated': None if raw is None else not complete or observed != len(raw),
        'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'omitted_lines': omitted, 'policy': 'exact_allowlisted_simctl_error_lines_only'}
    value = {'schema': 1, 'family': binding['identity']['family'], 'deviceId': binding['identity']['udid'],
        'source': binding['context'], 'identity_sha256': binding['identity_sha256'],
        'binding_sha256': binding['receipt_sha256'], 'command': observation,
        'error_type': error_type, 'simulator_completion': 'not_inferred', 'stderr': stderr}
    line = 'UIKIT_PREPARATION_FAILURE:' + json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n'
    require(len(line.encode()) + 128 <= MAX_PREPARATION_OUTPUT_BYTES,
            'Preparation failure framing exceeds shared allocation')
    return line


class ManagedWarmup(Warmup):
    def __init__(self, *args, host_runner=setup_capture, **kwargs):
        super().__init__(*args, **kwargs)
        self.host_runner = host_runner
        self.runner = self.absolute_runner
        self.operation_deadline = None
        self.fixture_observation = None

    def command(self, arguments, seconds, **kwargs):
        self.operation_deadline = min(self.clock() + seconds, self.deadline - CLEANUP)
        try: return super().command(arguments, seconds, **kwargs)
        finally: self.operation_deadline = None

    def absolute_runner(self, command, timeout):
        # Recompute after Warmup's durable-marker write, before process dispatch.
        require(self.operation_deadline is not None, 'Missing original preparation admission')
        deadline = min(self.clock() + timeout, self.operation_deadline, self.deadline - CLEANUP)
        grant = deadline - self.clock()
        require(grant > 0, 'Preparation entry expired before capture')
        if self.fixture_observation is not None:
            self.fixture_observation.update(started_monotonic=self.clock(), deadline_monotonic=deadline)
        try:
            result = self.host_runner(command, timeout=grant)
        except BaseException as error:
            if self.fixture_observation is not None:
                self.fixture_observation.update(
                    host_cleanup_confirmed=getattr(error, 'cleanup_confirmed', None),
                    stderr_prefix=getattr(error, 'stderr_prefix', None),
                    stderr_observed_bytes=getattr(error, 'stderr_observed_bytes', None))
            raise
        if self.fixture_observation is not None:
            self.fixture_observation.update(exit_code=result.returncode, host_cleanup_confirmed=True,
                stderr_prefix=getattr(result, 'stderr_prefix', result.stderr.encode('utf-8')[:4096]),
                stderr_observed_bytes=getattr(result, 'stderr_observed_bytes', len(result.stderr.encode('utf-8'))),
                stderr_complete=True, returned_monotonic=self.clock())
        require(self.clock() < deadline, 'Preparation returned after original absolute deadline')
        return result

    def owned_device(self):
        binding = read_managed_device(self.family, self.command, self.require_time)
        return self.bind_owned_device(binding)

    def bind_owned_device(self, binding):
        self.managed_binding = binding
        self.identity = binding['identity']
        self.identity_path = self.build / (self.family + '-simulator.json')
        self.identity_bytes = self.identity_path.read_bytes()
        self.require_identity()
        return self.identity['udid']

    def stop_fixture(self):
        # The same durable fence blocks all finalizers and another invocation.
        if not self.pending.exists() and not self.pending.is_symlink():
            with self.pending.open('x') as marker:
                marker.write('Terminal fixture failure; later simulator commands are blocked.\n')

    def fixture_device(self, setup):
        try:
            current = read_managed_device_state(self.family, self.command, self.require_time)
            require(current['binding'] == setup['binding'], 'Post-hosted binding differs from setup')
            device = self.bind_owned_device(current['binding'])
            if current['state'] == 'Shutdown':
                self.fixture_command(['xcrun', 'simctl', 'boot', device], 180)
                self.require_identity()
                self.fixture_command(['xcrun', 'simctl', 'bootstatus', device, '-b'], 240)
                self.require_identity()
                current = read_managed_device_state(self.family, self.command, self.require_time)
            require(current['binding'] == self.managed_binding and current['state'] == 'Booted',
                    'Same owned simulator must be Booted before fixture installation')
            self.require_identity()
            return device
        except BaseException:
            self.stop_fixture()
            raise

    def fixture_command(self, arguments, seconds):
        require(not self.pending.exists() and not self.pending.is_symlink(),
                'Earlier fixture command remains blocked')
        device = self.identity['udid']
        allowed = [(['xcrun', 'simctl', 'boot', device], 180),
                   (['xcrun', 'simctl', 'bootstatus', device, '-b'], 240),
                   (['xcrun', 'simctl', 'install', device,
                     'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90)]
        require((arguments, seconds) in allowed, 'Unexpected fixture evidence command')
        self.require_identity()
        self.fixture_observation = {'argv': arguments, 'exit_code': None,
            'host_cleanup_confirmed': None, 'stderr_complete': False}
        try:
            return self.command(arguments, seconds)
        except BaseException as error:
            # A known nonzero return removed Warmup's uncertainty marker. Keep
            # a terminal stop fence as well; failure is never a retry grant.
            self.stop_fixture()
            print(preparation_failure(self.managed_binding, self.fixture_observation,
                                      type(error).__name__), end='', flush=True)
            raise
        finally:
            self.fixture_observation = None

    def require_identity(self):
        super().require_identity()
        require(read_binding(self.family) == self.managed_binding, 'Managed ownership changed')


def fixture_seed(family, started=STARTED):
    warmup = ManagedWarmup(family, started=started)
    setup = load_setup(family)
    require_hosted(family, setup)
    verify_source(warmup, setup['binding']['context'])
    device = warmup.fixture_device(setup)
    # Exact predecessor Files-host command families and fixture assertions.
    warmup.fixture_command(['xcrun', 'simctl', 'install', device,
                    'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90)
    warmup.command(['xcrun', 'simctl', 'launch', '--terminate-running-process', device,
                    'com.mango.touchColor.tests.paletteFixtures'], 60)
    container = warmup.command(['xcrun', 'simctl', 'get_app_container', device,
                                'com.mango.touchColor.tests.paletteFixtures', 'data'], 30).strip()
    warmup.fixture(container)
    warmup.command(['xcrun', 'simctl', 'terminate', device, 'com.mango.touchColor.tests.paletteFixtures'], 30)
    warmup.command(['xcrun', 'simctl', 'spawn', device, 'launchctl', 'print', 'system'], 20, optional=True)
    warmup.command(['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-showdestinations'],
                    30, optional=True, simulator=False)
    warmup.seed(device)
    warmup.require_identity()
    require(load_setup(family) == setup, 'Setup changed during fixture preparation')
    write_json(record_path(family, 'fixtures'), {'schema': 1, 'setup': setup, 'complete': True}, limit=16384)
    warmup.require_time()


def require_fixtures(family, setup):
    value = strict_json(read_regular(record_path(family, 'fixtures'), 16384))
    require(type(value.get('schema')) is int and value == {'schema': 1, 'setup': setup, 'complete': True}, 'Same-device Files and Photos fixture required')
    seed = strict_json(read_regular(Path('build') / (family + '-fixture-seeded'), 8192))
    require(seed == setup['binding']['identity'], 'Photo seed identity differs')


def test_argv(family, suite, device):
    require(suite in STEPS, 'Unknown canonical suite')
    selection = suite
    if suite == 'TouchColorUITests':
        selection += '/TouchColorIPadUITests' if family.startswith('iPad') else '/TouchColorUITests'
    elif suite == 'AccessibilityAudits':
        selection = 'TouchColorUITests/TouchColorAccessibilityUITests'
    return ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-configuration', 'Debug',
            '-destination', 'platform=iOS Simulator,id=' + device, '-derivedDataPath', 'build/simulator',
            '-resultBundlePath', 'build/' + family + '-' + suite + '.xcresult', '-parallel-testing-enabled', 'NO',
            '-collect-test-diagnostics', 'never', '-test-timeouts-enabled', 'YES',
            '-default-test-execution-time-allowance', '180', '-maximum-test-execution-time-allowance', '240',
            '-only-testing:' + selection, 'test-without-building']


def invoke(command, deadline, *, clock=time.monotonic, popen=subprocess.Popen, stopper=stop_group):
    """Keep original live output/phone pipe; supervise only this owned process group."""
    began = clock()
    value = {'status': 'not_started', 'exit_code': None, 'host_cleanup_confirmed': None,
             'simulator_completion': 'unconfirmed', 'argv': command,
             'started_monotonic': began, 'deadline_monotonic': deadline}
    process = None; cancelled = [None]; previous = {}
    def interrupt(signum, frame):
        if cancelled[0] is None: cancelled[0] = signum
    try:
        require(clock() < deadline, 'Expired XCTest entry')
        for sig in (signal.SIGTERM, signal.SIGINT): previous[sig] = signal.signal(sig, interrupt)
        process = popen(command, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            require(cancelled[0] is None and clock() < deadline, 'Interrupted or expired XCTest')
            try:
                code = process.wait(timeout=min(.1, deadline - clock()))
                break
            except subprocess.TimeoutExpired:
                continue
        require(cancelled[0] is None and clock() < deadline and not group_exists(process.pid),
                'Late XCTest or live owned descendant')
        value.update(status='timely_exit', exit_code=code, host_cleanup_confirmed=True,
                     simulator_completion='xcode_command_returned_only')
    except BaseException as error:
        value.update(status='incomplete', reason=str(error)[:160])
        if process is not None:
            try: value['host_cleanup_confirmed'] = stopper(process, grace=CLEANUP / 2)
            except BaseException: value['host_cleanup_confirmed'] = False
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)
    if cancelled[0] is not None:
        value.update(status='incomplete', signal=cancelled[0], simulator_completion='unconfirmed')
    value.update(finished_monotonic=clock(), elapsed_seconds=clock() - began)
    return value


def summary_fields(raw, family, suite, identity, began, finished, code):
    value = strict_json(raw)
    fields = ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests', 'expectedFailures')
    require(all(type(value.get(k)) is int and value[k] >= 0 for k in fields), 'Invalid summary counts')
    count = STEPS[suite][2] if suite != 'TouchColorUITests' else (15 if family.startswith('iPad') else 17)
    require(value['totalTestCount'] == count and
            value['passedTests'] + value['failedTests'] + value['skippedTests'] == count and
            value['expectedFailures'] == 0, 'Incomplete or changed full-target inventory')
    expected_skips = 1 if suite == 'TouchColorTests' and family.startswith('iPhone') else 0
    # Preserve the declared WatchConnectivity capability skip in hosted phone tests.
    require(value['skippedTests'] == expected_skips, 'Unexpected skipped tests')
    require(all(type(value.get(k)) in (int, float) and math.isfinite(value[k]) for k in ('startTime', 'finishTime'))
            and began <= value['startTime'] <= value['finishTime'] <= finished, 'Stale or foreign summary interval')
    devices = value.get('devicesAndConfigurations')
    require(isinstance(devices, list) and len(devices) == 1, 'Ambiguous result destination')
    row = devices[0]
    require(row.get('device', {}).get('deviceId') == identity['udid'] and
            row['device'].get('platform') == 'iOS Simulator' and row['device'].get('osVersion') == '27.0',
            'Foreign result destination')
    require(all(row.get(k) == value[k] for k in fields[1:]), 'Per-device summary differs')
    passed = value['failedTests'] == 0
    require(value.get('result') == ('Passed' if passed else 'Failed') and (code == 0 if passed else code != 0),
            'Command and full-target result contradict')
    return {**{k: value[k] for k in fields}, 'result': value['result'], 'qualified': passed,
            'device': identity['udid'], 'startTime': value['startTime'], 'finishTime': value['finishTime']}


def run_suite(family, suite, *, started=STARTED, clock=time.monotonic, wall=time.time,
              runner=invoke, reader=capture, products=product_identity):
    require(suite in STEPS, 'Unknown canonical test target')
    seconds, grant, _ = STEPS[suite]; deadline = started + seconds
    warmup = ManagedWarmup(family, started=started, clock=clock, seconds=seconds)
    setup = load_setup(family)
    verify_source(warmup, setup['binding']['context'])
    if suite != 'TouchColorTests':
        require_hosted(family, setup); require_fixtures(family, setup)
    path = record_path(family, suite)
    result_path = Path('build') / (family + '-' + suite + '.xcresult')
    require(not path.exists() and not path.is_symlink() and not result_path.exists() and not result_path.is_symlink(),
            'No repeated suite or reused result bundle')
    record = {'schema': 1, 'suite': suite, 'setup': setup, 'qualified': False,
              'command': {'status': 'not_started'}, 'summary': {'status': 'not_started'}}
    def persist(): write_json(path, record, limit=32768)
    try:
        require(clock() + grant + 2 * CLEANUP + SUMMARY < deadline, 'Full XCTest and evidence tail cannot fit')
        with warmup.pending.open('x') as marker:
            marker.write('Managed XCTest has no confirmed timely completion.\n'); marker.flush(); os.fsync(marker.fileno())
        persist()
        require(clock() + grant + 2 * CLEANUP + SUMMARY < deadline, 'Entry persistence exhausted test admission')
        began = wall(); command_deadline = clock() + grant
        record['command'] = runner(test_argv(family, suite, setup['binding']['identity']['udid']), command_deadline)
        finished = wall()
        persist()  # Preserve observed XCTest outcome before host-only readers.
        require(record['command'].get('status') == 'timely_exit' and
                record['command'].get('host_cleanup_confirmed') is True and clock() < command_deadline,
                'Uncertain or late XCTest; all later simulator operations blocked')
        require(read_binding(family) == setup['binding'], 'Post-test binding changed')
        record['product_inventory'] = {'status': 'not_started'}
        observed = products(clock=clock, post_test_deadline=deadline - SUMMARY - CLEANUP,
                            observation=record['product_inventory'])
        require(observed == setup['products'], 'Post-test products changed')
        require(clock() + SUMMARY + CLEANUP < deadline, 'Summary and owned cleanup cannot fit')
        # The read grant is derived again after the receipt write, without reset.
        summary_deadline = min(clock() + SUMMARY, deadline - CLEANUP)
        record['summary'] = {'status': 'pending'}; persist()
        available = summary_deadline - clock()
        require(available > 0, 'Expired summary entry')
        result = reader(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(result_path)],
                        seconds=available, cap=1024 * 1024, cleanup_grace=10)
        record['summary'] = {'status': 'reader_returned', 'exit_code': result.returncode,
                             'host_cleanup_confirmed': True}
        require(clock() < summary_deadline and clock() < deadline, 'Late summary result')
        # A timely host-only nonzero result leaves qualification unavailable, but
        # does not claim that an already completed XCTest is simulator-uncertain.
        warmup.pending.unlink()
        require(result.returncode == 0, 'Summary reader failed')
        fields = summary_fields(result.stdout, family, suite, setup['binding']['identity'], began, finished,
                                record['command']['exit_code'])
        record['summary'] = {'status': 'complete', 'fields': fields, 'exit_code': 0,
                             'host_cleanup_confirmed': True,
                             'bytes': len(result.stdout), 'sha256': hashlib.sha256(result.stdout).hexdigest()}
        record['qualified'] = fields['qualified']
        persist()
        require(clock() < deadline, 'Final receipt exceeded original step')
        return 0 if record['qualified'] else (record['command']['exit_code'] or 3)
    except BaseException as error:
        if isinstance(error, ProductInventoryError):
            record['product_inventory'] = error.observation
        if record['summary'].get('status') == 'pending':
            record['summary'] = {'status': 'unavailable',
                                 'host_cleanup_confirmed': getattr(error, 'cleanup_confirmed', None)}
        record['qualified'] = False; record['error'] = str(error)[:160]
        persist()
        return 3
    finally:
        # Fixed small typed summary; raw app output already used the original stream.
        print('UIKIT_MANAGED_RESULT:' + json.dumps({'family': family, 'suite': suite,
              'source': setup['binding']['context'], 'command': record['command'],
              'summary': record['summary'], 'qualified': record['qualified'],
              'product_inventory': record.get('product_inventory'),
              'error': record.get('error')}, sort_keys=True), flush=True)


def main():
    family, mode = sys.argv[1:]
    if mode == 'configure': configure(family); return 0
    if mode == 'fixture-seed': fixture_seed(family); return 0
    if mode == 'managed-shutdown':
        warmup = ManagedWarmup(family, started=STARTED, seconds=120)
        warmup.shutdown(warmup.owned_device()); return 0
    return run_suite(family, {'managed-hosted': 'TouchColorTests', 'managed-functional': 'TouchColorUITests',
                              'managed-audits': 'AccessibilityAudits'}[mode])


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try: raise SystemExit(main())
    except Exception as error:
        if isinstance(error, ProductInventoryError):
            print('UIKIT_PRODUCT_INVENTORY:' + json.dumps(error.observation, sort_keys=True), flush=True)
        print('BLOCKED managed UIKit: ' + str(error), file=sys.stderr, flush=True)
        raise SystemExit(3)
