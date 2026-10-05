"""Executable simulator-uncertainty and shared-pool setup adversaries; no native calls."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_watch_crown_control as driver
from job_budget import BudgetExhausted
from watch_crown_contract import METHODS, PHASES, test_command
from test_watch_crown_driver import Clock, environment
import test_watch_crown_driver as driver_tests
from test_watch_crown_result import fixture
from watch_crown_result import validate_result

DEVICE='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
COMMANDS=[['xcrun','simctl',name,DEVICE] for name in ('list','create','pair','pair_activate','boot','bootstatus','terminate','shutdown','unpair','delete')]
COMMANDS += [['xcrun','simctl','spawn',DEVICE,'log','show'],
             ['xcrun','simctl','spawn',DEVICE,'launchctl','list'],
             test_command(METHODS[0],DEVICE),['xcodebuild','-project','TouchColorWatch.xcodeproj','test']]


class FenceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        Path('build/evidence').mkdir(parents=True);self.clock=Clock();self.spawns=[]
        self.d=driver.Driver(environment(),clock=lambda:self.clock.mono,wall=lambda:self.clock.wall)
        self.quiet=patch.object(driver,'_write_console_nonblocking',return_value=False);self.quiet.start()
    def tearDown(self):self.quiet.stop();os.chdir(self.old);self.temp.cleanup()
    def process(self,*,mode='success',elapsed=1,code=0):
        clock=self.clock;spawns=self.spawns
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):spawns.append(command);self.stdout=io.BytesIO(b'original diagnostic')
            def wait(self,timeout=None):
                if mode=='timeout':clock.advance(timeout);raise subprocess.TimeoutExpired('owned-device',timeout)
                clock.advance(elapsed)
                if mode=='interrupt':raise KeyboardInterrupt('interrupt')
                return code
        return Process
    def assert_blocked_everywhere(self,d=None):
        d=d or self.d;before=len(self.spawns)
        # Clearing generic work/budget flags cannot clear the dedicated fence.
        d.work_stopped=False;d.budget.cleanup_unconfirmed=False
        for call in (lambda:d.run(['xcrun','simctl','list'],3),lambda:d.run(['git','rev-parse','HEAD'],3),
                     lambda:d.run(['xcrun','xcresulttool','get'],3),lambda:d.method(METHODS[0]),d.execute):
            with self.assertRaises((ValueError,BudgetExhausted)):call()
        d.cleanup();d.evidence()
        self.assertEqual(len(self.spawns),before)
    def reload_blocked(self):
        fresh=driver.Driver(environment(),clock=lambda:self.clock.mono,wall=lambda:self.clock.wall,process_factory=self.process())
        self.assertTrue(fresh.simulator_blocked());self.assert_blocked_everywhere(fresh)

class SimulatorFenceTests(FenceTestCase):
    def test_every_current_device_family_timeout_fences_all_entrypoints(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                t=SimulatorFenceTests();t.setUp()
                try:
                    t.d.process_factory=t.process(mode='timeout')
                    with patch.object(driver,'stop_group',return_value=True) as stop,t.d.phase('setup',450):
                        row,_=t.d.run(command,3,required=False)
                    self.assertEqual(stop.call_count,1);self.assertTrue(row['timed_out'])
                    self.assertTrue(row['process_group_gone']);self.assertTrue(row['capture_reader_finished'])
                    self.assertEqual(row['simulator_command_completion'],'unconfirmed')
                    self.assertTrue(driver.SIMULATOR_STOP.is_file())
                    self.assertEqual(t.d.report['simulator_uncertainty']['marker_durability'],'fsync_confirmed')
                    t.assert_blocked_everywhere();t.reload_blocked()
                finally:t.tearDown()

    def test_post_cleanup_expiry_is_simulator_uncertainty_even_with_host_cleanup_confirmed(self):
        self.d.process_factory=self.process()
        def slow(*a,**kw):self.clock.advance(4);return True
        with patch.object(driver,'stop_group',side_effect=slow),self.d.phase('setup',450):
            row,_=self.d.run(COMMANDS[4],3,required=False)
        self.assertTrue(row['timed_out']);self.assertEqual(row['raw_exit'],0)
        self.assertTrue(row['process_group_gone']);self.assertTrue(self.d.simulator_uncertain)
        self.assert_blocked_everywhere();self.reload_blocked()

    def test_unknown_host_cleanup_and_interruption_each_fence(self):
        for mode,confirmed in [('success',False),('interrupt',True)]:
            with self.subTest(mode=mode):
                t=SimulatorFenceTests();t.setUp()
                try:
                    t.d.process_factory=t.process(mode=mode)
                    with patch.object(driver,'stop_group',return_value=confirmed) as stop,t.d.phase('setup',450):
                        if mode=='interrupt':
                            with self.assertRaises(KeyboardInterrupt):t.d.run(COMMANDS[5],3)
                        else:t.d.run(COMMANDS[5],3,required=False)
                    self.assertEqual(stop.call_count,1);t.assert_blocked_everywhere();t.reload_blocked()
                finally:t.tearDown()

    def test_reader_error_fences_even_after_zero_exit_and_group_cleanup(self):
        clock=self.clock;spawns=self.spawns
        class BadReader:
            def read(self,n):raise OSError('reader failure')
            def close(self):pass
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):spawns.append(command);self.stdout=BadReader()
            def wait(self,timeout=None):clock.advance(1);return 0
        self.d.process_factory=Process
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',450):row,_=self.d.run(COMMANDS[0],3,required=False)
        self.assertFalse(row['capture_reader_finished']);self.assert_blocked_everywhere()

    def test_marker_write_failure_cannot_preempt_host_cleanup_and_reload_is_blocked(self):
        self.d.process_factory=self.process(mode='interrupt');original=Path.open;order=[]
        def open_path(path,*args,**kwargs):
            if path==driver.SIMULATOR_STOP:order.append('marker');raise OSError('injected write failure')
            return original(path,*args,**kwargs)
        def stop(*args,**kwargs):order.append('host-cleanup');return True
        with patch.object(Path,'open',new=open_path),patch.object(driver,'stop_group',side_effect=stop),self.d.phase('setup',450):
            with self.assertRaises(KeyboardInterrupt):self.d.run(COMMANDS[5],3)
        self.assertEqual(order,['host-cleanup','marker'])
        self.assertFalse(driver.SIMULATOR_STOP.exists())
        self.assertEqual(self.d.report['simulator_uncertainty']['marker_durability'],'unknown')
        persisted=json.loads(Path('build/evidence/report.json').read_text())
        self.assertEqual(persisted['simulator_uncertainty']['marker_error'],'OSError')
        self.assert_blocked_everywhere();self.reload_blocked()

    def test_marker_fsync_failure_is_explicit_and_remains_a_reload_barrier(self):
        self.d.process_factory=self.process(mode='timeout');original_open=Path.open;original_fsync=os.fsync;marker_fd=[None]
        def open_path(path,*args,**kwargs):
            stream=original_open(path,*args,**kwargs)
            if path==driver.SIMULATOR_STOP:marker_fd[0]=stream.fileno()
            return stream
        def fsync(fd):
            if fd==marker_fd[0]:marker_fd[0]=None;raise OSError('marker fsync failure')
            return original_fsync(fd)
        with patch.object(Path,'open',new=open_path),patch.object(driver.os,'fsync',side_effect=fsync),\
             patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',450):
            self.d.run(COMMANDS[4],3,required=False)
        self.assertEqual(self.d.report['simulator_uncertainty']['marker_durability'],'unknown')
        self.assertTrue(driver.SIMULATOR_STOP.exists());self.reload_blocked()

    def test_post_spawn_receipt_failure_still_cleans_owned_host_then_fences(self):
        self.d.process_factory=self.process();original=self.d.persist;calls=[]
        def persist():
            calls.append(1)
            if len(calls)==2:raise OSError('post-spawn report failure')
            original()
        self.d.persist=persist
        with patch.object(driver,'stop_group',return_value=True) as stop,self.d.phase('setup',450):
            with self.assertRaises(OSError):self.d.run(COMMANDS[5],3)
        self.assertEqual(len(self.spawns),1);self.assertEqual(stop.call_count,1)
        self.assertTrue(self.d.report['stages'][0]['capture_reader_finished'])
        self.assert_blocked_everywhere();self.reload_blocked()

    def test_final_receipt_persistence_expiry_fences_before_any_later_command(self):
        self.d.process_factory=self.process();original=self.d.persist;calls=[]
        def persist():
            calls.append(1);original()
            if len(calls)==3:self.clock.advance(4)
        self.d.persist=persist
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',450):
            row,_=self.d.run(COMMANDS[4],3,required=False)
            self.assertTrue(row['timed_out']);self.assert_blocked_everywhere()
        self.assertTrue(driver.SIMULATOR_STOP.exists());self.reload_blocked()

    def test_pre_spawn_persistence_failure_never_starts_a_device_command(self):
        self.d.process_factory=self.process();original=self.d.persist;calls=[]
        def persist():
            calls.append(1)
            if len(calls)==1:raise OSError('before spawn')
            original()
        self.d.persist=persist
        with patch.object(driver,'stop_group') as stop,self.d.phase('setup',450):
            with self.assertRaises(OSError):self.d.run(COMMANDS[4],3)
        self.assertEqual(self.spawns,[]);stop.assert_not_called();self.assertFalse(self.d.simulator_uncertain)

    def test_timely_xctest65_is_a_real_failure_not_simulator_uncertainty(self):
        for required in (False,True):
            with self.subTest(required=required):
                t=SimulatorFenceTests();t.setUp()
                try:
                    t.d.process_factory=t.process(code=65)
                    with patch.object(driver,'stop_group',return_value=True),t.d.phase('isolated_static',180):
                        if required:
                            with self.assertRaises(ValueError):t.d.run(test_command(METHODS[0],DEVICE),180)
                        else:
                            row,_=t.d.run(test_command(METHODS[0],DEVICE),180,required=False)
                            self.assertEqual(row['raw_exit'],65)
                    self.assertFalse(t.d.simulator_uncertain);self.assertFalse(driver.SIMULATOR_STOP.exists())
                    self.assertNotIn('simulator_uncertainty',t.d.report)
                finally:t.tearDown()

    def test_real_bounded_exit65_keeps_the_single_static_failure(self):
        t=driver_tests.SequentialMethodTests();t.setUp()
        try:
            fake_other=t.d.run;real_run=driver.Driver.run.__get__(t.d,driver.Driver);clock=t.clock;starts=[]
            class Process:
                pid=123456
                def __init__(self,command,**kwargs):
                    starts.append(command)
                    target,cls,member=next(v for v in command if v.startswith('-only-testing:')).split(':',1)[1].split('/')
                    self.fields=target,cls,member
                    self.code=0 if member=='testRealDigitalCrownChangesRGBComponent' else 65
                    prefix="Test Case '-["+target+'.'+cls+' '+member+"]' "
                    self.stdout=io.BytesIO((prefix+'started.\n'+prefix+('passed' if self.code==0 else 'failed')+' (2.0 seconds).\n').encode())
                def wait(self,timeout=None):clock.advance(4);return self.code
            t.d.process_factory=Process
            def combined(command,*args,**kwargs):
                if command[:2]==['xcodebuild','test-without-building']:
                    row,text=real_run(command,*args,**kwargs)
                    target,cls,member=next(v for v in command if v.startswith('-only-testing:')).split(':',1)[1].split('/')
                    t.active_case=target,cls,member,row
                    return row,text
                row,text=fake_other(command,*args,**kwargs)
                row['phase']=t.d.current['name']
                return row,text
            t.d.run=combined
            with patch.object(driver,'stop_group',return_value=True):
                for method in METHODS:t.d.method(method)
            self.assertEqual(len(starts),1)
            self.assertEqual([r['observed_command_result'] for r in t.d.report['cases']],['failed'])
            self.assertFalse(t.d.simulator_uncertain);self.assertFalse(t.d.report['acceptance'])
        finally:t.tearDown()

    def test_existing_marker_including_malformed_symlink_blocks_without_reading_it(self):
        for kind in ('malformed','symlink'):
            with self.subTest(kind=kind):
                t=SimulatorFenceTests();t.setUp()
                try:
                    if kind=='malformed':driver.SIMULATOR_STOP.write_text('not JSON')
                    else:driver.SIMULATOR_STOP.symlink_to('/definitely-missing-private-target')
                    t.assert_blocked_everywhere();t.reload_blocked()
                finally:t.tearDown()

    def test_all_device_families_interrupt_late_and_unknown_cleanup_cannot_continue(self):
        for command in COMMANDS:
            for mode in ('interrupt','late','unclean'):
                with self.subTest(command=command,mode=mode):
                    t=SimulatorFenceTests();t.setUp()
                    try:
                        t.d.process_factory=t.process(mode='interrupt' if mode=='interrupt' else 'success',elapsed=4 if mode=='late' else 1)
                        with patch.object(driver,'stop_group',return_value=mode!='unclean') as stop,t.d.phase('setup',450):
                            if mode=='interrupt':
                                with self.assertRaises(KeyboardInterrupt):t.d.run(command,3,required=False)
                            else:t.d.run(command,3,required=False)
                        self.assertEqual(stop.call_count,1);t.assert_blocked_everywhere();t.reload_blocked()
                    finally:t.tearDown()

    def test_host_cleanup_exception_still_sets_durable_barrier(self):
        self.d.process_factory=self.process()
        with patch.object(driver,'stop_group',side_effect=OSError('cannot confirm group')) as stop,self.d.phase('setup',450):
            row,_=self.d.run(test_command(METHODS[0],DEVICE),3,required=False)
        self.assertEqual(stop.call_count,1);self.assertFalse(row['process_group_gone'])
        self.assertTrue(driver.SIMULATOR_STOP.exists());self.assert_blocked_everywhere();self.reload_blocked()

    def test_execute_finalizers_start_no_command_after_device_timeout(self):
        # Use the real top-level finally path with a tiny synthetic setup body.
        Path('build/evidence').rmdir();self.d.process_factory=self.process(mode='timeout')
        self.d.preflight=lambda:None;self.d.builds=lambda:None
        def setup():
            self.d.owned.extend([{'role':'watch','udid':DEVICE}]);self.d.device=DEVICE
            with self.d.phase('setup',450):self.d.run(COMMANDS[5],3)
        self.d.setup=setup
        with patch.object(driver,'stop_group',return_value=True):self.assertEqual(self.d.execute(),0)
        self.assertEqual(self.spawns,[COMMANDS[5]])
        saved=json.loads(Path('build/evidence/report.json').read_text())
        self.assertIn('simulator_uncertainty',saved);self.assertEqual(saved['cases'],[])
        self.assertFalse(saved['cleanup']['confirmed']);self.assertFalse(saved['acceptance'])

    def test_pre_spawn_and_phase_exit_persistence_errors_after_ownership_fence_finalizers(self):
        for fail_at in (1,4):
            with self.subTest(fail_at=fail_at):
                t=SimulatorFenceTests();t.setUp()
                try:
                    t.d.process_factory=t.process();t.d.owned.append({'udid':DEVICE})
                    original=t.d.persist;calls=[]
                    def persist():
                        calls.append(1)
                        if len(calls)==fail_at:raise OSError('injected boundary persistence failure')
                        original()
                    t.d.persist=persist
                    with patch.object(driver,'stop_group',return_value=True) as stop:
                        with self.assertRaises(OSError):
                            with t.d.phase('setup',450):t.d.run(['xcrun','simctl','boot',DEVICE],3)
                    self.assertEqual(stop.call_count,0 if fail_at==1 else 1)
                    self.assertTrue(driver.SIMULATOR_STOP.exists());t.assert_blocked_everywhere();t.reload_blocked()
                finally:t.tearDown()

    def test_reported_console_timeout_prevents_even_summary_extraction(self):
        clock=self.clock;spawns=self.spawns
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):spawns.append(command);self.stdout=io.BytesIO(b'Test execution timed out\n')
            def wait(self,timeout=None):clock.advance(1);return 65
        self.d.process_factory=Process;self.d.device=DEVICE;self.d.owned.append({'udid':DEVICE})
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(ValueError):self.d.method(METHODS[0])
        self.assertEqual(len(self.spawns),1)
        self.assertEqual(self.d.report['stages'][0]['raw_exit'],65)
        self.assertIn('timed out',Path('build/evidence/isolated_static-console.log').read_text())
        self.assert_blocked_everywhere();self.reload_blocked()

    def test_timeout_found_only_in_structured_summary_immediately_fences(self):
        t=driver_tests.SequentialMethodTests();t.setUp()
        try:
            original=t.d.run
            def run(command,*args,**kwargs):
                row,text=original(command,*args,**kwargs)
                if 'summary' in command:
                    value=json.loads(text);value['testFailures'][0]['failureText']='Test execution timed out'
                    text=json.dumps(value)
                return row,text
            t.d.run=run
            with self.assertRaises(ValueError):t.d.method(METHODS[0])
            self.assertEqual(len(t.commands),2)
            self.assertTrue(t.d.simulator_uncertain);self.assertTrue(driver.SIMULATOR_STOP.exists())
            self.assertTrue(Path('build/evidence/isolated_static-summary.json').is_file())
            # Restore the real command guard; mocks must not provide a bypass.
            t.d.run=driver.Driver.run.__get__(t.d,driver.Driver)
            before=len(t.commands);t.d.cleanup();t.d.evidence()
            with self.assertRaises(ValueError):t.d.method(METHODS[0])
            self.assertEqual(len(t.commands),before)
        finally:t.tearDown()

    def test_echoed_timeout_configuration_is_not_native_timeout_evidence(self):
        self.assertFalse(driver.reported_device_timeout('xcodebuild test-without-building -test-timeouts-enabled YES -maximum-test-execution-time-allowance 120'))
        for text in ('Test execution timed out','Test exceeded execution time allowance','Timeout waiting for simulator','The test may have hung'):
            self.assertTrue(driver.reported_device_timeout(text),text)

    def test_non_device_host_timeout_does_not_claim_simulator_uncertainty(self):
        self.d.process_factory=self.process(mode='timeout')
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('preflight',30):self.d.run(['git','rev-parse','HEAD'],3,required=False)
        self.assertFalse(self.d.simulator_uncertain);self.assertTrue(self.d.work_stopped)
        self.assertFalse(driver.SIMULATOR_STOP.exists())


class SetupAllowanceTests(FenceTestCase):
    def test_observed419_second_sequence_fits_clipped450_phase_without_clock_reset(self):
        durations=iter((6.637,123.119,99.743,189.882));clock=self.clock;spawns=self.spawns;observed=[]
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):spawns.append(command);self.stdout=io.BytesIO(b'ok')
            def wait(self,timeout=None):
                duration=next(durations);observed.append(timeout)
                if duration>=timeout:clock.advance(timeout);raise subprocess.TimeoutExpired('boot',timeout)
                clock.advance(duration);return 0
        self.d.process_factory=Process
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',450):
            self.clock.advance(3)
            for _ in range(2):
                self.d.run(['xcrun','simctl','boot',DEVICE],180,clip_setup=True)
                self.d.run(['xcrun','simctl','bootstatus',DEVICE,'-b'],420,clip_setup=True)
        self.assertAlmostEqual(self.clock.mono-100,422.381)
        [self.assertAlmostEqual(actual,expected) for actual,expected in zip(observed[:3],[180,420,180])];self.assertAlmostEqual(observed[3],217.501)
        self.assertFalse(self.d.simulator_uncertain);self.assertEqual(self.d.budget.record['started_monotonic'],100)
        self.assertEqual(self.d.budget.record['minutes'],25)

    def test_clipping_cannot_shrink_ui_or_any_unadmitted_setup_command(self):
        for command,seconds in [(test_command(METHODS[0],DEVICE),180),(['xcrun','simctl','shutdown',DEVICE],120),
                                (['xcrun','simctl','boot',DEVICE],240)]:
            with self.subTest(command=command),self.d.phase('setup',450):
                with self.assertRaises(ValueError):self.d.run(command,seconds,clip_setup=True)
        self.assertEqual(self.spawns,[])

    def test_expired_setup_has_no_launch_and_later_ui_requires_full_phase(self):
        self.d.process_factory=self.process()
        with self.d.phase('setup',450):
            self.clock.advance(449.5)
            with self.assertRaises(ValueError):self.d.run(['xcrun','simctl','bootstatus',DEVICE,'-b'],420,clip_setup=True)
        self.assertEqual(self.spawns,[]);self.assertFalse(self.d.simulator_uncertain)
        self.clock.advance(391)
        with self.assertRaises(BudgetExhausted):
            with self.d.phase('isolated_static',180):self.fail('Later UI must not start without full phase')
        self.assertEqual(PHASES['isolated_static'],180)
        self.assertEqual(sum(PHASES.values()),1050)


class IndependentFenceVerdictTests(unittest.TestCase):
    def test_uncertainty_rejects_even_with_cleared_generic_flags_and_positive_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=fixture(root)
            self.assertTrue(validate_result(r,root)['complete'])
            for value in ({'device_commands_forbidden':True},None,False):
                candidate=copy.deepcopy(r);candidate['simulator_uncertainty']=value;candidate['budget']['cleanup_unconfirmed']=False
                answer=validate_result(candidate,root)
                self.assertEqual(answer['result'],'incomplete');self.assertFalse(answer['complete']);self.assertFalse(answer['acceptance'])
                self.assertTrue(any('Simulator command completion' in s for s in answer['errors']))
            candidate=copy.deepcopy(r);candidate['stages'][0]['simulator_command_completion']='unconfirmed'
            self.assertEqual(validate_result(candidate,root)['result'],'incomplete')

if __name__=='__main__':unittest.main()
