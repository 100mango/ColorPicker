"""Local proposal: Mac-only held-direct-child transport; no Popen or implicit reap.

The caller supplies already-admitted absolute work and cleanup deadlines. This
module is not installed into frozen shared scripts and does not qualify a job.
"""
import ctypes
from dataclasses import dataclass
import errno
import locale
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

CAPACITY = 1024


def close_local_once(closers, primary=None):
    """Close only local descriptors once; never replace a primary target error."""
    errors = []
    for close in closers:
        try:
            close()
        except BaseException as error:
            errors.append(error)
    if errors:
        if primary is not None:
            primary.local_close_errors = (*getattr(primary, 'local_close_errors', ()), *errors)
        else:
            errors[0].local_close_errors = (*getattr(errors[0], 'local_close_errors', ()), *errors[1:])
            raise errors[0]


class CancellationScope:
    """Main-thread flags only: no asynchronous exception in spawn handoff."""
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)

    def __init__(self, cancelled):
        self.external = cancelled
        self.requested = False
        self.handlers = {}
        self.mask = None
        self.cleanup_complete = False
        self.owned_receipt = None

    def receive(self, signum, frame):
        self.requested = True

    def cancelled(self):
        return self.requested or self.external()

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
            raise ValueError('Owned CLI must be single-threaded on its main thread')
        try:
            for value in self.signals:
                self.handlers[value] = signal.getsignal(value)
                signal.signal(value, self.receive)
            self.mask = signal.pthread_sigmask(signal.SIG_UNBLOCK, self.signals)
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(self, error_type, error, traceback):
        if self.mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, self.mask)
        for value, handler in self.handlers.items():
            signal.signal(value, handler)
        if error_type is None and self.cancelled():
            cancelled = InterruptedError('Controller cancelled before return')
            cancelled.cleanup_confirmed = self.cleanup_complete
            if self.owned_receipt is not None:
                cancelled.owned_receipt = self.owned_receipt
            raise cancelled


def reject_inheritable_fds():
    """Bounded scan of this controller's own descriptors, never other processes."""
    entries = os.listdir('/dev/fd')
    if len(entries) > CAPACITY or any(not item.isdecimal() for item in entries):
        raise ValueError('Unbounded or unknown own descriptor inventory')
    for text in entries:
        fd = int(text)
        if fd < 3:
            continue
        try:
            inherited = os.get_inheritable(fd)
        except OSError as error:
            if error.errno == errno.EBADF:
                continue  # The inventory directory's own temporary fd closed.
            raise
        if inherited:
            raise ValueError('Unapproved inheritable descriptor')


class OwnershipUnknown(RuntimeError):
    def __init__(self, operation, original=None):
        super().__init__('Owned process state unknown: ' + operation)
        self.operation = operation
        self.original = original
        self.errno = getattr(original, 'errno', None)
        self.cleanup_confirmed = False


