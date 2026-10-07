"""Read one source-bound Watch failure's text stack; never collect a sysdiagnose."""
import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
import tempfile
import time
from ios_watch_archive_capture import capture, CaptureStopped

APP = 'com.mango.touchColor.watchkitapp'
SUITE = 'TouchColorWatchUITests'
METHOD = 'testTouchCopyEntryTouchAndCrownRemainResponsive'
TEST = 'WatchWorkflowTests/' + METHOD
CASE = '__WatchWorkflowTests_' + METHOD + '_'
BUNDLE = 'build/watch-ui.xcresult'
REPORT = 'watch-stack-diagnostic.json'
TOTAL_SECONDS = 50
MAX_CALLS = 8
MAX_META = 262144
MAX_TEXT = 262144
MAX_REPORT = 65536
ID = re.compile(r'[A-Za-z0-9_~+/=\-]{1,512}\Z')
TEXT_TYPES = {'public.text', 'public.plain-text', 'public.utf8-plain-text', 'com.apple.spindump'}

def label(text, cap):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(text or ''))[:cap]

class DiagnosticCancelled(Exception):
    pass

@contextmanager
def cancellation_guard():
    previous, cancelled = {}, [None]
    def interrupted(signum, frame):
        # Raise once so temporary payload contexts unwind. Repeated signals do
        # not interrupt deletion/reporting. The capture helper temporarily uses
        # its own reviewed handlers while an owned child is running.
        if cancelled[0] is None:
            cancelled[0] = signum
            raise DiagnosticCancelled('diagnostic cancelled by signal ' + str(signum))
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        yield
    finally:
        for signum, handler in previous.items(): signal.signal(signum, handler)

@contextmanager
def private_payload_directory(root):
    need(hasattr(signal, 'pthread_sigmask'), 'bounded payload cleanup requires POSIX signal masking')
    folder = tempfile.TemporaryDirectory(prefix='watch-stack-', dir=root)
    try:
        yield Path(folder.name)
    finally:
        # Do not let either the first cancellation or a repeated one interrupt
        # TemporaryDirectory after its finalizer has detached. Pending signals
        # are delivered only after the raw payload has been deleted.
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        try: folder.cleanup()
        finally: signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)

def need(value, reason):
    if not value: raise ValueError(reason)

def read(path, cap):
    path = Path(path)
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and not path.is_symlink() and before.st_nlink == 1, 'unsafe input file')
    need(before.st_size <= cap, 'input exceeds byte cap')
    with path.open('rb') as stream: data = stream.read(cap + 1)
    after = path.lstat()
    need(len(data) <= cap and (before.st_ino, before.st_size, before.st_mtime_ns) ==
         (after.st_ino, after.st_size, after.st_mtime_ns), 'input changed during read')
    return data

def value(node, key):
    field = node.get(key, {}) if isinstance(node, dict) else {}
    return field.get('_value') if isinstance(field, dict) else None

def kind(node):
    return node.get('_type', {}).get('_name') if isinstance(node, dict) else None

def walk(root):
    pending = [(root, (), 0)]
    count = 0
    while pending:
        node, context, depth = pending.pop()
        count += 1
        need(count <= 8192 and depth <= 32, 'metadata graph exceeds node/depth cap')
        if isinstance(node, dict):
            if kind(node) in {'ActionTestActivitySummary', 'ActionTestSummaryGroup', 'ActionTestableSummary'}:
                context = context + tuple(str(value(node, key))[:512] for key in ('title', 'identifier', 'targetName') if value(node, key) is not None)
            yield node, context
            pending.extend((child, context, depth + 1) for key, child in node.items() if key != '_type')
        elif isinstance(node, list): pending.extend((child, context, depth + 1) for child in node)

def reference(node, key):
    item = node.get(key, {})
    result = value(item, 'id')
    need(kind(item) == 'Reference' and isinstance(result, str) and ID.fullmatch(result), 'invalid object reference')
    return result

def timestamp(text):
    need(isinstance(text, str) and len(text) < 80, 'missing bounded timestamp')
    parsed = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    need(parsed.tzinfo is not None, 'timestamp has no timezone')
    return parsed.timestamp()

def owned_app_path(path, device):
    if not isinstance(path, str) or len(path) > 1024 or not path.startswith('/'): return False
    if any(part in {'.', '..'} for part in path.split('/')): return False
    marker = '/CoreSimulator/Devices/' + device + '/'
    if path.count('/CoreSimulator/Devices/') != 1 or marker not in path: return False
    tail = path.split(marker, 1)[1]
    return re.fullmatch(r'data/Containers/Bundle/Application/[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}/TouchColor\.app/TouchColor', tail) is not None

