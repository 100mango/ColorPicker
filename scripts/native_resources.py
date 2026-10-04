"""Tiny bounded phase evidence; never enumerates processes or reads result contents."""
import datetime
import os
from pathlib import Path
import stat
import subprocess
import time
from bounded_process import run_captured


def result_sizes(build, maximum_entries=4000, maximum_seconds=0.15):
    started = time.monotonic()
    entries = total = 0
    partial = False
    folders = []
    # Only the known owned result bundles, never an arbitrary VM tree.
    for name in ('vision-tests.xcresult', 'vision-ui.xcresult', 'watch-tests.xcresult', 'watch-ui.xcresult', 'tv-tests.xcresult'):
        path = Path(build) / name
        if path.is_dir() and not path.is_symlink(): folders.append(path)
    pending = list(folders)
    while pending and not partial:
        directory = pending.pop()
        try:
            with os.scandir(directory) as items:
                for item in items:
                    entries += 1
                    if entries > maximum_entries or time.monotonic() - started > maximum_seconds:
                        partial = True; break
                    info = item.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode): pending.append(Path(item.path))
                    elif stat.S_ISREG(info.st_mode): total += info.st_size
        except OSError:
            partial = True
    return {'bundles': [p.name for p in folders], 'bytes_observed': total,
            'entries_observed': min(entries, maximum_entries), 'partial': partial}


def snapshot(label, build=Path('build'), command_runner=run_captured):
    started = time.monotonic()
    result = {'label': label[:180], 'wall_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'monotonic_seconds': started}
    try:
        disk = os.statvfs(build)
        result['disk'] = {'available_bytes': disk.f_bavail * disk.f_frsize,
                          'total_bytes': disk.f_blocks * disk.f_frsize}
        result['results'] = result_sizes(build)
    except OSError as error: result['filesystem_error'] = type(error).__name__
    for key, command in [('memory_swap', ['sysctl', 'hw.memsize', 'vm.swapusage']), ('pages', ['vm_stat'])]:
        try:
            value = command_runner(command, timeout=3, text=True)
            result[key] = {'exit': value.returncode, 'text': value.stdout[:1600]}
        except Exception as error:
            result[key] = {'error': type(error).__name__}
            if isinstance(error, subprocess.TimeoutExpired) and not getattr(error, 'cleanup_confirmed', False):
                result['cleanup_unconfirmed'] = True; break
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result


def require_responsive(value):
    """Do not start a costly suite after basic local 3s probes already failed."""
    if value.get('cleanup_unconfirmed'):
        raise RuntimeError('Native resource prerequisite: previous process cleanup unconfirmed')
    for key in ('memory_swap', 'pages'):
        probe = value.get(key, {})
        if probe.get('exit') != 0 or probe.get('error'):
            raise RuntimeError('Native resource prerequisite: '+key+' probe was not responsive')
    return True
