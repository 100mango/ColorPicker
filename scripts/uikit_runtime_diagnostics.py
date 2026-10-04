"""One bounded, read-only Files-service snapshot for the recorded UIKit simulator.

No host process inventory, raw crash report, process arguments or personal path
is emitted. Missing service evidence remains an explicit observation gap.
"""
import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from bounded_process import run_captured
from native_runtime_diagnostics import crash_summary

FAMILIES = {'iPadMini', 'iPadLarge', 'iPhoneCompact', 'iPhoneLarge'}
SERVICE = re.compile(r'(?:^|:)(com\.apple\.(?:DocumentManager[\w.-]*|fileprovider[\w.-]*)|com\.mango\.touchColor(?:\.[\w.-]+)?)', re.I)
REPORT = re.compile(r'^(?:TouchColor|DocumentManager|DocumentPicker|FileProvider)', re.I)
MAX_OUTPUT_BYTES = 32 * 1024
FRAME = 'UIKIT_RUNTIME_DIAGNOSTICS:'


def validate_identity(value, family):
    if family not in FAMILIES or value.get('family') != family:
        raise ValueError('Invalid owned simulator family')
    identifier = value.get('udid', '')
    if str(uuid.UUID(identifier)).upper() != identifier:
        raise ValueError('Invalid owned simulator identifier')
    if value.get('runtime') != 'com.apple.CoreSimulator.SimRuntime.iOS-27-0':
        raise ValueError('Unexpected simulator runtime')
    started = value.get('started')
    if isinstance(started, bool) or not isinstance(started, (int, float)) or not 0 < started <= time.time():
        raise ValueError('Invalid simulator start time')
    return value


def service_rows(output):
    rows = []
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not (fields[0].isdigit() or fields[0] == '-'):
            continue
        match = SERVICE.search(fields[2])
        if match is None:
            continue
        rows.append({'pid': int(fields[0]) if fields[0].isdigit() else None,
                     'exit_status': fields[1][:12], 'service': match.group(1)[:100]})
        if len(rows) == 48:
            break
    return rows


def owned_crashes(home, identity):
    root = Path(home) / 'Library/Developer/CoreSimulator/Devices' / identity['udid'] / 'data/Library/Logs/CrashReporter'
    device_root = Path(home) / 'Library/Developer/CoreSimulator/Devices' / identity['udid']
    scoped_parts = [device_root, device_root / 'data', device_root / 'data/Library',
                    device_root / 'data/Library/Logs', root]
    if not root.is_dir() or any(part.is_symlink() for part in scoped_parts):
        return {'owned_crash_root_present': False, 'reports': []}
    candidates = []
    for path in root.glob('*.ips'):
        if path.is_symlink() or not REPORT.match(path.name):
            continue
        modified = path.stat().st_mtime
        if modified >= identity['started']:
            candidates.append((modified, path))
    reports = []
    for modified, path in sorted(candidates, reverse=True)[:4]:
        try:
            parsed = crash_summary(path)
            item = {'modified_at': modified}
            for key in ('procName', 'pid', 'parentProc', 'parentPid', 'captureTime', 'omitted'):
                if key in parsed:
                    value = parsed[key]
                    item[key] = '<path omitted>' if isinstance(value, str) and ('/' in value or '\\' in value) else value
            for key, fields in [('exception', ('type', 'signal')), ('termination', ('namespace', 'code', 'byProc', 'byPid'))]:
                item[key] = {field: value for field, value in parsed.get(key, {}).items()
                             if field in fields and '/' not in str(value) and '\\' not in str(value)}
            reports.append(item)
        except (OSError, ValueError, UnicodeError, TypeError, AttributeError) as error:
            reports.append({'modified_at': modified, 'parser_error': type(error).__name__})
    return {'owned_crash_root_present': True, 'reports': reports}


def collect(identity, home, runner=run_captured):
    result = {'family': identity['family'], 'deviceId': identity['udid'], 'runtime': identity['runtime'],
              'phase': 'after-functional-failure', 'wall_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'simulator_commands_completed': False}
    try:
        command = ['xcrun', 'simctl', 'spawn', identity['udid'], 'launchctl', 'list']
        process = runner(command, timeout=3, text=True)
        result['service_query_exit'] = process.returncode
        result['services'] = service_rows(process.stdout) if process.returncode == 0 else []
        if process.returncode != 0:
            return result
    except Exception as error:
        result['service_query_error'] = type(error).__name__
        result['host_client_cleanup_confirmed'] = getattr(error, 'cleanup_confirmed', None)
        # Reaping simctl's host group does not prove its simulator-side command
        # exited. The pending marker must block later simulator mutation.
        return result
    result['simulator_commands_completed'] = True
    result.update(owned_crashes(home, identity))
    return result


def framed_record(value):
    # Reserve 128 bytes for the Actions timestamp/line framing as well.
    output = FRAME + json.dumps(value, separators=(',', ':'), sort_keys=True) + '\n'
    if len(output.encode('utf-8')) + 128 > MAX_OUTPUT_BYTES:
        output = FRAME + json.dumps({'family': value['family'], 'deviceId': value['deviceId'],
            'omitted': 'metadata exceeded the bounded record size'}) + '\n'
    if len(output.encode('utf-8')) + 128 > MAX_OUTPUT_BYTES:
        raise ValueError('Runtime diagnostic framing exceeds limit')
    return output


def main():
    family = sys.argv[1]
    if family not in FAMILIES:
        raise ValueError('Invalid simulator family')
    path = Path('build') / (family + '-simulator.json')
    identity = validate_identity(json.loads(path.read_text()), family)
    pending = Path('build') / (family + '-runtime-command-uncertain')
    # An earlier unknown command cannot be cleared by a later successful query.
    # Exclusive creation also refuses an existing linked marker before spawning.
    try:
        with pending.open('x') as marker:
            marker.write('Simulator diagnostic exit has not been observed. Do not mutate this simulator.\n')
    except FileExistsError:
        raise SystemExit('An earlier simulator command has no confirmed exit; diagnostic retry is blocked')
    result = collect(identity, Path.home())
    print(framed_record(result), end='', flush=True)
    if result.get('simulator_commands_completed') is not True:
        raise SystemExit('Simulator diagnostic completion is uncertain; later simulator actions stay blocked')
    pending.unlink()
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('simulator_safe=true\n')


if __name__ == '__main__':
    main()
