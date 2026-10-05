"""Strict bounded Home observer extraction; no terminal/no-publish inference.

The app records four counters in order: appear, disappear, palette, transfer.
The last record is a lower-bound snapshot, not a flush on app termination.
"""
import json
import re

COLD_CASE = '__WatchWorkflowTests_testHomeListDigitalCrownFromColdLaunch_'
MAX_RECORDS = 28
MAX_RECORD_BYTES = 512
MAX_REPORT_BYTES = 16_384
LIMITS = [4, 4, 8, 8]
EVENTS = ['appear', 'disappear', 'palette', 'transfer']
PREFIX = re.compile(r'^(.{1,80}?) TouchColor\[(\d+):[^\]]+\] '
                    r'\[com\.mango\.touchColor\.WatchDiagnostics:home\] WATCH_HOME (.*)$')
FIELDS = {'case', 'pid', 'uptimeMilliseconds', 'event', 'counts', 'omitted', 'saturated', 'terminal'}


def summarize_home_notifications(output, *, expected_case=COLD_CASE):
    if expected_case != COLD_CASE:
        raise ValueError('Only the exact unchanged cold-home test is observed')
    result = {'schema': 1, 'case': expected_case, 'counter_order': EVENTS,
              'records': [], 'matched_records': 0, 'omitted_records': 0,
              'invalid_records': 0, 'foreign_records': 0,
              'terminal_snapshot': False, 'counts_are_lower_bounds': True}
    previous = {}
    for line in output.splitlines():
        if 'WATCH_HOME' not in line:
            continue
        result['matched_records'] += 1
        match = PREFIX.fullmatch(line)
        if not match:
            result['invalid_records'] += 1
            continue
        stamp, pid, payload = match.groups()
        try:
            if len(payload.encode()) > MAX_RECORD_BYTES:
                raise ValueError('oversized')
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != FIELDS:
                raise ValueError('fields')
            if value['case'] != expected_case:
                result['foreign_records'] += 1
                continue
            if type(value['pid']) is not int or value['pid'] != int(pid) or value['pid'] <= 0:
                raise ValueError('pid')
            if type(value['uptimeMilliseconds']) is not int or not 0 <= value['uptimeMilliseconds'] <= 2**63 - 1:
                raise ValueError('uptime')
            if value['event'] not in EVENTS or type(value['saturated']) is not bool or value['terminal'] is not False:
                raise ValueError('observation')
            for key in ('counts', 'omitted'):
                if not isinstance(value[key], list) or len(value[key]) != 4 or any(type(n) is not int or not 0 <= n <= 2**32 - 1 for n in value[key]):
                    raise ValueError('counters')
            for count, omit, limit in zip(value['counts'], value['omitted'], LIMITS):
                if omit != max(0, count - limit) and not value['saturated']:
                    raise ValueError('omissions')
            if value['counts'][EVENTS.index(value['event'])] < 1:
                raise ValueError('missing event count')
            prior = previous.get(value['pid'])
            if prior and (value['uptimeMilliseconds'] < prior['uptimeMilliseconds'] or any(a < b for a, b in zip(value['counts'], prior['counts'])) or any(a < b for a, b in zip(value['omitted'], prior['omitted']))):
                raise ValueError('nonmonotonic process counters')
        except (ValueError, TypeError, KeyError, OverflowError):
            result['invalid_records'] += 1
            continue
        if len(result['records']) >= MAX_RECORDS:
            result['omitted_records'] += 1
            continue
        result['records'].append({'log_timestamp': stamp, **value})
        if len(json.dumps({'watch_home_notifications': result}, indent=2).encode()) > MAX_REPORT_BYTES - 256:
            result['records'].pop()
            result['omitted_records'] += 1
            continue
        previous[value['pid']] = value
    result['truncated'] = bool(result['omitted_records'] or result['invalid_records'] or result['foreign_records'] or
        any(any(row['omitted']) or row['saturated'] for row in result['records']))
    if len(json.dumps({'watch_home_notifications': result}, indent=2).encode()) > MAX_REPORT_BYTES:
        raise ValueError('Home report exceeded hard byte cap')
    return result
