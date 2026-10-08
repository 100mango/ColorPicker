"""Bind failed, owned Vision UI results for attachment diagnostics only.

These records are never deferred qualifications. A fresh-result origin is recorded
before the actual producer, and its completed process/capture stage is bound to
an immutable original before shutdown. Failed live status is never rewritten.
"""
import copy
import datetime
import math
import os
from pathlib import Path
import re
import time
import uuid

from native_text_rows import validate as validate_row
from vision_suites import CASES

BUNDLE = 'build/vision-largest-text.xcresult'
FAILURE_STATUSES = ('largest_ui_failed', 'restore_readback_failed')
CONTRACT = {'project': 'TouchColorVision.xcodeproj', 'scheme': 'TouchColorVision',
            'derived_data': 'build/vision-tests', 'test_bundle': 'TouchColorVisionUITests',
            'platform': 'visionOS Simulator'}
STAGE_KEYS = ('command', 'exit', 'started', 'timed_out', 'process_group_gone',
              'capture_reader_finished', 'reader_errors', 'cleanup_error', 'started_at', 'finished_at')


def require(value, message):
    if not value:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def canonical(value):
    return (isinstance(value, str) and Path(value).is_absolute()
            and str(Path(value)) == value == os.path.normpath(value))


def contract_root(command, contract, cases, sha, device, runtime, row_binding):
    row = validate_row(row_binding, sha=sha)
    require(row['platform'] == 'vision' and row['phase'] == 'system-largest'
            and cases == [CASES[row['case']][0]], 'Diagnostic case differs from exact largest row')
    require(isinstance(contract, dict) and set(contract) == set(CONTRACT) | {'root'}
            and all(contract.get(key) == value for key, value in CONTRACT.items())
            and canonical(contract.get('root')), 'Diagnostic product/root contract changed')
    require(isinstance(device, str) and str(uuid.UUID(device)).upper() == device
            and runtime == 'com.apple.CoreSimulator.SimRuntime.xrOS-27-0', 'Diagnostic device/runtime changed')
    require(isinstance(command, list) and all(isinstance(part, str) for part in command)
            and command[:2] == ['xcodebuild', 'test-without-building'], 'Diagnostic execution command changed')
    for flag, expected in (('-project', CONTRACT['project']), ('-scheme', CONTRACT['scheme']),
                           ('-derivedDataPath', CONTRACT['derived_data']), ('-configuration', 'Debug'),
                           ('-resultBundlePath', BUNDLE),
                           ('-destination', 'platform=' + CONTRACT['platform'] + ',id=' + device),
                           ('-parallel-testing-enabled', 'NO'), ('-collect-test-diagnostics', 'never'),
                           ('-test-timeouts-enabled', 'YES'),
                           ('-default-test-execution-time-allowance', '180'),
                           ('-maximum-test-execution-time-allowance', '360'),
                           ('-maximum-concurrent-test-simulator-destinations', '1')):
        require(command.count(flag) == 1 and command.index(flag) + 1 < len(command)
                and command[command.index(flag) + 1] == expected, 'Diagnostic execution option changed: ' + flag)
    require(command.count('CODE_SIGNING_ALLOWED=NO') == 1 and command.count('ARCHS=arm64') == 1
            and [part for part in command if part.startswith('-only-testing:')] ==
            ['-only-testing:TouchColorVisionUITests/VisionWorkflowTests/' + cases[0]]
            and not any(part.startswith('-skip-testing:') for part in command), 'Diagnostic execution scope changed')
    paired = {'-project', '-scheme', '-derivedDataPath', '-configuration', '-resultBundlePath', '-destination',
              '-parallel-testing-enabled', '-collect-test-diagnostics', '-test-timeouts-enabled',
              '-default-test-execution-time-allowance', '-maximum-test-execution-time-allowance',
              '-maximum-concurrent-test-simulator-destinations'}
    index = 2
    while index < len(command):
        token = command[index]
        if token in paired:
            index += 2
        else:
            require(token in ('CODE_SIGNING_ALLOWED=NO', 'ARCHS=arm64') or token.startswith('-only-testing:'),
                    'Unsupported diagnostic execution option')
            index += 1
    return Path(contract['root'])


