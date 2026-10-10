"""Exact native method/host/result binding; counts alone never qualify a role."""
from collections import Counter
import hashlib
import math
import re

PAIRS = {('27.0', '26A428'), ('27.0.1', '26A434')}
CASE = re.compile(r"^Test Case '-\[(TouchColorMac(?:UI)?Tests)\.([A-Za-z_][A-Za-z_0-9]*) (test[A-Za-z_0-9]+)\]' (started|passed|failed|skipped)(?:\.| \([0-9.]+ seconds\)\.)$")


class Cases:
    def __init__(self, expected):
        self.expected = sorted(expected)
        self.pending = b''
        self.events = {key: Counter() for key in ('started', 'passed', 'failed', 'skipped')}
        self.foreign = []
        self.ordered = []
        self.sequence_error = False
        self.sha = hashlib.sha256()
        self.bytes = 0

    def consume(self, index, raw):
        if index != 0:
            raise ValueError('Native case stream must be one physical merged pipe')
        self.sha.update(raw)
        self.bytes += len(raw)
        self.pending += raw
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            self.line(line.rstrip(b'\r').decode('utf-8'))
        if len(self.pending) > 65536:
            raise ValueError('Unbounded native log line')

    def line(self, line):
        if not line.startswith('Test Case '):
            return
        match = CASE.fullmatch(line)
        if match is None:
            self.foreign.append(line[:512])
            return
        target, cls, method, event = match.groups()
        identity = target + '/' + cls + '/' + method
        if event == 'started':
            if self.events['started'][identity] or any(self.events[k][identity] for k in ('passed', 'failed', 'skipped')):
                self.sequence_error = True
        elif self.events['started'][identity] != 1 or any(self.events[k][identity] for k in ('passed', 'failed', 'skipped')):
            self.sequence_error = True
        self.ordered.append([identity, event])
        self.events[event][identity] += 1

    def finish(self):
        if self.pending:
            self.line(self.pending.decode('utf-8'))
            self.pending = b''
        expected = Counter(self.expected)
        complete = (not self.foreign and not self.sequence_error and self.events['started'] == expected and
                    self.events['passed'] == expected and not self.events['failed'] and not self.events['skipped'])
        return {'expected': self.expected, 'events': {key: dict(value) for key, value in self.events.items()},
                'foreign_lines': self.foreign, 'ordered_events': self.ordered, 'sequence_error': self.sequence_error,
                'raw_stream_sha256': self.sha.hexdigest(),
                'raw_stream_bytes': self.bytes, 'complete': complete}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def require(value, message):
    if not value:
        raise ValueError(message)


def bind_summary(summary, role_record, host, expected):
    require(role_record['role'] in ('hosted', 'normal', 'sandbox'), 'Unselected native role')
    require(role_record['exit'] == 0 and role_record['owned']['owned_group_cleanup_confirmed'] is True,
            'Native command or owned cleanup failed')
    require(role_record['cases']['complete'] is True and role_record['cases']['expected'] == sorted(expected),
            'Native exact case inventory incomplete')
    from commands import stages
    lane = 'sandbox' if role_record['role'] == 'sandbox' else 'normal'
    choices = [step['argv'] for stage in stages(lane) for step in stage['commands'] if step['role'] == role_record['role']]
    require(len(choices) == 1 and role_record.get('argv') == choices[0], 'Actual native argv differs from exact selected role')
    require(role_record.get('source_sha') == host['source_sha'] and role_record.get('run_id') == host['run_id'] and
            role_record.get('run_attempt') == host['run_attempt'] and role_record.get('lane') == lane, 'Command belongs to another source/run/lane')
    count = len(expected)
    require(summary.get('result') == 'Passed' and summary.get('testFailures') == [], 'Native summary failed')
    required = {'totalTestCount': count, 'passedTests': count, 'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}
    for key, value in required.items():
        require(type(summary.get(key)) is int and summary[key] == value, 'Summary count differs: ' + key)
    rows = summary.get('devicesAndConfigurations')
    require(isinstance(rows, list) and len(rows) == 1, 'One exact native destination required')
    config = rows[0]
    for key in ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures'):
        require(type(config.get(key)) is int and config[key] == required[key], 'Device count differs: ' + key)
    device = config.get('device', {})
    require(device.get('platform') == 'macOS' and device.get('architecture') == 'arm64' and
            (device.get('osVersion'), device.get('osBuildNumber')) == (host['version'], host['build']) and
            (host['version'], host['build']) in PAIRS, 'Summary does not match actual host pair')
    require(isinstance(device.get('deviceId'), str) and bool(device['deviceId']), 'Missing actual Mac destination')
    require(device['deviceId'] == host['destination_id'], 'Summary does not match this job observed Mac destination')
    start, finish = summary.get('startTime'), summary.get('finishTime')
    require(all(type(t) in (int, float) and math.isfinite(t) for t in (start, finish)), 'Invalid summary time')
    require(role_record['started_epoch'] <= start <= finish <= role_record['finished_epoch'] and
            role_record['finished_monotonic'] <= role_record['work_deadline'], 'Summary outside original command/work window')
    return device
