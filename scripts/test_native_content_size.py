"""Local orchestration oracles only; no simulated claim of Apple UI execution."""
import ast
import copy
import datetime
import re
import sys
import threading
import time
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from native_content_size import TouchSizeRunner, applicable_cases, run_largest, qualified, verify_summary, permits_public_trait_fallback, run_public_trait_fallback
from simulator_content_size import LARGEST, probe
import test_simulator_content_size as core_tests
DEVICE=core_tests.DEVICE
HELP=core_tests.HELP

class NativeContentSizeTests(unittest.TestCase):
    def test_no_default_runner_can_launch_commands(self):
        with self.assertRaisesRegex(ValueError,'explicit reviewed'):
            probe(DEVICE,Path('unused.json'))

    def test_setting_runner_reports_whole_group_cleanup_and_preserves_exit_two(self):
        command=['xcrun','simctl','help','ui']
        execute=Mock(return_value=subprocess.CompletedProcess(command,2,'denied',''))
        runner=TouchSizeRunner(Mock(),execute)
        code,_,operation=runner(command,15,output_limit=100,tail_limit=100)
        self.assertEqual(code,2);self.assertTrue(operation['cleanup_confirmed'])
        self.assertFalse(runner.cleanup_unconfirmed)

    def test_unknown_setting_cleanup_blocks_every_later_command(self):
        error=subprocess.TimeoutExpired(['synthetic'],1);error.cleanup_confirmed=False
        execute=Mock(side_effect=error);ui=Mock()
        runner=TouchSizeRunner(ui,execute)
        _,_,operation=runner(['synthetic'],1,output_limit=100,tail_limit=100)
        self.assertFalse(operation['cleanup_confirmed'])
        for command in (['xcrun','simctl','ui'],['xcodebuild','test-without-building']):
            with self.assertRaises(RuntimeError):runner(command,1,output_limit=100,tail_limit=100)
        self.assertEqual(execute.call_count,1);ui.assert_not_called()

    def test_ui_cleanup_requires_group_and_capture_reader_not_merely_exit_zero(self):
        for group,reader in ((True,False),(False,True),(False,False),(True,True)):
            ui=Mock(return_value=(0,'',{'process_group_gone':group,'capture_reader_finished':reader}))
            runner=TouchSizeRunner(ui)
            _,_,operation=runner(['xcodebuild','test-without-building'],10,output_limit=100,tail_limit=100)
            self.assertEqual(operation['cleanup_confirmed'],group and reader)
            self.assertEqual(runner.cleanup_unconfirmed,not(group and reader))

    def test_raising_ui_callback_and_failed_unknown_report_cannot_lose_cleanup_latch(self):
        from atomic_json import write_json
        fixture=core_tests.SimulatorContentSizeTests()
        with tempfile.TemporaryDirectory() as folder:
            contract,command=fixture.ui_fixture(folder)
            current='medium';commands=[];parent={}
            def execute(args,timeout,**kwargs):
                nonlocal current
                commands.append(args)
                if args==['xcrun','simctl','help','ui']:text=HELP
                elif args[:4]==['xcrun','simctl','list','devices']:
                    text=json.dumps({'devices':{'runtime':[{'udid':DEVICE,'state':'Booted'}]}})
                else:
                    if len(args)==6:current=args[-1]
                    text=current
                return subprocess.CompletedProcess(args,0,text,'')
            def ui(args,seconds):
                self.assertTrue(runner.cleanup_unconfirmed)
                raise RuntimeError('Synthetic callback raised before child cleanup proof')
            runner=TouchSizeRunner(ui,execute)
            def save(path,value,**kwargs):
                if value.get('cleanup_unconfirmed'):raise OSError('Synthetic atomic report publication failure')
                write_json(path,value,**kwargs)
            with patch('simulator_content_size.write_json',side_effect=save):
                with self.assertRaises(OSError):
                    try:run_largest(DEVICE,Path(folder)/'report.json',command,contract,['testImport'],runner)
                    finally:
                        # The actual driver's finally uses this same in-memory latch.
                        if runner.cleanup_unconfirmed:parent['cleanup_unconfirmed']=True
            self.assertTrue(parent['cleanup_unconfirmed'])
            self.assertEqual(current,LARGEST)
            self.assertEqual(commands[-1],['xcrun','simctl','ui',DEVICE,'content_size'])
            self.assertEqual(sum(len(c)==6 and c[-1]=='medium' for c in commands),0)
            before=len(commands)
            with self.assertRaises(RuntimeError):runner(['xcrun','simctl','shutdown',DEVICE],1,output_limit=100,tail_limit=100)
            self.assertEqual(len(commands),before)

    def test_known_complete_ui_failure_clears_latch_and_can_restore(self):
        ui=Mock(return_value=(65,'ordinary failed assertions',{'process_group_gone':True,'capture_reader_finished':True}))
        execute=Mock(return_value=subprocess.CompletedProcess(['restore'],0,'medium',''))
        runner=TouchSizeRunner(ui,execute)
        code,_,operation=runner(['xcodebuild','test-without-building'],10,output_limit=100,tail_limit=100)
        self.assertEqual(code,65);self.assertTrue(operation['cleanup_confirmed'])
        self.assertFalse(runner.cleanup_unconfirmed)
        code,_,operation=runner(['xcrun','simctl','ui',DEVICE,'content_size','medium'],10,output_limit=100,tail_limit=100)
        self.assertEqual(code,0);self.assertTrue(operation['cleanup_confirmed']);execute.assert_called_once()

    def test_bounded_output_failure_does_not_become_success(self):
        execute=Mock(return_value=subprocess.CompletedProcess(['synthetic'],0,'x'*101,''))
        code,text,operation=TouchSizeRunner(Mock(),execute)(['synthetic'],1,output_limit=100,tail_limit=40)
        self.assertEqual(code,1);self.assertEqual(len(text),40)
        self.assertTrue(operation['cleanup_confirmed']);self.assertTrue(operation['output_limit_exceeded'])

    def summary(self,count=3):
        counts={'passedTests':count,'failedTests':0,'skippedTests':0,'expectedFailures':0}
        device={'deviceId':DEVICE,'platform':'watchOS Simulator','osVersion':'27.0','architecture':'arm64'}
        return {'result':'Passed','totalTestCount':count,**counts,'devicesAndConfigurations':[{**counts,'device':device}]}

    def test_result_requires_exact_executed_count_no_skips_original_device(self):
        original=self.summary()
        self.assertEqual(verify_summary(original,DEVICE,'watchOS Simulator',3)['totalTestCount'],3)
        mutations=[lambda v:v.update(totalTestCount=2),lambda v:v.update(skippedTests=1),
                   lambda v:v.update(expectedFailures=1),lambda v:v['devicesAndConfigurations'][0]['device'].update(deviceId='CLONE'),
                   lambda v:v['devicesAndConfigurations'][0]['device'].update(platform='iOS Simulator'),
                   lambda v:v['devicesAndConfigurations'][0]['device'].update(osVersion='26.0'),
                   lambda v:v['devicesAndConfigurations'][0].update(passedTests=2)]
        for mutate in mutations:
            value=copy.deepcopy(original);mutate(value)
            with self.assertRaises(RuntimeError):verify_summary(value,DEVICE,'watchOS Simulator',3)

    def test_setting_status_and_restore_proof_are_required_separately(self):
        valid={'status':'largest_ui_passed','restore_verified':True,'ui_executed':True,'ui_exit':0,'observed_largest':LARGEST,'verified_results':{'totalTestCount':3}}
        self.assertTrue(qualified(valid))
        for key,value in [('restore_verified',False),('ui_executed',False),('ui_exit',2),('status','help_action_unavailable'),('verified_results',{}),('cleanup_unconfirmed',True)]:
            self.assertFalse(qualified(dict(valid,**{key:value})))

    def unsupported(self):
        return {'device':DEVICE,'status':'original_value_not_recognized','original_raw':'unsupported','ui_executed':False,'requested_largest':None,
                'operations':[{'label':'read_original','output':'unsupported\n','operation':{'command':['xcrun','simctl','ui',DEVICE,'content_size'],'exit':0,'cleanup_confirmed':True}}]}

    def test_public_trait_requires_exact_observed_unsupported_and_every_cleanup_proof(self):
        runner=TouchSizeRunner(Mock()); valid=self.unsupported()
        self.assertTrue(permits_public_trait_fallback(valid,DEVICE,runner));self.assertFalse(qualified(valid))
        for key,value in [('device','other'),('status','device_read_rejected'),('original_raw','unknown'),('ui_executed',True),('requested_largest',LARGEST),('cleanup_unconfirmed',True)]:
            self.assertFalse(permits_public_trait_fallback(dict(valid,**{key:value}),DEVICE,runner))
        for key,value in [('exit',2),('cleanup_confirmed',False),('command',['xcrun','simctl','ui','other','content_size'])]:
            changed=copy.deepcopy(valid);changed['operations'][0]['operation'][key]=value
            self.assertFalse(permits_public_trait_fallback(changed,DEVICE,runner))
        runner.cleanup_unconfirmed=True
        self.assertFalse(permits_public_trait_fallback(valid,DEVICE,runner))

    def test_public_trait_exact_command_and_summary_do_not_qualify_system_propagation(self):
        fixture=core_tests.SimulatorContentSizeTests()
        with tempfile.TemporaryDirectory() as folder:
            contract,command=fixture.ui_fixture(folder)
            contract.update(test_bundle='TouchColorWatchUITests',platform='watchOS Simulator')
            command[command.index('-destination')+1]='platform=watchOS Simulator,id='+DEVICE
            command=[part if not part.startswith('-only-testing:') else '-only-testing:TouchColorWatchUITests/WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave' for part in command]
            ui=Mock(return_value=(0,'',{'process_group_gone':True,'capture_reader_finished':True}))
            summary=Mock(return_value=subprocess.CompletedProcess(['summary'],0,json.dumps(self.summary(1)),''))
            result=run_public_trait_fallback(self.unsupported(),DEVICE,command,contract,TouchSizeRunner(ui,summary))
            self.assertEqual(result['status'],'public_trait_ui_passed');self.assertFalse(result['system_propagation_verified']);self.assertFalse(qualified(result))
            self.assertEqual(ui.call_args.args[1],300)
            ui=Mock(return_value=(0,'',{'process_group_gone':True,'capture_reader_finished':False}));summary.reset_mock()
            result=run_public_trait_fallback(self.unsupported(),DEVICE,command,contract,TouchSizeRunner(ui,summary))
            self.assertTrue(result['cleanup_unconfirmed']);summary.assert_not_called()

    def test_only_existing_small_subset_runs_after_normal_scope_with_same_caps(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'scripts/test_extra_platforms.py').read_text()
        self.assertLess(source.index("'build/watch-ui.xcresult'"),source.index('largest_cases=applicable_cases'))
        self.assertLess(source.index("'build/vision-ui.xcresult'"),source.index('largest_cases=applicable_cases'))
        self.assertIn("timeout=600",source)
        self.assertIn("if setting.get('cleanup_unconfirmed') or size_runner.cleanup_unconfirmed:",source)
        self.assertIn("if size_runner.cleanup_unconfirmed: report['cleanup_unconfirmed']=True",source)
        for kind,case,path in [('watch',None,'TouchColorWatchUITests/WatchWorkflowTests.swift'),('vision','chinese','TouchColorVisionUITests/VisionWorkflowTests.swift'),('vision','canvas-audit','TouchColorVisionUITests/VisionWorkflowTests.swift')]:
            swift=(root/path).read_text()
            for method in applicable_cases(kind,case):self.assertIn('func '+method+'(',swift)
        self.assertEqual(len(applicable_cases('watch')),3)
        self.assertFalse(applicable_cases('vision','photos'));self.assertFalse(applicable_cases('tv'))

    def test_serial_and_single_simulator_flags_cannot_be_omitted(self):
        fixture=core_tests.SimulatorContentSizeTests()
        with tempfile.TemporaryDirectory() as folder:
            contract,command=fixture.ui_fixture(folder)
            for flag in ('-parallel-testing-enabled','-maximum-concurrent-test-simulator-destinations','-collect-test-diagnostics','-test-timeouts-enabled'):
                altered=command.copy();index=altered.index(flag);del altered[index:index+2]
                with self.assertRaises(ValueError):probe(DEVICE,Path(folder)/'none.json',altered,runner=Mock(),expected_ui=contract)

    def test_full_setting_ui_restore_and_result_oracle(self):
        fixture=core_tests.SimulatorContentSizeTests()
        with tempfile.TemporaryDirectory() as folder:
            contract,command=fixture.ui_fixture(folder)
            current='medium'
            def execute(args,timeout,**kwargs):
                nonlocal current
                if args==['xcrun','simctl','help','ui']:text=HELP
                elif args[:4]==['xcrun','simctl','list','devices']:
                    text=json.dumps({'devices':{'runtime':[{'udid':DEVICE,'state':'Booted'}]}})
                elif args[:3]==['xcrun','simctl','ui']:
                    if len(args)==6:current=args[-1]
                    text=current
                else:
                    value=self.summary(1);value['devicesAndConfigurations'][0]['device']['platform']='visionOS Simulator';text=json.dumps(value)
                return subprocess.CompletedProcess(args,0,text,'')
            def ui(args,seconds):
                self.assertEqual(current,LARGEST)
                return 0,'',{'process_group_gone':True,'capture_reader_finished':True}
            result=run_largest(DEVICE,Path(folder)/'report.json',command,contract,['testImport'],TouchSizeRunner(ui,execute))
            self.assertTrue(qualified(result));self.assertEqual(current,'medium')
            self.assertEqual(result,json.loads((Path(folder)/'report.json').read_text()))

    def driver_runner(self, folder, capture):
        # Execute the actual checked-in run function, without the Apple platform
        # orchestration at module top level. The child below is a real local process.
        from bounded_process import stop_group
        source=Path(__file__).with_name('test_extra_platforms.py').read_text()
        function=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='run')
        namespace=dict(Path=Path,datetime=datetime,time=time,json=json,re=re,threading=threading,os=os,
                       subprocess=subprocess,stop_group=stop_group,print=lambda *a,**k:None,
                       kind='vision',device={'udid':DEVICE},out=Path(folder),capture_checkpoint=capture,
                       fail_cached_capture=lambda *a: {'success':False},
                       report={'captures':[],'stages':[],'ui_runner_identifier':'synthetic.runner'})
        exec(compile(ast.Module(body=[function],type_ignores=[]),'actual-native-run','exec'),namespace)
        return namespace

    def test_actual_ui_runner_waits_for_capture_lifecycle_before_proving_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            completed=[]
            def capture(*args,**kwargs):
                self.assertTrue(kwargs['may_start']());completed.append(True)
                return {'success':True}
            values=self.driver_runner(folder,capture)
            code=values['run']([sys.executable,'-c',"print('TOUCHCOLOR_CAPTURE_REQUEST '+"+repr(DEVICE)+", flush=True)"],3)
            self.assertEqual(code,0);self.assertEqual(completed,[True])
            stage=values['report']['stages'][-1]
            self.assertTrue(stage['process_group_gone']);self.assertTrue(stage['capture_reader_finished'])

    def test_actual_ui_runner_fails_closed_while_capture_callback_is_unfinished(self):
        release=threading.Event();finished=threading.Event();allowed=[]
        try:
            with tempfile.TemporaryDirectory() as folder:
                def capture(*args,**kwargs):
                    release.wait(10);allowed.append(kwargs['may_start']());finished.set()
                    return {'success':False}
                values=self.driver_runner(folder,capture)
                code=values['run']([sys.executable,'-c',"print('TOUCHCOLOR_CAPTURE_REQUEST '+"+repr(DEVICE)+", flush=True)"],3,required=False)
                self.assertEqual(code,124);self.assertTrue(values['report']['cleanup_unconfirmed'])
                self.assertFalse(values['report']['stages'][-1]['capture_reader_finished'])
                release.set();self.assertTrue(finished.wait(2));self.assertEqual(allowed,[False])
        finally:release.set()

    def test_parent_marks_unfinished_capture_and_blocks_teardown(self):
        source=Path(__file__).with_name('test_extra_platforms.py').read_text()
        self.assertIn('capture_reader_finished=reader_complete.is_set() and not reader.is_alive()',source)
        self.assertIn("if not capture_reader_finished:\n        report['cleanup_unconfirmed']=True",source)
        self.assertIn("elif device and kind!='watch' and not report.get('cleanup_unconfirmed'):",source)
        self.assertIn("may_start=lambda: not report.get('cleanup_unconfirmed')",source)

if __name__=='__main__':unittest.main()
