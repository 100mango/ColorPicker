"""One unchanged Mini XCTest case against functional build-for-testing products.

Always diagnostic-only: the disposable VM ends after host-only evidence. No
standalone launch, Photos seed, fixture service, retry, warmup or qualification.
"""
import time
STARTED = time.monotonic()  # Imports and setup consume the original work clock.
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys

from atomic_json import write_json
from bounded_process import group_exists, stop_group
from job_budget import enabled_budget, fail_record
from mini_passive_compatibility import HeadTail
from mini_passive_launch import product_identity
from palette_lifecycle_diagnostics import capture, CaptureStopped, strict_json, require
from uikit_runtime_diagnostics import read_identity
from uikit_warmup import Warmup

REF = 'refs/heads/codex/mini-direct-xctest'
WORKFLOW = '100mango/ColorPicker/.github/workflows/mini-direct-xctest.yml@' + REF
CASE = 'TouchColorUITests/TouchColorIPadUITests/testPalettePasteReviewAcceptAndRelaunch'
CASE_LABEL = '-[TouchColorIPadUITests testPalettePasteReviewAcceptAndRelaunch]'
BUILD = ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor',
         '-configuration', 'Debug', '-destination', 'generic/platform=iOS Simulator',
         '-derivedDataPath', 'build/simulator', 'build-for-testing']
PREPARATION_SECONDS, TEST_SECONDS, CLEANUP_SECONDS = 600, 300, 20
ROOT = Path('build/iPadMini-direct-xctest')
STOP = Path('build/iPadMini-direct-xctest-stop')
PENDING = Path('build/iPadMini-runtime-command-uncertain')
RESULT = Path('build/iPadMini-direct-xctest.xcresult')


