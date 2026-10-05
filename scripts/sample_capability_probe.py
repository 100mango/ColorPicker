"""Source-only, fail-closed Apple sample capability inspection proposal.

NOT integrated with Watch diagnostics or any workflow. Only the opt-in CLI's
fixed, targetless /usr/bin/sample help invocation is implemented. No arbitrary
PID, application name, flag adapter, live sampling or stack parser is exposed.
The generic bounded runner is an internal primitive tested with synthetic
producers; it is not a sample command builder.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

FILE_CAP = 64_000
PIPE_CAP = 32_000
REPORT_CAP = 32_000
HELP_TEXT_CAP = 12_000
TOTAL_RETAINED_CAP = 128_000
MAX_SECONDS = 5.0
CLEANUP_SECONDS = 1.0
ACK = b'LIMITS_READY\n'
TOOL_OWNERS = frozenset((0, os.getuid()))


class Unavailable(Exception):
    """Fixed reason codes only; do not expose paths or raw exception text."""


def checked_file(path, owner=None, executable=False, trusted_code=False):
    """Reject aliases at every component, special files, and unsafe tool modes.

    Hold the returned descriptor for identity/provenance; callers must close it.
    Ancestor directories are checked without following symlinks. An executable
    or trusted source additionally requires safe ownership, ancestors and modes.
    Trusted source need not have an executable bit; its interpreter executes it.
    """
    raw_path = os.fspath(path)
    path = Path(raw_path)
    if (not path.is_absolute() or '..' in path.parts or
            raw_path != os.path.normpath(raw_path)):
        raise Unavailable('unsafe_path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            if executable or trusted_code:
                parent = os.fstat(child)
                if parent.st_uid not in TOOL_OWNERS or parent.st_mode & 0o022:
                    os.close(child)
                    raise Unavailable('unsafe_executable_ancestor')
            os.close(fd)
            fd = child
        result = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=fd)
        info = os.fstat(result)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                (owner is not None and info.st_uid != owner) or
                ((executable or trusted_code) and
                 (info.st_uid not in TOOL_OWNERS or
                  info.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID))) or
                (executable and not info.st_mode & 0o111)):
            os.close(result)
            raise Unavailable('unsafe_file_identity')
        return result
    except OSError as error:
        raise Unavailable('path_identity_unavailable') from error
    finally:
        os.close(fd)


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def checked_directory(path):
    """Require an existing owned private directory; never silently resolve aliases."""
    raw_path = os.fspath(path)
    path = Path(raw_path)
    if (not path.is_absolute() or '..' in path.parts or
            raw_path != os.path.normpath(raw_path)):
        raise Unavailable('unsafe_work_directory')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Unavailable('work_directory_not_private')
        return path
    except OSError as error:
        raise Unavailable('work_directory_identity_unavailable') from error
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Result:
    output: bytes
    returncode: int
    limit_ready: bool
    timed_out: bool
    truncated: bool
    cleanup_confirmed: bool
    identity_confirmed: bool = True


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_owned_unreaped_group(process):
    """Never signal after reaping: the owned leader reserves its PID/PGID.

    The runner deliberately never calls poll/wait before this function. A leader
    that exited while descendants retain pipes therefore still reserves its ID.
    Once reaped we only observe group absence; uncertainty is latched as failure.
    No descendants may escape this owned group in an approved adapter/fixture.
    """
    if process.returncode is not None or process.pid == os.getpgrp():
        return False
    try:
        if os.getpgid(process.pid) != process.pid:
            return False
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            if sig == signal.SIGTERM:
                time.sleep(0.1)
        process.wait(timeout=CLEANUP_SECONDS / 2)
        deadline = time.monotonic() + CLEANUP_SECONDS / 2
        while _group_exists(process.pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        return not _group_exists(process.pid)
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_bounded(argv, directory, *, timeout=MAX_SECONDS, pipe_cap=PIPE_CAP,
                file_cap=FILE_CAP, interpreter=None):
    """Internal synthetic-testable executor; output is transient, never logged.

    Hard+soft RLIMIT_FSIZE is applied and acknowledged before producer exec.
    It bounds each regular file, not pipes or the number of files. One bounded
    combined pipe and a separate bounded acknowledgement pipe have independent
    readers. Exactly-at-cap output is conservatively incomplete. No communicate,
    shell, preexec_fn, poll/reap-before-signalling, or inherited credential env.
    """
    if (type(timeout) not in (int, float) or not math.isfinite(timeout) or
            not 0 < timeout <= MAX_SECONDS or type(pipe_cap) is not int or
            not 1 <= pipe_cap <= PIPE_CAP or type(file_cap) is not int or
            not 1 <= file_cap <= FILE_CAP or not argv or
            not all(isinstance(arg, str) and '\0' not in arg for arg in argv)):
        raise ValueError('Invalid bounded producer request')
    directory = checked_directory(directory)
    interpreter = str(interpreter or sys.executable)
    launcher = str(Path(__file__).with_name('sample_probe_limit_exec.py').absolute())
    held = []
    process = None
    reader = None
    output = bytearray()
    acknowledgement = bytearray()
    truncated = timed_out = cleanup = False
    identities_confirmed = True
    ack_read = ack_write = None
    try:
        for path, execute in ((argv[0], True), (interpreter, True), (launcher, False)):
            held.append(checked_file(path, executable=execute,
                                     owner=None if execute else os.getuid(),
                                     trusted_code=not execute))
        before_identities = [identity(os.fstat(fd)) for fd in held]
        producer_identity = before_identities[0]
        ack_read, ack_write = os.pipe()
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(
            [interpreter, '-I', '-S', launcher, str(ack_write), str(file_cap),
             json.dumps(producer_identity, separators=(',', ':')), *argv],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=directory, start_new_session=True, pass_fds=(ack_write,),
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                 'HOME': str(directory), 'TMPDIR': str(directory)})
        os.close(ack_write)
        ack_write = None
        reader = selectors.DefaultSelector()
        for descriptor, label in ((process.stdout.fileno(), 'output'), (ack_read, 'ack')):
            os.set_blocking(descriptor, False)
            reader.register(descriptor, selectors.EVENT_READ, label)
        while reader.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in reader.select(min(0.05, remaining)):
                target, cap = ((output, pipe_cap) if key.data == 'output'
                               else (acknowledgement, len(ACK)))
                try:
                    chunk = os.read(key.fd, min(4096, cap - len(target) + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    reader.unregister(key.fd)
                    continue
                remaining_bytes = cap - len(target)
                target.extend(chunk[:remaining_bytes])
                if len(chunk) > remaining_bytes:
                    truncated = True
                    break
            if truncated:
                break
        truncated = truncated or len(output) >= pipe_cap
    finally:
        active_error = sys.exc_info()[1]
        if process is not None:
            cleanup = _stop_owned_unreaped_group(process)
            if active_error is not None:
                active_error.cleanup_confirmed = cleanup
            # Holding descriptors prevents confusion with replacements; compare
            # both original objects and fresh no-follow path resolutions.
            for index, (path, execute) in enumerate(((argv[0], True),
                    (interpreter, True), (launcher, False))):
                check = None
                try:
                    check = checked_file(path, executable=execute,
                                         owner=None if execute else os.getuid(),
                                         trusted_code=not execute)
                    identities_confirmed = identities_confirmed and (
                        identity(os.fstat(held[index])) == before_identities[index] ==
                        identity(os.fstat(check)))
                except (Unavailable, OSError):
                    identities_confirmed = False
                finally:
                    if check is not None:
                        os.close(check)
        if reader is not None:
            reader.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        for descriptor in (*held, ack_read, ack_write):
            if descriptor is not None:
                os.close(descriptor)
    return Result(bytes(output), process.returncode if process.returncode is not None else 125,
                  bytes(acknowledgement) == ACK, timed_out, truncated, cleanup, identities_confirmed)


def capability_report(result=None, reason=None):
    """Retain only complete bounded installed help; never a capture or stack.

    A usage response is recognized by its first nonblank line. Its entire exact
    UTF-8 text must satisfy all gates; prefixes and oversized/unknown responses
    are omitted explicitly. Recognition does not validate a syntax/access adapter.
    """
    report = {
        'schema': 2, 'scope': 'owned_fixture_capability_only',
        'status': 'unavailable', 'reason': reason or 'noninteractive_contract_unverified',
        'captureAttempted': False, 'targetCreated': False,
        'syntax': 'not_validated_for_invocation', 'noninteractiveAccess': 'unverified',
        'stackFormat': 'unobserved', 'stackExtraction': 'not_implemented',
        'watchCause': 'not_assessed', 'retainedBudgetBytes': TOTAL_RETAINED_CAP,
        'omissions': ['raw_help', 'raw_stacks', 'process_inventory', 'paths',
                      'binary_images', 'environment', 'unowned_processes'],
    }
    if result is not None:
        complete = (result.limit_ready and result.cleanup_confirmed and
                    result.identity_confirmed and result.returncode >= 0 and
                    not result.timed_out and not result.truncated)
        help_info = {
            'bytesRead': len(result.output), 'complete': complete,
            'sha256': hashlib.sha256(result.output).hexdigest() if complete else None,
            'returncode': result.returncode, 'limitReady': result.limit_ready,
            'cleanupConfirmed': result.cleanup_confirmed,
            'identityConfirmed': result.identity_confirmed,
            'timedOut': result.timed_out, 'truncated': result.truncated,
            'textStatus': 'omitted_incomplete', 'retainedTextBytes': 0,
            'textComplete': False, 'textCapBytes': HELP_TEXT_CAP,
            'usageResponseObserved': False,
        }
        report['help'] = help_info
        text = None
        if not complete:
            report['reason'] = 'help_incomplete_or_cleanup_unconfirmed'
        elif len(result.output) > HELP_TEXT_CAP:
            report['reason'] = 'installed_help_oversized'
            help_info['textStatus'] = 'omitted_oversized'
        else:
            try:
                text = result.output.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                report['reason'] = 'installed_help_invalid_utf8'
                help_info['textStatus'] = 'omitted_invalid_utf8'
            if text is not None:
                first_line = next((line for line in text.splitlines() if line.strip()), '')
                usage = re.match(r'^\s*usage:\s+(?:/usr/bin/)?sample(?:\s|$)',
                                 first_line, flags=re.IGNORECASE)
                safe_controls = all(char.isprintable() or char in '\t\n\r'
                                    for char in text)
                safe_controls = safe_controls and '\r' not in text.replace('\r\n', '')
                help_info['usageResponseObserved'] = bool(usage)
                if not usage:
                    report['reason'] = 'installed_help_unrecognized'
                    help_info['textStatus'] = 'omitted_unknown_response'
                elif not safe_controls:
                    report['reason'] = 'installed_help_unsupported_controls'
                    help_info['textStatus'] = 'omitted_unsupported_controls'
                else:
                    help_info.update(text=text, textComplete=True,
                                     retainedTextBytes=len(result.output),
                                     textStatus='retained_complete')
                    report['omissions'].remove('raw_help')
        # Bound actual serialized bytes, including Unicode JSON escape expansion.
        # Omit the entire help text if it cannot fit; never trim a purported whole.
        if 'text' in help_info and len(json.dumps(report, sort_keys=True,
                indent=2).encode('ascii')) + 1 > REPORT_CAP:
            del help_info['text']
            help_info.update(textComplete=False, retainedTextBytes=0,
                             textStatus='omitted_report_bound')
            report['reason'] = 'installed_help_report_bound'
            report['omissions'].insert(0, 'raw_help')
    encoded = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode('ascii')
    if len(encoded) > REPORT_CAP:
        raise ValueError('Capability report exceeds retained cap')
    return encoded


def inspect_installed_help(directory):
    if sys.platform != 'darwin':
        return capability_report(reason='darwin_required')
    try:
        fd = checked_file('/usr/bin/sample', owner=0, executable=True)
        os.close(fd)
        # Zero arguments: no guessed help flag, PID, name, -wait, or sampling flag.
        result = run_bounded(['/usr/bin/sample'], directory)
        return capability_report(result)
    except (Unavailable, OSError) as error:
        return capability_report(reason=('cleanup_unconfirmed'
            if getattr(error, 'cleanup_confirmed', True) is False
            else 'tool_or_path_identity_unavailable'))


def main():
    # Explicit opt-in only. A future live capture requires a separately reviewed
    # source adapter; there is deliberately no override or arbitrary PID option.
    if len(sys.argv) != 3 or sys.argv[1] != '--inspect-installed-help':
        sys.stderr.write('Source-only proposal. Opt-in: --inspect-installed-help PRIVATE_DIRECTORY\n')
        return 2
    sys.stdout.buffer.write(inspect_installed_help(sys.argv[2]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
