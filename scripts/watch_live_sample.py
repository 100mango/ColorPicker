"""One exact-PID Watch diagnostic; host-only private libproc compatibility is gated."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from ios_watch_archive_capture import capture, CaptureStopped
from watch_xcresult_stack import (APP, SUITE, TEST, CASE, MAX_TEXT, MAX_REPORT, Budget, TOTAL_SECONDS,
    read, need, timestamp, main_thread_text, private_payload_directory, cancellation_guard, binding as completed_binding)

STATE = 'watch-live-state.json'
REPORT = 'watch-stack-diagnostic.json'
TOOLS = 'watch-live-tools'
IDENTITY = 'watch-sample-identity'
CASE_LOG = 'TouchColorWatchUITests.WatchWorkflowTests testTouchCopyEntryTouchAndCrownRemainResponsive'
QUIET_SECONDS = 5
SAMPLE_SECONDS = 1
SAMPLE_INTERVAL_MS = 5

class NativeCancelled(Exception):
    pass

class NativeSignals:
    """Record cancellation before native spawn; the owner cleans up after assignment."""
    def __init__(self):
        self.previous = {}
        self.cancelled = None
    def install(self):
        def interrupted(signum, frame):
            if self.cancelled is None: self.cancelled = signum
        for signum in (signal.SIGTERM, signal.SIGINT):
            self.previous[signum] = signal.signal(signum, interrupted)
    def check(self):
        if self.cancelled is not None: raise NativeCancelled('native observation cancelled')
    def restore(self):
        for signum, handler in self.previous.items(): signal.signal(signum, handler)

def wait_native(process, deadline, timeout, live, signals, now=time.monotonic):
    """Service one observation on the main thread without renewing native time."""
    import subprocess
    while True:
        signals.check()
        remaining = deadline - now()
        if remaining <= 0: raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            code = process.wait(timeout=min(0.25, remaining))
            signals.check()
            return code
        except subprocess.TimeoutExpired:
            signals.check()
            if now() >= deadline: raise subprocess.TimeoutExpired(process.args, timeout)
            live.service()

def observed_capture(report, runner):
    def run(command, **options):
        rows = report.setdefault('command_results', [])
        need(len(rows) < 8, 'too many live diagnostic command records')
        row = {'operation': report.get('operation'), 'state': 'starting'}
        rows.append(row)
        try:
            result = runner(command, **options)
        except CaptureStopped as error:
            row.update(state='stopped', reason=str(error), cleanup_confirmed=error.cleanup_confirmed,
                       cancelled_signal=error.cancelled_signal)
            raise
        need(isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes) and
             len(result.stdout) + len(result.stderr) <= options['cap'], 'invalid capture byte contract')
        row.update(state='completed', exit=result.returncode, stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr),
                   stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
                   stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),
                   permission_denied=bool(re.search(rb'permission denied|operation not permitted|not authorized|task_for_pid.*fail', result.stdout + result.stderr, re.I)))
        if report.get('operation') in {'sample-manual', 'container-help', 'compile-host-identity'} and result.stderr:
            row['preflight_stderr_prefix'] = clean_manual(result.stderr[:4096])
        if report.get('operation') == 'one-owned-app-sample' and result.returncode == 0:
            # sample may send progress to stderr. This single operation permits
            # bounded status only; the fresh output/header/identity/cleanup
            # gates still establish the evidence. No raw status is retained.
            status_text = result.stdout + b'\n' + result.stderr
            unsafe = re.search(rb'permission denied|operation not permitted|not authorized|authorization|task_for_pid.*fail|'
                               rb'invalid option|unknown option|unrecognized option|usage:|unsupported|not supported|\berror\b|\bfailed\b', status_text, re.I)
            need(not unsafe, 'sample reported a permission or command error')
            row['bounded_sample_status_accepted'] = bool(result.stderr)
            return subprocess.CompletedProcess(command, result.returncode, result.stdout, b'')
        return result
    return run

def clean_manual(raw):
    text = raw.decode('utf-8')
    while '\b' in text:
        changed = re.sub(r'.\x08', '', text)
        if changed == text: break
        text = changed
    return ''.join(c for c in text if c in '\n\t' or 32 <= ord(c) < 127)

def qualify_sample_manual(raw):
    text = clean_manual(raw)
    flat = ' '.join(text.lower().split())
    sections = re.search(r'\bSYNOPSIS\b(.*?)\bDESCRIPTION\b(.*)', text, re.S | re.I)
    need(sections is not None, 'sample manual synopsis/description unavailable')
    synopsis = ' '.join(sections[1].lower().split())
    need(re.search(r'\bsample\s+.*?\bpid\b.*?\bduration\b.*?\b(?:sampling)?interval\b', synopsis), 'sample numeric PID/duration/interval usage unavailable')
    need('seconds' in flat and 'milliseconds' in flat, 'sample units unavailable')
    need(re.search(r'-file\s+(?:<)?(?:file|filename|path)', synopsis), 'explicit sample output option unavailable')
    file_option = re.search(r'-file\s+[^\n]+(.*?)(?:\n\s*-\w|\n[A-Z][A-Z ]{3,}\n|\Z)', sections[2], re.S)
    need(file_option is not None and re.search(r'(?:save|write|written|output).{0,160}(?:file|report)',
         ' '.join(file_option[0].lower().split())), 'sample output-file contract unavailable')
    return text

def save(path, value):
    data = (json.dumps(value, indent=2) + '\n').encode()
    need(len(data) <= MAX_REPORT, 'live diagnostic report exceeds byte cap')
    path.write_bytes(data)

def state_paths():
    root = Path(os.environ['RUNNER_TEMP'])
    need(root.is_dir() and not root.is_symlink(), 'unsafe runner temporary directory')
    return root, root / STATE, root / 'watch-focused-evidence' / REPORT

def cleanup_tools(root):
    path = root / TOOLS
    if path.exists() or path.is_symlink():
        need(path.is_dir() and not path.is_symlink(), 'unsafe live tool directory')
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        try:
            import itertools
            entries = list(itertools.islice(path.iterdir(), 2))
            need(len(entries) <= 1 and all(item.name == IDENTITY for item in entries), 'unexpected live tool output')
            for item in entries:
                need(stat.S_ISREG(item.lstat().st_mode) and not item.is_symlink(), 'unsafe live tool output')
                item.unlink()
            path.rmdir()
        finally: signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        need(not path.exists(), 'live tool cleanup unconfirmed')

def preflight():
    root, state, published = state_paths()
    need(not state.exists(), 'live preflight already attempted')
    report = {'calls': 0, 'seconds_spent': 0, 'phase': 'preflight-started', 'attempts': 0,
              'private_host_api': 'libproc; installed SDK compatibility required; not a product dependency',
              'pid_reference_race': 'numeric PID lookup has a residual pre-check-to-sample race; mismatched post-checks are discarded'}
    clock = json.loads(read(published.parent/'report.json', MAX_REPORT))['started_monotonic']
    budget = Budget(report, clock, observed_capture(report, capture))
    folder = root / TOOLS
    try:
        need(not folder.exists() and not folder.is_symlink(), 'live tool directory already exists')
        folder.mkdir(mode=0o700)
        os.environ.update(MANPAGER='/bin/cat', PAGER='/bin/cat', MANWIDTH='100', LC_ALL='C')
        report['operation'] = 'sample-manual'
        raw = budget.run(['/usr/bin/man', '1', 'sample'], cap=16384)
        report['sample_manual'] = {'sha256': hashlib.sha256(raw).hexdigest(), 'text': clean_manual(raw)}
        qualify_sample_manual(raw)
        report['operation'] = 'container-help'
        help_raw = budget.run(['xcrun', 'simctl', 'help', 'get_app_container'], cap=8192)
        help_text = clean_manual(help_raw)
        report['container_help'] = {'sha256': hashlib.sha256(help_raw).hexdigest(), 'text': help_text}
        need(all(token in help_text for token in ('get_app_container', 'device', 'app', 'container')), 'owned app container operation unavailable')
        source = Path(__file__).with_name('watch_sample_identity.c')
        report['identity_source_sha256'] = hashlib.sha256(read(source, 32768)).hexdigest()
        report['operation'] = 'compile-host-identity'
        budget.run(['xcrun', '--sdk', 'macosx', 'clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(source), '-o', str(folder/IDENTITY)], cap=8192)
        report['identity_binary_sha256'] = hashlib.sha256(read(folder/IDENTITY, 1048576)).hexdigest()
        report.update(phase='preflight-verified', tool_cleanup_confirmed=False)
    except BaseException as error:
        report.update(phase='unavailable', error=type(error).__name__, tool_cleanup_confirmed=False)
        if type(error) is ValueError: report['reason'] = str(error)[:200]
        cleanup_tools(root)
        report['tool_cleanup_confirmed'] = True
        raise
    finally:
        budget.finish(); save(state, report); save(published, report)

class Trigger:
    """Reader-only event parsing; sampling is serviced by the owning main thread."""
    def __init__(self, now=time.monotonic, wall=time.time):
        self.now, self.wall = now, wall
        self.lock = threading.Lock()
        self.phase = 'before-case'
        self.case_started = None
        self.case_wall = None
        self.idle_started = None
        self.idle_wall = None
        self.copy_elapsed = None
        self.idle_elapsed = None
        self.claimed = False
        self.progressed = False
        self.reason = None
        self.last_elapsed = None
        self.copy_prelude = 0

    def record(self, line):
        if not isinstance(line, str) or len(line) > 4096: return
        with self.lock:
            if line.startswith('Test Case '):
                if line.rstrip() == "Test Case '-[" + CASE_LOG + "]' started." and self.phase == 'before-case':
                    self.phase = 'case'; self.case_started = self.now(); self.case_wall = self.wall()
                else:
                    self.progressed = True; self.reason = 'case-changed-or-terminal'
                return
            if self.phase == 'before-case' or self.progressed: return
            if '** TEST EXECUTE' in line or 'exceeded execution time allowance' in line or 'Restarting after' in line:
                self.progressed = True; self.reason = 'test-terminal'; return
            if line.strip() == 'WATCH_CREATE_ENTRY_RESPONSE touchFocusedCrown=true buttons=true':
                if self.phase == 'case': self.phase = 'create-proven'
                else: self.progressed = True; self.reason = 'duplicate-create-marker'
                return
            event = re.fullmatch(r'\s*t =\s*(\d+(?:\.\d+)?)s\s+(.+?)\s*\n?', line)
            if not event: return
            elapsed, message = float(event[1]), event[2]
            if not math.isfinite(elapsed) or (self.last_elapsed is not None and elapsed < self.last_elapsed):
                self.progressed = True; self.reason = 'invalid-or-regressing-case-time'; return
            self.last_elapsed = elapsed
            if self.phase == 'create-proven' and message == 'Tap "watch.edit.copy" Button':
                self.phase = 'copy-tapped'; self.copy_elapsed = elapsed; return
            if self.phase == 'copy-tapped':
                expected = ('Wait for ' + APP + ' to idle', 'Find the "watch.edit.copy" Button',
                            'Check for interrupting elements affecting "watch.edit.copy" Button', 'Synthesize event')
                if message == expected[self.copy_prelude]:
                    self.copy_prelude += 1
                    if self.copy_prelude == len(expected): self.phase = 'copy-synthesized'
                else:
                    self.progressed = True; self.reason = 'unexpected-copy-prelude'
                return
            if self.phase == 'copy-synthesized' and message == 'Wait for ' + APP + ' to idle':
                self.phase = 'copy-idle'; self.idle_started = self.now(); self.idle_wall = self.wall(); self.idle_elapsed = elapsed; return
            if self.phase == 'copy-synthesized':
                self.progressed = True; self.reason = 'unexpected-post-copy-event'; return
            if self.phase == 'copy-idle':
                self.progressed = True; self.reason = 'post-idle-activity'; return
            if self.phase in {'copy-tapped', 'copy-synthesized'} and message == 'Tap "watch.edit.copy" Button':
                self.progressed = True; self.reason = 'duplicate-copy-marker'

    def claim(self):
        with self.lock:
            if self.claimed or self.progressed or self.phase != 'copy-idle': return None
            if self.now() - self.idle_started < QUIET_SECONDS: return None
            if max(self.now() - self.case_started, self.idle_elapsed + self.now() - self.idle_started) > 120 - TOTAL_SECONDS:
                self.progressed = True; self.reason = 'insufficient-case-time'; return None
            # This records an observed idle window, not an assertion that the app is hung.
            self.claimed = True
            return {'case_started_monotonic': self.case_started, 'case_started_epoch': self.case_wall,
                    'post_copy_idle_monotonic': self.idle_started, 'post_copy_idle_epoch': self.idle_wall,
                    'copy_elapsed_seconds': self.copy_elapsed}

    def active(self):
        with self.lock: return self.claimed and not self.progressed and self.phase == 'copy-idle'

    def invalidate(self, reason):
        with self.lock:
            self.progressed = True; self.reason = reason

def verify_container(raw, device):
    path = raw.decode('utf-8').strip()
    need(len(path) < 1024 and '\n' not in path, 'invalid owned app container')
    marker = '/CoreSimulator/Devices/' + device + '/data/Containers/Bundle/Application/'
    need(path.startswith('/') and path.count('/CoreSimulator/Devices/') == 1 and marker in path,
         'app container is outside owned Watch device')
    need(re.fullmatch(r'[0-9A-Fa-f-]{36}/TouchColor\.app', path.split(marker, 1)[1]), 'unexpected owned app container shape')
    need(not any(part in {'.', '..'} for part in path.split('/')), 'app container has traversal')
    folder = Path(path)
    need(folder.is_dir() and not folder.is_symlink() and str(folder.resolve()) == path, 'unsafe app container')
    info = plistlib.loads(read(folder/'Info.plist', 65536))
    need(info.get('CFBundleIdentifier') == APP and info.get('CFBundleExecutable') == 'TouchColor', 'installed bundle identity mismatch')
    return path + '/TouchColor'

def candidate_pid(raw):
    text = raw.decode('utf-8')
    pids = set()
    for line in text.splitlines():
        if 'WATCH_EDITOR' not in line: continue
        match = re.search(r'TouchColor\[(\d+):[^\]]+\].*\[com\.mango\.touchColor\.WatchDiagnostics:editor\] WATCH_EDITOR \w+ case=' + re.escape(CASE) + r' ', line)
        need(match is not None, 'unparsed current-case process event')
        pid = int(match[1]); need(1 < pid < 4194304, 'invalid app PID')
        pids.add(pid)
    need(len(pids) == 1, 'current case has no unique app PID')
    return next(iter(pids))

def identity(raw, pid, executable, case_start, now):
    value = json.loads(raw)
    need(isinstance(value, dict) and set(value) == {'pid', 'uid', 'start_sec', 'start_usec', 'executable_path'}, 'invalid exact-PID identity record')
    need(type(value['pid']) is int and value['pid'] == pid and type(value['uid']) is int and value['uid'] == os.geteuid(), 'PID/UID identity mismatch')
    need(type(value['start_sec']) is int and type(value['start_usec']) is int and 0 <= value['start_usec'] < 1000000, 'invalid process start identity')
    started = value['start_sec'] + value['start_usec'] / 1000000
    need(case_start <= started <= now and value['executable_path'] == executable, 'process start/executable is not the current owned app')
    return value

class LiveSample:
    def __init__(self, runtime, command, device, *, now=time.monotonic, wall=time.time, runner=capture):
        self.runtime, self.command, self.device = runtime, command, dict(device)
        self.now, self.wall, self.runner = now, wall, runner
        self.trigger = Trigger(now, wall)
        self.finished = False
        self.root, self.state, self.published = state_paths()
        self.report = json.loads(read(self.state, MAX_REPORT))
        need(self.report.get('phase') == 'preflight-verified' and self.report.get('attempts') == 0, 'live preflight/one-shot unavailable')
        need(command[:2] == ['xcodebuild', 'test-without-building'] and
             command.count('-only-testing:' + SUITE + '/' + TEST) == 1 and
             sum(str(x).startswith('-only-testing:') for x in command) == 1, 'wrong selected native case')
        need(command[command.index('-destination')+1] == 'platform=watchOS Simulator,id=' + device['udid'], 'wrong native destination')
        need(command[command.index('-default-test-execution-time-allowance')+1] == '120' and
             command[command.index('-collect-test-diagnostics')+1] == 'never', 'changed native diagnostic/case allowance')
        owned = runtime.get('owned_watch_devices', [])
        need(len(owned) == 2 and sum(x.get('role') == 'watch' and x.get('udid') == device['udid'] for x in owned) == 1, 'owned Watch binding missing')
        self.started = json.loads(read(self.published.parent/'report.json', MAX_REPORT))['started_monotonic']
        self.budget = None
        self.cancel_check = lambda: None
        self.output_active = lambda: True
        self.native_active = lambda: True

    def record(self, line): self.trigger.record(line)

    def check_active(self):
        self.cancel_check()
        need(self.native_active(), 'native test process has exited')
        need(self.output_active(), 'native output reader is not active')
        need(self.trigger.active(), 'case progressed; live observation discarded')
        need(not self.runtime.get('cleanup_unconfirmed'), 'prior cleanup unconfirmed')

    def checked(self, operation, command, cap):
        self.check_active()
        self.report['operation'] = operation
        result = self.budget.run(command, cap=cap)
        self.check_active()
        return result

    def service(self):
        if self.finished: return
        origin = self.trigger.claim()
        if origin is None: return
        self.finished = True
        # Waiting for the UI marker is native-test time, not diagnostic work.
        # Carry preflight spending forward when the one live observation begins.
        self.budget = Budget(self.report, self.started, observed_capture(self.report, self.runner), self.now)
        self.report.update(attempts=1, phase='observing', origin=origin, sha=self.runtime['sha'],
                           device=self.device['udid'], case=TEST)
        raw_directory = None
        try:
            self.check_active()
            helper = self.root/TOOLS/IDENTITY
            need(hashlib.sha256(read(helper, 1048576)).hexdigest() == self.report['identity_binary_sha256'], 'host identity helper changed')
            predicate = 'subsystem == "com.mango.touchColor.WatchDiagnostics" AND eventMessage CONTAINS "case=' + CASE + ' "'
            log = self.checked('current-case-log', ['xcrun', 'simctl', 'spawn', self.device['udid'], 'log', 'show', '--last', '2m',
                                '--style', 'compact', '--predicate', predicate], 65536)
            pid = candidate_pid(log)
            container = self.checked('owned-app-container', ['xcrun', 'simctl', 'get_app_container', self.device['udid'], APP, 'app'], 8192)
            executable = verify_container(container, self.device['udid'])
            before = identity(self.checked('identity-before', [str(helper), str(pid)], 32768), pid, executable, origin['case_started_epoch'], origin['post_copy_idle_epoch'])
            self.report['identity_before'] = {key: value for key, value in before.items() if key != 'executable_path'}
            self.report['executable_path_sha256'] = hashlib.sha256(executable.encode()).hexdigest()
            sample_start = self.wall()
            with private_payload_directory(self.root) as folder:
                raw_directory = folder
                path = folder/'payload.txt'
                self.checked('one-owned-app-sample', [sys.executable, str(Path(__file__).resolve()), '--bounded-sample', str(pid), str(path)], 8192)
                need(list(folder.iterdir()) == [path], 'sample created an unexpected side file')
                raw = read(path, MAX_TEXT)
                after = identity(self.checked('identity-after', [str(helper), str(pid)], 32768), pid, executable, origin['case_started_epoch'], origin['post_copy_idle_epoch'])
                need(after == before, 'PID identity changed; sample discarded')
                sample_end = self.wall()
                bound = {'pid': pid, 'device': self.device['udid'], 'start': sample_start, 'end': sample_end}
                header_paths = re.findall(r'^[ \t]*Path:[ \t]+(.+)$', raw.decode('utf-8'), re.M)
                need(header_paths == [executable], 'sample header executable differs from verified process')
                main_headers = [line for line in raw.decode('utf-8').splitlines()
                                if re.search(r'\bThread[_ ]', line) and 'com.apple.main-thread' in line]
                need(len(main_headers) == 1, 'sample does not have exactly one main-thread section')
                frames = main_thread_text(raw, bound, sample_start)
                self.check_active()
                payload = {'main_thread': frames, 'sample_started_epoch': sample_start, 'sample_finished_epoch': sample_end,
                           'payload_bytes': len(raw), 'payload_sha256': hashlib.sha256(raw).hexdigest(),
                           'identity_after': {key: value for key, value in after.items() if key != 'executable_path'}}
            self.check_active()
            self.report.update(payload)
            self.report.update(phase='complete', evidence='owned app live main-thread sample', raw_cleanup_confirmed=True, qualified=False)
        except BaseException as error:
            self.report.update(phase='unavailable', evidence='no qualified live app stack', error=type(error).__name__)
            if type(error) is ValueError: self.report['reason'] = str(error)[:200]
            if raw_directory is not None and raw_directory.exists():
                self.report['raw_cleanup_confirmed'] = False
                self.runtime['cleanup_unconfirmed'] = True
                raise
            if isinstance(error, CaptureStopped):
                self.report['diagnostic_cleanup_confirmed'] = error.cleanup_confirmed
                if not error.cleanup_confirmed: self.runtime['cleanup_unconfirmed'] = True
                if error.cancelled_signal is not None or not error.cleanup_confirmed: raise
            if isinstance(error, (NativeCancelled, KeyboardInterrupt, SystemExit)): raise
        finally:
            self.budget.finish(); save(self.state, self.report)
            self.runtime['watch_live_sample'] = {'phase': self.report['phase'], 'attempts': self.report['attempts'],
                                                'calls': self.report['calls'], 'seconds_spent': self.report['seconds_spent']}

    def finish(self):
        if not self.finished:
            self.finished = True
            self.report.update(phase='not-sampled', evidence='no eligible idle window', trigger_reason=self.trigger.reason)
            save(self.state, self.report)

def bounded_sample(pid_text, filename):
    import resource
    need(re.fullmatch(r'[0-9]{1,7}', pid_text) and 1 < int(pid_text) < 4194304, 'invalid sample PID')
    path = Path(filename); root = Path(os.environ['RUNNER_TEMP']).resolve()
    need(path.name == 'payload.txt' and path.parent.name.startswith('watch-stack-') and
         not path.parent.is_symlink() and path.parent.parent.resolve() == root and not path.exists() and not path.is_symlink(), 'unsafe sample output')
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT, MAX_TEXT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.environ['TMPDIR'] = str(path.parent)
    os.chdir(path.parent)
    os.execv('/usr/bin/sample', ['/usr/bin/sample', pid_text, str(SAMPLE_SECONDS), str(SAMPLE_INTERVAL_MS), '-file', str(path)])

def finalize():
    root, state, published = state_paths()
    report = {'phase': 'unavailable', 'evidence': 'live state is unavailable'}
    budget = None
    try:
        report = json.loads(read(state, MAX_REPORT))
        need(isinstance(report, dict), 'invalid live state')
        clock = json.loads(read(published.parent/'report.json', MAX_REPORT))['started_monotonic']
        budget = Budget(report, clock)
        before = json.loads(read(published.parent/'source-before.json', 32768))
        after = json.loads(read(published.parent/'source-after.json', 32768))
        runtime = json.loads(read('build/watch-runtime/runtime.json', 262144))
        need(before == after and before.get('sha') == os.environ['GITHUB_SHA'] and before.get('clean') is True, 'live source readback mismatch')
        need(runtime.get('sha') == before['sha'] and runtime.get('active_command') is None and not runtime.get('cleanup_unconfirmed'), 'native cleanup unresolved')
        if 'main_thread' in report:
            completed = completed_binding(runtime, before, after, os.environ['GITHUB_SHA'])
            need(completed['pid'] == report['identity_before']['pid'] and completed['device'] == report['device'],
                 'completed native case differs from sampled process')
            need(completed['start'] <= report['sample_started_epoch'] <= report['sample_finished_epoch'] <= completed['end'],
                 'sample time is outside completed native command')
            stages = [row for row in runtime.get('stages', []) if '-only-testing:' + SUITE + '/' + TEST in row.get('command', [])]
            need(len(stages) == 1 and stages[0].get('exit') == 65 and stages[0].get('raw_exit') == 65 and
                 stages[0].get('timed_out') is False and stages[0].get('process_group_gone') is True and
                 stages[0].get('capture_reader_finished') is True, 'live sample native completion is unqualified')
            need(runtime.get('result') == 'failed' and report.get('sha') == before['sha'] and report.get('raw_cleanup_confirmed') is True,
                 'live sample lacks failed-case/source/raw cleanup qualification')
    except Exception as error:
        if not isinstance(report, dict): report = {}
        for field in ('main_thread', 'payload_bytes', 'payload_sha256'): report.pop(field, None)
        report.update(phase='unavailable', evidence='no source-bound live sample', finalization_error=type(error).__name__)
    finally:
        cleanup_tools(root)
        report['tool_cleanup_confirmed'] = True
        if budget is not None:
            budget.finish()
            need(report['seconds_spent'] <= TOTAL_SECONDS and 0 <= time.monotonic() - clock <= 2400,
                 'live finalization exceeds original diagnostic/evidence clock')
        save(published, report)
        if state.exists(): state.unlink()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['preflight', 'finalize'])
    parser.add_argument('--bounded-sample', nargs=2)
    args = parser.parse_args()
    if args.bounded_sample:
        need(args.phase is None, 'ambiguous live diagnostic command')
        bounded_sample(*args.bounded_sample); return
    with cancellation_guard():
        if args.phase == 'preflight': preflight()
        elif args.phase == 'finalize': finalize()
        else: raise ValueError('live diagnostic phase required')

if __name__ == '__main__': main()
