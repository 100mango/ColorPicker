"""Bounded Vision result reads after confirmed shutdown.

All summary and attachment readers share one byte-verified private input per
role. Original bundles stay immutable; failed-run diagnostics remain failed.
No UI rerun, reader retry, filename exception, or per-operation cap expansion.
"""
import argparse
import contextlib
import signal
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from atomic_json import write_json
from job_budget import enabled_budget, fail_record, BudgetExhausted, METADATA_RESERVE, RESERVES, VISION_RESERVES, STARTUP_MARGIN, EXPECTED_MINUTES
from bounded_process import run_captured
from simulator_content_size import LARGEST

BUNDLE = 'build/vision-largest-text.xcresult'
HOSTED_BUNDLE = 'build/vision-tests.xcresult'
NORMAL_BUNDLE = 'build/vision-ui.xcresult'
BUNDLES = {'hosted': HOSTED_BUNDLE, 'normal': NORMAL_BUNDLE, 'largest': BUNDLE}
REPORT_KEYS = {'hosted': 'vision_hosted_result', 'normal': 'vision_normal_result', 'largest': 'largest_system_text'}
DEVELOPER_DIR = '/Applications/Xcode_27.app/Contents/Developer'
XCODE_VERSION = 'Xcode 27.0\nBuild version 27A266a'
ATTACHMENT_NAMES = {'hosted':'vision-screenshots', 'normal':'vision-ui-screenshots', 'largest':'vision-largest-text-screenshots'}
# These are inside the existing evidence300 envelope, never an extra tail.
FINAL_RESERVE = 15 + 5 + 5  # original byte guard, scratch deletion, durable metadata
PROCESS_RESERVE = 20  # bounded_process's two ten-second group-stop intervals
SUMMARY_NAMES = {'hosted': 'vision-summary.json', 'normal': 'vision-ui-summary.json', 'largest': 'vision-largest-text-summary.json'}
HOSTED_COUNT = 42
CASES = ('testChinesePasteAndPrecisionControls', 'testOfficialAccessibilityEmptyAndPastedCanvas')


def require(value, message):
    if not value: raise ValueError(message)


def finite(value): return type(value) in (int, float) and math.isfinite(value)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate structured result key')
            result[key] = value
        return result
    def invalid(value): raise ValueError('Nonfinite structured result number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def validate_contract(command, contract, cases, sha, device, *, role="largest"):
    from vision_suites import CASES as ROWS
    require(role in ("normal", "largest"), "Unknown Vision UI result role")
    require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{40}', sha), 'Missing exact tested source SHA')
    expected = {'project': 'TouchColorVision.xcodeproj', 'scheme': 'TouchColorVision',
                'derived_data': 'build/vision-tests', 'test_bundle': 'TouchColorVisionUITests', 'platform': 'visionOS Simulator'}
    require(all(contract.get(key) == value for key, value in expected.items()), 'Offline qualification is Vision-only')
    allowed = CASES if role == 'largest' else tuple(value[0] for value in ROWS.values())
    require(len(cases) == 1 and cases[0] in allowed, 'Unexpected deferred Vision case scope')
    require(command[:2] == ['xcodebuild', 'test-without-building'] and command.count('-resultBundlePath') == 1
            and command[command.index('-resultBundlePath') + 1] == BUNDLES[role], 'Deferred result bundle differs from executed path')
    require(command.count('-destination') == 1 and command[command.index('-destination') + 1] == 'platform=visionOS Simulator,id=' + device,
            'Deferred destination differs from exact executed device')
    require([part for part in command if part.startswith('-only-testing:')] ==
            ['-only-testing:TouchColorVisionUITests/VisionWorkflowTests/' + cases[0]], 'Deferred test selector differs')
    root = Path(contract['root']).resolve(strict=True)
    require(root.is_dir(), 'Missing source root')
    return root


def bundle_identity(root, bundle=BUNDLE, *, clock=time.monotonic, inventory=None):
    """Bound every original byte and file/directory identity, including empty dirs."""
    from vision_result_snapshot import source_binding
    if inventory is not None:
        inventory.clear(); inventory.update(walk_complete=False,observed_files=0,omitted_files=0,records=[])
    limit = 15
    budget = enabled_budget()
    if budget is not None: limit = budget.admit('Bind exact Vision result bytes',limit,minimum=1,cleanup=0)
    return source_binding(root,bundle,deadline=clock()+limit,clock=clock,inventory=inventory)

def bundle_change_provenance(before, after):
    """Bounded per-file observations; never substitute for the full identity gate."""
    def persisted_size(value):
        # Exact atomic_json encoding at the deepest current runtime location.
        # Including both wrapper keys also bounds insertion into the role receipt.
        wrapped = {'vision_hosted_result': {'bundle_change_provenance': value}}
        return len((json.dumps(wrapped, ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode())
    def summary(value):
        if value is None: return {'status': 'not_observed'}
        return {'walk_complete': value['walk_complete'],
                'observed_files': value['observed_files'],
                'retained_files': len(value['records']),
                'omitted_files': value['omitted_files'],
                'identity': value.get('identity')}
    complete = all(value is not None and value['walk_complete'] and
                   value['omitted_files'] == 0 for value in (before, after))
    result = {'schema': 1, 'before': summary(before), 'after': summary(after),
              'inventory_complete': complete, 'details_complete': False,
              'changes': [], 'changes_total': None, 'omitted_changes': None}
    if not complete:
        result['status'] = 'unavailable_incomplete_inventory'
        return result
    old = {entry['path']:entry for entry in before['records']}
    new = {entry['path']:entry for entry in after['records']}
    changed = [path for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path)]
    result.update(status='observed', changes_total=len(changed), omitted_changes=len(changed))
    for path in changed:
        left, right = old.get(path), new.get(path)
        kind = 'added' if left is None else 'removed' if right is None else (
            'content_changed' if (left['sha256'],left['bytes']) != (right['sha256'],right['bytes']) else 'metadata_only')
        item = {'path':path, 'kind':kind,
                'before': {k:v for k,v in left.items() if k!='path'} if left else None,
                'after': {k:v for k,v in right.items() if k!='path'} if right else None}
        if len(result['changes']) >= 8: break
        result['changes'].append(item)
        if persisted_size(result) > 12_000:
            result['changes'].pop(); break
    def finish_fields():
        result['omitted_changes'] = len(changed)-len(result['changes'])
        result['details_complete'] = result['omitted_changes'] == 0
        result['status'] = 'observed' if result['details_complete'] else 'partial_details'
    finish_fields()
    # Bound final fields too: status/count changes can lengthen escaped JSON.
    while result['changes'] and persisted_size(result) > 12_000:
        result['changes'].pop()
        finish_fields()
    if persisted_size(result) > 12_000:
        return {'schema':1, 'status':'unavailable_provenance_bound',
                'inventory_complete':complete, 'details_complete':False,
                'changes':[], 'changes_total':len(changed), 'omitted_changes':len(changed)}
    return result


def prepare(report, command, contract, cases, sha, device, started, finished, *, row_binding):
    root = validate_contract(command, contract, cases, sha, device)
    require(report.get('status') == 'largest_ui_passed' and report.get('device') == device
            and report.get('ui_executed') is True and report.get('ui_exit') == 0
            and report.get('restore_verified') is True and report.get('observed_largest') == LARGEST
            and not report.get('cleanup_unconfirmed') and not report.get('summary_operation'),
            'Largest UI/restoration not ready for offline qualification')
    require(finite(started) and finite(finished) and started < finished, 'Invalid executed result lifetime')
    report['deferred_result'] = {'schema': 1, 'source_sha': sha, 'device': device,
        'command': list(command), 'contract': dict(contract), 'cases': list(cases),
        'started_at': started, 'finished_at': finished, 'bundle': bundle_identity(root), 'attempted': False}
    bind_row(report, row_binding, 'largest')
    report['status'] = 'largest_ui_result_deferred'
    return report


def validate_hosted(command, root, sha, device):
    require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha), 'Missing hosted source identity')
    require(command[:2] == ['xcodebuild','test-without-building'], 'Unexpected hosted command')
    for flag, expected in (('-project','TouchColorVision.xcodeproj'),('-scheme','TouchColorVision'),
                           ('-derivedDataPath','build/vision-tests'),('-resultBundlePath',HOSTED_BUNDLE),
                           ('-destination','platform=visionOS Simulator,id='+device)):
        require(command.count(flag) == 1 and command[command.index(flag)+1] == expected, 'Hosted command identity mismatch')
    require([part for part in command if part.startswith('-only-testing:')] == ['-only-testing:TouchColorVisionTests'],
            'Hosted test scope changed')
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), 'Missing hosted source root')
    return root