class Budget:
    def __init__(self, report, job_started, runner=capture, now=time.monotonic):
        self.report, self.runner, self.now = report, runner, now
        self.started = now()
        spent = report.get('seconds_spent', 0)
        need(type(spent) in (int, float) and 0 <= spent <= TOTAL_SECONDS, 'invalid diagnostic budget')
        self.prior = spent
        self.job_started = job_started
        self.calls = report.get('calls', 0)
        need(type(self.calls) is int and 0 <= self.calls <= MAX_CALLS, 'invalid command count')
    def elapsed(self): return self.prior + self.now() - self.started
    def run(self, command, cap=MAX_META):
        # One cumulative preflight+collection allowance, never renewed per node.
        # Reserve both existing TERM/KILL cleanup phases before every command.
        need(self.calls < MAX_CALLS and self.elapsed() + 8 + 20 <= TOTAL_SECONDS, 'diagnostic wall-clock budget exhausted')
        need(0 <= self.now() - self.job_started and self.now() - self.job_started + 8 + 20 + 10 <= 2400, 'original evidence clock has no diagnostic reserve')
        self.calls += 1
        self.report['calls'] = self.calls
        try: result = self.runner(command, seconds=8, cap=cap, cleanup_grace=10)
        except CaptureStopped as error:
            # Preserve unknown subprocess cleanup even if a later cancellation
            # is delivered while unwinding the private payload directory.
            self.report['diagnostic_cleanup_confirmed'] = error.cleanup_confirmed
            self.report['cancelled_signal'] = error.cancelled_signal
            raise
        need(isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes) and
             len(result.stdout) + len(result.stderr) <= cap, 'collector output violates byte contract')
        need(result.returncode == 0 and not result.stderr, 'diagnostic tool returned error; no fallback or retry')
        return result.stdout
    def finish(self): self.report['seconds_spent'] = round(self.elapsed(), 6)

def preflight(budget, report):
    need(report.get('phase') is None, 'diagnostic preflight already attempted')
    report['phase'] = 'preflight-started'
    required = {'get': ('--legacy', '--path', '--id', '--format'),
                'export': ('--legacy', '--path', '--id', '--type', '--output-path')}
    help_records = {}
    for operation, flags in required.items():
        report['help_operation'] = operation
        raw = budget.run(['xcrun', 'xcresulttool', 'help', operation, 'object'], cap=4096)
        text = raw.decode('utf-8')
        safe = ''.join(c if c in '\n\t' or 32 <= ord(c) < 127 else '?' for c in text)
        help_records[operation] = {'sha256': hashlib.sha256(raw).hexdigest(), 'text': safe}
        report['help'] = help_records
        need(all(flag in text for flag in flags), 'installed xcresulttool lacks required object flags')
        if operation == 'get': need('json' in text.lower(), 'JSON object output not advertised')
        else: need('file' in text.lower(), 'single-file object export not advertised')
    report.update(phase='preflight-verified', help=help_records)

def binding(runtime, before, after, sha):
    need(before == after and before.get('sha') == sha and before.get('clean') is True, 'source readback mismatch')
    need(runtime.get('sha') == sha and runtime.get('result') == 'failed' and
         not runtime.get('cleanup_unconfirmed') and runtime.get('active_command') is None, 'native work/cleanup unresolved')
    stages = runtime.get('stages', [])
    selected = [s for s in stages if '-only-testing:' + SUITE + '/' + TEST in s.get('command', [])]
    need(len(selected) == 1, 'not one exact selected test command')
    stage = selected[0]
    need(stage['command'][:2] == ['xcodebuild', 'test-without-building'] and stage.get('started') is True
         and stage.get('exit') == 65 and stage.get('raw_exit') == 65 and stage.get('timed_out') is False and stage.get('process_group_gone') is True
         and stage.get('capture_reader_finished') is True, 'test process completion unconfirmed')
    need(sum(str(c).startswith('-only-testing:') for c in stage['command']) == 1, 'multiple selected cases')
    owned = runtime.get('owned_watch_devices', [])
    need(len(owned) == 2 and {x.get('role') for x in owned} == {'phone', 'watch'}, 'owned pair missing')
    watch = next(x for x in owned if x['role'] == 'watch')['udid']
    need(re.fullmatch(r'[0-9A-F-]{36}', watch) is not None and runtime.get('device', {}).get('udid') == watch, 'device binding mismatch')
    for flag, expected in (('-destination', 'platform=watchOS Simulator,id=' + watch),
                           ('-configuration', 'Debug'), ('-collect-test-diagnostics', 'never'),
                           ('-default-test-execution-time-allowance', '120'), ('-resultBundlePath', BUNDLE)):
        need(stage['command'].count(flag) == 1 and stage['command'][stage['command'].index(flag) + 1] == expected,
             'test command contract mismatch')
    for device in owned:
        for action in ('shutdown', 'delete'):
            matches = [s for s in stages if s.get('command') == ['xcrun', 'simctl', action, device['udid']]]
            need(len(matches) == 1 and matches[0].get('exit') == 0 and matches[0].get('timed_out') is False and matches[0].get('process_group_gone') is True
                 and matches[0].get('capture_reader_finished') is True, 'owned device cleanup missing')
    lifecycle = runtime.get('watch_editor_lifecycle', {})
    need(lifecycle.get('exit') == 0, 'app lifecycle query failed')
    groups = [p for p in lifecycle.get('processes', []) if p.get('case') == CASE]
    need(len(groups) == 1 and type(groups[0].get('pid')) is int and 1 < groups[0]['pid'] < 4194304, 'app PID is not uniquely bound to current case')
    return {'sha': sha, 'case': TEST, 'pid': groups[0]['pid'], 'device': watch,
            'start': timestamp(stage['started_at']), 'end': timestamp(stage['finished_at'])}

