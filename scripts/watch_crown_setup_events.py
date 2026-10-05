"""Reconstruct the isolated diagnostic's event-only setup receipt; no processes.

These are past command-completion observations, not a simultaneous/current
Booted-state snapshot, transport connectivity, or continuing readiness proof.
"""
import hashlib
import math
import re

SCHEMA = 2
PROTOCOL = 'owned-pair-boot-events-v1'
BOOT_OUTPUT_LIMIT = 16_384
CAPS = {'list':30, 'create':60, 'pair':60, 'pair_activate':60, 'boot':180, 'bootstatus':420}


def require(value, message):
    if not value:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_setup_window(stage, phase, budget, previous_mono, previous_epoch):
    """Validate effective absolute bounds, not an earlier grant at a later stamp.

    Driver.run clips the nominal grant, then records the stage start, then takes
    min(start+grant, setup cutoff, remaining original pool) as the deadline.
    Scheduling between grant calculation and the stamp may shorten the actual
    window. It cannot move its enforced deadline or permit late completion.
    """
    sm, fm, se, fe, deadline, allowance = (stage.get(k) for k in
        ('started_monotonic','finished_monotonic','started_epoch','finished_epoch','deadline_monotonic','timeout_seconds'))
    require(all(number(v) for v in (sm, fm, se, fe, deadline, allowance,
            phase.get('started_monotonic'), budget.get('started_monotonic'))) and
            phase.get('limit_seconds') == 600, 'missing finite setup clocks')
    cap = CAPS[stage['command'][2]]
    require(stage.get('setup_command_cap_seconds') == cap and 1 <= allowance <= cap,
            'setup command cap changed')
    upper = min(sm + allowance, phase['started_monotonic'] + 600, budget['started_monotonic'] + 1020)
    require(previous_mono <= sm <= fm < deadline <= upper and previous_epoch <= se <= fe and
            abs((fm-sm)-(fe-se)) <= 1 and fe < se + allowance,
            'late, reordered or contradictory setup completion')
    return fm, fe


