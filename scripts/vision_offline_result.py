"""One Vision largest-text result qualification, after confirmed device shutdown.

Execution/restoration stay live. Only this immutable result's structured summary
is deferred; no UI rerun, summary retry, timeout expansion, or stdout-only pass.
"""
import argparse
import datetime
import hashlib
import shutil
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from atomic_json import write_json
from job_budget import enabled_budget, fail_record, BudgetExhausted, METADATA_RESERVE, RESERVES, STARTUP_MARGIN, EXPECTED_MINUTES
from bounded_process import run_captured
from simulator_content_size import LARGEST

BUNDLE = 'build/vision-largest-text.xcresult'
HOSTED_BUNDLE = 'build/vision-tests.xcresult'
NORMAL_BUNDLE = 'build/vision-ui.xcresult'
BUNDLES = {'hosted': HOSTED_BUNDLE, 'normal': NORMAL_BUNDLE, 'largest': BUNDLE}
REPORT_KEYS = {'hosted': 'vision_hosted_result', 'normal': 'vision_normal_result', 'largest': 'largest_system_text'}
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
    """Bound an immutable completed bundle to original bytes and filesystem node."""
    if inventory is not None:
        inventory.clear()
        inventory.update(walk_complete=False, observed_files=0, omitted_files=0, records=[])
    root = Path(root); path = root / bundle
    require(path.resolve().is_relative_to(root.resolve()) and path.resolve() == path, 'Result path left the exact source root')
    require(path.is_dir() and not path.is_symlink() and (path/'Info.plist').is_file(), 'Missing completed Vision result bundle')
    limit = 15
    budget = enabled_budget()
    if budget is not None: limit = budget.admit('Bind exact Vision result bytes', limit, minimum=1, cleanup=0)
    started = clock(); directory = path.stat(); digest = hashlib.sha256(); count = size = directories = 0
    for folder, dirs, files in os.walk(path, followlinks=False):
        directories += 1
        require(directories <= 8192 and directories+count <= 16384 and clock()-started < limit, 'Result directory traversal exceeded finite bound')
        require(not any((Path(folder)/name).is_symlink() for name in dirs), 'Result bundle contains a symlink directory')
        dirs.sort()
        for name in sorted(files):
            file = Path(folder)/name; before = file.lstat(); count += 1
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'Unsafe result bundle file')
            size += before.st_size
            require(count <= 8192 and size <= 256*1024*1024 and clock()-started < limit, 'Result identity exceeds finite bound')
            relative = file.relative_to(path).as_posix()
            digest.update(relative.encode() + b'\0' + str(before.st_size).encode() + b'\0')
            file_digest = hashlib.sha256() if inventory is not None else None
            with file.open('rb') as stream:
                while chunk := stream.read(65536):
                    require(clock()-started < limit, 'Result identity exceeded finite deadline')
                    digest.update(chunk)
                    if file_digest is not None: file_digest.update(chunk)
            after = file.lstat()
            require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
                    'Result bundle changed during identity read')
            digest.update(b'\0')
            if inventory is not None:
                inventory['observed_files'] += 1
                # Observation only: no extra reads, wider deadline, or changed gate.
                if len(inventory['records']) < 256 and len(relative.encode()) <= 512:
                    inventory['records'].append({'path': relative, 'bytes': before.st_size,
                        'sha256': file_digest.hexdigest(), 'inode': before.st_ino,
                        'mtime_ns': str(before.st_mtime_ns)})
                else: inventory['omitted_files'] += 1
    require(count > 0 and clock()-started < limit, 'Empty result bundle or identity deadline exceeded')
    require((path.stat().st_dev, path.stat().st_ino) == (directory.st_dev, directory.st_ino), 'Result directory replaced')
    result = {'path': str(path), 'device': directory.st_dev, 'inode': directory.st_ino,
              'sha256': digest.hexdigest(), 'files': count, 'directories': directories, 'bytes': size}
    if inventory is not None:
        inventory['walk_complete'] = True
        inventory['identity'] = {key:value for key,value in result.items() if key != 'path'}
    return result

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