def object_json(budget, object_id=None):
    command = ['xcrun', 'xcresulttool', 'get', 'object', '--legacy', '--path', BUNDLE, '--format', 'json']
    if object_id is not None: command += ['--id', object_id]
    raw = budget.run(command)
    data = json.loads(raw)
    types, identifiers = set(), []
    for node, _ in walk(data):
        if kind(node): types.add(label(kind(node), 60))
        if kind(node) in {'ActionTestMetadata', 'ActionTestSummary', 'ActionTestableSummary'} and len(identifiers) < 2:
            name = value(node, 'identifier') or value(node, 'targetName')
            if name: identifiers.append(label(name, 120))
    budget.report.setdefault('objects', []).append({'type': label(kind(data), 60), 'types': sorted(types)[:6],
        'identifiers': identifiers, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    return data

def attachment_candidates(summary, bound):
    candidates, inventory = [], []
    for node, context in walk(summary):
        if kind(node) != 'ActionTestAttachment': continue
        need(len(inventory) < 16, 'too many selected-case attachments')
        name, filename, uti = (value(node, key) for key in ('name', 'filename', 'uniformTypeIdentifier'))
        # Generic text stays excluded. An explicitly named app-hang text from
        # this exact failed case may be inspected under the same hard cap even
        # without a metadata PID; its actual header must still prove ownership.
        hints = ' '.join(str(x)[:512] for x in (name, filename) if x is not None)
        foreign = re.search(r'TouchColorWatchUITests|xctrunner|testmanagerd|\bRunner\b', hints, re.I) is not None
        declared = [int(x) for pair in re.findall(r'\bpid\s*[:=]?\s*(\d+)|TouchColor\s*\[(\d+)\]', hints, re.I) for x in pair if x]
        declared_devices = re.findall(r'/CoreSimulator/Devices/([0-9A-F-]{36})/', hints)
        foreign = foreign or any(pid != bound['pid'] for pid in declared) or any(device != bound['device'] for device in declared_devices)
        app = not foreign and (re.search(r'(?<![A-Za-z0-9_.])' + re.escape(APP) + r'(?![A-Za-z0-9_.])', hints) is not None
                               or re.search(r'(?<![A-Za-z0-9])TouchColor(?![A-Za-z0-9])', hints) is not None)
        claimed_paths = re.findall(r'(/[^\s]+/TouchColor\.app/TouchColor)(?:\s|$)', hints)
        device_path = any(owned_app_path(path, bound['device']) for path in claimed_paths)
        owner = bound['pid'] in declared or device_path
        text_type = uti in TEXT_TYPES and re.search(r'spindump|stack|hang|sample', hints, re.I) is not None
        app_hang = not foreign and re.search(r'\b(?:app|application)[ _-]*hang\b', hints, re.I) is not None
        row = {'name': label(name, 120), 'filename': label(filename, 120),
               'type': label(uti, 80), 'app_metadata': app, 'owner_metadata': owner, 'explicit_app_hang': app_hang}
        inventory.append(row)
        if not (((app and owner) or app_hang) and not foreign and text_type): continue
        moment = timestamp(value(node, 'timestamp'))
        need(bound['start'] <= moment <= bound['end'], 'attachment timestamp is outside current command')
        candidates.append((reference(node, 'payloadRef'), moment))
    return candidates, inventory

def main_thread_text(raw, bound, attachment_time):
    text = raw.decode('utf-8')
    need('\x00' not in text and len(raw) <= MAX_TEXT, 'non-text or oversized payload')
    for header in ('Process', 'Path', 'Identifier', 'Date/Time'):
        need(len(re.findall(r'^[ \t]*' + re.escape(header) + r':', text, re.M)) == 1, 'multiple or missing process headers')
    need(re.search(r'^[ \t]*Process:\s+TouchColor\s+\[' + str(bound['pid']) + r'\][ \t]*$', text, re.M), 'stack process PID/name mismatch')
    need(re.search(r'^[ \t]*Identifier:\s+' + re.escape(APP) + r'[ \t]*$', text, re.M), 'stack bundle identifier mismatch')
    path_match = re.search(r'^[ \t]*Path:[ \t]+(.+)$', text, re.M)
    need(path_match and owned_app_path(path_match[1], bound['device']), 'stack executable is outside owned Watch app')
    need(bound['start'] <= attachment_time <= bound['end'], 'stack time is not current')
    stamp = re.search(r'^[ \t]*Date/Time:\s+(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d+)?)[ ]*(Z|[+-]\d\d:?\d\d)[ \t]*$', text, re.M)
    need(stamp and bound['start'] <= timestamp(stamp[1] + stamp[2]) <= bound['end'], 'stack header time is outside current test')
    lines, active = [], False
    prefix = r'^\s*(?:[+|!:]\s*)*(\d+)\s+'
    sample = re.compile(prefix + r'(.+?)\s+\(in ([A-Za-z0-9_.+\-]+)\)(?:\s+\+\s+(\d+))?\s+\[(0x[0-9a-fA-F]+)\]\s*$')
    spin = re.compile(prefix + r'(.+?)\s+\+\s+(\d+)\s+\(([A-Za-z0-9_.+\-]+)\s+\+\s+\d+\)\s+\[(0x[0-9a-fA-F]+)\]\s*$')
    for line in text.splitlines():
        if re.search(r'\bThread[_ ]', line):
            if active: break
            if 'com.apple.main-thread' in line:
                active = True; lines.append('Main thread: com.apple.main-thread')
            else: continue
        if active:
            if re.match(r'^[ \t]*(?:Process|Path|Identifier|Date/Time):', line) or 'Binary Images:' in line or len(lines) >= 256: break
            match = sample.fullmatch(line) if len(line) <= 600 else None
            if match: count, symbol, image, offset, address = match.groups()
            else:
                match = spin.fullmatch(line) if len(line) <= 600 else None
                if not match: continue
                count, symbol, offset, image, address = match.groups()
            # Normalize recognized frame fields. Paths, email/URL strings and
            # arbitrary hex-bearing diagnostic lines are never copied through.
            if not re.fullmatch(r"[A-Za-z_.$+(\-][A-Za-z0-9_.$ :<>()\[\],?=&*~+!#'\-]{0,300}", symbol): continue
            lines.append(f'{count} {symbol} (in {image}) + {offset or "0"} [{address}]')
    need(len(lines) >= 2, 'no bounded main-thread stack was identified')
    stack = '\n'.join(lines)
    need(len(stack.encode()) <= 12288, 'main-thread stack exceeds retained text bound')
    return stack

def collect(budget, report, bound, temp_root):
    need(report.get('phase') == 'preflight-verified', 'installed-tool compatibility was not verified')
    report.update(phase='collecting', binding=bound)
    need(Path(BUNDLE).is_dir() and not Path(BUNDLE).is_symlink() and not Path('build').is_symlink(), 'unsafe or absent result bundle')
    invocation = object_json(budget)
    actions = [node for node, _ in walk(invocation) if kind(node) == 'ActionRecord' and
               value(node.get('runDestination', {}).get('targetDeviceRecord', {}), 'identifier') == bound['device']
               and 'testsRef' in node.get('actionResult', {})]
    need(len(actions) == 1, 'not one owned-device test action')
    tests = object_json(budget, reference(actions[0]['actionResult'], 'testsRef'))
    need(any(kind(n) == 'ActionTestableSummary' and value(n, 'targetName') == SUITE for n, _ in walk(tests)), 'test bundle identity missing')
    cases = [node for node, context in walk(tests) if kind(node) in {'ActionTestMetadata', 'ActionTestSummary'} and SUITE in context and
             (value(node, 'identifier') in {TEST, TEST + '()', SUITE + '/' + TEST, SUITE + '/' + TEST + '()'}
              or (value(node, 'identifier') in {METHOD, METHOD + '()'} and 'WatchWorkflowTests' in context and SUITE in context))]
    need(len(cases) == 1 and value(cases[0], 'testStatus') in {'Failure', 'Failed'}, 'selected failure is not unique')
    summary = cases[0] if kind(cases[0]) == 'ActionTestSummary' else object_json(budget, reference(cases[0], 'summaryRef'))
    need(kind(summary) == 'ActionTestSummary', 'unexpected referenced summary object')
    need(value(summary, 'identifier') in {None, TEST, TEST + '()', SUITE + '/' + TEST, SUITE + '/' + TEST + '()', METHOD, METHOD + '()'}, 'referenced summary is another case')
    candidates, report['attachments'] = attachment_candidates(summary, bound)
    if not candidates:
        report.update(phase='complete', evidence='no app/PID/device-bound text stack in metadata'); return
    need(len(candidates) == 1, 'multiple app stack candidates; no arbitrary selection')
    object_id, moment = candidates[0]
    with private_payload_directory(temp_root) as folder:
        path = folder / 'payload.txt'
        budget.run([sys.executable, str(Path(__file__).resolve()), '--bounded-export', object_id, str(path)], cap=8192)
        raw = read(path, MAX_TEXT)
        payload = {'main_thread': main_thread_text(raw, bound, moment),
                   'retention': {'thread': 'main', 'line_limit': 256, 'text_byte_limit': 12288, 'complete_payload': False},
                   'payload_sha256': hashlib.sha256(raw).hexdigest(), 'payload_bytes': len(raw)}
    report.update(payload)
    report.update(phase='complete', evidence='owned app main-thread stack', qualified=False)

def bounded_export(object_id, filename):
    need(ID.fullmatch(object_id), 'invalid export object ID')
    path = Path(filename)
    root = Path(os.environ['RUNNER_TEMP']).resolve()
    need(path.name == 'payload.txt' and path.parent.name.startswith('watch-stack-') and not path.parent.is_symlink() and
         path.parent.parent.resolve() == root and not path.exists() and not path.is_symlink(), 'unsafe export destination')
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT, MAX_TEXT))
    os.execvp('xcrun', ['xcrun', 'xcresulttool', 'export', 'object', '--legacy', '--path', BUNDLE,
                       '--id', object_id, '--type', 'file', '--output-path', str(path)])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['preflight', 'collect'])
    parser.add_argument('--bounded-export', nargs=2)
    args = parser.parse_args()
    if args.bounded_export:
        need(args.phase is None, 'ambiguous command'); bounded_export(*args.bounded_export); return 1
    need(args.phase is not None, 'phase required')
    with cancellation_guard(): return phase_main(args.phase)

