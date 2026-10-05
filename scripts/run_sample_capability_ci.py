"""One-off diagnostic receipts; never a live-capture adapter or app qualification."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import sample_capability_probe as probe

BASE = 'a6ea406d51e38319b76d19a5a5417b72cec857f4'
HELPER_TREE = '33a5529befe2d8968b2f10d51676a5e9634ebe93'
FROZEN = {
    'SAMPLE-CAPABILITY-PROPOSAL.md': '8288dcc14b09df8109557b5a5559f068837d3f15b1ffd21365ff5a16ebe1c8a8',
    'scripts/sample_capability_probe.py': '67866db0503fce67b79ef4269e46795b5df612ae854a1147ee3066f4675da20b',
    'scripts/sample_probe_limit_exec.py': 'd13a76016d2a632856da80ed8c6fbce41831e2c22d5860e90efb686ba31a6bba',
    'scripts/test_sample_capability_probe.py': '83038b579ee00b84b68d5c8a6da5e0ad666905532ed97edb0088302bbc58ac3b',
}
WORKFLOW = '.github/workflows/sample-capability-probe.yml'
ADDITIONS = {WORKFLOW, 'scripts/run_sample_capability_ci.py',
             'scripts/test_sample_capability_workflow.py'}
CAPS = {'normal.json': 8000, 'optimized.json': 8000,
        'capability.json': 32000, 'receipt.json': 12000}
TOTAL_CAP = 128000
TOOL_CAP = 32000000

# Only these fixed source-owned operations are executable by the child entry.
OPERATION_SCRIPT = Path(__file__).resolve()
DEADLINES = {'normal': 20.0, 'optimized': 20.0, 'help': 12.0}
DEFER_GRACE = 8.0  # Covers helper MAX_SECONDS + TERM/KILL/reap allowance.
FINAL_GRACE = 8.0  # Graceful cancellation only; never hard-kill the wrapper.


class OperationCancelled(KeyboardInterrupt):
    pass


def _perform_tests():
    # Never retain tracebacks, process output, or filesystem inventories.
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromName('test_sample_capability_probe').run(result)
    return {'testsRun': result.testsRun, 'passed': result.wasSuccessful(),
            'failures': [test.id() for test, _ in result.failures],
            'errors': [test.id() for test, _ in result.errors],
            'skipped': len(result.skipped), 'optimized': sys.flags.optimize}


def _perform_help(directory):
    # The admitted CLI entry point, unchanged, with its exact two arguments.
    sys.argv = [str(ROOT / 'scripts/sample_capability_probe.py'),
                '--inspect-installed-help', str(directory)]
    return probe.main()


def child_operation(mode, directory, output):
    """Defer cancellation until the helper has finished its own group cleanup.

    Handlers set a pending flag during the *entire* run_bounded call, including
    Popen construction and finally. No OS signal mask changes are inherited by
    producers. A deadline or cancellation always yields unavailable/failure.
    """
    require(mode in DEADLINES and (sys.flags.optimize > 0) == (mode == 'optimized'),
            'operation_mode_unavailable')
    probe.checked_directory(str(directory))
    probe.checked_directory(str(output.parent))
    original = probe.run_bounded
    pending = None
    critical = False
    finishing = False
    cleanup_confirmed = True

    def cancel(signum, _frame):
        nonlocal pending
        pending = pending or ('operation_deadline' if signum == signal.SIGALRM
                              else 'operation_cancelled')
        if not critical and not finishing:
            raise OperationCancelled()

    def finish_owned_cleanup(*args, **kwargs):
        nonlocal critical, cleanup_confirmed
        critical = True
        try:
            result = original(*args, **kwargs)
            cleanup_confirmed = cleanup_confirmed and result.cleanup_confirmed
            return result
        except BaseException as error:
            cleanup_confirmed = cleanup_confirmed and getattr(error, 'cleanup_confirmed', True)
            raise
        finally:
            critical = False
            if pending:
                raise OperationCancelled()

    for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, cancel)
    probe.run_bounded = finish_owned_cleanup
    code = 1
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii', newline='') as stream:
        signal.setitimer(signal.ITIMER_REAL, DEADLINES[mode])
        try:
            if mode == 'help':
                with contextlib.redirect_stdout(stream):
                    code = _perform_help(directory)
            else:
                summary = _perform_tests()
                stream.write(encode_receipt(summary, CAPS[mode + '.json']).decode('ascii'))
                code = 0 if summary['passed'] and summary['testsRun'] == 27 and not summary['skipped'] else 1
        except OperationCancelled:
            code = 124
        finally:
            finishing = True
            signal.setitimer(signal.ITIMER_REAL, 0)
            probe.run_bounded = original
            if pending:
                stream.seek(0)
                stream.truncate()
                if mode == 'help':
                    body = probe.capability_report(reason=pending)
                else:
                    body = encode_receipt({'status': 'unavailable', 'passed': False,
                        'firstFailure': pending, 'ownedCleanupConfirmed': cleanup_confirmed}, 8000)
                stream.write(body.decode('ascii'))
                code = 124
    return code


def run_owned_operation(mode, directory, output):
    """One fixed child, graceful deadlines/cancellation, no nested-producer kill.

    A wrapper that unexpectedly exceeds its deadline plus deferred-cleanup grace
    gets one TERM and one final bounded grace. Still-running means unconfirmed;
    it is never hard-killed or promoted to success, and no next operation runs.
    """
    require(mode in DEADLINES, 'operation_mode_unavailable')
    cancelled = None
    process = None
    previous = {}

    def cancel(signum, _frame):
        nonlocal cancelled
        cancelled = cancelled or signum

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, cancel)
    try:
        flags = ['-O'] if mode == 'optimized' else []
        process = subprocess.Popen([sys.executable, '-I', '-S', '-B', *flags,
            str(OPERATION_SCRIPT), '--owned-operation', mode, str(directory), str(output)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(directory), 'TMPDIR': str(directory),
                 'LANG': 'C', 'LC_ALL': 'C'})
        deadline = time.monotonic() + DEADLINES[mode] + DEFER_GRACE
        signalled = False
        overrun = False
        while True:
            if cancelled and not signalled:
                process.send_signal(cancelled)
                signalled = True
                deadline = min(deadline, time.monotonic() + DEFER_GRACE)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if overrun:
                    return {'returncode': None, 'cancelled': bool(cancelled),
                            'overrun': True, 'childExited': False}
                overrun = True
                process.send_signal(signal.SIGTERM)
                signalled = True
                deadline = time.monotonic() + FINAL_GRACE
                continue
            try:
                code = process.wait(timeout=min(0.05, remaining))
                return {'returncode': code, 'cancelled': bool(cancelled),
                        'overrun': overrun, 'childExited': True}
            except subprocess.TimeoutExpired:
                pass
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


class Closed(Exception):
    pass


def require(value, reason):
    if not value:
        raise Closed(reason)


def digest(path, *, executable=False):
    """Hash one predeclared trusted file with before/after descriptor identity."""
    descriptor = probe.checked_file(str(path), executable=executable,
                                    trusted_code=not executable)
    try:
        before = os.fstat(descriptor)
        require(before.st_size <= TOOL_CAP, 'tool_identity_size_unavailable')
        value = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            require(chunk, 'tool_identity_read_unavailable')
            value.update(chunk)
            remaining -= len(chunk)
        require(not os.read(descriptor, 1) and
                probe.identity(before) == probe.identity(os.fstat(descriptor)),
                'tool_identity_changed')
        return {'sha256': value.hexdigest(), 'bytes': before.st_size,
                'identity': probe.identity(before)}
    finally:
        os.close(descriptor)


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            check=True, timeout=2)
    require(len(result.stdout) <= 64000, 'source_output_bound')
    return result.stdout.decode('utf-8').strip()


def source_guard():
    e = os.environ
    require(e.get('GITHUB_EVENT_NAME') == 'push' and
            e.get('GITHUB_REPOSITORY') == '100mango/ColorPicker' and
            e.get('GITHUB_REF') == 'refs/heads/codex/sample-capability-probe' and
            e.get('GITHUB_RUN_ATTEMPT') == '1', 'event_identity_unavailable')
    sha = e.get('GITHUB_SHA', '')
    require(len(sha) == 40 and sha == e.get('GITHUB_WORKFLOW_SHA') == git('rev-parse', 'HEAD'),
            'source_identity_unavailable')
    require(git('show', '-s', '--format=%P', 'HEAD') == BASE, 'public_parent_changed')
    require(not git('status', '--porcelain=v1', '--untracked-files=all'), 'source_not_clean')
    event = json.loads(Path(e['GITHUB_EVENT_PATH']).read_text())
    require(event.get('created') is False and event.get('forced') is False and
            event.get('deleted') is False and event.get('before') == BASE and
            event.get('after') == sha, 'not_admitted_base_to_diagnostic_push')
    changed = set(git('diff', '--name-only', BASE, 'HEAD').splitlines())
    require(changed == set(FROZEN) | ADDITIONS, 'source_scope_changed')
    for name, expected in FROZEN.items():
        require(digest(ROOT / name)['sha256'] == expected, 'admitted_helper_changed')
    return {'commit': sha, 'tree': git('rev-parse', 'HEAD^{tree}'), 'parent': BASE,
            'admittedHelperTree': HELPER_TREE, 'ref': e['GITHUB_REF'],
            'workflowSha': e['GITHUB_WORKFLOW_SHA'],
            'workflowSha256': digest(ROOT / WORKFLOW)['sha256'],
            'runId': e['GITHUB_RUN_ID'], 'attempt': 1}


def encode_receipt(value, cap):
    body = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('ascii')
    require(len(body) <= cap, 'receipt_bound_exceeded')
    return body


def artifact_guard(directory):
    require(set(p.name for p in directory.iterdir()) <= set(CAPS), 'artifact_name_rejected')
    total = 0
    for path in directory.iterdir():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == os.getuid() and not info.st_mode & 0o077 and
                info.st_size <= CAPS[path.name], 'artifact_identity_or_bound_rejected')
        total += info.st_size
    require(total <= TOTAL_CAP, 'artifact_total_bound_exceeded')
    return total


def main():
    # Tests and receipts use private physical directories. Never chmod existing
    # paths, copy interpreter binaries, bypass identity checks, or try fallbacks.
    os.umask(0o077)
    evidence = work = None
    first_failure = None
    child_cleanup_uncertain = False
    receipt = {'schema': 1, 'liveCapture': 'unavailable', 'captureAttempted': False,
               'toolInvocation': ['/usr/bin/sample'], 'sampleCliAttempts': 0,
               'cleanup': 'not_started', 'errors': []}
    try:
        receipt['source'] = source_guard()
        require(sys.platform == 'darwin', 'darwin_required')
        require(str(Path(sys.executable)) == os.path.realpath(sys.executable),
                'interpreter_not_canonical')
        temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
        evidence = Path(tempfile.mkdtemp(prefix='touchcolor-sample-evidence-', dir=temp))
        work = Path(tempfile.mkdtemp(prefix='touchcolor-sample-work-', dir=temp))
        probe.checked_directory(str(evidence))
        probe.checked_directory(str(work))
        receipt['interpreter'] = {'path': sys.executable, 'version': sys.version.split()[0],
                                  **digest(Path(sys.executable), executable=True)}
        receipt['sample'] = {'path': '/usr/bin/sample',
                             **digest(Path('/usr/bin/sample'), executable=True)}
        for mode in ('normal', 'optimized'):
            result = run_owned_operation(mode, work, evidence / (mode + '.json'))
            child_cleanup_uncertain = not result['childExited']
            require(not result['overrun'], 'child_deadline_cleanup_unconfirmed')
            require(not result['cancelled'], 'operation_cancelled')
            require(result['returncode'] == 0, mode + '_tests_failed')
        # Exactly one admitted phase-0 CLI entry point; no retry after cancellation.
        receipt['sampleCliAttempts'] = 1
        result = run_owned_operation('help', work, evidence / 'capability.json')
        child_cleanup_uncertain = not result['childExited']
        require(not result['overrun'], 'child_deadline_cleanup_unconfirmed')
        require(not result['cancelled'], 'operation_cancelled')
        require(result['returncode'] == 0, 'phase_zero_cli_failed')
        artifact_guard(evidence)
        report = json.loads((evidence / 'capability.json').read_bytes())
        require(report.get('captureAttempted') is False and report.get('targetCreated') is False
                and report.get('status') == 'unavailable', 'unexpected_capture_claim')
        receipt['helpOutcome'] = report['reason']
        receipt['sampleIdentityAfter'] = digest(Path('/usr/bin/sample'), executable=True)
        receipt['interpreterIdentityAfter'] = digest(Path(sys.executable), executable=True)
        require(receipt['sampleIdentityAfter'] == {k: receipt['sample'][k]
                for k in ('sha256', 'bytes', 'identity')} and
                receipt['interpreterIdentityAfter'] == {k: receipt['interpreter'][k]
                for k in ('sha256', 'bytes', 'identity')}, 'tool_identity_changed')
        require(report.get('help', {}).get('complete') is True and
                report['help'].get('textComplete') is True, 'installed_help_unavailable')
    except (Closed, probe.Unavailable) as error:
        first_failure = first_failure or str(error)
    except subprocess.TimeoutExpired:
        child_cleanup_uncertain = True
        first_failure = first_failure or 'child_deadline_cleanup_unconfirmed'
    except Exception:
        first_failure = first_failure or 'diagnostic_unavailable'
    finally:
        try:
            if work is not None and not child_cleanup_uncertain:
                shutil.rmtree(work)
                require(not work.exists(), 'private_work_cleanup_unconfirmed')
            receipt['cleanup'] = ('child_cleanup_unconfirmed' if child_cleanup_uncertain
                                  else 'private_files_removed')
        except Exception:
            receipt['cleanup'] = 'unconfirmed'
            receipt['errors'].append('private_work_cleanup_unconfirmed')
            first_failure = first_failure or 'private_work_cleanup_unconfirmed'
        try:
            require(source_guard() == receipt.get('source'), 'source_not_clean_after')
        except Exception:
            receipt['errors'].append('source_not_clean_after')
            first_failure = first_failure or 'source_not_clean_after'
        receipt['firstFailure'] = first_failure
        if evidence is not None and not child_cleanup_uncertain:
            try:
                (evidence / 'receipt.json').write_bytes(encode_receipt(receipt, CAPS['receipt.json']))
                artifact_guard(evidence)
                with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                    output.write('artifact_ready=true\nartifact_path=' + str(evidence) + '\n')
            except Exception:
                first_failure = first_failure or 'evidence_guard_failed'
        print('Targetless sample capability diagnostic: ' + (first_failure or 'completed'))
    return 1 if first_failure else 0


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--owned-operation':
        raise SystemExit(child_operation(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])))
    require(len(sys.argv) == 1, 'unsupported_operation')
    raise SystemExit(main())