def qualify(report, report_path, shutdown_stage, *, sha, device, runtime, runner, cleanup_unconfirmed=False, persist=None, summary_path=None, summary_runner=run_captured, role='largest'):
    """Only offline metadata reads, once, after clean shutdown and state readback."""
    before_files = after_files = None
    try:
        shutdown_proven(shutdown_stage, device, cleanup_unconfirmed or runner.cleanup_unconfirmed)
        require(role in BUNDLES, 'Unknown offline result role')
        eligible = (report.get('status') == role+'_result_deferred' and isinstance(report.get('deferred_result'),dict)
                    and report['deferred_result'].get('attempted') is False) if role in ('hosted', 'normal') else pending(report)
        require(eligible, 'No eligible unattempted deferred Vision result')
        require(report.get('offline_shutdown_verified') == {'device':device,'runtime':runtime,'state':'Shutdown'},
                'Driver never confirmed exact shutdown; no offline command')
        binding = report['deferred_result']
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
        else: root = validate_contract(binding['command'], binding['contract'], binding['cases'], sha, device, role=role)
        bundle = BUNDLES[role]
        # Consume before any command. A failure or timeout must never retry.
        binding['attempted'] = True
        if persist is not None: persist() # Consume durably before any command, including on outer timeout.
        else: write_json(report_path, report, limit=48*1024)
        def read(label, command, seconds, limit=500_000):
            require(not runner.cleanup_unconfirmed, 'Prior owned metadata cleanup is unconfirmed')
            code, text, operation = runner(command, seconds, output_limit=limit, tail_limit=limit)
            report.setdefault('offline_operations', []).append({'label': label, 'operation': operation})
            require(operation.get('cleanup_confirmed') is True and not runner.cleanup_unconfirmed,
                    'Offline metadata process cleanup is unconfirmed')
            require(code == 0 and operation.get('output_limit_exceeded') is not True, label + ' failed')
            return text
        inventory = strict_json(read('confirm_shutdown', ['xcrun', 'simctl', 'list', 'devices', 'available', '-j'], 15))
        matches = [(r, value) for r, values in inventory['devices'].items() for value in values if value.get('udid') == device]
        require(len(matches) == 1 and matches[0][0] == runtime and matches[0][1].get('state') == 'Shutdown'
                and matches[0][1].get('isAvailable') is True, 'Exact owned Vision device is not confirmed Shutdown')
        report['offline_shutdown_verified'] = {'device': device, 'runtime': runtime, 'state': 'Shutdown'}
        observed_sha = read('confirm_source', ['git', '-C', str(root), 'rev-parse', 'HEAD'], 10, 4096).strip()
        require(observed_sha == sha, 'Tested source HEAD changed before offline qualification')
        read('confirm_unchanged_source', ['git', '-C', str(root), 'diff', '--exit-code', 'HEAD', '--'], 10, 4096)
        before_files = {}
        require(bundle_identity(root,bundle,inventory=before_files) == binding['bundle'], 'Completed result bundle changed before offline qualification')
        command = ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(root/bundle)]
        summary_seconds = 20 if role == 'normal' else 30
        operation = {'command': command, 'timeout_seconds': summary_seconds, 'cleanup_confirmed': False}
        report['summary_operation'] = operation
        runner.cleanup_unconfirmed = True
        try:
            value = summary_runner(command, timeout=summary_seconds, text=False)
            # run_captured returns only after its entire owned group exits.
            runner.cleanup_unconfirmed = False
            operation.update(exit=value.returncode, cleanup_confirmed=True, state='completed')
        except (subprocess.TimeoutExpired, BudgetExhausted) as error:
            confirmed = getattr(error, 'cleanup_confirmed', False) is True
            runner.cleanup_unconfirmed = not confirmed
            operation.update(exit=124, cleanup_confirmed=confirmed, state='timeout' if isinstance(error, subprocess.TimeoutExpired) else 'not_started_budget')
            raise
        raw = value.stdout
        require(isinstance(raw, bytes) and len(raw) <= 500_000, 'Summary bytes are incomplete or unexpected')
        report['summary_sha256'] = hashlib.sha256(raw).hexdigest()
        if summary_path is not None: Path(summary_path).write_bytes(raw)
        if value.stderr:
            report['summary_stderr'] = value.stderr[-4096:].decode('utf-8', errors='replace') if isinstance(value.stderr,bytes) else str(value.stderr)[-4096:]
        require(not value.stderr, 'Summary command returned unexpected diagnostics')
        require(value.returncode == 0, 'Offline largest summary command failed')
        verified = verify_offline_summary(strict_json(raw), binding, device, role)
        if role in ('hosted', 'normal'): require(report.get('execution_exit') == 0, 'Original '+role+' execution failed')
        after_files = {}
        require(bundle_identity(root,bundle,inventory=after_files) == binding['bundle'], 'Result bundle changed during summary qualification')
        report['verified_results'] = verified
        report['status'] = role+'_result_passed' if role in ('hosted', 'normal') else 'largest_ui_passed'
    except Exception as error:
        report['status'] = role+'_result_unqualified' if role in ('hosted', 'normal') else 'largest_ui_result_unqualified'
        report.setdefault('summary_error', str(error))
        if runner.cleanup_unconfirmed or cleanup_unconfirmed:
            report['cleanup_unconfirmed'] = True
            if os.environ.get('TOUCHCOLOR_BUDGET_PHASE') in ('work','cleanup','evidence'):
                fail_record('Offline Vision metadata cleanup is unconfirmed', phase=os.environ['TOUCHCOLOR_BUDGET_PHASE'], cleanup_unconfirmed=True)
    finally:
        if before_files is not None:
            report['bundle_change_provenance'] = bundle_change_provenance(before_files,after_files)
        write_json(report_path, report, limit=48*1024)
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
        require(role in roles or not setting, 'Foreign Vision phase result cannot satisfy current row')
        if isinstance(ticket, dict):
            require(ticket.get('native_text_row') == binding and ticket.get('role') == role,
                    'Deferred Vision row/phase binding changed')
            if role != 'hosted':
                require(ticket.get('cases') == [ROWS[binding['case']][0]], 'Deferred method differs from current row')
    return roles


