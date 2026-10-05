"""Complete setup order/canonical maxima and retained timing replays; no native calls."""
import ast
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
from test_watch_crown_driver import Clock,environment
from test_watch_crown_result import fixture
import watch_crown_result as result

ROOT=Path(__file__).resolve().parents[1]
PHONE='11111111-1111-4111-8111-111111111111';WATCH='22222222-2222-4222-8222-222222222222';PAIR='33333333-3333-4333-8333-333333333333'
IOS='com.apple.CoreSimulator.SimRuntime.iOS-27-0';WATCHOS='com.apple.CoreSimulator.SimRuntime.watchOS-27-0'
PHONE_TYPE='com.apple.CoreSimulator.SimDeviceType.iPhone-17';WATCH_TYPE='com.apple.CoreSimulator.SimDeviceType.Apple-Watch-SE-3-40mm'
CAPS={'list':30,'create':60,'pair':60,'pair_activate':60,'boot':180,'bootstatus':420}
# Exact operation families/order from e107 report, rounded retained durations.
# Replace only its failed final5s inventory with the paired1410 successful19.237s
# same-family read. These are scheduling fixtures, not a new native outcome.
PRELUDE=[1.146,.244,.385,.245,.240,.248,.283]
E107_BOOT=[13.327,77.943,56.080,91.770]
CANONICAL_BOOT=[6.637,123.119,99.743,189.882]
FINAL_READ=19.237
SETUP=600


class SetupReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        Path('build/evidence').mkdir(parents=True);self.clock=Clock();self.commands=[];self.allowances=[]
        self.d=driver.Driver(environment(),clock=lambda:self.clock.mono,wall=lambda:self.clock.wall)
        self.quiet=patch.object(driver,'_write_console_nonblocking',return_value=False);self.quiet.start()
    def tearDown(self):self.quiet.stop();os.chdir(self.old);self.temp.cleanup()
    def install(self,boot=E107_BOOT,*,activate=False,final_seconds=FINAL_READ,final_state='Booted',durations_override=None):
        clock=self.clock;commands=self.commands;allowances=self.allowances
        durations=list(PRELUDE[:6])+([.200] if activate else [])+[PRELUDE[6]]+list(boot)
        if durations_override is not None:durations=list(durations_override)
        self.expected_durations=durations
        class Process:
            pid=123456
            active=not activate;paired=False;created=[];booted=set()
            def __init__(self,command,**kwargs):
                commands.append(command);self.command=command;self.index=len(commands)-1
                op=command[2]
                if op=='create':raw=(PHONE if len(Process.created)==0 else WATCH)+'\n'
                elif op=='pair':raw=PAIR+'\n'
                elif command[2:4]==['list','pairs']:
                    pairs={PAIR:{'watch':{'udid':WATCH},'phone':{'udid':PHONE},'state':'(active, connected)' if Process.active else '(inactive, connected)'}} if Process.paired else {}
                    raw=json.dumps({'pairs':pairs})
                elif command[2:4]==['list','devices']:
                    devices={IOS:[{'name':'iPhone 17','udid':'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA','isAvailable':True,'deviceTypeIdentifier':PHONE_TYPE,'state':'Shutdown'}],
                             WATCHOS:[{'name':'Apple Watch SE 3 (40mm)','udid':'BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB','isAvailable':True,'deviceTypeIdentifier':WATCH_TYPE,'state':'Shutdown'}]}
                    if len(Process.created)==2:
                        devices[IOS].append({'name':'owned phone','udid':PHONE,'isAvailable':True,'deviceTypeIdentifier':PHONE_TYPE,'state':final_state})
                        devices[WATCHOS].append({'name':'owned Watch','udid':WATCH,'isAvailable':True,'deviceTypeIdentifier':WATCH_TYPE,'state':final_state})
                    raw=json.dumps({'devices':devices})
                elif op=='bootstatus':raw='synthetic monitor completed\n'
                else:raw=''
                self.stdout=io.BytesIO(raw.encode())
            def wait(self,timeout=None):
                duration=durations[self.index];allowances.append(timeout)
                if duration>=timeout:
                    clock.advance(timeout);raise subprocess.TimeoutExpired(self.command,timeout)
                clock.advance(duration);op=self.command[2]
                if op=='create':Process.created.append(PHONE if not Process.created else WATCH)
                elif op=='pair':Process.paired=True
                elif op=='pair_activate':Process.active=True
                elif op=='boot':Process.booted.add(self.command[3])
                return 0
        self.d.process_factory=Process
    def expected_commands(self,activate=False):
        # Created names are random; compare every other argument exactly.
        result=[['xcrun','simctl','list','devices','available','-j'],['xcrun','simctl','list','pairs','-j'],
                ['xcrun','simctl','create','<phone-name>',PHONE_TYPE,IOS],['xcrun','simctl','create','<watch-name>',WATCH_TYPE,WATCHOS],
                ['xcrun','simctl','pair',WATCH,PHONE],['xcrun','simctl','list','pairs','-j']]
        if activate:result.append(['xcrun','simctl','pair_activate',PAIR])
        result.extend([['xcrun','simctl','list','pairs','-j'],['xcrun','simctl','boot',PHONE],['xcrun','simctl','bootstatus',PHONE,'-b'],
                       ['xcrun','simctl','boot',WATCH],['xcrun','simctl','bootstatus',WATCH,'-b']])
        return result
    def assert_full_setup(self,activate=False):
        observed=copy.deepcopy(self.commands)
        self.assertTrue(observed[2][3].startswith('TouchColor-Crown-phone-'));observed[2][3]='<phone-name>'
        self.assertTrue(observed[3][3].startswith('TouchColor-Crown-watch-'));observed[3][3]='<watch-name>'
        self.assertEqual(observed,self.expected_commands(activate))
        stages=self.d.report['stages'];phase=self.d.report['phases'][0]
        self.assertTrue(phase['completed']);self.assertLess(phase['finished_monotonic']-phase['started_monotonic'],SETUP)
        for stage in stages:
            self.assertEqual(stage['setup_command_cap_seconds'],CAPS[stage['command'][2]])
            remaining=phase['started_monotonic']+SETUP-stage['started_monotonic']
            self.assertAlmostEqual(stage['timeout_seconds'],min(CAPS[stage['command'][2]],remaining))
            self.assertLessEqual(stage['deadline_monotonic'],phase['started_monotonic']+SETUP)
            self.assertLessEqual(stage['deadline_monotonic'],self.d.budget.record['started_monotonic']+1020)
        self.assertNotIn('setup_readback',self.d.report)
        self.assertEqual({r['udid'] for r in self.d.report['setup_proof']['events']},{PHONE,WATCH})
        self.assertEqual(self.d.report['setup_proof']['simultaneous_state'],'unobserved')
        self.assertEqual(self.d.report['cases'],[]);self.assertFalse(self.d.simulator_uncertain)
    def test_full_e107_setup_with_successful19_second_final_readback(self):
        self.install()
        self.clock.advance(.775+45.689)
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        self.assert_full_setup();self.assertEqual(self.commands[-1][2],'bootstatus')
        self.assertAlmostEqual(self.clock.mono-100,.775+45.689+sum(self.expected_durations))
    def test_full_canonical419_second_setup_clips_all_caps_and_preserves_readback(self):
        self.install(CANONICAL_BOOT)
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        self.assert_full_setup();self.assertGreater(self.allowances[-1],CANONICAL_BOOT[-1]);self.assertLessEqual(self.allowances[-1],420)
        self.assertAlmostEqual(self.clock.mono-100,sum(PRELUDE)+419.381)
        self.assertEqual(self.d.budget.record['started_monotonic'],100)
    def test_conditional_pair_activation_keeps_same_order_and60_second_cap(self):
        self.install(activate=True)
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        self.assert_full_setup(activate=True)
        activation=next(s for s in self.d.report['stages'] if s['command'][2]=='pair_activate')
        self.assertEqual(activation['timeout_seconds'],60)
    def test_any_inventory_timeout_keeps_fsync_barrier_and_zero_later_commands(self):
        self.install(durations_override=[31])
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(RuntimeError):self.d.setup()
        self.assertEqual(len(self.commands),1);self.assertEqual(self.d.report['stages'][-1]['timeout_seconds'],30)
        self.assertTrue(self.d.simulator_uncertain)
        self.assertEqual(self.d.report['simulator_uncertainty']['marker_durability'],'fsync_confirmed')
        before=len(self.commands);self.d.cleanup();self.d.evidence()
        with self.assertRaises(ValueError):self.d.run(['git','rev-parse','HEAD'],3)
        self.assertEqual(len(self.commands),before)
    def test_final_bootstatus_clipped_by_setup_ceiling_cannot_borrow_reserves(self):
        self.install([6.637,123.119,99.743,SETUP-220.000])
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(RuntimeError):self.d.setup()
        last=self.d.report['stages'][-1]
        self.assertEqual(last['command'],['xcrun','simctl','bootstatus',WATCH,'-b'])
        self.assertLess(last['timeout_seconds'],SETUP-220.000);self.assertTrue(self.d.simulator_uncertain)
        self.assertAlmostEqual(last['deadline_monotonic'],100+SETUP)
    def test_no_extra_query_is_started_after_last_timely_bootstatus(self):
        pre=sum(PRELUDE)+6.637+123.119+99.743
        self.install([6.637,123.119,99.743,SETUP-.5-pre])
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        self.assertEqual(len(self.commands),11);self.assertFalse(self.d.simulator_uncertain)
        self.assertNotIn('setup_readback',self.d.report)
        self.assertEqual(self.d.report['setup_proof']['inventory'],'not_requested')
    def test_no_simultaneous_booted_state_is_invented(self):
        self.install(final_state='Shutdown')
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        self.assertEqual(len(self.commands),11);self.assertNotIn('setup_readback',self.d.report)
        self.assertEqual(self.d.report['setup_proof']['simultaneous_state'],'unobserved')
        self.assertTrue(self.d.report['phases'][0]['completed'])
    def test_later_ui_still_requires_full_original_phase_allowance(self):
        self.install(CANONICAL_BOOT);self.clock.advance(46.464)
        with patch.object(driver,'stop_group',return_value=True):self.d.setup()
        with self.d.phase('actual_cold',240):self.clock.advance(240)
        with self.d.phase('isolated_static',180):self.clock.advance(180)
        with self.assertRaises(BudgetExhausted):
            with self.d.phase('rgb_positive',180):self.fail('Must not start shortened RGB phase')
        self.assertEqual(len(self.commands),11);self.assertEqual(self.d.budget.record['minutes'],25)


