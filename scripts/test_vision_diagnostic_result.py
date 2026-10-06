"""Portable failed-Vision diagnostic binding and snapshot integration tests."""
import ast
import contextlib
import copy
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import vision_diagnostic_result as diagnostic
import vision_offline_result as offline
from native_text_rows import row
from simulator_content_size import LARGEST
from test_vision_offline_result import SHA, DEVICE, RUNTIME, CASE, Reader, synthetic_reader, synthetic_reader_guard, attachment_export

ROOT=Path(__file__).resolve().parents[1]
ROW=row('vision','system-largest','canvas-audit','',SHA)


def failed_fixture(root, *, status='largest_ui_failed', exit=65, restored=True):
    root=Path(root).resolve();(root/'build/vision-runtime').mkdir(parents=True,exist_ok=True)
    contract=dict(diagnostic.CONTRACT,root=str(root))
    command=['xcodebuild','test-without-building','-project',contract['project'],'-scheme',contract['scheme'],
             'CODE_SIGNING_ALLOWED=NO','-configuration','Debug','-destination','platform='+contract['platform']+',id='+DEVICE,
             '-derivedDataPath',contract['derived_data'],'-parallel-testing-enabled','NO','-collect-test-diagnostics','never',
             '-test-timeouts-enabled','YES','-default-test-execution-time-allowance','180',
             '-maximum-test-execution-time-allowance','360','-maximum-concurrent-test-simulator-destinations','1','ARCHS=arm64',
             '-resultBundlePath',diagnostic.BUNDLE,'-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+CASE]
    origin=diagnostic.begin_largest_execution(command,contract,[CASE],SHA,DEVICE,RUNTIME,row_binding=ROW)
    start=max(time.time(),origin['checked_at'])+.001
    stage={'command':command,'exit':exit,'started':True,'timed_out':exit==124,'process_group_gone':True,
           'capture_reader_finished':True,'reader_errors':[],'cleanup_error':None,
           'started_at':datetime.datetime.fromtimestamp(start,datetime.timezone.utc).isoformat(),
           'finished_at':datetime.datetime.fromtimestamp(start+1,datetime.timezone.utc).isoformat(),'vision_result_origin':origin}
    operation=dict(command=command,exit=exit,command_started=True,cleanup_confirmed=True,process_group_gone=True,capture_reader_finished=True)
    setting={'device':DEVICE,'runtime':RUNTIME,'status':status,'ui_executed':True,'ui_exit':exit,'restore_verified':restored,
             'observed_largest':LARGEST,'native_text_row':copy.deepcopy(ROW),'expected_ui_contract':contract,
             'operations':[{'label':'actual_ui','operation':operation}],'error':'original native failure'}
    bundle=root/diagnostic.BUNDLE;bundle.mkdir();(bundle/'Info.plist').write_bytes(b'owned failed result')
    (bundle/'Data').mkdir();(bundle/'Data/result').write_bytes(b'failed test attachments')
    return setting,command,contract,stage


class VisionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'','GITHUB_SHA':'','TOUCHCOLOR_JOB_PLATFORM':'',
                                  'TOUCHCOLOR_TEXT_PHASE':'','TOUCHCOLOR_VISION_CASE':''})
        env.start();self.addCleanup(env.stop)
        selected=patch.object(offline,'selected_reader',side_effect=synthetic_reader);selected.start();self.addCleanup(selected.stop)
        guard=patch.object(offline,'verify_reader_file',side_effect=synthetic_reader_guard);guard.start();self.addCleanup(guard.stop)

    def prepare(self, setting, command, contract, stage):
        return diagnostic.prepare_failed_largest(setting,command,contract,[CASE],SHA,DEVICE,RUNTIME,stage,row_binding=ROW)

    def qualify(self, root, setting, **kwargs):
        shutdown={'command':['xcrun','simctl','shutdown',DEVICE],'exit':0,'process_group_gone':True,
                  'capture_reader_finished':True,'reader_errors':[],'cleanup_error':None}
        setting['offline_shutdown_verified']={'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'}
        query=Mock(side_effect=AssertionError('Diagnostic-only result must never query a summary'))
        reader=kwargs.pop('runner',Reader())
        result=offline.qualify(setting,Path(root)/'build/vision-runtime/largest-offline-result.json',shutdown,
            sha=SHA,device=DEVICE,runtime=RUNTIME,runner=reader,summary_runner=query,
            attachment_runner=kwargs.pop('attachment_runner',attachment_export),role='largest',diagnostic=True,
            deadline=kwargs.pop('deadline',time.monotonic()+180),**kwargs)
        query.assert_not_called();return result,reader

    def test_failed_ui_restore_and_clean_timeout_bind_without_changing_live_results(self):
        for status,exit,restored in [('largest_ui_failed',65,True),('restore_readback_failed',0,False),
                                    ('restore_readback_failed',65,False),('largest_ui_failed',124,True)]:
            with self.subTest(status=status,exit=exit),tempfile.TemporaryDirectory() as folder:
                setting,command,contract,stage=failed_fixture(folder,status=status,exit=exit,restored=restored)
                before=copy.deepcopy(setting);binding=self.prepare(setting,command,contract,stage)
                self.assertEqual({k:v for k,v in setting.items() if k!='diagnostic_result'},before)
                self.assertIs(diagnostic.validate_diagnostic(setting,sha=SHA,device=DEVICE,runtime=RUNTIME),binding)
                self.assertFalse(binding['qualification_eligible']);self.assertFalse(binding['attempted'])
                self.assertEqual(binding['purpose'],'attachments_only');self.assertNotIn('deferred_result',setting)
                self.assertFalse(offline.role_qualified(setting,'largest'));self.assertFalse(offline.pending(setting))
                binding['attempted']=True;diagnostic.validate_diagnostic(setting,sha=SHA,device=DEVICE,runtime=RUNTIME)
                with self.assertRaises(ValueError):self.prepare(setting,command,contract,stage)
                self.assertLess(len(json.dumps(setting).encode()),48*1024)

    def test_stale_bundle_and_alias_are_rejected_before_producer(self):
        with tempfile.TemporaryDirectory() as folder:
            setting,command,contract,stage=failed_fixture(folder)
            with self.assertRaisesRegex(ValueError,'stale'):
                diagnostic.begin_largest_execution(command,contract,[CASE],SHA,DEVICE,RUNTIME,row_binding=ROW)
            target=Path(folder)/diagnostic.BUNDLE;shutil.rmtree(target);target.symlink_to('missing')
            with self.assertRaisesRegex(ValueError,'stale'):
                diagnostic.begin_largest_execution(command,contract,[CASE],SHA,DEVICE,RUNTIME,row_binding=ROW)

    def test_invalid_live_ownership_cannot_read_original_or_create_ticket(self):
        changes=[lambda s,st:s.update(ui_executed=False),lambda s,st:s.update(cleanup_unconfirmed=True),
                 lambda s,st:s.update(status='largest_ui_passed'),lambda s,st:s.update(verified_results={'fake':True}),
                 lambda s,st:s.update(deferred_result={}),lambda s,st:s.update(device='OTHER'),
                 lambda s,st:st.update(started=False),lambda s,st:st.update(process_group_gone=False),
                 lambda s,st:st.update(capture_reader_finished=False),lambda s,st:st.update(reader_errors=['broken']),
                 lambda s,st:st.update(cleanup_error='unknown'),lambda s,st:st.pop('vision_result_origin'),
                 lambda s,st:s['operations'].append(copy.deepcopy(s['operations'][0])),
                 lambda s,st:s['operations'][0]['operation'].update(command_started=False)]
        for change in changes:
            with tempfile.TemporaryDirectory() as folder:
                setting,command,contract,stage=failed_fixture(folder);change(setting,stage)
                with patch.object(offline,'bundle_identity') as scan:
                    with self.assertRaises((ValueError,KeyError)):self.prepare(setting,command,contract,stage)
                scan.assert_not_called();self.assertNotIn('diagnostic_result',setting)

    def test_missing_or_unsafe_original_and_root_replacement_reject(self):
        for kind in ('missing-info','link-info','root-replaced'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)/'source';root.mkdir();setting,command,contract,stage=failed_fixture(root)
                if kind=='root-replaced':root.rename(root.with_name('old'));shutil.copytree(root.with_name('old'),root)
                else:
                    info=root/diagnostic.BUNDLE/'Info.plist';info.unlink()
                    if kind=='link-info':info.symlink_to(root/diagnostic.BUNDLE/'Data/result')
                with self.assertRaises(ValueError):self.prepare(setting,command,contract,stage)
                self.assertNotIn('diagnostic_result',setting)

    def test_forged_purpose_case_source_command_lifetime_origin_and_identity_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            setting,command,contract,stage=failed_fixture(folder);self.prepare(setting,command,contract,stage)
            changes=[lambda b:b.update(purpose='qualify'),lambda b:b.update(qualification_eligible=True),
                     lambda b:b.update(attempted=1),lambda b:b.update(role='normal'),lambda b:b.update(source_sha='b'*40),
                     lambda b:b.update(runtime='other'),lambda b:b.update(cases=['testOther']),lambda b:b.update(finished_at=0),
                     lambda b:b['command'].append('-skip-testing:Other'),lambda b:b['execution_origin'].update(absent_before_execution=False),
                     lambda b:b['execution_origin'].update(checked_at=float('nan')),lambda b:b['execution_origin'].update(checked_at=10**20),
                     lambda b:b['execution_origin'].update(invocation='bad'),lambda b:b['execution_origin']['source_root'].update(inode=1),
                     lambda b:b['bundle'].pop('node_identity_sha256'),lambda b:b['native_text_row'].update(phase='normal')]
            for change in changes:
                value=copy.deepcopy(setting);change(value['diagnostic_result'])
                with self.assertRaises((ValueError,KeyError)):diagnostic.validate_diagnostic(value,sha=SHA,device=DEVICE,runtime=RUNTIME)

    def test_receipt_validator_does_not_require_old_runner_filesystem(self):
        with tempfile.TemporaryDirectory() as folder:
            setting,command,contract,stage=failed_fixture(folder);self.prepare(setting,command,contract,stage)
        diagnostic.validate_diagnostic(setting,sha=SHA,device=DEVICE,runtime=RUNTIME)

    def test_real_callback_records_fresh_origin_before_native_run(self):
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text())
        callback=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='size_ui_runner')
        with tempfile.TemporaryDirectory() as folder:
            setting,command,contract,stage=failed_fixture(folder);shutil.rmtree(Path(folder)/diagnostic.BUNDLE)
            report={'sha':SHA,'stages':[]};seen=[]
            def run(actual,seconds,required=True):
                self.assertFalse((Path(folder)/diagnostic.BUNDLE).exists());seen.append('run');report['stages'].append(stage);return 65
            def begin(*args,**kwargs):seen.append('origin');return diagnostic.begin_largest_execution(*args,**kwargs)
            env=dict(kind='vision',contract=contract,largest_cases=[CASE],report=report,device={'udid':DEVICE},runtime=RUNTIME,
                     text_row=ROW,begin_largest_execution=begin,run=run)
            code=ast.Module(body=[callback],type_ignores=[]);ast.fix_missing_locations(code);exec(compile(code,'actual-callback','exec'),env)
            _,_,actual=env['size_ui_runner'](command,600)
            self.assertEqual(seen,['origin','run']);self.assertTrue(actual['vision_result_origin']['absent_before_execution'])

    def test_real_shutdown_tail_carries_diagnostic_proof_without_success(self):
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text());outer=next(n for n in source.body if isinstance(n,ast.Try))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();setting,command,contract,stage=failed_fixture(root);self.prepare(setting,command,contract,stage)
            report={'sha':SHA,'result':'failed','error':'original native failure','stages':[stage],'largest_system_text':setting,
                    'failures':[{'stage':'largest-text','error':'original native failure'}]}
            def run(command,seconds,required=True):
                report['stages'].append({'command':command,'exit':0,'process_group_gone':True,'capture_reader_finished':True,
                    'reader_errors':[],'cleanup_error':None});return 0
            env=dict(kind='vision',report=report,device={'udid':DEVICE},runtime=RUNTIME,owned_watch_devices=[],pending_vision_result=None,
                     pending_vision_hosted=None,pending_vision_normal=None,size_runner=Reader(),Path=Path,os=os,json=json,
                     subprocess=subprocess,out=root/'build/vision-runtime',TouchSizeRunner=lambda c:Reader(),
                     confirm_vision_shutdown=offline.confirm_shutdown,run=run,resources=lambda label:None,fail_record=Mock(),print=lambda *a,**k:None)
            code=ast.Module(body=outer.finalbody,type_ignores=[]);ast.fix_missing_locations(code)
            with contextlib.chdir(root):exec(compile(code,'actual-finally','exec'),env)
            self.assertEqual(report['result'],'failed');self.assertEqual(report['error'],'original native failure')
            self.assertEqual(setting['status'],'largest_ui_failed');self.assertNotIn('deferred_result',setting)
            self.assertEqual(setting['offline_shutdown_verified'],{'device':DEVICE,'runtime':RUNTIME,'state':'Shutdown'})
            self.assertEqual(json.loads((root/'build/vision-runtime/largest-text.json').read_text()),setting)

    def test_diagnostic_only_qualifier_exports_once_cleans_and_remains_failed(self):
        for status,exit,restored in [('largest_ui_failed',65,True),('restore_readback_failed',0,False)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();setting,command,contract,stage=failed_fixture(root,status=status,exit=exit,restored=restored)
                binding=self.prepare(setting,command,contract,stage);original=copy.deepcopy(binding['bundle']);paths=[]
                def export(command,**kwargs):
                    private=Path(command[command.index('--path')+1]);paths.append(private)
                    self.assertNotEqual(str(private),original['path']);(private/'database.sqlite3').write_bytes(b'cache')
                    return attachment_export(command,**kwargs)
                result,reader=self.qualify(root,setting,attachment_runner=export)
                self.assertEqual(result.get('diagnostic_status'),'retained',result)
                self.assertEqual(result['status'],status);self.assertEqual(result['error'],'original native failure')
                self.assertNotIn('verified_results',result);self.assertNotIn('deferred_result',result)
                self.assertTrue(binding['attempted']);self.assertFalse(offline.role_qualified(result,'largest'))
                self.assertEqual(len(paths),1);self.assertFalse(paths[0].parent.exists())
                self.assertEqual(offline.bundle_identity(root),original)
                offline.verify_isolation(result,binding,'largest',RUNTIME,diagnostic=True)
                export_again=Mock();self.qualify(root,setting,attachment_runner=export_again);export_again.assert_not_called()

    def test_diagnostic_export_failure_and_budget_refusal_remain_failed(self):
        for kind in ('export','budget'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();setting,command,contract,stage=failed_fixture(root);self.prepare(setting,command,contract,stage)
                error=subprocess.TimeoutExpired(['export'],20);error.cleanup_confirmed=True
                exporter=Mock(side_effect=error)
                result,reader=self.qualify(root,setting,attachment_runner=exporter,deadline=time.monotonic()+(30 if kind=='budget' else 180))
                self.assertNotEqual(result.get('diagnostic_status'),'retained');self.assertEqual(result['status'],'largest_ui_failed')
                self.assertFalse(offline.role_qualified(result,'largest'))
                if kind=='budget':exporter.assert_not_called()
                else:self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])

    def test_successful_failed_run_diagnostics_survive_actual_evidence_controller(self):
        import job_budget,run_budgeted_step
        from test_budgeted_step import FakeProcess
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();setting,command,contract,stage=failed_fixture(root);self.prepare(setting,command,contract,stage)
            with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence'}),patch.object(offline,'enabled_budget',return_value=None),patch.object(offline,'fail_record') as failure:
                result,_=self.qualify(root,setting)
            failure.assert_not_called();self.assertEqual(result['diagnostic_status'],'retained')
            runtime={'sha':SHA,'platform':'vision','native_text_row':ROW,'vision_offline_case':'canvas-audit',
                     'vision_offline_expected':['hosted','largest'],'device':{'udid':DEVICE},'runtime':RUNTIME,
                     'result':'failed','error':'original native failure','largest_system_text':result}
            (root/'build/vision-runtime/runtime.json').write_text(json.dumps(runtime))
            manifest=root/'build/evidence/vision-largest-text-screenshots/manifest.json'
            environment={'GITHUB_SHA':SHA,'GITHUB_RUN_ID':'1','TOUCHCOLOR_JOB_PLATFORM':'vision',
                         'TOUCHCOLOR_JOB_MINUTES':'35','TOUCHCOLOR_JOB_STARTED_EPOCH':str(time.time()),
                         'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(time.monotonic()),'TOUCHCOLOR_EVIDENCE_LIMIT':'700000'}
            with contextlib.chdir(root),patch.dict(os.environ,environment):
                job_budget.STATE.write_text(json.dumps(job_budget.create_record()))
                with patch.object(run_budgeted_step,'stop_group',return_value=True):
                    code=run_budgeted_step.execute('already collected diagnostics',label='synthetic evidence',seconds=180,
                        phase='evidence',process_factory=lambda *a,**kw:FakeProcess())
                self.assertEqual(code,0)
            self.assertTrue(manifest.is_file());self.assertFalse((root/'build/evidence-incomplete').exists())
            self.assertFalse(offline.evidence_complete(root/'build/evidence'))

    def test_unknown_offline_cleanup_fences_without_invalidating_failed_metadata(self):
        import vision_result_snapshot as snapshots
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();setting,command,contract,stage=failed_fixture(root);self.prepare(setting,command,contract,stage)
            owners=[];real_create=snapshots.create
            def create(*args,**kwargs):
                owner=real_create(*args,**kwargs);owners.append(owner);return owner
            error=subprocess.TimeoutExpired(['export'],20);error.cleanup_confirmed=False
            try:
                with patch.object(snapshots,'create',side_effect=create):
                    result,reader=self.qualify(root,setting,attachment_runner=Mock(side_effect=error))
                self.assertTrue(reader.cleanup_unconfirmed);self.assertTrue(offline.has_unconfirmed_reads(result))
                self.assertEqual(result['status'],'largest_ui_failed')
                diagnostic.validate_diagnostic(result,sha=SHA,device=DEVICE,runtime=RUNTIME)
                runtime={'sha':SHA,'native_text_row':ROW,'vision_offline_case':'canvas-audit',
                         'vision_offline_expected':['hosted','largest'],'device':{'udid':DEVICE},'runtime':RUNTIME,
                         'result':'failed','cleanup_unconfirmed':True,'largest_system_text':result}
                self.assertEqual(offline.expected_roles(runtime),['hosted','largest'])
            finally:
                for owner in owners:owner.cleanup()


if __name__=='__main__':unittest.main()
