"""Portable admission, bounded execution and orchestration regressions, no native claim."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_watch_crown_control as driver
from watch_crown_contract import binding, test_command, METHODS, PHASES
from job_budget import JobBudget, BudgetExhausted, EXPECTED_MINUTES, RESERVES, STARTUP_MARGIN

ROOT=Path(__file__).resolve().parents[1]


def environment():
    return dict(GITHUB_EVENT_NAME='push',GITHUB_REPOSITORY='100mango/ColorPicker',
      GITHUB_REF='refs/heads/codex/watch-crown-diagnostic',GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,
      GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',TOUCHCOLOR_JOB_PLATFORM='watch-crown-control',
      TOUCHCOLOR_JOB_LANE='watch-crown-control-smallest',TOUCHCOLOR_JOB_MINUTES='25',
      TOUCHCOLOR_WATCH_PROFILE='smallest',TOUCHCOLOR_TEXT_PHASE='normal',RUNNER_ARCH='ARM64',
      DEVELOPER_DIR='/Applications/Xcode_27.app/Contents/Developer',TOUCHCOLOR_MAX_EVIDENCE_BYTES='1200000',
      TOUCHCOLOR_JOB_STARTED_EPOCH='10000',TOUCHCOLOR_JOB_STARTED_MONOTONIC='100')


class Clock:
    def __init__(self): self.mono=100.;self.wall=10000.
    def advance(self,n):self.mono+=n;self.wall+=n


class ContractTests(unittest.TestCase):
    def test_exact_push_only_source_contract(self):
        self.assertEqual(binding(environment())['sha'],'a'*40)
        bad=[('GITHUB_REF','refs/heads/main'),('GITHUB_REF','refs/heads/codex/platform-integration'),
            ('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_EVENT_NAME','pull_request'),
            ('GITHUB_REPOSITORY','attacker/ColorPicker'),('GITHUB_WORKFLOW_SHA','b'*40),
            ('GITHUB_SHA','bad'),('TOUCHCOLOR_JOB_PLATFORM','watch'),('TOUCHCOLOR_JOB_MINUTES','45'),
            ('TOUCHCOLOR_WATCH_PROFILE','largest'),('TOUCHCOLOR_TEXT_PHASE','system-largest'),
            ('RUNNER_ARCH','X64'),('DEVELOPER_DIR','/Applications/Xcode-beta.app'),
            ('TOUCHCOLOR_MAX_EVIDENCE_BYTES','2000000'),('GITHUB_RUN_ID',''),('GITHUB_RUN_ATTEMPT','0')]
        for key,value in bad:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):binding(dict(environment(),**{key:value}))

    def test_budget_registration_preserves_every_canonical_identity(self):
        self.assertEqual({k:v for k,v in EXPECTED_MINUTES.items() if k!='watch-crown-control'},
                         dict(vision=25,watch=45,tv=25,mac=40,ios=20,paired=45))
        self.assertEqual(EXPECTED_MINUTES['watch-crown-control'],25)
        self.assertEqual(RESERVES,dict(cleanup=130,evidence=180,validation=60,upload=60,overhead=20))
        self.assertEqual(STARTUP_MARGIN,30)
        c=Clock();d=driver.Driver(environment(),clock=lambda:c.mono,wall=lambda:c.wall)
        self.assertEqual(d.budget.remaining(),1020)
        self.assertEqual(sum(PHASES.values()),1320) # Ceilings share1020s; never additive reservations.
        self.assertEqual(PHASES['setup'],450)
        wrong=copy.deepcopy(d.budget.record);wrong['platform']='watch'
        with self.assertRaises(ValueError):JobBudget(wrong,wall=lambda:c.wall,monotonic=lambda:c.mono)
        c.advance(900)
        with self.assertRaises(BudgetExhausted):d.budget.admit('unchanged RGB',180,minimum=180,cleanup=0)
        self.assertEqual(d.budget.remaining('cleanup')-d.budget.remaining(),130)

    def test_three_exact_sequential_commands_without_retry_or_gate_alias(self):
        for method in METHODS:
            command=test_command(method,'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE')
            self.assertEqual(command.count('test-without-building'),1)
            self.assertEqual([v for v in command if v.startswith('-only-testing:')],['-only-testing:'+method['target']+'/'+method['case']])
            self.assertEqual(command[command.index('-test-iterations')+1],'1')
            self.assertNotIn('-retry-tests-on-failure',command)
            self.assertEqual(command[command.index('-maximum-test-execution-time-allowance')+1],'120')
            self.assertEqual(command[command.index('-parallel-testing-enabled')+1],'NO')
        self.assertEqual([v['key'] for v in METHODS],['actual_cold','isolated_static','rgb_positive'])

    def test_source_and_original_assertions_frozen(self):
        values={'.github/workflows/apple-platforms.yml':'8c4e6fff2438d42838e718107a16db951629febd8a9cbe43e346c90e0f78e8e7',
                '.github/workflows/ios.yml':'e141cf19433d94cb78410f5d2b5e91f11523c92ddc3e9fae84743a17153f37ae',
                'TouchColorWatchUITests/WatchWorkflowTests.swift':'dea14e485da6362a72f5899e09299651699e32f7d7f95d2aed34f22e1bcd1a52'}
        for name,expected in values.items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),expected,name)

    def test_workflow_only_dedicated_push_and_bounded_upload(self):
        text=(ROOT/'.github/workflows/watch-crown-control.yml').read_text()
        self.assertIn('branches: [codex/watch-crown-diagnostic]',text)
        self.assertNotIn('workflow_dispatch:',text)
        self.assertNotIn('pull_request:',text)
        self.assertNotIn('matrix:',text)
        self.assertIn('runs-on: xcode-27',text)
        self.assertIn('timeout-minutes: 25',text)
        self.assertIn("steps.evidence_guard.outcome == 'success'",text)
        self.assertLess(text.index('Stamp original clock'),text.index('Check out exact'))
        self.assertIn('python3 scripts/watch_crown_result.py',text)


class BoundedDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        Path('build/evidence').mkdir(parents=True)
        self.clock=Clock();self.d=driver.Driver(environment(),clock=lambda:self.clock.mono,wall=lambda:self.clock.wall)
    def tearDown(self):os.chdir(self.old);self.temp.cleanup()
    def fake(self,elapsed=1,code=0,raw=b'ok',timeout=False):
        clock=self.clock
        class Process:
            pid=123456
            def __init__(self,*args,**kwargs):self.stdout=io.BytesIO(raw)
            def wait(self,timeout=None):
                clock.advance(elapsed)
                if self_timeout:raise subprocess.TimeoutExpired('fake',timeout)
                return code
        self_timeout=timeout
        return Process

    def test_whole_setup_phase_not_reset_per_command(self):
        self.d.process_factory=self.fake(50)
        with patch.object(driver,'stop_group',return_value=True):
            with self.assertRaises(ValueError),self.d.phase('setup',120):
                self.d.run(['first'],60)
                self.d.run(['second'],60)
                self.d.run(['third'],30)
        self.assertEqual(len(self.d.report['stages']),2)
        self.assertEqual(self.d.budget.record['started_monotonic'],100)
        self.assertEqual(self.d.report['phases'][0]['finished_monotonic'],200)

    def test_full_method_allowance_not_shrunk(self):
        with self.assertRaises(ValueError),self.d.phase('isolated_static',180):
            self.clock.advance(1)
            self.d.run(['xcodebuild','test-without-building'],180)
        self.assertEqual(self.d.report['stages'],[])

    def test_spawn_and_durable_write_consume_same_absolute_command_cap(self):
        clock=self.clock;observed=[]
        class SlowProcess:
            pid=123456
            def __init__(self,*args,**kwargs):
                self.stdout=io.BytesIO(b'ok');clock.advance(10)
            def wait(self,timeout=None):observed.append(timeout);clock.advance(1);return 0
        self.d.process_factory=SlowProcess
        original=self.d.persist
        def slow_persist():clock.advance(5);original()
        self.d.persist=slow_persist
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',120):
            stage,text=self.d.run(['slow-spawn'],30)
        self.assertEqual(observed,[15])
        self.assertEqual(stage['deadline_monotonic'],130)

    def test_first_transition_cannot_reset_an_existing_phase(self):
        self.d.process_factory=self.fake()
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('setup',120):
            self.d.run(['first'],5,first=True)
            with self.assertRaises(ValueError):self.d.run(['reset-not-allowed'],5,first=True)
        self.assertEqual(len(self.d.report['stages']),1)

    def test_ordinary65_preserved_cleanup_and_no_retry(self):
        self.d.process_factory=self.fake(code=65,raw=b'real failure')
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('actual_cold',240):
            stage,text=self.d.run(['xcodebuild','test-without-building'],180,required=False,first=True)
        self.assertEqual(stage['exit'],65);self.assertEqual(stage['raw_exit'],65)
        self.assertEqual(text,'real failure');self.assertTrue(stage['process_group_gone'])
        self.assertFalse(self.d.report['acceptance']);self.assertEqual(len(self.d.report['stages']),1)

    def test_timeout_retains_output_and_prevents_next_method(self):
        self.d.process_factory=self.fake(elapsed=180,raw=b'original timeout',timeout=True)
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('actual_cold',240):
            stage,text=self.d.run(['xcodebuild','test-without-building'],180,required=False,first=True)
        self.assertTrue(stage['timed_out']);self.assertIsNone(stage['raw_exit'])
        self.assertEqual(text,'original timeout')

    def test_unknown_cleanup_latches_all_commands(self):
        self.d.process_factory=self.fake()
        with patch.object(driver,'stop_group',return_value=False),patch.object(driver,'fail_record'),self.d.phase('actual_cold',240):
            stage,text=self.d.run(['xcodebuild','test-without-building'],180,required=False,first=True)
            with self.assertRaises(ValueError):self.d.run(['must-not-run'],1)
        self.assertTrue(self.d.budget.cleanup_unconfirmed)
        self.assertEqual(len(self.d.report['stages']),1)

    def test_oversized_output_is_drained_bounded_and_not_complete(self):
        self.d.process_factory=self.fake(raw=b'x'*300_000)
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('actual_cold',240):
            stage,text=self.d.run(['xcodebuild','test-without-building'],180,required=False,first=True)
        self.assertTrue(stage['stdout_truncated']);self.assertEqual(len(text),262_144)

    def test_post_cleanup_expiry_blocks_work_but_keeps_confirmed_cleanup_distinct(self):
        self.d.process_factory=self.fake(elapsed=1)
        def slow_cleanup(*args,**kwargs):self.clock.advance(4);return True
        with patch.object(driver,'stop_group',side_effect=slow_cleanup),self.d.phase('setup',120):
            stage,_=self.d.run(['slow-descendant-cleanup'],3,required=False)
            self.assertTrue(stage['timed_out']);self.assertEqual(stage['exit'],124)
            self.assertEqual(stage['raw_exit'],0);self.assertTrue(stage['process_group_gone'])
            self.assertTrue(self.d.work_stopped);self.assertFalse(self.d.budget.cleanup_unconfirmed)
            with self.assertRaises(ValueError):self.d.run(['later-operation'],3)
        self.assertEqual(len(self.d.report['stages']),1)
        with patch.object(driver,'stop_group',return_value=True),self.d.phase('cleanup',130,kind='cleanup'):
            self.d.run(['owned-cleanup-only'],3)
        self.assertEqual(len(self.d.report['stages']),2)

    def test_expired_operation_with_required_true_raises_before_continuation(self):
        self.d.process_factory=self.fake(elapsed=1)
        def slow_cleanup(*args,**kwargs):self.clock.advance(4);return True
        with patch.object(driver,'stop_group',side_effect=slow_cleanup),self.d.phase('setup',120):
            with self.assertRaises(RuntimeError):self.d.run(['expired-required-operation'],3)
            with self.assertRaises(ValueError):self.d.run(['later-operation'],3)

    def test_evidence_immutable_observations_cap(self):
        self.d.retain('home.json',b'x'*16384,'observation_home',limit=16384)
        with self.assertRaises(ValueError):self.d.retain('home.json',b'x','observation_home')
        with self.assertRaises(ValueError):self.d.retain('static.log',b'x'*16385,'observation_static',limit=16384)
        with self.assertRaises(ValueError):self.d.retain('../outside',b'x','summary')

    def test_original_clock_exhaustion_blocks_before_process(self):
        self.clock.advance(990)
        with self.assertRaises(BudgetExhausted):
            with self.d.phase('rgb_positive',180):self.fail('must not execute')
        self.assertEqual(self.d.report['stages'],[])


class SequentialMethodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        Path('build/evidence').mkdir(parents=True)
        self.clock=Clock();self.d=driver.Driver(environment(),clock=lambda:self.clock.mono,wall=lambda:self.clock.wall)
        self.d.device='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
        self.d.runners={'actual_cold':'com.mango.touchColor.TouchColorWatchUITests.xctrunner',
                        'isolated_static':'com.mango.touchColor.watchCrownControl.uitests.xctrunner'}
        self.commands=[];self.timeout=False;self.bad_cleanup=False;self.terminate_timeout=False
        def run(command,seconds,required=True,first=False):
            self.commands.append(command)
            stage={'command':command,'source_sha':'a'*40,'started':True,'raw_exit':0,'exit':0,'timed_out':False,'stdout_truncated':False,
                   'started_epoch':self.clock.wall,'started_monotonic':self.clock.mono,
                   'finished_epoch':self.clock.wall,'finished_monotonic':self.clock.mono,
                   'process_group_gone':True,'capture_reader_finished':True}
            self.d.report['stages'].append(stage)
            if command[:2]==['xcodebuild','test-without-building']:
                identifier=next(v for v in command if v.startswith('-only-testing:')).split(':',1)[1]
                target,cls,method=identifier.split('/')
                failure='RealDigitalCrown' not in method
                self.clock.advance(4)
                stage.update(exit=65 if failure else 0,raw_exit=65 if failure else 0,timed_out=self.timeout,
                             finished_epoch=self.clock.wall,finished_monotonic=self.clock.mono)
                self.active_case=(target,cls,method,stage)
                Path(command[command.index('-resultBundlePath')+1]).mkdir()
                text="Test Case '-["+target+'.'+cls+' '+method+"]' "
                return stage,text+'started.\n'+text+('failed' if failure else 'passed')+' (2.0 seconds).\n'
            if command[:3]==['xcrun','simctl','terminate'] and self.terminate_timeout:
                stage.update(exit=124,raw_exit=None,timed_out=True)
                return stage,'termination timeout'
            if 'summary' in command:
                failed='rgb_positive' not in command[-1]
                target,cls,method,test_stage=self.active_case
                counts=dict(passedTests=0 if failed else 1,failedTests=1 if failed else 0,skippedTests=0,expectedFailures=0)
                project='TouchColorWatchCrownControl' if target=='TouchColorWatchCrownControlUITests' else 'TouchColorWatch'
                failure={'targetName':target,'testIdentifierString':cls+'/'+method+'()',
                         'testIdentifierURL':'test://com.apple.xcode/'+project+'/'+target+'/'+cls+'/'+method,
                         'failureText':'Original genuine Crown assertion failure'}
                summary=dict(result='Failed' if failed else 'Passed',totalTestCount=1,**counts,
                    startTime=test_stage['started_epoch']+0.5,finishTime=test_stage['started_epoch']+3.0,
                    testFailures=[failure] if failed else [],devicesAndConfigurations=[dict(**counts,
                        device=dict(deviceId=self.d.device,platform='watchOS Simulator',osVersion='27.0',architecture='arm64'),
                        testPlanConfiguration=dict(configurationId='1',configurationName='Test Scheme Action'))])
                return stage,json.dumps(summary)

            if 'launchctl' in command:
                return stage,'PID\tStatus\tLabel\n'+('123\t0\tapplication.com.mango.touchColor.watchkitapp\n' if self.bad_cleanup else '')
            return stage,''
        self.d.run=run
    def tearDown(self):os.chdir(self.old);self.temp.cleanup()
    def test_three_calls_keep_first_two_real_failures_and_rgb_pass(self):
        for method in METHODS:self.d.method(method)
        self.assertEqual([v['observed_command_result'] for v in self.d.report['cases']],['failed','failed','passed'])
        self.assertEqual(sum(c[:2]==['xcodebuild','test-without-building'] for c in self.commands),3)
        self.assertTrue(all(v['cleanup_confirmed'] for v in self.d.report['cases']))
        self.assertFalse(self.d.report['acceptance'])
    def test_timeout_console_retained_without_extract_or_new_control(self):
        self.timeout=True
        with self.assertRaises(ValueError):self.d.method(METHODS[0])
        self.assertEqual(len(self.commands),1)
        self.assertTrue(Path('build/evidence/actual_cold-console.log').is_file())
        self.assertNotIn('observed_command_result',self.d.report['cases'][0])
    def test_live_owned_app_blocks_continuation(self):
        self.bad_cleanup=True
        with self.assertRaises(ValueError):self.d.method(METHODS[0])
        self.assertFalse(self.d.report['cases'][0]['cleanup_confirmed'])
        self.assertEqual(len(self.d.report['cases']),1)

    def test_terminate_timeout_cannot_be_cleared_by_later_empty_inventory(self):
        self.terminate_timeout=True
        with self.assertRaises(RuntimeError),patch.object(driver,'fail_record'):
            self.d.method(METHODS[0])
        self.assertTrue(self.d.budget.cleanup_unconfirmed)
        self.assertFalse(any('launchctl' in command for command in self.commands))
        self.assertEqual(sum(c[:2]==['xcodebuild','test-without-building'] for c in self.commands),1)
        self.assertFalse(self.d.report['cases'][0]['cleanup_confirmed'])

    def test_contradictory_summary_is_rejected_before_any_next_control(self):
        mutations=[
            lambda v:v.update(result='Passed',passedTests=1,failedTests=0),
            lambda v:v['devicesAndConfigurations'][0]['device'].update(deviceId='not-the-owned-watch'),
            lambda v:v['devicesAndConfigurations'][0]['device'].update(osVersion='26.0'),
            lambda v:v['devicesAndConfigurations'][0]['device'].update(platform='iOS Simulator'),
            lambda v:v['devicesAndConfigurations'][0]['device'].update(architecture='x86_64'),
            lambda v:v.update(startTime=1,finishTime=2),
            lambda v:v.update(finishTime=1000000),
            lambda v:v['testFailures'][0].update(testIdentifierString='Other/testCase()'),
            lambda v:v['devicesAndConfigurations'][0].update(failedTests=0,passedTests=1),
            lambda v:v['devicesAndConfigurations'][0]['testPlanConfiguration'].update(configurationId='other'),
            lambda v:v.update(failedTests=True),
            lambda v:v.update(testFailures=[]),
        ]
        for i,mutation in enumerate(mutations):
            with self.subTest(mutation=i):
                t=SequentialMethodTests();t.setUp()
                try:
                    original=t.d.run
                    def corrupt(command,*args,**kwargs):
                        stage,text=original(command,*args,**kwargs)
                        if 'summary' in command:
                            value=json.loads(text);mutation(value);return stage,json.dumps(value)
                        return stage,text
                    t.d.run=corrupt
                    with self.assertRaises(ValueError):
                        t.d.method(METHODS[0]);t.d.method(METHODS[1])
                    self.assertEqual(sum(c[:2]==['xcodebuild','test-without-building'] for c in t.commands),1)
                    self.assertTrue(Path('build/evidence/actual_cold-summary.json').is_file())
                    self.assertEqual(t.d.report['stages'][0]['raw_exit'],65)
                    self.assertFalse(t.d.report['acceptance'])
                finally:t.tearDown()

    def test_lifecycle_and_source_must_match_summary_before_continuation(self):
        for mismatch in ('lifecycle','source','command'):
            with self.subTest(mismatch=mismatch):
                t=SequentialMethodTests();t.setUp()
                try:
                    original=t.d.run
                    def corrupt(command,*args,**kwargs):
                        stage,text=original(command,*args,**kwargs)
                        if command[:2]==['xcodebuild','test-without-building']:
                            if mismatch=='lifecycle':text=text.replace('failed (','passed (')
                            if mismatch=='source':stage['source_sha']='b'*40
                            if mismatch=='command':stage['command']=command+['-retry-tests-on-failure']
                        return stage,text
                    t.d.run=corrupt
                    with self.assertRaises(ValueError):
                        t.d.method(METHODS[0]);t.d.method(METHODS[1])
                    self.assertEqual(sum(c[:2]==['xcodebuild','test-without-building'] for c in t.commands),1)
                finally:t.tearDown()

if __name__=='__main__':unittest.main()