def begin_largest_execution(command, contract, cases, sha, device, runtime, *, row_binding):
    """Record the absent exact output before one owned actual-UI invocation."""
    cases = list(cases)
    root = contract_root(command, contract, cases, sha, device, runtime, row_binding)
    require(root.resolve(strict=True) == root and root.is_dir(), 'Diagnostic source root is aliased or missing')
    target = root / BUNDLE
    require(target.parent.resolve(strict=True) == target.parent and target.parent.is_dir()
            and not target.exists() and not target.is_symlink(), 'Diagnostic result is stale, aliased, or already exists')
    info = root.stat()
    return {'schema': 1, 'role': 'largest', 'source_sha': sha, 'device': device, 'runtime': runtime,
            'native_text_row': copy.deepcopy(row_binding), 'path': str(target), 'absent_before_execution': True,
            'source_root': {'path': str(root), 'device': info.st_dev, 'inode': info.st_ino},
            'invocation': uuid.uuid4().hex, 'checked_at': time.time()}


def timestamp(value):
    require(isinstance(value, str), 'Diagnostic execution timestamp missing')
    parsed = datetime.datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'Diagnostic execution timestamp has no timezone')
    result = parsed.timestamp()
    require(finite(result) and result > 0, 'Diagnostic execution timestamp invalid')
    return result


def validate_diagnostic(setting, *, sha, device, runtime, role='largest'):
    """Pure receipt validation; never infers test success or adopts scratch."""
    return _validate_diagnostic(setting, sha=sha, device=device, runtime=runtime, role=role, check_bundle=True)


def _validate_diagnostic(setting, *, sha, device, runtime, role='largest', check_bundle):
    from vision_offline_result import verify_bundle_proof
    require(role == 'largest' and isinstance(setting, dict) and 'deferred_result' not in setting,
            'Diagnostic binding cannot replace or retry a deferred qualification')
    binding = setting.get('diagnostic_result')
    require(isinstance(binding, dict) and type(binding.get('schema')) is int and binding['schema'] == 1
            and binding.get('role') == role and binding.get('purpose') == 'attachments_only'
            and binding.get('qualification_eligible') is False and type(binding.get('attempted')) is bool,
            'Missing explicit nonqualifying diagnostic binding')
    require(binding.get('source_sha') == sha and binding.get('device') == device and binding.get('runtime') == runtime
            and setting.get('device') == device and setting.get('runtime') == runtime,
            'Diagnostic source/device/runtime changed')
    root = contract_root(binding.get('command'), binding.get('contract'), binding.get('cases'), sha, device, runtime,
                         binding.get('native_text_row'))
    require(setting.get('native_text_row') == binding['native_text_row']
            and setting.get('expected_ui_contract') == binding['contract'], 'Diagnostic live row/product contract changed')
    require(setting.get('status') in FAILURE_STATUSES and setting.get('ui_executed') is True
            and type(setting.get('ui_exit')) is int and -255 <= setting['ui_exit'] <= 255
            and not setting.get('verified_results'),
            'Diagnostic role was not an executed, failed, cleanup-confirmed UI result')
    require((setting['status'] == 'largest_ui_failed' and setting['ui_exit'] != 0) or
            (setting['status'] == 'restore_readback_failed' and setting.get('restore_verified') is False),
            'Diagnostic live failure is contradictory')
    operations = setting.get('operations')
    require(isinstance(operations, list), 'Diagnostic live operations missing')
    actual = [item.get('operation') for item in operations if isinstance(item, dict) and item.get('label') == 'actual_ui']
    require(len(actual) == 1 and isinstance(actual[0], dict), 'Diagnostic actual execution is missing or ambiguous')
    operation = actual[0]
    require(operation.get('command') == binding['command'] and operation.get('command_started') is True
            and type(operation.get('exit')) is int and operation['exit'] == setting['ui_exit']
            and operation.get('cleanup_confirmed') is True and operation.get('process_group_gone') is True
            and operation.get('capture_reader_finished') is True, 'Diagnostic actual-UI ownership changed')
    stage = binding.get('execution_stage')
    require(isinstance(stage, dict) and set(stage) == set(STAGE_KEYS)
            and stage['command'] == binding['command'] and stage['started'] is True
            and type(stage['exit']) is int and stage['exit'] == setting['ui_exit']
            and type(stage['timed_out']) is bool and (not stage['timed_out'] or stage['exit'] == 124)
            and stage['process_group_gone'] is True and stage['capture_reader_finished'] is True
            and stage['reader_errors'] == [] and stage['cleanup_error'] is None,
            'Diagnostic producer/capture cleanup is not confirmed')
    start, finish = timestamp(stage['started_at']), timestamp(stage['finished_at'])
    require(start < finish and binding.get('started_at') == start and binding.get('finished_at') == finish,
            'Diagnostic execution lifetime changed')
    origin = binding.get('execution_origin')
    expected = {'schema', 'role', 'source_sha', 'device', 'runtime', 'native_text_row', 'path',
                'absent_before_execution', 'source_root', 'invocation', 'checked_at'}
    require(isinstance(origin, dict) and set(origin) == expected and type(origin['schema']) is int
            and origin['schema'] == 1 and origin['role'] == role and origin['source_sha'] == sha
            and origin['device'] == device and origin['runtime'] == runtime
            and origin['native_text_row'] == binding['native_text_row'] and origin['path'] == str(root / BUNDLE)
            and origin['absent_before_execution'] is True and isinstance(origin['invocation'], str)
            and re.fullmatch('[0-9a-f]{32}', origin['invocation']) and finite(origin['checked_at'])
            and 0 < origin['checked_at'] <= start,
            'Diagnostic result lacks an exact pre-execution fresh-path origin')
    source = origin['source_root']
    require(isinstance(source, dict) and set(source) == {'path', 'device', 'inode'}
            and source['path'] == str(root) and type(source['device']) is int and source['device'] >= 0
            and type(source['inode']) is int and source['inode'] > 0, 'Diagnostic source-root origin changed')
    if check_bundle:
        bundle = binding.get('bundle')
        verify_bundle_proof(bundle, original=True)
        require(bundle['path'] == str(root / BUNDLE) and bundle['source_root'] == origin['source_root'],
                'Diagnostic original bundle/source-root binding changed')
    return binding


