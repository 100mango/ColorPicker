"""One 40 mm Edit-a-Copy observation. Never platform or release acceptance.

One selector drains XCTest and each observer concurrently. No observer calls
into the application, changes focus/quiescence, or holds its main thread. OS
sampling and screen capture still have overhead; their run is diagnostic only.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

from atomic_json import write_json
from bounded_process import group_exists, stop_group
from palette_lifecycle_diagnostics import capture
from watch_runtime_pair import verify_new_device, verify_pair, phone_template

PARENT = '74ccaa93ae3f0cb5d0a63f6957460e9e8e576add'
BRANCH = 'refs/heads/codex/watch-copy-observation'
WORKFLOW = '.github/workflows/watch-copy-observation.yml'
CASE = 'testTouchEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder'
CASE_KEY = '__WatchWorkflowTests_' + CASE + '_'
BUNDLE = 'com.mango.touchColor.watchkitapp'
ROOT = Path('build/watch-copy-observation')
EVIDENCE = ROOT / 'evidence'
STATE = EVIDENCE / 'observation.json'
LATCH = EVIDENCE / 'uncertain.json'
RESULT = ROOT / 'touch.xcresult'
PRODUCT = ROOT / 'derived/Build/Products/Debug-watchsimulator/TouchColor.app'
JOB_SECONDS = 2100
WORK_SECONDS = 1620  # 35 min minus startup30/cleanup130/evidence180/validation60/upload60/overhead20.
PHASE_SECONDS = {'preflight': 60, 'build': 420, 'setup': 600, 'test': 300}
OBSERVATION_SECONDS = 35
OBSERVER_DELAY = 5
LIMIT = 1_200_000
CAPS = {'test': 256*1024, 'lifecycle': 64*1024, 'pid-before': 4096,
        'sample': 256*1024, 'pid-after': 4096, 'screenshot': 4096}
SCREEN_CAP = 300_000
CLOCK_MARGIN = .05
INTERPRETATION = 'bounded-low-interference-diagnostic-only; observer-pass-is-not-original-flow-acceptance'
START = re.compile(r"Test Case '-\[(?:TouchColorWatchUITests\.)?WatchWorkflowTests " + CASE + r"\]' started\.$")
END = re.compile(r"Test Case '-\[(?:TouchColorWatchUITests\.)?WatchWorkflowTests " + CASE + r"\]' (passed|failed) \(([0-9.]+) seconds\)\.$")
TAP = re.compile(r'\bt =\s*([0-9.]+)s Tap "watch.edit.copy" Button\s*$')
ELAPSED = re.compile(r'\bt =\s*([0-9]+\.[0-9]+)s ')
TEST_CLOCK = re.compile(r'\bt =\s*0\.00s Start Test at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})$')
EDITOR = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+) .*?TouchColor\[([1-9][0-9]*):[^]]+\].*?'
    r'\[com\.mango\.touchColor\.WatchDiagnostics:editor\] WATCH_EDITOR (appear|disappear|focus|component_changed|component_unchanged) '
    r'case=' + re.escape(CASE_KEY) + r' id=([0-9A-F-]{36}) visible=(true|false)(?: focused=(true|false))? active=([0-9]+) dropped=([0-9]+)$')


def require(value, reason):
    if not value: raise ValueError(reason)


def digest(raw): return hashlib.sha256(raw).hexdigest()


def source_identity(env):
    require(env.get('GITHUB_REPOSITORY') == '100mango/ColorPicker' and env.get('GITHUB_REF') == BRANCH
        and env.get('GITHUB_EVENT_NAME') == 'push', 'wrong-diagnostic-route')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and env.get('GITHUB_WORKFLOW_SHA') == sha, 'wrong-source')
    require(env.get('GITHUB_WORKFLOW_REF') == '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH, 'wrong-workflow')
    require(all(re.fullmatch('[1-9][0-9]{0,19}', env.get(k, '')) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')), 'wrong-run')
    return {'sha': sha, 'parent': PARENT, 'run': env['GITHUB_RUN_ID'], 'attempt': env['GITHUB_RUN_ATTEMPT'],
            'workflow': WORKFLOW, 'ref': BRANCH}


def test_command(device):
    uuid.UUID(device)
    return ['xcodebuild', 'test-without-building', '-project', 'TouchColorWatch.xcodeproj', '-scheme', 'TouchColorWatch',
        'CODE_SIGNING_ALLOWED=NO', '-configuration', 'Debug', '-destination', 'platform=watchOS Simulator,id=' + device,
        '-derivedDataPath', str(ROOT / 'derived'), '-resultBundlePath', str(RESULT),
        '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1',
        '-collect-test-diagnostics', 'never', '-test-timeouts-enabled', 'YES',
        '-default-test-execution-time-allowance', '120', '-maximum-test-execution-time-allowance', '120',
        '-only-testing:TouchColorWatchUITests/WatchWorkflowTests/' + CASE, 'ARCHS=arm64']


def lifecycle_command(device):
    predicate = 'subsystem == "com.mango.touchColor.WatchDiagnostics" AND eventMessage CONTAINS "case=' + CASE_KEY + ' "'
    return ['xcrun', 'simctl', 'spawn', device, 'log', 'show', '--style', 'compact', '--last', '120s', '--predicate', predicate]


def bind_lifecycle(raw, test_epoch, tap_epoch, returned_epoch):
    """Two app-owned editor appearances, with the first closed, on one PID.

    Exact case + newly created owned device + the test's epoch binds the query.
    A copy appearance must be newer than the first editor's disappearance.
    This is lifecycle evidence, not a claim that the UI rendered or was idle.
    """
    rows = []
    for line in raw.decode('utf-8', errors='strict').splitlines():
        if 'WATCH_EDITOR ' not in line: continue
        match = EDITOR.fullmatch(line)
        require(match is not None, 'unparsed-editor-line')
        stamp, pid, kind, editor, visible, focused, active, dropped = match.groups()
        epoch = datetime.datetime.fromisoformat(stamp).replace(tzinfo=datetime.timezone.utc).timestamp()
        require(test_epoch <= epoch <= returned_epoch, 'editor-outside-current-test')
        uuid.UUID(editor)
        rows.append(dict(epoch=epoch, pid=int(pid), kind=kind, editor=editor, visible=visible == 'true',
                         focused=None if focused is None else focused == 'true', active=int(active), dropped=int(dropped)))
    require(rows and len(rows) <= 96 and len({r['pid'] for r in rows}) == 1, 'ambiguous-app-process')
    appearances = [r for r in rows if r['kind'] == 'appear']
    require(len(appearances) == 2 and appearances[0]['editor'] != appearances[1]['editor'], 'not-exact-copy-lifecycle')
    first, second = appearances
    require(first['visible'] and second['visible'] and first['active'] == second['active'] == 1, 'overlapping-editors')
    require(any(r['kind'] == 'disappear' and r['editor'] == first['editor'] and r['active'] == 0
                and first['epoch'] < r['epoch'] < second['epoch'] for r in rows), 'missing-first-editor-disappearance')
    # Tap is observed from streamed XCTest output. Buffering can make receipt
    # later than the actual app event; no invented subsecond simultaneity claim.
    require(second['epoch'] >= first['epoch'] and second['epoch'] <= returned_epoch and tap_epoch >= test_epoch,
            'unbound-copy-window')
    return {'pid': second['pid'], 'copyEditor': second['editor'], 'copyAppearanceEpoch': second['epoch'], 'events': rows}


def parse_process(raw, pid, device, product=None, home=None):
    line = raw.decode('utf-8', errors='strict').strip()
    # lstart is five words; keep it verbatim for the post-sample PID reuse check.
    match = re.fullmatch(r'\s*([1-9][0-9]*)\s+([A-Za-z]{3}\s+[A-Za-z]{3}\s+[0-9]{1,2}\s+[0-9:]{8}\s+[0-9]{4})\s+(.+)', line)
    require(match is not None and int(match[1]) == pid, 'missing-exact-pid')
    path = Path(match[3]); base = (Path.home() if home is None else Path(home)) / 'Library/Developer/CoreSimulator/Devices' / device / 'data/Containers/Bundle/Application'
    require(path.is_absolute() and path.parent.name == 'TouchColor.app' and path.name == 'TouchColor', 'wrong-app-executable')
    require(path.parent.parent.parent == base, 'process-outside-owned-watch')
    uuid.UUID(path.parent.parent.name)
    require(path.resolve(strict=True) == path and path.is_file(), 'linked-or-missing-app-executable')
    built = Path(PRODUCT if product is None else product)
    actual_info = plistlib.loads((path.parent / 'Info.plist').read_bytes())
    require(actual_info.get('CFBundleIdentifier') == BUNDLE, 'wrong-installed-bundle')
    files = {}
    # Debug builds may contain the real code in a dylib; bind it as well as the
    # launcher and plist. No same-name process or PID from a runner is accepted.
    for name in ('Info.plist', 'TouchColor', 'TouchColor.debug.dylib'):
        a, b = path.parent / name, built / name
        require(a.exists() == b.exists(), 'installed-product-layout-mismatch')
        if not a.exists(): continue
        require(not a.is_symlink() and not b.is_symlink() and a.is_file() and b.is_file(), 'linked-product-file')
        require(a.stat().st_size <= 16*1024*1024 and b.stat().st_size <= 16*1024*1024, 'product-file-cap')
        ar, br = a.read_bytes(), b.read_bytes()
        require(ar == br, 'installed-product-bytes-mismatch')
        files[name] = digest(ar)
    return {'pid': pid, 'started': ' '.join(match[2].split()), 'path': str(path), 'files': files}


def validate_sample(raw, identity):
    text = raw.decode('utf-8', errors='strict')
    require(re.search(r'^Process:\s+TouchColor \[' + str(identity['pid']) + r'\]\s*$', text, re.M), 'sample-pid-mismatch')
    require(re.search(r'^Path:\s+' + re.escape(identity['path']) + r'\s*$', text, re.M), 'sample-path-mismatch')
    require('Call graph:' in text, 'missing-sample-call-graph')


def validate_screen(raw):
    require(raw[:8] == b'\x89PNG\r\n\x1a\n', 'invalid-screen-png')
    offset = 8; chunks = 0; ended = False; image_data = False
    while offset < len(raw):
        require(offset + 12 <= len(raw) and chunks < 64 and not ended, 'invalid-png-chunk')
        length = int.from_bytes(raw[offset:offset+4], 'big'); kind = raw[offset+4:offset+8]
        end = offset + 12 + length
        require(end <= len(raw), 'truncated-png')
        data = raw[offset+8:offset+8+length]
        require(zlib.crc32(kind+data) & 0xffffffff == int.from_bytes(raw[end-4:end], 'big'), 'png-crc-mismatch')
        if chunks == 0:
            require(kind == b'IHDR' and length == 13 and
                (int.from_bytes(data[:4], 'big'), int.from_bytes(data[4:8], 'big')) == (324, 394), 'wrong-40mm-screen-size')
        if kind == b'IDAT': image_data = True
        if kind == b'IEND': require(length == 0, 'bad-png-end'); ended = True
        offset = end; chunks += 1
    require(ended and image_data, 'incomplete-screen-png')


def read_owned_screen(path, directory_identity):
    """Read only a terminal producer's owned regular file, with an actual cap."""
    path = Path(path); parent = path.parent.lstat()
    require(stat.S_ISDIR(parent.st_mode) and (parent.st_dev, parent.st_ino) == directory_identity, 'screen-directory-changed')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= SCREEN_CAP, 'nonregular-or-oversized-screen')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        require((opened.st_dev, opened.st_ino, opened.st_size) == (before.st_dev, before.st_ino, before.st_size), 'screen-file-changed')
        with os.fdopen(descriptor, 'rb', closefd=False) as source: raw = source.read(SCREEN_CAP + 1)
        after = os.fstat(descriptor)
        require(len(raw) <= SCREEN_CAP and len(raw) == before.st_size and
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) ==
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns), 'screen-changed-during-read')
    finally: os.close(descriptor)
    validate_screen(raw)
    return raw, (before.st_dev, before.st_ino)


