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
from native_text_rows import row as text_row, vision_roles
from simulator_content_size import LARGEST

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
DEVICE = 'E1B606CC-01C6-43A2-874B-F97EC6C3022B'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.xrOS-27-0'
CASE = 'testOfficialAccessibilityEmptyAndPastedCanvas'
ROW = text_row('vision', 'system-largest', 'canvas-audit', '', SHA)


# Test roots mirror Path.cwd() in the live driver, including macOS /var aliases.
def fixture(root):
    root = Path(root).resolve()
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
    offline.prepare(report, command, contract, [CASE], SHA, DEVICE, 100., 300., row_binding=ROW)
    report['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
    counts = {'passedTests': 1, 'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}
    summary = dict(counts, result='Passed', totalTestCount=1, startTime=150., finishTime=200., testFailures=[],
                   devicesAndConfigurations=[dict(counts, device={'deviceId': DEVICE, 'platform': 'visionOS Simulator', 'osVersion': '27.0', 'architecture': 'arm64'},
                                                   testPlanConfiguration={'configurationId': '1', 'configurationName': 'Test Scheme Action'})])
    shutdown = {'command': ['xcrun', 'simctl', 'shutdown', DEVICE], 'exit': 0,
                'process_group_gone': True, 'capture_reader_finished': True, 'reader_errors': [], 'cleanup_error': None}
    return report, summary, shutdown, command, contract


def hosted_fixture(root, summary, shutdown, row_binding=ROW):
    root=Path(root).resolve(); bundle=root/offline.HOSTED_BUNDLE;bundle.mkdir(parents=True,exist_ok=True)
    (bundle/'Info.plist').write_bytes(b'portable hosted result')
    command=['xcodebuild','test-without-building','-project','TouchColorVision.xcodeproj','-scheme','TouchColorVision',
             '-derivedDataPath','build/vision-tests','-resultBundlePath',offline.HOSTED_BUNDLE,'-destination',
             'platform=visionOS Simulator,id='+DEVICE,'-only-testing:TouchColorVisionTests']
    stage=dict(shutdown,command=command,started_at=datetime.datetime.fromtimestamp(10,datetime.timezone.utc).isoformat(),
               finished_at=datetime.datetime.fromtimestamp(90,datetime.timezone.utc).isoformat())
    report=offline.prepare_hosted(command,root,SHA,DEVICE,RUNTIME,stage,row_binding=row_binding)
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
        env = patch.dict(os.environ, {'TOUCHCOLOR_BUDGET_PHASE': '', 'GITHUB_SHA': '', 'TOUCHCOLOR_JOB_PLATFORM':'', 'TOUCHCOLOR_VISION_CASE':'','TOUCHCOLOR_TEXT_PHASE':'','TOUCHCOLOR_WATCH_PROFILE':'','TOUCHCOLOR_JOB_LANE':'','TOUCHCOLOR_JOB_MINUTES':'','TOUCHCOLOR_EVIDENCE_LIMIT':''})
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
                                          defer_vision_summary=True, source_sha=SHA, row_binding=ROW)
            runner.assert_not_called(); self.assertTrue(offline.pending(result)); self.assertFalse(sizes.qualified(result))
            with self.assertRaises(ValueError):
                sizes.run_largest(DEVICE, Path(folder)/'unused', command, dict(contract, platform='watchOS Simulator'), [CASE], runner,
                                  defer_vision_summary=True, source_sha=SHA, row_binding=ROW)

    def test_largest_live_execution_rejects_missing_normal_or_foreign_binding_before_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            _,_,_,command,contract=fixture(folder)
            for binding in (None, text_row('vision','normal','canvas-audit','',SHA),
                            text_row('vision','system-largest','chinese','',SHA),dict(ROW,source_sha='b'*40)):
                runner=Mock();runner.cleanup_unconfirmed=False
                with patch.object(sizes,'probe') as probe:
                    with self.assertRaises(ValueError):
                        sizes.run_largest(DEVICE,Path(folder)/'unused',command,contract,[CASE],runner,
                                          defer_vision_summary=True,source_sha=SHA,row_binding=binding)
                    probe.assert_not_called();runner.assert_not_called()

    def test_offline_binding_role_phase_case_and_source_reject_before_any_read(self):
        for key,value in [('role','normal'),('native_text_row',text_row('vision','normal','canvas-audit','',SHA)),
                          ('native_text_row',text_row('vision','system-largest','chinese','',SHA)),
                          ('native_text_row',dict(ROW,source_sha='b'*40))]:
            with self.subTest(key=key,value=value),tempfile.TemporaryDirectory() as folder:
                report,summary,shutdown,_,_=fixture(folder);report['deferred_result'][key]=value
                result,reader,query=self.qualify(folder,report,summary,shutdown)
                self.assertFalse(sizes.qualified(result));self.assertFalse(reader.calls);query.assert_not_called()

    def test_original_runtime_error_is_never_cleared_by_later_valid_result(self):
        for original in ('pending_offline_qualification', 'failed'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); report, summary, shutdown, _, _ = fixture(root)
                hosted, hosted_summary=hosted_fixture(root,summary,shutdown)
                runtime = {'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit','vision_offline_expected':['hosted','largest'],'sha': SHA, 'device': {'udid': DEVICE}, 'runtime': RUNTIME, 'result': original,
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
        env=dict(kind='vision',report=report,device={'udid':DEVICE},runtime=RUNTIME,owned_watch_devices=[],pending_vision_result=None,pending_vision_hosted=hosted,pending_vision_normal=None,
            text_phase='system-largest' if case=='canvas-audit' else 'normal',text_row=ROW,
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
            runtime={'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit','vision_offline_expected':['hosted','largest'],'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'passed','largest_system_text':report,
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
            with self.assertRaises(ValueError):offline.evidence_complete(folder)

    def successful_fallback(self, root):
        import job_budget
        root=Path(root);report,summary,shutdown,_,_=fixture(root)
        hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
        self.qualify(root,report,summary,shutdown);self.qualify(root,hosted,hosted_summary,shutdown,role='hosted')
        runtime={'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit','vision_offline_expected':['hosted','largest'],'sha':SHA,'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'passed','largest_system_text':report,
                 'vision_hosted_result':hosted,'vision_offline_shutdown':shutdown,'vision_offline_case':'canvas-audit',
                 'vision_offline_expected':['hosted','largest'],
                 'vision_offline_qualification':{'result':'passed','roles':{'hosted':True,'largest':True},'attempted':{'hosted':True,'largest':True}}}
        runtime_path=root/'build/vision-runtime/runtime.json';runtime_path.write_text(json.dumps(runtime))
        evidence=root/'build/evidence';evidence.mkdir()
        offline.copy_cached_summary(root);offline.copy_cached_summary(root,role='hosted')
        (evidence/'vision-runtime.json').write_bytes(runtime_path.read_bytes())
        self.assertTrue(offline.evidence_complete(evidence))
        environment={**os.environ,'GITHUB_SHA':SHA,'GITHUB_RUN_ID':'1','TOUCHCOLOR_JOB_PLATFORM':'vision',
            'TOUCHCOLOR_VISION_CASE':'canvas-audit','TOUCHCOLOR_TEXT_PHASE':'system-largest','TOUCHCOLOR_WATCH_PROFILE':'',
            'TOUCHCOLOR_JOB_LANE':'vision-canvas-audit-system-largest','TOUCHCOLOR_JOB_MINUTES':'25','TOUCHCOLOR_EVIDENCE_LIMIT':'700000',
            'TOUCHCOLOR_JOB_STARTED_EPOCH':str(time.time()),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(time.monotonic()),
            'GITHUB_OUTPUT':str(root/'outputs.txt'),'TOUCHCOLOR_BUDGET_PHASE':'evidence'}
        with contextlib.chdir(root),patch.dict(os.environ,environment):
            job_budget.STATE.write_text(json.dumps(job_budget.create_record()))
            job_budget.fail_record('Late attachment exporter timed out',phase='evidence')
            job_budget.retain_metadata(fallback_reason='Evidence phase failed or exceeded its reserved deadline')
        self.assertEqual({p.name for p in evidence.iterdir()},{'job-budget.json','vision-runtime.json'})
        return evidence,environment

    def test_symlinked_temporary_root_uses_canonical_fixture_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            parent=Path(folder).resolve(); physical=parent/'physical';physical.mkdir()
            alias=parent/'alias';alias.symlink_to(physical, target_is_directory=True)
            evidence,environment=self.successful_fallback(alias)
            runtime=json.loads((evidence/'vision-runtime.json').read_bytes())
            hosted=runtime['vision_hosted_result']['deferred_result']
            largest=runtime['largest_system_text']['deferred_result']
            self.assertEqual(hosted['root'],str(physical))
            self.assertEqual(largest['contract']['root'],str(physical))
            self.assertEqual(hosted['bundle']['path'],str(physical/offline.HOSTED_BUNDLE))
            self.assertEqual(largest['bundle']['path'],str(physical/offline.BUNDLE))
            # Run the real validator after its prior real qualification/fallback,
            # without writing to the enclosing CI step's environment/output files.
            environment['GITHUB_ENV']=str(parent/'fixture-github-env')
            result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'700000'],
                                  env=environment,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(Path(environment['GITHUB_OUTPUT']).read_text(),'vision_offline_qualified=false\nnative_text_evidence_complete=false\n')

    def test_actual_qualifier_then_controller_fallback_remains_uploadable_but_false(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence,environment=self.successful_fallback(folder)
            result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'700000'],
                                  env=environment,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output=(Path(folder)/'outputs.txt').read_text()
            self.assertEqual(output,'vision_offline_qualified=false\nnative_text_evidence_complete=false\n')
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
                result=subprocess.run([__import__('sys').executable,str(ROOT/'scripts/validate_evidence.py'),str(evidence),'700000'],
                                      env=environment,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,change)
                output=Path(folder)/'outputs.txt'
                self.assertFalse(output.exists() and '=true' in output.read_text())

    def test_all_rows_require_exact_hosted_and_phase_specific_ui(self):
        from vision_suites import CASES
        for case in CASES:
            for phase in ('normal', 'system-largest'):
                if phase == 'system-largest' and case not in ('chinese', 'canvas-audit'): continue
                binding = text_row('vision', phase, case, '', SHA)
                roles = vision_roles(binding)
                runtime = {'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit','vision_offline_expected':['hosted','largest'],'sha': SHA, 'native_text_row': binding, 'vision_offline_case': case, 'vision_offline_expected': roles}
                self.assertEqual(offline.expected_roles(runtime), roles)
                foreign = 'vision_normal_result' if phase == 'system-largest' else 'largest_system_text'
                runtime[foreign] = {'status': 'passed'}
                with self.assertRaisesRegex(ValueError, 'Foreign Vision phase'): offline.expected_roles(runtime)

    def test_wrong_saved_lane_cannot_satisfy_current_row(self):
        for case in ('chinese', 'canvas-audit'):
            binding = text_row('vision', 'system-largest', case, '', SHA)
            runtime = {'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit','vision_offline_expected':['hosted','largest'],'sha': SHA, 'native_text_row': text_row('vision', 'normal', case, '', SHA),
                       'vision_offline_case': case, 'vision_offline_expected': ['hosted', 'normal']}
            env = {'GITHUB_SHA': SHA, 'TOUCHCOLOR_JOB_PLATFORM': 'vision', 'TOUCHCOLOR_VISION_CASE': case,
                   'TOUCHCOLOR_TEXT_PHASE': 'system-largest', 'TOUCHCOLOR_WATCH_PROFILE': '',
                   'TOUCHCOLOR_JOB_LANE': binding['lane'], 'TOUCHCOLOR_JOB_MINUTES': '25', 'TOUCHCOLOR_EVIDENCE_LIMIT': '700000'}
            with patch.dict(os.environ, env):
                with self.assertRaisesRegex(ValueError, 'current row'): offline.expected_roles(runtime)

    def normal_fixture(self, root, case='canvas-audit', exit_code=0):
        root=Path(root).resolve(); original,summary,shutdown,command,contract=fixture(root)
        binding=text_row('vision','normal',case,'',SHA)
        from vision_suites import CASES
        method=CASES[case][0]
        command=[offline.NORMAL_BUNDLE if part==offline.BUNDLE else part for part in command]
        command[-1]='-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+method
        bundle=root/offline.NORMAL_BUNDLE;bundle.mkdir();(bundle/'Info.plist').write_bytes(b'normal fixture only')
        stage=dict(shutdown, command=command, exit=exit_code,
                   started_at=datetime.datetime.fromtimestamp(100,datetime.timezone.utc).isoformat(),
                   finished_at=datetime.datetime.fromtimestamp(300,datetime.timezone.utc).isoformat())
        result=offline.prepare_normal(command,contract,[method],SHA,DEVICE,RUNTIME,stage,row_binding=binding)
        result['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
        hosted,hosted_summary=hosted_fixture(root,summary,shutdown,row_binding=binding)
        return result,summary,shutdown,hosted,hosted_summary,binding

    def test_normal_summary_requires_postshutdown_exact_bundle_and_raw_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);normal,summary,shutdown,hosted,hosted_summary,binding=self.normal_fixture(root)
            self.assertFalse(offline.normal_qualified(normal))
            _,_,normal_query=self.qualify(root,normal,summary,shutdown,role='normal')
            self.assertEqual(normal_query.call_args.kwargs,{'timeout':20,'text':False})
            self.qualify(root,hosted,hosted_summary,shutdown,role='hosted')
            self.assertTrue(offline.normal_qualified(normal))
            runtime={'platform':'vision','sha':SHA,'native_text_row':binding,'vision_offline_case':binding['case'],'vision_offline_expected':['hosted','normal'],
                     'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'passed','vision_normal_result':normal,'vision_hosted_result':hosted,
                     'vision_offline_shutdown':shutdown,'vision_offline_qualification':{'result':'passed','roles':{'hosted':True,'normal':True},'attempted':{'hosted':True,'normal':True}}}
            (root/'build/vision-runtime/runtime.json').write_text(json.dumps(runtime))
            evidence=root/'build/evidence';evidence.mkdir()
            offline.copy_cached_summary(root,role='hosted');offline.copy_cached_summary(root,role='normal')
            (evidence/'vision-runtime.json').write_text(json.dumps(runtime))
            self.assertTrue(offline.evidence_complete(evidence))
            (evidence/'vision-ui-summary.json').unlink()
            with self.assertRaises(ValueError):offline.evidence_complete(evidence)

    def test_normal_failure_wrong_phase_and_wrong_method_never_qualify(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);normal,summary,shutdown,_,_,binding=self.normal_fixture(root,exit_code=65)
            self.qualify(root,normal,summary,shutdown,role='normal')
            self.assertFalse(offline.normal_qualified(normal))
            self.assertEqual(normal['execution_exit'],65)
            self.assertIn('Original normal execution failed',normal['summary_error'])
            with self.assertRaises(ValueError):offline.bind_row(normal,ROW,'normal')
            normal['deferred_result']['cases']=['testRealPhotosImport']
            with self.assertRaises(ValueError):offline.bind_row(normal,binding,'normal')

    def test_missing_hosted_or_required_ui_never_passes_and_no_summary_retries(self):
        for missing in ('hosted','normal'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);normal,summary,shutdown,hosted,hosted_summary,binding=self.normal_fixture(root)
                runtime={'platform':'vision','sha':SHA,'native_text_row':binding,'vision_offline_case':binding['case'],'vision_offline_expected':['hosted','normal'],
                         'device':{'udid':DEVICE},'runtime':RUNTIME,'result':'pending_offline_qualification','vision_offline_shutdown':shutdown}
                runtime['vision_normal_result' if missing=='hosted' else 'vision_hosted_result']=normal if missing=='hosted' else hosted
                path=root/'build/vision-runtime/runtime.json';path.write_text(json.dumps(runtime));seen=[]
                def qualify(setting,report_path,stage,**kwargs):
                    role=kwargs['role'];seen.append(role);setting['deferred_result']['attempted']=True
                    setting['status']=role+'_result_passed';setting['verified_results']={'fixture':True}
                with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence'}),patch.object(offline,'qualify',side_effect=qualify):
                    offline.qualify_for_evidence(root);offline.qualify_for_evidence(root)
                self.assertEqual(len(seen),1)
                self.assertEqual(json.loads(path.read_bytes())['result'],'failed')

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
        self.assertIn('if test "$platform" = vision;',branch);self.assertIn('vision_offline_result.py copy-summary',branch)
        self.assertIn('vision_offline_result.py copy-hosted-summary',workflow)
        self.assertIn('vision_offline_result.py copy-normal-summary',workflow)
        self.assertIn('else\n                python3 scripts/budget_command.py --seconds 20',branch)
        self.assertIn("run: test '${{ steps.evidence_guard.outputs.vision_offline_qualified }}' = 'true'",workflow)
        self.assertLess(workflow.index('Retain small test evidence for review'),workflow.index('Require every deferred Vision result qualification'))


    def test_per_file_inventory_preserves_exact_identity_and_actual_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();fixture(root);inventory={}
            plain=offline.bundle_identity(root)
            observed=offline.bundle_identity(root,inventory=inventory)
            self.assertEqual(observed,plain)
            self.assertTrue(inventory['walk_complete']);self.assertEqual(inventory['omitted_files'],0)
            self.assertEqual(len(inventory['records']),plain['files'])
            for item in inventory['records']:
                actual=(root/offline.BUNDLE/item['path']).read_bytes()
                self.assertEqual(item['sha256'],hashlib.sha256(actual).hexdigest())
                self.assertEqual(item['bytes'],len(actual));self.assertNotIn(str(root),item['path'])
            unchanged=offline.bundle_change_provenance(inventory,inventory)
            self.assertTrue(unchanged['inventory_complete']);self.assertTrue(unchanged['details_complete'])
            self.assertEqual(unchanged['changes'],[])

    def test_changed_summary_bundle_stays_failed_and_records_exact_file_changes(self):
        for role in ('hosted','normal','largest'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown,_,_=fixture(root)
                if role=='hosted':report,summary=hosted_fixture(root,summary,shutdown)
                elif role=='normal':
                    normal_bundle=root/offline.NORMAL_BUNDLE;normal_bundle.mkdir();(normal_bundle/'Info.plist').write_bytes(b'normal fixture')
                    command=report['deferred_result']['command'];command=[offline.NORMAL_BUNDLE if part==offline.BUNDLE else part for part in command]
                    stage=dict(shutdown,command=command,started_at=datetime.datetime.fromtimestamp(100,datetime.timezone.utc).isoformat(),finished_at=datetime.datetime.fromtimestamp(300,datetime.timezone.utc).isoformat())
                    report=offline.prepare_normal(command,report['deferred_result']['contract'],[CASE],SHA,DEVICE,RUNTIME,stage,row_binding=text_row('vision','normal','canvas-audit','',SHA))
                    report['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
                bundle=root/offline.BUNDLES[role]
                old=(bundle/'Info.plist').read_bytes()
                def extract(*args,**kwargs):
                    (bundle/'Info.plist').write_bytes(b'changed test result object')
                    (bundle/'new-read-observation').write_bytes(b'synthetic additional object')
                    return subprocess.CompletedProcess([],0,json.dumps(summary).encode(),b'')
                result,_,command=self.qualify(root,report,summary,shutdown,role=role,summary_runner=Mock(side_effect=extract))
                command.assert_called_once();self.assertEqual(command.call_args.kwargs,{'timeout':20 if role=='normal' else 30,'text':False})
                self.assertIn('Result bundle changed during summary qualification',result['summary_error'])
                self.assertFalse(offline.role_qualified(result,role))
                proof=result['bundle_change_provenance'];self.assertTrue(proof['inventory_complete']);self.assertTrue(proof['details_complete'])
                changes={item['path']:item for item in proof['changes']}
                self.assertEqual(changes['Info.plist']['kind'],'content_changed')
                self.assertEqual(changes['Info.plist']['before']['sha256'],hashlib.sha256(old).hexdigest())
                self.assertEqual(changes['Info.plist']['after']['sha256'],hashlib.sha256(b'changed test result object').hexdigest())
                self.assertEqual(changes['new-read-observation']['kind'],'added')
                self.assertNotEqual(proof['before']['identity']['sha256'],proof['after']['identity']['sha256'])

    def test_inventory_omission_never_hides_aggregate_mutation_or_claims_complete_diff(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown,_,_=fixture(root);bundle=root/offline.BUNDLE
            for index in range(260):(bundle/'Data'/f'entry-{index:03}').write_bytes(b'fixed bytes')
            report['deferred_result']['bundle']=offline.bundle_identity(root)
            def extract(*args,**kwargs):
                (bundle/'Data'/'entry-259').write_bytes(b'changed bytes')
                return subprocess.CompletedProcess([],0,json.dumps(summary).encode(),b'')
            result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=Mock(side_effect=extract))
            self.assertFalse(sizes.qualified(result));self.assertIn('changed during',result['summary_error'])
            proof=result['bundle_change_provenance'];self.assertFalse(proof['inventory_complete'])
            self.assertEqual(proof['status'],'unavailable_incomplete_inventory')
            self.assertGreater(proof['before']['omitted_files'],0);self.assertEqual(proof['before']['retained_files'],256)
            self.assertEqual(proof['changes'],[]);self.assertIsNone(proof['changes_total'])

    def test_change_details_have_finite_count_and_byte_omissions(self):
        before={'walk_complete':True,'observed_files':20,'omitted_files':0,'records':[]}
        for index in range(20):
            before['records'].append({'path':('数'*140)+str(index),'bytes':1,'sha256':'a'*64,'inode':index,'mtime_ns':'123'})
        after=copy.deepcopy(before)
        for item in after['records']:item['sha256']='b'*64
        proof=offline.bundle_change_provenance(before,after)
        self.assertEqual(proof['changes_total'],20);self.assertLessEqual(len(proof['changes']),8)
        self.assertGreater(proof['omitted_changes'],0);self.assertFalse(proof['details_complete'])
        self.assertLessEqual(len(json.dumps(proof,sort_keys=True).encode()),12000)

    def test_timeout_and_identity_deadline_keep_incomplete_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown,_,_=fixture(root)
            error=subprocess.TimeoutExpired(['summary'],30);error.cleanup_confirmed=True
            result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=Mock(side_effect=error))
            self.assertFalse(sizes.qualified(result));proof=result['bundle_change_provenance']
            self.assertEqual(proof['after'],{'status':'not_observed'});self.assertFalse(proof['inventory_complete'])
            inventory={'identity':{'sha256':'stale'}};now=[0.]
            def walk(*args,**kwargs):
                yield str(root/offline.BUNDLE),[],['Info.plist']
                now[0]=1000.
                yield str(root/offline.BUNDLE/'Data'),[],[]
            with patch.object(offline.os,'walk',side_effect=walk):
                with self.assertRaises(ValueError):offline.bundle_identity(root,clock=lambda:now[0],inventory=inventory)
            self.assertFalse(inventory['walk_complete']);self.assertNotIn('identity',inventory)

    def test_final_escaped_filename_provenance_is_bounded_after_status_changes(self):
        # Reviewer reproduced 12,003 bytes after observed -> partial_details.
        # Real result scans, not a synthetic serialization-only object.
        for count in range(150,181):
            with self.subTest(escaped_count=count), tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();fixture(root);bundle=root/offline.BUNDLE
                nested=bundle/('a'*100);nested.mkdir()
                paths=[nested/('\x01'*count+str(index)) for index in range(9)]
                for path in paths:path.write_bytes(b'a')
                before={};offline.bundle_identity(root,inventory=before)
                for path in paths:path.write_bytes(b'b')
                after={};offline.bundle_identity(root,inventory=after)
                proof=offline.bundle_change_provenance(before,after)
                self.assertTrue(proof['inventory_complete']);self.assertEqual(proof['changes_total'],9)
                self.assertLessEqual(len(proof['changes']),8);self.assertGreater(proof['omitted_changes'],0)
                self.assertEqual(proof['status'],'partial_details');self.assertFalse(proof['details_complete'])
                for receipt in ('vision_hosted_result','vision_normal_result','largest_system_text'):
                    self.assertLessEqual(len(receipt),len('vision_hosted_result'))
                    output=root/(receipt+'-provenance.json')
                    offline.write_json(output,{receipt:{'bundle_change_provenance':proof}},limit=12000)
                    self.assertLessEqual(output.stat().st_size,12000)


if __name__=='__main__':unittest.main()