def phase_main(phase):
    root = Path(os.environ['RUNNER_TEMP']) / 'watch-focused-evidence'
    need(root.is_dir() and not root.is_symlink(), 'unsafe evidence root')
    report = json.loads(read(root / REPORT, MAX_REPORT))
    clock = json.loads(read(root / 'report.json', MAX_REPORT))['started_monotonic']
    budget = Budget(report, clock)
    code = 0
    try:
        if phase == 'preflight': preflight(budget, report)
        else:
            bound = binding(json.loads(read('build/watch-runtime/runtime.json', MAX_META)),
                            json.loads(read(root/'source-before.json', 32768)),
                            json.loads(read(root/'source-after.json', 32768)), os.environ['GITHUB_SHA'])
            collect(budget, report, bound, Path(os.environ['RUNNER_TEMP']))
    except Exception as error:
        report.update(phase='unavailable', evidence='no qualified app stack', error=str(error)[:400])
        if isinstance(error, CaptureStopped):
            report['diagnostic_cleanup_confirmed'] = error.cleanup_confirmed
            if phase == 'preflight':
                report['incomplete_help_prefix'] = label(getattr(error, 'stdout_prefix', b'').decode('utf-8', errors='replace'), 4096)
        code = 1 if phase == 'preflight' or isinstance(error, (CaptureStopped, DiagnosticCancelled)) else 0
    finally:
        budget.finish()
        data = (json.dumps(report, indent=2) + '\n').encode()
        need(len(data) <= MAX_REPORT, 'diagnostic report exceeds artifact share')
        (root / REPORT).write_bytes(data)
    return code

if __name__ == '__main__': sys.exit(main())
