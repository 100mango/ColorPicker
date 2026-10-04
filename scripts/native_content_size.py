"""Touch-owned system text-size execution; no default external process runner.

Normal-size tests run first. Only the existing Chinese/layout cases below are
repeated under an actually read-back system setting on the same owned device.
"""
import json
import subprocess
from pathlib import Path
from bounded_process import run_captured
from simulator_content_size import LARGEST, probe

WATCH_CASES = (
    'testChineseColorEditorSave',
    'testOfficialAccessibilityHomeAndColorEditor',
    'testOfficialAccessibilitySavedListSendAndCancel',
)
VISION_CASES = {
    'chinese': ('testChinesePasteAndPrecisionControls',),
    'canvas-audit': ('testOfficialAccessibilityEmptyAndPastedCanvas',),
}


def applicable_cases(kind, case=None):
    if kind == 'watch': return WATCH_CASES
    if kind == 'vision': return VISION_CASES.get(case, ())
    return ()


class TouchSizeRunner:
    """A UI callback must prove its group AND capture reader have finished."""
    def __init__(self, ui_runner, command_runner=run_captured):
        self.ui_runner = ui_runner
        self.command_runner = command_runner
        self.cleanup_unconfirmed = False

    def __call__(self, command, timeout, *, output_limit, tail_limit, echo=False):
        if self.cleanup_unconfirmed:
            raise RuntimeError('Prior owned command/capture cleanup is unconfirmed')
        operation = {'command': command, 'timeout_seconds': timeout, 'cleanup_confirmed': False}
        if command[:2] == ['xcodebuild', 'test-without-building']:
            # Dispatch can raise while the app/capture child is still alive.
            # Persist the in-memory stop latch before calling it; report writes
            # are evidence only and cannot be required to enforce cleanup safety.
            self.cleanup_unconfirmed = True
            code, text, detail = self.ui_runner(command, timeout)
            for key in ('process_group_gone','capture_reader_finished','elapsed_seconds','wall_elapsed_seconds'):
                operation[key]=detail.get(key)
            confirmed = detail.get('process_group_gone') is True and detail.get('capture_reader_finished') is True
            operation['cleanup_confirmed'] = confirmed
            if confirmed: self.cleanup_unconfirmed = False
        else:
            try:
                result = self.command_runner(command, timeout=timeout, text=True)
                code = result.returncode
                text = (result.stdout or '') + (result.stderr or '')
                # run_captured returns only after the complete owned group exits.
                operation.update(cleanup_confirmed=True, state='completed')
            except subprocess.TimeoutExpired as error:
                code, text = 124, 'Owned command exceeded its bounded deadline'
                operation.update(cleanup_confirmed=getattr(error, 'cleanup_confirmed', False) is True,
                                 state='timeout')
            except Exception as error:
                code, text = 1, type(error).__name__
                operation.update(state='execution_error')
        if operation['cleanup_confirmed'] is not True:
            self.cleanup_unconfirmed = True
        encoded = text.encode('utf-8')
        if len(encoded) > output_limit:
            text = encoded[-min(output_limit, tail_limit):].decode('utf-8', errors='replace')
            operation['output_limit_exceeded'] = True
            if code == 0: code = 1
        operation['exit'] = code
        return code, text, operation


def verify_summary(summary, device_id, platform, count):
    expected = {'passedTests': count, 'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}
    if summary.get('result') != 'Passed' or summary.get('totalTestCount') != count:
        raise RuntimeError('Largest-text result did not execute every required case')
    for key, value in expected.items():
        if summary.get(key) != value: raise RuntimeError('Largest-text result '+key+' mismatch')
    rows = summary.get('devicesAndConfigurations')
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError('Largest-text result has an unexpected destination/configuration')
    row = rows[0]
    for key, value in expected.items():
        if row.get(key) != value: raise RuntimeError('Largest-text destination '+key+' mismatch')
    device = row.get('device', {})
    if device.get('deviceId') != device_id or device.get('platform') != platform:
        raise RuntimeError('Largest-text XCTest used another device or clone')
    if device.get('osVersion') != '27.0' or device.get('architecture') != 'arm64':
        raise RuntimeError('Largest-text XCTest used another runtime/architecture')
    if summary.get('testFailures'): raise RuntimeError('Largest-text result retains failures')
    return {'totalTestCount': count, **expected, 'device': device}


def run_largest(device, report_path, command, contract, cases, runner, *, timeout=600):
    """Preserve exact setting status; no exit-code alias means restored/passed."""
    report = probe(device, report_path, command, timeout, runner=runner, expected_ui=contract)
    if runner.cleanup_unconfirmed or report.get('cleanup_unconfirmed'):
        return report
    if (report.get('status') != 'largest_ui_passed' or report.get('ui_executed') is not True
            or report.get('ui_exit') != 0 or report.get('observed_largest') != LARGEST
            or report.get('restore_verified') is not True):
        return report
    result_path = command[command.index('-resultBundlePath') + 1]
    code, text, operation = runner(
        ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', result_path],
        30, output_limit=500_000, tail_limit=500_000)
    report['summary_operation'] = operation
    if runner.cleanup_unconfirmed:
        report.update(cleanup_unconfirmed=True, status='owned_process_cleanup_unconfirmed')
    else:
        try:
            if code: raise RuntimeError('Largest-text result summary command failed')
            report['verified_results'] = verify_summary(json.loads(text), device, contract['platform'], len(cases))
        except (RuntimeError, ValueError) as error:
            report.update(status='largest_ui_result_unqualified', summary_error=str(error))
    from atomic_json import write_json
    write_json(report_path, report, limit=48*1024)
    return report


def qualified(report):
    return (report.get('status') == 'largest_ui_passed' and report.get('restore_verified') is True
            and report.get('ui_executed') is True and report.get('ui_exit') == 0
            and report.get('observed_largest') == LARGEST and bool(report.get('verified_results'))
            and not report.get('cleanup_unconfirmed'))
