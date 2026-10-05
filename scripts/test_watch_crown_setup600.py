"""600-second setup redistribution; the unchanged original deadlines remain exact."""
import ast
import copy
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import run_watch_crown_control as driver
import test_watch_crown_setup_allowances as replay
from job_budget import BudgetExhausted,RESERVES,STARTUP_MARGIN
from watch_crown_contract import PHASES
from test_watch_crown_result import fixture
import watch_crown_result as validator

ROOT=Path(__file__).resolve().parents[1]
# fa1ff report.json exact original-clock values. The last native raw0 was late.
ORIGINAL_START=93.400197708
SETUP_START=166.224344666
WATCH_READ_START=474.769036375
WATCH_READ_FINISH=616.309486750
OLD_DEADLINE=616.224344666
SETUP_OFFSET=SETUP_START-ORIGINAL_START
READ_OFFSET=WATCH_READ_START-SETUP_START
READ_DURATION=WATCH_READ_FINISH-WATCH_READ_START
LATE=WATCH_READ_FINISH-OLD_DEADLINE
# Exact retained stage starts/finishes, relative to the same setup clock.
OBSERVED=[(166.224389916,168.440449416),(168.441964958,168.841200208),
 (168.842566875,169.357834958),(169.359882500,169.696087916),
 (169.698749208,170.035187375),(170.036786791,170.436435416),
 (170.448975416,170.953023875),(170.961144958,174.559325000),
 (174.786356291,339.075601041),(339.242122250,470.463748958),
 (WATCH_READ_START,WATCH_READ_FINISH)]


