"""One post-failure Apple diagnostic export; no live sampler or debugger attach.

Raw device diagnostics remain in a private temporary directory. Only an
identity-bound main-thread excerpt and a case-bound native PNG can be retained.
Installed help is an admission gate, not a claim that a future tool was tested.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time

from ios_watch_archive_capture import capture, CaptureStopped
import watch_xcresult_stack as old
from watch_diagnostic_files import inspect_private_tree, read_private_file, sanitize_native_png

REPORT = 'watch-native-diagnostic.json'
STACK = 'watch-app-main-thread.txt'
SCREEN = 'watch-copy-failure.png'
TOTAL_SECONDS = 50
MAX_CALLS = 12
MAX_METADATA = 2 * 1024 * 1024
MAX_REPORT = 65536
MAX_PNG = 512 * 1024
MAX_TEXT = 262144
MAX_STACK_FILES = 4
MAX_OUTPUT_FILES = 2
SAFE_REASONS = {'installed-help-missing-required-flag', 'installed-help-unrecognized-command',
    'installed-help-does-not-advertise-on-failure', 'unreviewed-xcode-version',
    'official-tool-failed', 'official-tool-unexpected-stderr', 'diagnostic-budget-exhausted',
    'original-evidence-clock-exhausted', 'metadata-budget-exhausted', 'duration-limit', 'byte-limit',
    'owned-device-action-not-unique', 'owned-action-has-no-tests', 'unexpected-build-diagnostics-reference',
    'fixed-failed-case-not-unique', 'unknown-case-summary-format',
    'summary-case-identity-mismatch', 'too-many-png-attachments', 'screenshot-outside-command',
    'too-many-post-copy-pngs', 'ambiguous-latest-native-png', 'too-many-stack-file-candidates',
    'multiple-owned-app-stacks', 'raw-cleanup-unconfirmed'}

def need(value, reason):
    if not value:
        raise RuntimeError(reason)

class Budget:
    def __init__(self, report, job_started, runner=capture, now=time.monotonic):
        self.report, self.job_started, self.runner, self.now = report, job_started, runner, now
        self.started = now()
        self.prior = report.get('seconds_spent', 0)
        self.calls = report.get('calls', 0)
        self.bytes_read = report.get('metadata_bytes', 0)
        need(type(self.prior) in (int, float) and 0 <= self.prior <= TOTAL_SECONDS, 'invalid-budget')
        need(type(self.calls) is int and 0 <= self.calls <= MAX_CALLS, 'invalid-calls')
        need(type(self.bytes_read) is int and 0 <= self.bytes_read <= MAX_METADATA, 'invalid-metadata-budget')

    def elapsed(self):
        return self.prior + self.now() - self.started

    def run(self, command, cap=262144, *, help_output=False, guard=None):
        need(self.calls < MAX_CALLS and self.elapsed() + 8 + 20 <= TOTAL_SECONDS, 'diagnostic-budget-exhausted')
        need(0 <= self.now() - self.job_started and self.now() - self.job_started + 38 <= 2400, 'original-evidence-clock-exhausted')
        need(0 < cap <= MAX_METADATA - self.bytes_read, 'metadata-budget-exhausted')
        self.calls += 1
        self.report['calls'] = self.calls
        options = dict(seconds=8, cap=cap, cleanup_grace=10)
        if guard is not None:
            options['guard'] = guard
        try:
            result = self.runner(command, **options)
        except CaptureStopped as error:
            # A signal delivered while private-directory cleanup unwinds may
            # replace this exception. Preserve unknown owned-group cleanup now.
            self.report['diagnostic_cleanup_confirmed'] = error.cleanup_confirmed
            self.report['cancelled_signal'] = error.cancelled_signal
            raise
        need(isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes), 'invalid-tool-streams')
        need(len(result.stdout) + len(result.stderr) <= cap, 'tool-stream-cap-exceeded')
        self.bytes_read += len(result.stdout) + len(result.stderr)
        self.report['metadata_bytes'] = self.bytes_read
        need(result.returncode == 0, 'official-tool-failed')
        if help_output:
            return result.stdout + b'\n' + result.stderr
        need(not result.stderr, 'official-tool-unexpected-stderr')
        return result.stdout

    def finish(self):
        self.report['seconds_spent'] = round(self.elapsed(), 6)

def preflight(budget, report):
    need(report.get('phase') == 'pending', 'preflight-already-attempted')
    need(os.environ.get('DEVELOPER_DIR') == '/Applications/Xcode_27.app/Contents/Developer', 'wrong-developer-directory')
    need(os.environ.get('TOUCHCOLOR_WATCH_LIVE_SAMPLE') == '0', 'live-sampling-must-remain-disabled')
    report['phase'] = 'preflight-started'
    version = budget.run(['xcodebuild', '-version'], cap=4096, help_output=True)
    need(version.decode('utf-8').strip() == 'Xcode 27.0\nBuild version 27A266a', 'unreviewed-xcode-version')
    report['toolchain'] = {'version': 'Xcode 27.0', 'build': '27A266a', 'version_sha256': hashlib.sha256(version).hexdigest()}
    specifications = [
        ('xcodebuild', ['xcodebuild', '-help'], ['-collect-test-diagnostics'], None),
        ('diagnostics', ['xcrun', 'xcresulttool', 'help', 'export', 'diagnostics'],
         ['--path', '--output-path'], 'xcresulttool export diagnostics'),
        ('get-object', ['xcrun', 'xcresulttool', 'help', 'get', 'object'],
         ['--legacy', '--path', '--id', '--format', 'json'], 'xcresulttool get object'),
        ('export-object', ['xcrun', 'xcresulttool', 'help', 'export', 'object'],
         ['--legacy', '--path', '--id', '--type', '--output-path', 'file'], 'xcresulttool export object'),
    ]
    report['help'] = {}
    for name, command, flags, usage in specifications:
        report['help_operation'] = name
        raw = budget.run(command, cap=65536, help_output=True)
        text = raw.decode('utf-8')
        need(all(flag in text for flag in flags), 'installed-help-missing-required-flag')
        if usage:
            need(usage in text, 'installed-help-unrecognized-command')
        else:
            need(re.search(r'-collect-test-diagnostics[^\n]{0,180}\bon-failure\b', text) is not None,
                 'installed-help-does-not-advertise-on-failure')
        # Retain only known help lines, never arbitrary subprocess error text.
        lines = [line.strip() for line in text.splitlines()
                 if any(flag in line for flag in flags) or line.startswith('USAGE:')
                 or (name == 'diagnostics' and '--device-id' in line)]
        excerpt = '\n'.join(lines)[:4096]
        need(all(c in '\n\t' or 32 <= ord(c) < 127 for c in excerpt), 'non-ascii-help-excerpt')
        report['help'][name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'excerpt': excerpt}
        if name == 'diagnostics':
            report['help'][name]['device_filter_supported'] = re.search(r'(?<!\S)--device-id(?:[ =\n<]|$)', text) is not None
    report['phase'] = 'preflight-verified'

@contextmanager
def private_export_directory(report, temp_root):
    folder = None
    try:
        with old.private_payload_directory(temp_root) as path:
            folder = path
            report['raw_cleanup_confirmed'] = False
            yield folder
    finally:
        if folder is not None:
            report['raw_cleanup_confirmed'] = not folder.exists()
            need(report['raw_cleanup_confirmed'], 'raw-cleanup-unconfirmed')

def selected_case(budget, bound):
    invocation = old.object_json(budget, role='invocation')
    actions = [n for n, _ in old.walk(invocation) if old.kind(n) == 'ActionRecord' and
               old.value(n.get('runDestination', {}).get('targetDeviceRecord', {}), 'identifier') == bound['device']]
    need(len(actions) == 1, 'owned-device-action-not-unique')
    need('testsRef' in actions[0].get('actionResult', {}), 'owned-action-has-no-tests')
    need('diagnosticsRef' not in actions[0].get('buildResult', {}), 'unexpected-build-diagnostics-reference')
    action = actions[0]['actionResult']
    diagnostic_ref = old.reference(action, 'diagnosticsRef') if 'diagnosticsRef' in action else None
    tests = old.object_json(budget, old.reference(action, 'testsRef'), role='test-plan')
    cases = [n for n, context in old.walk(tests) if old.kind(n) in {'ActionTestMetadata', 'ActionTestSummary'}
             and old.SUITE in context and old.value(n, 'identifier') in
             {old.TEST, old.TEST + '()', old.SUITE + '/' + old.TEST, old.SUITE + '/' + old.TEST + '()'}]
    need(len(cases) == 1 and old.value(cases[0], 'testStatus') in {'Failure', 'Failed'}, 'fixed-failed-case-not-unique')
    summary = cases[0] if old.kind(cases[0]) == 'ActionTestSummary' else old.object_json(
        budget, old.reference(cases[0], 'summaryRef'), role='selected-failure-summary')
    need(old.kind(summary) == 'ActionTestSummary', 'unknown-case-summary-format')
    need(old.value(summary, 'identifier') in {old.TEST, old.TEST + '()', old.SUITE + '/' + old.TEST,
                                            old.SUITE + '/' + old.TEST + '()', old.METHOD, old.METHOD + '()'},
         'summary-case-identity-mismatch')
    return summary, diagnostic_ref

def screenshot_candidate(summary, budget, bound):
    copy_times, images = [], []
    inventory = {'png_attachments': 0, 'after_copy': 0}
    nodes = old.walk_selected_summary(summary, budget, 'attachment-discovery')
    try:
        for node, _ in nodes:
            if old.kind(node) == 'ActionTestActivitySummary' and old.value(node, 'title') == 'Tap "watch.edit.copy" Button':
                copy_times.append(old.timestamp(old.value(node, 'start')))
            if old.kind(node) != 'ActionTestAttachment' or old.value(node, 'uniformTypeIdentifier') != 'public.png':
                continue
            inventory['png_attachments'] += 1
            need(inventory['png_attachments'] <= 128, 'too-many-png-attachments')
            name = old.value(node, 'name')
            if not isinstance(name, str) or not re.search(r'screenshot|failure', name, re.I):
                continue
            moment = old.timestamp(old.value(node, 'timestamp'))
            need(bound['start'] <= moment <= bound['end'], 'screenshot-outside-command')
            images.append((moment, old.reference(node, 'payloadRef')))
    finally:
        nodes.close()
    # A pre-Copy frame must never be relabelled as the failed Copy screen.
    if len(copy_times) != 1 or not bound['start'] <= copy_times[0] <= bound['end']:
        return None, dict(inventory, state='copy-activity-time-unavailable')
    eligible = sorted(set(item for item in images if item[0] >= copy_times[0]))
    inventory['after_copy'] = len(eligible)
    if not eligible:
        return None, dict(inventory, state='no-native-png-after-copy')
    need(len(eligible) <= 8, 'too-many-post-copy-pngs')
    latest = [item for item in eligible if item[0] == eligible[-1][0]]
    need(len(latest) == 1, 'ambiguous-latest-native-png')
    return latest[0], dict(inventory, state='selected-latest-after-copy', copy_started_epoch=copy_times[0])

def extract_app_stack(raw, bound):
    text = raw.decode('utf-8')
    need(len(raw) <= MAX_TEXT and '\x00' not in text, 'invalid-stack-text')
    headers = list(re.finditer(r'^[ \t]*Process:[^\n]*$', text, re.M))
    matches = []
    for index, header in enumerate(headers):
        if not re.fullmatch(r'[ \t]*Process:\s+TouchColor\s+\[' + str(bound['pid']) + r'\][ \t]*', header.group()):
            continue
        section = text[header.start():headers[index + 1].start() if index + 1 < len(headers) else len(text)]
        # The existing parser validates executable path, device, bundle ID,
        # header time and normalized main-thread frames. Unknown formats fail.
        try:
            matches.append(old.main_thread_text(section.encode(), bound, bound['end']))
        except (ValueError, UnicodeError):
            continue
    need(len(matches) == 1, 'no-unique-owned-app-main-thread')
    return matches[0]

def collect(budget, report, bound, out, temp_root):
    need(report.get('phase') == 'preflight-verified', 'installed-help-not-verified')
    need(Path(old.BUNDLE).is_dir() and not Path(old.BUNDLE).is_symlink(), 'result-bundle-unavailable')
    report.update(phase='collecting', binding={k: bound[k] for k in ('sha', 'case', 'pid', 'device', 'start', 'end')})
    report['operation'] = 'read-owned-action-and-fixed-case'
    summary, diagnostic_ref = selected_case(budget, bound)
    device_filter = report['help']['diagnostics'].get('device_filter_supported') is True
    report['action_diagnostics'] = {'present': diagnostic_ref is not None,
                                    'reference_sha256': hashlib.sha256(diagnostic_ref.encode()).hexdigest() if diagnostic_ref else None,
                                    'device_scoped_export': device_filter,
                                    'export_scope': 'owned-watch-device' if device_filter else 'owned-result-bundle',
                                    'reference_selects_export_bytes': False}
    screenshot, inventory = screenshot_candidate(summary, budget, bound)
    report['screenshot'] = inventory
    if screenshot:
        report['operation'] = 'export-selected-native-png'
        moment, object_id = screenshot
        with private_export_directory(report, temp_root) as folder:
            target = folder / 'payload.png'
            budget.run([sys.executable, str(Path(__file__).resolve()), '--export-png', object_id, str(target)], cap=8192)
            original = old.read(target, MAX_PNG)
            clean = sanitize_native_png(original)
            need(not (out / SCREEN).exists(), 'screenshot-output-already-exists')
            (out / SCREEN).write_bytes(clean.data)
            report['screenshot'].update(state='extracted', file=SCREEN, timestamp=moment,
                source_sha256=hashlib.sha256(original).hexdigest(), sha256=hashlib.sha256(clean.data).hexdigest(),
                width=clean.width, height=clean.height, bytes=len(clean.data),
                scope='Latest native PNG retained after Copy in this failed case; not a color-accuracy proof.')
    if not diagnostic_ref:
        report.update(phase='complete', evidence='action-diagnostics-reference-missing')
        return
    with private_export_directory(report, temp_root) as folder:
        # Prefer a device filter only when installed help advertises it. If
        # absent, the official export is still limited to this owned bundle;
        # final payload ownership checks remain exact and raw files stay private.
        # Periodic directory checks stop the official exporter on a breach;
        # they are not a kernel quota or a bound on native XCTest collection.
        report['operation'] = 'export-owned-result-diagnostics'
        def guard():
            try:
                inspect_private_tree(folder)
            except RuntimeError as error:
                # The official producer may add a file during a metadata-only
                # sweep. Retry this transient view at the next capture tick;
                # final inspection after producer exit must be fully stable.
                if str(error) != 'tree_changed':
                    raise
        selector = bound['device'] if device_filter else 'owned-bundle'
        budget.run([sys.executable, str(Path(__file__).resolve()), '--export-diagnostics', selector, str(folder)],
                   cap=8192, guard=guard)
        tree = inspect_private_tree(folder)
        report['action_diagnostics'].update(files=len(tree.files), bytes=tree.total_bytes, export_complete=True)
        candidates = []
        for item in tree.files:
            name = Path(item.relative_path).name
            if re.search(r'sysdiagnose|logarchive|xctrunner|testmanagerd|WatchUITests|Runner', name, re.I):
                continue
            if re.search(r'spindump|stack|hang|sample', name, re.I) and name.lower().endswith(('.txt', '.spin', '.spindump', '.hang', '.sample')):
                candidates.append(item)
        need(len(candidates) <= MAX_STACK_FILES, 'too-many-stack-file-candidates')
        report['action_diagnostics']['stack_file_candidates'] = len(candidates)
        report['operation'] = 'read-bounded-stack-candidates'
        extracted = []
        for item in candidates:
            if item.size_bytes > MAX_TEXT:
                report['action_diagnostics']['oversize_stack_files'] = report['action_diagnostics'].get('oversize_stack_files', 0) + 1
                continue
            payload = read_private_file(folder, item.relative_path, max_bytes=MAX_TEXT)
            try:
                excerpt = extract_app_stack(payload.data, bound)
            except (RuntimeError, ValueError, UnicodeError):
                continue
            extracted.append((excerpt, payload.sha256, payload.size_bytes))
        need(len(extracted) <= 1, 'multiple-owned-app-stacks')
        if extracted:
            excerpt, digest, length = extracted[0]
            need(not (out / STACK).exists(), 'stack-output-already-exists')
            (out / STACK).write_text(excerpt + '\n')
            report['app_stack'] = {'state': 'extracted', 'file': STACK, 'source_sha256': digest,
                                   'source_bytes': length, 'retained_bytes': len((excerpt + '\n').encode()),
                                   'thread': 'com.apple.main-thread', 'line_limit': 256, 'byte_limit': 12288}
        else:
            report['app_stack'] = {'state': 'not-extracted', 'reason': 'no-supported-owned-app-main-thread'}
    report.update(phase='complete', raw_cleanup_confirmed=True, qualified=False)
    report['operation'] = 'finished'

def bounded_export(kind, first, destination):
    root = Path(os.environ['RUNNER_TEMP']).resolve()
    path = Path(destination)
    need(path.is_absolute(), 'export-path-not-absolute')
    if kind == 'png':
        need(old.ID.fullmatch(first) is not None and path.name == 'payload.png' and not path.exists() and not path.is_symlink(), 'invalid-png-export')
        folder = path.parent
        limit = MAX_PNG
        command = ['xcrun', 'xcresulttool', 'export', 'object', '--legacy', '--path', old.BUNDLE,
                   '--id', first, '--type', 'file', '--output-path', str(path)]
    else:
        need(first == 'owned-bundle' or re.fullmatch(r'[0-9A-F-]{36}', first) is not None, 'invalid-diagnostic-device')
        folder = path
        limit = 8 * 1024 * 1024
        command = ['xcrun', 'xcresulttool', 'export', 'diagnostics', '--path', old.BUNDLE,
                   '--output-path', str(folder)]
        if first != 'owned-bundle':
            command += ['--device-id', first]
    need(folder.parent.resolve() == root and folder.name.startswith('watch-stack-') and not folder.is_symlink(), 'unsafe-export-directory')
    need(folder.stat().st_mode & 0o077 == 0, 'export-directory-not-private')
    if kind != 'png':
        need(not inspect_private_tree(folder).files, 'diagnostic-directory-not-empty')
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execvp(command[0], command)

def phase_main(phase):
    out = Path(os.environ['RUNNER_TEMP']) / 'watch-focused-evidence'
    report = json.loads(old.read(out / REPORT, MAX_REPORT))
    clock = json.loads(old.read(out / 'report.json', 65536))['started_monotonic']
    budget = Budget(report, clock)
    code = 0
    try:
        if phase == 'preflight':
            preflight(budget, report)
        else:
            runtime = json.loads(old.read('build/watch-runtime/runtime.json', 262144))
            if runtime.get('result') == 'passed':
                report.update(phase='not-applicable', evidence='selected-case-did-not-fail', qualified=False)
            else:
                bound = old.binding(runtime, json.loads(old.read(out / 'source-before.json', 32768)),
                    json.loads(old.read(out / 'source-after.json', 32768)), os.environ['GITHUB_SHA'], diagnostic_mode='on-failure')
                collect(budget, report, bound, out, Path(os.environ['RUNNER_TEMP']))
    except BaseException as error:
        # No raw exception text, diagnostic paths or environment values enter
        # the public result. An unavailable diagnostic never changes test state.
        report.update(phase='unavailable', evidence='no-complete-native-diagnostic-extraction',
                      error_type=type(error).__name__, qualified=False)
        if str(error) in SAFE_REASONS:
            report['reason'] = str(error)
        if isinstance(error, CaptureStopped):
            report['diagnostic_cleanup_confirmed'] = error.cleanup_confirmed
            report['cancelled_signal'] = error.cancelled_signal
        code = 1 if phase == 'preflight' or report.get('raw_cleanup_confirmed') is False or isinstance(error, (CaptureStopped, old.DiagnosticCancelled, KeyboardInterrupt, SystemExit)) else 0
    finally:
        budget.finish()
        if budget.elapsed() > TOTAL_SECONDS or not 0 <= budget.now() - clock <= 2400:
            report.update(phase='unavailable', reason='diagnostic-budget-exhausted', qualified=False)
            code = 1
        safe_files = [p for p in (out / STACK, out / SCREEN) if p.exists()]
        need(len(safe_files) <= MAX_OUTPUT_FILES and all(p.is_file() and not p.is_symlink() for p in safe_files), 'unsafe-retained-output')
        data = (json.dumps(report, indent=2) + '\n').encode()
        need(len(data) <= MAX_REPORT, 'diagnostic-report-too-large')
        (out / REPORT).write_bytes(data)
    return code

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--phase', choices=['preflight', 'collect'])
    group.add_argument('--export-png', nargs=2)
    group.add_argument('--export-diagnostics', nargs=2)
    args = parser.parse_args()
    if args.export_png:
        bounded_export('png', *args.export_png)
    elif args.export_diagnostics:
        bounded_export('diagnostics', *args.export_diagnostics)
    else:
        with old.cancellation_guard():
            return phase_main(args.phase)
    return 1

if __name__ == '__main__':
    sys.exit(main())
