"""Portable adversarial integration of the single-reader snapshot lifecycle."""
import contextlib
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import vision_offline_result as offline
import vision_result_snapshot as snapshots
from test_vision_offline_result import (fixture, hosted_fixture, Reader, synthetic_reader,
    attachment_export, SHA, DEVICE, RUNTIME, ROW)
import test_vision_offline_result as fixtures

ROOT = Path(__file__).resolve().parents[1]
REAL_READER = offline.selected_reader


class VisionReadIsolationTests(unittest.TestCase):
    def setUp(self):
        self.deadline=time.monotonic()+180
        env=patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'','GITHUB_SHA':'','TOUCHCOLOR_JOB_PLATFORM':'',
            'TOUCHCOLOR_VISION_CASE':'','TOUCHCOLOR_TEXT_PHASE':'','TOUCHCOLOR_WATCH_PROFILE':'',
            'TOUCHCOLOR_JOB_LANE':'','TOUCHCOLOR_JOB_MINUTES':'','TOUCHCOLOR_EVIDENCE_LIMIT':''})
        env.start();self.addCleanup(env.stop)
        selected=patch.object(offline,'selected_reader',return_value=synthetic_reader())
        selected.start();self.addCleanup(selected.stop)

    def qualify(self,*args,**kwargs):
        return fixtures.VisionOfflineTests.qualify(self,*args,**kwargs)

    def role_fixture(self,root,role):
        if role=='normal':
            report,summary,shutdown,*_=fixtures.VisionOfflineTests.normal_fixture(self,root)
        else:
            report,summary,shutdown,*_=fixture(root)
            if role=='hosted':report,summary=hosted_fixture(root,summary,shutdown)
        return report,summary,shutdown

    def test_every_role_shares_one_mutable_scratch_between_both_readers(self):
        for role in ('hosted','normal','largest'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,role)
                original=copy.deepcopy(report['deferred_result']['bundle']);seen=[]
                def query(command,**kwargs):
                    private=Path(command[-1]);seen.append(private)
                    self.assertNotEqual(str(private),original['path'])
                    (private/'arbitrary-reader-cache').write_bytes(b'disposable reader bytes')
                    return subprocess.CompletedProcess(command,0,json.dumps(summary).encode(),b'')
                def export(command,**kwargs):
                    private=Path(command[command.index('--path')+1]);seen.append(private)
                    self.assertEqual((private/'arbitrary-reader-cache').read_bytes(),b'disposable reader bytes')
                    (private/'other-cache').write_text('attachment side effect')
                    return attachment_export(command,**kwargs)
                result,_,_=self.qualify(root,report,summary,shutdown,role=role,summary_runner=query,attachment_runner=export)
                self.assertTrue(offline.role_qualified(result,role),result.get('summary_error'))
                self.assertEqual(seen[0],seen[1]);self.assertFalse(seen[0].parent.exists())
                self.assertEqual(offline.bundle_identity(root,offline.BUNDLES[role]),original)
                offline.verify_isolation(result,result['deferred_result'],role,RUNTIME)

    def test_arbitrary_original_add_remove_change_and_empty_directory_rename_fail(self):
        for mutate in ('add','remove','change','empty-directory'):
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
                original=root/offline.BUNDLE
                if mutate=='empty-directory':
                    (original/'old-empty').mkdir();report['deferred_result']['bundle']=offline.bundle_identity(root)
                def query(command,**kwargs):
                    if mutate=='add':(original/'not-a-known-filename').write_bytes(b'x')
                    elif mutate=='remove':(original/'Data/result').unlink()
                    elif mutate=='change':(original/'Data/result').write_bytes(b'x')
                    else:(original/'old-empty').rename(original/'new-empty')
                    return subprocess.CompletedProcess(command,0,json.dumps(summary).encode(),b'')
                result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=query)
                self.assertFalse(offline.role_qualified(result,'largest'))
                self.assertFalse(result['read_isolation']['original_postguard_confirmed'])
                self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])

    def test_unsafe_reader_added_snapshot_node_blocks_attachment_and_preserves_original(self):
        for kind in ('symlink','hardlink','fifo'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
                original=copy.deepcopy(report['deferred_result']['bundle']);export=Mock()
                def query(command,**kwargs):
                    target=Path(command[-1])/'unsafe-reader-cache'
                    if kind=='symlink':target.symlink_to(root/offline.BUNDLE/'Info.plist')
                    elif kind=='hardlink':os.link(root/offline.BUNDLE/'Info.plist',target)
                    else:os.mkfifo(target)
                    return subprocess.CompletedProcess(command,0,json.dumps(summary).encode(),b'')
                result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=query,attachment_runner=export)
                export.assert_not_called();self.assertFalse(offline.role_qualified(result,'largest'))
                self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])
                # A hardlink changes original inode metadata and therefore remains a failure even after unlink.
                if kind!='hardlink':self.assertEqual(offline.bundle_identity(root),original)

    def test_snapshot_replaced_by_reader_cannot_be_exported_or_claim_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest');export=Mock()
            def query(command,**kwargs):
                target=Path(command[-1]);target.rename(target.with_name('moved.xcresult'));target.mkdir()
                return subprocess.CompletedProcess(command,0,json.dumps(summary).encode(),b'')
            result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=query,attachment_runner=export)
            export.assert_not_called();self.assertFalse(offline.role_qualified(result,'largest'))
            self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])

    def test_forged_source_snapshot_tool_command_output_hash_or_cleanup_receipt_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            self.qualify(root,report,summary,shutdown)
            changes=[
                lambda p:p['read_isolation'].update(source_sha='b'*40),
                lambda p:p['read_isolation'].update(device='other'),
                lambda p:p['read_isolation'].update(runtime='other'),
                lambda p:p['read_isolation'].update(role='normal'),
                lambda p:p['read_isolation']['reader'].update(path='/tmp/xcresulttool'),
                lambda p:p['read_isolation']['reader'].update(xcode_version='other'),
                lambda p:p['read_isolation']['snapshot']['equivalence'].update(ordinary_byte_copy=False),
                lambda p:p['read_isolation']['snapshot']['input_binding'].update(sha256='b'*64),
                lambda p:p['read_isolation']['snapshot']['owned_root'].update(path=p['deferred_result']['bundle']['source_root']['path']),
                lambda p:p['read_isolation']['snapshot']['cleanup'].update(confirmed=False),
                lambda p:p['read_isolation']['snapshot']['cleanup'].update(deleted=False),
                lambda p:p['read_isolation'].update(original_postguard_confirmed=False),
                lambda p:p['read_isolation'].update(qualified_at=0),
                lambda p:p['read_isolation']['snapshot']['reader_input_guard'].update(verified=False),
                lambda p:p['summary_operation']['input_guard'].update(files=999999),
                lambda p:p['attachment_operation']['input_guard'].update(bytes=10**20),
                lambda p:p.update(device='OTHER'),
                lambda p:p.update(runtime='OTHER'),
                lambda p:p['summary_operation']['command'].__setitem__(-1,p['deferred_result']['bundle']['path']),
                lambda p:p['attachment_operation']['command'].__setitem__(-1,'/tmp/forged-output'),
                lambda p:p['attachment_operation'].update(exit=1),
                lambda p:p['read_isolation']['summary_output'].update(path='/tmp/forged-summary'),
                lambda p:p.update(summary_sha256='b'*64),
                lambda p:p['read_isolation']['attachment_output'].update(path='/tmp/forged-output'),
            ]
            for change in changes:
                value=copy.deepcopy(report);change(value)
                with self.assertRaises((ValueError,KeyError)):
                    offline.verify_isolation(value,value['deferred_result'],'largest',RUNTIME)

    def test_initial_reader_rejects_changed_private_bytes_before_any_read(self):
        for kind in ('bytes','replacement'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
                actual=snapshots.OwnedSnapshot.verify;query=Mock();export=Mock();seen=[]
                def mutate(owner,*args,**kwargs):
                    if not seen:
                        target=owner.path/'Info.plist'
                        if kind=='bytes':target.write_bytes(b'changed before first reader')
                        else:
                            data=target.read_bytes();target.unlink();target.write_bytes(data)
                    seen.append(True);return actual(owner,*args,**kwargs)
                with patch.object(snapshots.OwnedSnapshot,'verify',mutate):
                    result,_,_=self.qualify(root,report,summary,shutdown,summary_runner=query,attachment_runner=export)
                query.assert_not_called();export.assert_not_called()
                self.assertFalse(offline.role_qualified(result,'largest'))
                self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])

    def test_incomplete_and_contradictory_identity_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            self.qualify(root,report,summary,shutdown)
            def private(value):
                for item in (value['read_isolation']['snapshot_input_binding'],value['read_isolation']['snapshot']['input_binding']):
                    item.pop('device',None);item.pop('inode',None)
            def original(value):
                proof=value['read_isolation']
                for item in (value['deferred_result']['bundle'],proof['original'],proof['original_postguard'],
                             proof['snapshot']['original_binding'],proof['snapshot']['original_guard']['identity']):
                    item.pop('node_identity_sha256',None)
            def aliased_node_digest(value):
                proof=value['read_isolation'];digest=value['deferred_result']['bundle']['node_identity_sha256']
                for item in (proof['snapshot_input_binding'],proof['snapshot']['input_binding'],
                             value['summary_operation']['input_guard']['input_binding']):
                    item['node_identity_sha256']=digest
            def aliased_owned_root(value):
                source=value['deferred_result']['bundle']['source_root']
                value['read_isolation']['snapshot']['owned_root'].update(device=source['device'],inode=source['inode'])
            changes=[private,original,aliased_node_digest,aliased_owned_root,
                lambda v:v['read_isolation']['snapshot']['owned_root'].update(device=99999999),
                lambda v:v['read_isolation']['snapshot']['owned_root'].update(inode=0),
                lambda v:v['read_isolation']['snapshot']['original_guard'].pop('finished_at'),
                lambda v:v['summary_operation']['input_guard'].update(input_byte_equivalent=False),
                lambda v:v['read_isolation'].update(lifecycle_finished=False)]
            for change in changes:
                value=copy.deepcopy(report);change(value)
                with self.assertRaises((ValueError,KeyError)):
                    offline.verify_isolation(value,value['deferred_result'],'largest',RUNTIME)

    def test_failed_summary_keeps_exported_diagnostics_without_evidence_failure(self):
        import job_budget,run_budgeted_step
        from test_budgeted_step import FakeProcess
        for role in ('hosted','normal','largest'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,role)
                summary['result']='Failed';summary['failedTests']=1
                exported=Mock(side_effect=attachment_export)
                with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence'}),patch.object(offline,'enabled_budget',return_value=None),patch.object(offline,'fail_record') as failure:
                    result,_,_=self.qualify(root,report,summary,shutdown,role=role,attachment_runner=exported)
                failure.assert_not_called();self.assertEqual(exported.call_count,1)
                self.assertFalse(offline.role_qualified(result,role))
                self.assertTrue(result['read_isolation']['evidence_collected'])
                manifest=root/'build/evidence'/offline.ATTACHMENT_NAMES[role]/'manifest.json'
                self.assertTrue(manifest.is_file())
                environment={'GITHUB_SHA':SHA,'GITHUB_RUN_ID':'1','TOUCHCOLOR_JOB_PLATFORM':'vision',
                    'TOUCHCOLOR_JOB_MINUTES':'25','TOUCHCOLOR_JOB_STARTED_EPOCH':str(time.time()),
                    'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(time.monotonic()),'TOUCHCOLOR_EVIDENCE_LIMIT':'700000',
                    'GITHUB_OUTPUT':str(root/'outputs')}
                with contextlib.chdir(root),patch.dict(os.environ,environment):
                    job_budget.STATE.write_text(json.dumps(job_budget.create_record()))
                    with patch.object(run_budgeted_step,'stop_group',return_value=True):
                        code=run_budgeted_step.execute('already collected diagnostics',label='synthetic evidence',seconds=180,
                            phase='evidence',process_factory=lambda *a,**kw:FakeProcess())
                    self.assertEqual(code,0)
                self.assertTrue(manifest.is_file())
                self.assertFalse((root/'build/evidence-incomplete').exists())

    def test_incomplete_creation_without_owned_path_still_fences_next_role(self):
        setting={'read_isolation':{'lifecycle_finished':True,'snapshot':{
            'creation_attempted':True,'cleanup':{'confirmed':False,'not_created':False}}}}
        self.assertTrue(offline.has_unconfirmed_reads(setting))
        self.assertTrue(offline.has_unconfirmed_reads({'read_isolation':{'started_at':1}}))

    def test_final_original_guard_and_confirmed_cleanup_happen_on_reader_failure(self):
        for stage in ('summary','attachment'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
                error=subprocess.TimeoutExpired(['synthetic'],20);error.cleanup_confirmed=True
                kwargs={stage+'_runner':Mock(side_effect=error)}
                result,reader,_=self.qualify(root,report,summary,shutdown,**kwargs)
                self.assertFalse(offline.role_qualified(result,'largest'));self.assertFalse(reader.cleanup_unconfirmed)
                self.assertTrue(result['read_isolation']['original_postguard_confirmed'])
                self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])

    def test_preinvoke_persistence_failure_never_claims_a_started_reader_or_leaks_scratch(self):
        for stage in ('summary','attachment'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
                real=offline.write_json;injected=[];invoke=Mock()
                def write(path,value,**kwargs):
                    if value is report and report.get(stage+'_operation',{}).get('state')=='running' and not injected:
                        injected.append(True);raise OSError('synthetic durable write failure before invoke')
                    return real(path,value,**kwargs)
                with patch.object(offline,'write_json',side_effect=write):
                    result,reader,_=self.qualify(root,report,summary,shutdown,**{stage+'_runner':invoke})
                invoke.assert_not_called();self.assertFalse(reader.cleanup_unconfirmed)
                self.assertFalse(offline.role_qualified(result,'largest'))
                self.assertFalse(result[stage+'_operation']['command_started'])
                self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])
                self.assertFalse(Path(result['read_isolation']['snapshot']['owned_root']['path']).exists())

    def test_final_guard_and_diagnostic_write_failures_cannot_skip_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            real=offline.bundle_identity;reads=[]
            def identity(*args,**kwargs):
                reads.append(True)
                if len(reads)==2:raise ValueError('synthetic final original guard failure')
                return real(*args,**kwargs)
            with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence'}),patch.object(offline,'enabled_budget',return_value=None),patch.object(offline,'bundle_identity',side_effect=identity),patch.object(offline,'fail_record',side_effect=OSError('synthetic failure ledger unavailable')):
                result,_,_=self.qualify(root,report,summary,shutdown)
            self.assertFalse(offline.role_qualified(result,'largest'))
            self.assertTrue(result['read_isolation']['snapshot']['cleanup']['confirmed'])
            self.assertIn('ledger unavailable',result['failure_record_error'])
            self.assertFalse(Path(result['read_isolation']['snapshot']['owned_root']['path']).exists())

    def test_final_guard_before_inventory_initialization_still_persists_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            real=offline.bundle_identity;reads=[]
            def identity(*args,**kwargs):
                reads.append(True)
                if len(reads)==2:raise ValueError('final scan failed before reading any node')
                return real(*args,**kwargs)
            with patch.object(offline,'bundle_identity',side_effect=identity):
                result,_,_=self.qualify(root,report,summary,shutdown)
            persisted=json.loads((root/'build/vision-runtime/largest-offline-result.json').read_bytes())
            self.assertFalse(offline.role_qualified(persisted,'largest'))
            self.assertTrue(persisted['read_isolation']['snapshot']['cleanup']['confirmed'])
            self.assertFalse(persisted['bundle_change_provenance']['after']['walk_complete'])
            self.assertEqual(persisted['bundle_change_provenance']['after']['observed_files'],0)
            self.assertIn('before reading any node',persisted['summary_error'])

    def test_provenance_diagnostic_failure_cannot_skip_final_failed_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            with patch.object(offline,'bundle_change_provenance',side_effect=ValueError('diagnostic unavailable')):
                result,_,_=self.qualify(root,report,summary,shutdown)
            persisted=json.loads((root/'build/vision-runtime/largest-offline-result.json').read_bytes())
            self.assertFalse(offline.role_qualified(persisted,'largest'))
            self.assertTrue(persisted['read_isolation']['snapshot']['cleanup']['confirmed'])
            self.assertTrue(persisted['read_isolation']['original_postguard_confirmed'])
            self.assertEqual(persisted['bundle_change_provenance_error'],'diagnostic unavailable')

    def test_cleanup_failure_latches_no_next_role_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            owned=[];real_create=snapshots.create
            def create(*args,**kwargs):
                value=real_create(*args,**kwargs);owned.append(value);return value
            with patch.object(snapshots,'create',side_effect=create),patch.object(snapshots.OwnedSnapshot,'cleanup',return_value=False):
                result,reader,_=self.qualify(root,report,summary,shutdown)
            self.assertFalse(offline.role_qualified(result,'largest'));self.assertTrue(reader.cleanup_unconfirmed)
            hosted,hosted_summary=hosted_fixture(root,summary,shutdown)
            _,_,query=self.qualify(root,hosted,hosted_summary,shutdown,role='hosted',runner=reader)
            query.assert_not_called();self.assertTrue(result['read_isolation']['original_postguard_confirmed'])
            for owner in owned:self.assertTrue(owner.cleanup())

    def test_shared_deadline_cannot_reset_or_borrow_a_later_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();report,summary,shutdown=self.role_fixture(root,'largest')
            result,reader,query=self.qualify(root,report,summary,shutdown,deadline=time.monotonic()+30)
            query.assert_not_called();self.assertFalse(reader.calls)
            self.assertIn('Shared evidence deadline',result['summary_error'])
        for value in ('','nan',str(time.monotonic()+1000)):
            with patch.dict(os.environ,{'TOUCHCOLOR_BUDGET_PHASE':'evidence','TOUCHCOLOR_EVIDENCE_DEADLINE_MONOTONIC':value}):
                with self.assertRaises(ValueError):offline.evidence_deadline()

    def test_selected_reader_uses_live_toolchain_version_and_documented_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            developer=Path(folder).resolve();tool=developer/'usr/bin/xcresulttool';tool.parent.mkdir(parents=True)
            tool.write_bytes(b'portable tool');tool.chmod(0o700);seen=[]
            def read(label,command,seconds,limit):
                seen.append((command,seconds));return offline.XCODE_VERSION+'\n' if command[0]=='xcodebuild' else str(tool)+'\n'
            with patch.object(offline,'DEVELOPER_DIR',str(developer)),patch.dict(os.environ,{'DEVELOPER_DIR':str(developer)}):
                value=REAL_READER(read)
                self.assertEqual(value['path'],str(tool));self.assertEqual(seen,[(['xcodebuild','-version'],5),(['xcrun','--find','xcresulttool'],5)])
                with self.assertRaises(ValueError):REAL_READER(lambda *a:'Xcode other')
                tool.unlink();tool.symlink_to('/bin/echo')
                with self.assertRaises(ValueError):REAL_READER(read)

    def test_real_sigterm_and_sigint_unwind_owned_child_and_snapshot(self):
        child_script='''import os,signal,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
def finish(sig,frame):
    child.terminate();child.wait(timeout=3);raise SystemExit(128+sig)
signal.signal(signal.SIGTERM,finish)
open(sys.argv[1],'w').write(str(os.getpid())+' '+str(child.pid))
while True:time.sleep(1)
'''
        for stage in ('summary','attachment'):
            for signum in (signal.SIGTERM,signal.SIGINT):
                with self.subTest(stage=stage,signal=signum),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder).resolve();ready=root/'ready';child=root/'owned.py';child.write_text(child_script)
                    script=root/'harness.py';script.write_text('''import json,sys,subprocess
from pathlib import Path
import vision_offline_result as o
from bounded_process import run_captured
from test_vision_offline_result import fixture,Reader,synthetic_reader,attachment_export,SHA,DEVICE,RUNTIME
root=Path(sys.argv[1]);stage=sys.argv[2]
report,summary,shutdown,*_=fixture(root)
o.selected_reader=lambda read:synthetic_reader()
def blocked(command,**kwargs):return run_captured([sys.executable,str(root/'owned.py'),str(root/'ready')],timeout=30,text=False)
def query(command,**kwargs):return subprocess.CompletedProcess(command,0,json.dumps(summary).encode(),b'')
o.qualify(report,root/'build/vision-runtime/largest-offline-result.json',shutdown,sha=SHA,device=DEVICE,runtime=RUNTIME,runner=Reader(),summary_path=root/'build/vision-runtime/largest-summary.json',summary_runner=blocked if stage=='summary' else query,attachment_runner=blocked if stage=='attachment' else attachment_export)
''')
                    process=subprocess.Popen([sys.executable,str(script),str(root),stage],env={**os.environ,'PYTHONPATH':str(ROOT/'scripts')},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    try:
                        end=time.monotonic()+5
                        while not ready.exists() and process.poll() is None and time.monotonic()<end:time.sleep(.02)
                        self.assertTrue(ready.exists(),'Owned child never became ready')
                        pids=[int(pid) for pid in ready.read_text().split()]
                        os.kill(process.pid,signum)
                        out,err=process.communicate(timeout=25)
                        self.assertEqual(process.returncode,0,(out,err))
                        report=json.loads((root/'build/vision-runtime/largest-offline-result.json').read_bytes())
                        self.assertTrue(report['interrupted']);self.assertFalse(offline.role_qualified(report,'largest'))
                        self.assertTrue(report['summary_operation' if stage=='summary' else 'attachment_operation']['cleanup_confirmed'])
                        self.assertTrue(report['read_isolation']['original_postguard_confirmed'])
                        self.assertTrue(report['read_isolation']['snapshot']['cleanup']['confirmed'])
                        for pid in pids:
                            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
                    finally:
                        if process.poll() is None:process.kill();process.wait(timeout=5)
                        process.stdout.close();process.stderr.close()


if __name__=='__main__':unittest.main()