class Timeline:
    """Only the pre-existing action/lifecycle output can open observation."""
    def __init__(self):
        self.started = None; self.tap = None; self.ended = None; self.timeout = False; self.progressed = False
        self.case_epoch = None; self.elapsed = None; self.elapsed_received = None

    def line(self, line, now, epoch):
        line = line.rstrip()
        if START.search(line):
            require(self.started is None, 'repeated-case')
            self.started = (now, epoch)
        clock = TEST_CLOCK.search(line)
        if clock:
            require(self.started is not None and self.case_epoch is None, 'unbound-or-repeated-case-clock')
            self.case_epoch = datetime.datetime.fromisoformat(clock[1]).replace(tzinfo=datetime.timezone.utc).timestamp()
            require(self.case_epoch <= epoch, 'case-clock-in-future')
        elapsed = ELAPSED.search(line)
        if elapsed and self.started is not None and self.ended is None:
            value = float(elapsed[1])
            if self.elapsed is None or value >= self.elapsed:
                self.elapsed, self.elapsed_received = value, now
        if TAP.search(line):
            require(self.started is not None and self.ended is None and self.tap is None, 'unbound-or-repeated-copy-tap')
            self.tap = (now, epoch, float(TAP.search(line)[1]))
        if self.tap is not None and re.search(r'\bt =\s*[0-9.]+s Tap "watch.component.down" Button\s*$', line):
            self.progressed = True
        ending = END.search(line)
        if ending:
            require(self.started is not None and self.ended is None, 'unbound-case-end')
            self.ended = {'result': ending[1], 'seconds': float(ending[2]), 'observedMonotonic': now}
        if 'exceeded execution time allowance' in line or 'TOUCHCOLOR_UI_FAIL_CLOSED_ABORT' in line:
            self.timeout = True

    def due(self, now):
        return self.tap is not None and self.ended is None and not self.timeout and not self.progressed and now >= self.tap[0] + OBSERVER_DELAY

    def case_deadline(self, now, epoch, anchor):
        if self.started is None or self.case_epoch is None or self.elapsed is None: return None
        anchor_mono, anchor_wall = anchor
        # UTC wall time maps the existing absolute XCTest Start Test timestamp
        # to this host's monotonic clock. Buffered START/t lines cannot reset it.
        # Refuse a wall-clock discontinuity; the margin only shortens admission.
        if abs((epoch-anchor_wall)-(now-anchor_mono)) > CLOCK_MARGIN: return None
        if not anchor_wall <= self.case_epoch <= epoch: return None
        absolute = anchor_mono + (self.case_epoch-anchor_wall) + 120 - CLOCK_MARGIN
        relative = self.elapsed_received + 120 - self.elapsed - .01
        return min(self.started[0]+120, absolute, relative)

    def observation_ceiling(self, now, test_deadline, epoch, anchor):
        require(self.started is not None and self.due(now), 'no-copy-window')
        case_deadline = self.case_deadline(now, epoch, anchor)
        if case_deadline is None: return None
        ceiling = min(test_deadline, case_deadline)
        return now + OBSERVATION_SECONDS if now + OBSERVATION_SECONDS + 4 < ceiling else None