def qualify_for_evidence(root=Path('.')):
    """Both reads share evidence180; neither extends the driver's cleanup130."""
    from native_content_size import TouchSizeRunner, qualified
    root = Path(root); runtime_path = root/'build/vision-runtime/runtime.json'
    if not runtime_path.is_file(): return
    runtime_report = strict_json(runtime_path.read_bytes())
    roles = expected_roles(runtime_report)
    require(os.environ.get('TOUCHCOLOR_BUDGET_PHASE') == 'evidence', 'Offline qualification requires the existing evidence phase')
    original_result = runtime_report.get('result')
    records = {role: runtime_report.get(key, {}) for role, key in REPORT_KEYS.items()}
    def no_ui(*args): raise RuntimeError('Offline qualification cannot launch UI tests')
    runner = TouchSizeRunner(no_ui)
    def persist(): write_json(runtime_path, runtime_report, limit=256*1024)
    results = {}; attempted = {}
    for role in roles:
        setting = records[role]
        write_json(root/('build/vision-runtime/'+role+'-offline-handled.json'),
                   {'source_sha':runtime_report['sha'],'bundle':BUNDLES[role]}, limit=4096)
        if 'deferred_result' in setting and setting['deferred_result'].get('attempted') is False:
            qualify(setting, root/('build/vision-runtime/'+role+'-offline-result.json'),
                    runtime_report.get('vision_offline_shutdown',runtime_report.get('vision_largest_shutdown')),
                    sha=runtime_report['sha'], device=runtime_report['device']['udid'], runtime=runtime_report['runtime'], runner=runner,
                    cleanup_unconfirmed=runtime_report.get('cleanup_unconfirmed',False), persist=persist,
                    summary_path=root/('build/vision-runtime/'+role+'-summary.json'), role=role)
        if runner.cleanup_unconfirmed: runtime_report['cleanup_unconfirmed'] = True
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


def copy_cached_summary(root=Path('.'), role='largest'):
    root = Path(root); runtime_path = root/'build/vision-runtime/runtime.json'
    if not runtime_path.is_file(): return
    runtime_report = strict_json(runtime_path.read_bytes())
    require(role in BUNDLES, 'Unknown cached result role')
    setting = runtime_report.get(REPORT_KEYS[role], {})
    path = root/('build/vision-runtime/'+role+'-summary.json')
    if not path.is_file(): return # Explicitly unqualified metadata remains; never retry extraction.
    require('deferred_result' in setting, 'Cached summary requires its exact deferred result')
    require(not path.is_symlink() and path.stat().st_size <= 500_000, 'Unsafe cached summary')
    raw = path.read_bytes()
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
            and value.get('reserves') == RESERVES and all(type(value['reserves'].get(key)) is int for key in RESERVES)
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
    proven = {}
    for role in roles:
        setting = records[role]; binding = setting.get('deferred_result')
        if not isinstance(binding,dict): proven[role] = False; continue
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
        operation = setting.get('summary_operation',{})
        require(operation.get('cleanup_confirmed') is True and type(operation.get('exit')) is int and operation['exit'] == 0
                and operation.get('timeout_seconds') == (20 if role == 'normal' else 30) and operation.get('state') == 'completed'
                and operation.get('command') == ['xcrun','xcresulttool','get','test-results','summary','--path',str(Path(bound_root)/bundle_name)],
                'Missing successful bounded exact-result summary operation')
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
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['qualify', 'copy-summary', 'copy-hosted-summary', 'copy-normal-summary']); args = parser.parse_args()
    if args.action == 'qualify':
        if os.environ.get('TOUCHCOLOR_JOB_PLATFORM') == 'vision': qualify_for_evidence()
    else: copy_cached_summary(role={'copy-hosted-summary': 'hosted', 'copy-normal-summary': 'normal', 'copy-summary': 'largest'}[args.action])
