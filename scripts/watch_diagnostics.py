"""Bounded, observational Watch diagnostics. This module never drives the UI."""
import json
import math
import re

MAX_PROCESSES = 16
MAX_EVENTS_PER_PROCESS = 96
MAX_EVENT_JSON_BYTES = 500
MAX_LIFECYCLE_JSON_BYTES = 850_000
MAX_FRAME_RECORDS = 96
MAX_FRAMES_PER_CASE = 48
MAX_FRAME_JSON_BYTES = 4096
MAX_FRAME_REPORT_BYTES = 405_000
_EVENT = re.compile(r'TouchColor\[(\d+):[^\]]+\].*'
                    r'\[com\.mango\.touchColor\.WatchDiagnostics:editor\] '
                    r'WATCH_EDITOR (\w+) case=([A-Za-z0-9_.]{1,120}) ')
_ROW = re.compile(r'watch\.(?:editor|photo|count|transfer\.open|privacy|color\.\d+)\Z')


def log_lookback(source_job_minutes):
    if type(source_job_minutes) is not int or not 1 <= source_job_minutes <= 60:
        raise ValueError('Watch diagnostic requires a bounded source-owned job duration')
    return str(source_job_minutes + 2) + 'm'


def _bounded_line(line):
    # Bound the actual JSON encoding, including escape expansion.
    line = line[:MAX_EVENT_JSON_BYTES]
    low, high = 0, len(line)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(line[:middle]).encode()) <= MAX_EVENT_JSON_BYTES:
            low = middle
        else:
            high = middle - 1
    return line[:low]


def summarize_editor_lifecycle(output):
    groups = {}
    matched = unparsed = overflow = 0
    for line in output.splitlines():
        if 'WATCH_EDITOR' not in line:
            continue
        matched += 1
        match = _EVENT.search(line)
        if not match:
            unparsed += 1
            continue
        pid, kind, case = match.groups()
        key = (case, pid)
        if key not in groups:
            if len(groups) == MAX_PROCESSES:
                overflow += 1
                continue
            groups[key] = {'case': case, 'pid': int(pid), 'matched_events': 0, 'app_dropped_events': 0, 'entries': []}
        group = groups[key]
        group['matched_events'] += 1
        dropped = re.search(r' dropped=(\d+)', line)
        if dropped:
            group['app_dropped_events'] = max(group['app_dropped_events'], int(dropped.group(1)))
        lifecycle = kind in ('appear', 'disappear')
        entries = group['entries']
        if len(entries) == MAX_EVENTS_PER_PROCESS:
            if not lifecycle:
                continue
            # Preserve decisive late lifecycle events even for an older or
            # unexpectedly noisy app, independently of repetitive records.
            remove = next((i for i, (important, _) in enumerate(entries) if not important), 0)
            entries.pop(remove)
        entries.append((lifecycle, _bounded_line(line)))
    result = {'matched_events': matched, 'unparsed_events': unparsed,
              'overflow_process_events': overflow, 'processes': []}
    for group in groups.values():
        entries = group.pop('entries')
        group['events'] = [line for _, line in entries]
        group['omitted_events'] = group['matched_events'] - len(entries)
        result['processes'].append(group)
    result['truncated'] = bool(unparsed or overflow or any(g['omitted_events'] or g['app_dropped_events'] for g in result['processes']))
    # Static caps keep the diagnostic below its share of the unchanged 2 MB
    # artifact budget. Never silently write an oversized diagnostic.
    if len(json.dumps({'watch_editor_lifecycle': result}, indent=2).encode()) > MAX_LIFECYCLE_JSON_BYTES:
        raise ValueError('Watch lifecycle diagnostic exceeded its JSON byte bound')
    return result


def _rectangle(value):
    return (isinstance(value, list) and len(value) == 4
            and all(type(number) in (int, float) and math.isfinite(number) for number in value))


class ListFrameDiagnostics:
    def __init__(self):
        self.report = {'records': [], 'matched_records': 0, 'omitted_records': 0, 'invalid_records': 0}
        self._cases = {}

    def record(self, line):
        _, marker, payload = line.partition('WATCH_LIST_FRAME ')
        if not marker:
            return
        self.report['matched_records'] += 1
        try:
            if len(payload.encode()) > MAX_FRAME_JSON_BYTES + 1:
                raise ValueError('oversized input')
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {'case', 'phase', 'viewport', 'rows', 'snapshotMilliseconds'}:
                raise ValueError('unexpected fields')
            if not all(isinstance(value[key], str) and len(value[key]) <= 160 for key in ('case', 'phase')):
                raise ValueError('unbounded identity')
            if not _rectangle(value['viewport']):
                raise ValueError('invalid viewport')
            if type(value['snapshotMilliseconds']) is not int or value['snapshotMilliseconds'] < 0:
                raise ValueError('invalid duration')
            rows = value['rows']
            if not isinstance(rows, list) or len(rows) > 24:
                raise ValueError('unbounded rows')
            for row in rows:
                if (not isinstance(row, dict) or set(row) != {'id', 'frame'}
                        or not isinstance(row['id'], str) or not _ROW.fullmatch(row['id'])
                        or not _rectangle(row['frame'])):
                    raise ValueError('unexpected row data')
            if len(json.dumps(value).encode()) > MAX_FRAME_JSON_BYTES:
                raise ValueError('oversized encoding')
        except (ValueError, TypeError, OverflowError):
            self.report['invalid_records'] += 1
            return
        case = value['case']
        if len(self.report['records']) == MAX_FRAME_RECORDS or self._cases.get(case, 0) == MAX_FRAMES_PER_CASE:
            self.report['omitted_records'] += 1
            return
        self.report['records'].append(value)
        # The runtime artifact uses indent=2, one level below its report root.
        # Account for that real encoding rather than only compact input bytes.
        if len(json.dumps({'watch_list_frames': self.report}, indent=2).encode()) > MAX_FRAME_REPORT_BYTES:
            self.report['records'].pop()
            self.report['omitted_records'] += 1
            return
        self._cases[case] = self._cases.get(case, 0) + 1