def prepare_hosted(command, root, sha, device, runtime, stage, *, row_binding):
    root = validate_hosted(command, root, sha, device)
    require(stage.get('command') == command and type(stage.get('exit')) is int and stage['exit'] in (0,65)
            and stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True
            and stage.get('reader_errors') == [] and stage.get('cleanup_error') is None,
            'Hosted execution did not complete with confirmed cleanup')
    def timestamp(value):
        parsed = datetime.datetime.fromisoformat(value)
        require(parsed.tzinfo is not None, 'Hosted timestamp has no timezone')
        return parsed.timestamp()
    started, finished = timestamp(stage['started_at']), timestamp(stage['finished_at'])
    require(started < finished, 'Incomplete hosted command lifetime')
    result = {'device':device, 'runtime':runtime, 'execution_exit':stage['exit'], 'status':'hosted_result_deferred',
            'deferred_result':{'schema':1,'source_sha':sha,'device':device,'root':str(root),'command':list(command),
                'count':HOSTED_COUNT,'started_at':started,'finished_at':finished,
                'bundle':bundle_identity(root,HOSTED_BUNDLE),'attempted':False}}
    bind_row(result, row_binding, 'hosted')
    return result


def bind_row(report, binding, role):
    from native_text_rows import validate, vision_roles
    validate(binding, sha=report['deferred_result']['source_sha'])
    require(role in vision_roles(binding), 'Deferred role does not belong to exact row phase')
    if role != 'hosted':
        from vision_suites import CASES as ROWS
        require(report['deferred_result']['cases'] == [ROWS[binding['case']][0]], 'Deferred method differs from exact row')
    report['deferred_result']['native_text_row'] = dict(binding)
    report['deferred_result']['role'] = role


def prepare_normal(command, contract, cases, sha, device, runtime, stage, *, row_binding):
    root = validate_contract(command, contract, cases, sha, device, role='normal')
    require(stage.get('command') == command and type(stage.get('exit')) is int and stage['exit'] in (0,65)
            and stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True
            and stage.get('reader_errors') == [] and stage.get('cleanup_error') is None,
            'Normal Vision execution did not complete with confirmed cleanup')
    def timestamp(value):
        parsed = datetime.datetime.fromisoformat(value)
        require(parsed.tzinfo is not None, 'Normal Vision timestamp has no timezone')
        return parsed.timestamp()
    started, finished = timestamp(stage['started_at']), timestamp(stage['finished_at'])
    require(started < finished, 'Incomplete normal command lifetime')
    result = {'device': device, 'runtime': runtime, 'execution_exit': stage['exit'], 'status': 'normal_result_deferred',
              'deferred_result': {'schema': 1, 'source_sha': sha, 'device': device, 'command': list(command),
                  'contract': dict(contract), 'cases': list(cases), 'started_at': started, 'finished_at': finished,
                  'bundle': bundle_identity(root, NORMAL_BUNDLE), 'attempted': False}}
    bind_row(result, row_binding, 'normal')
    return result


def normal_qualified(report):
    return (report.get('status') == 'normal_result_passed' and type(report.get('execution_exit')) is int
            and report['execution_exit'] == 0 and bool(report.get('verified_results')) and not report.get('cleanup_unconfirmed'))


def role_qualified(report, role):
    from native_content_size import qualified
    return {'hosted': hosted_qualified, 'normal': normal_qualified, 'largest': qualified}[role](report)


def hosted_qualified(report):
    return (report.get('status') == 'hosted_result_passed' and type(report.get('execution_exit')) is int
            and report['execution_exit'] == 0 and bool(report.get('verified_results')) and not report.get('cleanup_unconfirmed'))


def pending(report):
    return (report.get('status') == 'largest_ui_result_deferred' and report.get('restore_verified') is True
            and report.get('ui_executed') is True and type(report.get('ui_exit')) is int and report['ui_exit'] == 0
            and report.get('observed_largest') == LARGEST and not report.get('cleanup_unconfirmed')
            and isinstance(report.get('deferred_result'), dict) and report['deferred_result'].get('attempted') is False)


def shutdown_proven(stage, device, cleanup_unconfirmed):
    require(not cleanup_unconfirmed, 'Owned process cleanup is unconfirmed; no offline command')
    require(isinstance(stage, dict) and stage.get('command') == ['xcrun', 'simctl', 'shutdown', device]
            and type(stage.get('exit')) is int and stage['exit'] == 0 and stage.get('started', True) is True
            and stage.get('process_group_gone') is True and stage.get('capture_reader_finished') is True
            and stage.get('reader_errors') == [] and stage.get('cleanup_error') is None
            and not stage.get('budget_incomplete'), 'Owned Vision shutdown was not confirmed successful')


def verify_offline_summary(summary, binding, device, role='largest'):
    from native_content_size import verify_summary
    count = HOSTED_COUNT if role == 'hosted' else len(binding['cases'])
    for key in ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures', 'totalTestCount'):
        require(type(summary.get(key)) is int, 'Missing or noninteger result count')
    require(summary.get('testFailures') == [], 'Missing or contradictory failure inventory')
    rows = summary.get('devicesAndConfigurations')
    require(isinstance(rows, list) and len(rows) == 1, 'Ambiguous summary destination/configuration')
    for key in ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures'):
        require(type(rows[0].get(key)) is int, 'Missing or noninteger destination count')
    require(rows[0].get('testPlanConfiguration') == {'configurationId': '1', 'configurationName': 'Test Scheme Action'},
            'Summary configuration differs from executed result')
    start, finish = summary.get('startTime'), summary.get('finishTime')
    require(finite(start) and finite(finish) and binding['started_at'] - 0.001 <= start < finish <= binding['finished_at'] + 0.001,
            'Summary is stale, incomplete or outside the executed result lifetime')
    return verify_summary(summary, device, 'visionOS Simulator', count)


def evidence_deadline():
    """One controller-owned absolute deadline, inherited by every role."""
    now = time.monotonic()
    if os.environ.get('TOUCHCOLOR_BUDGET_PHASE') != 'evidence':
        return now + VISION_RESERVES['evidence']  # Portable tests only; workflow requires evidence.
    deadline = float(os.environ.get('TOUCHCOLOR_EVIDENCE_DEADLINE_MONOTONIC', 'nan'))
    require(finite(deadline) and 0 < deadline <= now + VISION_RESERVES['evidence'],
            'Missing or invalid shared evidence deadline')
    return deadline


def admit_read(label, seconds, deadline, reserve=FINAL_RESERVE + PROCESS_RESERVE):
    require(finite(deadline), 'Missing absolute evidence deadline')
    if deadline - time.monotonic() < seconds + reserve:
        raise BudgetExhausted('Shared evidence deadline cannot reserve '+label+' and final cleanup')
    budget = enabled_budget()
    if budget is not None:
        budget.admit(label, seconds, minimum=seconds, cleanup=reserve)
    return seconds


class OfflineInterrupted(BaseException):
    pass


@contextlib.contextmanager
def owned_interrupts():
    """Unwind through existing owned-process cleanup, including actual TERM/INT."""
    previous = {}; interrupted = []
    def stop(signum, frame):
        interrupted.append(signum)
        if len(interrupted) == 1:
            raise OfflineInterrupted('Offline Vision interrupted by '+signal.Signals(signum).name)
        # A second signal cannot interrupt the already-bounded final cleanup.
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, stop)
    try: yield
    finally:
        for signum, handler in previous.items(): signal.signal(signum, handler)


READER_LIMIT = 64 * 1024 * 1024
READER_RECEIPT = 'touchcolor-vision-reader/receipt.json'
READER_KEYS = {'schema','developer_dir','xcode_version','version_command','selection_command','path',
               'identity','context','version_observation','selection','verified_at','verification'}


