"""Portable orchestration/identity tests; no Apple execution or historical pass claim."""
import ast
import datetime
import time
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import native_content_size as sizes
import vision_offline_result as offline
from simulator_content_size import LARGEST

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
DEVICE = 'E1B606CC-01C6-43A2-874B-F97EC6C3022B'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.xrOS-27-0'
CASE = 'testOfficialAccessibilityEmptyAndPastedCanvas'


def fixture(root):
    root = Path(root)
    (root/'build/vision-runtime').mkdir(parents=True)
    bundle = root/offline.BUNDLE; bundle.mkdir(parents=True)
    (bundle/'Info.plist').write_bytes(b'portable fixture only')
    (bundle/'Data').mkdir(); (bundle/'Data/result').write_bytes(b'fixture result bytes')
    contract = {'root': str(root), 'project': 'TouchColorVision.xcodeproj', 'scheme': 'TouchColorVision',
                'derived_data': 'build/vision-tests', 'test_bundle': 'TouchColorVisionUITests', 'platform': 'visionOS Simulator'}
    command = ['xcodebuild', 'test-without-building', '-resultBundlePath', offline.BUNDLE, '-destination',
               'platform=visionOS Simulator,id=' + DEVICE, '-only-testing:TouchColorVisionUITests/VisionWorkflowTests/' + CASE]
    report = {'device': DEVICE, 'runtime': RUNTIME, 'status': 'largest_ui_passed', 'restore_verified': True,
              'ui_executed': True, 'ui_exit': 0, 'observed_largest': LARGEST, 'operations': []}
    offline.prepare(report, command, contract, [CASE], SHA, DEVICE, 100., 300.)
    report['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
    counts = {'passedTests': 1, 'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}
    summary = dict(counts, result='Passed', totalTestCount=1, startTime=150., finishTime=200., testFailures=[],
                   devicesAndConfigurations=[dict(counts, device={'deviceId': DEVICE, 'platform': 'visionOS Simulator', 'osVersion': '27.0', 'architecture': 'arm64'},
                                                   testPlanConfiguration={'configurationId': '1', 'configurationName': 'Test Scheme Action'})])
    shutdown = {'command': ['xcrun', 'simctl', 'shutdown', DEVICE], 'exit': 0,
                'process_group_gone': True, 'capture_reader_finished': True, 'reader_errors': [], 'cleanup_error': None}
    return report, summary, shutdown, command, contract


def hosted_fixture(root, summary, shutdown):
    root=Path(root); bundle=root/offline.HOSTED_BUNDLE;bundle.mkdir(parents=True,exist_ok=True)
    (bundle/'Info.plist').write_bytes(b'portable hosted result')
    command=['xcodebuild','test-without-building','-project','TouchColorVision.xcodeproj','-scheme','TouchColorVision',
             '-derivedDataPath','build/vision-tests','-resultBundlePath',offline.HOSTED_BUNDLE,'-destination',
             'platform=visionOS Simulator,id='+DEVICE,'-only-testing:TouchColorVisionTests']
    stage=dict(shutdown,command=command,started_at=datetime.datetime.fromtimestamp(10,datetime.timezone.utc).isoformat(),
               finished_at=datetime.datetime.fromtimestamp(90,datetime.timezone.utc).isoformat())
    report=offline.prepare_hosted(command,root,SHA,DEVICE,RUNTIME,stage)
    report['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
    hosted=copy.deepcopy(summary);hosted.update(passedTests=offline.HOSTED_COUNT,totalTestCount=offline.HOSTED_COUNT,startTime=30.,finishTime=70.)
    hosted['devicesAndConfigurations'][0]['passedTests']=offline.HOSTED_COUNT
    return report,hosted


class Reader:
    def __init__(self, *, state='Shutdown', sha=SHA, events=None):
        self.cleanup_unconfirmed = False; self.calls = []; self.state = state; self.sha = sha; self.events = events
    def __call__(self, command, seconds, **kwargs):
        self.calls.append((command, seconds))
        if self.events is not None: self.events.append('readback' if command[0] == 'xcrun' else 'source')
        if command[:3] == ['xcrun', 'simctl', 'list']:
            text = json.dumps({'devices': {RUNTIME: [{'udid': DEVICE, 'state': self.state, 'isAvailable': True}]}})
        elif command[-2:] == ['rev-parse', 'HEAD']: text = self.sha + '\n'
        elif 'diff' in command: text = ''
        else: raise AssertionError('Unexpected offline command: ' + str(command))
        return 0, text, {'command': command, 'timeout_seconds': seconds, 'cleanup_confirmed': True, 'exit': 0, 'state': 'completed'}


class VisionOfflineTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': '', 'GITHUB_SHA': '', 'TOUCHCOLOR_JOB_PLATFORM':'', 'TOUCHCOLOR_VISION_CASE':''})
        env.start(); self.addCleanup(env.stop)

    def qualify(self, folder, report, summary, shutdown, **kwargs):
        reader = kwargs.pop('runner', Reader())
        raw = json.dumps(summary, indent=2).encode() + b'\n'
        summary_runner = kwargs.pop('summary_runner', Mock(return_value=subprocess.CompletedProcess([], 0, raw, b'')))
        role=kwargs.get('role','largest')
        result = offline.qualify(report, Path(folder)/('build/vision-runtime/'+role+'-offline-result.json'), shutdown,
            sha=kwargs.pop('sha', SHA), device=kwargs.pop('device', DEVICE), runtime=kwargs.pop('runtime', RUNTIME), runner=reader,
            summary_path=Path(folder)/('build/vision-runtime/'+role+'-summary.json'), summary_runner=summary_runner, **kwargs)
        return result, reader, summary_runner

    def test_pending_is_not_pass_and_single_summary_runs_after_shutdown_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            self.assertFalse(sizes.qualified(report)); self.assertTrue(offline.pending(report))
            result, reader, command = self.qualify(folder, report, summary, shutdown)
            self.assertTrue(sizes.qualified(result)); self.assertEqual(reader.calls[0][0][:3], ['xcrun', 'simctl', 'list'])
            command.assert_called_once(); self.assertEqual(command.call_args.kwargs, {'timeout': 30, 'text': False})
            self.assertTrue(result['deferred_result']['attempted'])

    def test_exact_raw_summary_bytes_are_cached_without_reencoding(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            raw = json.dumps(summary, separators=(',', ':')).encode() + b'\r\n'
            command = Mock(return_value=subprocess.CompletedProcess([], 0, raw, b''))
            result, _, _ = self.qualify(folder, report, summary, shutdown, summary_runner=command)
            self.assertTrue(sizes.qualified(result))
            self.assertEqual((Path(folder)/'build/vision-runtime/largest-summary.json').read_bytes(), raw)
            self.assertEqual(result['summary_sha256'], hashlib.sha256(raw).hexdigest())

    def test_summary_diagnostics_fail_but_raw_stdout_and_error_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _=fixture(folder)
            raw=json.dumps(summary).encode()+b'\n'
            result,_,_=self.qualify(folder,report,summary,shutdown,summary_runner=Mock(return_value=subprocess.CompletedProcess([],0,raw,b'original diagnostic')))
            self.assertFalse(sizes.qualified(result));self.assertEqual(result['summary_stderr'],'original diagnostic')
            self.assertEqual((Path(folder)/'build/vision-runtime/largest-summary.json').read_bytes(),raw)

    def test_failed_or_unknown_shutdown_never_starts_any_offline_command(self):
        for change in ({'exit': 1}, {'exit': 124}, {'process_group_gone': False}, {'capture_reader_finished': False},
                       {'reader_errors': ['Error']}, {'command': ['shutdown', 'OTHER']}, {'started': False}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                report, summary, shutdown, _, _ = fixture(folder); shutdown.update(change)
                result, reader, command = self.qualify(folder, report, summary, shutdown)
                self.assertFalse(sizes.qualified(result)); self.assertEqual(reader.calls, []); command.assert_not_called()

    def test_existing_unknown_cleanup_permits_no_command(self):
        for which in ('parent', 'runner'):
            with tempfile.TemporaryDirectory() as folder:
                report, summary, shutdown, _, _ = fixture(folder); reader = Reader()
                if which == 'runner': reader.cleanup_unconfirmed = True
                result, reader, command = self.qualify(folder, report, summary, shutdown, runner=reader, cleanup_unconfirmed=which == 'parent')
                self.assertTrue(result['cleanup_unconfirmed']); self.assertFalse(reader.calls); command.assert_not_called()

    def test_missing_driver_shutdown_readback_is_not_retried_in_evidence_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            report.pop('offline_shutdown_verified')
            result, reader, command = self.qualify(folder, report, summary, shutdown)
            self.assertFalse(sizes.qualified(result)); self.assertFalse(reader.calls); command.assert_not_called()

    def test_device_must_read_back_exact_shutdown_before_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            result, reader, command = self.qualify(folder, report, summary, shutdown, runner=Reader(state='Booted'))
            self.assertFalse(sizes.qualified(result)); self.assertEqual(len(reader.calls), 1); command.assert_not_called()

    def test_changed_source_device_runtime_or_result_are_rejected_before_summary(self):
        for change in ('sha', 'device', 'runtime', 'head', 'bytes', 'directory'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                report, summary, shutdown, _, _ = fixture(folder); kwargs = {}
                if change == 'sha': kwargs['sha'] = 'b' * 40
                elif change == 'device': kwargs['device'] = 'OTHER'
                elif change == 'runtime': kwargs['runtime'] = 'other'
                elif change == 'head': kwargs['runner'] = Reader(sha='b' * 40)
                elif change == 'bytes': (Path(folder)/offline.BUNDLE/'Data/result').write_bytes(b'changed')
                else:
                    bundle = Path(folder)/offline.BUNDLE; renamed = bundle.with_name('old.xcresult'); bundle.rename(renamed)
                    import shutil; shutil.copytree(renamed, bundle)
                result, _, command = self.qualify(folder, report, summary, shutdown, **kwargs)
                self.assertFalse(sizes.qualified(result)); command.assert_not_called()

    def test_result_moved_behind_symlink_cannot_reuse_original_inode_and_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report,summary,shutdown,_,_=fixture(root)
            bundle=root/offline.BUNDLE; relocated=root/'moved.xcresult';bundle.rename(relocated);bundle.symlink_to(relocated,target_is_directory=True)
            result,_,command=self.qualify(root,report,summary,shutdown)
            self.assertFalse(sizes.qualified(result));command.assert_not_called()

    def test_missing_stale_noninteger_wrong_device_and_contradictory_result_fail(self):
        mutations = [lambda x: x.pop('totalTestCount'), lambda x: x.update(passedTests=True),
                     lambda x: x.update(startTime=1), lambda x: x.update(finishTime=float('nan')),
                     lambda x: x.update(failedTests=1), lambda x: x.update(skippedTests=1),
                     lambda x: x.update(testFailures=[{'failureText': 'retained error'}]),
                     lambda x: x['devicesAndConfigurations'][0]['device'].update(deviceId='OTHER'),
                     lambda x: x['devicesAndConfigurations'][0]['testPlanConfiguration'].update(configurationId='2')]
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as folder:
                report, summary, shutdown, _, _ = fixture(folder); mutate(summary)
                result, _, command = self.qualify(folder, report, summary, shutdown)
                self.assertFalse(sizes.qualified(result)); command.assert_called_once()

    def test_summary_timeout_is_not_retried_even_with_confirmed_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            error = subprocess.TimeoutExpired(['xcresulttool'], 30); error.cleanup_confirmed = True
            command = Mock(side_effect=error)
            result, reader, _ = self.qualify(folder, report, summary, shutdown, summary_runner=command)
            self.assertEqual(result['summary_operation']['state'], 'timeout'); self.assertFalse(reader.cleanup_unconfirmed)
            self.qualify(folder, report, summary, shutdown, summary_runner=command)
            command.assert_called_once()

    def test_unknown_summary_cleanup_latches_and_blocks_later_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            error = subprocess.TimeoutExpired(['xcresulttool'], 30); error.cleanup_confirmed = False
            result, reader, command = self.qualify(folder, report, summary, shutdown, summary_runner=Mock(side_effect=error))
            self.assertTrue(result['cleanup_unconfirmed']); self.assertTrue(reader.cleanup_unconfirmed)
            before = len(reader.calls); self.qualify(folder, report, summary, shutdown, runner=reader, summary_runner=command)
            self.assertEqual(len(reader.calls), before); command.assert_called_once()

    def test_result_changed_during_summary_cannot_be_qualified(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder)
            def extract(*args, **kwargs):
                (Path(folder)/offline.BUNDLE/'Data/result').write_bytes(b'replaced during extraction')
                return subprocess.CompletedProcess([], 0, json.dumps(summary).encode(), b'')
            result, _, _ = self.qualify(folder, report, summary, shutdown, summary_runner=extract)
            self.assertFalse(sizes.qualified(result))

    def test_attempt_is_persisted_before_any_offline_command(self):
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _ = fixture(folder); seen = []
            def persist(): seen.append(report['deferred_result']['attempted'])
            reader = Reader()
            self.qualify(folder, report, summary, shutdown, runner=reader, persist=persist)
            self.assertEqual(seen, [True]); self.assertTrue(reader.calls)

    def test_work_helper_defers_only_vision_and_does_not_extract(self):
        with tempfile.TemporaryDirectory() as folder:
            report, _, _, command, contract = fixture(folder)
            executed = {k:v for k,v in report.items() if k!='deferred_result'}; executed['status']='largest_ui_passed'
            runner = Mock(); runner.cleanup_unconfirmed = False
            with patch.object(sizes, 'probe', return_value=executed), patch.object(sizes.time, 'time', side_effect=[100., 300.]):
                result = sizes.run_largest(DEVICE, Path(folder)/'build/vision-runtime/largest-text.json', command, contract, [CASE], runner,
                                          defer_vision_summary=True, source_sha=SHA)
            runner.assert_not_called(); self.assertTrue(offline.pending(result)); self.assertFalse(sizes.qualified(result))
            with self.assertRaises(ValueError):
                sizes.run_largest(DEVICE, Path(folder)/'unused', command, dict(contract, platform='watchOS Simulator'), [CASE], runner,
                                  defer_vision_summary=True, source_sha=SHA)

    def test_original_runtime_error_is_never_cleared_by_later_valid_result(self):
        for original in ('pending_offline_qualification', 'failed'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); report, summary, shutdown, _, _ = fixture(root)
                hosted, hosted_summary=hosted_fixture(root,summary,shutdown)
                runtime = {'sha': SHA, 'device': {'udid': DEVICE}, 'runtime': RUNTIME, 'result': original,
                           'largest_system_text': report, 'vision_hosted_result':hosted, 'vision_offline_shutdown': shutdown}
                if original == 'failed': runtime['error'] = 'Original independent live-phase failure'
                path=root/'build/vision-runtime/runtime.json';path.write_text(json.dumps(runtime))
                def qualify(setting, report_path, stage, **kwargs):
                    setting['deferred_result']['attempted']=True;role=kwargs['role'];setting['status']='hosted_result_passed' if role=='hosted' else 'largest_ui_passed'
                    setting['verified_results']=offline.verify_offline_summary(hosted_summary if role=='hosted' else summary, setting['deferred_result'], DEVICE, role)
                with patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE':'evidence'}), patch.object(offline, 'qualify', side_effect=qualify):
                    offline.qualify_for_evidence(root)
                result=json.loads(path.read_bytes())
                self.assertEqual(result['result'], 'passed' if original=='pending_offline_qualification' else 'failed')
                if original=='failed': self.assertEqual(result['error'], runtime['error'])

    def test_qualification_cannot_run_in_cleanup_or_work_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); report, _, shutdown, _, _=fixture(root)
            (root/'build/vision-runtime/runtime.json').write_text(json.dumps({'largest_system_text': report}))
            for phase in ('work','cleanup'):
                with patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE':phase}), patch.object(offline, 'qualify') as qualify:
                    with self.assertRaises(ValueError): offline.qualify_for_evidence(root)
                    qualify.assert_not_called()

    def test_insufficient_evidence_budget_starts_no_summary_and_preserves_tail(self):
        from job_budget import JobBudget, create_record
        from test_job_budget import Clock
        clock=Clock(); record=create_record({'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_JOB_MINUTES':'25',
            'TOUCHCOLOR_JOB_STARTED_EPOCH':str(clock.wall),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(clock.mono),
            'GITHUB_SHA':SHA,'GITHUB_RUN_ID':'1'}, wall=lambda:clock.wall, monotonic=lambda:clock.mono)
        budget=JobBudget(record, wall=lambda:clock.wall, monotonic=lambda:clock.mono);budget.phase='evidence'
        with tempfile.TemporaryDirectory() as folder:
            report, summary, shutdown, _, _=fixture(folder)
            clock.advance(budget.remaining('evidence')-15)
            before=budget.remaining('upload')
            with patch.object(offline, 'enabled_budget', return_value=budget), patch('job_budget.enabled_budget', return_value=budget), patch('job_budget.fail_record'), patch('subprocess.Popen') as launch:
                result, _, _=self.qualify(folder, report, summary, shutdown, summary_runner=offline.run_captured)
            launch.assert_not_called();self.assertFalse(sizes.qualified(result))
            self.assertEqual(result['summary_operation']['state'],'not_started_budget')
            self.assertEqual(budget.remaining('upload'),before)
            self.assertEqual(budget.events[-1]['phase'],'evidence')

    def driver_tail(self, folder, *, shutdown_exit=0, unknown=False, case='canvas-audit'):
        from watch_failure_continuation import record_failure, require_no_failures
        root=Path(folder); setting, summary, stage, _, _=fixture(root); events=[]
        hosted,_=hosted_fixture(root,summary,stage)
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text()); outer=next(x for x in source.body if isinstance(x,ast.Try))
        index=next(i for i,node in enumerate(outer.body) if isinstance(node,ast.Assign) and ast.unparse(node.targets[0])=="report['tests']")
        body=copy.deepcopy(outer.body[index:]); body.insert(-1,ast.parse('later_live_phase()').body[0])
        code=ast.Module(body=[ast.Try(body=body,handlers=outer.handlers,orelse=[],finalbody=outer.finalbody),source.body[-1]],type_ignores=[]);ast.fix_missing_locations(code)
        report={'sha':SHA,'stages':[],'vision_hosted_result':hosted};reader=Reader(events=events)
        def run(command,timeout,required=True):
            events.append('shutdown'); row=copy.deepcopy(stage);row['exit']=shutdown_exit;report['stages'].append(row)
            if unknown: report['cleanup_unconfirmed']=True
            return shutdown_exit
        def largest(*args,**kwargs):
            self.assertTrue(kwargs['defer_vision_summary']); events.append('largest live execution and restoration');return setting
        env=dict(kind='vision',report=report,device={'udid':DEVICE},runtime=RUNTIME,owned_watch_devices=[],pending_vision_result=None,pending_vision_hosted=hosted,
            test_common=['xcodebuild'],test_arguments=[],name='TouchColorVision',project='TouchColorVision.xcodeproj',platform='visionOS',
            Path=Path,os=os,json=json,subprocess=subprocess,photo_seed_failed=False,out=root/'build/vision-runtime',
            applicable_cases=lambda *args:(CASE,) if case=='canvas-audit' else (),TouchSizeRunner=lambda callback:reader,run_largest=largest,qualified=sizes.qualified,
            vision_summary_pending=offline.pending,confirm_vision_shutdown=offline.confirm_shutdown,run=run,
            record_failure=record_failure,require_no_failures=require_no_failures,
            resources=lambda label:events.append('live resources'),later_live_phase=lambda:events.append('later live phase'),
            fail_record=Mock(),print=lambda *args,**kwargs:None)
        with contextlib.chdir(root),patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE':''}):
            if shutdown_exit or unknown:
                with self.assertRaises(SystemExit):exec(compile(code,'actual-driver-tail','exec'),env)
            else:exec(compile(code,'actual-driver-tail','exec'),env)
        self.assertNotIn('largest_text_outcome', report) # Watch bookkeeping must not pre-qualify Vision.
        return report,events

    def test_real_driver_tail_finishes_all_live_phases_before_shutdown_and_never_extracts(self):
        with tempfile.TemporaryDirectory() as folder:
            report,events=self.driver_tail(folder)
            self.assertEqual(events,['largest live execution and restoration','later live phase','live resources','shutdown','readback'])
            self.assertEqual(report['result'],'pending_offline_qualification')
            self.assertFalse(sizes.qualified(report['largest_system_text']))

    def test_real_json_driver_defers_hosted_without_introducing_largest_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            report,events=self.driver_tail(folder,case='json')
            self.assertEqual(events,['later live phase','live resources','shutdown','readback'])
            self.assertEqual(report['result'],'pending_offline_qualification')
            self.assertNotIn('largest_system_text',report)
            self.assertEqual(report['vision_hosted_result']['offline_shutdown_verified']['state'],'Shutdown')

    def test_real_driver_failed_shutdown_or_unknown_cleanup_has_no_readback_or_summary(self):
        for unknown in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                report,events=self.driver_tail(folder,shutdown_exit=1 if not unknown else 0,unknown=unknown)
                self.assertNotIn('readback',events);self.assertEqual(report['result'],'failed')

    def test_exported_summary_is_verified_and_missing_or_mutated_bytes_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); report, summary, shutdown, _, _=fixture(root)
            hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
            self.qualify(root,report,summary,shutdown);self.qualify(root,hosted,hosted_summary,shutdown,role='hosted')
            runtime={'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'passed','largest_system_text':report,
                     'vision_hosted_result':hosted,'vision_offline_shutdown':shutdown,
                     'vision_offline_qualification':{'result':'passed','roles':{'hosted':True,'largest':True},'attempted':{'hosted':True,'largest':True}}}
            (root/'build/vision-runtime/runtime.json').write_text(json.dumps(runtime))
            evidence=root/'build/evidence';evidence.mkdir()
            offline.copy_cached_summary(root);offline.copy_cached_summary(root,role='hosted')
            (evidence/'vision-runtime.json').write_text(json.dumps(runtime))
            self.assertTrue(offline.evidence_complete(evidence))
            (evidence/'vision-largest-text-summary.json').write_bytes(b'changed')
            with self.assertRaises(ValueError):offline.evidence_complete(evidence)
            (evidence/'vision-largest-text-summary.json').unlink()
            with self.assertRaises((ValueError,FileNotFoundError)):offline.evidence_complete(evidence)

    def test_missing_expected_vision_report_cannot_claim_completion(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_VISION_CASE':'canvas-audit'}):
            self.assertFalse(offline.evidence_complete(folder))
            (Path(folder)/'vision-runtime.json').write_text('{}')
            self.assertFalse(offline.evidence_complete(folder))

    def successful_fallback(self, root):
        import job_budget
        root=Path(root);report,summary,shutdown,_,_=fixture(root)
        hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
        self.qualify(root,report,summary,shutdown);self.qualify(root,hosted,hosted_summary,shutdown,role='hosted')
        runtime={'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'passed','largest_system_text':report,
                 'vision_hosted_result':hosted,'vision_offline_shutdown':shutdown,'vision_offline_case':'canvas-audit',
                 'vision_offline_expected':['hosted','largest'],
                 'vision_offline_qualification':{'result':'passed','roles':{'hosted':True,'largest':True},'attempted':{'hosted':True,'largest':True}}}
        runtime_path=root/'build/vision-runtime/runtime.json';runtime_path.write_text(json.dumps(runtime))
        evidence=root/'build/evidence';evidence.mkdir()
        offline.copy_cached_summary(root);offline.copy_cached_summary(root,role='hosted')
        (evidence/'vision-runtime.json').write_bytes(runtime_path.read_bytes())
        self.assertTrue(offline.evidence_complete(evidence))
        environment={**os.environ,'GITHUB_SHA':SHA,'GITHUB_RUN_ID':'1','TOUCHCOLOR_JOB_PLATFORM':'vision',
            'TOUCHCOLOR_VISION_CASE':'canvas-audit','TOUCHCOLOR_JOB_MINUTES':'25','TOUCHCOLOR_EVIDENCE_LIMIT':'650000',
            'TOUCHCOLOR_JOB_STARTED_EPOCH':str(time.time()),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(time.monotonic()),
            'GITHUB_OUTPUT':str(root/'outputs.txt'),'TOUCHCOLOR_BUDGET_PHASE':'evidence'}
        with contextlib.chdir(root),patch.dict(os.environ,environment):
            job_budget.STATE.write_text(json.dumps(job_budget.create_record()))
            job_budget.fail_record('Late attachment exporter timed out',phase='evidence')
            job_budget.retain_metadata(fallback_reason='Evidence phase failed or exceeded its reserved deadline')
        self.assertEqual({p.name for p in evidence.iterdir()},{'job-budget.json','vision-runtime.json'})
        return evidence,environment

    def test_actual_qualifier_then_controller_fallback_remains_uploadable_but_false(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence,environment=self.successful_fallback(folder)
            result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'650000'],
                                  env=environment,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output=(Path(folder)/'outputs.txt').read_text()
            self.assertEqual(output,'vision_offline_qualified=false\n')
            gate=subprocess.run(['bash','-c',"test 'false' = 'true'"])
            self.assertNotEqual(gate.returncode,0)
            retained=json.loads((evidence/'vision-runtime.json').read_bytes())
            self.assertEqual(retained['result'],'passed') # Historical extraction, never final artifact qualification.
            self.assertTrue((Path(folder)/'build/evidence-incomplete/vision-summary.json').is_file())
            self.assertTrue((Path(folder)/'build/evidence-incomplete/vision-largest-text-summary.json').is_file())

    def test_tampered_or_missing_fallback_provenance_fails_actual_validator(self):
        for change in ('missing_budget','missing_marker','source','run','hash','bytes','duplicate','runtime','phase','no_phase','wrong_phase','wrong_result','extra_file'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                evidence,environment=self.successful_fallback(folder);path=evidence/'job-budget.json';value=json.loads(path.read_bytes())
                if change=='missing_budget':path.unlink()
                elif change=='runtime':(evidence/'vision-runtime.json').write_bytes((evidence/'vision-runtime.json').read_bytes()+b'\n')
                elif change=='extra_file':(evidence/'architecture.txt').write_text('Not an exact metadata-only fallback')
                else:
                    if change=='missing_marker':value.pop('unpublished_partial_evidence')
                    elif change=='source':value['sha']='b'*40
                    elif change=='run':value['run_id']='other'
                    elif change=='hash':value['runtime_retention'][0]['sha256']='0'*64
                    elif change=='bytes':value['runtime_retention'][0]['bytes']+=1
                    elif change=='duplicate':value['runtime_retention'].append(copy.deepcopy(value['runtime_retention'][0]))
                    elif change=='phase':value['phase_failures']['evidence']['sha']='b'*40
                    elif change=='no_phase':
                        value['phase_failures']={};value.pop('failure',None);value.pop('cleanup_failure',None)
                    elif change=='wrong_phase':value['phase_failures']['evidence']['phase']='work'
                    elif change=='wrong_result':value['phase_failures']['evidence']['result']='passed'
                    path.write_text(json.dumps(value))
                result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'650000'],
                                      env=environment,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,change)
                output=Path(folder)/'outputs.txt'
                self.assertFalse(output.exists() and '=true' in output.read_text())

    def test_all_vision_rows_require_hosted_and_only_existing_two_require_largest(self):
        from vision_suites import CASES
        for case in CASES:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);largest,summary,shutdown,_,_=fixture(root);hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
                roles=['hosted']+(['largest'] if case in ('chinese','canvas-audit') else [])
                runtime={'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'pending_offline_qualification',
                         'vision_hosted_result':hosted,'vision_offline_shutdown':shutdown,'vision_offline_case':case,'vision_offline_expected':roles}
                if 'largest' in roles:
                    largest['deferred_result']['cases']=[CASES[case][0]]
                    largest['deferred_result']['command'][-1]='-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+CASES[case][0]
                    runtime['largest_system_text']=largest
                path=root/'build/vision-runtime/runtime.json';path.write_text(json.dumps(runtime));seen=[]
                def qualify(setting,report_path,stage,**kwargs):
                    role=kwargs['role'];seen.append(role);setting['deferred_result']['attempted']=True
                    setting['status']='hosted_result_passed' if role=='hosted' else 'largest_ui_passed'
                    setting['verified_results']=offline.verify_offline_summary(hosted_summary if role=='hosted' else summary,setting['deferred_result'],DEVICE,role)
                with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence'}),patch.object(offline,'qualify',side_effect=qualify):
                    offline.qualify_for_evidence(root);offline.qualify_for_evidence(root)
                self.assertEqual(seen,roles) # No extraction retry on a repeated handoff.
                self.assertEqual(json.loads(path.read_bytes())['result'],'passed')

    def test_wrong_saved_lane_cannot_omit_current_rows_largest_result(self):
        for case in ('chinese','canvas-audit'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);_,summary,shutdown,_,_=fixture(root);hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
                runtime={'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'pending_offline_qualification',
                         'vision_hosted_result':hosted,'vision_offline_shutdown':shutdown,'vision_offline_case':'json-export',
                         'vision_offline_expected':['hosted']}
                path=root/'build/vision-runtime/runtime.json';path.write_text(json.dumps(runtime))
                environment={**os.environ,'GITHUB_SHA':SHA,'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_VISION_CASE':case,
                             'TOUCHCOLOR_BUDGET_PHASE':'evidence','GITHUB_OUTPUT':str(root/'outputs.txt')}
                with patch.dict(os.environ,environment),patch.object(offline,'qualify') as command:
                    with self.assertRaisesRegex(ValueError,'current row'):offline.qualify_for_evidence(root)
                    command.assert_not_called()
                self.qualify(root,hosted,hosted_summary,shutdown,role='hosted')
                runtime['result']='passed';runtime['vision_offline_qualification']={'result':'passed','roles':{'hosted':True},'attempted':{'hosted':True}}
                path.write_text(json.dumps(runtime));evidence=root/'build/evidence';evidence.mkdir();offline.copy_cached_summary(root,role='hosted')
                (evidence/'vision-runtime.json').write_bytes(path.read_bytes())
                result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'650000'],env=environment,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0);self.assertFalse((root/'outputs.txt').exists())

    def test_hosted_query_keeps_30s_cap_and_requires_exact42_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            _,summary,shutdown,_,_=fixture(folder);hosted,hosted_summary=hosted_fixture(folder,summary,shutdown)
            result,_,command=self.qualify(folder,hosted,hosted_summary,shutdown,role='hosted')
            self.assertTrue(offline.hosted_qualified(result));self.assertEqual(command.call_args.kwargs,{'timeout':30,'text':False})
            self.assertTrue(command.call_args.args[0][-1].endswith(offline.HOSTED_BUNDLE))
            hosted_summary['passedTests']=41
            with self.assertRaises((ValueError,RuntimeError)):offline.verify_offline_summary(hosted_summary,hosted['deferred_result'],DEVICE,'hosted')
            files=list((ROOT/'TouchColorVisionTests').rglob('*.swift'))+list((ROOT/'Packages/ColorCore/Tests').rglob('*.swift'))
            self.assertEqual(sum(len(__import__('re').findall(r'func test\w+\(',p.read_text())) for p in files),offline.HOSTED_COUNT)

    def test_directory_and_final_identity_deadlines_are_enforced(self):
        for empty in (True,False):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);fixture(root);bundle=root/offline.BUNDLE;now=[0.]
                def walk(*args,**kwargs):
                    yield str(bundle),[],['Info.plist']
                    now[0]=1000.
                    if empty:yield str(bundle/'empty'),[],[]
                with patch.object(offline.os,'walk',side_effect=walk):
                    with self.assertRaises(ValueError):offline.bundle_identity(root,clock=lambda:now[0])

    def test_source_budgets_and_cached_export_order_remain_explicit(self):
        workflow=(ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.assertIn("--seconds 180 --phase evidence",workflow)
        self.assertLess(workflow.index('vision_offline_result.py qualify'),workflow.index('for platform in vision watch;'))
        branch=workflow.split('for platform in vision watch;',1)[1].split('done',1)[0]
        self.assertIn('TOUCHCOLOR_VISION_CASE:-',branch);self.assertIn('vision_offline_result.py copy-summary',branch)
        self.assertIn('vision_offline_result.py copy-hosted-summary',workflow)
        self.assertIn('else\n                python3 scripts/budget_command.py --seconds 20',branch)
        self.assertIn("run: test '${{ steps.evidence_guard.outputs.vision_offline_qualified }}' = 'true'",workflow)
        self.assertLess(workflow.index('Retain small test evidence for review'),workflow.index('Require every deferred Vision result qualification'))


if __name__=='__main__':unittest.main()
