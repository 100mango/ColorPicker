"""Synthetic deadline/cleanup failures; no simulator or sampling command runs."""
import ast
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from watch_live_sample import NativeSignals, NativeCancelled, wait_native


SOURCE = Path(__file__).with_name('test_extra_platforms.py').read_text()
TREE = ast.parse(SOURCE)
FUNCTIONS = compile(ast.Module(body=[node for node in TREE.body if isinstance(node, ast.FunctionDef)
                                     and node.name in ('run', 'resources')], type_ignores=[]), 'native-run', 'exec')
TAIL = compile(ast.Module(body=next(node for node in TREE.body if isinstance(node, ast.Try)).finalbody,
                          type_ignores=[]), 'native-tail', 'exec')


class Fixture:
    def __init__(self, directory, *, spawn_delay=0, write_delay=0, outcome='exit', exit_code=0, timeout_at=None, kind='watch', stdout_text=''):
        self.clock = [100.0]
        self.waits, self.stopped, self.commands, self.joins = [], [], [], []
        self.report = {'sha': 'a' * 40, 'stages': [], 'result': 'failed'}
        self.out = Path(directory) / 'metadata'; self.out.mkdir()
        fixture = self
        class Process:
            pid = 12345
            def __init__(self, command): self.args, self.stdout = command, io.StringIO(stdout_text)
            def wait(self, timeout):
                fixture.waits.append(timeout)
                if outcome in ('timeout', 'late-exit') and (timeout_at is None or len(fixture.commands)-1 == timeout_at):
                    fixture.clock[0] += timeout + 2
                    if outcome == 'timeout': raise subprocess.TimeoutExpired(self.args, timeout)
                return exit_code
            def poll(self): return None
        def spawn(command, **kwargs):
            self.commands.append(command); self.clock[0] += spawn_delay
            return Process(command)
        class Thread:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
            def is_alive(self): return False
            def join(self, timeout): fixture.joins.append(timeout)
        class Signals:
            cancelled = None
            def install(self): pass
            def restore(self): pass
            def check(self): pass
        class Live:
            def __init__(self, *args): self.trigger = types.SimpleNamespace(invalidate=lambda reason: None)
            def record(self, line): pass
            def finish(self): pass
        def stop(process): self.stopped.append(process.pid); return True
        def no_query(*args, **kwargs): raise AssertionError('No optional command after a deadline')
        def wait_native(process, deadline, timeout, live, signals):
            self.native_wait = (deadline, timeout)
            return process.wait(timeout=deadline-self.clock[0])
        self.env = {'report': self.report, 'out': self.out, 'kind': kind, 'device': {'udid': 'WATCH'},
            'LiveSample': Live, 'NativeSignals': Signals, 'NativeCancelled': type('NativeCancelled', (Exception,), {}),
            'wait_native': wait_native, 'subprocess': types.SimpleNamespace(Popen=spawn, PIPE=subprocess.PIPE,
                STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired),
            'datetime': datetime, 'time': types.SimpleNamespace(monotonic=lambda: self.clock[0], time=lambda: self.clock[0]),
            'json': json, 'threading': types.SimpleNamespace(Event=threading.Event, Thread=Thread), 're': re,
            'WATCH_UI_BUNDLE': 'build/watch-ui.xcresult',
            'WatchCaseLifecycle': lambda: types.SimpleNamespace(record=lambda line: None, report={}),
            'watch_frames': types.SimpleNamespace(record=lambda line: None), 'stop_group': stop, 'print': lambda *a, **k: None,
            'resource_snapshot': no_query, 'run_captured': no_query}
        exec(FUNCTIONS, self.env)
        self.budget = types.ModuleType('job_budget')
        self.budget.enabled_budget = lambda: None
        self.budget.fail_record = lambda *a, **k: None
        self.budget.BudgetExhausted = RuntimeError
        self.write_delay = write_delay

    @contextlib.contextmanager
    def active(self):
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == 'runtime.json': self.clock[0] += self.write_delay
            return original(path, *args, **kwargs)
        with patch.dict(sys.modules, job_budget=self.budget), patch.object(Path, 'write_text', write): yield self

    def run(self, command, timeout=60): return self.env['run'](command, timeout, required=False)


