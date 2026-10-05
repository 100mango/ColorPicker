"""Staging-only console mirror tests; no simulator or capture timing changes."""
import ast
import copy
import hashlib
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
        if help_timeout:
            self.engine.help_duration = 10
            self.failed('absolute-deadline')
        else:
            self.run_capture()
        return Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes()

    def test_actual_generated_timeout_is_help_with_actual_cleanup(self):
        raw = self.generated(help_timeout=True); original = bytes(raw)
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
        value = json.loads(self.generated())
        value.pop('host_cleanup_confirmed')
        value['processes']['collector'].pop('host_cleanup_confirmed')
        value['processes']['help']['host_cleanup_confirmed'] = 'true'
        value['processes']['help']['exit'] = True
        result = decode(status.status_line(json.dumps(value).encode()))
        self.assertIsNone(result['cleanup'])
        self.assertEqual(result['help'], ['owned', None, None])
        self.assertEqual(result['stream'], ['owned', -15, None])

    def test_actual_false_cleanup_is_not_replaced_with_unknown_or_success(self):
        value = json.loads(self.generated()); value['host_cleanup_confirmed'] = False
        for row in value['processes'].values(): row['host_cleanup_confirmed'] = False
        result = decode(status.status_line(json.dumps(value).encode()))
        self.assertIs(result['cleanup'], False)
        self.assertIs(result['help'][2], False); self.assertIs(result['stream'][2], False)

    def test_unsupported_error_text_and_raw_logs_are_never_printed(self):
        value = json.loads(self.generated()); private = 'SECRET-PATH\n::warning::' + 'x' * 1000
        value['failure'] = private; value['raw_stream'] = private
        value['processes']['collector']['argv'] = [private]
        line = status.status_line(json.dumps(value).encode())
        self.assertNotIn(b'SECRET', line); self.assertNotIn(b'::warning', line)
        self.assertEqual(decode(line)['reason'], 'other')

    def test_allowlisted_reason_keeps_late_read_distinct_from_generic_deadline(self):
        value = json.loads(self.generated())
        for reason in ('CaptureFailed: Pipe read returned after its absolute deadline',
                       'Pipe read returned after its absolute deadline'):
            value['failure'] = reason
            self.assertEqual(decode(status.status_line(json.dumps(value).encode()))['reason'], 'late-read')

    def test_cancelled_reason_uses_only_actual_typed_signal(self):
        value = json.loads(self.generated()); value['cancelled_signal'] = 15
        self.assertEqual(decode(status.status_line(json.dumps(value).encode()))['reason'], 'cancelled')
        value['cancelled_signal'] = True
        self.assertIsNone(decode(status.status_line(json.dumps(value).encode()))['reason'])

    def test_wrong_receipt_sha_run_attempt_or_family_exposes_no_result(self):
        original = json.loads(self.generated())
        for key, bad in (('source_sha', 'b' * 40), ('workflow_sha', 'b' * 40),
                         ('run_id', '124'), ('run_attempt', '2'), ('device', {'family': 'iPhoneLarge'})):
            with self.subTest(key=key):
                value = copy.deepcopy(original); value[key] = bad
                result = decode(status.status_line(json.dumps(value).encode()))
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

    def test_invalid_duplicate_oversized_or_nonfinite_receipt_is_unknown(self):
        for raw in (b'', b'{', b'\xff', b'[]', b'{"schema":1,"schema":1}', b'{"v":NaN}', b'x' * 8193):
            with self.subTest(raw=raw[:20]):
                result = decode(status.status_line(raw))
                self.assertEqual(result['receipt'], 'invalid')
                self.assertIsNone(result['phase']); self.assertIsNone(result['cleanup'])

    def test_maximum_generated_fields_fit_darwin_512_with_no_omission(self):
        value = json.loads(self.generated()); env = dict(os.environ)
        env['GITHUB_RUN_ID'] = env['GITHUB_RUN_ATTEMPT'] = '9' * 20
        value.update(run_id='9' * 20, run_attempt='9' * 20, status='bounded_observation_finished',
                     failure='CaptureFailed: absolute-deadline', host_cleanup_confirmed=False)
        value['processes'] = {name: {'state': 'attempted', 'exit': -255, 'host_cleanup_confirmed': False}
                              for name in ('help', 'collector')}
        raw = json.dumps(value).encode(); sent = []
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

    def test_actual_staging_uses_already_read_receipt_and_preserves_its_bytes(self):
        raw = self.generated(help_timeout=True); before = hashlib.sha256(raw).hexdigest(); sent = []
        old_path = list(sys.path)
        try:
            with patch.object(status, '_write_nonblocking', side_effect=lambda data: sent.append(data) or True):
                exec(compile(staging_body(), '<actual Mini staging>', 'exec'), {})
        finally: sys.path[:] = old_path
        self.assertEqual(len(sent), 1); self.assertEqual(decode(sent[0])['phase'], 'help')
        self.assertEqual(hashlib.sha256(Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes()).hexdigest(), before)
        self.assertEqual(Path('build/mini-passive-upload/iPadMini-passive-compatibility-receipt.json').read_bytes(), raw)
        note = Path('build/mini-passive-upload/console-summary.json')
        self.assertLessEqual(note.stat().st_size, 128)
        self.assertEqual(json.loads(note.read_bytes()), {'attempts': 1, 'omitted': 0, 'record_bytes': len(sent[0])})

    def test_staging_records_omission_without_retry_when_receipt_missing(self):
        old_path = list(sys.path)
        try:
            with patch.object(status, '_write_nonblocking', return_value=False) as writer:
                exec(compile(staging_body(), '<actual Mini staging>', 'exec'), {})
        finally: sys.path[:] = old_path
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(decode(writer.call_args.args[0])['receipt'], 'missing')
        note = json.loads(Path('build/mini-passive-upload/console-summary.json').read_bytes())
        self.assertEqual(note['omitted'], 1); self.assertEqual(note['attempts'], 1)


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
raw=json.dumps(receipt).encode();line=status_line(raw,env)
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