class Session:
    """A fixed, non-retrying observation chain alongside one XCTest process."""
    def __init__(self, owner, device, deadline, *, clock=time.monotonic, wall=time.time):
        self.owner, self.device, self.deadline = owner, device, deadline
        self.clock, self.wall = clock, wall
        self.clock_anchor = (clock(), wall())
        self.selector = selectors.DefaultSelector(); self.children = {}; self.rows = []; self.timeline = Timeline()
        self.line_buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self.observation_deadline = None; self.bound = None; self.identity = None
        self.triggered = False; self.test_exit = None; self.completed = False; self.raw_sample = None
        self.cancelled = None
        self.test_process = None; self.test_deadline = None
        self.screen_path = None; self.screen_directory_identity = None

    def drain_ready(self, timeout=0):
        """Consume all presently readable complete events before another spawn."""
        events = self.selector.select(timeout)
        while events:
            for key, _ in events:
                label, channel = key.data; entry = self.children[label]
                remaining = CAPS[label] + 1 - len(entry['stdout']) - len(entry['stderr'])
                raw = os.read(key.fileobj.fileno(), min(4096, remaining))
                if raw: self.consume(label, channel, raw)
                else:
                    self.selector.unregister(key.fileobj); key.fileobj.close(); entry['open'] -= 1
            # Per-process acquisition caps bound a continuously readable writer.
            events = self.selector.select(0)

    def live_guard(self, label):
        require(not self.owner.stopped and self.cancelled is None and self.owner.cancelled is None, 'uncertainty-or-cancellation-fence')
        self.drain_ready()
        require(self.cancelled is None and self.owner.cancelled is None, 'controller-cancelled')
        if label == 'test': return
        require(self.test_process is not None and self.test_process.poll() is None, 'xctest-already-exited')
        require(self.timeline.ended is None and not self.timeline.timeout, 'no-observer-after-case-end')
        require(not self.timeline.progressed, 'copy-window-resumed-before-next-observer')
        case_deadline = self.timeline.case_deadline(self.clock(), self.wall(), self.clock_anchor)
        require(case_deadline is not None and self.clock()+4 < case_deadline, 'case-clock-unproved-or-expired')
        require(self.test_deadline is not None and self.clock()+4 < self.test_deadline, 'xctest-command-window-expired')
        return min(case_deadline, self.test_deadline)

    def spawn(self, label, argv, seconds):
        case_ceiling = self.live_guard(label)
        now = self.clock()
        ceiling = self.deadline if label == 'test' else min(self.deadline, self.observation_deadline, case_ceiling)
        require(now + seconds + 4 < ceiling, 'observer-does-not-fit-existing-clock')
        row = {'label': label, 'argv': argv, 'startedMonotonic': now, 'startedEpoch': self.wall(),
               'deadlineMonotonic': now + seconds, 'cap': CAPS[label], 'exit': None, 'cleanupConfirmed': None}
        self.rows.append(row); self.owner.value['observationCommands'] = self.rows; self.owner.persist()
        # Persistence can deliver cancellation or allow XCTest to exit/write a
        # terminal event. Recheck all of them immediately before Popen.
        current_case_ceiling = self.live_guard(label)
        require(label == 'test' or row['deadlineMonotonic']+4 < current_case_ceiling, 'case-clock-changed-before-spawn')
        require(self.clock() < row['deadlineMonotonic'], 'late-before-spawn')
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        entry = dict(process=child, row=row, stdout=bytearray(), stderr=bytearray(), open=2)
        self.children[label] = entry; row['hostPID'] = child.pid
        if label == 'test': self.test_process = child; self.test_deadline = row['deadlineMonotonic']
        for channel, pipe in [('stdout', child.stdout), ('stderr', child.stderr)]:
            os.set_blocking(pipe.fileno(), False)
            self.selector.register(pipe, selectors.EVENT_READ, (label, channel))
        require(self.cancelled is None and self.owner.cancelled is None, 'cancelled-during-spawn')

    def consume(self, label, channel, raw):
        entry = self.children[label]
        require(len(entry['stdout']) + len(entry['stderr']) + len(raw) <= CAPS[label], label + '-byte-cap')
        entry[channel].extend(raw)
        if label == 'test':
            # Log forwarding is not required for triggering and cannot block
            # behind an observer. The retained stream is bounded separately.
            self.line_buffers[channel].extend(raw)
            require(len(self.line_buffers[channel]) <= 16*1024 or b'\n' in self.line_buffers[channel], 'test-line-cap')
            while b'\n' in self.line_buffers[channel]:
                line, _, tail = self.line_buffers[channel].partition(b'\n'); self.line_buffers[channel] = bytearray(tail)
                require(len(line) <= 16*1024, 'test-line-cap')
                self.timeline.line(line.decode('utf-8', errors='replace'), self.clock(), self.wall())
            if self.timeline.timeout: raise RuntimeError('xctest-timeout-or-interruption')

    def finished(self, label, entry):
        row = entry['row']; process = entry['process']
        require(process.returncode is not None and not group_exists(process.pid), label + '-descendants-unconfirmed')
        require(self.clock() < row['deadlineMonotonic'], label + '-late-return')
        row.update(exit=process.returncode, cleanupConfirmed=True, finishedMonotonic=self.clock(), finishedEpoch=self.wall(),
                   stdoutBytes=len(entry['stdout']), stderrBytes=len(entry['stderr']))
        raw = bytes(entry['stdout']); errors = bytes(entry['stderr'])
        row.update(stdoutSHA256=digest(raw), stderrSHA256=digest(errors))
        row['stderrTail'] = errors.decode('utf-8', errors='replace')[-1024:]
        self.owner.persist()
        if label == 'test':
            self.owner.retain_bytes('test-stdout.log', raw); self.owner.retain_bytes('test-stderr.log', errors)
            self.test_exit = process.returncode
            require(process.returncode in (0, 65) and self.timeline.ended is not None, 'unclosed-test-lifecycle')
            self.owner.value['caseOutcome'] = self.timeline.ended
            require((process.returncode == 0) == (self.timeline.ended['result'] == 'passed'), 'test-outcome-mismatch')
            return
        require(process.returncode == 0, label + '-nonzero')
        if label == 'lifecycle':
            self.bound = bind_lifecycle(raw, self.timeline.case_epoch, self.timeline.tap[1], row['finishedEpoch'])
            self.owner.value['lifecycle'] = self.bound
            self.owner.retain_bytes('editor-lifecycle.log', raw)
            self.spawn('pid-before', ['ps', '-p', str(self.bound['pid']), '-o', 'pid=', '-o', 'lstart=', '-o', 'comm='], 3)
        elif label == 'pid-before':
            self.identity = parse_process(raw, self.bound['pid'], self.device)
            self.owner.value['appIdentity'] = self.identity
            require(self.clock() < row['deadlineMonotonic'], 'late-product-binding')
            self.spawn('sample', ['/usr/bin/sample', str(self.bound['pid']), '1', '10', '-file', '/dev/stdout'], 6)
        elif label == 'sample':
            validate_sample(raw, self.identity); self.raw_sample = raw
            self.spawn('pid-after', ['ps', '-p', str(self.bound['pid']), '-o', 'pid=', '-o', 'lstart=', '-o', 'comm='], 3)
        elif label == 'pid-after':
            after = parse_process(raw, self.bound['pid'], self.device)
            require(after == self.identity, 'process-changed-during-sample')
            self.owner.retain_bytes('app-sample.txt', self.raw_sample)
            self.live_guard('screenshot')
            directory = Path(tempfile.mkdtemp(prefix='owned-screen-', dir=ROOT))
            info = directory.lstat(); self.screen_directory_identity = (info.st_dev, info.st_ino)
            self.screen_path = directory / 'copy.png'
            self.owner.value['ownedScreenshot'] = {'directory': str(directory), 'path': str(self.screen_path),
                'directoryDevice': info.st_dev, 'directoryInode': info.st_ino, 'fileLimit': SCREEN_CAP,
                'terminalProducer': False, 'removedAfterRetention': False}
            # Repository capture_simulator_checkpoint.py uses an explicit owned
            # destination. '-' is not assumed to mean stdout on this toolchain.
            self.spawn('screenshot', ['xcrun', 'simctl', 'io', self.device, 'screenshot', '--type=png', str(self.screen_path)], 8)
        elif label == 'screenshot':
            self.live_guard('screenshot')
            require(row['exit'] == 0 and row['cleanupConfirmed'] is True, 'screen-producer-not-terminal')
            image, file_identity = read_owned_screen(self.screen_path, self.screen_directory_identity)
            require(self.clock() < row['deadlineMonotonic'], 'late-screen-read')
            self.live_guard('screenshot')
            self.owner.retain_bytes('copy-screen.png', image)
            self.owner.value['ownedScreenshot'].update(terminalProducer=True, bytes=len(image), sha256=digest(image))
            # Only after confirmed production, identity/read validation and a
            # live cancellation/uncertainty guard may this owned file be removed.
            self.live_guard('screenshot')
            current = self.screen_path.lstat()
            require((current.st_dev, current.st_ino) == file_identity, 'screen-changed-before-removal')
            self.screen_path.unlink(); self.screen_path.parent.rmdir()
            self.owner.value['ownedScreenshot']['removedAfterRetention'] = True
            self.completed = True
            self.owner.value['observationStatus'] = 'sample-and-screen-captured-with-overhead'
        self.owner.persist()

    def run(self):
        previous = {}
        def interrupted(signum, frame):
            if self.cancelled is None: self.cancelled = signum
            if self.owner.cancelled is None: self.owner.cancelled = signum
        try:
            # Record-only handlers cover Popen ownership assignment and remain
            # active through bounded TERM/KILL cleanup, including repeat signals.
            for signum in (signal.SIGTERM, signal.SIGINT): previous[signum] = signal.signal(signum, interrupted)
            # This cap includes cold XCTest installation/startup. It does not
            # lengthen the pre-existing test's own 120 second allowance.
            self.spawn('test', test_command(self.device), 280)
            while self.children:
                require(self.cancelled is None and self.owner.cancelled is None, 'controller-cancelled')
                require(not self.owner.stopped and self.clock() < self.deadline, 'test-phase-deadline')
                for label, entry in tuple(self.children.items()):
                    require(self.clock() < entry['row']['deadlineMonotonic'], label + '-deadline')
                    entry['process'].poll()
                # Pending terminal/progress/cancel events take precedence over
                # starting the lifecycle observer or any observer handoff.
                self.drain_ready(.025)
                if self.test_process.poll() is not None and self.timeline.ended is None:
                    raise RuntimeError('xctest-exited-without-closed-case')
                if self.screen_path is not None and self.screen_path.exists():
                    info = self.screen_path.lstat()
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= SCREEN_CAP,
                            'screen-file-cap-or-type')
                if not self.triggered and self.timeline.due(self.clock()):
                    self.triggered = True
                    self.observation_deadline = self.timeline.observation_ceiling(self.clock(), min(self.deadline,self.test_deadline), self.wall(), self.clock_anchor)
                    self.owner.value.update(copyTapObservedEpoch=self.timeline.tap[1], observerDelaySeconds=OBSERVER_DELAY,
                        copyTapXCTestElapsed=self.timeline.tap[2],
                        caseStartEpoch=self.timeline.case_epoch, latestXCTestElapsed=self.timeline.elapsed,
                        caseDeadlineMonotonic=self.timeline.case_deadline(self.clock(), self.wall(), self.clock_anchor),
                        observationDeadlineMonotonic=self.observation_deadline)
                    if self.observation_deadline is None:
                        self.owner.value['observationStatus'] = 'insufficient-original-case-window-no-observer'
                        self.owner.persist()
                    else:
                        self.spawn('lifecycle', lifecycle_command(self.device), 5)
                for label, entry in tuple(self.children.items()):
                    entry['process'].poll()
                    if entry['open'] == 0 and entry['process'].returncode is not None:
                        self.finished(label, entry)
                        del self.children[label]
                # Never start a new observer after a case ended; an already
                # running observer is stopped and labelled incomplete instead.
                if self.timeline.ended is not None and any(k != 'test' for k in self.children):
                    raise RuntimeError('case-ended-during-observation')
            if not self.triggered: self.owner.value['observationStatus'] = (
                'copy-interaction-resumed-before-observation' if self.timeline.progressed else 'copy-window-not-observed')
            require(self.test_exit is not None, 'missing-test-exit')
        except BaseException as error:
            self.owner.fence(str(error))
            raise
        finally:
            # Only owned observer/Xcode host process groups are signalled.
            # Never signal the sampled app, runner PID from a log, or sim daemon.
            try:
                for label, entry in tuple(self.children.items()):
                    confirmed = stop_group(entry['process'], grace=2)
                    entry['row']['cleanupConfirmed'] = confirmed
                    entry['row']['forcedHostCleanup'] = True
                    for pipe in (entry['process'].stdout, entry['process'].stderr):
                        if pipe and not pipe.closed: pipe.close()
                self.selector.close()
                for label, entry in self.children.items():
                    if label == 'test':
                        self.owner.retain_bytes('test-stdout.log', bytes(entry['stdout']))
                        self.owner.retain_bytes('test-stderr.log', bytes(entry['stderr']))
                self.owner.persist()
            finally:
                for signum, handler in previous.items(): signal.signal(signum, handler)
            if self.cancelled is not None or self.owner.cancelled is not None:
                self.owner.fence('controller-cancelled-during-session-close')
                raise RuntimeError('controller-cancelled-during-session-close')