class DeadlineTailTests(unittest.TestCase):
    def test_spawn_and_report_work_are_subtracted_before_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, spawn_delay=30, write_delay=10)
            with f.active(): self.assertEqual(f.run(['xcrun', 'simctl', 'shutdown', 'WATCH']), 0)
            self.assertEqual(f.waits, [10])
            self.assertEqual(f.stopped, [12345]); self.assertEqual(f.joins, [5])
            self.assertNotIn('device_uncertain', f.report)

    def test_blocked_spawn_returns_after_deadline_without_new_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, spawn_delay=61)
            with f.active(): self.assertEqual(f.run(['xcrun', 'simctl', 'shutdown', 'WATCH']), 124)
            self.assertEqual(f.waits, [])
            self.assertEqual(f.stopped, [12345]); self.assertEqual(f.joins, [5])
            self.assertTrue(f.report['command_deadline_exceeded'])
            self.assertEqual(f.report['device_uncertain']['target'], 'WATCH')
            self.assertTrue(f.report['stages'][0]['process_group_gone'])
            self.assertNotIn('cleanup_unconfirmed', f.report) # Child exit is distinct from device state.
            self.assertIsNone(f.report['active_command'])

    def test_late_natural_exit_is_not_classified_within_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, outcome='late-exit')
            with f.active(): self.assertEqual(f.run(['xcrun', 'simctl', 'delete', 'WATCH']), 124)
            stage = f.report['stages'][0]
            self.assertEqual(stage['raw_exit'], 0); self.assertTrue(stage['timed_out'])
            self.assertEqual(f.report['device_uncertain']['action'], 'delete')

    def test_live_ui_retains_original_840_second_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, spawn_delay=14, exit_code=65)
            with f.active():
                self.assertEqual(f.run(['xcodebuild', 'test-without-building', '-resultBundlePath', 'build/watch-ui.xcresult'], 840), 65)
            self.assertEqual(f.native_wait, (940, 840)); self.assertEqual(f.waits, [826])
            self.assertNotIn('command_deadline_exceeded', f.report)

    def test_disabled_optional_sampling_keeps_native_wait_and_case_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            line='Test Case synthetic observation input\n'
            f = Fixture(directory, spawn_delay=14, exit_code=65, stdout_text=line)
            f.report['watch_live_sample_enabled'] = False
            def no_observer(*args): raise AssertionError('disabled sampling constructed an observer')
            f.env['LiveSample'] = no_observer
            lifecycle = {'lines': []}
            f.env['WatchCaseLifecycle'] = lambda: types.SimpleNamespace(record=lambda line: lifecycle['lines'].append(line), report=lifecycle)
            with f.active():
                self.assertEqual(f.run(['xcodebuild', 'test-without-building', '-resultBundlePath', 'build/watch-ui.xcresult'], 840), 65)
            self.assertEqual(f.native_wait, (940,840))
            self.assertEqual(f.waits, [826]); self.assertEqual(f.stopped, [12345])
            self.assertEqual(lifecycle['lines'],[line])
            self.assertEqual(f.report['stages'][0]['watch_case_lifecycle'], lifecycle)
            self.assertNotIn('watch_live_sample', f.report)

    def test_empty_observer_wait_preserves_deadline_and_cancellation(self):
        clock=[0.0];waits=[]
        class Process:
            args=['synthetic-native']
            def wait(self,timeout):
                waits.append(timeout);clock[0]+=timeout
                raise subprocess.TimeoutExpired(self.args,timeout)
        with self.assertRaises(subprocess.TimeoutExpired):
            wait_native(Process(),1,1,None,NativeSignals(),now=lambda:clock[0])
        self.assertEqual(clock,[1.0]);self.assertTrue(all(value<=.25 for value in waits))
        guard=NativeSignals();guard.cancelled=15;waits.clear()
        with self.assertRaises(NativeCancelled):wait_native(Process(),2,1,None,guard,now=lambda:clock[0])
        self.assertEqual(waits,[])

    def test_disabled_sampling_restores_real_native_handlers_after_exit_or_cancel(self):
        for cancel in (False,True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                f=Fixture(directory,exit_code=65)
                f.report['watch_live_sample_enabled']=False
                previous=signal.getsignal(signal.SIGTERM)
                original=f.env['subprocess'].Popen
                def spawn(*args,**kwargs):
                    process=original(*args,**kwargs)
                    if cancel:os.kill(os.getpid(),signal.SIGTERM)
                    return process
                f.env['subprocess'].Popen=spawn
                f.env['NativeSignals']=NativeSignals;f.env['NativeCancelled']=NativeCancelled
                f.env['wait_native']=lambda *args:wait_native(*args,now=lambda:f.clock[0])
                command=['xcodebuild','test-without-building','-resultBundlePath','build/watch-ui.xcresult']
                with f.active():
                    if cancel:
                        with self.assertRaises(NativeCancelled):f.run(command,840)
                    else:self.assertEqual(f.run(command,840),65)
                self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
                self.assertEqual(f.stopped,[12345]);self.assertEqual(f.joins,[5])
                self.assertEqual(bool(f.report.get('native_cancelled')),cancel)
                self.assertIsNone(f.report['active_command'])

    def test_optional_sampling_mode_is_explicit_and_rejects_unknown_values(self):
        first = next(i for i,node in enumerate(TREE.body) if isinstance(node,ast.Assign)
                     and any(isinstance(target,ast.Name) and target.id=='live_sample_mode' for target in node.targets))
        code = compile(ast.Module(body=TREE.body[first:first+3],type_ignores=[]),'sampling-mode','exec')
        for value, expected in [('0',False),('1',True),(None,True)]:
            environment = {} if value is None else {'TOUCHCOLOR_WATCH_LIVE_SAMPLE':value}
            scope = {'os':types.SimpleNamespace(environ=environment),'report':{}}
            exec(code,scope)
            self.assertIs(scope['report']['watch_live_sample_enabled'], expected)
        for value in ('','false','yes','2'):
            with self.assertRaises(ValueError):
                exec(code,{'os':types.SimpleNamespace(environ={'TOUCHCOLOR_WATCH_LIVE_SAMPLE':value}),'report':{}})

    def test_non_device_timeout_does_not_invent_device_cleanup_result(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, outcome='timeout')
            with f.active(): self.assertEqual(f.run(['xcodebuild', 'build']), 124)
            self.assertTrue(f.report['command_deadline_exceeded'])
            self.assertNotIn('device_uncertain', f.report)
            f.env['resources']('after platform attempt') # Would fail if it launched optional probes.

    def test_tv_vision_generic_run_success_and_timeout_compatibility(self):
        # The focused executable currently admits Watch only. These exercise
        # the shared function semantics, not either platform's native product.
        for kind in ('tv', 'vision'):
            for outcome in ('exit', 'timeout'):
                with self.subTest(kind=kind,outcome=outcome), tempfile.TemporaryDirectory() as directory:
                    f = Fixture(directory, kind=kind, spawn_delay=14, outcome=outcome)
                    def no_watch_observer(*args): raise AssertionError('Watch observer on another platform')
                    f.env['LiveSample'] = no_watch_observer
                    command = ['xcodebuild', 'test-without-building', '-resultBundlePath', 'build/'+kind+'-ui.xcresult']
                    with f.active(): self.assertEqual(f.run(command), 124 if outcome=='timeout' else 0)
                    self.assertEqual(f.waits, [46]); self.assertEqual(f.stopped, [12345]); self.assertEqual(f.joins, [5])
                    self.assertNotIn('device_uncertain', f.report)
                    self.assertIsNone(f.report['active_command'])
                    self.assertEqual(f.report['stages'][0]['timed_out'], outcome=='timeout')
                    if outcome=='timeout':
                        self.assertTrue(f.report['command_deadline_exceeded'])
                        f.env['resources']('after platform attempt')
                    else:self.assertNotIn('command_deadline_exceeded', f.report)

    def test_first_device_timeout_at_each_step_stops_chain_and_writes_local_result(self):
        actions = [['shutdown','WATCH'],['shutdown','PHONE'],['unpair','PAIR'],['delete','WATCH'],['delete','PHONE']]
        for index in range(len(actions)):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory, outcome='timeout', timeout_at=index)
                f.report['command_deadline_exceeded'] = True
                f.env.update({'pending_vision_hosted': None, 'pending_vision_normal': None, 'pending_vision_result': None,
                    'os': os, 'Path': Path, 'owned_watch_devices': [{'role': 'phone', 'udid': 'PHONE'}, {'role': 'watch', 'udid': 'WATCH'}],
                    'owned_watch_pair': 'PAIR', 'fail_record': lambda *a, **k: None})
                with f.active(), patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': 'work'}): exec(TAIL, f.env)
                self.assertEqual([command[2:] for command in f.commands], actions[:index+1])
                self.assertEqual(f.stopped, [12345]*(index+1)); self.assertEqual(f.joins, [5]*(index+1))
                saved = json.loads((f.out / 'runtime.json').read_text())
                self.assertEqual(saved['result'], 'failed')
                self.assertEqual(saved['device_uncertain']['action'], actions[index][0])
                self.assertEqual(saved['device_uncertain']['target'], actions[index][1])
                self.assertIn('device cleanup is unconfirmed', saved['simulator_cleanup'])
                self.assertIsNone(saved['active_command'])

    def test_successful_device_cleanup_sequence_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.report['command_deadline_exceeded'] = True # Skip optional queries, allow owned cleanup.
            f.env.update({'pending_vision_hosted': None, 'pending_vision_normal': None, 'pending_vision_result': None,
                'os': os, 'Path': Path, 'owned_watch_devices': [{'role': 'phone', 'udid': 'PHONE'}, {'role': 'watch', 'udid': 'WATCH'}],
                'owned_watch_pair': 'PAIR', 'fail_record': lambda *a, **k: None})
            with f.active(), patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': 'work'}): exec(TAIL, f.env)
            self.assertEqual([row[2:] for row in f.commands], [['shutdown','WATCH'],['shutdown','PHONE'],['unpair','PAIR'],['delete','WATCH'],['delete','PHONE']])
            self.assertNotIn('device_uncertain', f.report)
            self.assertEqual(f.report['result'], 'failed') # Cleanup does not convert the failed case.


if __name__ == '__main__': unittest.main()
