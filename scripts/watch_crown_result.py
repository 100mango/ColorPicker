"""Independently reconcile a bounded, static-only Watch Crown diagnostic receipt.

Only retained files authenticated by the receipt manifest are read. A passing
control is not product acceptance. A complete stationary Crown failure stays failed;
missing evidence or uncertain cleanup leaves the single case incomplete. Missing, timed-out or ambiguous evidence never
qualifies as passed. This validator starts no process and cannot run tests.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

from watch_crown_setup_events import SCHEMA, PROTOCOL, validate_setup_events

MAX_EVIDENCE_BYTES = 1_200_000
MAX_RECEIPT_BYTES = 300_000
MAX_OBSERVATION_BYTES = 16_384
RESERVES = {'cleanup': 130, 'evidence': 180, 'validation': 60, 'upload': 60, 'overhead': 20}
PHASE_LIMITS = {'preflight': 30, 'builds': 240, 'setup': 600,
                'isolated_static': 180}
CASE_NAMES = ('isolated_static',)
DIAGNOSTIC_SCOPE = 'static-list-crown-only-v1'
EXCLUDED_CASES = ['actual_cold', 'rgb_positive']
WORKFLOW = '.github/workflows/watch-static-crown-control.yml'
CASES = {
    'isolated_static': {'identifier': 'TouchColorWatchCrownControlUITests/WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations',
                       'project': 'TouchColorWatchCrownControl.xcodeproj', 'scheme': 'TouchColorWatchCrownControl',
                       'result_bundle': 'build/watch-crown-isolated_static.xcresult', 'derived_data': 'build/crown-static'},
}
COUNTS = ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures')
TIMEOUT = re.compile(r'exceeded execution time allowance|execution time.*exceeded|\btimed? out\b|\btime[ -]?out\b|test may have hung', re.I)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('nonfinite JSON number: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    pending = [(value, 0)]; count = 0
    while pending:
        item, depth = pending.pop(); count += 1
        require(count <= 30_000 and depth <= 40, 'JSON structure exceeds finite bound')
        if isinstance(item, dict): pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list): pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, float): require(math.isfinite(item), 'nonfinite JSON number')
    return value


def recorded_timeout(value):
    pending = [value]; visited = 0
    while pending:
        item = pending.pop(); visited += 1
        require(visited <= 30_000, 'diagnostic structure exceeds finite bound')
        if isinstance(item, str) and TIMEOUT.search(item): return True
        if isinstance(item, dict): pending.extend(item.values())
        elif isinstance(item, list): pending.extend(item)
    return False


def expected_command(name, device):
    case = CASES[name]
    return ['xcodebuild', 'test-without-building', '-project', case['project'], '-scheme', case['scheme'],
            '-configuration', 'Debug', '-destination', 'platform=watchOS Simulator,id=' + device,
            '-derivedDataPath', case['derived_data'], '-parallel-testing-enabled', 'NO',
            '-maximum-concurrent-test-simulator-destinations', '1', '-collect-test-diagnostics', 'never',
            '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '120',
            '-maximum-test-execution-time-allowance', '120',
            '-resultBundlePath', case['result_bundle'], '-only-testing:' + case['identifier'],
            'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO']


def _safe_read(root, name, cap):
    require(isinstance(name, str) and 0 < len(name) < 240, 'invalid evidence filename')
    parts = name.split('/')
    require(not Path(name).is_absolute() and all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in ('.', '..') for p in parts),
            'unsafe evidence filename')
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'unsafe evidence root')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd); fd = child
        leaf = os.open(parts[-1], flags, dir_fd=fd)
        try:
            before = os.fstat(leaf)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= cap,
                    'evidence is not a bounded independent regular file')
            raw = bytearray()
            while len(raw) <= cap:
                chunk = os.read(leaf, min(65536, cap + 1 - len(raw)))
                if not chunk: break
                raw.extend(chunk)
            after = os.fstat(leaf)
            require(len(raw) == before.st_size and len(raw) <= cap and
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'evidence changed while reading')
            return bytes(raw)
        finally:
            os.close(leaf)
    finally:
        os.close(fd)


def _manifest(report, root):
    entries = report.get('evidence')
    require(isinstance(entries, list) and 1 <= len(entries) <= 64, 'missing bounded evidence manifest')
    total = 0; observation = {'observation_static': 0}; blobs = {}; manifest = {}
    for entry in entries:
        require(isinstance(entry, dict), 'invalid evidence entry')
        name = entry.get('path'); size = entry.get('bytes'); digest = entry.get('sha256')
        require(type(size) is int and 0 <= size <= MAX_EVIDENCE_BYTES, 'invalid evidence byte count')
        require(name not in manifest and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'duplicate evidence path or invalid hash')
        total += size
        require(total <= MAX_EVIDENCE_BYTES, 'evidence exceeds 1200000 byte cap')
        raw = _safe_read(root, name, min(size, MAX_EVIDENCE_BYTES))
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, 'evidence size or SHA256 mismatch: ' + name)
        kind = entry.get('kind')
        allowed = {
            'isolated_static-build.log': ('build', 'isolated_static', 262_144),
            'setup-phone-bootstatus.log': ('setup_bootstatus', 'phone', 16_384),
            'setup-watch-bootstatus.log': ('setup_bootstatus', 'watch', 16_384),
            'static-observations.log': ('observation_static', 'isolated_static', 16_384),
            'cleanup-devices.json': ('cleanup_devices', None, 100_000), 'cleanup-pairs.json': ('cleanup_pairs', None, 100_000),
            **{'isolated_static-'+suffix: (category, 'isolated_static', cap) for suffix, category, cap in
               [('lifecycle.log','lifecycle',4096),('console.log','diagnostics',65_536),('summary.json','summary',100_000),
                ('cleanup-services.log','case_cleanup',65_536),('tests.json','tests',150_000)]}}
        require(name in allowed and (kind, entry.get('case')) == allowed[name][:2], 'Excluded or foreign evidence path/kind/case')
        require(size <= allowed[name][2], 'evidence exceeds unchanged per-file cap: '+name)
        if kind in observation:
            observation[kind] += size
            require(observation[kind] <= MAX_OBSERVATION_BYTES, kind + ' observation exceeds 16384 byte cap')
        blobs[name] = raw; manifest[name] = entry
    require(sum(observation.values()) <= MAX_OBSERVATION_BYTES, 'static observations exceed 16384 byte cap')
    return blobs, manifest


def _counts(value):
    require(isinstance(value, dict), 'missing structured result summary')
    require(all(type(value.get(key)) is int and value[key] >= 0 for key in COUNTS), 'invalid result counts')
    return {key: value[key] for key in COUNTS}


def _summary(summary, case, stage, device):
    counts = _counts(summary)
    require(type(summary.get('totalTestCount')) is int and summary['totalTestCount'] == 1 and sum(counts.values()) == 1,
            'summary does not contain exactly one test')
    require(counts['expectedFailures'] == 0 and counts['skippedTests'] == 0, 'skipped or expected-failure case is incomplete')
    status = 'passed' if counts['passedTests'] == 1 else 'failed' if counts['failedTests'] == 1 else None
    require(status is not None and summary.get('result') == status.title(), 'summary result/counts disagree')
    rows = summary.get('devicesAndConfigurations')
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict), 'ambiguous summary device/configuration')
    row = rows[0]
    require(_counts(row) == counts, 'device result counts disagree')
    actual = row.get('device', {})
    require(isinstance(actual, dict) and all(actual.get(key) == value for key, value in
            {'deviceId': device, 'platform': 'watchOS Simulator', 'osVersion': '27.0', 'architecture': 'arm64'}.items()),
            'summary device/runtime/architecture mismatch')
    require(row.get('testPlanConfiguration') == {'configurationId': '1', 'configurationName': 'Test Scheme Action'},
            'summary test configuration mismatch')
    start, finish = summary.get('startTime'), summary.get('finishTime')
    require(number(start) and number(finish) and stage['started_epoch'] <= start < finish <= stage['finished_epoch'],
            'summary timestamps outside test command lifetime')
    require(not recorded_timeout(summary), 'structured summary records a timeout')
    failures = summary.get('testFailures')
    require(isinstance(failures, list) and (bool(failures) == (status == 'failed')), 'missing or contradictory failure diagnostics')
    target, cls, method = case['identifier'].split('/')
    for failure in failures:
        require(isinstance(failure, dict) and failure.get('targetName') == target and
                failure.get('testIdentifierString') == cls + '/' + method + '()' and
                failure.get('testIdentifierURL') == 'test://com.apple.xcode/' + case['scheme'] + '/' + case['identifier'] and
                isinstance(failure.get('failureText'), str) and bool(failure['failureText']), 'failure diagnostic case binding mismatch')
    return status


def _test_tree(tree, case, status):
    require(isinstance(tree, dict) and isinstance(tree.get('testNodes'), list), 'missing test tree')
    pending = [(node, ()) for node in tree['testNodes']]; methods = []; visited = 0
    target, cls, method = case['identifier'].split('/')
    while pending:
        node, parents = pending.pop(); visited += 1
        require(visited <= 256 and isinstance(node, dict), 'invalid or oversized test tree')
        children = node.get('children', [])
        require(isinstance(children, list), 'invalid test-tree children')
        node_type = node.get('nodeType')
        if node_type == 'Test Case':
            methods.append(node)
            identifier = node.get('nodeIdentifier')
            require(identifier in (cls + '/' + method + '()', cls + '/' + method,
                                   case['identifier'], case['identifier'] + '()'), 'foreign test-tree method')
            require(node.get('result') == status.title(), 'test-tree result disagrees with summary')
            require(not children, 'repeated or nested test case is incomplete')
            require(target in parents, 'test-tree method lacks exact target ancestry')
        else:
            require(node_type in ('Test Plan', 'Unit test bundle', 'UI test bundle', 'Test Suite', 'Test Class', 'Test Bundle'),
                    'unknown test-tree node type')
            if node_type in ('Unit test bundle', 'UI test bundle', 'Test Bundle'):
                require(node.get('name') == target, 'foreign test-tree target')
        pending.extend((child, parents + (node.get('name'),)) for child in children)
    require(len(methods) == 1, 'test tree does not contain exactly one method')


def _lifecycle(raw, case, status, stage):
    text = raw.decode('utf-8', errors='strict')
    require(not recorded_timeout(text), 'lifecycle records a timeout')
    lines = [line.rstrip() for line in text.splitlines() if line.startswith('Test Case ')]
    target, cls, method = case['identifier'].split('/')
    prefix = "Test Case '-[" + target + '.' + cls + ' ' + method + "]' "
    require(len(lines) == 2 and lines[0] == prefix + 'started.', 'missing, duplicate, foreign or reordered lifecycle start')
    terminal = re.fullmatch(re.escape(prefix + status) + r' \(([0-9]+(?:\.[0-9]+)?) seconds\)\.', lines[1])
    require(terminal is not None, 'missing or contradictory lifecycle terminal')
    seconds = float(terminal[1])
    require(0 <= seconds < 120 and seconds <= stage['finished_monotonic'] - stage['started_monotonic'] + .001,
            'test lifecycle reached allowance or exceeds command lifetime')
    return seconds


def _identity(report, expected_source=None):
    require('simulator_uncertainty' not in report, 'Simulator command completion is uncertain; VM disposal required')
    require(not isinstance(report.get('stages'),list) or not any(isinstance(s,dict) and s.get('simulator_command_completion')=='unconfirmed'
                    for s in report['stages']),
            'Stage records unresolved simulator command completion')
    require(report.get('schema') == SCHEMA and type(report.get('schema')) is int and
            report.get('protocol') == PROTOCOL, 'unsupported receipt schema/protocol')
    require(report.get('acceptance', False) is False, 'receipt claims product acceptance')
    require(isinstance(report.get('errors'),list), 'malformed producer error inventory')
    require(report.get('diagnostic_scope') == DIAGNOSTIC_SCOPE and report.get('excluded_cases') == EXCLUDED_CASES,
            'missing or foreign static-only diagnostic scope/exclusions')
    source = report.get('source')
    require(isinstance(source, dict), 'missing source identity')
    for field, width in (('sha', 40), ('tree', 40), ('workflow_sha256', 64)):
        require(isinstance(source.get(field), str) and re.fullmatch('[0-9a-f]{' + str(width) + '}', source[field]),
                'invalid source ' + field)
    require(source.get('repository') == '100mango/ColorPicker' and
            source.get('ref') == 'refs/heads/codex/watch-static-crown-diagnostic' and source.get('workflow') == WORKFLOW, 'source repository/ref mismatch')
    for key in ('run_id', 'attempt'):
        require(isinstance(source.get(key), str) and re.fullmatch('[1-9][0-9]*', source[key]) and
                report.get(key) == source[key], 'source/run identity mismatch: ' + key)
    if expected_source is not None:
        require(source == expected_source, 'receipt differs from independently admitted source')
    require(report.get('source_before') == report.get('source_after') == {k: source[k] for k in ('sha', 'tree', 'workflow_sha256')}, 'source changed or before/after verification is missing')
    require(report.get('source_verified') is True, 'exact clean source not verified before and after execution')
    require(report.get('toolchain') == {'xcode': 'Xcode 27.0\nBuild version 27A266a', 'macos': '26A428', 'architecture': 'arm64'},
            'toolchain does not match exact admitted versions')
    device = report.get('device')
    require(isinstance(device, dict), 'missing owned device identity')
    require(device.get('profile') == 'smallest' and type(device.get('millimeters')) is int and device['millimeters'] == 40 and
            device.get('text_phase') == 'normal' and device.get('owned') is True,
            'device/profile/text phase mismatch')
    require(device.get('runtime') == 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0', 'wrong Watch runtime')
    require(isinstance(device.get('udid'), str) and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', device['udid']), 'invalid Watch UUID')
    require(isinstance(device.get('deviceTypeIdentifier'), str) and '40mm' in device['deviceTypeIdentifier'], 'unmeasured or different Watch device type')
    owned = report.get('owned_devices')
    require(isinstance(owned, list) and len(owned) == 2 and all(isinstance(row, dict) for row in owned), 'ambiguous owned device inventory')
    roles = {row.get('role'): row for row in owned}
    require(set(roles) == {'watch', 'phone'}, 'owned pair roles incomplete')
    watch, phone = roles['watch'], roles['phone']
    require(all(watch.get(key) == device.get(key) for key in ('udid', 'runtime', 'deviceTypeIdentifier')), 'owned Watch differs from destination')
    require(isinstance(phone.get('udid'), str) and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', phone['udid']) and
            phone['udid'].lower() != device['udid'].lower() and phone.get('runtime') == 'com.apple.CoreSimulator.SimRuntime.iOS-27-0' and
            isinstance(phone.get('deviceTypeIdentifier'), str) and phone['deviceTypeIdentifier'].startswith('com.apple.CoreSimulator.SimDeviceType.iPhone'), 'owned phone identity invalid')
    pair = report.get('pair')
    require(isinstance(pair, dict) and isinstance(pair.get('id'), str) and re.fullmatch(r'[0-9A-Fa-f-]{36}', pair['id']), 'missing owned pair identity')
    record = pair.get('record', {})
    require(isinstance(record, dict) and record.get('watch', {}).get('udid') == device['udid'] and
            record.get('phone', {}).get('udid') == phone['udid'], 'owned pair record does not match destination')
    activation = pair.get('activation')
    require(isinstance(activation, dict) and type(activation.get('activation_requested')) is bool and
            isinstance(activation.get('record'), dict) and activation['record'].get('watch', {}).get('udid') == device['udid'] and
            activation['record'].get('phone', {}).get('udid') == phone['udid'] and
            activation['record'].get('state') in ('(active, connected)', '(active, disconnected)'), 'owned pair activation unconfirmed')
    products = report.get('products_before')
    require(isinstance(products, dict) and set(products) == {'isolated_static'} and
            products == report.get('products_after'), 'static built products missing or changed during diagnostic')
    for product in products.values():
        require(isinstance(product, dict) and isinstance(product.get('sha256'), str) and
                re.fullmatch('[0-9a-f]{64}', product['sha256']) and type(product.get('files')) is int and
                1 <= product['files'] <= 8192 and type(product.get('bytes')) is int and 0 < product['bytes'] <= 1024**3,
                'invalid built product fingerprint')
    require(report.get('runner_bundle_ids') == {'isolated_static': 'com.mango.touchColor.watchCrownControl.uitests.xctrunner'},
            'runner identity is missing, excluded or foreign')
    initial = report.get('initial_inventory', {})
    require(isinstance(initial.get('devices'), dict) and isinstance(initial.get('pairs'), dict) and
            isinstance(initial['pairs'].get('pairs'), dict), 'missing original pair/device ownership inventory')
    originals = {item.get('udid') for rows in initial['devices'].values() if isinstance(rows, list)
                 for item in rows if isinstance(item, dict)}
    require(not (originals & {device['udid'], phone['udid']}) and pair['id'] not in initial['pairs']['pairs'], 'device or pair existed before this run')
    candidates = []
    for runtime, rows in initial['devices'].items():
        require(isinstance(rows, list), 'invalid original device inventory')
        if runtime != device['runtime']: continue
        for item in rows:
            require(isinstance(item, dict), 'invalid original device row')
            mm = re.search(r'\((\d+)mm\)', str(item.get('name', '')))
            if item.get('isAvailable') is True and mm:
                candidates.append((int(mm[1]), item))
    require(candidates and min(mm for mm, _ in candidates) == 40 and
            any(mm == 40 and item.get('deviceTypeIdentifier') == device['deviceTypeIdentifier'] for mm, item in candidates),
            '40mm destination is not the observed smallest available Watch profile')
    return source, device['udid']


def _budget_identity(report, source):
    budget = report.get('budget')
    require(isinstance(budget, dict) and budget.get('schema') == 1 and budget.get('platform') == 'watch-crown-control' and
            budget.get('lane') == 'watch-static-crown-control-smallest' and type(budget.get('minutes')) is int and budget['minutes'] == 25,
            'wrong source-owned 25-minute budget identity')
    require(budget.get('sha') == source['sha'] and budget.get('run_id') == source['run_id'], 'budget source/run mismatch')
    require(budget.get('reserves') == RESERVES and budget.get('startup_margin') == 30, 'budget reserves or startup margin changed')
    require(number(budget.get('started_epoch')) and number(budget.get('started_monotonic')), 'missing original budget clocks')
    return budget


def _budget_and_stages(report, source):
    budget = _budget_identity(report, source)
    require(budget.get('cleanup_unconfirmed') is False, 'budget records unconfirmed cleanup')
    phases = report.get('phases')
    require(isinstance(phases, list) and [row.get('name') for row in phases if isinstance(row, dict)] == list(PHASE_LIMITS) + ['cleanup', 'evidence'],
            'phase inventory is incomplete, duplicated or reordered')
    previous_epoch, previous_mono = budget['started_epoch'], budget['started_monotonic']
    phase_map = {}
    for row in phases:
        name = row['name']
        phase_limit = (PHASE_LIMITS | RESERVES)[name]
        require(row.get('limit_seconds') == phase_limit and row.get('completed') is True, 'phase is incomplete or allowance changed: ' + name)
        se, fe, sm, fm = (row.get(key) for key in ('started_epoch', 'finished_epoch', 'started_monotonic', 'finished_monotonic'))
        require(all(number(value) for value in (se, fe, sm, fm)), 'invalid phase timing')
        require(previous_epoch <= se <= fe and previous_mono <= sm <= fm and
                fm - sm <= phase_limit and fe - se <= phase_limit and abs((fm-sm)-(fe-se)) <= 1,
                'overlapping, over-budget or contradictory phase clocks')
        if name in PHASE_LIMITS:
            require(sm-budget['started_monotonic']+phase_limit <= 1020 and
                    se-budget['started_epoch']+phase_limit <= 1020, 'full phase allowance not admitted on original clock')
        cutoff = 1020 if name in PHASE_LIMITS else {'cleanup': 1150, 'evidence': 1330}[name]
        require(fm - budget['started_monotonic'] <= cutoff and fe - budget['started_epoch'] <= cutoff,
                'phase exceeded original-clock cutoff')
        previous_epoch, previous_mono = fe, fm
        phase_map[name] = row
    end = report.get('work_finished_monotonic'); elapsed = report.get('work_elapsed_from_original_seconds')
    require(number(end) and number(elapsed) and 0 <= elapsed <= 1020 and
            abs(end-budget['started_monotonic']-elapsed) <= .01 and
            max(row['finished_monotonic'] for row in phases if row['name'] in PHASE_LIMITS) <= end,
            'work elapsed receipt contradicts original clock or cutoff')
    stages = report.get('stages')
    require(isinstance(stages, list) and 1 <= len(stages) <= 192, 'missing bounded command stages')
    previous_epoch, previous_mono = budget['started_epoch'], budget['started_monotonic']
    for stage in stages:
        require(isinstance(stage, dict), 'invalid command stage')
        require(isinstance(stage.get('command'), list) and stage['command'] and
                all(isinstance(arg, str) and len(arg) <= 4096 for arg in stage['command']), 'invalid command argv')
        require(stage.get('source_sha') == source['sha'], 'command source SHA mismatch')
        require(type(stage.get('started')) is bool and stage['started'], 'command was not started')
        require(type(stage.get('exit')) is int and type(stage.get('raw_exit')) is int and stage['exit'] == stage['raw_exit'], 'synthetic or missing command exit')
        require(stage.get('timed_out') is False and not stage.get('reported_device_timeout'),
                'command timed out or timeout state unknown')
        require(stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True and
                not stage.get('reader_errors') and not stage.get('cleanup_error'), 'owned process or capture cleanup unconfirmed')
        require(type(stage.get('stdout_truncated')) is bool, 'missing capture truncation state')
        phase = stage.get('phase')
        require(phase in PHASE_LIMITS or phase in RESERVES, 'unexpected command phase')
        se, fe, sm, fm = (stage.get(key) for key in ('started_epoch', 'finished_epoch', 'started_monotonic', 'finished_monotonic'))
        limit = stage.get('timeout_seconds')
        if stage['command'][:3] in (['xcrun','simctl','boot'],['xcrun','simctl','bootstatus']):
            require(phase=='setup','Boot/readiness command is outside setup')
        if phase=='setup' and stage['command'][:2]==['xcrun','simctl']:
            caps={'list':30,'create':60,'pair':60,'pair_activate':60,'boot':180,'bootstatus':420}
            cap=caps.get(stage['command'][2] if len(stage['command'])>2 else '')
            require(cap is not None and stage.get('setup_command_cap_seconds')==cap and number(limit) and 0<limit<=cap,
                    'Canonical setup command cap changed or unknown family')
        require(all(number(value) for value in (se, fe, sm, fm, limit)), 'invalid command timing')
        require(previous_epoch <= se <= fe and previous_mono <= sm <= fm and 0 < limit <= (PHASE_LIMITS | RESERVES)[phase] and
                fm-sm < limit and fe-se < limit and abs((fm-sm)-(fe-se)) <= 1, 'overlapping, expired or contradictory command clocks')
        if phase in PHASE_LIMITS:
            row = phase_map[phase]
            require(row['started_epoch'] <= se <= fe <= row['finished_epoch'] and
                    row['started_monotonic'] <= sm <= fm <= row['finished_monotonic'], 'command is outside its admitted phase')
        else:
            deadline = {'cleanup': 1150, 'evidence': 1330, 'validation': 1390, 'upload': 1450, 'overhead': 1470}[phase]
            require(fe-budget['started_epoch'] <= deadline and fm-budget['started_monotonic'] <= deadline,
                    'command borrowed a later reserve')
        previous_epoch, previous_mono = fe, fm
    cleanup = report.get('cleanup')
    require(isinstance(cleanup, dict) and all(cleanup.get(key) is True for key in ('confirmed', 'device_absence_verified', 'pair_absence_verified')),
            'owned pair/device cleanup is incomplete')
    return stages


def _command_inventory(report):
    """Exact fixed lane commands. Wrappers, extra selectors and product work fail closed."""
    stages=report['stages']; device=report['device']['udid']
    phone=next(d['udid'] for d in report['owned_devices'] if d['role']=='phone')
    source_commands=[(['git','rev-parse','HEAD'],2),(['git','rev-parse','HEAD^{tree}'],2),
                     (['git','status','--porcelain','--untracked-files=all'],2)]
    preflight=[s for s in stages if s['phase']=='preflight']
    require(len(preflight)==10, 'fixed preflight command inventory changed')
    generator=preflight[6]['command']
    require(len(generator)==2 and re.fullmatch(r'python(?:3(?:\.[0-9]+)?)?',Path(generator[0]).name) and
            generator[1]=='scripts/generate_watch_crown_control_project.py', 'foreign project generator')
    expected={
        'preflight':source_commands+[(['xcodebuild','-version'],4),(['sw_vers','-buildVersion'],2),(['uname','-m'],2),
                                     (generator,3)]+source_commands,
        'builds':[(['xcodebuild','-quiet','-project','TouchColorWatchCrownControl.xcodeproj','-scheme','TouchColorWatchCrownControl',
                   '-configuration','Debug','-destination','generic/platform=watchOS Simulator','-derivedDataPath','build/crown-static',
                   'ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','build-for-testing'],110)],
        'isolated_static':[(expected_command('isolated_static',device),180),
            (['xcrun','xcresulttool','get','test-results','summary','--path',CASES['isolated_static']['result_bundle']],15),
            (['xcrun','simctl','terminate',device,'com.mango.touchColor.watchCrownControl'],30),
            (['xcrun','simctl','terminate',device,'com.mango.touchColor.watchCrownControl.uitests.xctrunner'],30),
            (['xcrun','simctl','spawn',device,'launchctl','list'],5)],
        'cleanup':[(['xcrun','simctl','shutdown',device],10),(['xcrun','simctl','shutdown',phone],10),
            (['xcrun','simctl','list','devices','-j'],5),(['xcrun','simctl','unpair',report['pair']['id']],10),
            (['xcrun','simctl','delete',device],10),(['xcrun','simctl','delete',phone],10),
            (['xcrun','simctl','list','devices','-j'],5),(['xcrun','simctl','list','pairs','-j'],5)],
        'evidence':source_commands+[
            (['xcrun','xcresulttool','get','test-results','tests','--path',CASES['isolated_static']['result_bundle']],20)]}
    for phase,commands in expected.items():
        observed=[stage for stage in stages if stage['phase']==phase]
        require([(stage['command'],stage['timeout_seconds']) for stage in observed]==commands,
                'fixed static-only command inventory/caps changed: '+phase)
        if phase!='isolated_static':
            require(all(stage['raw_exit']==0 and not stage['stdout_truncated'] for stage in observed
                        if stage['command'][:3]!=['xcrun','simctl','shutdown']), 'non-test command failed or was truncated')
    require(all(stage['phase'] in expected or stage['phase']=='setup' for stage in stages), 'foreign command phase')
    require(isinstance(report.get('cases'),list) and len(report['cases'])==1 and
            isinstance(report['cases'][0],dict) and report['cases'][0].get('name')=='isolated_static',
            'exact singleton static case inventory required')
    row=report['cases'][0]
    static_indices=[i for i,stage in enumerate(stages) if stage['phase']=='isolated_static']
    require([row.get('stage_index'),row.get('summary_stage_index'),row.get('process_cleanup',{}).get('inventory_stage_index')]
            ==[static_indices[0],static_indices[1],static_indices[4]], 'case stages do not bind sole static invocation')


def _case_timing(report, name, stage):
    budget = report['budget']
    phases = [row for row in report.get('phases', []) if isinstance(row, dict) and row.get('name') == name]
    require(len(phases) == 1, 'case phase missing or duplicated')
    phase = phases[0]
    require(phase.get('limit_seconds') == PHASE_LIMITS[name], 'case phase allowance changed')
    se, fe, sm, fm = (stage.get(key) for key in ('started_epoch', 'finished_epoch', 'started_monotonic', 'finished_monotonic'))
    pse, pfe, psm, pfm = (phase.get(key) for key in ('started_epoch', 'finished_epoch', 'started_monotonic', 'finished_monotonic'))
    limit = stage.get('timeout_seconds')
    require(all(number(v) for v in (se, fe, sm, fm, pse, pfe, psm, pfm, limit)), 'invalid case timing')
    require(budget['started_epoch'] <= pse <= se < fe <= pfe and budget['started_monotonic'] <= psm <= sm < fm <= pfm and
            limit == 180 and fm-sm < limit and fe-se < limit and pfm-psm <= PHASE_LIMITS[name] and
            pfe-pse <= PHASE_LIMITS[name] and abs((fm-sm)-(fe-se)) <= 1 and abs((pfm-psm)-(pfe-pse)) <= 1 and
            fe-budget['started_epoch'] <= 1020 and fm-budget['started_monotonic'] <= 1020, 'case timing or original work cutoff inconsistent')
    require(stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True and
            not stage.get('reader_errors') and not stage.get('cleanup_error'), 'case process/capture cleanup unconfirmed')


def _cleanup_evidence(report, blobs, manifest):
    cleanup = report.get('cleanup', {})
    owned = {row['udid'] for row in report.get('owned_devices', [])}
    require(set(cleanup.get('owned_device_ids', [])) == owned and cleanup.get('pair_id') == report['pair']['id'], 'cleanup targets differ from owned pair')
    for filename, kind, key in (('cleanup-devices.json', 'cleanup_devices', 'device_inventory_sha256'),
                                ('cleanup-pairs.json', 'cleanup_pairs', 'pair_inventory_sha256')):
        require(filename in blobs and manifest[filename].get('kind') == kind and cleanup.get(key) == manifest[filename]['sha256'], 'missing or inconsistent cleanup inventory')
    for key, filename, noun in (('device_stage_index', 'cleanup-devices.json', 'devices'), ('pair_stage_index', 'cleanup-pairs.json', 'pairs')):
        index = cleanup.get(key)
        require(type(index) is int and 0 <= index < len(report['stages']), 'final cleanup inventory command missing')
        stage = report['stages'][index]
        require(stage.get('command') == ['xcrun', 'simctl', 'list', noun, '-j'] and stage.get('phase') == 'cleanup' and
                stage.get('started') is True and stage.get('exit') == 0 and type(stage.get('raw_exit')) is int and stage['raw_exit'] == 0 and
                stage.get('timed_out') is False and stage.get('stdout_truncated') is False and stage.get('process_group_gone') is True and
                stage.get('capture_reader_finished') is True and stage.get('stdout_sha256') == manifest[filename]['sha256'] and
                stage.get('stdout_bytes') == manifest[filename]['bytes'], 'final cleanup raw inventory is unbound')
    devices = strict_json(blobs['cleanup-devices.json']).get('devices'); pairs = strict_json(blobs['cleanup-pairs.json']).get('pairs')
    require(isinstance(devices, dict) and isinstance(pairs, dict), 'malformed cleanup inventories')
    present = set()
    for rows in devices.values():
        require(isinstance(rows, list), 'malformed final device inventory')
        for row in rows:
            require(isinstance(row, dict) and isinstance(row.get('udid'), str), 'malformed final device row')
            present.add(row['udid'])
    require(not (present & owned) and report['pair']['id'] not in pairs, 'owned device or pair remains after cleanup')


def _extraction_and_cleanup(report, name, row, stage, blobs, manifest):
    stages = report['stages']
    for key, filename, action, phase in (('summary_stage_index', row['summary_file'], 'summary', name),
                                          ('tests_stage_index', row['tests_file'], 'tests', 'evidence')):
        index = row.get(key)
        require(type(index) is int and row['stage_index'] < index < len(stages), 'missing or reordered extraction stage')
        extraction = stages[index]
        require(extraction.get('command') == ['xcrun', 'xcresulttool', 'get', 'test-results', action, '--path', row['result_bundle']] and
                extraction.get('phase') == phase and extraction.get('started') is True and extraction.get('exit') == 0 and
                type(extraction.get('raw_exit')) is int and extraction['raw_exit'] == 0 and extraction.get('timed_out') is False and
                extraction.get('stdout_truncated') is False and extraction.get('process_group_gone') is True and
                extraction.get('capture_reader_finished') is True and not extraction.get('reader_errors') and
                extraction.get('stdout_sha256') == manifest[filename]['sha256'] and
                extraction.get('stdout_bytes') == manifest[filename]['bytes'], 'raw result extraction is unbound or incomplete')
        require(number(extraction.get('started_epoch')) and extraction['started_epoch'] >= stage['finished_epoch'] and
                number(extraction.get('started_monotonic')) and extraction['started_monotonic'] >= stage['finished_monotonic'], 'raw result extraction predates case')
    proof = row.get('process_cleanup')
    require(isinstance(proof, dict) and proof.get('confirmed') is True, 'missing case process cleanup receipt')
    index = proof.get('inventory_stage_index')
    require(type(index) is int and row['summary_stage_index'] < index < len(stages), 'invalid case process inventory index')
    cleanup = stages[index]; device = report['device']['udid']
    require(cleanup.get('command') == ['xcrun', 'simctl', 'spawn', device, 'launchctl', 'list'] and cleanup.get('exit') == 0 and
            cleanup.get('raw_exit') == 0 and cleanup.get('started') is True and cleanup.get('timed_out') is False and
            cleanup.get('stdout_truncated') is False and cleanup.get('process_group_gone') is True and cleanup.get('capture_reader_finished') is True,
            'case cleanup inventory command incomplete')
    expected_ids = ['com.mango.touchColor.watchCrownControl', 'com.mango.touchColor.watchCrownControl.uitests.xctrunner']
    require(proof.get('identifiers') == expected_ids, 'case cleanup targets wrong app/runner')
    filename = proof.get('inventory_file')
    require(filename == name + '-cleanup-services.log' and filename in blobs and manifest[filename].get('kind') == 'case_cleanup' and
            manifest[filename].get('case') == name and proof.get('inventory_sha256') == manifest[filename]['sha256'] == cleanup.get('stdout_sha256') and
            cleanup.get('stdout_bytes') == manifest[filename]['bytes'], 'case process inventory evidence missing or changed')
    lines = blobs[filename].decode('utf-8', errors='strict').splitlines()
    require(lines and lines[0].split() == ['PID', 'Status', 'Label'] and
            all(not any(identifier in line for identifier in expected_ids) for line in lines[1:]), 'case app/runner remains in process inventory')
    require(proof.get('entries') == len(lines)-1, 'process inventory count mismatch')


def _capture_extraction(report, row, stage, blobs, manifest):
    """Reconcile producer attestation, never reconstruct discarded interleaving."""
    size,digest=stage.get('stdout_bytes'),stage.get('stdout_sha256')
    require(type(size) is int and 0 < size <= 262_144 and isinstance(digest,str) and
            re.fullmatch('[0-9a-f]{64}',digest), 'original static capture digest/count is missing or invalid')
    files=[]
    for path,cap in [('isolated_static-lifecycle.log',4096),('isolated_static-console.log',65_536),
                     ('static-observations.log',16_384)]:
        require(path in blobs and path in manifest, 'static extraction file is missing')
        raw=blobs[path]
        require(0 < len(raw) <= cap and manifest[path]['bytes']==len(raw) and
                manifest[path]['sha256']==hashlib.sha256(raw).hexdigest(), 'static extraction file bytes differ')
        files.append({'path':path,'sha256':manifest[path]['sha256'],'bytes':manifest[path]['bytes']})
    expected={'schema':1,'policy':'watch-static-crown-split-lines-v1',
        'provenance':'source-controlled extraction; original interleaving is not reconstructed',
        'source_sha':report['source']['sha'],'run_id':report['run_id'],'attempt':report['attempt'],
        'case':'isolated_static','stage_index':row['stage_index'],
        'capture':{'sha256':digest,'bytes':size},'files':files}
    proof=row.get('capture_extraction')
    require(isinstance(proof,dict) and type(proof.get('schema')) is int and
            type(proof.get('stage_index')) is int and isinstance(proof.get('capture'),dict) and
            type(proof['capture'].get('bytes')) is int and isinstance(proof.get('files'),list) and
            all(isinstance(v,dict) and type(v.get('bytes')) is int for v in proof['files']) and proof==expected,
            'static source-controlled extraction receipt differs from test stage or retained files')
    # The fixed policy duplicates lifecycle lines in the ordinary console and
    # splits static markers out of it. This verifies the deterministic visible
    # relation, without asserting a lost ordering of static and ordinary lines.
    console=blobs['isolated_static-console.log'].decode('utf-8',errors='strict')
    lifecycle=blobs['isolated_static-lifecycle.log'].decode('utf-8',errors='strict')
    markers=blobs['static-observations.log'].decode('utf-8',errors='strict')
    require(lifecycle=='\n'.join(line for line in console.splitlines() if line.startswith('Test Case '))+'\n',
            'lifecycle differs from fixed console extraction policy')
    require(not any(line.startswith('WATCH_STATIC_CROWN_') for line in console.splitlines()) and
            all(line.startswith('WATCH_STATIC_CROWN_') for line in markers.splitlines()),
            'static marker/console split differs from fixed extraction policy')


def _observations(blobs, manifest):
    filename = 'static-observations.log'
    require(filename in blobs and manifest[filename].get('kind') == 'observation_static' and
            manifest[filename].get('case') == 'isolated_static', 'mandatory static observation missing or unbound')
    def rect(value):
        return (isinstance(value, list) and len(value) == 4 and all(number(v) for v in value) and
                value[2] > 0 and value[3] > 0 and math.isfinite(value[0]+value[2]) and math.isfinite(value[1]+value[3]))
    lines = blobs['static-observations.log'].decode('utf-8', errors='strict').splitlines()
    frames = []; summaries = []; frame_bytes = 0; summary_bytes = 0
    for line in lines:
        prefix, separator, payload = line.partition(' ')
        require(separator and prefix in ('WATCH_STATIC_CROWN_FRAME', 'WATCH_STATIC_CROWN_RESULT'), 'invalid static observation marker')
        value = strict_json(payload)
        require(isinstance(value, dict) and value.get('case') == 'WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations',
                'static observation case mismatch')
        if prefix.endswith('_FRAME'):
            require(not summaries and len(payload.encode()) <= 1536, 'static frame order/byte bound')
            frames.append(value); frame_bytes += len(payload.encode())
        else:
            require(len(payload.encode()) <= 2048, 'static result byte bound')
            summaries.append(value); summary_bytes += len(payload.encode())
    require(len(summaries) == 1, 'static result missing or duplicated')
    summary = summaries[0]
    integer_fields=('crownCalls','crownSnapshots','touchSnapshots','touchCalls','emittedFrames','maxStructuredBytes',
                    'frameBytes','structuredBytes','omittedFrames','omittedRows','omittedSubtreeRoots','snapshotErrors')
    require(all(type(summary.get(k)) is int for k in integer_fields), 'static summary count types are not exact integers')
    require(summary.get('crownCalls') == 3 and summary.get('delta') == -0.1 and summary.get('crownSnapshots') == 6 and
            type(summary.get('touchSnapshots')) is int and 0 <= summary['touchSnapshots'] <= 2 and
            type(summary.get('touchCalls')) is int and 0 <= summary['touchCalls'] <= 1 and
            summary.get('emittedFrames') == len(frames) == 6+summary['touchSnapshots'] and
            summary.get('touchCanSatisfyCrown') is False and summary.get('productHomeAcceptance') == 'unchanged' and
            summary.get('maxStructuredBytes') == 16384 and summary.get('frameBytes') == frame_bytes and
            summary.get('structuredBytes') == frame_bytes+summary_bytes <= 16384 and
            summary.get('failureReason') == 'none' and all(summary.get(k) == 0 for k in
                ('omittedFrames', 'omittedRows', 'omittedSubtreeRoots', 'snapshotErrors')) and
            summary.get('omittedDescendantsUnknown') is False and summary.get('crownStatus') in ('moved_downward', 'stationary', 'inconclusive_geometry_changed'),
            'static Crown observations incomplete, omitted or acceptance alias')
    expected_phases = ['crown.'+str(i)+'.'+side for i in range(3) for side in ('before','after')]
    expected_phases += ['touch.before', 'touch.after'][:summary['touchSnapshots']]
    require([f.get('phase') for f in frames] == expected_phases, 'static Crown/touch snapshot sequence mismatch')
    pid = None; uptime = -1
    for frame in frames:
        require(all(type(frame.get(k)) is int for k in ('runnerPID','listCount','navigationCount','backButtons',
                'omittedIdentityCharacters','omittedSubtreeRoots','duplicateRows','invalidRows','omittedRows','nodesVisited')),
                'static frame count types are not exact integers')
        require(type(frame.get('runnerPID')) is int and frame['runnerPID'] > 0 and (pid is None or pid == frame['runnerPID']) and
                number(frame.get('uptime')) and frame['uptime'] >= uptime and frame.get('geometryComplete') is True and
                frame.get('listCount') == 1 and frame.get('navigationCount') == 1 and frame.get('listIdentifier') == 'static.list' and
                (frame.get('navigationIdentifier') == 'Crown Control' or frame.get('navigationTitle') == 'Crown Control') and
                all(rect(frame.get(k)) and frame[k][2] > 0 and frame[k][3] > 0 for k in ('viewport', 'list', 'navigation')) and
                all(frame.get(k) == 0 for k in ('backButtons', 'omittedIdentityCharacters', 'omittedSubtreeRoots', 'duplicateRows', 'invalidRows', 'omittedRows')) and
                frame.get('omittedDescendantsUnknown') is False and type(frame.get('nodesVisited')) is int and 1 <= frame['nodesVisited'] <= 256,
                'static frame PID, geometry or traversal incomplete')
        pid, uptime = frame['runnerPID'], frame['uptime']
        rows = frame.get('rows')
        require(isinstance(rows, list) and 1 <= len(rows) <= 12 and all(isinstance(r, dict) and type(r.get('id')) is int and
                0 <= r['id'] < 12 and rect(r.get('frame')) for r in rows) and len({r['id'] for r in rows}) == len(rows), 'static rows missing or invalid')

    def same(a, b): return all(abs(x-y) <= .5 for x,y in zip(a,b))
    def intersects(a, b):
        return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]
    def movement(before, after):
        if any(not same(before[k], after[k]) for k in ('viewport','list','navigation')): return 'unclassified'
        left={r['id']:r['frame'] for r in before['rows']};right={r['id']:r['frame'] for r in after['rows']}
        shared=left.keys() & right.keys()
        for identifier in shared:
            a,b=left[identifier],right[identifier]
            if not (intersects(a,before['viewport']) or intersects(b,after['viewport'])): continue
            if all(abs(a[k]-b[k]) <= .5 for k in (0,2,3)) and b[1] < a[1]-1: return 'downward'
        if left.keys()==right.keys() and all(same(left[k],right[k]) for k in shared): return 'stationary'
        return 'unclassified'
    moved=False;stationary=True;last=None
    for i in range(3):
        before,after=frames[2*i:2*i+2]; change=movement(before,after)
        if change=='downward': moved=True;stationary=False
        elif change!='stationary': stationary=False
        if movement(frames[0],after)=='downward': moved=True
        if last is not None and movement(last,before)!='stationary': stationary=False
        last=after
    observed='moved_downward' if moved else 'stationary' if stationary else 'inconclusive_geometry_changed'
    require(observed != 'inconclusive_geometry_changed', 'changed geometry leaves the Crown observation incomplete')
    require(summary['crownStatus']==observed, 'static Crown marker contradicts retained frame movement')
    touch=summary.get('touchStatus')
    if observed != 'stationary':
        require(summary['touchCalls']==summary['touchSnapshots']==0 and touch=='not_attempted',
                'touch was attempted before a frozen stationary Crown result')
    elif summary['touchCalls']==1:
        require(summary['touchSnapshots']==2 and movement(frames[5],frames[6])=='stationary', 'touch lacks its frozen stationary starting frame')
        touch_result={'downward':'moved_downward','stationary':'stationary','unclassified':'inconclusive_geometry_changed'}[movement(frames[6],frames[7])]
        require(touch==touch_result, 'touch marker contradicts separately retained frames')
    else:
        require(summary['touchSnapshots']==1 and touch in ('not_attempted_geometry_changed','not_attempted_invalid_geometry'),
                'stationary Crown lacks its bounded optional touch outcome')
    return summary


def _directory_budget(root, manifest):
    root = Path(root); total = 0; count = 0
    for folder, directories, names in os.walk(root, followlinks=False):
        require(len(directories) <= 64 and all(not (Path(folder)/d).is_symlink() for d in directories), 'unsafe evidence subdirectory')
        for name in names:
            path = Path(folder)/name; count += 1
            require(count <= 70, 'evidence file inventory exceeds bound')
            st = path.lstat()
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'unsafe evidence file')
            relative = str(path.relative_to(root))
            require(relative in manifest or relative in ('report.json', 'validation.json'), 'unmanifested evidence file: ' + relative)
            total += st.st_size
    require(total + (0 if (root/'validation.json').exists() else 16_384) <= MAX_EVIDENCE_BYTES,
            'evidence plus validation reserve exceeds 1200000 byte cap')
    return total


def incomplete_result(error=None):
    return {'schema': 1, 'result': 'incomplete', 'complete': False, 'acceptance': False,
            'purpose': 'static_list_crown_only', 'diagnostic_scope': DIAGNOSTIC_SCOPE,
            'excluded_cases': list(EXCLUDED_CASES), 'cases': [{'name':'isolated_static',
                'identifier':CASES['isolated_static']['identifier'], 'result':'incomplete'}],
            'errors': [error] if error else []}


def validate_result(report, evidence_dir, *, expected_source=None, expected_budget=None):
    """Return diagnostic outcomes; no receipt can produce acceptance=True."""
    result = incomplete_result()
    result['cases'] = []
    blobs = {}; manifest = {}; stages = report.get('stages', []) if isinstance(report, dict) else []
    if not isinstance(stages, list): stages = []
    global_valid = True
    try:
        require(isinstance(report, dict), 'receipt is not an object')
        blobs, manifest = _manifest(report, evidence_dir)
        result['evidence_bytes'] = _directory_budget(evidence_dir, manifest)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, UnicodeError, RecursionError, OverflowError) as error:
        result['errors'].append(str(error)[:500]); global_valid = False
    try:
        source, device = _identity(report, expected_source)
        _budget_identity(report, source)
        validate_setup_events(report, blobs, manifest)
        if expected_budget is not None:
            require(all(report['budget'].get(k) == v for k, v in expected_budget.items()), 'receipt clock or budget differs from original persisted budget')
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, UnicodeError, RecursionError, OverflowError) as error:
        result['errors'].append(str(error)[:500]); global_valid = False
        device = report.get('device', {}).get('udid') if isinstance(report, dict) and isinstance(report.get('device'), dict) else None
    try:
        if global_valid:
            _budget_and_stages(report, source)
            _cleanup_evidence(report, blobs, manifest)
            _command_inventory(report)
            build = next(s for s in report['stages'] if s['phase']=='builds')
            require('isolated_static-build.log' in manifest and
                    build.get('stdout_sha256') == manifest['isolated_static-build.log']['sha256'] and
                    build.get('stdout_bytes') == manifest['isolated_static-build.log']['bytes'],
                    'static build evidence is missing or unbound')
            observation = _observations(blobs, manifest)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, UnicodeError, RecursionError, OverflowError) as error:
        result['errors'].append(str(error)[:500]); global_valid = False
    if isinstance(report, dict) and report.get('errors'):
        if isinstance(report['errors'],list):
            result['errors'].extend(str(error)[:500] for error in report['errors'][:8])
        else:
            result['errors'].append('malformed producer error inventory'); global_valid = False
    rows = report.get('cases', []) if isinstance(report, dict) else []
    if not isinstance(rows, list) or len(rows) != 1 or any(not isinstance(row, dict) for row in rows) or [r.get('name') for r in rows] != list(CASE_NAMES):
        result['errors'].append('case inventory is incomplete, duplicated or reordered')
    by_name = {row.get('name'): row for row in rows if isinstance(row, dict) and isinstance(row.get('name'), str)} if isinstance(rows, list) else {}
    used_indices = []
    for name in CASE_NAMES:
        outcome = {'name': name, 'identifier': CASES[name]['identifier'], 'result': 'incomplete', 'errors': [],
                   'original_exit': None, 'raw_summary_result': None, 'summary_failures': [], 'evidence': {}}
        row = by_name.get(name, {}); summary = None
        try:
            summary_file = row.get('summary_file')
            if summary_file == name + '-summary.json' and summary_file in blobs and manifest[summary_file].get('case') == name and manifest[summary_file].get('kind') == 'summary':
                summary = strict_json(blobs[row['summary_file']])
                if isinstance(summary, dict):
                    outcome['raw_summary_result'] = summary.get('result')
                    failures = summary.get('testFailures', [])
                    outcome['summary_failure_count'] = len(failures) if isinstance(failures, list) else None
                    outcome['summary_failures'] = [{'failureText': str(f.get('failureText', ''))[:700],
                        'truncated': len(str(f.get('failureText', ''))) > 700} for f in failures[:2] if isinstance(f, dict)] if isinstance(failures, list) else []
            for key, kind in (('summary_file', 'summary'), ('tests_file', 'tests'), ('lifecycle_file', 'lifecycle'), ('diagnostics_file', 'diagnostics')):
                filename = row.get(key)
                expected = name + {'summary_file': '-summary.json', 'tests_file': '-tests.json', 'lifecycle_file': '-lifecycle.log', 'diagnostics_file': '-console.log'}[key]
                require(filename == expected and filename in blobs and manifest[filename].get('case') == name and
                        manifest[filename].get('kind') == kind, 'missing or unbound case evidence: ' + key)
                outcome['evidence'][key] = filename
            case = CASES[name]
            require(all(row.get(key) == case[key] for key in ('identifier', 'project', 'scheme', 'result_bundle')), 'case command identity mismatch')
            index = row.get('stage_index')
            require(type(index) is int and 0 <= index < len(stages) and index not in used_indices, 'invalid or reused test stage index')
            used_indices.append(index); stage = stages[index]
            outcome['original_exit'] = stage.get('raw_exit')
            require(stage.get('command') == expected_command(name, device) and stage.get('phase') == name, 'exact single-method test command mismatch')
            require(stage.get('started') is True and stage.get('timed_out') is False and stage.get('stdout_truncated') is False and
                    stage.get('exit') == stage.get('raw_exit') and type(stage.get('raw_exit')) is int and stage['raw_exit'] in (0, 65),
                    'test was unstarted, timed out, truncated or lacks genuine terminal exit')
            require(row.get('cleanup_confirmed') is True, 'case app/runner cleanup unconfirmed')
            _case_timing(report, name, stage)
            _capture_extraction(report, row, stage, blobs, manifest)
            _extraction_and_cleanup(report, name, row, stage, blobs, manifest)
            status = _summary(summary, case, stage, device)
            require(stage['raw_exit'] == (0 if status == 'passed' else 65), 'test command exit contradicts structured summary')
            _test_tree(strict_json(blobs[row['tests_file']]), case, status)
            outcome['duration_seconds'] = _lifecycle(blobs[row['lifecycle_file']], case, status, stage)
            require(not recorded_timeout(blobs[row['diagnostics_file']].decode('utf-8', errors='strict')), 'console records timeout')
            require(global_valid, 'receipt provenance, timing, evidence or cleanup is incomplete')
            require((status == 'passed') == (observation['crownStatus'] == 'moved_downward'),
                    'static Crown result contradicts genuine XCTest outcome; touch cannot satisfy Crown')
            outcome['crown_status'] = observation['crownStatus']; outcome['touch_status'] = observation['touchStatus']
            outcome['result'] = status
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, UnicodeError, RecursionError, OverflowError) as error:
            outcome['errors'].append(str(error)[:500])
        result['cases'].append(outcome)
    if used_indices != sorted(used_indices):
        result['errors'].append('test methods executed out of required order')
        for outcome in result['cases']: outcome['result'] = 'incomplete'
    expected_indices = {row.get('stage_index') for row in rows if isinstance(row, dict) and type(row.get('stage_index')) is int} if isinstance(rows, list) else set()
    extra_tests = [i for i, stage in enumerate(stages) if isinstance(stage, dict) and isinstance(stage.get('command'), list) and
                   stage['command'] and isinstance(stage['command'][0], str) and Path(stage['command'][0]).name == 'xcodebuild' and
                   any(arg in ('test', 'test-without-building') for arg in stage['command'][1:]) and i not in expected_indices]
    if extra_tests:
        result['errors'].append('extra, repeated or unassigned test invocation')
        for outcome in result['cases']: outcome['result'] = 'incomplete'
    results = [row['result'] for row in result['cases']]
    result['complete'] = not result['errors'] and all(value in ('passed', 'failed') for value in results)
    result['result'] = 'failed' if 'failed' in results else 'passed' if result['complete'] else 'incomplete'
    result['incomplete_cases'] = [row['name'] for row in result['cases'] if row['result'] == 'incomplete']
    return result


def load_result(report_path, evidence_dir=None, *, expected_source=None, expected_budget=None, expected_binding=None):
    path = Path(report_path)
    raw = _safe_read(path.parent, path.name, MAX_RECEIPT_BYTES)
    report = strict_json(raw)
    if expected_binding is not None:
        require(isinstance(report,dict) and isinstance(report.get('source'),dict) and
                all(report['source'].get(k)==v for k,v in expected_binding.items()),
                'receipt source/ref/workflow/run differs from this exact job')
    return validate_result(report, evidence_dir or path.parent, expected_source=expected_source, expected_budget=expected_budget)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('evidence_directory', nargs='?')
    parser.add_argument('--evidence-dir')
    args = parser.parse_args(argv)
    try:
        from job_budget import load
        from atomic_json import write_json
        budget = load()
        budget.admit('Independent Watch Crown result validation', 60, minimum=60, cleanup=0, phase='validation')
        started = time.monotonic()
        from watch_crown_contract import binding
        admitted = {**binding(os.environ), 'workflow_sha256': hashlib.sha256(Path(WORKFLOW).read_bytes()).hexdigest()}
        result = load_result(args.report, args.evidence_dir or args.evidence_directory,
                             expected_budget=budget.record, expected_binding=admitted)
        require(time.monotonic()-started < 60, 'validation exceeded 60-second reserve')
    except (ValueError, KeyError, IndexError, AttributeError, OSError, TypeError, UnicodeError, RecursionError, RuntimeError, OverflowError) as error:
        result = incomplete_result(str(error)[:500])
    try:
        from atomic_json import write_json
        write_json(Path(args.evidence_dir or args.evidence_directory or Path(args.report).parent)/'validation.json', result, limit=16_384)
    except (ValueError, OSError, TypeError) as error:
        result = incomplete_result('validation receipt could not be retained: ' + str(error)[:500])
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result['result'] == 'passed' and result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
