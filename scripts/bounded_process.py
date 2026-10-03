"""Bounded cleanup for test-owned process groups, without daemons or OS changes."""
import os
import signal
import subprocess
import time


def stop_group(process, grace=10, checkpoint=None):
    start = time.monotonic()
    for stop_signal in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            return True
        if checkpoint:
            checkpoint('sending ' + stop_signal.name)
        try:
            os.killpg(process.pid, stop_signal)
        except ProcessLookupError:
            pass
        if checkpoint:
            checkpoint('bounded reap after ' + stop_signal.name)
        try:
            process.wait(timeout=grace)
            return True
        except subprocess.TimeoutExpired:
            continue
    confirmed = process.poll() is not None
    if checkpoint:
        checkpoint('exit confirmed' if confirmed else 'exit unconfirmed after %.3fs' % (time.monotonic() - start))
    return confirmed


def run_captured(command, timeout, *, text=True, stderr=subprocess.PIPE, checkpoint=None):
    """Like subprocess.run(capture_output=True), with bounded post-kill reaping.

    Python's convenience run/check_output wait without a second timeout while
    reaping a killed child. This wrapper keeps that cleanup explicitly bounded.
    A timeout is always a failed attempt, even if output was partly written.
    """
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr,
                               text=text, start_new_session=True)
    try:
        output, errors = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        error.cleanup_confirmed = stop_group(process, checkpoint=checkpoint)
        raise
    finally:
        # communicate's selector no longer owns these read handles. Do not call
        # communicate again just to drain descendants that may still hold a pipe.
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    return subprocess.CompletedProcess(command, process.returncode, output, errors)


def check_output(command, timeout, *, text=True):
    result = run_captured(command, timeout, text=text)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
    return result.stdout