class CanonicalMapTests(unittest.TestCase):
    def test_map_matches_canonical_source_without_importing_imperative_runner(self):
        canonical=(ROOT/'scripts/test_extra_platforms.py').read_text()
        tree=ast.parse(canonical);found={k:set() for k in CAPS}
        setup_end=next(i for i,line in enumerate(canonical.splitlines(),1) if line.lstrip().startswith('test_common='))
        for call in ast.walk(tree):
            if not isinstance(call,ast.Call) or call.lineno>=setup_end or not isinstance(call.func,ast.Name) or call.func.id not in ('run','check_output'):continue
            if not call.args or not isinstance(call.args[0],ast.List):continue
            args=call.args[0].elts
            if len(args)<3 or not all(isinstance(v,ast.Constant) for v in args[:3]):continue
            prefix=[v.value for v in args[:3]]
            if prefix[:2]!=['xcrun','simctl'] or prefix[2] not in CAPS:continue
            timeout=next((k.value for k in call.keywords if k.arg=='timeout'),call.args[1] if len(call.args)>1 else None)
            if isinstance(timeout,ast.Constant):found[prefix[2]].add(timeout.value)
        self.assertEqual(found,{key:{value} for key,value in CAPS.items()})
        self.assertEqual(driver.SETUP_COMMAND_CAPS,CAPS)
        source=ast.parse((ROOT/'scripts/run_watch_crown_control.py').read_text())
        for node in ast.walk(source):
            if isinstance(node,ast.ImportFrom):self.assertNotEqual(node.module,'test_extra_platforms')
            if isinstance(node,ast.Import):self.assertNotIn('test_extra_platforms',[n.name for n in node.names])
        methods=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Driver').body
        for name in ('text','value'):
            method=next(n for n in methods if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(method.args.defaults[0].value,5) # Cleanup/evidence/source defaults unchanged.
    def test_independent_validator_rejects_shortened_or_expanded_canonical_map(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=fixture(root)
            self.assertTrue(result.validate_result(receipt,root)['complete'])
            for index,original in enumerate(receipt['stages']):
                if original['phase']!='setup':continue
                family=original['command'][2];cap=CAPS[family]
                for bad in (cap-1,cap+1,None):
                    with self.subTest(family=family,bad=bad):
                        value=copy.deepcopy(receipt);value['stages'][index]['setup_command_cap_seconds']=bad
                        answer=result.validate_result(value,root)
                        self.assertFalse(answer['complete']);self.assertNotEqual(answer['result'],'passed')

if __name__=='__main__':unittest.main()
