"""One advisory live-process console mirror of the in-memory Mini receipt.

No capture/runtime imports, subprocesses, file reads, retries, waits or writes
other than one nonblocking atomic stdout-pipe attempt. The original receipt is
primary; memory fields do not establish persistence or durable delivery.
Missing/mismatched/invalid fields stay unknown, never successful.
"""
import json
import os
import re
import stat

PREFIX = 'MINI_PASSIVE_STATUS '
MAX_LINE_BYTES = 512  # Includes prefix and newline; Darwin's PIPE_BUF floor.
REF = 'refs/heads/codex/mini-passive-compatibility'
WORKFLOW = '100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@' + REF


def _boolean(value):
    return value if type(value) is bool else None


def _exit(value):
    return value if type(value) is int and -255 <= value <= 255 else None


def _context(env):
    sha, run, attempt = (env.get(name) for name in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': REF,
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': WORKFLOW,
        'GITHUB_JOB': 'mini-passive-compatibility', 'GITHUB_ACTIONS': 'true',
        'RUNNER_OS': 'macOS', 'RUNNER_ENVIRONMENT': 'github-hosted'}
    if (not all(env.get(key) == value for key, value in expected.items()) or
            not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha) or
            env.get('GITHUB_WORKFLOW_SHA') != sha or
            not all(isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,19}', value)
                    for value in (run, attempt))):
        return None
    return sha, run, attempt


def _receipt(value, identity):
    if value is None:
        return 'missing', {}
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1 or
            value.get('purpose') != 'isolated-compatibility-only'):
        return 'invalid', {}
    sha, run, attempt = identity
    if (value.get('source_sha') != sha or value.get('workflow_sha') != sha or
            value.get('run_id') != run or value.get('run_attempt') != attempt or
            not isinstance(value.get('device'), dict) or value['device'].get('family') != 'iPadMini'):
        return 'mismatch', {}
    return 'bound', value


def _process(value):
    value = value if isinstance(value, dict) else {}
    state = value.get('state')
    return [state if state in ('attempted', 'owned') else None,
            _exit(value.get('exit')), _boolean(value.get('host_cleanup_confirmed'))]


def _reason(value):
    raw = value.get('failure')
    reasons = {'CaptureFailed: absolute-deadline': 'absolute-deadline',
        'CaptureFailed: Pipe read returned after its absolute deadline': 'late-read',
        'Pipe read returned after its absolute deadline': 'late-read',
        'CaptureFailed: Unsupported installed help': 'help-options',
        'CaptureFailed: Help completion uncertain': 'help-exit',
        'CaptureFailed: Collector exited during observation': 'stream-exit',
        'CaptureFailed: cancelled': 'cancelled',
        'Cleanup/persistence exceeded shared deadline': 'cleanup-deadline'}
    if isinstance(raw, str):
        return reasons.get(raw, 'other')  # Never echo arbitrary error text.
    cancelled = value.get('cancelled_signal')
    return 'cancelled' if type(cancelled) is int and 1 <= cancelled <= 64 else None


def status_line(receipt, env=os.environ):
    identity = _context(env)
    binding, value = _receipt(receipt, identity) if identity is not None else ('invalid-context', {})
    sha, run, attempt = identity if identity is not None else (None, None, None)
    processes = value.get('processes')
    processes = processes if isinstance(processes, dict) else {}
    help_row, stream_row = _process(processes.get('help')), _process(processes.get('collector'))
    phase = ('stream' if stream_row[0] is not None else 'help'
             if 'collector' not in processes and help_row[0] is not None else None)
    state = value.get('status')
    value = {'v': 1, 'sha': sha, 'run': run, 'try': attempt, 'receipt': binding,
        'phase': phase, 'reason': _reason(value), 'help': help_row, 'stream': stream_row,
        'cleanup': _boolean(value.get('host_cleanup_confirmed')),
        'state': state if state in ('not_started', 'failed_or_incomplete', 'bounded_observation_finished') else None,
        'source': 'memory', 'durability': 'unconfirmed',
        'reader': 'unconfirmed' if value.get('reader_completion') == 'unconfirmed' else None,
        'warmup': False if value.get('warmup_admitted') is False else None, 'delivery': 'best_effort'}
    encoded = (PREFIX + json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    return encoded if len(encoded) <= MAX_LINE_BYTES else None


def _write_nonblocking(raw):
    previous = None
    try:
        if (not stat.S_ISFIFO(os.fstat(1).st_mode) or len(raw) > MAX_LINE_BYTES or
                len(raw) > os.fpathconf(1, 'PC_PIPE_BUF')):
            return False
        previous = os.get_blocking(1)
        if previous:
            os.set_blocking(1, False)
        return os.write(1, raw) == len(raw)
    except (OSError, ValueError):
        return False
    finally:
        if previous:
            try:
                os.set_blocking(1, True)
            except OSError:
                pass


def emit_summary(receipt, env=os.environ):
    """Attempt once from memory; never retry, persist, or alter the receipt."""
    result = {'attempts': 1, 'omitted': 1, 'record_bytes': 0}
    try:
        line = status_line(receipt, env)
        if line is not None:
            result['record_bytes'] = len(line)
            if _write_nonblocking(line):
                result['omitted'] = 0
    except Exception:
        pass  # An advisory mirror cannot change capture/cleanup acceptance.
    return result
