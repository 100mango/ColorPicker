"""Live-process console mirror tests; no simulator or capture timing changes."""
import ast
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import types
import unittest
from unittest.mock import patch

import mini_passive_status as status
from test_mini_passive_compatibility import Harness
import mini_passive_compatibility as mini


def decode(raw):
    if raw is None or len(raw) > 512 or not raw.endswith(b'\n'):
        raise AssertionError('Record does not fit one Darwin atomic pipe write')
    return json.loads(raw[len(status.PREFIX):])


def staging_body():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/mini-passive-compatibility.yml'
    stage = path.read_text().split('- name: Stage bounded existing files only', 1)[1].split('- name: Verify upload reserve', 1)[0]
    return textwrap.dedent(stage.split("python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])


class SummaryTests(Harness):
    def generated(self, *, help_timeout=False):
        operation = self.operation()
        with patch.object(status, '_write_nonblocking', return_value=False):
            if help_timeout:
                self.engine.help_duration = 10
                with self.assertRaisesRegex(mini.CaptureFailed, 'absolute-deadline'):
                    operation.run()
            else:
                operation.run()
        return operation.receipt

    def test_actual_generated_timeout_is_help_with_actual_cleanup(self):
        raw = self.generated(help_timeout=True); original = copy.deepcopy(raw)
        result = decode(status.status_line(raw))
        self.assertEqual(result['receipt'], 'bound')
        self.assertEqual(result['phase'], 'help')
        self.assertEqual(result['reason'], 'absolute-deadline')
        self.assertEqual(result['help'], ['owned', -15, True])
        self.assertEqual(result['stream'], [None, None, None])
        self.assertIs(result['cleanup'], True)
        self.assertEqual(result['reader'], 'unconfirmed')
        self.assertIs(result['warmup'], False)
        self.assertEqual((result['sha'], result['run'], result['try']), ('a' * 40, '123', '1'))
        self.assertEqual(raw, original)

    def test_actual_generated_stream_receipt_stays_advisory(self):
        raw = self.generated(); result = decode(status.status_line(raw))
        self.assertEqual(result['phase'], 'stream')
        self.assertIsNone(result['reason'])
        self.assertEqual(result['help'], ['owned', 0, True])
        self.assertEqual(result['stream'], ['owned', -15, True])
        self.assertEqual(result['delivery'], 'best_effort')
        self.assertIs(result['warmup'], False)

    def test_missing_receipt_has_null_phase_results_and_cleanup(self):
        result = decode(status.status_line(None))
        self.assertEqual(result['receipt'], 'missing')
        self.assertEqual((result['sha'], result['run'], result['try']), ('a' * 40, '123', '1'))
        for name in ('phase', 'reason', 'cleanup', 'reader', 'warmup', 'state'):
            self.assertIsNone(result[name])
        self.assertEqual(result['help'], [None, None, None]); self.assertEqual(result['stream'], [None, None, None])

    def test_missing_boolean_fields_are_null_not_inferred_from_exit(self):
        value = self.generated()
        value.pop('host_cleanup_confirmed')
        value['processes']['collector'].pop('host_cleanup_confirmed')
        value['processes']['help']['host_cleanup_confirmed'] = 'true'
        value['processes']['help']['exit'] = True
        result = decode(status.status_line(value))
        self.assertIsNone(result['cleanup'])
        self.assertEqual(result['help'], ['owned', None, None])
        self.assertEqual(result['stream'], ['owned', -15, None])

    def test_actual_false_cleanup_is_not_replaced_with_unknown_or_success(self):
        value = self.generated(); value['host_cleanup_confirmed'] = False
        for row in value['processes'].values(): row['host_cleanup_confirmed'] = False
        result = decode(status.status_line(value))
        self.assertIs(result['cleanup'], False)
        self.assertIs(result['help'][2], False); self.assertIs(result['stream'][2], False)

    def test_unsupported_error_text_and_raw_logs_are_never_printed(self):
        value = self.generated(); private = 'SECRET-PATH\n::warning::' + 'x' * 1000
        value['failure'] = private; value['raw_stream'] = private
        value['processes']['collector']['argv'] = [private]
        line = status.status_line(value)
        self.assertNotIn(b'SECRET', line); self.assertNotIn(b'::warning', line)
        self.assertEqual(decode(line)['reason'], 'other')

    def test_allowlisted_reason_keeps_late_read_distinct_from_generic_deadline(self):
        value = self.generated()
        for reason in ('CaptureFailed: Pipe read returned after its absolute deadline',
                       'Pipe read returned after its absolute deadline'):
            value['failure'] = reason
            self.assertEqual(decode(status.status_line(value))['reason'], 'late-read')

    def test_cancelled_reason_uses_only_actual_typed_signal(self):
        value = self.generated(); value['cancelled_signal'] = 15
        self.assertEqual(decode(status.status_line(value))['reason'], 'cancelled')
        value['cancelled_signal'] = True
        self.assertIsNone(decode(status.status_line(value))['reason'])

    def test_wrong_receipt_sha_run_attempt_or_family_exposes_no_result(self):
        original = self.generated()
        for key, bad in (('source_sha', 'b' * 40), ('workflow_sha', 'b' * 40),
                         ('run_id', '124'), ('run_attempt', '2'), ('device', {'family': 'iPhoneLarge'})):
            with self.subTest(key=key):
                value = copy.deepcopy(original); value[key] = bad
                result = decode(status.status_line(value))
                self.assertEqual(result['receipt'], 'mismatch')
                self.assertIsNone(result['phase']); self.assertIsNone(result['cleanup'])
                self.assertEqual(result['stream'], [None, None, None])

    def test_wrong_current_branch_source_workflow_or_run_context_is_unknown(self):
        raw = self.generated()
        for key, bad in (('GITHUB_REF', 'refs/heads/codex/platform-integration'),
                ('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_REPOSITORY', 'other/repo'),
                ('GITHUB_WORKFLOW_REF', 'other'), ('GITHUB_WORKFLOW_SHA', 'b' * 40),
                ('GITHUB_JOB', 'other'), ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '9' * 21),
                ('RUNNER_ENVIRONMENT', 'self-hosted')):
            with self.subTest(key=key), patch.dict(os.environ, {key: bad}):
                result = decode(status.status_line(raw))
                self.assertEqual(result['receipt'], 'invalid-context')
                self.assertIsNone(result['sha']); self.assertIsNone(result['run']); self.assertIsNone(result['try'])
                self.assertIsNone(result['cleanup']); self.assertIsNone(result['phase'])

    def test_invalid_receipt_and_serialized_bytes_are_unknown(self):
        for raw in (b'', b'{', b'\xff', [], {'schema': True}, {'schema': 1}, b'x' * 8193):
            with self.subTest(raw=repr(raw)[:40]):
                result = decode(status.status_line(raw))
                self.assertEqual(result['receipt'], 'invalid')
                self.assertIsNone(result['phase']); self.assertIsNone(result['cleanup'])

    def test_maximum_generated_fields_fit_darwin_512_with_no_omission(self):
        value = self.generated(); env = dict(os.environ)
        env['GITHUB_RUN_ID'] = env['GITHUB_RUN_ATTEMPT'] = '9' * 20
        value.update(run_id='9' * 20, run_attempt='9' * 20, status='bounded_observation_finished',
                     failure='CaptureFailed: absolute-deadline', host_cleanup_confirmed=False)
        value['processes'] = {name: {'state': 'attempted', 'exit': -255, 'host_cleanup_confirmed': False}
                              for name in ('help', 'collector')}
        raw = value; sent = []
        with patch.object(status.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)), \
             patch.object(status.os, 'fpathconf', return_value=512), \
             patch.object(status.os, 'get_blocking', return_value=True), \
             patch.object(status.os, 'set_blocking'), \
             patch.object(status.os, 'write', side_effect=lambda fd, data: sent.append(data) or len(data)):
            result = status.emit_summary(raw, env)
        self.assertEqual(result['omitted'], 0); self.assertEqual(result['attempts'], 1)
        self.assertEqual(len(sent), 1); self.assertLessEqual(len(sent[0]), 512)
        self.assertEqual(decode(sent[0])['phase'], 'stream')

    def test_actual_generated_record_is_one_complete_real_pipe_write(self):
        raw = self.generated(help_timeout=True); expected = status.status_line(raw)
        saved = os.dup(1); reader, writer = os.pipe()
        try:
            os.dup2(writer, 1)
            result = status.emit_summary(raw)
        finally:
            os.dup2(saved, 1); os.close(saved); os.close(writer)
        try:
            received = os.read(reader, 512)
            self.assertEqual(os.read(reader, 1), b'')
        finally: os.close(reader)
        self.assertEqual(received, expected)
        self.assertEqual(result, {'attempts': 1, 'omitted': 0, 'record_bytes': len(expected)})
        self.assertEqual(decode(received)['reason'], 'absolute-deadline')

    def test_staging_preserves_receipt_and_never_repeats_the_live_summary(self):
        receipt = self.generated(help_timeout=True)
        raw = Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes()
        old_path = list(sys.path)
        try:
            with patch.object(status, '_write_nonblocking') as writer:
                exec(compile(staging_body(), '<actual Mini staging>', 'exec'), {})
        finally: sys.path[:] = old_path
        writer.assert_not_called()
        self.assertEqual(Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes(), raw)
        self.assertEqual(Path('build/mini-passive-upload/iPadMini-passive-compatibility-receipt.json').read_bytes(), raw)
        self.assertFalse(Path('build/mini-passive-upload/console-summary.json').exists())

    def test_staging_with_missing_receipt_does_not_create_a_summary(self):
        with patch.object(status, '_write_nonblocking') as writer:
            exec(compile(staging_body(), '<actual Mini staging>', 'exec'), {})
        writer.assert_not_called()
        self.assertEqual(list(Path('build/mini-passive-upload').glob('*receipt*')), [])
        self.assertFalse(Path('build/mini-passive-upload/console-summary.json').exists())


