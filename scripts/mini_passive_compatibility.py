"""One isolated compatibility measurement; never launch or continue warmup.

Run only in the dedicated source-bound GitHub-hosted disposable macOS job.
Read the installed help, then observe five seconds of one app-filtered stream.
Every observation remains raw evidence: neither a banner nor silence proves
readiness. Host cleanup cannot prove simulator-side producer completion.
Leave the simulator uncertainty latch in place; dispose of the whole VM.
Only the dedicated compatibility workflow invokes this command.
"""
import time

STARTED = time.monotonic()  # Original preparation clock includes imports.

import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import selectors
import signal
import stat
import subprocess
import sys

from atomic_json import write_json
from bounded_process import group_exists
from job_budget import enabled_budget, fail_record
from uikit_runtime_diagnostics import read_identity
from uikit_warmup import Warmup

PREPARATION_SECONDS = 600
HELP_SECONDS = 5
OBSERVATION_SECONDS = 5
CLEANUP_SECONDS = 20
MINIMUM_SECONDS = HELP_SECONDS + OBSERVATION_SECONDS + CLEANUP_SECONDS
STREAM_BYTES = 64 * 1024
STDERR_BYTES = 4 * 1024
HELP_BYTES = 8 * 1024
METADATA_BYTES = 8 * 1024
APP = 'com.mango.touchColor'
EXECUTABLE = 'TouchColor'
APP_PLIST = Path('build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app/Info.plist')


class CaptureFailed(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise CaptureFailed(reason)


def require_disposable_job():
    require(os.environ.get('GITHUB_REPOSITORY') == '100mango/ColorPicker' and
            os.environ.get('GITHUB_REF') == 'refs/heads/codex/mini-passive-compatibility' and
            os.environ.get('GITHUB_EVENT_NAME') == 'push' and
            os.environ.get('GITHUB_WORKFLOW_REF') ==
                '100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@refs/heads/codex/mini-passive-compatibility',
            'Dedicated push repository/ref/workflow identity required')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'macOS' and
            os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and
            os.environ.get('GITHUB_JOB') == 'mini-passive-compatibility',
            'Dedicated disposable GitHub-hosted macOS job required')


def setup_runner(command, *, timeout):
    # Reuse the existing finite single-command capture for setup only. It stops
    # on >64 KiB total output; no partial inventory or build is accepted.
    from palette_lifecycle_diagnostics import capture
    budget = enabled_budget()
    now = time.monotonic()
    deadline = STARTED + PREPARATION_SECONDS - CLEANUP_SECONDS
    if budget is not None:
        deadline = min(deadline, now + budget.remaining() - CLEANUP_SECONDS)
    allowance = min(timeout, deadline - now)
    require(allowance > 0, 'Original setup deadline exhausted')
    result = capture(command, seconds=allowance, cap=64 * 1024, cleanup_grace=10)
    require(time.monotonic() < deadline, 'Setup returned after original absolute deadline')
    result.stdout = result.stdout.decode('utf-8', errors='strict')
    result.stderr = result.stderr.decode('utf-8', errors='strict')
    return result


def prepare_compatibility(controller):
    """Fixed setup on the new VM, sharing STARTED and the original stop latch."""
    require_disposable_job()
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
            'Source/workflow binding unavailable')
    budget = controller.budget
    require(budget is not None and not budget.cleanup_unconfirmed and
            budget.record.get('sha') == sha and budget.record.get('run_id') == os.environ.get('GITHUB_RUN_ID') and
            budget.record.get('platform') == 'ios', 'Original source-bound iOS budget unavailable')
    require(controller.command(['git', 'rev-parse', 'HEAD'], 3, simulator=False).strip() == sha,
            'Checkout source differs')
    controller.command(['git', 'diff', '--quiet', 'HEAD', '--'], 3, simulator=False)
    toolchain = controller.command(['xcodebuild', '-version'], 5, simulator=False)
    require(toolchain.splitlines() == ['Xcode 27.0', 'Build version 27A266a'], 'Exact stable toolchain unavailable')
    controller.command(['xcodebuild', '-quiet', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor',
        '-configuration', 'Debug', '-destination', 'generic/platform=iOS Simulator',
        '-derivedDataPath', 'build/simulator', 'CODE_SIGNING_ALLOWED=NO', 'build'], 300, simulator=False)
    # No install is needed: this measurement examines the installed tool itself.
    # Existing selection writes the exact UUID/runtime binding once, before boot.
    device = controller.select()
    controller.command(['xcrun', 'simctl', 'boot', device], 180, optional=True)
    controller.command(['xcrun', 'simctl', 'bootstatus', device, '-b'], 240)
    return toolchain


