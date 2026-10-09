"""Portable closed-route, absolute-clock and real owned-process regressions."""
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import uikit_managed_tests as m
from palette_lifecycle_diagnostics import CaptureStopped

ROOT = Path(__file__).resolve().parents[1]
DEVICE = '7EBB1450-0922-41FE-984D-B2B14D1C34C3'
IDENTITY = {'family': 'iPadMini', 'udid': DEVICE, 'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 1}
SETUP = {'schema': 1, 'binding': {'identity': IDENTITY, 'context': {'sha': 'a'*40}, 'receipt_sha256': 'c'*64},
         'products': {'tree_sha256': 'b'*64, 'files': 1, 'bytes': 1, 'claim': 'built_product_bytes_only'}}


def summary(family='iPadMini', suite='TouchColorTests', failures=0):
    total = {'TouchColorTests': 54, 'TouchColorUITests': 16 if family.startswith('iPad') else 17,
             'AccessibilityAudits': 7}[suite]
    skips = 0
    fields = {'totalTestCount': total, 'passedTests': total-skips-failures, 'failedTests': failures,
              'skippedTests': skips, 'expectedFailures': 0}
    return {**fields, 'result': 'Failed' if failures else 'Passed', 'startTime': 1000.1, 'finishTime': 1000.9,
            'devicesAndConfigurations': [{**{k:v for k,v in fields.items() if k!='totalTestCount'},
                'device': {'deviceId': DEVICE, 'platform': 'iOS Simulator', 'osVersion': '27.0'}}]}


class SummaryTests(unittest.TestCase):
    def check(self, value, family='iPadMini', suite='TouchColorTests', code=0):
        return m.summary_fields(json.dumps(value), family, suite, IDENTITY, 1000, 1001, code)
    def test_all_full_inventories(self):
        for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge'):
            for suite in m.STEPS:
                with self.subTest(family=family,suite=suite):
                    self.assertTrue(self.check(summary(family,suite),family,suite)['qualified'])
    def test_known_failed_remains_failed(self):
        value=self.check(summary(failures=1),code=65)
        self.assertFalse(value['qualified']); self.assertEqual(value['failedTests'],1)
    def test_destination_and_clock_adversaries(self):
        mutations=[lambda s:s.update(startTime=999.999),lambda s:s.update(finishTime=1001.001),
            lambda s:s.update(startTime=float('nan')),lambda s:s['devicesAndConfigurations'].append(copy.deepcopy(s['devicesAndConfigurations'][0])),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(deviceId='A'*36),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(platform='iOS'),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(osVersion='26.0')]
        for mutate in mutations:
            value=summary();mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):self.check(value)
    def test_count_skip_outcome_adversaries(self):
        mutations=[lambda s:s.update(totalTestCount=1),lambda s:s.update(passedTests=52),
            lambda s:s.update(failedTests=True),lambda s:s.update(skippedTests=1,passedTests=53),
            lambda s:s.update(expectedFailures=1),lambda s:s.update(result='Failed'),
            lambda s:s['devicesAndConfigurations'][0].update(passedTests=0)]
        for mutate in mutations:
            value=summary();mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.check(value)
        with self.assertRaises(ValueError):self.check(summary(),code=65)
        with self.assertRaises(ValueError):self.check(summary(failures=1),code=0)
    def test_former_phone_capability_skip_rejected_on_every_staged_profile(self):
        for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge'):
            value=summary(family)
            value.update(totalTestCount=53,passedTests=52,skippedTests=1)
            value['devicesAndConfigurations'][0].update(passedTests=52,skippedTests=1)
            with self.subTest(family=family),self.assertRaises(ValueError):self.check(value,family)
    def test_complete_staged_matrix_requires_310_passes_and_zero_skips(self):
        receipts=[summary(family,suite) for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge') for suite in m.STEPS]
        self.assertEqual(sum(r['passedTests'] for r in receipts),310)
        self.assertEqual(sum(r['skippedTests'] for r in receipts),0)
    def test_old_53_case_results_cannot_qualify_current_54_case_target(self):
        for failed in (0, 1):
            value = summary(failures=failed)
            value.update(totalTestCount=53, passedTests=53-failed)
            value['devicesAndConfigurations'][0].update(passedTests=53-failed)
            with self.subTest(failed=failed), self.assertRaises(ValueError):
                self.check(value, code=65 if failed else 0)
    def test_duplicates_fail(self):
        raw=json.dumps(summary()).replace('"passedTests": 54','"passedTests": 54, "passedTests": 54',1)
        with self.assertRaises(ValueError):m.summary_fields(raw,'iPadMini','TouchColorTests',IDENTITY,1000,1001,0)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
        self.tick=0.;self.calls=[];self.reader_calls=[];self.inject=None;self.read_inject=None
        self.family='iPadMini';self.suite='TouchColorTests'
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(m,'load_setup',return_value=copy.deepcopy(SETUP)))
        self.stack.enter_context(patch.object(m,'read_binding',return_value=copy.deepcopy(SETUP['binding'])))
        self.stack.enter_context(patch.object(m,'verify_source'))
        self.stack.enter_context(patch.object(m,'require_hosted'))
        self.stack.enter_context(patch.object(m,'require_fixtures'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    def tearDown(self):
        self.stack.close();os.chdir(self.old);self.tmp.cleanup()
    def runner(self,command,deadline):
        began=self.tick;self.calls.append((command,deadline));self.tick+=1
        value={'status':'timely_exit','exit_code':0,'host_cleanup_confirmed':True,'simulator_completion':'xcode_command_returned_only'}
        if self.inject:self.inject(value,deadline)
        value.update(started_monotonic=began,finished_monotonic=self.tick,
                     elapsed_seconds=self.tick-began,deadline_monotonic=deadline)
        return value
    def reader(self,command,**kw):
        self.reader_calls.append((command,kw))
        if self.read_inject:self.read_inject(kw)
        return subprocess.CompletedProcess(command,0,json.dumps(summary(self.family,self.suite)).encode(),b'')
    def run_case(self,**kwargs):
        products=kwargs.pop('products',lambda **kw:copy.deepcopy(SETUP['products']))
        return m.run_suite(self.family,self.suite,started=0,clock=lambda:self.tick,
            wall=lambda:1000+self.tick,runner=self.runner,reader=self.reader,
            products=products,**kwargs)
    def record(self):return json.loads(m.record_path(self.family,self.suite).read_text())
    def pending(self):return Path('build/'+self.family+'-runtime-command-uncertain').exists()
    def test_exact_success(self):
        self.assertEqual(self.run_case(),0);self.assertFalse(self.pending());self.assertTrue(self.record()['qualified'])
        self.assertEqual(self.calls[0][1],800)
        self.assertEqual(self.reader_calls[0][1],{'seconds':20,'cap':1048576,'cleanup_grace':10})
        self.assertEqual(self.record()['command']['prior_500_benchmark'],
            {'admitted_monotonic':0.,'deadline_monotonic':500.,
             'completed_before_deadline':True,'status':'within_prior_limit'})
    def clear_case(self):
        m.record_path(self.family,self.suite).unlink(missing_ok=True)
        Path('build/'+self.family+'-runtime-command-uncertain').unlink(missing_ok=True)
        self.calls.clear();self.reader_calls.clear()
    def test_only_mini_hosted_receives_larger_command_and_phase(self):
        for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge'):
            for suite,(phase,grant,_) in m.STEPS.items():
                self.family=family;self.suite=suite;self.tick=0.
                mini=family=='iPadMini' and suite=='TouchColorTests'
                expected_phase,expected_grant=(960,800) if mini else (phase,grant)
                scans=[]
                def scan(**kw):
                    scans.append(kw);return copy.deepcopy(SETUP['products'])
                with self.subTest(family=family,suite=suite):
                    self.assertEqual(self.run_case(products=scan),0)
                    self.assertEqual(self.calls[0][1],expected_grant)
                    self.assertEqual(scans[0]['post_test_deadline'],expected_phase-40)
                    self.assertEqual('prior_500_benchmark' in self.record()['command'],mini)
                    self.clear_case()
                    # Every non-Mini route retains its exact 40-second entry boundary.
                    self.tick=100 if mini else 40
                    self.assertEqual(self.run_case(),3);self.assertEqual(self.calls,[])
                    self.clear_case()
    def test_unknown_family_or_suite_cannot_obtain_mini_allowance(self):
        for family,suite in [('iPadmini','TouchColorTests'),('iPadMiniExtra','TouchColorTests'),
                             ('iPadMini','TouchColorTests/testOne'),('iPadMini','hosted')]:
            self.family=family;self.suite=suite
            with self.subTest(family=family,suite=suite),self.assertRaises(ValueError):self.run_case()
            self.assertEqual(self.calls,[])
    def test_observed_composite_fits_but_retains_prior_benchmark_exceeded(self):
        self.inject=lambda value,deadline:setattr(self,'tick',770.044)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(self.run_case(),0)
        record=self.record();benchmark=record['command']['prior_500_benchmark']
        self.assertFalse(benchmark['completed_before_deadline'])
        self.assertEqual(benchmark['status'],'prior_limit_exceeded')
        self.assertEqual(record['summary']['fields']['passedTests'],54)
        self.assertEqual(record['summary']['fields']['skippedTests'],0)
        self.assertTrue(record['qualified']);self.assertFalse(self.pending())
        printed=json.loads(output.getvalue().split('UIKIT_MANAGED_RESULT:',1)[1])
        self.assertEqual(printed['command']['prior_500_benchmark'],benchmark)
    def test_prior_benchmark_exact_representable_boundaries_use_admission(self):
        # These instants catch both directions of rounded-deadline subtraction.
        for admission in (0.,.002,.003):
            old=admission+500
            for finish,within in ((math.nextafter(old,-math.inf),True),
                                  (old,False),(math.nextafter(old,math.inf),False)):
                self.tick=admission
                self.inject=lambda value,deadline,finish=finish:setattr(self,'tick',finish)
                with self.subTest(admission=admission,finish=finish):
                    self.assertEqual(self.run_case(),0)
                    benchmark=self.record()['command']['prior_500_benchmark']
                    self.assertEqual(benchmark['admitted_monotonic'],admission)
                    self.assertEqual(benchmark['deadline_monotonic'],old)
                    self.assertIs(benchmark['completed_before_deadline'],within)
                    self.assertEqual(self.calls[0][1],admission+800)
                    self.clear_case()
        self.assertLess((.002+800)-800+500,.002+500)
        self.assertGreater((.003+800)-800+500,.003+500)
    def test_entry_persistence_defines_one_shared_admission_instant(self):
        original=m.write_json;calls=[0]
        def delayed(*args,**kw):
            original(*args,**kw);calls[0]+=1
            if calls[0]==1:self.tick=.002
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),0)
        self.assertEqual(self.calls[0][1],800.002)
        self.assertEqual(self.record()['command']['prior_500_benchmark']['deadline_monotonic'],500.002)
        self.assertEqual(self.record()['command']['prior_500_benchmark']['admitted_monotonic'],.002)
    def test_wall_observation_overhead_does_not_extend_admitted_deadlines(self):
        observations=[0]
        def wall():
            observations[0]+=1
            if observations[0]==1:self.tick=.006
            return 1000+self.tick
        self.assertEqual(m.run_suite(self.family,self.suite,started=0,clock=lambda:self.tick,
            wall=wall,runner=self.runner,reader=self.reader,
            products=lambda **kw:copy.deepcopy(SETUP['products'])),0)
        command=self.record()['command']
        self.assertEqual(command['started_monotonic'],.006)
        self.assertEqual(command['deadline_monotonic'],800)
        self.assertEqual(command['prior_500_benchmark']['admitted_monotonic'],0)
        self.assertEqual(command['prior_500_benchmark']['deadline_monotonic'],500)
    def test_other_routes_keep_their_original_post_wall_command_clock(self):
        for family,suite,grant in [('iPadLarge','TouchColorTests',500),
                                  ('iPhoneCompact','TouchColorTests',500),
                                  ('iPhoneLarge','TouchColorTests',500),
                                  ('iPadMini','TouchColorUITests',1100),
                                  ('iPadMini','AccessibilityAudits',620)]:
            self.family=family;self.suite=suite;self.tick=0.;observations=[0]
            def wall():
                observations[0]+=1
                if observations[0]==1:self.tick=.006
                return 1000+self.tick
            with self.subTest(family=family,suite=suite):
                self.assertEqual(m.run_suite(family,suite,started=0,clock=lambda:self.tick,
                    wall=wall,runner=self.runner,reader=self.reader,
                    products=lambda **kw:copy.deepcopy(SETUP['products'])),0)
                self.assertEqual(self.calls[0][1],.006+grant)
                self.assertNotIn('prior_500_benchmark',self.record()['command'])
                self.clear_case()
    def test_unobserved_or_unclean_completion_has_unknown_prior_benchmark(self):
        for status,cleanup in [('incomplete',True),('incomplete',False),('not_started',None),
                               ('timely_exit',False),('timely_exit',None)]:
            self.tick=0.
            self.inject=lambda value,deadline:value.update(status=status,host_cleanup_confirmed=cleanup)
            with self.subTest(status=status,cleanup=cleanup):
                self.assertEqual(self.run_case(),3)
                benchmark=self.record()['command']['prior_500_benchmark']
                self.assertIsNone(benchmark['completed_before_deadline'])
                self.assertEqual(benchmark['status'],'unknown')
                self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
                self.clear_case()
    def test_missing_or_non_numeric_completion_is_never_a_prior_benchmark_pass(self):
        original=self.runner
        for finish in (None,True,'unknown'):
            self.tick=0.
            def run(command,deadline):
                value=original(command,deadline);value['finished_monotonic']=finish;return value
            self.runner=run
            with self.subTest(finish=finish):
                self.assertEqual(self.run_case(),0)
                self.assertEqual(self.record()['command']['prior_500_benchmark']['status'],'unknown')
                self.clear_case()
    def test_nonfinite_completion_fails_existing_strict_receipt_write(self):
        original=self.runner
        for finish in (float('nan'),float('inf')):
            self.tick=0.
            def run(command,deadline):
                value=original(command,deadline);value['finished_monotonic']=finish;return value
            self.runner=run;output=io.StringIO()
            with self.subTest(finish=finish),contextlib.redirect_stdout(output),self.assertRaises(ValueError):
                self.run_case()
            self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
            printed=json.loads(output.getvalue().split('UIKIT_MANAGED_RESULT:',1)[1])
            self.assertEqual(printed['command']['prior_500_benchmark']['status'],'unknown')
            self.clear_case()
    def test_real_invoke_finish_and_cleanup_drive_prior_benchmark(self):
        for finish,within in ((math.nextafter(500.,-math.inf),True),(500.,False),(770.044,False)):
            self.tick=0.
            class Process:
                pid=123456789
                def wait(inner,timeout):self.tick=finish;return 0
            self.runner=lambda command,deadline:m.invoke(command,deadline,clock=lambda:self.tick,
                popen=lambda *a,**kw:Process())
            with self.subTest(finish=finish),patch.object(m,'group_exists',return_value=False):
                self.assertEqual(self.run_case(),0)
                command=self.record()['command']
                self.assertEqual(command['started_monotonic'],0)
                self.assertEqual(command['finished_monotonic'],finish)
                self.assertEqual(command['elapsed_seconds'],finish)
                self.assertTrue(command['host_cleanup_confirmed'])
                self.assertIs(command['prior_500_benchmark']['completed_before_deadline'],within)
                self.clear_case()
    def test_real_invoke_start_offset_does_not_reset_prior_benchmark(self):
        observations=[0]
        def wall():
            observations[0]+=1
            if observations[0]==1:self.tick=.006
            return 1000+self.tick
        class Process:
            pid=123456789
            def wait(inner,timeout):self.tick=500.003;return 0
        self.runner=lambda command,deadline:m.invoke(command,deadline,clock=lambda:self.tick,
            popen=lambda *a,**kw:Process())
        with patch.object(m,'group_exists',return_value=False):
            self.assertEqual(m.run_suite(self.family,self.suite,started=0,clock=lambda:self.tick,
                wall=wall,runner=self.runner,reader=self.reader,
                products=lambda **kw:copy.deepcopy(SETUP['products'])),0)
        command=self.record()['command']
        self.assertEqual(command['started_monotonic'],.006)
        self.assertLess(command['elapsed_seconds'],500)
        self.assertEqual(command['prior_500_benchmark']['admitted_monotonic'],0)
        self.assertEqual(command['prior_500_benchmark']['status'],'prior_limit_exceeded')
    def test_real_invoke_timeout_does_not_infer_completion_from_cleanup(self):
        for cleanup in (True,False):
            self.tick=0.;stops=[]
            class Process:
                pid=123456789
                def wait(inner,timeout):
                    self.tick=800
                    raise subprocess.TimeoutExpired('xcodebuild',timeout)
            def stop(process,grace):
                stops.append(grace);self.tick+=20;return cleanup
            self.runner=lambda command,deadline:m.invoke(command,deadline,clock=lambda:self.tick,
                popen=lambda *a,**kw:Process(),stopper=stop)
            with self.subTest(cleanup=cleanup):
                self.assertEqual(self.run_case(),3)
                command=self.record()['command']
                self.assertEqual(command['finished_monotonic'],820)
                self.assertEqual(command['status'],'incomplete')
                self.assertIs(command['host_cleanup_confirmed'],cleanup)
                self.assertEqual(command['prior_500_benchmark']['status'],'unknown')
                self.assertIsNone(command['prior_500_benchmark']['completed_before_deadline'])
                self.assertEqual(stops,[10]);self.assertTrue(self.pending())
                self.assertEqual(self.reader_calls,[]);self.clear_case()
    def test_runner_exception_preserves_unknown_admitted_benchmark_and_fence(self):
        def fail(command,deadline):raise OSError('launch unavailable')
        self.runner=fail
        self.assertEqual(self.run_case(),3)
        benchmark=self.record()['command']['prior_500_benchmark']
        self.assertEqual(benchmark['admitted_monotonic'],0)
        self.assertEqual(benchmark['deadline_monotonic'],500)
        self.assertEqual(benchmark['status'],'unknown')
        self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
    def test_99_seconds_entry_fits(self):
        self.tick=99
        # Make summary dates correspond to this injected entry time.
        def read(command,**kw):
            value=summary();value.update(startTime=1099.1,finishTime=1099.9)
            return subprocess.CompletedProcess(command,0,json.dumps(value).encode(),b'')
        self.reader=read
        self.assertEqual(self.run_case(),0);self.assertEqual(self.calls[0][1],899)
    def test_exact_100_seconds_entry_refuses_full_admission(self):
        self.tick=100;self.assertEqual(self.run_case(),3);self.assertEqual(self.calls,[])
    def test_insufficient_and_rounded_equality_reserves_refuse_without_spawn(self):
        for entry in (101.,math.nextafter(100.,-math.inf)):
            self.tick=entry
            self.assertGreaterEqual(entry+800+2*m.CLEANUP+m.SUMMARY,960)
            self.assertEqual(self.run_case(),3);self.assertEqual(self.calls,[])
            self.assertFalse(self.pending());self.clear_case()
    def test_persist_overhead_cannot_start_expired_grant(self):
        original=m.write_json
        def delayed(*args,**kw):
            original(*args,**kw);self.tick=100
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.calls,[]);self.assertTrue(self.pending())
    def test_marker_fsync_overhead_cannot_borrow_owned_cleanup_reserve(self):
        original=m.os.fsync
        def delayed(fd):
            original(fd);self.tick=100
        with patch.object(m.os,'fsync',side_effect=delayed):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.calls,[]);self.assertTrue(self.pending())
    def test_late_xctest_retains_fence_and_early_outcome(self):
        self.inject=lambda value,deadline:setattr(self,'tick',deadline)
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
        self.assertEqual(self.record()['command']['status'],'timely_exit')
        self.assertFalse(self.record()['qualified'])
    def test_timeout_unknown_or_cancel_cannot_start_reader(self):
        for status in ('incomplete','not_started'):
            self.inject=lambda value,deadline:value.update(status=status,host_cleanup_confirmed=False)
            self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
            Path('build/iPadMini-runtime-command-uncertain').unlink();m.record_path('iPadMini','TouchColorTests').unlink()
    def test_late_summary_keeps_fence(self):
        self.read_inject=lambda kw:setattr(self,'tick',1+kw['seconds'])
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertFalse(self.record()['qualified'])
    def test_summary_persistence_cost_is_subtracted_before_capture(self):
        original=m.write_json;calls=[0]
        def delayed(*args,**kwargs):
            original(*args,**kwargs);calls[0]+=1
            if calls[0]==3:self.tick+=19
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),0)
        self.assertEqual(self.reader_calls[0][1]['seconds'],1)
    def test_expired_summary_persistence_never_dispatches_reader(self):
        original=m.write_json;calls=[0]
        def delayed(*args,**kwargs):
            original(*args,**kwargs);calls[0]+=1
            if calls[0]==3:self.tick+=20
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_summary_unknown_cleanup_keeps_fence(self):
        def fail(kw):raise CaptureStopped('duration-limit',False)
        self.read_inject=fail
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertFalse(self.record()['qualified'])
        self.assertIs(self.record()['summary']['host_cleanup_confirmed'],False)
    def test_known_failed_suite_retains_complete_failed_result(self):
        self.inject=lambda value,deadline:value.update(exit_code=65)
        self.reader=lambda command,**kw:subprocess.CompletedProcess(command,0,json.dumps(summary(failures=1)).encode(),b'')
        self.assertEqual(self.run_case(),65);self.assertFalse(self.pending())
        self.assertEqual(self.record()['summary']['status'],'complete');self.assertFalse(self.record()['qualified'])
    def test_known_failed_functional_result_does_not_suppress_required_audit(self):
        self.suite='TouchColorUITests'
        self.inject=lambda value,deadline:value.update(exit_code=65)
        self.reader=lambda command,**kw:subprocess.CompletedProcess(command,0,
            json.dumps(summary(self.family,self.suite,failures=1)).encode(),b'')
        self.assertEqual(self.run_case(),65);self.assertFalse(self.pending())
        functional=m.record_path(self.family,self.suite)
        before=functional.read_bytes()
        self.suite='AccessibilityAudits';self.inject=None
        def audit_reader(command,**kw):
            value=summary(self.family,self.suite)
            value.update(startTime=1001.1,finishTime=1001.9)
            return subprocess.CompletedProcess(command,0,json.dumps(value).encode(),b'')
        self.reader=audit_reader
        self.assertEqual(self.run_case(),0)
        self.assertTrue(self.record()['qualified']);self.assertFalse(self.pending())
        self.assertEqual(functional.read_bytes(),before)
        self.assertFalse(json.loads(before)['qualified'])
        self.assertEqual(len(self.calls),2)

    def test_uncertain_functional_result_blocks_audit_before_any_new_command(self):
        self.suite='TouchColorUITests'
        self.inject=lambda value,deadline:value.update(status='incomplete',exit_code=None,
            host_cleanup_confirmed=None,simulator_completion='unconfirmed')
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending())
        before=list(self.calls);readers=list(self.reader_calls)
        self.suite='AccessibilityAudits';self.inject=None
        with self.assertRaises(m.WarmupFailed):self.run_case()
        self.assertEqual(self.calls,before);self.assertEqual(self.reader_calls,readers)
        self.assertFalse(m.record_path(self.family,self.suite).exists())

    def test_prepare_marker_overhead_cannot_reset_nominal_cap(self):
        calls=[]
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,
            host_runner=lambda command,timeout:(calls.append(timeout) or subprocess.CompletedProcess(command,0,'','')))
        original=Path.open
        class DelayedMarker:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):self.tick=0;return self
            def write(inner,data):self.tick=31;return inner.stream.write(data)
            def __exit__(inner,*args):inner.stream.close()
        def opening(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return DelayedMarker(stream) if str(path).endswith('-runtime-command-uncertain') else stream
        with patch.object(Path,'open',new=opening):
            with self.assertRaises(ValueError):w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[]);self.assertTrue(self.pending())
    def test_all_managed_finalizers_stop_at_existing_uncertainty(self):
        Path('build').mkdir();Path('build/iPadMini-runtime-command-uncertain').write_text('old')
        with patch.object(m,'read_managed_device') as inventory,patch.object(m,'setup_capture') as capture:
            with self.assertRaises(Exception):m.fixture_seed('iPadMini',started=0)
            with patch.object(sys,'argv',['tool','iPadMini','managed-shutdown']):
                with self.assertRaises(Exception):m.main()
            inventory.assert_not_called();capture.assert_not_called()
    def test_known_reader_nonzero_preserves_command_and_no_false_uncertainty(self):
        self.reader=lambda command,**kw:subprocess.CompletedProcess(command,1,b'',b'error')
        self.assertEqual(self.run_case(),3);self.assertFalse(self.pending());self.assertEqual(self.record()['command']['exit_code'],0)
    def test_changed_product_stops_before_summary(self):
        with patch.object(m,'read_binding',return_value={}):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_post_product_scan_uses_original_phase_and_retains_failure(self):
        seen=[];observation={'status':'failed','complete':False,'reason':'elapsed_limit',
                           'files':204,'bytes':26142729,'elapsed_seconds':20.25}
        self.inject=lambda value,deadline:value.update(exit_code=65)
        def scan(**kw):
            seen.append(kw);self.tick=21.25
            raise m.ProductInventoryError(observation)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(seen[0]['post_test_deadline'],920)
        self.assertIsNotNone(seen[0]['clock']);self.assertEqual(self.reader_calls,[])
        record=self.record();self.assertEqual(record['command']['exit_code'],65)
        self.assertIs(record['command']['host_cleanup_confirmed'],True)
        self.assertEqual(record['summary'],{'status':'not_started'})
        self.assertEqual(record['product_inventory'],observation)
        self.assertFalse(record['qualified']);self.assertTrue(self.pending())
        printed=json.loads(output.getvalue().split('UIKIT_MANAGED_RESULT:',1)[1])
        self.assertEqual(printed['product_inventory'],observation)
        with patch.object(m,'read_managed_device') as inventory,patch.object(m,'setup_capture') as capture:
            with self.assertRaises(Exception):m.fixture_seed('iPadMini',started=0)
            with patch.object(sys,'argv',['tool','iPadMini','managed-shutdown']):
                with self.assertRaises(Exception):m.main()
            inventory.assert_not_called();capture.assert_not_called()
    def test_changed_product_digest_remains_unqualified(self):
        def scan(**kw):
            kw['observation'].update(status='complete',complete=True,reason=None)
            return {**SETUP['products'],'tree_sha256':'c'*64}
        self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
        self.assertEqual(self.record()['error'],'Post-test products changed')
        self.assertTrue(self.record()['product_inventory']['complete'])
        self.assertFalse(self.record()['qualified'])
    def test_product_scan_at_phase_tail_cannot_start_summary(self):
        def scan(**kw):
            self.tick=kw['post_test_deadline']
            return copy.deepcopy(SETUP['products'])
        self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_interrupted_real_scan_retains_completed_reads_and_command(self):
        root=Path('build/simulator/Build/Products')
        for path in (root/'Debug-iphonesimulator/TouchColor.app',
                     root/'Debug-iphonesimulator/TouchColorUITests-Runner.app',
                     Path('build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app')):
            path.mkdir(parents=True);(path/'binary').write_bytes(b'binary')
        (root/'TouchColor.xctestrun').write_bytes(b'configuration')
        original=m.read_regular;calls=[0]
        def interrupted(*args,**kw):
            calls[0]+=1
            if calls[0]==2:
                self.tick=1.125
                raise m.WarmupFailed('UIKit owned command interrupted by signal 15')
            return original(*args,**kw)
        self.inject=lambda value,deadline:value.update(exit_code=65)
        with patch.object(m,'read_regular',side_effect=interrupted):
            self.assertEqual(self.run_case(products=m.product_identity),3)
        record=self.record();value=record['product_inventory']
        self.assertEqual(value['reason'],'interrupted');self.assertEqual(value['status'],'failed')
        self.assertFalse(value['complete']);self.assertEqual(value['files'],1)
        self.assertEqual(value['bytes'],len(b'configuration'));self.assertEqual(value['elapsed_seconds'],.125)
        self.assertEqual(record['command']['exit_code'],65);self.assertTrue(record['command']['host_cleanup_confirmed'])
        self.assertEqual(record['summary'],{'status':'not_started'})
        self.assertFalse(record['qualified']);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
    def test_repeated_result_refused(self):
        self.assertEqual(self.run_case(),0)
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(len(self.calls),1)
    def test_existing_uncertainty_blocks_all_calls(self):
        Path('build').mkdir();Path('build/iPadMini-runtime-command-uncertain').write_text('old')
        with self.assertRaises(Exception):self.run_case()
        self.assertEqual(self.calls,[]);self.assertEqual(self.reader_calls,[])
    def test_pre_capture_setup_deadline_clamp(self):
        calls=[];self.tick=579
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,
            host_runner=lambda command,timeout:(calls.append(timeout) or subprocess.CompletedProcess(command,0,'','')))
        w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[1])
        self.tick=580
        with self.assertRaises(Exception):w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[1])
    def test_late_setup_result_rejected(self):
        def late(command,timeout):self.tick+=timeout;return subprocess.CompletedProcess(command,0,'','')
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,host_runner=late)
        with self.assertRaises(ValueError):w.command(['host-only-proof'],30,simulator=False)
        self.assertTrue(self.pending())