class LiveBoundaryTests(Harness):
    def boundary(self, operation, action=None):
        sent = []
        original = mini.emit_summary
        def summarize(receipt):
            self.assertIs(receipt, operation.receipt)
            before = copy.deepcopy(receipt)
            # Prove summary formatting/emission itself starts no subprocess and
            # performs no file open/read, even when saving the receipt failed.
            with patch.object(status.os, 'open', side_effect=AssertionError('second open')), \
                 patch.object(status.os, 'read', side_effect=AssertionError('second read')), \
                 patch.object(Path, 'read_bytes', side_effect=AssertionError('second file read')), \
                 patch.object(mini.subprocess, 'Popen', side_effect=AssertionError('new process')):
                result = original(receipt)
            self.assertEqual(receipt, before)
            return result
        with patch.object(mini, 'emit_summary', side_effect=summarize) as emitter, \
             patch.object(status, '_write_nonblocking', side_effect=lambda line: sent.append(line) or True):
            if action is None:
                result = operation.run()
                self.assertIs(result, operation.receipt)
            else:
                action(operation)
        self.assertEqual(emitter.call_count, 1)
        self.assertEqual(len(sent), 1)
        value = decode(sent[0])
        self.assertEqual(value['source'], 'memory')
        self.assertEqual(value['durability'], 'unconfirmed')
        self.assertEqual(value['reader'], 'unconfirmed')
        self.assertIs(value['warmup'], False)
        self.assertTrue(self.warmup.pending.exists())
        return value

    def test_live_success_emits_same_final_object_once_after_cleanup(self):
        operation = self.operation()
        value = self.boundary(operation)
        self.assertEqual(value['phase'], 'stream')
        self.assertIs(value['cleanup'], True)
        self.assertEqual(value['state'], 'bounded_observation_finished')
        self.assertEqual([call[0][-2:] for call in self.engine.calls],
                         [['help', 'stream'], ['--predicate', 'process == "TouchColor"']])
        self.assertEqual(self.budget.calls, [(5, 5, 25), (5, 5, 20)])
        self.no_later_command()

    def test_live_help_failure_emits_once_and_preserves_exception(self):
        self.engine.help_duration = 10
        def fails(operation):
            with self.assertRaisesRegex(mini.CaptureFailed, 'absolute-deadline'):
                operation.run()
        value = self.boundary(self.operation(), fails)
        self.assertEqual(value['phase'], 'help')
        self.assertEqual(value['reason'], 'absolute-deadline')
        self.assertEqual(value['help'], ['owned', -15, True])
        self.assertEqual(value['stream'], [None, None, None])
        self.no_later_command()

    def test_final_save_failure_still_emits_memory_without_durability_claim(self):
        operation = self.operation(); persist = operation._persist
        error = OSError('synthetic final receipt save failure')
        def save():
            if 'cleanup_finished' in operation.receipt['events']:
                raise error
            return persist()
        def fails(operation):
            with self.assertRaises(OSError) as caught:
                operation.run()
            self.assertIs(caught.exception, error)
        with patch.object(operation, '_persist', side_effect=save):
            value = self.boundary(operation, fails)
        self.assertIs(value['cleanup'], True)
        self.assertIsNone(value['reason'])  # Do not invent receipt fields.
        saved = self.receipt()
        self.assertNotIn('host_cleanup_confirmed', saved)
        self.assertNotEqual(saved, operation.receipt)

    def test_final_cleanup_failure_still_emits_unknown_cleanup(self):
        operation = self.operation(); error = OSError('synthetic cleanup failure')
        def fails(operation):
            with self.assertRaises(OSError) as caught:
                operation.run()
            self.assertIs(caught.exception, error)
        with patch.object(operation, '_cleanup', side_effect=error):
            value = self.boundary(operation, fails)
        self.assertIsNone(value['cleanup'])
        self.assertIsNone(value['stream'][2])

    def test_output_failure_does_not_replace_capture_success_or_failure(self):
        operation = self.operation()
        with patch.object(status, '_write_nonblocking', side_effect=OSError('broken output')) as writer:
            result = operation.run()
        self.assertIs(result, operation.receipt)
        self.assertEqual(writer.call_count, 1)

    def test_output_failure_does_not_replace_original_capture_failure(self):
        self.engine.help_duration = 10
        with patch.object(status, '_write_nonblocking', side_effect=OSError('broken output')) as writer:
            self.failed('absolute-deadline')
        self.assertEqual(writer.call_count, 1)
        self.no_later_command()

    def test_serialization_failure_does_not_replace_capture_failure(self):
        self.engine.help_duration = 10
        with patch.object(status, 'status_line', side_effect=ValueError('format failure')) as formatter, \
             patch.object(status, '_write_nonblocking') as writer:
            self.failed('absolute-deadline')
        self.assertEqual(formatter.call_count, 1)
        writer.assert_not_called()

    def test_existing_main_return_remains_three_without_staging(self):
        operation = self.operation()
        with patch.object(mini, 'Warmup', return_value=self.warmup), \
             patch.object(mini, 'prepare_compatibility', return_value='synthetic toolchain'), \
             patch.object(mini, 'CompatibilityCapture', return_value=operation), \
             patch.object(mini, 'enabled_budget', return_value=self.budget), \
             patch.object(mini, 'fail_record') as fail_record, \
             patch.object(mini.sys, 'argv', ['mini_passive_compatibility.py', 'compatibility-only']), \
             patch.object(status, '_write_nonblocking', return_value=False) as writer:
            self.assertEqual(mini.main(), 3)
        self.assertEqual(writer.call_count, 1)
        fail_record.assert_called_once()
        self.assertTrue(fail_record.call_args.kwargs['cleanup_unconfirmed'])