class HeadTail:
    """Fixed raw-byte head/tail, streaming hash, bounded even for giant lines."""
    def __init__(self, limit):
        self.limit = limit
        self.head = bytearray()
        self.tail = bytearray()
        self.seen = self.newlines = 0
        self.digest = hashlib.sha256()

    def feed(self, data):
        self.seen += len(data)
        self.newlines += data.count(b'\n')
        self.digest.update(data)
        head_room = self.limit // 2 - len(self.head)
        take = min(head_room, len(data))
        self.head.extend(data[:take])
        tail_limit = self.limit - self.limit // 2
        rest_size = len(data) - take
        if rest_size >= tail_limit:
            self.tail[:] = data[-tail_limit:]
        else:
            self.tail.extend(data[take:])
            del self.tail[:max(0, len(self.tail) - tail_limit)]

    def data(self):
        return bytes(self.head + self.tail)

    def summary(self):
        data = self.data()
        return {'raw_bytes': self.seen, 'retained_bytes': len(data),
                'dropped_bytes': self.seen - len(data), 'truncated': self.seen > len(data),
                'raw_newlines': self.newlines,
                'dropped_newline_bytes': self.newlines - data.count(b'\n'),
                'sha256_all_observed': self.digest.hexdigest(),
                'sha256_retained': hashlib.sha256(data).hexdigest(),
                'format': 'raw bytes; head then tail; discontinuity when truncated'}


