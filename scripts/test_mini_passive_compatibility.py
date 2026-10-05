"""Portable synthetic protocol tests. No test claims an Apple readiness contract."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import tempfile
import sys
import time
import types
import unittest
from unittest.mock import patch

import mini_passive_compatibility as mini
from uikit_warmup import Warmup

UUID = 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


class Budget:
    cleanup_unconfirmed = False
    record = {'sha': 'a' * 40, 'run_id': '123', 'platform': 'ios'}
    def __init__(self, clock): self.clock = clock; self.deadline = 700; self.calls = []
    def remaining(self): return max(0, self.deadline - self.clock())
    def admit(self, label, requested, *, minimum, cleanup):
        self.calls.append((requested, minimum, cleanup))
        if self.remaining() < minimum + cleanup: raise mini.CaptureFailed('job budget')
        return requested


class Pipe:
    next_id = 20
    def __init__(self, process, data):
        self.process, self.data = process, bytearray(data)
        self.number = Pipe.next_id; Pipe.next_id += 1
        self.closed = False
    def fileno(self): return self.number
    def close(self): self.closed = True


class Process:
    def __init__(self, engine, name, stdout, stderr, duration):
        self.engine, self.name = engine, name
        self.pid = 2000 + len(engine.processes)
        self.stdout, self.stderr = Pipe(self, stdout), Pipe(self, stderr)
        self.exit_at = engine.clock() + duration
        self.returncode = None
        self.descendant = name in engine.descendants
    def poll(self):
        if self.returncode is None and self.engine.clock() >= self.exit_at:
            self.returncode = 0
        return self.returncode


class Selector:
    def __init__(self, engine): self.engine = engine; self.keys = {}; self.closed = False
    def register(self, pipe, event, data): self.keys[pipe.fileno()] = types.SimpleNamespace(fileobj=pipe, data=data)
    def unregister(self, pipe): del self.keys[pipe.fileno()]
    def get_map(self): return self.keys
    def select(self, timeout):
        self.engine.clock.advance(min(.01, timeout))
        return [(key, 1) for key in list(self.keys.values()) if key.fileobj.data or key.fileobj.process.poll() is not None]
    def close(self): self.closed = True


class Engine:
    """Only synthetic byte/process semantics, never a plausible native banner."""
    def __init__(self, clock):
        self.clock = clock; self.processes = []; self.calls = []; self.signals = []
        self.collector_duration = 1000
        self.help_duration = .01; self.help_text = b'--info --debug --predicate\n'
        self.collector_text = b'synthetic arbitrary output; not readiness\n'; self.stderr = b''
        self.descendants = set(); self.unkillable = set(); self.on_spawn = None
        self.spawn_delay = {}; self.cancel = None
    def popen(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.copy(), self.clock()))
        name = 'help' if argv[-2:] == ['help', 'stream'] else 'collector'
        output = self.help_text if name == 'help' else self.collector_text
        duration = self.help_duration if name == 'help' else self.collector_duration
        process = Process(self, name, output, self.stderr if name == 'collector' else b'', duration)
        self.processes.append(process)
        self.clock.advance(self.spawn_delay.get(name, 0))
        if self.on_spawn: self.on_spawn(name, process)
        return process
    def group(self, pid):
        process = next(p for p in self.processes if p.pid == pid)
        return process.poll() is None or process.descendant
    def kill(self, pid, sig):
        process = next(p for p in self.processes if p.pid == pid)
        self.signals.append((process.name, sig, self.clock()))
        if process.name not in self.unkillable:
            process.returncode = -sig; process.descendant = False
    def read(self, fd, cap):
        pipe = next(pipe for p in self.processes for pipe in (p.stdout, p.stderr) if pipe.fileno() == fd)
        data = bytes(pipe.data[:cap]); del pipe.data[:cap]; return data


class Harness(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='Mini passive synthetic ')
        self.previous = Path.cwd(); os.chdir(self.directory.name)
        self.addCleanup(self.directory.cleanup); self.addCleanup(os.chdir, self.previous)
        self.clock = Clock(); self.engine = Engine(self.clock); self.budget = Budget(self.clock)
        self.warmup = Warmup('iPadMini', started=100, clock=self.clock, budget=self.budget, sleep=self.clock.advance)
        self.identity = {'family': 'iPadMini', 'udid': UUID, 'runtime': RUNTIME, 'started': 1}
        Path('build/iPadMini-simulator.json').write_text(json.dumps(self.identity))
        mini.APP_PLIST.parent.mkdir(parents=True)
        mini.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier': mini.APP, 'CFBundleExecutable': mini.EXECUTABLE}))
        self.env = patch.dict(os.environ, {'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40,
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ACTIONS': 'true',
            'RUNNER_OS': 'macOS', 'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_JOB': 'mini-passive-compatibility',
            'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': 'refs/heads/codex/mini-passive-compatibility',
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@refs/heads/codex/mini-passive-compatibility'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.patches = [            patch.object(mini.subprocess, 'Popen', side_effect=self.engine.popen),
            patch.object(mini.selectors, 'DefaultSelector', side_effect=lambda: Selector(self.engine)),
            patch.object(mini.os, 'set_blocking'), patch.object(mini.os, 'read', side_effect=self.engine.read),
            patch.object(mini.os, 'killpg', side_effect=self.engine.kill), patch.object(mini, 'group_exists', side_effect=self.engine.group)]
        # Only intercept reads for fake pipes; real bounded binding reads still work.
        self.original_read = os.read
        self.patches[-3] = patch.object(mini.os, 'read', side_effect=self.read)
        for item in self.patches: item.start(); self.addCleanup(item.stop)
    def read(self, fd, cap):
        if any(fd == pipe.fileno() for p in self.engine.processes for pipe in (p.stdout, p.stderr)):
            return self.engine.read(fd, cap)
        return self.original_read(fd, cap)
    def operation(self): return mini.CompatibilityCapture(self.warmup, preparation_started=100)
    def run_capture(self): return self.operation().run()
    def receipt(self): return json.loads(Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes())
    def failed(self, reason=None):
        with self.assertRaises(mini.CaptureFailed) as caught: self.run_capture()
        if reason: self.assertIn(reason, str(caught.exception))
        return self.receipt()
    def no_later_command(self):
        count = len(self.engine.calls)
        with self.assertRaises(FileExistsError):
            self.warmup.command(['xcrun', 'simctl', 'shutdown', UUID], 90)
        self.assertEqual(len(self.engine.calls), count)


class CompatibilityTests(Harness):
    def test_exact_help_and_app_filter_no_launch_or_environment_change(self):
        receipt = self.run_capture()
        self.assertEqual([call[0] for call in self.engine.calls], [
            ['xcrun', 'simctl', 'spawn', UUID, 'log', 'help', 'stream'],
            ['xcrun', 'simctl', 'spawn', UUID, 'log', 'stream', '--info', '--debug', '--predicate', 'process == "TouchColor"']])
        self.assertTrue(all(call[1] == {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
            'start_new_session': True} for call in self.engine.calls))
        self.assertEqual(receipt['preparation_started'], 100)
        self.assertEqual(receipt['preparation_deadline'], 700)
        self.assertEqual(self.budget.calls, [(5, 5, 25), (5, 5, 20)])
        self.assertEqual(receipt['status'], 'bounded_observation_finished')
        self.assertFalse(receipt['diagnostic_complete'])
        self.assertFalse(receipt['warmup_admitted'])
        self.assertFalse(receipt['app_launch_attempted'])
        self.assertEqual(receipt['readiness'], 'unqualified')
        self.assertEqual(receipt['reader_completion'], 'unconfirmed')
        self.assertTrue(receipt['vm_disposal_required']); self.no_later_command()

    def test_existing_warmup_job_is_not_eligible(self):
        for variable, value in (('GITHUB_JOB', 'test'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                                ('RUNNER_OS', 'Linux'), ('GITHUB_ACTIONS', 'false')):
            with self.subTest(variable=variable), patch.dict(os.environ, {variable: value}):
                with self.assertRaisesRegex(mini.CaptureFailed, 'Dedicated disposable'): self.run_capture()
                self.assertEqual(self.engine.calls, [])

    def test_nonapproved_repository_ref_event_or_workflow_is_blocked(self):
        for variable, value in (('GITHUB_REPOSITORY', 'other/ColorPicker'),
                ('GITHUB_REF', 'refs/heads/codex/platform-integration'),
                ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                ('GITHUB_WORKFLOW_REF', '100mango/ColorPicker/.github/workflows/ios.yml@refs/heads/codex/mini-passive-compatibility')):
            with self.subTest(variable=variable), patch.dict(os.environ, {variable: value}):
                with self.assertRaisesRegex(mini.CaptureFailed, 'repository/ref/workflow'): self.run_capture()
                self.assertEqual(self.engine.calls, [])

    def test_insufficient_30_seconds_starts_no_process(self):
        self.clock.value = 670.001
        self.failed('30-second')
        self.assertEqual(self.engine.calls, [])

    def test_inherited_job_deadline_only_shortens_remainder(self):
        self.budget.deadline = 129
        self.failed('30-second')
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.warmup.deadline, 700)

    def test_inherited_cleanup_failure_blocks(self):
        self.budget.cleanup_unconfirmed = True
        with self.assertRaisesRegex(mini.CaptureFailed, 'budget unavailable'): self.run_capture()
        self.assertEqual(self.engine.calls, [])

    def test_identity_source_run_and_app_mismatch_fail_before_spawn(self):
        scenarios = [lambda: Path('build/iPadMini-simulator.json').write_text(json.dumps({**self.identity, 'runtime': 'other'})),
            lambda: os.environ.__setitem__('GITHUB_WORKFLOW_SHA', 'b' * 40),
            lambda: os.environ.__setitem__('GITHUB_RUN_ID', '124'),
            lambda: mini.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'other', 'CFBundleExecutable': mini.EXECUTABLE}))]
        for mutate in scenarios:
            with self.subTest(mutate=mutate):
                Path('build/iPadMini-simulator.json').write_text(json.dumps(self.identity))
                os.environ['GITHUB_WORKFLOW_SHA'] = 'a' * 40; os.environ['GITHUB_RUN_ID'] = '123'
                mutate()
                with self.assertRaises((mini.CaptureFailed, ValueError)): self.run_capture()
                self.assertEqual(self.engine.calls, [])

    def test_unsupported_help_does_not_start_stream(self):
        self.engine.help_text = b'--info --debug'
        receipt = self.failed('Unsupported')
        self.assertEqual(len(self.engine.calls), 1)
        self.assertFalse(receipt['diagnostic_complete']); self.no_later_command()

    def test_help_option_prefixes_do_not_count(self):
        self.engine.help_text = b'--info-more --debug-other --predicate-extra'
        self.failed('Unsupported'); self.assertEqual(len(self.engine.calls), 1)

    def test_quiet_stream_does_not_establish_no_launch_or_readiness(self):
        self.engine.collector_text = b''
        receipt = self.run_capture()
        self.assertEqual(receipt['outputs']['stream']['raw_bytes'], 0)
        self.assertEqual(receipt['readiness'], 'unqualified')
        self.assertEqual(receipt['reader_completion'], 'unconfirmed')
        self.assertNotIn('application_did_not_launch', receipt)
        self.assertEqual(len(self.engine.calls), 2); self.no_later_command()

    def test_banner_never_becomes_readiness(self):
        self.engine.collector_text = b'Filtering the log data using a predicate\n'
        receipt = self.run_capture()
        self.assertEqual(receipt['readiness'], 'unqualified')
        self.assertEqual(receipt['outputs']['stream']['retained_bytes'], len(self.engine.collector_text))
        self.no_later_command()

    def test_collector_early_exit_is_retained_and_not_retried(self):
        self.engine.collector_duration = .001
        receipt = self.failed('Collector exited')
        self.assertEqual(len(self.engine.calls), 2)
        self.assertFalse(receipt['app_launch_attempted'])
        self.assertGreater(receipt['outputs']['stream']['retained_bytes'], 0)
        self.no_later_command()

    def test_slow_stream_spawn_consumes_original_five_seconds(self):
        self.engine.spawn_delay['collector'] = 5.01
        self.failed('absolute-deadline')
        self.assertEqual(len(self.engine.calls), 2); self.no_later_command()

    def test_slow_help_spawn_never_gets_fresh_timeout(self):
        self.engine.spawn_delay['help'] = 5.01
        self.failed('absolute-deadline')
        self.assertEqual(len(self.engine.calls), 1); self.no_later_command()

    def test_unknown_containment_requires_disposal_even_timely_observation(self):
        receipt = self.run_capture()
        self.assertTrue(receipt['host_cleanup_confirmed'])
        self.assertEqual(receipt['reader_completion'], 'unconfirmed')
        self.assertTrue(self.warmup.pending.exists()); self.no_later_command()

    def test_owned_cleanup_has_only_one_twenty_second_tail(self):
        self.engine.unkillable = {'collector'}
        receipt = self.failed()
        events = receipt['events']
        self.assertLessEqual(events['cleanup_finished']['monotonic'] - events['cleanup_started']['monotonic'], 20.000001)
        self.assertEqual([sig for name, sig, when in self.engine.signals], [signal.SIGTERM, signal.SIGKILL])
        self.assertFalse(receipt['host_cleanup_confirmed']); self.no_later_command()

    def test_reaped_help_leader_with_descendant_blocks_stream(self):
        self.engine.descendants = {'help'}; self.engine.unkillable = {'help'}
        receipt = self.failed('Help completion uncertain')
        self.assertEqual(len(self.engine.calls), 1)
        self.assertFalse(receipt['processes']['help']['host_cleanup_confirmed']); self.no_later_command()

    def test_cancel_at_each_spawn_ownership_boundary(self):
        for stage in ('help', 'collector'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as other:
                previous = Path.cwd(); os.chdir(other)
                try:
                    Path('build').mkdir(); Path('build/iPadMini-simulator.json').write_text(json.dumps(self.identity))
                    mini.APP_PLIST.parent.mkdir(parents=True)
                    mini.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier': mini.APP, 'CFBundleExecutable': mini.EXECUTABLE}))
                    self.clock.value = 100; self.engine.processes.clear(); self.engine.calls.clear()
                    operation = self.operation()
                    self.engine.on_spawn = lambda name, process: setattr(operation, 'cancelled', signal.SIGTERM) if name == stage else None
                    with self.assertRaisesRegex(mini.CaptureFailed, 'cancelled'): operation.run()
                    self.assertTrue(self.warmup.pending.exists())
                    self.assertTrue(all(p.poll() is not None for p in self.engine.processes))
                    self.assertEqual(len(self.engine.calls), ('help', 'collector').index(stage) + 1)
                finally: os.chdir(previous)

    def test_immutable_preexisting_marker_cannot_be_cleared(self):
        self.warmup.pending.write_text('original\n')
        with self.assertRaises(FileExistsError): self.run_capture()
        self.assertEqual(self.warmup.pending.read_text(), 'original\n')
        self.assertEqual(self.engine.calls, [])

    def test_overflow_giant_invalid_utf8_and_final_encoded_caps(self):
        self.engine.collector_text = b'\xff' * (mini.STREAM_BYTES * 4) + b'\nlast event\n'
        self.engine.stderr = b'\xff' * (mini.STDERR_BYTES * 4)
        receipt = self.run_capture()
        self.assertTrue(receipt['outputs']['stream']['truncated'])
        self.assertGreater(receipt['outputs']['stream']['dropped_bytes'], 0)
        self.assertEqual(receipt['outputs']['stream']['sha256_all_observed'], hashlib.sha256(self.engine.collector_text).hexdigest())
        for name, cap in (('stream', 65536), ('collector_stderr', 4096), ('help', 8192)):
            self.assertLessEqual(Path('build/iPadMini-passive-compatibility/' + name + '.bin').stat().st_size, cap)
        self.assertLessEqual(Path('build/iPadMini-passive-compatibility/receipt.json').stat().st_size, 8192)

    def test_original_clock_cannot_be_reset(self):
        for start in (101, 99, float('nan')):
            with self.subTest(start=start):
                with self.assertRaisesRegex(mini.CaptureFailed, '600-second'):
                    mini.CompatibilityCapture(self.warmup, preparation_started=start).run()
        self.assertEqual(self.engine.calls, [])

    def test_help_timeout_stops_without_stream(self):
        self.engine.help_duration = 10
        self.failed('absolute-deadline')
        self.assertEqual(len(self.engine.calls), 1); self.no_later_command()

    def test_cancel_during_final_persist_keeps_marker(self):
        operation = self.operation(); original = operation._persist
        def persist():
            original()
            if 'cleanup_finished' in operation.receipt['events']: operation.cancelled = signal.SIGTERM
        with patch.object(operation, '_persist', side_effect=persist):
            with self.assertRaises(mini.CaptureFailed): operation.run()
        self.assertTrue(self.warmup.pending.exists())
        self.assertFalse(self.receipt()['diagnostic_complete'])
        self.assertEqual(self.receipt()['status'], 'failed_or_incomplete')

    def test_persist_failure_after_spawn_still_cleans_owned_groups(self):
        operation = self.operation(); original = operation._persist
        def persist():
            if 'collector' in operation.processes: raise OSError('synthetic disk failure')
            original()
        with patch.object(operation, '_persist', side_effect=persist):
            with self.assertRaises(OSError): operation.run()
        self.assertEqual(len(self.engine.calls), 2)
        self.assertTrue(self.warmup.pending.exists())
        self.assertTrue(all(process.poll() is not None for process in self.engine.processes))

    def test_cleanup_bytes_are_discarded_without_extending_observation(self):
        operation = self.operation(); original = operation._cleanup
        def cleanup():
            process = operation.processes['collector']
            process.stdout.data.extend(b'late cleanup-only output\n')
            original()
        with patch.object(operation, '_cleanup', side_effect=cleanup): receipt = operation.run()
        self.assertEqual(receipt['cleanup_discarded_bytes']['stream'], len(b'late cleanup-only output\n'))
        data = Path('build/iPadMini-passive-compatibility/stream.bin').read_bytes()
        self.assertNotIn(b'late cleanup-only', data)
        self.assertLessEqual(receipt['output_observed_at']['stream']['last']['monotonic'], receipt['observation_deadline'])

    def test_main_always_returns_stop_not_warmup_success(self):
        with patch.object(mini, 'STARTED', 100), patch.object(mini, 'Warmup', return_value=self.warmup), \
             patch.object(mini, 'enabled_budget', return_value=self.budget), \
             patch.object(mini, 'prepare_compatibility', return_value='Xcode 27.0\nBuild version 27A266a\n'), \
             patch.object(mini.sys, 'argv', ['mini_passive_compatibility.py', 'compatibility-only']), \
             patch.object(mini, 'fail_record') as record:
            self.assertEqual(mini.main(), 3)
            self.assertTrue(record.call_args.kwargs['cleanup_unconfirmed'])
        self.no_later_command()

    def test_unknown_cli_is_not_accepted(self):
        with patch.object(mini.sys, 'argv', ['tool', 'launch']), patch.object(mini, 'fail_record'):
            self.assertEqual(mini.main(), 3)
        self.assertEqual(self.engine.calls, [])


class DelayedReadTests(Harness):
    def assert_stopped(self, receipt, expected_calls):
        self.assertEqual(receipt['status'], 'failed_or_incomplete')
        self.assertFalse(receipt['diagnostic_complete'])
        self.assertFalse(receipt['warmup_admitted'])
        self.assertEqual(receipt['readiness'], 'unqualified')
        self.assertEqual(receipt['reader_completion'], 'unconfirmed')
        self.assertEqual(len(self.engine.calls), expected_calls)
        self.assertTrue(self.warmup.pending.exists())
        self.no_later_command()
        self.assertLessEqual(Path('build/iPadMini-passive-compatibility/receipt.json').stat().st_size, 8192)

    def test_stream_read_returning_late_is_omitted_before_timestamp_and_hash(self):
        operation = self.operation(); injected = [False]
        def read(fd, cap):
            data = self.read(fd, cap)
            process = operation.processes.get('collector')
            if process is not None and fd == process.stdout.fileno() and not injected[0]:
                injected[0] = True
                self.clock.value = operation.receipt['observation_deadline'] + .25
            return data
        with patch.object(mini.os, 'read', side_effect=read):
            with self.assertRaisesRegex(mini.CaptureFailed, 'read returned after'): operation.run()
        receipt = self.receipt(); self.assertTrue(injected[0]); self.assert_stopped(receipt, 2)
        self.assertEqual(receipt['late_reads']['stream']['omitted_bytes'], len(self.engine.collector_text))
        self.assertEqual(receipt['late_reads']['stream']['omitted_newline_bytes'], 1)
        self.assertEqual(receipt['late_reads']['stream']['phase'], 'collector')
        self.assertNotIn('stream', receipt['output_observed_at'])
        self.assertEqual(receipt['outputs']['stream']['raw_bytes'], 0)
        self.assertEqual(receipt['outputs']['stream']['sha256_all_observed'], hashlib.sha256(b'').hexdigest())
        self.assertEqual(Path('build/iPadMini-passive-compatibility/stream.bin').read_bytes(), b'')

    def test_help_read_returning_late_cannot_admit_collector(self):
        operation = self.operation(); injected = [False]
        def read(fd, cap):
            data = self.read(fd, cap)
            process = operation.processes.get('help')
            if process is not None and fd == process.stdout.fileno() and not injected[0]:
                injected[0] = True
                self.clock.value = operation.receipt['events']['help_attempt']['monotonic'] + 5.25
            return data
        with patch.object(mini.os, 'read', side_effect=read):
            with self.assertRaisesRegex(mini.CaptureFailed, 'read returned after'): operation.run()
        receipt = self.receipt(); self.assertTrue(injected[0]); self.assert_stopped(receipt, 1)
        self.assertEqual(receipt['help'], 'attempted')
        self.assertEqual(receipt['late_reads']['help']['omitted_bytes'], len(self.engine.help_text))
        self.assertEqual(receipt['late_reads']['help']['phase'], 'help')
        self.assertNotIn('help', receipt['output_observed_at'])
        self.assertEqual(Path('build/iPadMini-passive-compatibility/help.bin').read_bytes(), b'')

    def test_late_help_eof_is_not_a_timely_completion_receipt(self):
        operation = self.operation(); injected = [False]
        def read(fd, cap):
            data = self.read(fd, cap)
            process = operation.processes.get('help')
            if process is not None and fd == process.stdout.fileno() and not data and not injected[0]:
                injected[0] = True
                self.clock.value = operation.receipt['events']['help_attempt']['monotonic'] + 5.25
            return data
        with patch.object(mini.os, 'read', side_effect=read):
            with self.assertRaisesRegex(mini.CaptureFailed, 'read returned after'): operation.run()
        receipt = self.receipt(); self.assertTrue(injected[0]); self.assert_stopped(receipt, 1)
        self.assertEqual(receipt['late_reads']['help']['omitted_bytes'], 0)
        self.assertEqual(receipt['late_reads']['help']['omitted_eof_receipts'], 1)
        self.assertEqual(receipt['help'], 'attempted')

    def cleanup_read_delay(self, seconds, *, eof=False):
        operation = self.operation(); injected = [False]; original_cleanup = operation._cleanup
        late_bytes = b'late cleanup-only output\n'
        def cleanup():
            if not eof: operation.processes['collector'].stdout.data.extend(late_bytes)
            original_cleanup()
        def read(fd, cap):
            data = self.read(fd, cap)
            process = operation.processes.get('collector')
            if ('cleanup_started' in operation.receipt['events'] and process is not None and
                    fd == process.stdout.fileno() and not injected[0]):
                injected[0] = True
                self.clock.value = operation.receipt['events']['cleanup_started']['monotonic'] + seconds
            return data
        with patch.object(operation, '_cleanup', side_effect=cleanup), patch.object(mini.os, 'read', side_effect=read):
            with self.assertRaisesRegex(mini.CaptureFailed, 'read returned after'): operation.run()
        receipt = self.receipt(); self.assertTrue(injected[0]); self.assert_stopped(receipt, 2)
        self.assertEqual(receipt['late_reads']['stream']['phase'], 'cleanup')
        self.assertEqual(receipt['late_reads']['stream']['omitted_bytes'], 0 if eof else len(late_bytes))
        self.assertEqual(receipt['late_reads']['stream']['omitted_eof_receipts'], int(eof))
        self.assertEqual(receipt['cleanup_discarded_bytes']['stream'], 0 if eof else len(late_bytes))
        self.assertEqual(receipt['cleanup_deadline'], receipt['events']['cleanup_started']['monotonic'] + 20)
        self.assertNotIn(late_bytes, Path('build/iPadMini-passive-compatibility/stream.bin').read_bytes())
        self.assertLess(receipt['output_observed_at']['stream']['last']['monotonic'], receipt['observation_deadline'])
        return receipt

    def test_late_cleanup_read_preserves_failed_status_even_when_group_exits(self):
        receipt = self.cleanup_read_delay(10.25)
        self.assertTrue(receipt['host_cleanup_confirmed'])
        self.assertLess(receipt['events']['cleanup_finished']['monotonic'], receipt['cleanup_deadline'])

    def test_late_cleanup_read_cannot_reset_shared_tail(self):
        receipt = self.cleanup_read_delay(20.25)
        self.assertFalse(receipt['host_cleanup_confirmed'])
        self.assertGreater(receipt['events']['cleanup_finished']['monotonic'], receipt['cleanup_deadline'])

    def test_late_cleanup_eof_cannot_claim_bounded_pipe_completion(self):
        receipt = self.cleanup_read_delay(20.25, eof=True)
        self.assertFalse(receipt['host_cleanup_confirmed'])


class SetupTests(Harness):
    def controller_runner(self, command, *, timeout):
        self.setup_calls.append((command, timeout))
        self.clock.advance(.01)
        if command == ['git', 'rev-parse', 'HEAD']: output = 'a' * 40 + '\n'
        elif command == ['xcodebuild', '-version']: output = 'Xcode 27.0\nBuild version 27A266a\n'
        elif command[0:4] == ['xcrun', 'simctl', 'list', 'devices']:
            output = json.dumps({'devices': {RUNTIME: [{'name': 'iPad mini (A17 Pro)', 'udid': UUID, 'isAvailable': True}]}})
        else: output = ''
        return subprocess.CompletedProcess(command, 0, output, '')

    def test_complete_setup_materializes_binding_without_install_or_launch(self):
        self.setup_calls = []; self.warmup.runner = self.controller_runner
        Path('build/iPadMini-simulator.json').unlink()
        result = mini.prepare_compatibility(self.warmup)
        self.assertEqual(result, 'Xcode 27.0\nBuild version 27A266a\n')
        self.assertEqual([args[0] for args, cap in self.setup_calls],
            ['git', 'git', 'xcodebuild', 'xcodebuild', 'xcrun', 'xcrun', 'xcrun'])
        self.assertEqual([args[2] for args, cap in self.setup_calls if args[0] == 'xcrun'],
            ['list', 'boot', 'bootstatus'])
        self.assertEqual([cap for args, cap in self.setup_calls], [3, 3, 5, 300, 30, 180, 240])
        identity = json.loads(Path('build/iPadMini-simulator.json').read_text())
        self.assertEqual(identity['udid'], UUID); self.assertEqual(identity['runtime'], RUNTIME)
        self.assertEqual(self.warmup.deadline, 700)

    def test_setup_timeout_cannot_fall_through_to_observation(self):
        self.setup_calls = []
        def runner(command, *, timeout):
            if command[0:3] == ['xcrun', 'simctl', 'boot']:
                self.clock.advance(timeout)
                error = subprocess.TimeoutExpired(command, timeout); error.cleanup_confirmed = True
                raise error
            return self.controller_runner(command, timeout=timeout)
        self.warmup.runner = runner
        with self.assertRaisesRegex(Exception, 'timed out'): mini.prepare_compatibility(self.warmup)
        self.assertTrue(self.warmup.pending.exists())
        self.assertFalse(any(args[2] == 'bootstatus' for args, cap in self.setup_calls if args[0] == 'xcrun'))
        self.assertEqual(self.engine.calls, [])

    def test_setup_and_observation_share_original_clock(self):
        self.setup_calls = []; self.warmup.runner = self.controller_runner
        mini.prepare_compatibility(self.warmup)
        self.clock.value = 671
        self.failed('30-second')
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.warmup.deadline, 700)


class SetupRunnerClockTests(unittest.TestCase):
    def test_slow_prior_write_cannot_reset_setup_allowance(self):
        clock = Clock(); clock.value = 679
        captured = []
        def capture(command, *, seconds, cap, cleanup_grace):
            captured.append((seconds, cap, cleanup_grace))
            clock.advance(1.1)
            return subprocess.CompletedProcess(command, 0, b'', b'')
        with patch.object(mini, 'STARTED', 100), patch.object(mini.time, 'monotonic', side_effect=clock), \
             patch.object(mini, 'enabled_budget', return_value=None), \
             patch('palette_lifecycle_diagnostics.capture', side_effect=capture):
            with self.assertRaisesRegex(mini.CaptureFailed, 'absolute deadline'):
                mini.setup_runner(['git', 'rev-parse', 'HEAD'], timeout=3)
        self.assertEqual(captured, [(1, 65536, 10)])

    def test_exhausted_original_clock_spawns_nothing(self):
        with patch.object(mini, 'STARTED', 100), patch.object(mini.time, 'monotonic', return_value=680), \
             patch.object(mini, 'enabled_budget', return_value=None), \
             patch('palette_lifecycle_diagnostics.capture') as capture:
            with self.assertRaisesRegex(mini.CaptureFailed, 'deadline exhausted'):
                mini.setup_runner(['git', 'rev-parse', 'HEAD'], timeout=3)
            capture.assert_not_called()


class RealHostPipeTests(unittest.TestCase):
    def test_real_owned_group_pipe_drain_stops_without_native_calls(self):
        with tempfile.TemporaryDirectory(prefix='Mini host pipe test ') as folder:
            previous = Path.cwd(); os.chdir(folder)
            try:
                started = time.monotonic(); budget = Budget(time.monotonic); budget.deadline = started + 600
                controller = Warmup('iPadMini', started=started, budget=budget)
                Path('build/iPadMini-simulator.json').write_text(json.dumps(
                    {'family': 'iPadMini', 'udid': UUID, 'runtime': RUNTIME, 'started': 1}))
                mini.APP_PLIST.parent.mkdir(parents=True)
                mini.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier': mini.APP, 'CFBundleExecutable': mini.EXECUTABLE}))
                original_popen = subprocess.Popen
                calls = []
                def local_child(argv, **kwargs):
                    calls.append(argv)
                    if argv[-2:] == ['help', 'stream']:
                        script = "print('--info --debug --predicate', flush=True)"
                    else:
                        self.assertEqual(argv[2:5], ['spawn', UUID, 'log'])
                        script = "import time; print('synthetic host-only bytes', flush=True); time.sleep(30)"
                    return original_popen([sys.executable, '-c', script], **kwargs)
                with patch.dict(os.environ, {'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS',
                    'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_JOB': 'mini-passive-compatibility',
            'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': 'refs/heads/codex/mini-passive-compatibility',
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@refs/heads/codex/mini-passive-compatibility'}), \
                    patch.object(mini.subprocess, 'Popen', side_effect=local_child):
                    receipt = mini.CompatibilityCapture(controller, preparation_started=started).run()
                self.assertEqual(len(calls), 2)
                self.assertTrue(receipt['host_cleanup_confirmed'])
                self.assertEqual(receipt['reader_completion'], 'unconfirmed')
                self.assertTrue(controller.pending.exists())
                self.assertEqual(Path('build/iPadMini-passive-compatibility/stream.bin').read_bytes(), b'synthetic host-only bytes\n')
                self.assertLess(time.monotonic() - started, 10)
            finally:
                os.chdir(previous)


class RealDelayedPipeTests(unittest.TestCase):
    def delayed_pipe(self, phase):
        with tempfile.TemporaryDirectory(prefix='Mini delayed host pipe ') as folder:
            previous = Path.cwd(); os.chdir(folder)
            try:
                started = time.monotonic(); budget = Budget(time.monotonic); budget.deadline = started + 600
                controller = Warmup('iPadMini', started=started, budget=budget)
                Path('build/iPadMini-simulator.json').write_text(json.dumps(
                    {'family': 'iPadMini', 'udid': UUID, 'runtime': RUNTIME, 'started': 1}))
                mini.APP_PLIST.parent.mkdir(parents=True)
                mini.APP_PLIST.write_bytes(plistlib.dumps({'CFBundleIdentifier': mini.APP, 'CFBundleExecutable': mini.EXECUTABLE}))
                original_popen, original_read = subprocess.Popen, os.read
                operation = mini.CompatibilityCapture(controller, preparation_started=started)
                calls, delayed = [], [False]
                def local_child(argv, **kwargs):
                    calls.append(argv)
                    if argv[-2:] == ['help', 'stream']:
                        script = "print('--info --debug --predicate', flush=True)"
                    else:
                        self.assertEqual(argv[2:5], ['spawn', UUID, 'log'])
                        script = "import time; print('synthetic delayed pipe bytes', flush=True); time.sleep(30)"
                    return original_popen([sys.executable, '-c', script], **kwargs)
                def delayed_read(fd, cap):
                    process = operation.processes.get('help' if phase == 'help' else 'collector')
                    deadline = None
                    if process is not None and fd == process.stdout.fileno() and not delayed[0]:
                        if phase == 'help':
                            deadline = operation.receipt['events']['help_attempt']['monotonic'] + 5
                        elif phase == 'stream':
                            deadline = operation.receipt['observation_deadline']
                        elif 'cleanup_started' in operation.receipt['events']:
                            deadline = operation.receipt['events']['cleanup_started']['monotonic'] + 10
                    if deadline is not None:
                        delayed[0] = True
                        # A real scheduler pause around an actual POSIX pipe
                        # read, with the unchanged native five/ten-second caps.
                        time.sleep(max(0, deadline - time.monotonic() + .25))
                    return original_read(fd, cap)
                environment = {'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'macOS',
                    'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_JOB': 'mini-passive-compatibility',
                    'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': 'refs/heads/codex/mini-passive-compatibility',
                    'GITHUB_EVENT_NAME': 'push', 'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@refs/heads/codex/mini-passive-compatibility'}
                with patch.dict(os.environ, environment), patch.object(mini.subprocess, 'Popen', side_effect=local_child), \
                        patch.object(mini.os, 'read', side_effect=delayed_read):
                    with self.assertRaisesRegex(mini.CaptureFailed, 'read returned after'): operation.run()
                receipt = json.loads(Path('build/iPadMini-passive-compatibility/receipt.json').read_bytes())
                stream = 'help' if phase == 'help' else 'stream'
                late = receipt['late_reads'][stream]
                self.assertTrue(delayed[0])
                self.assertGreater(late['last_returned_monotonic'], late['deadline'])
                self.assertEqual(receipt['status'], 'failed_or_incomplete')
                self.assertTrue(receipt['host_cleanup_confirmed'])
                self.assertFalse(receipt['diagnostic_complete'])
                self.assertFalse(receipt['warmup_admitted'])
                self.assertEqual(receipt['readiness'], 'unqualified')
                self.assertEqual(receipt['reader_completion'], 'unconfirmed')
                self.assertTrue(controller.pending.exists())
                self.assertEqual(len(calls), 1 if phase == 'help' else 2)
                if phase != 'cleanup':
                    self.assertGreater(late['omitted_bytes'], 0)
                    self.assertNotIn(stream, receipt['output_observed_at'])
                    self.assertEqual(Path('build/iPadMini-passive-compatibility/' + stream + '.bin').read_bytes(), b'')
                else:
                    self.assertEqual(late['omitted_eof_receipts'], 1)
                    self.assertLessEqual(receipt['cleanup_deadline'], receipt['events']['cleanup_started']['monotonic'] + 20)
                    self.assertGreater(receipt['cleanup_deadline'], receipt['events']['cleanup_started']['monotonic'] + 19)
                    self.assertLess(receipt['events']['cleanup_finished']['monotonic'], receipt['cleanup_deadline'])
                    self.assertLess(receipt['output_observed_at']['stream']['last']['monotonic'], receipt['observation_deadline'])
            finally:
                os.chdir(previous)

    def test_real_delayed_stream_read_is_never_in_window_evidence(self):
        self.delayed_pipe('stream')

    def test_real_delayed_help_read_cannot_start_stream(self):
        self.delayed_pipe('help')

    def test_real_delayed_cleanup_eof_is_not_a_successful_observation(self):
        self.delayed_pipe('cleanup')


class BufferTests(unittest.TestCase):
    def test_single_giant_chunk_retains_fixed_head_tail(self):
        value = mini.HeadTail(16); raw = b'A' * 8 + b'\xff\n' * 100000 + b'Z' * 8
        value.feed(raw)
        self.assertEqual(value.data(), b'A' * 8 + b'Z' * 8)
        self.assertEqual(len(value.head) + len(value.tail), 16)
        self.assertEqual(value.summary()['dropped_newline_bytes'], 100000)
        self.assertEqual(value.summary()['sha256_all_observed'], hashlib.sha256(raw).hexdigest())

    def test_chunking_does_not_change_retained_bytes(self):
        raw = bytes(range(256)) * 64
        one, many = mini.HeadTail(111), mini.HeadTail(111)
        one.feed(raw)
        for offset in range(0, len(raw), 37): many.feed(raw[offset:offset + 37])
        self.assertEqual(one.summary(), many.summary()); self.assertEqual(one.data(), many.data())


class RunnableWorkflowTests(unittest.TestCase):
    def test_materialized_workflow_matches_reviewed_recipe_exactly(self):
        root=Path(__file__).resolve().parents[1]
        document=(root/'MINI-PASSIVE-COMPATIBILITY.md').read_text()
        recipe=document.split('```yaml\n',1)[1].split('```',1)[0]
        self.assertEqual((root/'.github/workflows/mini-passive-compatibility.yml').read_text(),recipe)

    def test_only_dedicated_branch_one_standard_job_and_local_tail(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/mini-passive-compatibility.yml').read_text()
        self.assertIn('branches: [codex/mini-passive-compatibility]',workflow)
        self.assertNotIn('workflow_dispatch',workflow)
        self.assertEqual(workflow.count('runs-on:'),1)
        self.assertIn('runs-on: xcode-27',workflow)
        self.assertIn('timeout-minutes: 20',workflow)
        self.assertNotIn('matrix:',workflow)
        tail=workflow.split('- name: Stage bounded existing files only',1)[1]
        self.assertNotIn('simctl',tail)
        self.assertNotIn('xcodebuild',tail)
        for name in ('apple-platforms.yml','ios.yml'):
            canonical=(root/'.github/workflows'/name).read_text()
            self.assertIn('branches: [codex/platform-integration]',canonical)
            self.assertNotIn('codex/mini-passive-compatibility',canonical)

if __name__ == '__main__': unittest.main()
