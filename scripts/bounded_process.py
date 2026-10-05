"""Bounded cleanup for test-owned process groups, without daemons or OS changes."""
import os
import signal
import subprocess
import time


def group_exists(group_id):
    """A reaped leader is not proof that its descendants exited."""
    try:
        os.killpg(group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Unknown liveness is never successful cleanup.


def stop_group(process, grace=10, checkpoint=None):
    # Every caller creates the child with start_new_session=True. Its original
    # PID is the owned PGID even when the session leader has already exited.
    if process.pid == os.getpgrp():
        raise ValueError('Refusing to signal the caller process group')
    start = time.monotonic()
    for stop_signal in (signal.SIGTERM, signal.SIGKILL):
        process.poll()  # Reap the owned leader when possible.
        if not group_exists(process.pid):
            return process.poll() is not None
        if checkpoint:
            checkpoint('sending ' + stop_signal.name)
        try:
            os.killpg(process.pid, stop_signal)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            process.poll()
            if not group_exists(process.pid):
                return process.poll() is not None
            time.sleep(min(0.025, max(0, deadline-time.monotonic())))
    confirmed = process.poll() is not None and not group_exists(process.pid)
    if checkpoint:
        checkpoint('exit confirmed' if confirmed else 'exit unconfirmed after %.3fs' % (time.monotonic() - start))
    return confirmed


def run_captured(command, timeout, *, text=True, stderr=subprocess.PIPE, checkpoint=None):
    """Bound command and whole owned-group cleanup, including orphan descendants."""
    # Enabled only inside a source-bound native workflow controller. Portable
    # tests and unrelated callers preserve their original explicit deadlines.
    from job_budget import enabled_budget, fail_record
    budget = enabled_budget()
    if budget is not None:
        try:
            timeout = budget.admit(' '.join(str(v) for v in command[:3]), timeout,
                                   minimum=min(timeout, 1), cleanup=20)
        except Exception as error:
            fail_record(error, phase=budget.phase)
            raise
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr,
                               text=text, start_new_session=True)
    try:
        output, errors = process.communicate(timeout=timeout)
        if not stop_group(process, checkpoint=checkpoint):
            error = subprocess.TimeoutExpired(command, timeout)
            error.cleanup_confirmed = False
            raise error
    except subprocess.TimeoutExpired as error:
        if not hasattr(error, 'cleanup_confirmed'):
            error.cleanup_confirmed = stop_group(process, checkpoint=checkpoint)
        if budget is not None:
            fail_record('Bounded command timeout: '+' '.join(str(v) for v in command[:3]),
                        phase=budget.phase, cleanup_unconfirmed=not getattr(error, 'cleanup_confirmed', False))
        raise
    except BaseException as error:
        confirmed = stop_group(process, checkpoint=checkpoint)
        error.cleanup_confirmed = confirmed
        if budget is not None:
            fail_record('Bounded command interrupted', phase=budget.phase, cleanup_unconfirmed=not confirmed)
        raise
    finally:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    return subprocess.CompletedProcess(command, process.returncode, output, errors)


def check_output(command, timeout, *, text=True):
    result = run_captured(command, timeout, text=text)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
    return result.stdout
