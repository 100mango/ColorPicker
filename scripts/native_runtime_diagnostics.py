"""Small, read-only runtime evidence for app versus remote-service failures.

No process arguments, environment, complete crash reports, or system settings are
collected. Only named test/app services and selected crash fields are retained.
"""
import datetime
import json
from pathlib import Path
import re
import subprocess
import time

from bounded_process import run_captured

RELEVANT = re.compile(r'TouchColor|PhotosUI|photospicker|PhotosPicker|AXUI|Accessibility|accessibility|SurfBoard|backboardd|testmanagerd|xctest|CoreSimulator', re.I)
MAX_REPORT_BYTES = 512_000
MAX_SNAPSHOTS = 20


def process_rows(text):
    rows = []
    for line in text.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) != 5 or not fields[0].isdigit():
            continue
        name = Path(fields[4]).name
        if RELEVANT.search(name):
            rows.append({'pid': int(fields[0]), 'parent_pid': int(fields[1]),
                         'state': fields[2][:12], 'rss_kib': int(fields[3]), 'name': name[:100]})
    return rows[:48]


def crash_summary(path):
    # IPS has a one-line metadata object followed by the actual report object.
    with path.open('rb') as source:
        raw = source.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        return {'file': path.name, 'omitted': 'report exceeds bounded parser size'}
    decoder = json.JSONDecoder()
    text = raw.decode('utf-8')
    header, end = decoder.raw_decode(text.lstrip())
    rest = text.lstrip()[end:].lstrip()
    report = decoder.raw_decode(rest)[0] if rest else header
    result = {'file': path.name}
    for key in ('procName', 'pid', 'parentProc', 'parentPid', 'captureTime'):
        value = report.get(key)
        if isinstance(value, (int, float, bool)): result[key] = value
        elif isinstance(value, str): result[key] = value[:120]
    # Avoid arbitrary diagnostic messages, paths, registers and application data.
    for key, fields in [('exception', ('type', 'signal', 'subtype', 'codes')),
                        ('termination', ('namespace', 'code', 'indicator', 'byProc', 'byPid'))]:
        item = report.get(key, {})
        if isinstance(item, dict):
            result[key] = {field: str(item[field])[:160] for field in fields if field in item}
    return result


def recent_crashes(roots, since):
    candidates = []
    for root in roots:
        if not root.is_dir(): continue
        # Only known simulator/test-service IPS reports under these exact roots.
        for path in root.glob('*.ips'):
            if not path.is_symlink() and RELEVANT.search(path.name):
                info = path.stat()
                if info.st_mtime >= since: candidates.append((info.st_mtime, path))
    reports = []
    for _, path in sorted(candidates, key=lambda item: item[0], reverse=True)[:4]:
        try: reports.append(crash_summary(path))
        except (OSError, ValueError, UnicodeError) as error:
            reports.append({'file': path.name, 'parser_error': type(error).__name__})
    return reports


def snapshot(label, device, since, command_runner=run_captured):
    started = time.monotonic()
    result = {'label': label[:180], 'wall_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'monotonic_seconds': started}
    for key, command in [('processes', ['ps', '-axo', 'pid,ppid,stat,rss,comm']),
                         ('memory', ['sysctl', 'hw.memsize', 'vm.swapusage'])]:
        try:
            command_result = command_runner(command, timeout=3, text=True)
            result[key] = process_rows(command_result.stdout) if key == 'processes' else command_result.stdout[:500]
            result[key + '_exit'] = command_result.returncode
        except Exception as error:
            result[key + '_error'] = type(error).__name__
            if isinstance(error, subprocess.TimeoutExpired) and not getattr(error, 'cleanup_confirmed', False):
                result['cleanup_unconfirmed'] = True
                return result
    roots = [Path.home() / 'Library/Logs/DiagnosticReports']
    if device:
        roots.append(Path.home() / 'Library/Developer/CoreSimulator/Devices' / device / 'data/Library/Logs/CrashReporter')
    result['crash_roots_present'] = [root.is_dir() for root in roots]
    result['recent_crashes'] = recent_crashes(roots, since)
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result