class PipeWriterTests(unittest.TestCase):
    def pipe_patches(self):
        return (patch.object(status.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)),
                patch.object(status.os, 'fpathconf', return_value=512))

    def test_full_error_short_and_interrupted_writes_are_not_retried(self):
        for effect in (BlockingIOError(), BrokenPipeError(), InterruptedError(), OSError(), 1):
            with self.subTest(effect=effect):
                p1, p2 = self.pipe_patches()
                with p1, p2, patch.object(status.os, 'get_blocking', return_value=True), \
                     patch.object(status.os, 'set_blocking') as flags, \
                     patch.object(status.os, 'write', side_effect=effect if isinstance(effect, Exception) else None,
                                  return_value=effect if isinstance(effect, int) else None) as writer:
                    self.assertFalse(status._write_nonblocking(b'record\n'))
                self.assertEqual(writer.call_count, 1)
                self.assertEqual(flags.call_args_list, [((1, False),), ((1, True),)])

    def test_regular_file_or_too_small_pipe_never_receives_a_write(self):
        with patch.object(status.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFREG)), \
             patch.object(status.os, 'write') as writer:
            self.assertFalse(status._write_nonblocking(b'record\n')); writer.assert_not_called()
        p1, p2 = self.pipe_patches()
        with p1, p2, patch.object(status.os, 'write') as writer:
            self.assertFalse(status._write_nonblocking(b'x' * 513)); writer.assert_not_called()
        with p1, patch.object(status.os, 'fpathconf', return_value=4), patch.object(status.os, 'write') as writer:
            self.assertFalse(status._write_nonblocking(b'record\n')); writer.assert_not_called()

    def test_unsupported_pipe_probe_and_flag_errors_are_omissions(self):
        with patch.object(status.os, 'fstat', side_effect=OSError()), patch.object(status.os, 'write') as writer:
            self.assertFalse(status._write_nonblocking(b'record\n')); writer.assert_not_called()
        p1, p2 = self.pipe_patches()
        with p1, p2, patch.object(status.os, 'get_blocking', return_value=True), \
             patch.object(status.os, 'set_blocking', side_effect=OSError()), patch.object(status.os, 'write') as writer:
            self.assertFalse(status._write_nonblocking(b'record\n')); writer.assert_not_called()

    def test_real_generated_record_on_full_pipe_returns_without_wait(self):
        code = '''import os, time, json
from mini_passive_status import emit_summary, status_line, REF, WORKFLOW
env={'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':REF,'GITHUB_EVENT_NAME':'push','GITHUB_WORKFLOW_REF':WORKFLOW,
'GITHUB_JOB':'mini-passive-compatibility','GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted'}
receipt={'schema':1,'purpose':'isolated-compatibility-only','source_sha':'a'*40,'workflow_sha':'a'*40,
'run_id':'123','run_attempt':'1','device':{'family':'iPadMini'},'status':'failed_or_incomplete',
'failure':'CaptureFailed: absolute-deadline','host_cleanup_confirmed':None,'reader_completion':'unconfirmed',
'warmup_admitted':False,'processes':{'help':{'state':'owned','exit':None,'host_cleanup_confirmed':None}}}
raw=receipt;line=status_line(raw,env)
if not line or len(line)>512:raise RuntimeError('Generated record exceeds Darwin bound')
r,w=os.pipe();os.dup2(w,1);os.set_blocking(1,False)
for _ in range(4096):
 try:os.write(1,b'x'*4096)
 except BlockingIOError:break
else:raise RuntimeError('Pipe never filled')
os.set_blocking(1,True);started=time.monotonic();result=emit_summary(raw,env)
if result!={'attempts':1,'omitted':1,'record_bytes':len(line)}:raise RuntimeError('Missing omission count')
if time.monotonic()-started>1:raise RuntimeError('Console waited on full pipe')
if not os.get_blocking(1):raise RuntimeError('Blocking flag not restored')
os.close(r);os.close(w)
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(status.__file__).parent,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_helper_has_no_capture_or_native_command_import(self):
        module = ast.parse(Path(status.__file__).read_text())
        imports = {alias.name for item in ast.walk(module) if isinstance(item, ast.Import) for alias in item.names}
        self.assertEqual(imports, {'json', 'os', 're', 'stat'})
        self.assertFalse(any(isinstance(item, ast.ImportFrom) for item in ast.walk(module)))


if __name__ == '__main__': unittest.main()
