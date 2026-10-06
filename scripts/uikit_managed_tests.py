"""Owned UIKit setup and original complete targets, plus fixed completion groups.

A configured fresh UUID and built product digest are not an installed-byte seal.
Original preparation requires full hosted success. The separate completion route
requires its actually executed two-case bootstrap, never a full-target claim.
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
from uikit_completion import resource_selection, selection

# Existing workflow step ceilings. The whole command grant must fit, plus both
# owned-cleanup tails and the result reader; entry never resets this clock.
STEPS = {'TouchColorTests': (600, 500, 54), 'TouchColorUITests': (1200, 1100, None),
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


def require_hosted(family, setup, *, clock=time.monotonic, deadline=None):
    if deadline is not None: require(clock() < deadline, 'Bootstrap reread exhausted caller phase')
    value = strict_json(read_regular(record_path(family, 'TouchColorTests'), 32768))
    selected = selection(family, 'TouchColorTests')
    if selected is not None:
        return require_selected_bootstrap(family, setup, value, selected, clock=clock, deadline=deadline)
    require(type(value.get('schema')) is int and value['schema'] == 1 and value.get('suite') == 'TouchColorTests' and
            value.get('setup') == setup and value.get('qualified') is True and
            value.get('command', {}).get('status') == 'timely_exit' and
            value.get('command', {}).get('exit_code') == 0 and
            value.get('command', {}).get('host_cleanup_confirmed') is True,
            'Full timely hosted success is required before fixture preparation')
    fields = value.get('summary', {}).get('fields', {})
    expected = {'result': 'Passed', 'totalTestCount': 54, 'passedTests': 54,
                'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0,
                'qualified': True, 'device': setup['binding']['identity']['udid']}
    require(value.get('summary', {}).get('status') == 'complete' and 'error' not in value and
            all(type(fields.get(k)) is type(v) and fields[k] == v for k, v in expected.items()),
            'Hosted receipt does not contain the required complete passing counts')
    return value


def require_selected_bootstrap(family, setup, value, selected, *, clock=time.monotonic, deadline=None):
    """Reconstruct the actual two-case bootstrap from its original bounded reads."""
    def remaining():
        if deadline is not None:
            require(clock() < deadline, 'Bootstrap reread exhausted caller phase')
    remaining()
    require(type(value.get('schema')) is int and value['schema'] == 3 and 'cases' not in value and
            value.get('summary_qualification_only') is True and
            value.get('case_identity_basis') == 'fixed_executed_argv_and_complete_summary' and
            value.get('per_case_log_reconciliation') == 'pending_external_review' and
            value.get('suite') == 'TouchColorTests' and value.get('selection') == selected and
            value.get('setup') == setup and value.get('qualified') is True and 'error' not in value,
            'Fresh selected bootstrap receipt required')
    command = value.get('command', {})
    require(command.get('status') == 'timely_exit' and type(command.get('exit_code')) is int and
            command['exit_code'] == 0 and command.get('host_cleanup_confirmed') is True and
            command.get('argv') == test_argv(family, 'TouchColorTests', setup['binding']['identity']['udid']),
            'Bootstrap command does not match the exact executed selection')
    timing = value.get('timing', {})
    keys = {'phase_started_monotonic', 'phase_deadline_monotonic', 'admitted_monotonic',
            'command_origin_monotonic', 'command_wall_started', 'command_wall_finished',
            'reader_admitted_monotonic', 'reader_started_monotonic', 'reader_deadline_monotonic', 'evidence_completed_monotonic'}
    require(isinstance(timing, dict) and set(timing) == keys and
            all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in timing.values()),
            'Missing original bootstrap phase and reader bounds')
    seconds, grant = (960, 800) if family == 'iPadMini' else STEPS['TouchColorTests'][:2]
    phase_start, phase_end = timing['phase_started_monotonic'], timing['phase_deadline_monotonic']
    admitted, origin = timing['admitted_monotonic'], timing['command_origin_monotonic']
    began, finished = timing['command_wall_started'], timing['command_wall_finished']
    times = [command.get(k) for k in ('started_monotonic', 'finished_monotonic', 'deadline_monotonic')]
    require(all(type(t) in (int, float) and math.isfinite(t) for t in times) and
            phase_end == phase_start + seconds and phase_start <= admitted <= origin <= times[0] <= times[1] < times[2] and
            times[2] == origin + grant and admitted + grant + 2 * CLEANUP + SUMMARY < phase_end and
            (family != 'iPadMini' or origin == admitted) and began <= finished,
            'Bootstrap original command admission or interval differs')
    reader_start, reader_end = timing['reader_started_monotonic'], timing['reader_deadline_monotonic']
    require(times[1] <= timing['reader_admitted_monotonic'] <= reader_start and
            timing['reader_admitted_monotonic'] + SUMMARY + CLEANUP < phase_end and
            reader_end == min(reader_start + SUMMARY, phase_end - CLEANUP) and
            reader_start <= timing['evidence_completed_monotonic'] < reader_end,
            'Bootstrap original shared reader allowance differs')
    proof = value.get('summary', {})
    read = proof.get('reader', {})
    expected_argv = ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path',
                     'build/' + family + '-TouchColorTests.xcresult']
    require(proof.get('status') == 'complete' and type(proof.get('exit_code')) is int and
            proof['exit_code'] == 0 and proof.get('host_cleanup_confirmed') is True and
            set(read) == {'argv', 'entered_monotonic', 'deadline_monotonic', 'returned_monotonic'} and
            read.get('argv') == expected_argv, 'Bootstrap reader exit, cleanup or argv differs')
    entry, end, returned = (read[k] for k in ('entered_monotonic', 'deadline_monotonic', 'returned_monotonic'))
    require(all(type(t) in (int, float) and math.isfinite(t) for t in (entry, end, returned)) and
            reader_start <= entry <= returned < end == reader_end and
            returned <= timing['evidence_completed_monotonic'], 'Bootstrap reader original interval differs')
    remaining()
    raw = read_regular(Path('build') / (family + '-TouchColorTests-selected-summary.json'), 1024 * 1024)
    remaining()
    require(type(proof.get('bytes')) is int and proof['bytes'] == len(raw) and
            proof.get('sha256') == hashlib.sha256(raw).hexdigest(), 'Bootstrap saved raw observation differs')
    remaining()
    fields = summary_fields(raw, family, 'TouchColorTests', setup['binding']['identity'], began, finished, 0)
    require(fields['qualified'] is True and value['summary'].get('fields') == fields,
            'Bootstrap persisted fields differ from raw results')
    remaining()
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


def completed_bootstatus(raw, expected):
    """Fail closed on any output outside the retained public Xcode27 shape."""
    require(isinstance(raw,str) and 0<len(raw.encode())<=65536,'Missing or oversized bootstatus output')
    header='Monitoring boot status for '+expected['name']+' ('+expected['device']+').\n'
    proof={'stdout_sha256':hashlib.sha256(raw.encode()).hexdigest(),'stdout_bytes':len(raw.encode())}
    # This wording is separately retained from an actual Xcode27 bootstatus -b
    # stdout. It proves no terminal status/Finished field; current operation
    # completion/cleanup and unchanged owned binding are checked by the caller.
    if raw==header+'Device already booted, nothing to do.\n\n':
        return {**proof,'completion_kind':'already_booted_no_work',
                'completion_message':'Device already booted, nothing to do.'}
    stamp=r'\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} \+[0-9]{4}\] '
    elapsed=r'Elapsed=[0-9]{2}:[0-5][0-9]\.\n'
    # Intermediate status/detail blocks are bounded, unqualified progress.
    # Only the final known terminal outcome contributes readiness evidence.
    progress=stamp+r'Status=(?!4294967295,)[0-9]{1,10}, isTerminal=NO, '+elapsed+\
             r'(?:\t{1,4}(?!Finished\n)[^\x00-\x1f\x7f]{1,1024}\n){1,16}\n'
    finished=stamp+r'Status=4294967295, isTerminal=YES, '+elapsed+r'\tFinished\n\n'
    require(re.fullmatch(re.escape(header)+'(?:'+progress+')*'+finished,raw) is not None,
                 'Unknown bootstatus output or missing exact owned terminal Finished')
    return {**proof,'completion_kind':'terminal_finished','terminal_status':4294967295,'isTerminal':True,'terminal_message':'Finished'}


class ManagedWarmup(Warmup):
    def __init__(self, *args, host_runner=setup_capture, **kwargs):
        super().__init__(*args, **kwargs)
        self.host_runner = host_runner
        self.runner = self.absolute_runner
        self.operation_deadline = None
        self.fixture_observation = None
        self.fixture_readiness = None
        self.last_fixture_operation = None

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
            readiness = {'schema': 2, 'device': device,
                'binding_sha256': current['binding']['receipt_sha256'],
                'basis': 'owned_booted_inventory_snapshot_only', 'completion': None,
                'operations': [], 'observed_monotonic': self.clock()}
            if current['state'] == 'Shutdown':
                self.fixture_command(['xcrun', 'simctl', 'boot', device], 180)
                readiness['operations'].append(self.last_fixture_operation)
                self.require_identity()
                raw = self.fixture_command(['xcrun', 'simctl', 'bootstatus', device, '-b'], 240)
                readiness['operations'].append(self.last_fixture_operation)
                self.require_identity()
                readiness.update(basis='owned_bootstatus_completion_observation_only',
                    completion=completed_bootstatus(raw, {'device': device,
                        'name': current['binding']['receipt']['requested_name']}),
                    observed_monotonic=self.clock())
            else:
                require(current['state'] == 'Booted', 'Unknown owned pre-fixture state')
            # No second global inventory: bootstatus is a completion observation,
            # not a continuously Booted state or a fresh JSON snapshot.
            self.require_identity()
            self.require_time()
            validate_fixture_readiness(readiness, setup)
            self.fixture_readiness = readiness
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
                     'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90),
                   (['xcrun', 'simctl', 'launch', '--terminate-running-process', device,
                     'com.mango.touchColor.tests.paletteFixtures'], 60)]
        require((arguments, seconds) in allowed, 'Unexpected fixture evidence command')
        self.require_identity()
        self.fixture_observation = {'argv': arguments, 'exit_code': None,
            'host_cleanup_confirmed': None, 'stderr_complete': False}
        try:
            raw = self.command(arguments, seconds)
            self.last_fixture_operation = {key: self.fixture_observation[key] for key in
                ('argv', 'exit_code', 'host_cleanup_confirmed', 'started_monotonic',
                 'returned_monotonic', 'deadline_monotonic')}
            return raw
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


def fixture_seed(family, started=STARTED, *, clock=time.monotonic):
    warmup = ManagedWarmup(family, started=started, clock=clock)
    setup = load_setup(family)
    require_hosted(family, setup, clock=warmup.clock, deadline=warmup.deadline - CLEANUP)
    verify_source(warmup, setup['binding']['context'])
    selected = resource_selection(family)
    device = warmup.fixture_device(setup)
    if selected is None or selected['required']['files']:
        # Exact predecessor Files-host command families and fixture assertions.
        warmup.fixture_command(['xcrun', 'simctl', 'install', device,
                        'build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'], 90)
        warmup.fixture_command(['xcrun', 'simctl', 'launch', '--terminate-running-process', device,
                        'com.mango.touchColor.tests.paletteFixtures'], 60)
        require(warmup.remaining() >= 60 + CLEANUP, 'Full fixture container lookup and cleanup cannot fit')
        container = warmup.command(['xcrun', 'simctl', 'get_app_container', device,
                                    'com.mango.touchColor.tests.paletteFixtures', 'data'], 60).strip()
        warmup.fixture(container)
        warmup.command(['xcrun', 'simctl', 'terminate', device, 'com.mango.touchColor.tests.paletteFixtures'], 30)
    print('Optional simulator service listing diagnostic: not collected', flush=True)
    print('Optional destination enumeration diagnostic: not collected', flush=True)
    if selected is None or selected['required']['photos']:
        warmup.seed(device)
    warmup.require_identity()
    require(load_setup(family) == setup, 'Setup changed during fixture preparation')
    value = {'schema': 2, 'setup': setup, 'complete': True, 'readiness': warmup.fixture_readiness}
    if selected is not None:
        value.update(schema=3, selection=selected, resources={
            name: 'performed-success' if required else 'not-required-by-exact-selection'
            for name, required in selected['required'].items()})
    warmup.require_time()
    write_json(record_path(family, 'fixtures'), value, limit=16384)
    warmup.require_time()


def validate_fixture_readiness(value, setup):
    """Closed source-produced fixture handoff; never upgrade an old receipt."""
    binding = setup['binding']; device = binding['identity']['udid']
    require(isinstance(value, dict) and set(value) == {'schema', 'device', 'binding_sha256',
        'basis', 'completion', 'operations', 'observed_monotonic'} and
        type(value['schema']) is int and value['schema'] == 2 and value['device'] == device and
        value['binding_sha256'] == binding['receipt_sha256'], 'Foreign fixture readiness')
    observed = value['observed_monotonic']
    require(type(observed) in (int, float) and math.isfinite(observed) and observed >= 0,
            'Unknown fixture observation time')
    if value['basis'] == 'owned_booted_inventory_snapshot_only':
        require(value['completion'] is None and value['operations'] == [], 'Conflicting inventory basis')
        return
    require(value['basis'] == 'owned_bootstatus_completion_observation_only', 'Unknown fixture readiness basis')
    operations = value['operations']
    require(isinstance(operations, list) and len(operations) == 2, 'Exact boot/readiness pair required')
    previous = None
    for op, command, cap in zip(operations,
            (['xcrun', 'simctl', 'boot', device], ['xcrun', 'simctl', 'bootstatus', device, '-b']), (180, 240)):
        require(isinstance(op, dict) and set(op) == {'argv', 'exit_code', 'host_cleanup_confirmed',
            'started_monotonic', 'returned_monotonic', 'deadline_monotonic'} and op['argv'] == command and
            type(op['exit_code']) is int and op['exit_code'] == 0 and op['host_cleanup_confirmed'] is True,
            'Unknown or unsuccessful owned handoff operation')
        start, finish, deadline = (op[k] for k in ('started_monotonic', 'returned_monotonic', 'deadline_monotonic'))
        require(all(type(t) in (int, float) and math.isfinite(t) for t in (start, finish, deadline)) and
            0 <= start <= finish < deadline <= start + cap and finish <= observed and
            (previous is None or previous <= start), 'Late or contradictory handoff timing')
        previous = finish
    proof = value['completion']
    require(isinstance(proof, dict) and type(proof.get('stdout_bytes')) is int and
        0 < proof['stdout_bytes'] <= 65536 and isinstance(proof.get('stdout_sha256'), str) and
        re.fullmatch('[0-9a-f]{64}', proof['stdout_sha256']) is not None, 'Missing bounded bootstatus output identity')
    common = {'stdout_sha256', 'stdout_bytes', 'completion_kind'}
    if proof.get('completion_kind') == 'terminal_finished':
        require(set(proof) == common | {'terminal_status', 'isTerminal', 'terminal_message'} and
            type(proof['terminal_status']) is int and proof['terminal_status'] == 4294967295 and
            proof['isTerminal'] is True and proof['terminal_message'] == 'Finished', 'Invalid Finished evidence')
    else:
        require(set(proof) == common | {'completion_message'} and proof['completion_kind'] == 'already_booted_no_work' and
            proof['completion_message'] == 'Device already booted, nothing to do.', 'Unknown completion wording')


def require_fixtures(family, setup):
    value = strict_json(read_regular(record_path(family, 'fixtures'), 16384))
    selected = resource_selection(family)
    if selected is None:
        require(type(value.get('schema')) is int and value.get('schema') == 2 and
                set(value) == {'schema', 'setup', 'complete', 'readiness'} and
                value['setup'] == setup and value['complete'] is True, 'Same-device Files and Photos fixture required')
    else:
        require(setup['binding']['context'] == require_job(family),
                'Completion resources belong to another route or source')
        require(type(value.get('schema')) is int and value['schema'] == 3 and
                set(value) == {'schema', 'setup', 'complete', 'readiness', 'selection', 'resources'} and
                value['setup'] == setup and value['complete'] is True and value['selection'] == selected and
                all(type(required) is bool for required in value['selection']['required'].values()) and
                value['resources'] == {name: 'performed-success' if required else 'not-required-by-exact-selection'
                                       for name, required in selected['required'].items()},
                'Same-device resources for the exact completion selection required')
    validate_fixture_readiness(value['readiness'], setup)
    if selected is None or selected['required']['photos']:
        seed = strict_json(read_regular(Path('build') / (family + '-fixture-seeded'), 8192))
        require(seed == setup['binding']['identity'], 'Photo seed identity differs')


def test_argv(family, suite, device):
    require(suite in STEPS, 'Unknown canonical suite')
    target = suite
    if suite == 'TouchColorUITests':
        target += '/TouchColorIPadUITests' if family.startswith('iPad') else '/TouchColorUITests'
    elif suite == 'AccessibilityAudits':
        target = 'TouchColorUITests/TouchColorAccessibilityUITests'
    selected = selection(family, suite)
    selectors = selected['cases'] if selected else [target]
    return ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor', '-configuration', 'Debug',
            '-destination', 'platform=iOS Simulator,id=' + device, '-derivedDataPath', 'build/simulator',
            '-resultBundlePath', 'build/' + family + '-' + suite + '.xcresult', '-parallel-testing-enabled', 'NO',
            '-collect-test-diagnostics', 'never', '-test-timeouts-enabled', 'YES',
            '-default-test-execution-time-allowance', '180', '-maximum-test-execution-time-allowance', '240',
            *('-only-testing:' + case for case in selectors), 'test-without-building']


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
    count = STEPS[suite][2] if suite != 'TouchColorUITests' else (16 if family.startswith('iPad') else 17)
    selected = selection(family, suite)
    if selected: count = len(selected['cases'])
    require(value['totalTestCount'] == count and
            value['passedTests'] + value['failedTests'] + value['skippedTests'] == count and
            value['expectedFailures'] == 0, 'Incomplete or changed test inventory')
    # Staged feature-absence/import coverage replaces the former capability skip.
    require(value['skippedTests'] == 0, 'Unexpected skipped tests')
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
    if selected:
        require(type(code) is int and code == (0 if passed else 65), 'Unknown selected XCTest exit')
    require(value.get('result') == ('Passed' if passed else 'Failed') and (code == 0 if passed else code != 0),
            'Command and full-target result contradict')
    return {**{k: value[k] for k in fields}, 'result': value['result'], 'qualified': passed,
            'device': identity['udid'], 'startTime': value['startTime'], 'finishTime': value['finishTime']}


def run_suite(family, suite, *, started=STARTED, clock=time.monotonic, wall=time.time,
              runner=invoke, reader=capture, products=product_identity):
    require(suite in STEPS, 'Unknown canonical test target')
    selected = selection(family, suite)
    seconds, grant, _ = STEPS[suite]
    mini_hosted = family == 'iPadMini' and suite == 'TouchColorTests'
    if mini_hosted: seconds, grant = 960, 800
    deadline = started + seconds
    warmup = ManagedWarmup(family, started=started, clock=clock, seconds=seconds)
    setup = load_setup(family)
    verify_source(warmup, setup['binding']['context'])
    if suite != 'TouchColorTests':
        require_hosted(family, setup, clock=clock, deadline=deadline - CLEANUP); require_fixtures(family, setup)
    path = record_path(family, suite)
    result_path = Path('build') / (family + '-' + suite + '.xcresult')
    require(not path.exists() and not path.is_symlink() and not result_path.exists() and not result_path.is_symlink(),
            'No repeated suite or reused result bundle')
    record = {'schema': 3 if selected else 1, 'suite': suite, 'setup': setup, 'qualified': False,
              'command': {'status': 'not_started'}, 'summary': {'status': 'not_started'}}
    if selected:
        record.update(selection=selected, summary_qualification_only=True,
                      case_identity_basis='fixed_executed_argv_and_complete_summary',
                      per_case_log_reconciliation='pending_external_review',
                      timing={'phase_started_monotonic': started, 'phase_deadline_monotonic': deadline})
    def persist(): write_json(path, record, limit=32768)
    try:
        require(clock() + grant + 2 * CLEANUP + SUMMARY < deadline, 'Full XCTest and evidence tail cannot fit')
        with warmup.pending.open('x') as marker:
            marker.write('Managed XCTest has no confirmed timely completion.\n'); marker.flush(); os.fsync(marker.fileno())
        persist()
        admitted = clock()
        require(admitted + grant + 2 * CLEANUP + SUMMARY < deadline, 'Entry persistence exhausted test admission')
        began = wall(); command_origin = admitted if mini_hosted else clock()
        command_deadline = command_origin + grant
        if selected:
            record['timing'].update(admitted_monotonic=admitted, command_origin_monotonic=command_origin,
                                    command_wall_started=began)
        if mini_hosted:
            # Both limits use the same instant; deadline subtraction loses bits.
            benchmark = {'admitted_monotonic': admitted, 'deadline_monotonic': admitted + 500,
                         'completed_before_deadline': None, 'status': 'unknown'}
            record['command']['prior_500_benchmark'] = benchmark
        record['command'] = runner(test_argv(family, suite, setup['binding']['identity']['udid']), command_deadline)
        finished = wall()
        if selected: record['timing']['command_wall_finished'] = finished
        if mini_hosted:
            observed = record['command'].get('finished_monotonic')
            if (record['command'].get('status') == 'timely_exit' and
                    record['command'].get('host_cleanup_confirmed') is True and
                    type(observed) in (int, float) and math.isfinite(observed)):
                within = observed < benchmark['deadline_monotonic']
                benchmark.update(completed_before_deadline=within,
                    status='within_prior_limit' if within else 'prior_limit_exceeded')
            record['command']['prior_500_benchmark'] = benchmark
        persist()  # Preserve observed XCTest outcome before host-only readers.
        require(record['command'].get('status') == 'timely_exit' and
                record['command'].get('host_cleanup_confirmed') is True and clock() < command_deadline,
                'Uncertain or late XCTest; all later simulator operations blocked')
        require(read_binding(family) == setup['binding'], 'Post-test binding changed')
        record['product_inventory'] = {'status': 'not_started'}
        observed = products(clock=clock, post_test_deadline=deadline - SUMMARY - CLEANUP,
                            observation=record['product_inventory'])
        require(observed == setup['products'], 'Post-test products changed')
        summary_admitted = clock()
        require(summary_admitted + SUMMARY + CLEANUP < deadline, 'Summary and owned cleanup cannot fit')
        # The read grant is derived again after the receipt write, without reset.
        summary_started = clock()
        summary_deadline = min(summary_started + SUMMARY, deadline - CLEANUP)
        if selected:
            record['timing'].update(reader_admitted_monotonic=summary_admitted,
                                    reader_started_monotonic=summary_started, reader_deadline_monotonic=summary_deadline)
        record['summary'] = {'status': 'pending'}; persist()
        summary_entry = clock()
        available = summary_deadline - summary_entry
        require(available > 0, 'Expired summary entry')
        summary_argv = ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(result_path)]
        summary_read = {'argv': summary_argv, 'entered_monotonic': summary_entry, 'deadline_monotonic': summary_deadline}
        if selected: record['summary']['reader'] = summary_read
        result = reader(summary_argv, seconds=available, cap=1024 * 1024, cleanup_grace=10)
        if selected: summary_read['returned_monotonic'] = clock()
        record['summary'] = {'status': 'reader_returned', 'exit_code': result.returncode,
                             'host_cleanup_confirmed': True, **({'reader': summary_read} if selected else {})}
        require(clock() < summary_deadline and clock() < deadline, 'Late summary result')
        # A timely host-only nonzero result leaves qualification unavailable, but
        # does not claim that an already completed XCTest is simulator-uncertain.
        if not selected: warmup.pending.unlink()
        if selected:
            record['summary'].update(bytes=len(result.stdout), sha256=hashlib.sha256(result.stdout).hexdigest())
            persist()
            retain_selected_raw(family, suite, 'summary', result.stdout)
        require(result.returncode == 0, 'Summary reader failed')
        fields = summary_fields(result.stdout, family, suite, setup['binding']['identity'], began, finished,
                                record['command']['exit_code'])
        record['summary'] = {'status': 'complete', 'fields': fields, 'exit_code': 0,
                             'host_cleanup_confirmed': True,
                             'bytes': len(result.stdout), 'sha256': hashlib.sha256(result.stdout).hexdigest(),
                             **({'reader': summary_read} if selected else {})}
        if selected:
            require(read_binding(family) == setup['binding'], 'Post-reader binding changed')
            record['timing']['evidence_completed_monotonic'] = clock()
            persist()
            require(clock() < summary_deadline and clock() < deadline, 'Selected evidence exceeded original reader allowance')
            warmup.pending.unlink()
        record['qualified'] = fields['qualified']
        persist()
        require(clock() < deadline, 'Final receipt exceeded original step')
        return 0 if record['qualified'] else (record['command']['exit_code'] or 3)
    except BaseException as error:
        if isinstance(error, ProductInventoryError):
            record['product_inventory'] = error.observation
        if record['summary'].get('status') == 'pending':
            record['summary'].update(status='unavailable',
                                     host_cleanup_confirmed=getattr(error, 'cleanup_confirmed', None))
        record['qualified'] = False; record['error'] = str(error)[:160]
        persist()
        return 3
    finally:
        # Fixed small typed summary; raw app output already used the original stream.
        output = 'UIKIT_MANAGED_RESULT:' + json.dumps({'family': family, 'suite': suite,
              'source': setup['binding']['context'], 'command': record['command'],
              'summary': record['summary'], 'qualified': record['qualified'],
              'product_inventory': record.get('product_inventory'),
              'error': record.get('error'),
              **({'selection': selected, 'timing': record['timing'],
                  'summary_qualification_only': True, 'case_identity_basis': record['case_identity_basis'],
                  'per_case_log_reconciliation': record['per_case_log_reconciliation']} if selected else {})}, sort_keys=True)
        if selected:
            require(len(output.encode()) + 1 <= 36 * 1024, 'Selected result framing exceeds whole-run allocation')
        print(output, flush=True)


def retain_selected_raw(family, suite, kind, raw):
    require(kind == 'summary' and type(raw) is bytes and len(raw) <= 1024 * 1024, 'Invalid selected raw summary')
    path = Path('build') / (family + '-' + suite + '-selected-' + kind + '.json')
    with path.open('xb') as output:
        output.write(raw)


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
