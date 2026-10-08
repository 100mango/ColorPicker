"""Small offline parser prototype. Does not launch processes or drive UI."""
import json
import re
import uuid

CASE = '__WatchWorkflowTests_testTouchCopyEntryTouchAndCrownRemainResponsive_'
UI_CAP = 262144
LOG_CAP = 65536
REPORT_CAP = 8192
EVENT_CAP = 14
_SCOPE = re.compile(r'^WATCH_MAIN_ACTOR_SCOPE nonce=([0-9A-F-]{36})$', re.M)
_EVENT = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3,6}) [A-Za-z]{1,4} '
    r'TouchColor\[([1-9][0-9]{0,9}):[0-9a-fA-F]+\] '
    r'\[com\.mango\.touchColor\.WatchDiagnostics:editor\] '
    r'WATCH_MAIN_ACTOR event=(baseline|copy_enter|copy_exit|copy_beat) '
    r'case=' + CASE + r' nonce=([0-9A-F-]{36}) seq=([0-6]) elapsed_ms=([0-9]{1,5})$')


def summarize(native_output, oslog_output):
    """PID comes from the OSLog compact header, never message text or App self-report."""
    report = {'schema': 1, 'state': 'not-observed', 'baseline_samples': 0,
              'copy_action_enter_observed': False, 'copy_action_exit_observed': False,
              'copy_mainactor_samples': 0, 'pid': None, 'events': [],
              'product_qualified': False, 'deadlock_established': False}
    if not isinstance(native_output, bytes) or not isinstance(oslog_output, bytes):
        raise TypeError('byte inputs required')
    if len(native_output) > UI_CAP or len(oslog_output) > LOG_CAP:
        report.update(state='unavailable', reason='input-byte-limit');return report
    try:
        native = native_output.decode('utf8', 'strict');lines = oslog_output.decode('utf8', 'strict').splitlines()
    except UnicodeError:
        report.update(state='unavailable', reason='unsupported-text-encoding');return report
    scopes = _SCOPE.findall(native)
    if len(scopes) != 1:
        report.update(reason='single-test-scope-not-observed');return report
    nonce = scopes[0]
    try:
        if str(uuid.UUID(nonce)).upper() != nonce:raise ValueError('invalid')
    except ValueError:
        report.update(state='unavailable', reason='invalid-test-scope');return report
    events=[];pids=set();seen=set();previous={}
    for line in lines:
        if len(line.encode('utf8')) > 512 or 'WATCH_MAIN_ACTOR' not in line:continue
        m = _EVENT.fullmatch(line)
        if not m:continue
        moment, pid, event, observed_nonce, sequence, elapsed = m.groups()
        if observed_nonce != nonce:continue
        pid, sequence, elapsed = int(pid), int(sequence), int(elapsed)
        if pid > 2147483647:continue
        if (event == 'baseline' and (sequence > 5 or elapsed > 12000)
            or event == 'copy_beat' and (sequence == 0 or elapsed > 14000)
            or event in ('copy_enter','copy_exit') and (sequence != 0 or elapsed > 14000)):
            report.update(state='unavailable', reason='event-contract-mismatch');return report
        if len(events) == EVENT_CAP:
            report.update(state='unavailable', reason='event-count-limit');return report
        identity=(event,sequence)
        if identity in seen or (event in previous and elapsed < previous[event]):
            report.update(state='unavailable', reason='duplicate-or-reversed-event');return report
        seen.add(identity);previous[event]=elapsed;pids.add(pid)
        events.append({'os_timestamp_unzoned':moment,'event':event,'sequence':sequence,'elapsed_ms':elapsed})
    if len(pids) > 1:
        report.update(state='unavailable', reason='multiple-target-processes');return report
    if not events:
        report.update(reason='target-events-not-observed');return report
    report.update(state='observed',pid=next(iter(pids)),pid_provenance='OSLog compact process header',nonce=nonce,events=events,
                  baseline_samples=sum(x['event']=='baseline' for x in events),
                  copy_action_enter_observed=any(x['event']=='copy_enter' for x in events),
                  copy_action_exit_observed=any(x['event']=='copy_exit' for x in events),
                  copy_mainactor_samples=sum(x['event']=='copy_beat' for x in events))
    report['interpretation'] = ('mainactor-scheduled-at-copy-sample-instants' if report['copy_mainactor_samples']
        else 'baseline-observed-copy-scheduling-not-observed' if report['baseline_samples']
        else 'action-markers-observed-scheduling-not-observed')
    if len(json.dumps(report,indent=2).encode()) > REPORT_CAP:raise RuntimeError('report-byte-limit')
    return report