def _bounded_plist():
    # Reject links in every path component and nonregular/hardlinked final files.
    for path in (APP_PLIST, *APP_PLIST.parents):
        require(not path.is_symlink(), 'Linked app path')
    descriptor = os.open(APP_PLIST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                0 < before.st_size <= 65536, 'Unsafe app plist')
        raw = os.read(descriptor, 65537)
        after = os.fstat(descriptor)
        require(len(raw) == before.st_size and all(getattr(before, key) == getattr(after, key)
            for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'Changed app plist')
    finally:
        os.close(descriptor)
    value = plistlib.loads(raw)
    require(type(value) is dict and value.get('CFBundleIdentifier') == APP and
            value.get('CFBundleExecutable') == EXECUTABLE, 'Wrong built app')
    return {'identifier': APP, 'executable': EXECUTABLE, 'plist_sha256': hashlib.sha256(raw).hexdigest()}


class CompatibilityCapture:
    """One owned marker, bounded sequential help/reader, no launcher API."""
    def __init__(self, warmup, *, preparation_started):
        self.warmup, self.clock = warmup, warmup.clock
        self.processes = {}
        self.cancelled = None
        self.pipe_failures = set()
        self.selector = selectors.DefaultSelector()
        self.buffers = {'stream': HeadTail(STREAM_BYTES), 'collector_stderr': HeadTail(STDERR_BYTES),
                        'help': HeadTail(HELP_BYTES)}
        self.receipt = {'schema': 1, 'purpose': 'isolated-compatibility-only', 'status': 'not_started',
            'diagnostic_complete': False, 'warmup_admitted': False, 'app_launch_attempted': False,
            'readiness': 'unqualified', 'reader_completion': 'unconfirmed',
            'simulator_command_completion': 'unconfirmed', 'vm_disposal_required': True,
            'help': 'not_started', 'preparation_started': preparation_started,
            'preparation_deadline': warmup.deadline, 'preparation_seconds': 600,
            'help_seconds': 5, 'observation_seconds': 5, 'shared_cleanup_seconds': 20,
            'events': {}, 'processes': {}, 'output_observed_at': {}, 'cleanup_discarded_bytes': {}}
        self.folder = Path('build/iPadMini-passive-compatibility')

    def _event(self, name):
        self.receipt['events'][name] = {'monotonic': self.clock(), 'epoch': time.time()}

    def _check(self, deadline):
        require(self.cancelled is None, 'cancelled')
        require(self.clock() < deadline and self.warmup.remaining() > CLEANUP_SECONDS,
                'absolute-deadline')

    def _persist(self):
        self.receipt['outputs'] = {key: value.summary() for key, value in self.buffers.items()}
        write_json(self.folder / 'receipt.json', self.receipt, limit=METADATA_BYTES)

    def _binding(self):
        require(self.warmup.family == 'iPadMini', 'Mini only')
        started = self.receipt['preparation_started']
        require(type(started) in (int, float) and math.isfinite(started) and
                math.isfinite(self.warmup.deadline) and started <= self.clock() and
                self.warmup.deadline - started == PREPARATION_SECONDS, 'Original 600-second clock required')
        # This is a fixed isolated job, not an opt-in on the existing warmup job.
        require_disposable_job()
        self.identity = read_identity('iPadMini')
        sha = os.environ.get('GITHUB_SHA', '')
        run, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
        require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
                'Source/workflow binding unavailable')
        require(all(re.fullmatch('[1-9][0-9]{0,19}', part) for part in (run, attempt)), 'Run binding unavailable')
        budget = self.warmup.budget
        require(budget is not None and not budget.cleanup_unconfirmed and budget.record.get('sha') == sha and
                budget.record.get('run_id') == run and budget.record.get('platform') == 'ios',
                'Original source-bound iOS budget unavailable')
        self.receipt.update({'source_sha': sha, 'workflow_sha': sha, 'run_id': run,
                             'run_attempt': attempt, 'device': self.identity, 'app': _bounded_plist()})
        device = self.identity['udid']
        self.collector = ['xcrun', 'simctl', 'spawn', device, 'log', 'stream',
                          '--info', '--debug', '--predicate', 'process == "TouchColor"']
        self.help = ['xcrun', 'simctl', 'spawn', device, 'log', 'help', 'stream']
        self.receipt.update({'collector_argv': self.collector, 'help_argv': self.help})

    def _same_binding(self):
        require_disposable_job()
        require(read_identity('iPadMini') == self.identity, 'Device binding changed')
        require(_bounded_plist() == self.receipt['app'], 'Built app binding changed')
        require(os.environ.get('GITHUB_SHA') == self.receipt['source_sha'] and
                os.environ.get('GITHUB_WORKFLOW_SHA') == self.receipt['source_sha'] and
                os.environ.get('GITHUB_RUN_ID') == self.receipt['run_id'] and
                os.environ.get('GITHUB_RUN_ATTEMPT') == self.receipt['run_attempt'], 'Source/run binding changed')

    def _spawn(self, name, argv, deadline):
        self._check(deadline)
        self.receipt['processes'][name] = {'state': 'attempted', 'argv': argv}
        self._event(name + '_attempt')
        self._persist()
        self._check(deadline)
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.processes[name] = process
        self.receipt['processes'][name].update({'state': 'owned', 'pid': process.pid, 'pgid': process.pid})
        self._event(name + '_owned')
        for pipe, stream in ((process.stdout, 'stream' if name == 'collector' else 'help'),
                             (process.stderr, 'collector_stderr' if name == 'collector' else 'help')):
            os.set_blocking(pipe.fileno(), False)
            self.selector.register(pipe, selectors.EVENT_READ, (name, stream))
        self._persist()
        self._check(deadline)
        return process

    def _drain(self, deadline, *, cleanup=False):
        remaining = deadline - self.clock()
        if remaining <= 0:
            return
        for key, _ in self.selector.select(min(.025, remaining)):
            if self.clock() >= deadline:
                return
            try:
                data = os.read(key.fileobj.fileno(), 4096)
            except OSError as error:
                if not cleanup:
                    raise
                self.pipe_failures.add(key.data[0])
                self.receipt['processes'][key.data[0]]['drain_error'] = type(error).__name__
                self.selector.unregister(key.fileobj)
                continue
            returned = self.clock()
            if returned >= deadline:
                # Nonblocking reads can still return late after descheduling.
                # Neither their bytes nor an EOF observed late belong to the
                # admitted window. Keep only bounded omission/timing metadata.
                late = self.receipt.setdefault('late_reads', {}).setdefault(key.data[1],
                    {'read_calls': 0, 'omitted_bytes': 0, 'omitted_newline_bytes': 0,
                     'omitted_eof_receipts': 0, 'first_returned_monotonic': returned})
                late['read_calls'] += 1
                late['omitted_bytes'] += len(data)
                late['omitted_newline_bytes'] += data.count(b'\n')
                late['omitted_eof_receipts'] += int(not data)
                late.update(last_returned_monotonic=returned, deadline=deadline,
                            phase='cleanup' if cleanup else key.data[0])
                self.receipt['status'] = 'failed_or_incomplete'
                self.receipt.setdefault('failure', 'Pipe read returned after its absolute deadline')
                if cleanup:
                    counts = self.receipt['cleanup_discarded_bytes']
                    counts[key.data[1]] = counts.get(key.data[1], 0) + len(data)
                    # Preserve the original TERM/KILL deadlines and continue
                    # stopping owned groups; no new drain allowance is created.
                    return
                raise CaptureFailed('Pipe read returned after its absolute deadline')
            if data and cleanup:
                counts = self.receipt['cleanup_discarded_bytes']
                counts[key.data[1]] = counts.get(key.data[1], 0) + len(data)
                continue
            if data:
                observed = {'monotonic': returned, 'epoch': time.time()}
                timing = self.receipt['output_observed_at'].setdefault(key.data[1], {'first': observed})
                timing['last'] = observed
                self.buffers[key.data[1]].feed(data)
            else:
                self.selector.unregister(key.fileobj)
        if not cleanup and self.cancelled is not None:
            raise CaptureFailed('cancelled')

    def _closed(self, name):
        return not any(key.data[0] == name for key in self.selector.get_map().values())

    def _help_supported(self):
        data = self.buffers['help'].data()
        return not self.buffers['help'].summary()['truncated'] and all(
            re.search(rb'(?<![\w-])' + word + rb'(?![\w-])', data)
            for word in (b'--info', b'--debug', b'--predicate'))

    def _cleanup(self):
        started = self.clock()
        deadline = min(started + CLEANUP_SECONDS, self.warmup.deadline,
                       started + self.warmup.remaining())
        self.receipt['cleanup_deadline'] = deadline
        self._event('cleanup_started')
        for phase, stop_signal in ((10, signal.SIGTERM), (20, signal.SIGKILL)):
            phase_deadline = min(started + phase, deadline)
            for name, process in self.processes.items():
                process.poll()
                if group_exists(process.pid):
                    require(process.pid != os.getpgrp(), 'Refusing caller group')
                    try:
                        os.killpg(process.pid, stop_signal)
                    except ProcessLookupError:
                        pass
                    except OSError as error:
                        self.receipt['processes'][name]['signal_error'] = type(error).__name__
            while self.clock() < phase_deadline:
                gone = all(process.poll() is not None and not group_exists(process.pid)
                           for process in self.processes.values())
                if gone and not self.selector.get_map():
                    break
                self._drain(phase_deadline, cleanup=True)
                if not self.selector.get_map() and not gone:
                    self.warmup.sleep(min(.025, max(0, phase_deadline - self.clock())))
            if all(process.poll() is not None and not group_exists(process.pid)
                   for process in self.processes.values()) and not self.selector.get_map():
                break
        confirmations = []
        for name, process in self.processes.items():
            confirmed = (process.poll() is not None and not group_exists(process.pid) and
                         self._closed(name) and name not in self.pipe_failures)
            confirmations.append(confirmed)
            self.receipt['processes'][name].update({'exit': process.poll(), 'host_cleanup_confirmed': confirmed})
        self.receipt['host_cleanup_confirmed'] = all(confirmations)
        self._event('cleanup_finished')

    def run(self):
        previous = {}
        marker_owned = folder_created = False
        failure = None
        def interrupted(signum, frame):
            if self.cancelled is None:
                self.cancelled = signum
        try:
            self._binding()
            require(not self.folder.exists() and not self.folder.is_symlink(), 'Prior compatibility evidence exists')
            self.folder.mkdir()
            folder_created = True
            require(self.warmup.remaining() >= MINIMUM_SECONDS, 'Insufficient original 30-second remainder')
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, interrupted)
            # Never remove this marker, including after a timely host-only exit.
            with self.warmup.pending.open('x') as marker:
                marker_owned = True
                marker.write('Mini compatibility reader completion unconfirmed. No later simulator command; dispose VM.\n')
                marker.flush()
                os.fsync(marker.fileno())
            self.receipt['uncertainty_marker'] = str(self.warmup.pending)
            self._event('ownership_acquired')
            self._persist()
            require(self.warmup.remaining() >= MINIMUM_SECONDS, 'Insufficient original 30-second remainder')
            self.warmup.budget.admit('Mini compatibility help', HELP_SECONDS, minimum=HELP_SECONDS,
                                    cleanup=OBSERVATION_SECONDS + CLEANUP_SECONDS)
            help_deadline = self.clock() + HELP_SECONDS
            self.receipt['help'] = 'attempted'
            helper = self._spawn('help', self.help, help_deadline)
            while helper.poll() is None or not self._closed('help'):
                self._check(help_deadline)
                self._drain(help_deadline)
            self._check(help_deadline)
            require(helper.returncode == 0 and not group_exists(helper.pid), 'Help completion uncertain')
            require(self._help_supported(), 'Unsupported installed help')
            self.receipt['help'] = 'supported-options-only'
            require(self.warmup.remaining() >= OBSERVATION_SECONDS + CLEANUP_SECONDS,
                    'Insufficient original observation remainder')
            self._same_binding()
            self.warmup.budget.admit('Mini compatibility stream', OBSERVATION_SECONDS,
                                    minimum=OBSERVATION_SECONDS, cleanup=CLEANUP_SECONDS)
            self._event('observation_started')
            observation_deadline = self.clock() + OBSERVATION_SECONDS
            self.receipt['observation_deadline'] = observation_deadline
            reader = self._spawn('collector', self.collector, observation_deadline)
            while self.clock() < observation_deadline:
                require(self.cancelled is None, 'cancelled')
                self._drain(observation_deadline)
                if reader.poll() is not None:
                    # Preserve a promptly exiting tool's bounded error bytes
                    # inside the same observation window, never a new tail.
                    while not self._closed('collector') and self.clock() < observation_deadline:
                        self._drain(observation_deadline)
                    raise CaptureFailed('Collector exited during observation')
            self.receipt['status'] = 'bounded_observation_finished'
            self._event('observation_finished')
            # No readiness parsing, app launch, device query or retry follows.
        except BaseException as error:
            failure = error
            self.receipt['status'] = 'failed_or_incomplete'
            self.receipt['failure'] = type(error).__name__ + ': ' + str(error)[:300]
        finally:
            try:
                if marker_owned:
                    self._cleanup()
                    self.receipt['cancelled_signal'] = self.cancelled
                    if self.cancelled is not None:
                        self.receipt['status'] = 'failed_or_incomplete'
                        if failure is None: failure = CaptureFailed('cancelled during cleanup')
                    for name, buffer in self.buffers.items():
                        with (self.folder / (name + '.bin')).open('xb') as output:
                            output.write(buffer.data())
                    self._persist()
                    if self.receipt.get('late_reads') and failure is None:
                        failure = CaptureFailed('Pipe read returned after its absolute deadline')
                    if self.cancelled is not None and failure is None:
                        self.receipt['cancelled_signal'] = self.cancelled
                        self.receipt['status'] = 'failed_or_incomplete'
                        self._persist()
                        failure = CaptureFailed('cancelled during persistence')
                    if not self.receipt['host_cleanup_confirmed'] and failure is None:
                        failure = CaptureFailed('Owned host reader exit unconfirmed; dispose VM')
                    if self.clock() >= self.receipt['cleanup_deadline'] and failure is None:
                        self.receipt['status'] = 'failed_or_incomplete'
                        self.receipt['failure'] = 'Cleanup/persistence exceeded shared deadline'
                        self._persist()
                        failure = CaptureFailed(self.receipt['failure'])
                elif folder_created:
                    self._persist()
            finally:
                self.selector.close()
                for process in self.processes.values():
                    process.stdout.close()
                    process.stderr.close()
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
        if failure is not None:
            raise failure
        return self.receipt


def main():
    controller = None
    try:
        require(sys.argv[1:] == ['compatibility-only'], 'Only compatibility-only is supported')
        controller = Warmup('iPadMini', started=STARTED, budget=enabled_budget(), runner=setup_runner)
        toolchain = prepare_compatibility(controller)
        print('MINI_PASSIVE_COMPATIBILITY_TOOLCHAIN: ' + toolchain.replace('\n', '; ').strip(), flush=True)
        receipt = CompatibilityCapture(controller, preparation_started=STARTED).run()
        print('MINI_PASSIVE_COMPATIBILITY: ' + receipt['status'] +
              '; readiness=unqualified; reader_completion=unconfirmed; dispose_vm=true', flush=True)
    except BaseException as error:
        print('MINI_PASSIVE_COMPATIBILITY: ' + type(error).__name__ + ': ' + str(error)[:300],
              file=sys.stderr, flush=True)
    finally:
        if controller is not None and controller.pending.exists():
            fail_record('Compatibility-only measurement; simulator reader completion unconfirmed; dispose VM',
                        cleanup_unconfirmed=True)
    # Deliberately never signals warmup success, even when evidence was captured.
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