def require_job():
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': REF,
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': WORKFLOW,
                'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS',
                'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_JOB': 'mini-direct-xctest'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'Dedicated disposable push job required')
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
            'Exact workflow/source binding required')
    require(all(re.fullmatch('[1-9][0-9]{0,19}', os.environ.get(k, ''))
                for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')), 'Exact run identity required')
    return sha


def read_file(path, cap):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Linked file path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                0 <= before.st_size <= cap, 'Unsafe or unbounded file')
        raw = bytearray()
        while len(raw) <= cap:
            part = os.read(fd, min(65536, cap + 1 - len(raw)))
            if not part: break
            raw.extend(part)
        after = os.fstat(fd)
        require(len(raw) == before.st_size and all(getattr(before, k) == getattr(after, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')),
                'File changed during bounded read')
        return bytes(raw)
    finally:
        os.close(fd)


def products(clock=time.monotonic):
    """Bind the app plus the complete local test-product tree, without a rebuild."""
    root = Path('build/simulator/Build/Products')
    require(root.is_dir() and not root.is_symlink(), 'Missing test products')
    runs = list(root.glob('*.xctestrun'))
    require(len(runs) == 1, 'Exactly one fresh build-for-testing configuration required')
    require((root / 'Debug-iphonesimulator/TouchColorUITests-Runner.app').is_dir(), 'Missing UI runner')
    start = clock(); digest = hashlib.sha256(); count = size = 0
    # Match the existing bounded local-product recipe; no code-signing override.
    for parent, directories, files in os.walk(root, followlinks=False):
        require(clock() - start < 10, 'Product fingerprint time bound')
        require(not any((Path(parent) / p).is_symlink() for p in directories), 'Linked product directory')
        require(len(directories) + len(files) <= 8192, 'Product directory entry bound')
        directories.sort()
        for name in sorted(files):
            path = Path(parent) / name
            raw = read_file(path, 128 * 1024 * 1024)
            count += 1; size += len(raw)
            require(count <= 8192 and size <= 1024**3 and clock() - start < 10, 'Product inventory bound')
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(str(len(raw)).encode() + b'\0' + raw)
    return {'app': product_identity(), 'tree_sha256': digest.hexdigest(), 'files': count,
            'bytes': size, 'xctestrun': runs[0].name}


def test_argv(device):
    return ['xcodebuild', '-project', 'TouchColor.xcodeproj', '-scheme', 'TouchColor',
            '-configuration', 'Debug', '-destination', 'platform=iOS Simulator,id=' + device,
            '-derivedDataPath', 'build/simulator', '-resultBundlePath', str(RESULT),
            '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
            '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '180',
            '-maximum-test-execution-time-allowance', '240', '-only-testing:' + CASE,
            'test-without-building']


class CaseObservation:
    """Observe exact console lifecycle only; command exit is never case success."""
    def __init__(self):
        self.partial = bytearray(); self.oversize = False
        self.started = self.ended = 0; self.outcome = None; self.conflict = False

    def feed(self, data):
        for piece in data.splitlines(keepends=True):
            if not self.oversize:
                self.partial.extend(piece)
                if len(self.partial) > 8192:
                    self.partial.clear(); self.oversize = True
            if piece.endswith(b'\n'):
                if not self.oversize:
                    self.line(self.partial.decode('utf-8', errors='replace').strip())
                self.partial.clear(); self.oversize = False

    def line(self, line):
        match = re.search(r"Test Case '([^']+)' (started\.|(passed|failed|skipped) \([0-9.]+ seconds\)\.)$", line)
        if not match: return
        if match[1] != CASE_LABEL:
            self.conflict = True; return
        if match[2] == 'started.':
            self.started += 1
            if self.started != 1 or self.ended: self.conflict = True
        else:
            self.ended += 1; self.outcome = match[3]
            if self.started != 1 or self.ended != 1: self.conflict = True

    def result(self):
        return {'source': 'exact_xctest_console_lines', 'started': self.started,
                'ended': self.ended, 'outcome': self.outcome,
                'status': 'conflicting' if self.conflict else 'completed' if self.ended == 1
                else 'started_without_end' if self.started else 'unobserved',
                'partial_line_omitted': bool(self.partial) or self.oversize}


def observe(command, seconds, *, work_deadline=None, clock=time.monotonic,
            popen=subprocess.Popen, stopper=stop_group):
    """One owned command, capped live evidence and the existing two 10s cleanup phases."""
    began = clock(); deadline = began + seconds
    value = {'argv': command, 'allowance_seconds': seconds, 'attempted': False, 'owned': False,
             'observed_command_exit': None, 'final_host_exit': None,
             'host_cleanup_confirmed': None, 'simulator_completion': 'unconfirmed',
             'status': 'not_started', 'started_monotonic': began}
    buffers = {'stdout': HeadTail(65536), 'stderr': HeadTail(16384)}
    cases = CaseObservation(); selector = selectors.DefaultSelector()
    process = None; cancelled = [None]; previous = {}
    def interrupt(signum, frame):
        if cancelled[0] is None: cancelled[0] = signum
    try:
        require(work_deadline is None or deadline <= work_deadline, 'full_command_window_unavailable')
        for signum in (signal.SIGTERM, signal.SIGINT): previous[signum] = signal.signal(signum, interrupt)
        value['attempted'] = True
        process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        value.update(owned=True, pid=process.pid)
        for name in buffers:
            pipe = getattr(process, name); os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            require(cancelled[0] is None, 'interrupted')
            remaining = deadline - clock(); require(remaining > 0, 'command_deadline')
            for key, _ in selector.select(min(remaining, .05)):
                data = os.read(key.fileobj.fileno(), 4096)
                if not data: selector.unregister(key.fileobj); continue
                buffers[key.data].feed(data)
                if key.data == 'stdout': cases.feed(data)
                require(sum(b.seen for b in buffers.values()) <= 1_000_000, 'output_limit')
        require(cancelled[0] is None and clock() < deadline, 'interrupted_or_late_exit')
        value['observed_command_exit'] = process.returncode
        require(not group_exists(process.pid), 'owned_descendant_unconfirmed')
        value.update(status='command_exit_observed', host_cleanup_confirmed=True,
                     simulator_completion='command_returned_only')
    except BaseException as error:
        value.update(status='failed_or_incomplete', reason=str(error)[:160])
        if process is not None:
            try:
                value['host_cleanup_confirmed'] = stopper(process, grace=CLEANUP_SECONDS / 2)
            except BaseException as cleanup_error:
                value.update(host_cleanup_confirmed=False, cleanup_error=type(cleanup_error).__name__)
        elif not value['attempted']:
            value['host_cleanup_confirmed'] = True
        # An exception before ownership assignment cannot establish cleanup.
    finally:
        selector.close()
        if process is not None:
            value['final_host_exit'] = process.poll()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None: pipe.close()
        for signum, handler in previous.items(): signal.signal(signum, handler)
    if cancelled[0] is not None:
        value.update(status='failed_or_incomplete', reason='interrupted', signal=cancelled[0],
                     simulator_completion='unconfirmed')
    value.update(elapsed_seconds=round(clock() - began, 3), case=cases.result(),
                 output={k: b.summary() for k, b in buffers.items()})
    return value, {k: bytes(b.head + b.tail) for k, b in buffers.items()}


class Diagnostic:
    def __init__(self):
        self.sha = require_job(); self.budget = enabled_budget()
        b = self.budget
        require(b is not None and b.phase == 'work' and not b.cleanup_unconfirmed and
                b.record.get('sha') == self.sha and b.record.get('run_id') == os.environ['GITHUB_RUN_ID'] and
                b.record.get('platform') == 'ios' and b.record.get('lane') == 'mini-direct-xctest' and
                b.record.get('minutes') == 20, 'Original source-bound 20-minute budget required')
        require(not STOP.exists() and not STOP.is_symlink() and not ROOT.exists() and
                not RESULT.exists() and not RESULT.is_symlink(), 'Diagnostic cannot be retried')
        self.report = {'schema': 1, 'purpose': 'single_existing_mini_case_diagnostic',
                       'sha': self.sha, 'workflow_sha': self.sha, 'run_id': os.environ['GITHUB_RUN_ID'],
                       'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'case': CASE,
                       'build_argv': BUILD, 'warmup_accepted': False, 'full_row_accepted': False,
                       'release_accepted': False, 'vm_disposal_required': True,
                       'summary': {'status': 'unavailable_not_requested'}, 'status': 'not_started'}
        self.warmup = Warmup('iPadMini', started=STARTED, budget=b, runner=self.setup_runner)
        ROOT.mkdir(exist_ok=False)
        with STOP.open('x') as output: output.write('Permanent diagnostic stop. Never resume this VM.\n')

    def persist(self):
        self.report['budget'] = self.budget.snapshot()
        write_json(ROOT / 'receipt.json', self.report, limit=32768)

    def setup_runner(self, command, *, timeout):
        # Only setup uses this predecessor capture; exact command receipts survive
        # failures without ever implying simulator-daemon completion.
        began = time.monotonic()
        deadline = min(began + timeout, self.warmup.deadline - CLEANUP_SECONDS,
                       self.budget.hard_deadline - sum(self.budget.record['reserves'].values()) - CLEANUP_SECONDS)
        event = {'argv': command, 'allowance_seconds': timeout, 'exit': None,
                 'host_cleanup_confirmed': None, 'absolute_deadline': deadline}
        self.report.setdefault('preparation_commands', []).append(event)
        try:
            require(time.monotonic() < deadline, 'setup_window_expired_before_persistence')
            self.persist()
            require(time.monotonic() < deadline, 'setup_window_expired_after_persistence')
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'setup_window_expired_before_capture')
            event['capture_seconds'] = remaining
            value = capture(command, seconds=remaining, cap=1_000_000, cleanup_grace=10)
            event.update(exit=value.returncode, host_cleanup_confirmed=True)
            require(time.monotonic() < deadline, 'setup_capture_returned_after_deadline')
            if command == BUILD:
                for name in ('stdout', 'stderr'):
                    buffer = HeadTail(32768); buffer.feed(getattr(value, name))
                    (ROOT / ('build-' + name + '.bin')).write_bytes(buffer.data())
                    event[name] = buffer.summary()
        except BaseException as error:
            event.update(reason=str(error)[:160], host_cleanup_confirmed=getattr(
                error, 'cleanup_confirmed', event['host_cleanup_confirmed']))
            raise
        finally:
            event['elapsed_seconds'] = round(time.monotonic() - began, 3)
        value.stdout = value.stdout.decode('utf-8', errors='strict')
        value.stderr = value.stderr.decode('utf-8', errors='replace')
        return value

    def prepare(self):
        w = self.warmup
        require(w.command(['git', 'rev-parse', 'HEAD'], 3, simulator=False).strip() == self.sha, 'Wrong checkout')
        w.command(['git', 'diff', '--quiet', 'HEAD', '--'], 3, simulator=False)
        toolchain = w.command(['xcodebuild', '-version'], 5, simulator=False)
        require(toolchain.splitlines() == ['Xcode 27.0', 'Build version 27A266a'], 'Wrong toolchain')
        self.report['toolchain'] = toolchain
        require(not Path('build/simulator').exists() and not Path('build/simulator').is_symlink(), 'Stale products')
        w.command(BUILD, 300, simulator=False)
        self.report['products'] = products()
        device = w.select()  # Original template Mini, on this fresh disposable VM.
        self.identity = read_identity('iPadMini')
        require(self.identity['udid'] == device, 'Selected ownership changed')
        self.report['device'] = self.identity
        w.command(['xcrun', 'simctl', 'boot', device], 180, optional=True)
        w.command(['xcrun', 'simctl', 'bootstatus', device, '-b'], 240)
        w.command(['xcrun', 'simctl', 'install', device,
                   'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app'], 300)
        require(w.command(['git', 'rev-parse', 'HEAD'], 3, simulator=False).strip() == self.sha,
                'Checkout changed during build/setup')
        w.command(['git', 'diff', '--quiet', 'HEAD', '--'], 3, simulator=False)
        require(read_identity('iPadMini') == self.identity and products() == self.report['products'],
                'Installed product/device binding changed')
        w.require_time()

    def execute(self):
        require_job()
        require(read_identity('iPadMini') == self.identity, 'Owned Mini changed')
        command = test_argv(self.identity['udid'])
        self.report['test_argv'] = command
        # No partial UI window. This is the unchanged job-budget work remainder,
        # initially 720s, not a new clock after the 600s preparation ceiling.
        self.budget.admit('single direct Mini XCTest', TEST_SECONDS,
                          minimum=TEST_SECONDS, cleanup=CLEANUP_SECONDS)
        with PENDING.open('x') as output:
            output.write('Permanent diagnostic stop. XCTest may run; no later device call is permitted.\n')
        self.report['status'] = 'xctest_attempt_pending'; self.persist()
        # Persistence consumes time too; repeat admission immediately before spawn.
        self.budget.admit('single direct Mini XCTest final gate', TEST_SECONDS,
                          minimum=TEST_SECONDS, cleanup=CLEANUP_SECONDS)
        work_deadline = self.budget.hard_deadline - sum(self.budget.record['reserves'].values()) - CLEANUP_SECONDS
        value, output = observe(command, TEST_SECONDS, work_deadline=work_deadline)
        self.report['xctest'] = value
        for name, raw in output.items(): (ROOT / (name + '.bin')).write_bytes(raw)
        self.report['status'] = 'diagnostic_stopped'
        if value['host_cleanup_confirmed'] is not True:
            self.budget.latch_cleanup_failure()
        if value['status'] != 'command_exit_observed' or value['observed_command_exit'] != 0:
            fail_record('Direct Mini XCTest failed or incomplete', cleanup_unconfirmed=self.budget.cleanup_unconfirmed)
        self.persist()

    def host_summary(self):
        """Only one local result-bundle read; never query the device after XCTest."""
        test = self.report.get('xctest', {})
        if test.get('host_cleanup_confirmed') is not True or test.get('signal'):
            self.report['summary'] = {'status': 'unavailable_cleanup_or_cancellation'}; return
        if not RESULT.is_dir() or RESULT.is_symlink():
            self.report['summary'] = {'status': 'unavailable_result_bundle'}; return
        try:
            self.budget.admit('host-only XCTest summary', 3, minimum=3, cleanup=20, phase='evidence')
            value = capture(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(RESULT)],
                            seconds=3, cap=65536, cleanup_grace=10)
            require(value.returncode == 0, 'summary_command_nonzero')
            raw = strict_json(value.stdout)
            require(isinstance(raw, dict), 'summary_schema_unavailable')
            # This aggregate is independent of the exact case's console lifecycle.
            fields = {k: raw[k] for k in ('result', 'totalTestCount', 'passedTests', 'failedTests', 'skippedTests')
                      if k in raw and type(raw[k]) in (str, int) and len(str(raw[k])) <= 100}
            require(fields, 'summary_fields_unavailable')
            self.report['summary'] = {'status': 'observed_aggregate_only', 'fields': fields}
        except Exception as error:
            self.report['summary'] = {'status': 'unavailable', 'reason': str(error)[:160]}
            if getattr(error, 'cleanup_confirmed', True) is not True:
                self.budget.latch_cleanup_failure()
                fail_record('Host summary cleanup unconfirmed', phase='evidence', cleanup_unconfirmed=True)

    def run(self):
        try:
            self.prepare(); self.execute(); self.host_summary()
        except Exception as error:
            self.report.update(status='failed_or_incomplete', reason=str(error)[:240])
            if getattr(error, 'cleanup_confirmed', True) is not True: self.budget.latch_cleanup_failure()
            fail_record(error, cleanup_unconfirmed=self.budget.cleanup_unconfirmed)
        finally:
            if not PENDING.exists() and not PENDING.is_symlink():
                with PENDING.open('x') as output: output.write('Permanent diagnostic stop; VM disposal required.\n')
            self.persist()
        # A passed command/case is still only this diagnostic, never row acceptance.
        return 3


def stage():
    """Finite allowlist of existing host files only; no xcresult traversal/upload."""
    caps = {'iPadMini-direct-xctest/receipt.json': 32768,
            'iPadMini-direct-xctest/stdout.bin': 65536, 'iPadMini-direct-xctest/stderr.bin': 16384,
            'iPadMini-direct-xctest/build-stdout.bin': 32768, 'iPadMini-direct-xctest/build-stderr.bin': 32768,
            'iPadMini-direct-xctest-stop': 4096, 'iPadMini-runtime-command-uncertain': 4096,
            'iPadMini-simulator.json': 8192, 'job-budget.json': 8192,
            'job-budget-incomplete.json': 4096, 'job-budget-cleanup-unconfirmed.json': 4096}
    require(not Path('build').is_symlink(), 'Linked build root')
    target = Path('build/mini-direct-upload'); target.mkdir(exist_ok=False)
    for name, cap in caps.items():
        path = Path('build') / name
        if not path.exists() and not path.is_symlink(): continue
        (target / name.replace('/', '-')).write_bytes(read_file(path, cap))


if __name__ == '__main__':
    require(len(sys.argv) == 2 and sys.argv[1] in ('diagnose', 'stage'), 'Choose diagnose or stage')
    if sys.argv[1] == 'stage': stage()
    else: raise SystemExit(Diagnostic().run())