class RedistributionTests(unittest.TestCase):
    def create(self):
        value=replay.SetupReplayTests();value.setUp();self.addCleanup(value.tearDown);return value
    def native_last_read(self,ceiling,extra=0):
        t=self.create();t.clock.advance(SETUP_OFFSET);clock=t.clock
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):t.commands.append(command);self.stdout=io.BytesIO(b'raw completion')
            def wait(self,timeout=None):clock.advance(READ_DURATION);return 0
        t.d.process_factory=Process
        with patch.object(driver,'stop_group',return_value=True),t.d.phase('setup',ceiling):
            clock.advance(READ_OFFSET+extra)
            row,_=t.d.run(['xcrun','simctl','bootstatus',replay.WATCH,'-b'],420,clip_setup=True,required=False)
        return t,row
    def test_exact_old_late_zero_remains_incomplete_with_no_later_commands(self):
        # Historical450s bound is deliberately replayed, not restored in source.
        t=self.create();t.clock.advance(SETUP_OFFSET);clock=t.clock
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):t.commands.append(command);self.stdout=io.BytesIO(b'raw completion')
            def wait(self,timeout=None):clock.advance(READ_DURATION);return 0
        t.d.process_factory=Process
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(ValueError):
                with t.d.phase('setup',450):
                    clock.advance(READ_OFFSET)
                    row,_=t.d.run(['xcrun','simctl','bootstatus',replay.WATCH,'-b'],420,clip_setup=True,required=False)
        self.assertEqual(row['raw_exit'],0);self.assertEqual(row['exit'],124);self.assertTrue(row['timed_out'])
        self.assertAlmostEqual(row['finished_monotonic']-row['deadline_monotonic'],LATE,places=9)
        self.assertTrue(t.d.simulator_uncertain);t.d.cleanup();t.d.evidence();self.assertEqual(len(t.commands),1)
    def test_same_measured_read_fits600_without_changing420_command_cap(self):
        t,row=self.native_last_read(600)
        self.assertEqual(row['setup_command_cap_seconds'],420)
        self.assertAlmostEqual(row['timeout_seconds'],600-READ_OFFSET,places=9)
        self.assertEqual(row['raw_exit'],0);self.assertEqual(row['exit'],0);self.assertFalse(row['timed_out'])
        self.assertFalse(t.d.simulator_uncertain)
        self.assertAlmostEqual(row['deadline_monotonic']-row['finished_monotonic'],150-LATE,places=9)
    def test_same085_second_late_zero_still_fences_at_the_new600_deadline(self):
        t=self.create();t.clock.advance(SETUP_OFFSET);clock=t.clock
        class Process:
            pid=123456
            def __init__(self,command,**kwargs):t.commands.append(command);self.stdout=io.BytesIO(b'raw completion')
            def wait(self,timeout=None):clock.advance(READ_DURATION);return 0
        t.d.process_factory=Process
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(ValueError):
                with t.d.phase('setup',600):
                    clock.advance(READ_OFFSET+150)
                    row,_=t.d.run(['xcrun','simctl','bootstatus',replay.WATCH,'-b'],420,clip_setup=True,required=False)
        self.assertAlmostEqual(row['finished_monotonic']-row['deadline_monotonic'],LATE,places=9)
        self.assertEqual(row['raw_exit'],0);self.assertEqual(row['exit'],124)
        self.assertTrue(t.d.simulator_uncertain);self.assertEqual(t.d.report['simulator_uncertainty']['marker_durability'],'fsync_confirmed')
        t.d.cleanup();t.d.evidence();self.assertEqual(len(t.commands),1)
    def test_full_fa1ff_timing_plus_hypothetical_final_read_preserves_later_full_admission(self):
        t=self.create();t.clock.advance(SETUP_OFFSET)
        durations=[finish-start for start,finish in OBSERVED]+[replay.FINAL_READ]
        t.install(durations_override=durations);original=t.d.run
        setup_local=t.clock.mono
        def timed(command,*args,**kwargs):
            index=len(t.commands)
            target=setup_local+((OBSERVED[index][0] if index<len(OBSERVED) else WATCH_READ_FINISH)-SETUP_START)
            if target>t.clock.mono:t.clock.advance(target-t.clock.mono)
            return original(command,*args,**kwargs)
        t.d.run=timed
        with patch.object(driver,'stop_group',return_value=True):t.d.setup()
        t.assert_full_setup()
        self.assertAlmostEqual(t.clock.mono-setup_local,450+LATE,places=9)
        self.assertEqual(t.d.report['cases'],[]);self.assertFalse(t.d.report['acceptance'])
        self.assertEqual(t.d.report['setup_proof']['simultaneous_state'],'unobserved')
        for row in t.d.report['stages']:
            self.assertLessEqual(row['deadline_monotonic'],100+1020)
        with t.d.phase('actual_cold',240):t.clock.advance(240)
        with t.d.phase('isolated_static',180):t.clock.advance(180)
        with self.assertRaises(BudgetExhausted):
            with t.d.phase('rgb_positive',180):self.fail('No shortened RGB control is allowed')
        self.assertEqual(len(t.commands),11);self.assertEqual(t.d.report['cases'],[])
    def test_full_setup_admission_latest420_seconds_or_no_commands(self):
        for offset in (420,420.001):
            with self.subTest(offset=offset):
                t=replay.SetupReplayTests();t.setUp()
                try:
                    t.install(replay.CANONICAL_BOOT);t.clock.advance(offset)
                    if offset>420:
                        with self.assertRaises(BudgetExhausted):t.d.setup()
                        self.assertEqual(t.commands,[]);self.assertEqual(t.d.report['phases'],[])
                    else:
                        with patch.object(driver,'stop_group',return_value=True):t.d.setup()
                        self.assertTrue(t.d.report['phases'][0]['completed'])
                        self.assertTrue(all(s['deadline_monotonic']<=1120 for s in t.d.report['stages']))
                        with self.assertRaises(BudgetExhausted):
                            with t.d.phase('actual_cold',240):self.fail('Insufficient original work remains')
                finally:t.tearDown()
    def test_caps_pool_reserves_and_required_ui_allowances_are_unchanged(self):
        self.assertEqual(PHASES,{'preflight':30,'builds':240,'setup':600,'actual_cold':240,'isolated_static':180,'rgb_positive':180})
        self.assertEqual(sum(PHASES.values()),1470)
        self.assertEqual(driver.SETUP_COMMAND_CAPS,{'list':30,'create':60,'pair':60,'pair_activate':60,'boot':180,'bootstatus':420})
        self.assertEqual(RESERVES,{'cleanup':130,'evidence':180,'validation':60,'upload':60,'overhead':20});self.assertEqual(STARTUP_MARGIN,30)
        t=self.create();self.assertEqual(t.d.budget.remaining('work'),1020);self.assertEqual(t.d.budget.record['minutes'],25)
    def test_independent_validator_requires_the_exact_new_phase_limit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=fixture(root);self.assertTrue(validator.validate_result(receipt,root)['complete'])
            for bad in (450,599,601,1020):
                with self.subTest(bad=bad):
                    mutated=copy.deepcopy(receipt);next(p for p in mutated['phases'] if p['name']=='setup')['limit_seconds']=bad
                    self.assertFalse(validator.validate_result(mutated,root)['complete'])
    def test_reviewed_canonical_ordering_is_sequential_and_readiness_is_not_skipped(self):
        canonical=(ROOT/'scripts/test_extra_platforms.py').read_text()
        order=["run(['xcrun','simctl','boot',phone_id],180)","run(['xcrun','simctl','bootstatus',phone_id,'-b'],420)",
               "run(['xcrun','simctl','boot',device['udid']],180,required=False)","run(['xcrun','simctl','bootstatus',device['udid'],'-b'],420)"]
        positions=[canonical.index(text) for text in order];self.assertEqual(positions,sorted(positions))
        paired=ast.parse((ROOT/'scripts/test_paired_watch.py').read_text())
        method=next(n for n in paired.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_owned_pair')
        loop=next(n for n in method.body if isinstance(n,ast.For))
        self.assertEqual([v.value for v in loop.iter.elts],['phone','watch'])
        calls=[n.value for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='run']
        self.assertEqual([call.args[0].elts[2].value for call in calls],['boot','bootstatus'])
        self.assertFalse(any(isinstance(n,(ast.AsyncFor,ast.Await)) for n in ast.walk(method)))

if __name__=='__main__':unittest.main()