class PublicMac:
    """Public SDK C boundary loaded from the exact controller-built library."""
    def __init__(self, library):
        if os.uname().sysname != 'Darwin':
            raise ValueError('Actual public boundary requires Darwin')
        self.library = ctypes.CDLL(str(Path(library).resolve()), use_errno=True)
        self.function = self.library.tc_owned_group_members
        self.function.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_int32),
                                  ctypes.c_uint32, ctypes.POINTER(ctypes.c_int32)]
        self.function.restype = ctypes.c_int
        self.policy = self.library.tc_default_reaper_policy
        self.policy.argtypes = []
        self.policy.restype = ctypes.c_int
        if self.policy() != 1:
            raise ValueError('Unknown SIGCHLD reaper policy')

    def members(self, pid):
        values = (ctypes.c_int32 * CAPACITY)()
        error = ctypes.c_int32()
        size = self.function(pid, values, CAPACITY, ctypes.byref(error))
        if error.value:
            raise OSError(error.value, 'proc_listpids')
        if size <= 0 or size >= CAPACITY * 4 or size % 4:
            raise ValueError('Incomplete bounded group list')
        return list(values[:size // 4])

    @staticmethod
    def lease(pid):
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)

    @staticmethod
    def send(pid, value):
        os.killpg(pid, value)

    @staticmethod
    def reap(pid):
        return os.waitpid(pid, os.WNOHANG)


@dataclass
class Owned:
    pid: int
    backend: object
    deadline: float
    clock: object = time.monotonic
    sleep: object = time.sleep
    state: str = 'HELD_LIVE'
    terminal: object = None
    fault: object = None
    returncode: object = None
    last_operation: str = 'spawn'
    singleton_ready: bool = False
    lease_calls: int = 0
    group_calls: int = 0
    reap_calls: int = 0

    def receipt(self):
        return {'pid': self.pid, 'owned_group_cleanup_confirmed': self.state == 'REAPED' and self.returncode is not None,
                'lease_calls': self.lease_calls, 'group_calls': self.group_calls,
                'reap_calls': self.reap_calls, 'state': self.state,
                'last_operation': self.last_operation,
                'unknown_operation': self.fault.operation if self.fault is not None else None}

    def unknown(self, operation, original=None):
        if self.fault is None:
            self.fault = OwnershipUnknown(operation, original)
            self.state = 'UNKNOWN'
        raise self.fault

    def guard(self):
        if self.fault is not None:
            raise self.fault
        if self.state == 'REAPED':
            raise ValueError('Released child cannot be queried again')
        if self.clock() >= self.deadline:
            self.unknown('ownership_deadline')

    def call(self, operation, function, *args):
        self.guard()
        self.last_operation = operation
        try:
            value = function(*args)
        except BaseException as error:
            self.unknown(operation, error)
        if self.clock() >= self.deadline:
            self.unknown(operation + '_returned_late')
        return value

    def lease(self):
        self.guard()
        self.lease_calls += 1
        value = self.call('waitid_wnowait', self.backend.lease, self.pid)
        if value is None or value.si_pid == 0:
            if self.terminal is not None:
                self.unknown('terminal_lease_disappeared')
            return False
        observed = (value.si_code, value.si_status)
        if value.si_pid != self.pid or value.si_code not in (os.CLD_EXITED, os.CLD_KILLED, os.CLD_DUMPED):
            self.unknown('unexpected_child_status')
        if value.si_code == os.CLD_EXITED and not 0 <= value.si_status <= 255:
            self.unknown('unexpected_exit_status')
        if value.si_code != os.CLD_EXITED and not 0 < value.si_status < signal.NSIG:
            self.unknown('unexpected_signal_status')
        if self.terminal is not None and observed != self.terminal:
            self.unknown('terminal_lease_changed')
        self.terminal = observed
        self.state = 'HELD_TERMINAL'
        return True

    def observe(self):
        self.singleton_ready = False
        terminal = self.lease()
        self.group_calls += 1
        members = self.call('proc_listpids', self.backend.members, self.pid)
        if (not isinstance(members, list) or not 0 < len(members) < CAPACITY or
            any(type(pid) is not int or pid <= 0 for pid in members) or
            len(set(members)) != len(members) or members.count(self.pid) != 1):
            self.unknown('invalid_group_members')
        self.singleton_ready = terminal and members == [self.pid]
        return self.singleton_ready

    def finish(self):
        # Caller just obtained a complete singleton group observation.
        if self.fault is not None:
            raise self.fault
        if not self.singleton_ready:
            raise ValueError('A complete held-terminal singleton was not observed')
        self.singleton_ready = False
        if not self.lease():
            self.unknown('final_lease_not_terminal')
        self.guard()
        self.last_operation = 'waitpid_reap'
        # Release before interpreting any result: there can never be a retry.
        self.state = 'REAPED'
        self.reap_calls += 1
        try:
            pid, status = self.backend.reap(self.pid)
        except BaseException as error:
            self.unknown('waitpid_reap', error)
        if pid != self.pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
            self.unknown('unexpected_reap_result')
        code = os.waitstatus_to_exitcode(status)
        expected = self.terminal[1] if self.terminal[0] == os.CLD_EXITED else -self.terminal[1]
        if code != expected:
            self.unknown('reap_status_changed')
        if self.clock() >= self.deadline:
            self.unknown('reap_returned_late')
        self.returncode = code
        return code

    def stop(self, cleanup_deadline, grace=10):
        if self.fault is not None:
            raise self.fault
        if self.state == 'REAPED':
            return True
        if cleanup_deadline != self.deadline or not 0 < grace <= 10:
            raise ValueError('Cleanup cannot extend the admitted deadline or grace')
        for value in (signal.SIGTERM, signal.SIGKILL):
            if self.observe():
                self.finish()
                return True
            self.call('killpg_' + value.name, self.backend.send, self.pid, value)
            phase_end = min(self.deadline, self.clock() + grace)
            while self.clock() < phase_end:
                if self.observe():
                    self.finish()
                    return True
                self.sleep(min(.02, max(0, phase_end - self.clock())))
        self.unknown('cleanup_deadline')


def spawn(command, environ=None, *, check_dispatch, stderr=subprocess.PIPE):
    """One public spawn. No fallback, Popen object, or child query on failure."""
    if not command or not os.path.isabs(command[0]):
        raise ValueError('Resolve the exact executable before spawn')
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ValueError('Non-default SIGCHLD policy')
    for fd in (0, 1, 2):
        os.fstat(fd)  # Closed standard descriptors cannot alias our pipe actions.
    readers, writers = [], []
    created = False
    try:
        if stderr not in (subprocess.PIPE, subprocess.STDOUT):
            raise ValueError('Only explicit captured stderr routes are admitted')
        for _ in range(1 if stderr == subprocess.STDOUT else 2):
            read, write = os.pipe()
            readers.append(read)
            writers.append(write)
            os.set_inheritable(read, False)
            os.set_inheritable(write, False)
            os.set_blocking(read, False)
        actions = [(os.POSIX_SPAWN_DUP2, writers[0], 1),
                   (os.POSIX_SPAWN_DUP2, writers[0] if stderr == subprocess.STDOUT else writers[1], 2)]
        actions += [(os.POSIX_SPAWN_CLOSE, fd) for fd in readers + writers]
        environment = dict(os.environ if environ is None else environ)
        reject_inheritable_fds()
        check_dispatch()  # After pipe/FD/environment setup, immediately at dispatch.
        pid = os.posix_spawn(command[0], command, environment,
                             file_actions=actions, setsid=True, setsigmask=(),
                             setsigdef=(signal.SIGINT, signal.SIGTERM, signal.SIGALRM,
                                        signal.SIGPIPE, signal.SIGCHLD))
        created = True
        # The caller adopts PID before a possibly failing local writer close.
        return pid, readers, writers
    finally:
        if not created:
            close_local_once([lambda fd=fd: os.close(fd) for fd in readers + writers],
                             sys.exc_info()[1])


def run_captured(command, *, backend, work_deadline, cleanup_deadline,
                 maximum_bytes=2_000_000, environ=None, consume=None,
                 cancelled=lambda: False, clock=time.monotonic, sleep=time.sleep,
                 text=True, stderr=subprocess.PIPE):
    with CancellationScope(cancelled) as cancellation:
        result = _run_captured(command, backend=backend, work_deadline=work_deadline,
                             cleanup_deadline=cleanup_deadline, maximum_bytes=maximum_bytes,
                             environ=environ, consume=consume, cancelled=cancellation.cancelled,
                             clock=clock, sleep=sleep, text=text, stderr=stderr)
        cancellation.cleanup_complete = True
        cancellation.owned_receipt = result.owned_receipt
        return result


def _run_captured(command, *, backend, work_deadline, cleanup_deadline,
                  maximum_bytes, environ, consume, cancelled, clock, sleep, text, stderr):
    """Prototype transport only; caller must enforce job/phase/substep admission."""
    if (not clock() < work_deadline < cleanup_deadline or
        cleanup_deadline - work_deadline > 20 or maximum_bytes <= 0):
        raise ValueError('Invalid admitted bounds')
    encoding = 'utf-8' if sys.flags.utf8_mode else locale.getencoding()
    if text and encoding.lower().replace('_', '-') != 'utf-8':
        raise ValueError('The Mac control text route requires its fixed UTF-8 locale')
    readers = []
    owned = None
    pid = None
    chunks = [bytearray(), bytearray()]
    total = 0
    selector = selectors.DefaultSelector()
    def check_dispatch():
        if cancelled():
            raise InterruptedError('Controller cancelled before dispatch')
        if clock() >= work_deadline:
            raise subprocess.TimeoutExpired(command, work_deadline)
    try:
        check_dispatch()
        pid, readers, writers = spawn(command, environ, check_dispatch=check_dispatch, stderr=stderr)
        owned = Owned(pid, backend, cleanup_deadline, clock, sleep)
        close_local_once([lambda fd=fd: os.close(fd) for fd in writers])
        for index, fd in enumerate(readers):
            selector.register(fd, selectors.EVENT_READ, index)
        while True:
            if cancelled():
                raise InterruptedError('Controller cancelled')
            if clock() >= work_deadline:
                raise subprocess.TimeoutExpired(command, work_deadline)
            for key, _ in selector.select(min(.02, max(0, work_deadline - clock()))):
                raw = os.read(key.fd, min(65536, maximum_bytes - total))
                if not raw:
                    selector.unregister(key.fd)
                    continue
                total += len(raw)
                if total >= maximum_bytes:
                    raise ValueError('Captured output exceeds fixed bound')
                chunks[key.data].extend(raw)
                if consume is not None:
                    consume(key.data, raw)
            singleton = owned.observe()
            if clock() >= work_deadline:
                raise subprocess.TimeoutExpired(command, work_deadline)
            if singleton and not selector.get_map():
                code = owned.finish()
                if clock() >= work_deadline:
                    raise subprocess.TimeoutExpired(command, work_deadline)
                output = bytes(chunks[0])
                errors = bytes(chunks[1]) if stderr == subprocess.PIPE else None
                if text:
                    output = output.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                    errors = errors.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n') if errors is not None else None
                result = subprocess.CompletedProcess(command, code, output, errors)
                result.owned_receipt = owned.receipt()
                return result
    except BaseException as primary:
        observed_errors = (primary, *getattr(primary, 'local_close_errors', ()))
        denied = next((error for error in observed_errors if isinstance(error, PermissionError) or
                       getattr(error, 'errno', None) in (errno.EPERM, errno.EACCES)), None)
        if owned is not None and denied is not None:
            try:
                owned.unknown('transport_permission_denied', denied)
            except OwnershipUnknown:
                pass  # Preserve the primary exception; never re-enter cleanup.
        # No cleanup re-entry after an observation/permission/unknown failure.
        if owned is None:
            primary.cleanup_confirmed = False
        elif owned.fault is not None:
            primary.cleanup_confirmed = False
            primary.ownership_fault = owned.fault
        else:
            try:
                primary.cleanup_confirmed = owned.stop(cleanup_deadline)
            except BaseException as cleanup_error:
                primary.cleanup_confirmed = False
                primary.ownership_fault = cleanup_error
        if owned is not None:
            primary.owned_receipt = owned.receipt()
        elif pid is not None:
            primary.owned_receipt = {'pid': pid, 'state': 'UNKNOWN', 'owned_group_cleanup_confirmed': False,
                                     'lease_calls': 0, 'group_calls': 0, 'reap_calls': 0,
                                     'unknown_operation': 'owner_handoff_failed'}
        raise
    finally:
        try:
            close_local_once([selector.close] + [lambda fd=fd: os.close(fd) for fd in readers],
                             sys.exc_info()[1])
        except BaseException as close_error:
            if owned is not None:
                close_error.owned_receipt = owned.receipt()
            raise


class Session:
    """One controller's fail-closed command admission latch; no implicit retry."""
    def __init__(self, backend):
        self.backend = backend
        self.fault = None

    def run(self, command, **arguments):
        if self.fault is not None:
            raise self.fault
        try:
            return run_captured(command, backend=self.backend, **arguments)
        except BaseException as error:
            self.fault = error
            raise
