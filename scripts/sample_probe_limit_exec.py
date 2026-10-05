"""Internal, source-only probe launcher; never installed or used by CI yet.

The parent starts this trusted source with -I -S in a new session. It applies
limits before executing a producer. The short acknowledgement uses a separate
bounded pipe; absence or mismatch is failure. No preexec_fn or shell is used.
"""
import json
import os
import resource
import signal
import stat
import sys


def main():
    # This entry point is internal. No sampling command or PID is constructed.
    try:
        ack_fd, file_cap = int(sys.argv[1]), int(sys.argv[2])
        identity = json.loads(sys.argv[3])
        argv = sys.argv[4:]
        if not argv or not 1 <= file_cap <= 64_000:
            return 125
        if not os.path.isabs(argv[0]) or os.path.realpath(argv[0]) != argv[0]:
            return 125
        info = os.stat(argv[0], follow_symlinks=False)
        actual = [info.st_dev, info.st_ino, info.st_size,
                  info.st_mtime_ns, info.st_ctime_ns]
        if not stat.S_ISREG(info.st_mode) or actual != identity:
            return 125
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_cap, file_cap))
        if resource.getrlimit(resource.RLIMIT_FSIZE) != (file_cap, file_cap):
            return 125
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.write(ack_fd, b'LIMITS_READY\n')
        os.close(ack_fd)
        os.execve(argv[0], argv, dict(os.environ))
    except (OSError, ValueError, IndexError, TypeError):
        return 125
    return 125


if __name__ == '__main__':
    raise SystemExit(main())