def file_bytes_identity(path, deadline, *, maximum=READER_LIMIT, executable=False):
    """No aliases, links, oversized input or changing bytes in a local identity."""
    path = Path(path)
    require(time.monotonic() < deadline, 'Reader identity deadline exhausted')
    require(path.is_absolute() and path == path.resolve(strict=True), 'Reader identity path is not canonical')
    def identity(info):
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum,
                'Reader identity is not a bounded single-link regular file')
        return {'device':info.st_dev,'inode':info.st_ino,'mode':info.st_mode,'bytes':info.st_size,
                'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}
    before = identity(path.lstat())
    require(not executable or os.access(path,os.X_OK), 'Reader is not executable')
    digest=hashlib.sha256(); data=[]; total=0
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        require(identity(os.fstat(stream.fileno())) == before, 'Reader changed before open')
        while True:
            require(time.monotonic() < deadline, 'Reader byte verification deadline exhausted')
            chunk=stream.read(1024*1024)
            if not chunk:break
            total+=len(chunk);require(total<=maximum, 'Reader byte bound exceeded')
            digest.update(chunk)
            if maximum<=16384:data.append(chunk)
        require(identity(os.fstat(stream.fileno())) == before, 'Reader changed during hashing')
    require(identity(path.lstat()) == before and total == before['bytes'] and path.resolve(strict=True)==path, 'Reader changed after hashing')
    require(time.monotonic() < deadline, 'Reader identity returned late')
    return {**before,'sha256':digest.hexdigest()}, b''.join(data)


def reader_context(root, deadline):
    from job_budget import load
    from native_text_rows import from_environment
    root=Path(root).resolve(strict=True);temporary=Path(os.environ.get('RUNNER_TEMP',''))
    require(temporary.is_absolute() and temporary==temporary.resolve(strict=True)
            and temporary.is_dir() and not temporary.is_relative_to(root), 'Missing canonical runner-local receipt root')
    require(os.environ.get('DEVELOPER_DIR')==DEVELOPER_DIR, 'Selected developer directory changed')
    sha=os.environ.get('GITHUB_SHA','');binding=from_environment('vision',sha)
    budget=load(root/'build/job-budget.json')
    require(budget.record['platform']=='vision' and budget.record['lane']==binding['lane'], 'Reader budget row changed')
    run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
    require(re.fullmatch('[1-9][0-9]*',run) and re.fullmatch('[1-9][0-9]*',attempt), 'Missing exact reader run/attempt')
    identity,_=file_bytes_identity(root/'build/job-budget.json',deadline,maximum=8192)
    def directory(path):
        info=path.stat();return {'path':str(path),'device':info.st_dev,'inode':info.st_ino}
    return {'source_sha':sha,'run_id':run,'run_attempt':attempt,'native_text_row':binding,
            'source_root':directory(root),'runner_temp':directory(temporary),
            'job_budget_identity':identity,'started_epoch':budget.record['started_epoch'],
            'started_monotonic':budget.record['started_monotonic'],
            'work_deadline':budget.record['started_monotonic']+1500},budget


def prepare_reader(root=Path('.'), *, version_observation=Path('/tmp/touchcolor-platform-xcode.txt'), invoke=run_captured):
    """One early documented lookup, before any Vision native driver is admitted."""
    start=time.monotonic();context,budget=reader_context(root,start+5)
    budget.admit('Prepare same-VM Vision reader',30,minimum=30,cleanup=30)
    require(budget.remaining('work')>=60, 'Early reader work reserve exhausted')
    owner=Path(context['runner_temp']['path'])/Path(READER_RECEIPT).parent
    owner.mkdir(mode=0o700)  # Exclusive attempt: stale/duplicate preparation never retries.
    target=owner/'receipt.json';finished=False
    try:
        require(not Path(version_observation).is_symlink(), 'Aliased Xcode observation file')
        version_path=Path(version_observation).resolve(strict=True)
        identity,raw=file_bytes_identity(version_path,min(context['work_deadline'],time.monotonic()+5),maximum=4096)
        require(raw==(XCODE_VERSION+'\n').encode()
                and identity['mtime_ns']/1e9 >= context['started_epoch'], 'Missing fresh exact preflight Xcode observation')
        started=time.monotonic();deadline=started+30
        require(deadline<=context['work_deadline']-30, 'Full early lookup allowance does not fit')
        try:result=invoke(['xcrun','--find','xcresulttool'],timeout=30,text=False)
        except BaseException as error:
            fail_record('Early Vision reader selection failed',phase='work',cleanup_unconfirmed=getattr(error,'cleanup_confirmed',False) is not True)
            raise
        ended=time.monotonic()
        require(ended<deadline and result.returncode==0 and result.stderr==b''
                and isinstance(result.stdout,bytes) and len(result.stdout)<=4096, 'Early reader lookup failed or returned late')
        tool=result.stdout.decode('utf-8').strip();path=Path(tool)
        require(path.is_absolute() and path.is_relative_to(Path(DEVELOPER_DIR)) and path.name=='xcresulttool',
                'Reader is outside the selected toolchain')
        identity_deadline=min(context['work_deadline'],time.monotonic()+5)
        tool_identity,_=file_bytes_identity(path,identity_deadline,executable=True)
        require(file_bytes_identity(version_path,identity_deadline,maximum=4096)[0]==identity, 'Preflight version observation changed')
        value={'schema':2,'developer_dir':DEVELOPER_DIR,'xcode_version':XCODE_VERSION,
               'version_command':['xcodebuild','-version'],'selection_command':['xcrun','--find','xcresulttool'],
               'path':tool,'identity':tool_identity,'context':context,
               'version_observation':{'path':str(version_path),'identity':identity},
               'selection':{'started_at':started,'finished_at':ended,'deadline':deadline,'timeout_seconds':30,'cleanup_confirmed':True},
               'verified_at':time.monotonic()}
        persistence_deadline=min(context['work_deadline'],time.monotonic()+5)
        write_json(target,value,limit=16384)
        persisted,raw=file_bytes_identity(target,persistence_deadline,maximum=16384)
        require(strict_json(raw)==value and time.monotonic()<persistence_deadline, 'Reader receipt persistence returned late')
        finished=True
        return value
    finally:
        if not finished:target.unlink(missing_ok=True)


def validate_file_identity(value):
    require(isinstance(value,dict) and set(value)=={'device','inode','mode','bytes','mtime_ns','ctime_ns','sha256'}
            and all(type(value.get(key)) is int for key in ('device','inode','mode','bytes','mtime_ns','ctime_ns'))
            and value['device']>=0 and value['inode']>0 and stat.S_ISREG(value['mode'])
            and 0<value['bytes']<=READER_LIMIT and value['mtime_ns']>0 and value['ctime_ns']>0
            and isinstance(value.get('sha256'),str) and re.fullmatch('[0-9a-f]{64}',value['sha256']), 'Invalid reader byte identity')


def validate_reader_receipt(value, binding):
    require(isinstance(value,dict) and set(value)==READER_KEYS-{'verification'} and type(value.get('schema')) is int
            and value['schema']==2 and value['developer_dir']==DEVELOPER_DIR and value['xcode_version']==XCODE_VERSION
            and value['version_command']==['xcodebuild','-version'] and value['selection_command']==['xcrun','--find','xcresulttool'],
            'Reader differs from the early selected source-owned toolchain')
    tool=value['path'];context=value['context'];selection=value['selection'];version=value['version_observation']
    require(isinstance(tool,str) and Path(tool).is_absolute() and str(Path(tool))==os.path.normpath(tool)
            and Path(tool).is_relative_to(Path(DEVELOPER_DIR)) and Path(tool).name=='xcresulttool', 'Invalid selected reader path')
    validate_file_identity(value['identity'])
    require(bool(value['identity']['mode'] & 0o111), 'Selected reader was not executable')
    require(isinstance(context,dict) and set(context)=={'source_sha','run_id','run_attempt','native_text_row',
            'source_root','runner_temp','job_budget_identity','started_epoch','started_monotonic','work_deadline'}
            and context['source_sha']==binding['source_sha'] and context['native_text_row']==binding,
            'Reader receipt belongs to another source or row')
    from native_text_rows import validate
    validate(binding)
    require(all(isinstance(context[k],str) and re.fullmatch('[1-9][0-9]*',context[k]) for k in ('run_id','run_attempt')),
            'Unknown reader run/attempt')
    if os.environ.get('GITHUB_SHA')==binding['source_sha']:
        for key,name in (('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
            require(not os.environ.get(name) or context[key]==os.environ[name], 'Reader receipt belongs to another run/attempt')
    validate_file_identity(context['job_budget_identity'])
    for key in ('source_root','runner_temp'):
        item=context[key]
        require(isinstance(item,dict) and set(item)=={'path','device','inode'} and isinstance(item['path'],str)
                and Path(item['path']).is_absolute() and os.path.normpath(item['path'])==item['path']
                and type(item['device']) is int and item['device']>=0 and type(item['inode']) is int and item['inode']>0,
                'Unknown reader instance directory')
    require(not Path(context['runner_temp']['path']).is_relative_to(Path(context['source_root']['path'])), 'Receipt is inside source')
    require(all(finite(context[k]) and context[k]>0 for k in ('started_epoch','started_monotonic','work_deadline'))
            and context['work_deadline']<=context['started_monotonic']+1500, 'Reader extended immutable work budget')
    require(isinstance(selection,dict) and set(selection)=={'started_at','finished_at','deadline','timeout_seconds','cleanup_confirmed'}
            and selection['timeout_seconds']==30 and type(selection['timeout_seconds']) is int and selection['cleanup_confirmed'] is True
            and all(finite(selection[k]) for k in ('started_at','finished_at','deadline'))
            and context['started_monotonic']<=selection['started_at']<=selection['finished_at']<selection['deadline']<=context['work_deadline']
            and selection['deadline']==selection['started_at']+30
            and selection['deadline']<=context['work_deadline']-30
            and finite(value['verified_at']) and selection['finished_at']<=value['verified_at']<context['work_deadline'],
            'Early reader selection exceeded its immutable deadline')
    require(isinstance(version,dict) and set(version)=={'path','identity'} and isinstance(version['path'],str)
            and Path(version['path']).is_absolute() and os.path.normpath(version['path'])==version['path'], 'Missing version observation provenance')
    validate_file_identity(version['identity'])
    require(version['identity']['bytes']<=4096 and version['identity']['mtime_ns']/1e9>=context['started_epoch']
            and version['identity']['sha256']==hashlib.sha256((XCODE_VERSION+'\n').encode()).hexdigest(), 'Changed Xcode observation bytes')


def verify_reader_file(reader, deadline):
    started=time.monotonic();limit=min(deadline-FINAL_RESERVE,started+5)
    require(os.environ.get('DEVELOPER_DIR')==reader['developer_dir']==DEVELOPER_DIR, 'Selected environment changed before read')
    identity,_=file_bytes_identity(reader['path'],limit,executable=True)
    require(identity==reader['identity'], 'Selected reader identity/bytes changed')
    return {'identity':identity,'started_at':started,'finished_at':time.monotonic(),'deadline':limit}


def selected_reader(root, binding, deadline):
    """Use only this VM's early receipt; no offline resolver or version process."""
    started=time.monotonic();context,_=reader_context(root,min(deadline-FINAL_RESERVE,started+5))
    target=Path(context['runner_temp']['path'])/READER_RECEIPT
    require(target.parent.stat().st_mode & 0o777==0o700, 'Unsafe reader receipt owner')
    _,raw=file_bytes_identity(target,min(deadline-FINAL_RESERVE,time.monotonic()+5),maximum=16384)
    value=strict_json(raw);validate_reader_receipt(value,binding)
    require(value['context']==context, 'Foreign or changed VM/source/run/attempt/row receipt')
    require(file_bytes_identity(value['version_observation']['path'],min(deadline-FINAL_RESERVE,time.monotonic()+5),maximum=4096)[0]==value['version_observation']['identity'], 'Changed preflight Xcode observation')
    value['verification']=verify_reader_file(value,deadline)
    require(value['verified_at']<=started and time.monotonic()<deadline-FINAL_RESERVE, 'Late reader selection receipt')
    return value


def validate_reader_guard(guard, reader, deadline):
    require(isinstance(guard,dict) and set(guard)=={'identity','started_at','finished_at','deadline'}
            and guard['identity']==reader['identity'] and all(finite(guard[k]) for k in ('started_at','finished_at','deadline'))
            and reader['verified_at']<=guard['started_at']<=guard['finished_at']<guard['deadline']<=deadline
            and guard['deadline']<=guard['started_at']+5, 'Missing bounded same-byte reader guard')



def qualify(report, report_path, shutdown_stage, *, sha, device, runtime, runner,
            cleanup_unconfirmed=False, persist=None, summary_path=None, summary_runner=run_captured,
            attachment_runner=run_captured, role='largest', deadline=None, diagnostic=False):
    with owned_interrupts():
        return _qualify(report, report_path, shutdown_stage, sha=sha, device=device, runtime=runtime,
            runner=runner, cleanup_unconfirmed=cleanup_unconfirmed, persist=persist,
            summary_path=summary_path, summary_runner=summary_runner, attachment_runner=attachment_runner,
            role=role, deadline=deadline, diagnostic=diagnostic)


def _qualify(report, report_path, shutdown_stage, *, sha, device, runtime, runner,
             cleanup_unconfirmed, persist, summary_path, summary_runner, attachment_runner, role, deadline, diagnostic):
    """One verified disposable input for every xcresult read; originals stay closed."""
    from vision_result_snapshot import create
    before_files = after_files = None
    snapshot = source = root = binding = verified = None
    succeeded = False
    evidence_collected = False
    isolation = None
    def flush():
        write_json(report_path, report, limit=48*1024)
        if persist is not None: persist()
    def fail(error):
        if diagnostic:
            report['diagnostic_status']='incomplete'
            report.setdefault('diagnostic_error',str(error) or type(error).__name__)
        else:
            report['status'] = role+'_result_unqualified' if role in ('hosted','normal') else 'largest_ui_result_unqualified'
            report.setdefault('summary_error', str(error) or type(error).__name__)
        if isinstance(error, (OfflineInterrupted, KeyboardInterrupt, SystemExit)):
            runner.interrupted = True
            report['interrupted'] = True
    try:
        shutdown_proven(shutdown_stage, device, cleanup_unconfirmed or runner.cleanup_unconfirmed)
        require(not getattr(runner,'interrupted',False), 'Prior offline operation was interrupted')
        require(not report.get('cleanup_unconfirmed'), 'Current result cleanup is unconfirmed')
        require(role in BUNDLES, 'Unknown offline result role')
        if diagnostic:
            from vision_diagnostic_result import validate_diagnostic
            binding=validate_diagnostic(report,sha=sha,device=device,runtime=runtime,role=role)
            require(binding.get('attempted') is False and 'deferred_result' not in report,
                    'Diagnostic attempt is consumed or overlaps a deferred result')
        else:
            eligible = (report.get('status') == role+'_result_deferred' and isinstance(report.get('deferred_result'),dict)
                        and report['deferred_result'].get('attempted') is False) if role in ('hosted','normal') else pending(report)
            require(eligible, 'No eligible unattempted deferred Vision result')
            binding = report['deferred_result']
        require(report.get('offline_shutdown_verified') == {'device':device,'runtime':runtime,'state':'Shutdown'},
                'Driver never confirmed exact shutdown; no offline command')
        from native_text_rows import validate, vision_roles
        row_binding = validate(binding.get('native_text_row'), sha=sha)
        require(binding.get('role') == role and role in vision_roles(row_binding), 'Deferred role/phase binding changed')
        if role != 'hosted':
            from vision_suites import CASES as ROWS
            require(binding.get('cases') == [ROWS[row_binding['case']][0]], 'Deferred method/row binding changed')
        require(binding.get('schema') == 1 and binding.get('source_sha') == sha and binding.get('device') == device
                and report.get('device') == device and report.get('runtime') == runtime,
                'Deferred source/device/runtime identity changed')
        if role == 'hosted':
            require(type(binding.get('count')) is int and binding['count'] == HOSTED_COUNT, 'Hosted count contract changed')
            root = validate_hosted(binding['command'],binding['root'],sha,device)
        else: root = validate_contract(binding['command'],binding['contract'],binding['cases'],sha,device,role=role)
        bundle = BUNDLES[role]
        binding['attempted'] = True
        isolation = report['read_isolation'] = {'schema':1, 'source_sha':sha, 'device':device, 'runtime':runtime,
            'role':role, 'purpose':'attachments_only' if diagnostic else 'qualification',
            'native_text_row':dict(row_binding), 'original':dict(binding['bundle']),
            'original_postguard_confirmed':False, 'completed':False, 'started_at':time.monotonic()}
        flush()  # Durable consumption before every possible offline operation.
        deadline = evidence_deadline() if deadline is None else deadline
        isolation['evidence_deadline_monotonic'] = deadline
        def read(label, command, seconds, limit=500_000):
            require(not runner.cleanup_unconfirmed, 'Prior owned metadata cleanup is unconfirmed')
            admit_read(label, seconds, deadline)
            operation = {'command':command, 'timeout_seconds':seconds, 'cleanup_confirmed':False, 'state':'running'}
            report.setdefault('offline_operations', []).append({'label':label, 'operation':operation})
            flush()
            try:
                code, text, result = runner(command, seconds, output_limit=limit, tail_limit=limit)
            except BaseException as error:
                confirmed = getattr(error,'cleanup_confirmed',False) is True
                runner.cleanup_unconfirmed = not confirmed
                operation.update(cleanup_confirmed=confirmed, state='interrupted')
                raise
            operation.update(result)
            require(operation.get('cleanup_confirmed') is True and not runner.cleanup_unconfirmed,
                    'Offline metadata process cleanup is unconfirmed')
            require(code == 0 and operation.get('output_limit_exceeded') is not True, label+' failed')
            return text
        inventory = strict_json(read('confirm_shutdown',['xcrun','simctl','list','devices','available','-j'],15))
        matches = [(r,v) for r,values in inventory['devices'].items() for v in values if v.get('udid') == device]
        require(len(matches) == 1 and matches[0][0] == runtime and matches[0][1].get('state') == 'Shutdown'
                and matches[0][1].get('isAvailable') is True, 'Exact owned Vision device is not confirmed Shutdown')
        observed_sha = read('confirm_source',['git','-C',str(root),'rev-parse','HEAD'],10,4096).strip()
        require(observed_sha == sha, 'Tested source HEAD changed before offline qualification')
        read('confirm_unchanged_source',['git','-C',str(root),'diff','--exit-code','HEAD','--'],10,4096)
        isolation['reader'] = selected_reader(root,row_binding,deadline)
        admit_read('Original result preguard',15,deadline,FINAL_RESERVE)
        before_files = {"walk_complete":False,"observed_files":0,"omitted_files":0,"records":[]}
        require(bundle_identity(root,bundle,inventory=before_files) == binding['bundle'], 'Completed result bundle changed before offline qualification')
        admit_read('Verified result snapshot',15,deadline,FINAL_RESERVE)
        snapshot = create(root,bundle,binding['bundle'],isolation,min(deadline-FINAL_RESERVE,time.monotonic()+15))
        source = snapshot.input_binding
        isolation['snapshot_input_binding'] = source
        flush()
        def extract(name, command, seconds, invoke):
            require(not runner.cleanup_unconfirmed, 'Prior reader cleanup is unconfirmed')
            admit_read('Private input safety guard',15,deadline,FINAL_RESERVE+PROCESS_RESERVE+seconds)
            snapshot.verify(min(deadline-FINAL_RESERVE-PROCESS_RESERVE-seconds,time.monotonic()+15),require_input=diagnostic or name=='summary_operation')
            operation = {'command':command, 'timeout_seconds':seconds, 'cleanup_confirmed':False, 'state':'not_started',
                         'input_guard':dict(isolation['snapshot']['reader_input_guard'])}
            report[name] = operation
            started=False
            try:
                admit_read(name,seconds,deadline,FINAL_RESERVE+PROCESS_RESERVE+(20 if name=='summary_operation' else 0))
                operation.update(state='running',started_at=time.monotonic()); flush()
                admit_read(name,seconds,deadline,FINAL_RESERVE+PROCESS_RESERVE+(20 if name=='summary_operation' else 0))
                operation['reader_guard']=verify_reader_file(isolation['reader'],deadline)
                admit_read(name,seconds,deadline,FINAL_RESERVE+PROCESS_RESERVE+(20 if name=='summary_operation' else 0))
                started=True
                runner.cleanup_unconfirmed = True
                value = invoke(command,timeout=seconds,text=False)
                runner.cleanup_unconfirmed = False
                operation.update(exit=value.returncode,cleanup_confirmed=True,state='completed',finished_at=time.monotonic())
                operation['reader_postguard']=verify_reader_file(isolation['reader'],deadline)
                require(operation['finished_at']<deadline and operation['finished_at']-operation['started_at']<=seconds+PROCESS_RESERVE,
                        'Reader returned beyond its strict deadline')
                return value
            except BaseException as error:
                confirmed = not started or operation.get('cleanup_confirmed') is True or getattr(error,'cleanup_confirmed',False) is True
                runner.cleanup_unconfirmed = not confirmed
                operation.update(command_started=started,exit=124 if isinstance(error,(subprocess.TimeoutExpired,BudgetExhausted)) else 1,
                    cleanup_confirmed=confirmed,state='not_started_budget' if isinstance(error,BudgetExhausted) else
                    'timeout' if isinstance(error,subprocess.TimeoutExpired) else 'interrupted' if isinstance(error,BaseException) and not isinstance(error,Exception) else 'failed')
                raise
        tool = isolation['reader']['path']
        summary_valid=False
        if not diagnostic:
            command = [tool,'get','test-results','summary','--path',str(snapshot.path)]
            try:
                value = extract('summary_operation',command,20 if role=='normal' else 30,summary_runner)
                raw = value.stdout
                require(isinstance(raw,bytes) and len(raw)<=500_000, 'Summary bytes are incomplete or unexpected')
                report['summary_sha256']=hashlib.sha256(raw).hexdigest()
                expected_summary = root/('build/vision-runtime/'+role+'-summary.json')
                require(summary_path is not None and Path(summary_path).resolve() == expected_summary,
                        'Summary output differs from exact role cache')
                require(not expected_summary.exists() and not expected_summary.is_symlink(), 'Summary output is stale or unsafe')
                with expected_summary.open('xb') as stream: stream.write(raw)
                isolation['summary_output']={'path':str(expected_summary),'sha256':report['summary_sha256'],'bytes':len(raw)}
                if value.stderr:
                    report['summary_stderr']=value.stderr[-4096:].decode('utf-8',errors='replace') if isinstance(value.stderr,bytes) else str(value.stderr)[-4096:]
                require(not value.stderr, 'Summary command returned unexpected diagnostics')
                require(value.returncode==0, 'Offline largest summary command failed')
                verified=verify_offline_summary(strict_json(raw),binding,device,role)
                summary_valid=True
            except BaseException as error:
                fail(error)
            require(not runner.cleanup_unconfirmed and not getattr(runner,'interrupted',False)
                    and report.get('summary_operation',{}).get('input_guard',{}).get('input_byte_equivalent') is True,
                    'Summary input safety, reader cleanup or interruption blocks attachment export')
        output=root/'build/evidence'/ATTACHMENT_NAMES[role]
        output.parent.mkdir(parents=True,exist_ok=True)
        require(output.parent.resolve()==output.parent and not output.exists() and not output.is_symlink(),
                'Attachment output is stale or outside the exact evidence root')
        isolation['attachment_output']={'path':str(output)}
        value=extract('attachment_operation',[tool,'export','attachments','--path',str(snapshot.path),'--output-path',str(output)],20,attachment_runner)
        require(value.returncode==0, 'Offline attachment export failed')
        require(isinstance(value.stdout,bytes) and len(value.stdout)<=500_000 and isinstance(value.stderr,bytes)
                and len(value.stderr)<=500_000, 'Attachment diagnostics exceeded bound')
        if value.stderr: report['attachment_stderr']=value.stderr[-4096:].decode('utf-8',errors='replace')
        require(output.is_dir() and not output.is_symlink() and (output/'manifest.json').is_file()
                and not (output/'manifest.json').is_symlink(), 'Missing safe attachment export manifest')
        evidence_collected=True
        if not diagnostic:
            if role in ('hosted','normal'): require(report.get('execution_exit')==0, 'Original '+role+' execution failed')
            require(summary_valid, 'Summary qualification failed; retained attachments are diagnostic only')
        succeeded=True
    except BaseException as error:
        fail(error)
    finally:
        # Even a failed reader/copy must prove the untouched original and delete
        # only this invocation's owned scratch, never a guessed or stale path.
        if before_files is not None:
            try:
                admit_read('Final original result guard',15,deadline,10 if snapshot is not None else 5)
                after_files={"walk_complete":False,"observed_files":0,"omitted_files":0,"records":[]}
                original=bundle_identity(root,BUNDLES[role],inventory=after_files)
                require(original==binding['bundle'], 'Result bundle changed during summary qualification (isolated summary/attachments)')
                isolation['original_postguard']=original
                isolation['original_postguard_confirmed']=True
                isolation['original_postguard_finished_at']=time.monotonic()
            except BaseException as error:
                succeeded=False; evidence_collected=False; fail(error)
        if snapshot is not None:
            try:
                require(not runner.cleanup_unconfirmed, 'Reader cleanup unknown; scratch deletion is unsafe')
                require(snapshot.cleanup(min(deadline-5,time.monotonic()+5)) is True, 'Owned snapshot deletion unconfirmed')
            except BaseException as error:
                succeeded=False; evidence_collected=False; runner.cleanup_unconfirmed=True; fail(error)
        if isolation is not None and isolation.get('snapshot',{}).get('cleanup',{}).get('confirmed') is False:
            runner.cleanup_unconfirmed=True
        if runner.cleanup_unconfirmed or cleanup_unconfirmed:
            report['cleanup_unconfirmed']=True
        if before_files is not None:
            try:
                report['bundle_change_provenance']=bundle_change_provenance(before_files,after_files)
            except BaseException as error:
                succeeded=False; evidence_collected=False; fail(error)
                report['bundle_change_provenance_error']=(str(error) or type(error).__name__)[:240]
        if succeeded and time.monotonic()>=deadline:
            succeeded=False; evidence_collected=False; fail(BudgetExhausted('Qualification exceeded shared evidence deadline'))
        if isolation is not None:
            isolation['lifecycle_finished']=True
            isolation['evidence_collected']=evidence_collected
        if succeeded:
            isolation['completed']=True
            if diagnostic:
                isolation['diagnostic_completed_at']=time.monotonic()
                report['diagnostic_status']='retained'
            else:
                isolation['qualified_at']=time.monotonic()
                report['verified_results']=verified
                report['status']=role+'_result_passed' if role in ('hosted','normal') else 'largest_ui_passed'
        if not succeeded and os.environ.get('TOUCHCOLOR_BUDGET_PHASE') in ('work','cleanup','evidence') and (
                report.get('cleanup_unconfirmed') or report.get('interrupted') or (not evidence_collected and 'attachment_operation' in report)):
            try: fail_record(report.get('diagnostic_error' if diagnostic else 'summary_error','Offline Vision incomplete'),phase=os.environ['TOUCHCOLOR_BUDGET_PHASE'],
                             cleanup_unconfirmed=bool(report.get('cleanup_unconfirmed')))
            except BaseException as error:
                report['failure_record_error']=str(error)[:240]
                if isinstance(error,(OfflineInterrupted,KeyboardInterrupt,SystemExit)): fail(error)
        flush()
        if succeeded and time.monotonic()>=deadline:
            isolation.update(completed=False,evidence_collected=False)
            isolation.pop('qualified_at',None);isolation.pop('diagnostic_completed_at',None)
            report.pop('verified_results',None)
            fail(BudgetExhausted('Qualification persistence exceeded shared evidence deadline'))
            flush()
    return report


def confirm_shutdown(report, stage, *, device, runtime, runner, cleanup_unconfirmed=False):
    """The driver's cleanup tail only confirms shutdown; no xcresult extraction."""
    shutdown_proven(stage, device, cleanup_unconfirmed or runner.cleanup_unconfirmed)
    code, text, operation = runner(['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 15,
                                   output_limit=500_000, tail_limit=500_000)
    report['shutdown_readback_operation'] = operation
    require(code == 0 and operation.get('cleanup_confirmed') is True and not runner.cleanup_unconfirmed
            and operation.get('output_limit_exceeded') is not True, 'Shutdown state readback failed')
    inventory = strict_json(text)
    matches = [(r, value) for r, values in inventory['devices'].items() for value in values if value.get('udid') == device]
    require(len(matches) == 1 and matches[0][0] == runtime and matches[0][1].get('state') == 'Shutdown'
            and matches[0][1].get('isAvailable') is True, 'Exact owned Vision device is not Shutdown')
    report['offline_shutdown_verified'] = {'device': device, 'runtime': runtime, 'state': 'Shutdown'}


def expected_roles(report):
    from native_text_rows import report_binding, vision_roles
    from vision_suites import CASES as ROWS
    binding = report_binding(report)
    roles = vision_roles(binding)
    require(report.get('vision_offline_case') == binding['case'], 'Recorded Vision case differs from current row')
    require(report.get('vision_offline_expected') == roles, 'Expected offline summary scope changed')
    if 'ui_scope' in report:
        scope = report['ui_scope']
        require(scope.get('case') == binding['case'] and scope.get('phase') == binding['phase']
                and scope.get('cases') == [ROWS[binding['case']][0]] and scope.get('fresh_vm') is True
                and scope.get('evidence_bytes') == binding['evidence_bytes'], 'Vision UI scope differs from exact row')
    for role, key in REPORT_KEYS.items():
        setting = report.get(key, {})
        ticket = setting.get('deferred_result')
        diagnostic=setting.get('diagnostic_result')
        if diagnostic is not None:
            from vision_diagnostic_result import validate_diagnostic
            require(ticket is None,'Diagnostic and deferred routes overlap')
            require(diagnostic.get('native_text_row')==binding,'Diagnostic result differs from runtime row')
            validate_diagnostic(setting,sha=report['sha'],device=report['device']['udid'],runtime=report['runtime'],role=role)
        require(role in roles or not setting, 'Foreign Vision phase result cannot satisfy current row')
        if isinstance(ticket, dict):
            require(ticket.get('native_text_row') == binding and ticket.get('role') == role,
                    'Deferred Vision row/phase binding changed')
            if role != 'hosted':
                require(ticket.get('cases') == [ROWS[binding['case']][0]], 'Deferred method differs from current row')
    return roles


def has_unconfirmed_reads(setting):
    operations=[item.get('operation',{}) for item in setting.get('offline_operations',[])]
    operations += [setting[key] for key in ('summary_operation','attachment_operation') if key in setting]
    if any(value.get('state')=='running' or value.get('cleanup_confirmed') is False
           for value in operations): return True
    proof=setting.get('read_isolation',{});snapshot=proof.get('snapshot',{})
    return bool((proof and not proof.get('lifecycle_finished') and not proof.get('completed')) or
                ((snapshot.get('owned_root') or snapshot.get('creation_attempted'))
                 and snapshot.get('cleanup',{}).get('confirmed') is not True))


def fence_incomplete_reads(root=Path('.')):
    """Controller-side fence if a killed qualifier cannot finish its own finally.

    This never adopts/deletes persisted scratch or signals an unowned PID. The
    source-bound pending operation is retained and all later commands are barred.
    """
    path=Path(root)/'build/vision-runtime/runtime.json'
    if not path.is_file(): return False
    require(not path.is_symlink() and path.stat().st_size<=256*1024, 'Unsafe interrupted runtime receipt')
    report=strict_json(path.read_bytes());unclean=False
    for key in REPORT_KEYS.values():
        setting=report.get(key,{})
        if has_unconfirmed_reads(setting):
            setting['cleanup_unconfirmed']=True;unclean=True
    if unclean:
        report['cleanup_unconfirmed']=True;report['result']='failed'
        report.setdefault('error','Offline Vision operation interrupted before confirmed cleanup')
        write_json(path,report,limit=256*1024)
    return unclean


def qualify_for_evidence(root=Path('.')):
    """Both reads share evidence300; neither extends the driver's cleanup130."""
    from native_content_size import TouchSizeRunner, qualified
    root = Path(root).resolve(); runtime_path = root/'build/vision-runtime/runtime.json'
    if not runtime_path.is_file(): return
    runtime_report = strict_json(runtime_path.read_bytes())
    roles = expected_roles(runtime_report)
    require(os.environ.get('TOUCHCOLOR_BUDGET_PHASE') == 'evidence', 'Offline qualification requires the existing evidence phase')
    original_result = runtime_report.get('result')
    records = {role: runtime_report.get(key, {}) for role, key in REPORT_KEYS.items()}
    def no_ui(*args): raise RuntimeError('Offline qualification cannot launch UI tests')
    runner = TouchSizeRunner(no_ui)
    if any(has_unconfirmed_reads(setting) for setting in records.values()):
        runtime_report['cleanup_unconfirmed']=True
        runner.cleanup_unconfirmed=True
    def persist(): write_json(runtime_path, runtime_report, limit=256*1024)
    results = {}; attempted = {}
    deadline = evidence_deadline()
    for role in roles:
        setting = records[role]
        write_json(root/('build/vision-runtime/'+role+'-offline-handled.json'),
                   {'source_sha':runtime_report['sha'],'bundle':BUNDLES[role]}, limit=4096)
        if 'deferred_result' in setting and setting['deferred_result'].get('attempted') is False and not getattr(runner,'interrupted',False):
            qualify(setting, root/('build/vision-runtime/'+role+'-offline-result.json'),
                    runtime_report.get('vision_offline_shutdown',runtime_report.get('vision_largest_shutdown')),
                    sha=runtime_report['sha'], device=runtime_report['device']['udid'], runtime=runtime_report['runtime'], runner=runner,
                    cleanup_unconfirmed=runtime_report.get('cleanup_unconfirmed',False), persist=persist,
                    summary_path=root/('build/vision-runtime/'+role+'-summary.json'), role=role, deadline=deadline)
        elif 'deferred_result' not in setting and isinstance(setting.get('diagnostic_result'),dict) and setting['diagnostic_result'].get('attempted') is False and not getattr(runner,'interrupted',False):
            qualify(setting, root/('build/vision-runtime/'+role+'-offline-result.json'),
                    runtime_report.get('vision_offline_shutdown',runtime_report.get('vision_largest_shutdown')),
                    sha=runtime_report['sha'], device=runtime_report['device']['udid'], runtime=runtime_report['runtime'],runner=runner,
                    cleanup_unconfirmed=runtime_report.get('cleanup_unconfirmed',False),persist=persist,
                    role=role,deadline=deadline,diagnostic=True)
        if runner.cleanup_unconfirmed: runtime_report['cleanup_unconfirmed'] = True
        if getattr(runner,'interrupted',False): runtime_report['interrupted'] = True
        results[role] = role_qualified(setting, role) and not runtime_report.get('cleanup_unconfirmed')
        attempted[role] = setting.get('deferred_result',{}).get('attempted') is True
        if role == 'hosted':
            if results[role]: runtime_report['xctest_summary'] = dict(setting['verified_results'],result='Passed',failures=[])
            elif setting.get('summary_error'): runtime_report.setdefault('summary_error',setting['summary_error'])
    success = all(results.values())
    runtime_report['vision_offline_qualification'] = {'result':'passed' if success else 'failed','roles':results,'attempted':attempted}
    if success and original_result in ('pending_offline_qualification','passed') and not any(runtime_report.get(key) for key in ('error','summary_error','failures')):
        runtime_report['result'] = 'passed'
    else:
        runtime_report['result'] = 'failed'
        first = next((records[role].get('summary_error') for role in roles if not results[role] and records[role].get('summary_error')),
                     'Required offline Vision qualification failed or an earlier error remains')
        runtime_report.setdefault('error',first)
    persist()


def verify_bundle_proof(proof, *, original=False):
    keys={'path','device','inode','sha256','files','directories','bytes','full_tree_sha256','node_identity_sha256'}
    require(isinstance(proof,dict) and set(proof)==keys|({'source_root'} if original else set()),
            'Missing complete bundle identity proof')
    require(isinstance(proof['path'],str) and Path(proof['path']).is_absolute()
            and str(Path(proof['path']))==os.path.normpath(proof['path']), 'Noncanonical bundle proof path')
    require(type(proof['device']) is int and proof['device']>=0
            and type(proof['inode']) is int and proof['inode']>0, 'Missing exact bundle filesystem identity')
    require(all(type(proof[key]) is int and 0<proof[key]<=8192 for key in ('files','directories'))
            and type(proof['bytes']) is int and 0<=proof['bytes']<=256*1024*1024, 'Invalid bounded bundle counts')
    require(all(isinstance(proof[key],str) and re.fullmatch('[0-9a-f]{64}',proof[key])
                for key in ('sha256','full_tree_sha256','node_identity_sha256')), 'Missing complete bundle digests')
    if original:
        source=proof['source_root']
        require(isinstance(source,dict) and set(source)=={'path','device','inode'}
                and isinstance(source['path'],str) and Path(source['path']).is_absolute()
                and str(Path(source['path']))==os.path.normpath(source['path'])
                and type(source['device']) is int and source['device']>=0
                and type(source['inode']) is int and source['inode']>0, 'Missing exact source-root identity')


def verify_isolation(setting, binding, role, runtime, *, diagnostic=False):
    """Independent portable receipt binding, before any success/cache acceptance."""
    if diagnostic:
        from vision_diagnostic_result import validate_diagnostic
        require(validate_diagnostic(setting,sha=binding['source_sha'],device=binding['device'],runtime=runtime,role=role)==binding
                and binding.get('attempted') is True and setting.get('diagnostic_status')=='retained'
                and not role_qualified(setting,role), 'Invalid diagnostic-only result or qualification claim')
    original=binding['bundle']; verify_bundle_proof(original,original=True)
    root=Path(original['source_root']['path'])
    require(original['path']==str(root/BUNDLES[role]) and root.is_absolute(), 'Original source path changed')
    proof=setting.get('read_isolation',{})
    require(setting.get('device')==binding['device'] and setting.get('runtime')==runtime, 'Result device/runtime changed')
    require(proof.get('schema')==1 and proof.get('source_sha')==binding['source_sha']
            and proof.get('device')==binding['device'] and proof.get('runtime')==runtime and proof.get('role')==role
            and proof.get('native_text_row')==binding['native_text_row'] and proof.get('original')==original
            and proof.get('original_postguard')==original and proof.get('original_postguard_confirmed') is True
            and proof.get('completed') is True and proof.get('lifecycle_finished') is True and proof.get('evidence_collected') is True
            and proof.get('purpose')==('attachments_only' if diagnostic else 'qualification'),
            'Missing exact isolated original pre/post proof')
    reader=proof.get('reader',{}); tool=reader.get('path')
    require(isinstance(reader,dict) and set(reader)==READER_KEYS, 'Missing early reader contract')
    validate_reader_receipt({key:value for key,value in reader.items() if key!='verification'},binding['native_text_row'])
    require(reader['context']['source_root']==original['source_root'], 'Reader selected in a different source instance')
    require(reader['verified_at']<=proof['started_at'], 'Reader was selected after offline qualification began')
    validate_reader_guard(reader['verification'],reader,proof['evidence_deadline_monotonic'])
    snapshot=proof.get('snapshot',{}); owned=snapshot.get('owned_root',{}); private=snapshot.get('input_binding',{})
    verify_bundle_proof(private)
    path=private.get('path'); owner=owned.get('path')
    require(snapshot.get('schema')==1 and snapshot.get('state')=='ready' and snapshot.get('verified') is True
            and snapshot.get('copy_limit_seconds')==15 and snapshot.get('cleanup_limit_seconds')==5
            and snapshot.get('original_binding')==original and proof.get('snapshot_input_binding')==private,
            'Missing complete verified snapshot input binding')
    require(isinstance(path,str) and isinstance(owner,str) and Path(owner).is_absolute()
            and str(Path(owner))==os.path.normpath(owner) and re.fullmatch('touchcolor-vision-result-[0-9a-f]{32}',Path(owner).name)
            and not Path(owner).is_relative_to(root) and path==str(Path(owner)/Path(BUNDLES[role]).name)
            and set(owned)=={'path','mode','device','inode'} and owned.get('mode')=='0700'
            and type(owned.get('device')) is int and owned['device']>=0
            and type(owned.get('inode')) is int and owned['inode']>0
            and owned['device']==private['device'] and owned['inode']!=private['inode']
            and (owned['device'],owned['inode']) not in ((original['device'],original['inode']),
                (original['source_root']['device'],original['source_root']['inode']))
            and private['node_identity_sha256']!=original['node_identity_sha256']
            and (private.get('device'),private.get('inode'))!=(original.get('device'),original.get('inode'))
            and all(private.get(key)==original.get(key) for key in ('sha256','files','directories','bytes','full_tree_sha256'))
            and isinstance(private.get('node_identity_sha256'),str) and re.fullmatch('[0-9a-f]{64}',private['node_identity_sha256']),
            'Snapshot path, identity or byte equivalence changed')
    require(snapshot.get('equivalence')=={'verified':True,'ordinary_byte_copy':True,'independent_readback':True,
            'file_identities_disjoint':True,'full_tree_sha256':original['full_tree_sha256']}, 'Snapshot equivalence proof changed')
    guard=snapshot.get('original_guard',{})
    require(guard.get('verified') is True and guard.get('identity')==original, 'Copy changed the original binding')
    cleanup=snapshot.get('cleanup',{})
    require(cleanup.get('confirmed') is True and cleanup.get('deleted') is True and not cleanup.get('error'),
            'Snapshot cleanup was not confirmed before qualification')
    deadline=proof.get('evidence_deadline_monotonic');started=proof.get('started_at')
    require(finite(deadline) and finite(started) and started<deadline<=started+300, 'Evidence window exceeds its source-owned300s cap')
    for operation,cap in ((snapshot,15),(cleanup,5)):
        start,end,limit=operation.get('started_at'),operation.get('finished_at'),operation.get('deadline')
        require(all(finite(value) for value in (start,end,limit,deadline)) and start<=end<=limit<=deadline
                and limit-start<=cap+0.001, 'Isolated copy/cleanup exceeded the shared deadline')
    summary=setting.get('summary_operation',{}); attachment=setting.get('attachment_operation',{})
    output=root/'build/evidence'/ATTACHMENT_NAMES[role]
    operations=[(attachment,[tool,'export','attachments','--path',path,'--output-path',str(output)],20)]
    if not diagnostic:operations.insert(0,(summary,[tool,'get','test-results','summary','--path',path],20 if role=='normal' else 30))
    for operation,command,seconds in operations:
        validate_reader_guard(operation.get('reader_guard'),reader,deadline)
        validate_reader_guard(operation.get('reader_postguard'),reader,deadline)
        require(operation['reader_guard']['finished_at']<=operation['finished_at']<=operation['reader_postguard']['started_at'], 'Reader identity guards do not bracket execution')
        input_guard=operation.get('input_guard',{})
        require(input_guard.get('verified') is True and all(type(input_guard.get(key)) is int and 0<input_guard[key]<=8192
                for key in ('files','directories')) and type(input_guard.get('bytes')) is int and 0<=input_guard['bytes']<=256*1024*1024
                and all(finite(input_guard.get(key)) for key in ('started_at','finished_at','deadline'))
                and input_guard['started_at']<=input_guard['finished_at']<=input_guard['deadline']<=deadline
                and input_guard['deadline']-input_guard['started_at']<=15.001
                and input_guard['finished_at']<=operation.get('started_at',0), 'Missing safe bounded private input guard')
        require(all(finite(operation.get(key)) for key in ('started_at','finished_at'))
                and operation['started_at']<=operation['finished_at']<deadline
                and operation['finished_at']-operation['started_at']<=seconds+PROCESS_RESERVE,
                'Reader operation lifetime exceeds the shared envelope')
        require(operation.get('command')==command and operation.get('timeout_seconds')==seconds
                and operation.get('cleanup_confirmed') is True and type(operation.get('exit')) is int and operation['exit']==0
                and operation.get('state')=='completed', 'Missing successful bounded exact-snapshot reader operation')
    first=attachment if diagnostic else summary
    require(first.get('input_guard',{}).get('input_byte_equivalent') is True
            and first['input_guard'].get('input_binding')==private,
            'Missing strict initial byte-equivalent reader guard')
    require(finite(guard.get('finished_at')) and snapshot['started_at']<=guard['finished_at']<=snapshot['finished_at'],
            'Missing bounded original copy guard lifetime')
    require(snapshot.get('reader_input_guard')==attachment['input_guard']
            and snapshot['finished_at']<=first['input_guard']['started_at'], 'Private input guard stage order changed')
    if not diagnostic:
        require(attachment.get('input_guard',{}).get('input_byte_equivalent') is False
                and summary['finished_at']<=attachment['input_guard']['started_at'], 'Reader stage order changed')
    final_key='diagnostic_completed_at' if diagnostic else 'qualified_at'
    require(all(finite(proof.get(key)) for key in ('original_postguard_finished_at',final_key))
            and attachment['finished_at']<=proof['original_postguard_finished_at']<=cleanup['started_at']
            and cleanup['finished_at']<=proof[final_key]<deadline, 'Reader/final-guard/cleanup stage order changed')
    require(proof.get('attachment_output')=={'path':str(output)}, 'Attachment output differs from exact role')
    if diagnostic:
        require(not summary and not proof.get('summary_output') and 'verified_results' not in setting
                and 'qualified_at' not in proof, 'Diagnostic-only result acquired qualification data')
        return proof
    cache=proof.get('summary_output',{})
    require(cache.get('path')==str(root/('build/vision-runtime/'+role+'-summary.json'))
            and cache.get('sha256')==setting.get('summary_sha256') and type(cache.get('bytes')) is int
            and 0<cache['bytes']<=500_000, 'Raw summary output binding changed')
    return proof


def copy_cached_summary(root=Path('.'), role='largest'):
    root = Path(root).resolve(); runtime_path = root/'build/vision-runtime/runtime.json'
    if not runtime_path.is_file(): return
    runtime_report = strict_json(runtime_path.read_bytes())
    require(role in BUNDLES, 'Unknown cached result role')
    setting = runtime_report.get(REPORT_KEYS[role], {})
    path = root/('build/vision-runtime/'+role+'-summary.json')
    if not path.is_file(): return # Explicitly unqualified metadata remains; never retry extraction.
    require('deferred_result' in setting, 'Cached summary requires its exact deferred result')
    require(not path.is_symlink() and path.stat().st_size <= 500_000, 'Unsafe cached summary')
    raw = path.read_bytes()
    cache=setting.get('read_isolation',{}).get('summary_output',{})
    require(cache=={'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}, 'Cached summary output binding changed')
    if role_qualified(setting,role): verify_isolation(setting,setting['deferred_result'],role,runtime_report['runtime'])
    require(hashlib.sha256(raw).hexdigest() == setting.get('summary_sha256'), 'Cached summary identity changed')
    destination = SUMMARY_NAMES[role]
    (root/'build/evidence'/destination).write_bytes(raw)


def verified_metadata_only_fallback(root, runtime_raw, sha):
    """Accept only retain_metadata's exact bounded fallback, never qualification.

    The earlier runtime may truthfully describe a successful extraction. Once a
    later exporter fails and its raw summary is archived, this artifact cannot
    re-prove that qualification. Permit the authenticated fallback metadata to
    upload, but its final qualification output is explicitly false.
    """
    root = Path(root); path = root/'job-budget.json'
    require(root.is_dir() and not root.is_symlink(), 'Unsafe fallback root')
    require({item.name for item in root.iterdir()} == {'job-budget.json','vision-runtime.json'},
            'Missing raw summary without an exact metadata-only fallback')
    for file, limit in ((path, METADATA_RESERVE), (root/'vision-runtime.json', 1_000_000)):
        info = file.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit,
                'Unsafe or unbounded fallback metadata')
    value = strict_json(path.read_bytes())
    require(type(value.get('schema')) is int and value['schema'] == 1 and value.get('platform') == 'vision',
            'Fallback is not an exact Vision budget record')
    require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha) and value.get('sha') == sha,
            'Fallback source does not match retained runtime')
    run_id = value.get('run_id')
    require(isinstance(run_id,str) and re.fullmatch('[0-9]+',run_id)
            and (not os.environ.get('GITHUB_RUN_ID') or run_id == os.environ['GITHUB_RUN_ID']),
            'Fallback run identity does not match')
    require(type(value.get('minutes')) is int and value['minutes'] == EXPECTED_MINUTES['vision']
            and value.get('reserves') == VISION_RESERVES and all(type(value['reserves'].get(key)) is int for key in RESERVES)
            and type(value.get('startup_margin')) is int and value['startup_margin'] == STARTUP_MARGIN,
            'Fallback budget contract changed')
    require(finite(value.get('started_epoch')) and value['started_epoch'] > 0
            and finite(value.get('started_monotonic')) and value['started_monotonic'] >= 0,
            'Fallback has no valid source-bound clock')
    fallback = value.get('unpublished_partial_evidence')
    require(isinstance(fallback,dict) and isinstance(fallback.get('reason'),str) and 0 < len(fallback['reason']) <= 1000
            and fallback.get('retention') == 'Incomplete export remains runner-local; this artifact contains bounded metadata only',
            'Missing explicit controller fallback provenance')
    require(value.get('result') in ('budget_only_not_test_acceptance','failed_or_incomplete','incomplete'),
            'Fallback incorrectly claims an accepted result')
    retained = value.get('runtime_retention')
    require(isinstance(retained,list), 'Missing runtime retention manifest')
    matches = [item for item in retained if isinstance(item,dict) and item.get('platform') == 'vision']
    require(len(retained) == 1 and len(matches) == 1 and matches[0].get('retained') is True
            and type(matches[0].get('bytes')) is int and matches[0]['bytes'] == len(runtime_raw)
            and matches[0].get('sha256') == hashlib.sha256(runtime_raw).hexdigest(),
            'Fallback retained-runtime hash/size/provenance mismatch')
    failures = value.get('phase_failures')
    require(isinstance(failures,dict) and isinstance(failures.get('evidence'),dict)
            and value.get('result') == 'failed_or_incomplete', 'Missing failed evidence-phase fallback provenance')
    phases = ('work','cleanup','evidence','validation','upload')
    for phase,record in failures.items():
        require(phase in phases and isinstance(record,dict) and record.get('phase') == phase, 'Fallback phase record is contradictory')
    records = list(failures.values()) + [value[key] for key in ('failure','cleanup_failure') if key in value]
    for record in records:
        require(isinstance(record,dict) and type(record.get('schema')) is int and record['schema'] == 1
                and record.get('result') == 'failed_or_incomplete' and record.get('phase') in phases
                and record.get('sha') == sha and record.get('run_id') == run_id
                and isinstance(record.get('reason'),str) and 0 < len(record['reason']) <= 1000
                and type(record.get('cleanup_unconfirmed')) is bool,
                'Invalid fallback failure schema/result/phase/source/run')
    return False


def evidence_complete(root):
    """Every expected summary is mandatory; exact controller fallback stays false."""
    from native_content_size import qualified
    root = Path(root); path = root/'vision-runtime.json'
    expected = os.environ.get('TOUCHCOLOR_JOB_PLATFORM') == 'vision'
    if not path.is_file(): return not expected
    runtime_raw = path.read_bytes(); report = strict_json(runtime_raw)
    roles = expected_roles(report); records = {role: report.get(key, {}) for role, key in REPORT_KEYS.items()}
    if not any('deferred_result' in setting for setting in records.values()): return False
    sha = report.get('sha')
    require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha)
            and (not os.environ.get('GITHUB_SHA') or sha == os.environ['GITHUB_SHA']), 'Deferred evidence source changed')
    proven = {}; shared_deadline = None
    for role in roles:
        setting = records[role]; binding = setting.get('deferred_result')
        if not isinstance(binding,dict):
            if setting.get('diagnostic_status')=='retained':
                verify_isolation(setting,setting['diagnostic_result'],role,report['runtime'],diagnostic=True)
            proven[role] = False; continue
        require(sha == binding.get('source_sha') and report['device']['udid'] == binding.get('device'), 'Deferred source/device changed')
        bundle_name = BUNDLES[role]
        bound_root = binding.get('root') if role=='hosted' else binding.get('contract',{}).get('root')
        require(isinstance(bound_root,str) and Path(bound_root).is_absolute()
                and binding.get('bundle',{}).get('path') == str(Path(bound_root)/bundle_name), 'Deferred result path changed')
        if role=='hosted': require(type(binding.get('count')) is int and binding['count'] == HOSTED_COUNT, 'Deferred hosted count changed')
        summary_path = root/SUMMARY_NAMES[role]
        if summary_path.exists():
            require(hashlib.sha256(summary_path.read_bytes()).hexdigest() == setting.get('summary_sha256'), 'Exported summary changed')
        passed = role_qualified(setting, role)
        proven[role] = passed
        if not passed: continue
        shutdown_proven(report.get('vision_offline_shutdown',report.get('vision_largest_shutdown')),binding['device'],report.get('cleanup_unconfirmed',False))
        require(setting.get('offline_shutdown_verified') == {'device':binding['device'],'runtime':report['runtime'],'state':'Shutdown'}
                and binding.get('attempted') is True, 'Missing confirmed shutdown or consumed qualification attempt')
        isolation=verify_isolation(setting,binding,role,report['runtime'])
        if shared_deadline is None: shared_deadline=isolation['evidence_deadline_monotonic']
        require(shared_deadline==isolation['evidence_deadline_monotonic'], 'Vision roles did not share one evidence deadline')
        summary_path = root/SUMMARY_NAMES[role]
        if not summary_path.exists() and not summary_path.is_symlink(): return verified_metadata_only_fallback(root,runtime_raw,sha)
        raw = summary_path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == setting.get('summary_sha256'), 'Exported summary changed')
        require(verify_offline_summary(strict_json(raw),binding,binding['device'],role) == setting['verified_results'], 'Exported result contradicts qualification')
    outcome = report.get('vision_offline_qualification',{})
    complete = all(proven.values()) and not report.get('cleanup_unconfirmed')
    if complete:
        require(outcome == {'result':'passed','roles':proven,'attempted':dict.fromkeys(roles,True)}, 'Contradictory offline qualification outcome')
    return report.get('result') == 'passed' and complete


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare-reader', 'qualify', 'copy-summary', 'copy-hosted-summary', 'copy-normal-summary']); args = parser.parse_args()
    if args.action == 'prepare-reader': prepare_reader()
    elif args.action == 'qualify':
        if os.environ.get('TOUCHCOLOR_JOB_PLATFORM') == 'vision': qualify_for_evidence()
    else: copy_cached_summary(role={'copy-hosted-summary': 'hosted', 'copy-normal-summary': 'normal', 'copy-summary': 'largest'}[args.action])