def prepare_failed_largest(setting, command, contract, cases, sha, device, runtime, stage, *, row_binding):
    """Attach one diagnostic binding without changing any live outcome fields."""
    from vision_offline_result import bundle_identity
    require(isinstance(setting, dict) and not setting.get('cleanup_unconfirmed')
            and 'diagnostic_result' not in setting and 'deferred_result' not in setting,
            'Diagnostic result is already bound or eligible for deferred qualification')
    require(isinstance(stage, dict) and all(key in stage for key in STAGE_KEYS), 'Incomplete diagnostic execution stage')
    cases = list(cases)
    root = contract_root(command, contract, cases, sha, device, runtime, row_binding)
    # Validate every execution fact before reading any original bundle bytes.
    candidate = {'schema': 1, 'purpose': 'attachments_only', 'qualification_eligible': False,
                 'role': 'largest', 'attempted': False, 'source_sha': sha, 'device': device, 'runtime': runtime,
                 'native_text_row': copy.deepcopy(row_binding), 'cases': cases, 'command': list(command),
                 'contract': dict(contract), 'started_at': timestamp(stage['started_at']),
                 'finished_at': timestamp(stage['finished_at']),
                 'execution_stage': {key: copy.deepcopy(stage[key]) for key in STAGE_KEYS},
                 'execution_origin': copy.deepcopy(stage.get('vision_result_origin'))}
    # The first full identity is bounded by the existing 15-second identity cap.
    # It is never evidence of a passing execution.
    trial = dict(setting, diagnostic_result=candidate)
    origin = candidate['execution_origin']
    require(isinstance(origin, dict) and origin.get('absent_before_execution') is True,
            'Missing diagnostic pre-execution origin')
    _validate_diagnostic(trial, sha=sha, device=device, runtime=runtime, check_bundle=False)
    candidate['bundle'] = bundle_identity(root, BUNDLE)
    validate_diagnostic(trial, sha=sha, device=device, runtime=runtime)
    setting['diagnostic_result'] = candidate
    return candidate