class ProductInventoryTests(unittest.TestCase):
    def completion_environment(self):
        from test_uikit_managed_device import ENV
        from uikit_completion import REF, WORKFLOW
        return patch.dict(os.environ, {**ENV, 'GITHUB_REF': REF, 'GITHUB_WORKFLOW_REF': WORKFLOW,
            'GITHUB_JOB': 'completion', 'TC_COMPLETION_GROUP': 'ipad-mini'}, clear=True)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
        self.tick=0.;self.observation={}
        self.roots=(Path('build/simulator/Build/Products'),Path('build/palette-fixtures/Build/Products'))
        self.bundles=(self.roots[0]/'Debug-iphonesimulator/TouchColor.app',
                      self.roots[0]/'Debug-iphonesimulator/TouchColorUITests-Runner.app',
                      self.roots[1]/'Debug-iphonesimulator/PaletteFixtures.app')
        for bundle in self.bundles:
            bundle.mkdir(parents=True);(bundle/'binary').write_bytes(b'built bytes')
        (self.roots[0]/'TouchColor.xctestrun').write_bytes(b'configuration')
    def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
    def scan(self,**kw):
        return m.product_identity(clock=lambda:self.tick,observation=self.observation,**kw)
    def failure(self,reason,**kw):
        with self.assertRaises(m.ProductInventoryError) as raised:self.scan(**kw)
        self.assertEqual(raised.exception.observation,self.observation)
        self.assertEqual(self.observation['reason'],reason)
        self.assertEqual(self.observation['status'],'failed');self.assertFalse(self.observation['complete'])
        self.assertLess(len(json.dumps(self.observation).encode()),2048)
        self.assertNotIn(str(Path.cwd()),json.dumps(self.observation))
        return self.observation
    def test_identity_recipe_and_full_auxiliary_scope_are_unchanged(self):
        auxiliary=self.roots[0]/'unselected.swiftmodule';auxiliary.write_bytes(b'auxiliary')
        expected=hashlib.sha256();count=size=0
        for root in self.roots:
            for parent,directories,files in os.walk(root):
                directories.sort()
                for name in sorted(files):
                    path=Path(parent)/name;raw=path.read_bytes();count+=1;size+=len(raw)
                    expected.update(path.as_posix().encode()+b'\0'+str(len(raw)).encode()+b'\0'+raw)
        identity=self.scan()
        self.assertEqual(identity,{'tree_sha256':expected.hexdigest(),'files':count,'bytes':size,
                                   'claim':'built_product_bytes_only'})
        self.assertTrue(self.observation['complete']);self.assertEqual(self.observation['allowance_seconds'],10)
        self.tick=100;self.assertEqual(self.scan(post_test_deadline=200),identity)
        self.assertEqual(self.observation['allowance_seconds'],20)
        auxiliary.write_bytes(b'changedxx');self.assertNotEqual(self.scan(),identity)
    def test_changed_consumed_binary_changes_identity(self):
        identity=self.scan();binary=self.bundles[0]/'binary'
        binary.write_bytes(b'other bytes');self.assertNotEqual(self.scan(),identity)
    def test_initial_ten_second_boundary_is_unchanged(self):
        original=m.read_regular
        def slow(*args,**kw):
            raw=original(*args,**kw);self.tick=10;return raw
        with patch.object(m,'read_regular',side_effect=slow):value=self.failure('elapsed_limit')
        self.assertEqual(value['allowance_seconds'],10);self.assertEqual(value['elapsed_seconds'],10)
        self.assertEqual(value['files'],1);self.assertEqual(value['bytes'],len(b'configuration'))

    def test_preparation_reread_accepts_before_thirty_and_rejects_exact_deadline(self):
        original = m.read_regular
        with self.completion_environment():
            identity = self.scan()
            for returned in (10.695, math.nextafter(30, -math.inf), 30):
                self.tick = 0.
                def slow(*args, **kwargs):
                    raw = original(*args, **kwargs); self.tick = returned; return raw
                with self.subTest(returned=returned), patch.object(m, 'read_regular', side_effect=slow):
                    if returned == 30:
                        value = self.failure('phase_deadline', preparation_reread_deadline=30)
                        self.assertEqual(value['files'], 1)
                    else:
                        self.assertEqual(self.scan(preparation_reread_deadline=30), identity)
                    self.assertEqual(self.observation['allowance_seconds'], 30)
                    self.assertEqual(self.observation['deadline_monotonic'], 30)
                    self.assertEqual(self.observation['stage'], 'preparation_reread')

    def test_preparation_metadata_uses_the_already_admitted_deadline(self):
        with self.completion_environment():
            setup = {**SETUP, 'products': self.scan()}
            m.write_json(m.record_path('iPadMini', 'setup'), setup)
            original = m.read_regular
            for metadata_finished in (29., 30.):
                self.tick = 0.; product_reads = []
                def read(path, *args, **kwargs):
                    raw = original(path, *args, **kwargs)
                    if path == m.record_path('iPadMini', 'setup'):
                        self.tick = metadata_finished
                    else:
                        product_reads.append(path)
                    return raw
                with self.subTest(metadata_finished=metadata_finished), \
                        patch.object(m, 'read_binding', return_value=SETUP['binding']), \
                        patch.object(m, 'read_regular', side_effect=read):
                    if metadata_finished == 30:
                        with self.assertRaises(m.ProductInventoryError) as raised:
                            m.load_setup('iPadMini', preparation_reread_deadline=30, clock=lambda: self.tick)
                        self.assertEqual(raised.exception.observation['granted_seconds'], 0)
                        self.assertFalse(product_reads)
                    else:
                        self.assertEqual(m.load_setup('iPadMini', preparation_reread_deadline=30,
                                                      clock=lambda: self.tick), setup)
                        self.assertTrue(product_reads)

    def test_preparation_metadata_then_file_read_cannot_restart_thirty_seconds(self):
        with self.completion_environment():
            setup = {**SETUP, 'products': self.scan()}
            m.write_json(m.record_path('iPadMini', 'setup'), setup)
            original = m.read_regular
            def read(path, *args, **kwargs):
                raw = original(path, *args, **kwargs)
                self.tick = 29 if path == m.record_path('iPadMini', 'setup') else 30
                return raw
            with patch.object(m, 'read_binding', return_value=SETUP['binding']), \
                    patch.object(m, 'read_regular', side_effect=read), self.assertRaises(m.ProductInventoryError) as raised:
                m.load_setup('iPadMini', preparation_reread_deadline=30, clock=lambda: self.tick)
            value = raised.exception.observation
            self.assertEqual(value['started_monotonic'], 29)
            self.assertEqual(value['deadline_monotonic'], 30)
            self.assertEqual(value['granted_seconds'], 1)
            self.assertEqual(value['files'], 1)
            self.assertFalse(value['complete'])

    def test_preparation_late_hash_update_and_final_digest_cannot_return_identity(self):
        for stage in ('update', 'hexdigest'):
            self.tick = 0.; real = hashlib.sha256()
            class SlowDigest:
                def update(inner, data):
                    real.update(data)
                    if stage == 'update': self.tick = 30
                def hexdigest(inner):
                    result = real.hexdigest()
                    if stage == 'hexdigest': self.tick = 30
                    return result
            with self.subTest(stage=stage), self.completion_environment(), \
                    patch.object(m.hashlib, 'sha256', return_value=SlowDigest()):
                self.failure('phase_deadline', preparation_reread_deadline=30)

    def test_preparation_mode_rejects_original_foreign_or_mixed_scan_routes(self):
        with self.completion_environment():
            changes = ({'GITHUB_REF': 'refs/heads/ios-original-release'},
                       {'GITHUB_WORKFLOW_SHA': 'b'*40}, {'GITHUB_REPOSITORY': 'other/ColorPicker'},
                       {'TC_COMPLETION_GROUP': 'ipad-large'}, {'GITHUB_JOB': 'compatibility'})
            for changed in changes:
                with self.subTest(changed=changed), patch.dict(os.environ, changed), \
                        patch.object(m, 'read_regular') as read, self.assertRaises(ValueError):
                    self.scan(preparation_reread_deadline=30)
                read.assert_not_called()
            with self.assertRaises(ValueError): self.scan(post_test_deadline=100, preparation_reread_deadline=30)
            for deadline in (True, -1, float('inf'), float('nan'), '30'):
                with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                    self.scan(preparation_reread_deadline=deadline)
        with patch.dict(os.environ, {}, clear=True), patch.object(m, 'read_binding') as binding:
            with self.assertRaises(ValueError): self.scan(preparation_reread_deadline=30)
            with self.assertRaises(ValueError): m.load_setup('iPadMini', preparation_reread_deadline=30)
            binding.assert_not_called()

    def test_preparation_identity_and_entire_built_product_scope_stay_identical(self):
        auxiliary = self.roots[0]/'unselected.swiftmodule'; auxiliary.write_bytes(b'auxiliary')
        identity = self.scan(); limits = dict(self.observation['limits'])
        with self.completion_environment():
            self.assertEqual(self.scan(preparation_reread_deadline=30), identity)
            self.assertEqual(self.observation['limits'], limits)
            for path in (auxiliary, self.bundles[0]/'binary', self.bundles[1]/'binary', self.bundles[2]/'binary'):
                before = path.read_bytes(); path.write_bytes(b'changed')
                self.assertNotEqual(self.scan(preparation_reread_deadline=30), identity)
                path.write_bytes(before)
            self.assertEqual(limits, {'directory_entries':8192, 'files':8192,
                                     'bytes':1024**3, 'file_bytes':128*1024*1024})

    def test_original_setup_reread_still_uses_default_ten_second_scan(self):
        setup = {**SETUP, 'products': self.scan()}
        m.write_json(m.record_path('iPadMini', 'setup'), setup)
        with patch.object(m, 'read_binding', return_value=SETUP['binding']), \
                patch.object(m, 'product_identity', return_value=setup['products']) as scan:
            self.assertEqual(m.load_setup('iPadMini'), setup)
        scan.assert_called_once_with()
    def test_post_scan_accepts_ten_but_rejects_twenty_seconds(self):
        original=m.read_regular
        def slow(*args,**kw):
            raw=original(*args,**kw);self.tick=10;return raw
        with patch.object(m,'read_regular',side_effect=slow):self.scan(post_test_deadline=100)
        self.assertTrue(self.observation['complete']);self.assertEqual(self.observation['elapsed_seconds'],10)
        self.tick=0
        def late(*args,**kw):
            raw=original(*args,**kw);self.tick=20;return raw
        with patch.object(m,'read_regular',side_effect=late):value=self.failure('elapsed_limit',post_test_deadline=100)
        self.assertEqual(value['granted_seconds'],20)
    def test_original_phase_clips_post_scan_and_refuses_expired_entry(self):
        original=m.read_regular;self.tick=550
        def late(*args,**kw):
            raw=original(*args,**kw);self.tick=560;return raw
        with patch.object(m,'read_regular',side_effect=late):value=self.failure('phase_deadline',post_test_deadline=560)
        self.assertEqual(value['granted_seconds'],10);self.assertEqual(value['deadline_monotonic'],560)
        with patch.object(m,'read_regular') as read:value=self.failure('phase_deadline',post_test_deadline=560)
        read.assert_not_called();self.assertEqual(value['files'],0);self.assertEqual(value['granted_seconds'],0)
    def test_final_hash_cost_cannot_escape_deadline(self):
        real=hashlib.sha256()
        class SlowDigest:
            def update(inner,data):real.update(data);self.tick=20
            def hexdigest(inner):return real.hexdigest()
        with patch.object(m.hashlib,'sha256',return_value=SlowDigest()):
            self.failure('elapsed_limit',post_test_deadline=100)
    def test_directory_fanout_has_its_own_reason(self):
        with patch.object(m.os,'walk',return_value=iter([(str(self.roots[0]),[],['x']*8193)])):
            value=self.failure('directory_entries_limit')
        self.assertEqual(value['directory_entries'],8193);self.assertEqual(value['files'],0)
    def counted_walk(self,count):
        def walk(root,**kw):
            if Path(root)==self.roots[0]:
                for start in range(0,count,1024):
                    yield str(root),[],[str(i) for i in range(start,min(start+1024,count))]
        return walk
    def test_aggregate_file_count_boundary_is_unchanged(self):
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8192)),patch.object(m,'read_regular',return_value=b''):
            self.assertEqual(self.scan()['files'],8192)
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8193)),patch.object(m,'read_regular',return_value=b''):
            value=self.failure('file_count_limit')
        self.assertEqual(value['files'],8193);self.assertEqual(value['bytes'],0)
    def test_aggregate_byte_boundary_does_not_allocate_a_gibibyte(self):
        class SizedBytes(bytes):
            def __len__(self):return 128*1024*1024
        def read(path,cap,**kw):
            self.assertEqual(cap,128*1024*1024);return SizedBytes(b'x')
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8)),patch.object(m,'read_regular',side_effect=read):
            self.assertEqual(self.scan()['bytes'],1024**3)
        with patch.object(m.os,'walk',side_effect=self.counted_walk(9)),patch.object(m,'read_regular',side_effect=read):
            value=self.failure('total_bytes_limit')
        self.assertEqual(value['bytes'],9*128*1024*1024);self.assertEqual(value['files'],9)
    def test_single_file_cap_remains_safety_failure(self):
        with (self.roots[0]/'oversized').open('wb') as stream:stream.truncate(128*1024*1024+1)
        value=self.failure('safety');self.assertEqual(value['safety_detail'],'unsafe_or_unreadable_file')
        self.assertEqual(value['limits']['file_bytes'],128*1024*1024)
    def test_linked_product_and_file_fail_without_disclosing_path(self):
        (self.roots[0]/'linked').symlink_to(self.bundles[0]/'binary')
        value=self.failure('safety');self.assertEqual(value['safety_detail'],'unsafe_or_unreadable_file')
    def test_walk_read_error_is_not_silently_omitted(self):
        def walk(root,**kw):
            kw['onerror'](PermissionError('/private/unrelated/path'));return iter(())
        with patch.object(m.os,'walk',side_effect=walk):value=self.failure('safety')
        self.assertEqual(value['safety_detail'],'unreadable_directory')
        self.assertNotIn('/private',json.dumps(value))


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name);Path('build').mkdir()
    def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
    def hosted(self):
        fields=m.summary_fields(json.dumps(summary()),'iPadMini','TouchColorTests',IDENTITY,1000,1001,0)
        return {'schema':1,'suite':'TouchColorTests','setup':SETUP,'qualified':True,
                'command':{'status':'timely_exit','exit_code':0,'host_cleanup_confirmed':True},
                'summary':{'status':'complete','fields':fields}}
    def test_full_hosted_receipt_required(self):
        value=self.hosted();m.write_json(m.record_path('iPadMini','TouchColorTests'),value)
        self.assertEqual(m.require_hosted('iPadMini',SETUP),value)
    def test_old_52_plus_one_receipt_cannot_seed_any_staged_profile(self):
        for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge'):
            value=self.hosted()
            m.write_json(m.record_path(family,'TouchColorTests'),value)
            self.assertEqual(m.require_hosted(family,SETUP),value)
            value['summary']['fields'].update(totalTestCount=53,passedTests=52,skippedTests=1)
            m.write_json(m.record_path(family,'TouchColorTests'),value)
            with self.subTest(family=family),self.assertRaises(ValueError):m.require_hosted(family,SETUP)
    def test_old_53_pass_receipt_cannot_seed_current_54_case_target(self):
        value = self.hosted()
        value['summary']['fields'].update(totalTestCount=53, passedTests=53)
        m.write_json(m.record_path('iPadMini','TouchColorTests'), value)
        with self.assertRaises(ValueError):m.require_hosted('iPadMini', SETUP)
    def test_flags_alone_cannot_hide_failed_or_missing_counts(self):
        changes=[lambda v:v['summary'].update(status='pending'),lambda v:v['summary'].update(fields={}),
            lambda v:v['summary']['fields'].update(totalTestCount=1),lambda v:v['summary']['fields'].update(failedTests=1),
            lambda v:v['summary']['fields'].update(device='foreign'),lambda v:v.update(error='late'),
            lambda v:v.update(schema=True),lambda v:v['command'].update(host_cleanup_confirmed=False)]
        for change in changes:
            value=self.hosted();change(value);m.write_json(m.record_path('iPadMini','TouchColorTests'),value)
            with self.subTest(change=change),self.assertRaises(ValueError):m.require_hosted('iPadMini',SETUP)
    def test_fixture_receipt_and_seed_both_bound(self):
        m.write_json(m.record_path('iPadMini','fixtures'),{'schema':2,'setup':SETUP,'complete':True,
            'readiness':{'schema':2,'device':DEVICE,'binding_sha256':'c'*64,
                'basis':'owned_booted_inventory_snapshot_only','completion':None,'operations':[],
                'observed_monotonic':100}})
        m.write_json(Path('build/iPadMini-fixture-seeded'),IDENTITY)
        m.require_fixtures('iPadMini',SETUP)
        value={**IDENTITY,'udid':'foreign'};m.write_json(Path('build/iPadMini-fixture-seeded'),value)
        with self.assertRaises(ValueError):m.require_fixtures('iPadMini',SETUP)
    def test_trusted_file_rejects_links_and_bounded_oversize(self):
        path=Path('build/plain');path.write_bytes(b'123')
        self.assertEqual(m.read_regular(path,3),b'123')
        with self.assertRaises(ValueError):m.read_regular(path,2)
        link=Path('build/link');link.symlink_to('plain')
        with self.assertRaises(ValueError):m.read_regular(link,3)
    def test_setup_capture_uses_existing_bounded_reader(self):
        with patch.object(m,'capture',return_value=subprocess.CompletedProcess([],0,b'ok',b'')) as capture:
            result=m.setup_capture(['host-only-proof'],3)
        capture.assert_called_once_with(['host-only-proof'],seconds=3,cap=1000000,cleanup_grace=10)
        self.assertEqual(result.stdout,'ok')