class Owner:
    def __init__(self, source, started, *, runner=capture, clock=time.monotonic):
        self.source, self.started, self.runner, self.clock = source, started, runner, clock
        self.stopped = False; self.devices = []; self.pair = None; self.phase_deadline = None
        self.cancelled = None
        self.value = dict(schema=1, source=source, acceptance=False, interpretation=INTERPRETATION,
            result='incomplete', phase='preflight', commands=[], ownedDevices=self.devices,
            observationCommands=[], observationStatus='not-started', caseOutcome=None,
            byteLimit=LIMIT, jobSeconds=JOB_SECONDS, workSeconds=WORK_SECONDS, phaseLimits=PHASE_SECONDS)

    def persist(self):
        write_json(STATE, self.value)

    def retain_bytes(self, name, raw):
        require('/' not in name and len(raw) <= LIMIT, 'invalid-retained-file')
        path = EVIDENCE / name
        require(not path.exists() and not path.is_symlink(), 'repeat-evidence-file')
        path.write_bytes(raw)

    def fence(self, reason):
        self.stopped = True
        self.value.update(result='incomplete', reason=str(reason)[:500], simulatorCompletion='unknown',
                          furtherCommandsForbidden=True, disposableVMRequired=True)
        write_json(LATCH, {'source': self.source, 'reason': str(reason)[:500], 'furtherCommandsForbidden': True})
        self.persist()

    def phase(self, name, seconds):
        self.value['phase'] = name
        ceiling = self.started + (WORK_SECONDS if name != 'cleanup' else WORK_SECONDS + 130)
        self.phase_deadline = min(self.clock() + seconds, ceiling)
        self.persist()

    def call(self, label, argv, seconds, cap=256*1024, allowed=(0,), merge=False):
        require(not self.stopped and self.cancelled is None and not LATCH.exists(), 'uncertainty-or-cancellation-fence')
        began = self.clock(); deadline = min(began + seconds, self.phase_deadline - 4)
        require(deadline >= began + seconds, 'full-command-does-not-fit-phase')
        row = dict(label=label, argv=argv, startedMonotonic=began, deadlineMonotonic=deadline,
                   exit=None, cleanupConfirmed=None, cap=cap)
        self.value['commands'].append(row); self.persist()
        try:
            require(self.cancelled is None and not self.stopped and not LATCH.exists(), 'cancelled-after-persistence')
            remaining = deadline - self.clock(); require(remaining > 0, 'late-before-command')
            result = self.runner(argv, seconds=remaining, cap=cap, cleanup_grace=2)
            row.update(exit=result.returncode, cleanupConfirmed=True, finishedMonotonic=self.clock(),
                       stdoutBytes=len(result.stdout), stderrBytes=len(result.stderr),
                       stdoutSHA256=digest(result.stdout), stderrSHA256=digest(result.stderr))
            require(self.clock() < deadline and result.returncode in allowed, 'late-or-failed-' + label)
            self.persist()
            return result.stdout + result.stderr if merge else result.stdout
        except BaseException as error:
            if getattr(error, 'cancelled_signal', None) is not None: self.cancelled = error.cancelled_signal
            if row['cleanupConfirmed'] is None: row['cleanupConfirmed'] = getattr(error, 'cleanup_confirmed', None)
            self.fence(label + ':' + str(error)); raise

    def prepare(self):
        self.phase('preflight', 60)
        require(self.call('source', ['git', 'show', '--no-patch', '--format=%H%n%P', 'HEAD'], 5).decode().strip().splitlines()
                == [self.source['sha'], PARENT], 'wrong-sole-parent')
        require(self.call('clean', ['git', 'status', '--porcelain', '--untracked-files=all'], 5) == b'', 'dirty-source')
        require(self.call('xcode', ['xcodebuild', '-version'], 5).decode().strip() == 'Xcode 27.0\nBuild version 27A266a', 'wrong-xcode')
        require(self.call('system', ['sw_vers', '-buildVersion'], 5).decode().strip() == '26A428', 'wrong-system')
        require(self.call('architecture', ['uname', '-m'], 5).decode().strip() == 'arm64', 'wrong-architecture')
        require(self.call('timezone', ['date', '+%z'], 5).decode().strip() == '+0000', 'log-clock-not-utc')
        # Screenshot uses this repository's existing owned-file route. Tool help
        # text is not treated as execution evidence for '-' or stdout support.
        self.phase('build', 420)
        self.call('build', ['xcodebuild', '-quiet', '-project', 'TouchColorWatch.xcodeproj', '-scheme', 'TouchColorWatch',
            '-configuration', 'Debug', '-destination', 'generic/platform=watchOS Simulator', '-derivedDataPath', str(ROOT / 'derived'),
            'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO', 'build-for-testing'], 400)
        self.phase('setup', 600)
        devices = json.loads(self.call('devices', ['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 20))['devices']
        watches = [(runtime, item) for runtime, items in devices.items() if runtime.endswith('watchOS-27-0')
                   for item in items if item.get('isAvailable') and item.get('deviceTypeIdentifier') == 'com.apple.CoreSimulator.SimDeviceType.Apple-Watch-SE-3-40mm']
        require(len(watches) == 1, 'missing-or-ambiguous-40mm')
        phone_runtime, phone = phone_template(devices); watch_runtime, watch = watches[0]
        before = json.loads(self.call('pairs', ['xcrun', 'simctl', 'list', 'pairs', '-j'], 20))
        require(isinstance(before.get('pairs'), dict) and len(before['pairs']) <= 64, 'invalid-original-pairs')
        for role, runtime, template in [('phone', phone_runtime, phone), ('watch', watch_runtime, watch)]:
            identifier = self.call('create-' + role, ['xcrun', 'simctl', 'create', 'TouchColor-copy-' + role + '-' + uuid.uuid4().hex[:8],
                template['deviceTypeIdentifier'], runtime], 30).decode().strip()
            verify_new_device(identifier, devices, self.devices)
            self.devices.append({'role': role, 'udid': identifier, 'runtime': runtime,
                                 'deviceTypeIdentifier': template['deviceTypeIdentifier']}); self.persist()
        phone_id, watch_id = [x['udid'] for x in self.devices]
        self.pair = self.call('pair', ['xcrun', 'simctl', 'pair', watch_id, phone_id], 30).decode().strip(); uuid.UUID(self.pair)
        actual = json.loads(self.call('pair-readback', ['xcrun', 'simctl', 'list', 'pairs', '-j'], 20))
        paired = verify_pair(actual, self.pair, watch_id, phone_id, before['pairs'])
        require(paired.get('state') in ('(active, connected)', '(active, disconnected)'), 'created-pair-not-active')
        self.value['ownedPair'] = self.pair; self.persist()
        self.boot_owned_pair()
        return watch_id

    def boot_owned_pair(self):
        # Fresh host only: phone's observed direct route, Watch's historical split
        # route. Every full allowance must fit the same setup600 absolute clock.
        # Nominal setup allowances total730; slow earlier calls prevent admission
        # of later calls. No deadline reset, timeout fallback or retry is permitted.
        try:
            phone, watch = self.devices
            self.call('bootstatus-phone', ['xcrun', 'simctl', 'bootstatus', phone['udid'], '-b'], 200)
            self.call('boot-watch', ['xcrun', 'simctl', 'boot', watch['udid']], 180)
            self.call('bootstatus-watch', ['xcrun', 'simctl', 'bootstatus', watch['udid'], '-b'], 180)
            inventory = json.loads(self.call('booted-inventory',
                ['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 20))['devices']
            verified = []
            for owned in self.devices:
                matches = [(runtime, item) for runtime, items in inventory.items() for item in items
                           if item.get('udid') == owned['udid']]
                require(len(matches) == 1, 'missing-or-ambiguous-owned-booted-device')
                runtime, item = matches[0]
                require(runtime == owned['runtime'] and item.get('isAvailable') is True
                        and item.get('state') == 'Booted'
                        and item.get('deviceTypeIdentifier') == owned['deviceTypeIdentifier'],
                        'owned-device-not-booted-or-identity-changed')
                verified.append({**owned, 'state': item['state'], 'isAvailable': True})
            self.value['bootedInventory'] = verified; self.persist()
        except BaseException as error:
            if not self.stopped: self.fence(str(error))
            raise

    def cleanup(self):
        if self.cancelled is not None:
            self.fence('controller-cancelled-before-device-cleanup')
            return
        if self.stopped: return
        self.phase('cleanup', 130)
        for item in reversed(self.devices): self.call('shutdown-' + item['role'], ['xcrun', 'simctl', 'shutdown', item['udid']], 20)
        if self.pair: self.call('unpair', ['xcrun', 'simctl', 'unpair', self.pair], 20)
        for item in reversed(self.devices): self.call('delete-' + item['role'], ['xcrun', 'simctl', 'delete', item['udid']], 20)


def local_validation():
    files = []
    allowed = {'observation.json', 'uncertain.json', 'test-stdout.log', 'test-stderr.log',
               'editor-lifecycle.log', 'app-sample.txt', 'copy-screen.png'}
    for path in EVIDENCE.iterdir():
        require(path.name in allowed, 'unknown-evidence-file')
        require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1, 'nonregular-evidence')
        require(path.stat().st_size <= 300_000 if path.name != STATE.name else path.stat().st_size <= 128*1024, 'retained-file-cap')
        raw = path.read_bytes(); files.append({'path': path.name, 'bytes': len(raw), 'sha256': digest(raw)})
    require(sum(x['bytes'] for x in files) + 32*1024 <= LIMIT, 'total-evidence-cap')
    write_json(ROOT / 'artifact-manifest.json', {'acceptance': False, 'interpretation': INTERPRETATION, 'files': files})


def plan():
    return dict(parent=PARENT, branch=BRANCH, workflow=WORKFLOW, profile='SE3/40mm/watchOS27', cases=[CASE],
        jobSeconds=JOB_SECONDS, workSeconds=WORK_SECONDS, phases=PHASE_SECONDS, maximumPhaseSum=1380,
        observation='one lifecycle query, exact PID before/after, sample 1s at 10ms, one screen; inside test clock',
        testCaseSeconds=120, sampleOverhead='not-zero; diagnostic-only', observerSeconds=OBSERVATION_SECONDS,
        retry=False, matrix=False, crown=False, acceptance=False, evidenceLimit=LIMIT)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--plan', action='store_true'); args = parser.parse_args()
    if args.plan: print(json.dumps(plan(), indent=2)); return 0
    source = source_identity(os.environ)
    started = float(os.environ['WATCH_COPY_STARTED_MONOTONIC'])
    require(0 < started <= time.monotonic() and time.monotonic() - started < WORK_SECONDS, 'invalid-job-start')
    require(not ROOT.exists() and not ROOT.is_symlink(), 'stale-diagnostic-output')
    EVIDENCE.mkdir(parents=True)
    owner = Owner(source, started)
    previous = {}
    def interrupted(signum, frame):
        owner.cancelled = signum
        raise RuntimeError('controller-interrupted-' + str(signum))
    try:
        for signum in (signal.SIGTERM, signal.SIGINT): previous[signum] = signal.signal(signum, interrupted)
        device = owner.prepare()
        owner.phase('test', 300)
        Session(owner, device, owner.phase_deadline).run()
        owner.value['result'] = 'diagnostic-observation-closed'
        owner.cleanup()
    except BaseException as error:
        if not owner.stopped: owner.fence(str(error))
    finally:
        for signum, handler in previous.items(): signal.signal(signum, handler)
        owner.persist(); local_validation()
    # A diagnostic never returns a product-acceptance success.
    return 3


if __name__ == '__main__': sys.exit(main())