def validate_setup_events(report, blobs, manifest):
    """Validate the exact planned sequence and reconstruct every claimed event."""
    require(report.get('schema') == SCHEMA and type(report.get('schema')) is int and
            report.get('protocol') == PROTOCOL, 'unsupported setup event protocol')
    require('simulator_uncertainty' not in report and 'work_stop' not in report,
            'setup has unresolved command uncertainty')
    require('setup_readback' not in report, 'event protocol cannot claim a Booted snapshot')
    source = report['source']
    require(all(isinstance(source.get(k), str) for k in ('sha', 'run_id', 'attempt')),
            'missing setup source/run binding')
    owned = report['owned_devices']
    require(isinstance(owned, list) and len(owned) == 2 and
            [x.get('role') for x in owned] == ['phone', 'watch'], 'setup role order changed')
    phone, watch = owned
    require(phone.get('runtime') == 'com.apple.CoreSimulator.SimRuntime.iOS-27-0' and
            watch.get('runtime') == 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0' and
            isinstance(phone.get('deviceTypeIdentifier'), str) and 'iPhone' in phone['deviceTypeIdentifier'] and
            isinstance(watch.get('deviceTypeIdentifier'), str) and '40mm' in watch['deviceTypeIdentifier'],
            'setup runtime/device profile changed')
    for device in owned:
        require(re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', device['udid']) is not None,
                'invalid owned setup UUID')
    require(phone['udid'].lower() != watch['udid'].lower(), 'duplicated owned UUID')
    originals = {x.get('udid', '').lower() for rows in report['initial_inventory']['devices'].values()
                 for x in rows}
    require(not ({phone['udid'].lower(), watch['udid'].lower()} & originals), 'pre-existing owned UUID')
    pair = report['pair']
    require(isinstance(pair.get('id'), str) and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',pair['id']) is not None,
            'invalid owned pair UUID')
    require(pair['id'] not in report['initial_inventory']['pairs']['pairs'], 'pre-existing owned pair')
    before_state = pair['record'].get('state')
    require(before_state in ('(active, connected)', '(active, disconnected)',
                             '(inactive, connected)', '(inactive, disconnected)'),
            'unrecognized pre-activation pair state')
    activate = before_state in ('(inactive, connected)', '(inactive, disconnected)')
    require(type(pair['activation'].get('activation_requested')) is bool and
            pair['activation']['activation_requested'] is activate,
            'activation branch contradicts original pair state')
    for record in (pair['record'], pair['activation']['record']):
        require(record['phone']['udid'] == phone['udid'] and record['watch']['udid'] == watch['udid'],
                'pair role binding changed')
    require(pair['activation']['record']['state'] in ('(active, connected)', '(active, disconnected)'),
            'pair was not observed active before boot')
    selected = [(i, s) for i, s in enumerate(report['stages']) if s.get('phase') == 'setup']
    require(len(selected) == (12 if activate else 11), 'unexpected setup command inventory')
    require([i for i, _ in selected] == list(range(selected[0][0], selected[-1][0]+1)),
            'interleaved command invalidates setup sequence')
    expected = [['xcrun','simctl','list','devices','available','-j'],
                ['xcrun','simctl','list','pairs','-j']]
    for device in owned:
        observed = selected[len(expected)][1]['command']
        require(len(observed) == 6 and re.fullmatch('TouchColor-Crown-'+device['role']+'-[0-9a-f]{8}', observed[3]) is not None,
                'creation name is not the exact owned role')
        expected.append(['xcrun','simctl','create',observed[3],device['deviceTypeIdentifier'],device['runtime']])
    expected += [['xcrun','simctl','pair',watch['udid'],phone['udid']],
                 ['xcrun','simctl','list','pairs','-j']]
    if activate:
        expected.append(['xcrun','simctl','pair_activate',pair['id']])
    expected.append(['xcrun','simctl','list','pairs','-j'])
    for device in owned:
        expected += [['xcrun','simctl','boot',device['udid']],
                     ['xcrun','simctl','bootstatus',device['udid'],'-b']]
    require([s['command'] for _, s in selected] == expected, 'setup sequence changed or extra inventory attempted')
    phase_rows = [p for p in report['phases'] if p['name'] == 'setup']
    require(len(phase_rows) == 1 and phase_rows[0]['limit_seconds'] == 600, 'wrong setup phase envelope')
    phase = phase_rows[0]
    budget = report['budget']
    require(budget['sha'] == source['sha'] and budget['run_id'] == source['run_id'] and
            not budget.get('cleanup_unconfirmed'), 'setup budget binding or cleanup failed')
    previous_mono, previous_epoch = phase['started_monotonic'], phase['started_epoch']
    for (index, stage), command in zip(selected, expected):
        require(stage.get('source_sha') == source['sha'] and stage.get('budget_phase') == 'work',
                'setup stage source/budget phase mismatch')
        require(stage.get('started') is True and type(stage.get('raw_exit')) is int and
                type(stage.get('exit')) is int and stage['raw_exit'] == stage['exit'] == 0 and stage.get('timed_out') is False,
                'setup command lacks genuine timely zero exit')
        require(stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True and
                stage.get('stdout_truncated') is False and not stage.get('reader_errors') and
                not stage.get('cleanup_error') and not stage.get('reported_device_timeout') and
                stage.get('simulator_command_completion') != 'unconfirmed', 'setup command cleanup/output uncertain')
        previous_mono, previous_epoch = validate_setup_window(stage, phase, budget, previous_mono, previous_epoch)
    # Creation/pair IDs must match the actual bounded command-output digests.
    for position, identity in ((2,phone['udid']), (3,watch['udid']), (4,pair['id'])):
        stage = selected[position][1]; raw = (identity+'\n').encode('ascii')
        require(type(stage.get('stdout_bytes')) is int and stage['stdout_bytes'] == len(raw) and
                stage.get('stdout_sha256') == hashlib.sha256(raw).hexdigest(), 'creation/pair output binding mismatch')
    events = []
    for offset, device in zip((len(selected)-4, len(selected)-2), owned):
        boot_index, boot = selected[offset]; status_index, status = selected[offset+1]
        name = 'setup-'+device['role']+'-bootstatus.log'
        require(name in blobs and name in manifest and manifest[name].get('kind') == 'setup_bootstatus' and
                manifest[name].get('case') == device['role'], 'missing role-bound bootstatus evidence')
        raw = blobs[name]
        require(isinstance(raw, bytes) and 0 <= len(raw) <= BOOT_OUTPUT_LIMIT and
                type(status.get('stdout_bytes')) is int and status['stdout_bytes'] == len(raw) and status.get('stdout_sha256') == hashlib.sha256(raw).hexdigest() and
                manifest[name].get('bytes') == len(raw) and manifest[name].get('sha256') == hashlib.sha256(raw).hexdigest(),
                'bootstatus bytes/hash do not match command receipt')
        text = raw.decode('utf-8', errors='strict')
        require(not re.search(r'\b(?:timed? out|time-out|timeout)\b|exceeded execution time allowance|execution time.*exceeded|test may have hung', text, re.I),
                'bootstatus output reports timeout')
        events.append({**{k:device[k] for k in ('role','udid','runtime','deviceTypeIdentifier')},
            'source_sha':source['sha'], 'run_id':source['run_id'], 'attempt':source['attempt'],
            'boot_stage_index':boot_index, 'bootstatus_stage_index':status_index, 'bootstatus_file':name,
            'completed_epoch':status['finished_epoch'], 'completed_monotonic':status['finished_monotonic']})
    expected_proof = {'kind':PROTOCOL, 'inventory':'not_requested', 'simultaneous_state':'unobserved',
                      'connectivity':'unobserved', 'continued_readiness':'unobserved', 'events':events}
    require(report.get('setup_proof') == expected_proof, 'setup proof differs from reconstructed command events')
    first_case = next((s for s in report['stages'] if s.get('phase') in ('actual_cold','isolated_static','rgb_positive') and
                       s.get('command', [])[:2] == ['xcodebuild','test-without-building']), None)
    if first_case is not None:
        require(first_case['started_monotonic'] >= previous_mono and first_case['started_epoch'] >= previous_epoch,
                'test preceded setup completion')
    # The admitted source emits no command between setup and first XCTest.
    # Reject every intervening stage, including absolute-path aliases and
    # wrappers; do not infer safety from a narrow executable-prefix test.
    last_index = selected[-1][0]
    if first_case is not None:
        require(report['stages'][last_index+1] is first_case,
                'unexpected command between setup and first XCTest')
    else:
        require(last_index == len(report['stages'])-1,
                'post-setup commands without an actual first XCTest')
    return events