class ProcessTests(unittest.TestCase):
    def test_actual_host_exit(self):
        value=m.invoke([sys.executable,'-c','pass'],m.time.monotonic()+3)
        self.assertEqual(value['status'],'timely_exit');self.assertTrue(value['host_cleanup_confirmed'])
    def test_actual_host_failure(self):
        value=m.invoke([sys.executable,'-c','raise SystemExit(65)'],m.time.monotonic()+3)
        self.assertEqual(value['exit_code'],65);self.assertEqual(value['status'],'timely_exit')
    def test_actual_timeout_owned_cleanup(self):
        value=m.invoke([sys.executable,'-c','import time;time.sleep(10)'],m.time.monotonic()+.05)
        self.assertEqual(value['status'],'incomplete');self.assertTrue(value['host_cleanup_confirmed'])
    def test_expired_entry_does_not_spawn(self):
        calls=[]
        value=m.invoke(['unused'],0,clock=lambda:1,popen=lambda *a,**k:calls.append(a))
        self.assertEqual(calls,[]);self.assertEqual(value['status'],'incomplete')


class SourceTests(unittest.TestCase):
    def test_original_case_and_target_arguments(self):
        for family in ('iPhoneCompact','iPhoneLarge','iPadMini','iPadLarge'):
            for suite in m.STEPS:
                argv=m.test_argv(family,suite,DEVICE)
                self.assertEqual(argv.count('test-without-building'),1)
                self.assertEqual(argv[argv.index('-default-test-execution-time-allowance')+1],'180')
                self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance')+1],'240')
                self.assertNotIn('-test-iterations',argv);self.assertFalse(any('retry' in a for a in argv))
                self.assertIn('platform=iOS Simulator,id='+DEVICE,argv)
    def test_source_inventory_matches_complete_counts(self):
        import re
        files=['ColorPickerTests/'+n for n in ('ColorPickerTests.m','TCAdaptiveLayoutTests.m','TCWorkspaceTests.m',
             'TCPhotoImportLifecycleTests.m','ColorCoreEquivalenceTests.swift','TCPhotoImportTests.swift')]
        files+=['TouchColorPhoneCompanion/Tests/PhonePaletteImportTests.swift']
        count=sum(len(re.findall(r'(?:-\s*\(void\)\s*|func\s+)(test\w+)\b', (ROOT/p).read_text())) for p in files)
        self.assertEqual(count,54)
        for name,count in [('TouchColorUITests',17),('TouchColorIPadUITests',16),('TouchColorAccessibilityUITests',7)]:
            text=(ROOT/'TouchColorUITests'/(name+'.m')).read_text()
            self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',text)),count)
    def test_closed_workflow_budgets_and_gates(self):
        import re
        text=(ROOT/'.github/workflows/ios.yml').read_text()
        job=text.split('  compatibility:\n',1)[1]
        self.assertIn("    timeout-minutes: ${{ matrix.family == 'iPadMini' && 70 || 60 }}\n",job)
        self.assertEqual(re.findall(r'^      max-parallel: (.+)$',job,re.M),['2'])
        def step(name):return job.split('      - name: '+name+'\n',1)[1].split('      - name:',1)[0]
        hosted=step('Unit and constrained-window layout tests')
        functional=step('Functional UI tests')
        seeded=step('Prepare Files fixture and seed synthetic photo')
        self.assertIn("steps.hosted-tests.outcome == 'success'",seeded)
        self.assertIn("timeout-minutes: ${{ matrix.family == 'iPadMini' && 16 || 10 }}",hosted)
        self.assertIn('timeout-minutes: 20',functional)
        self.assertIn('timeout-minutes: 10',seeded)
        # The only two conditional ceilings are this row and its hosted step.
        self.assertEqual(re.findall(r'^  ([a-z-]+):$',text.split('jobs:\n',1)[1],re.M),
                         ['compile-prerequisites','compatibility'])
        self.assertEqual(re.findall(r'^        timeout-minutes: (.+)$',job,re.M),
            ['6','5','8','4','10',"${{ matrix.family == 'iPadMini' && 16 || 10 }}",
             '10','20','12','2','2','3'])
        self.assertEqual(re.findall(r'^    timeout-minutes: (.+)$',text,re.M),
            ['20',"${{ matrix.family == 'iPadMini' && 70 || 60 }}"])
    def test_optional_device_diagnostics_follow_all_required_ui_and_audits(self):
        text=(ROOT/'.github/workflows/ios.yml').read_text()
        names=['Functional UI tests','Official XCTest accessibility audits',
               'Read bounded app and Files-service metadata after a functional failure','Shut down simulator']
        positions=[text.index('      - name: '+name+'\n') for name in names]
        self.assertEqual(positions,sorted(positions))
        audit=text[positions[1]:positions[2]]
        self.assertIn("!cancelled() && steps.seed-device.outcome == 'success'",audit)
        self.assertNotIn('runtime-diagnostics',audit)
        self.assertNotIn('functional-tests.outcome',audit)
        diagnostic=text[positions[2]:positions[3]]
        self.assertIn("steps.functional-tests.outcome == 'failure'",diagnostic)
        self.assertIn('timeout-minutes: 2',diagnostic)
        self.assertIn('uikit_runtime_diagnostics.py',diagnostic)
        shutdown=text[positions[3]+len('      - name: Shut down simulator\n'):].split('      - name:',1)[0]
        self.assertIn("steps.runtime-diagnostics.outputs.simulator_safe == 'true'",shutdown)
        self.assertIn('managed-shutdown',shutdown)

    def test_live_phone_pipe_and_legacy_paths_preserved(self):
        text=(ROOT/'scripts/test_simulators.sh').read_text()
        self.assertIn('set -euo pipefail',text)
        self.assertIn('"$suite" == managed-functional',text)
        self.assertIn('palette_lifecycle_diagnostics.py" retain "$family"',text)
        self.assertIn('run_test_suite()',text);self.assertIn('uikit_warmup.py" "$family" "$suite"',text)
    def test_no_prehosted_boot_or_standalone_touchcolor_launch(self):
        import inspect
        prehosted=inspect.getsource(m.configure)
        self.assertNotIn("'boot'",prehosted);self.assertNotIn("'bootstatus'",prehosted)
        text=prehosted+inspect.getsource(m.fixture_seed)+inspect.getsource(m.ManagedWarmup.fixture_device)
        self.assertIn('warmup.fixture_device(setup)',text)
        self.assertNotIn("device, 'com.mango.touchColor'",text)
        self.assertIn('warmup.fixture(container)',text);self.assertIn('warmup.seed(device)',text)
    def test_finite_schedule_arithmetic(self):
        self.assertEqual(m.STEPS,{'TouchColorTests':(600,500,54),
            'TouchColorUITests':(1200,1100,None),'AccessibilityAudits':(720,620,7)})
        self.assertEqual((m.CLEANUP,m.SUMMARY),(20,20))
        for step,command,_ in m.STEPS.values():
            self.assertEqual(step-command-2*m.CLEANUP-m.SUMMARY,40)


if __name__=='__main__':unittest.main()
