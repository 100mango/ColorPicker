"""Portable early-reader identity/deadline tests; no native acceptance claim."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import job_budget
import vision_offline_result as reader
from native_text_rows import row
from test_native_text_rows import environment
from test_job_budget import Clock

class ReaderReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.home=Path(folder.name).resolve();self.root=self.home/'source';self.root.mkdir()
        self.temp=self.home/'runner';self.temp.mkdir();self.developer=self.home/'Developer';self.tool=self.developer/'usr/bin/xcresulttool'
        self.tool.parent.mkdir(parents=True);self.tool.write_bytes(b'portable executable identity');self.tool.chmod(0o700)
        self.binding=row('vision','normal','chinese','','a'*40)
        env=environment(self.binding)|{'RUNNER_TEMP':str(self.temp),'DEVELOPER_DIR':str(self.developer),
            'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','TOUCHCOLOR_BUDGET_PHASE':'',
            'TOUCHCOLOR_JOB_STARTED_EPOCH':str(time.time()-2),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(time.monotonic()-2)}
        for p in [patch.dict(os.environ,env),patch.object(reader,'DEVELOPER_DIR',str(self.developer))]:
            p.start();self.addCleanup(p.stop)
        (self.root/'build').mkdir();(self.root/'build/job-budget.json').write_text(json.dumps(job_budget.create_record()))
        self.version=self.home/'version.txt';self.version.write_bytes((reader.XCODE_VERSION+'\n').encode())
        self.resolve=Mock(return_value=subprocess.CompletedProcess([],0,(str(self.tool)+'\n').encode(),b''))

    def prepare(self):return reader.prepare_reader(self.root,version_observation=self.version,invoke=self.resolve)
    def select(self):return reader.selected_reader(self.root,self.binding,time.monotonic()+300)

    def test_once30_documented_lookup_then_same_vm_local_bytes_only(self):
        value=self.prepare();self.resolve.assert_called_once_with(['xcrun','--find','xcresulttool'],timeout=30,text=False)
        with patch.object(reader,'run_captured',side_effect=AssertionError('No offline process')):
            selected=self.select()
        self.assertEqual(selected['path'],str(self.tool));self.assertEqual(selected['identity'],value['identity'])
        reader.validate_reader_receipt(value,self.binding)
        reader.validate_reader_guard(selected['verification'],selected,time.monotonic()+300)
        with self.assertRaises(FileExistsError):self.prepare()
        self.assertEqual(self.resolve.call_count,1)

    def fixed_clock_budget(self, now, remaining=1498):
        path=self.root/'build/job-budget.json';record=json.loads(path.read_text())
        record['started_monotonic']=now[0]-(1500-remaining)
        # Vary the monotonic boundary without inventing a later job start than
        # the retained preflight version observation when this loop runs slowly.
        record['started_epoch']=min(record['started_epoch'],time.time()-(1500-remaining))
        path.write_text(json.dumps(record))
        return job_budget.JobBudget(record,monotonic=lambda:now[0])

    def test_actual_producer_persisted_selection_and_guard_cross_float_exponent(self):
        # Exact arithmetic changes sign across1024; no epsilon is used anywhere.
        for start in (999.9,1000.1,1000.2,1019.9,1020.1,1023.9):
            with self.subTest(start=start):
                now=[start];budget=self.fixed_clock_budget(now)
                with patch.object(job_budget,'load',return_value=budget),patch.object(reader.time,'monotonic',side_effect=lambda:now[0]):
                    value=self.prepare()
                    saved=json.loads((self.temp/reader.READER_RECEIPT).read_text())
                    self.assertEqual(saved,value)
                    self.assertEqual(saved['selection']['deadline'],start+30)
                    reader.validate_reader_receipt(saved,self.binding)
                    selected=self.select()
                    reader.validate_reader_guard(selected['verification'],selected,start+300)
                    for bad in (math.nextafter(start+30,math.inf),math.nextafter(start+30,-math.inf)):
                        changed=copy.deepcopy(saved);changed['selection']['deadline']=bad
                        with self.assertRaises(ValueError):reader.validate_reader_receipt(changed,self.binding)
                    changed=copy.deepcopy(saved);changed['selection']['finished_at']=start+30
                    with self.assertRaises(ValueError):reader.validate_reader_receipt(changed,self.binding)
                    guard=copy.deepcopy(selected['verification']);guard['deadline']=math.nextafter(start+5,math.inf)
                    with self.assertRaises(ValueError):reader.validate_reader_guard(guard,selected,start+300)
                target=self.temp/reader.READER_RECEIPT;target.unlink();target.parent.rmdir()

    def test_boundary_fixture_keeps_original_job_epoch_after_wall_time_advances(self):
        original=json.loads((self.root/'build/job-budget.json').read_text())['started_epoch']
        later=time.time()+5;now=[1000.1]
        with patch.object(reader.time,'time',return_value=later):
            budget=self.fixed_clock_budget(now)
        self.assertEqual(budget.record['started_epoch'],original)
        with patch.object(job_budget,'load',return_value=budget),patch.object(reader.time,'monotonic',side_effect=lambda:now[0]):
            value=self.prepare();reader.validate_reader_receipt(value,self.binding)
            self.select()
        self.resolve.assert_called_once()

    def test_original_reserve_exhausted_during_prelookup_work_starts_no_process(self):
        now=[1000.1];budget=self.fixed_clock_budget(now,remaining=80)
        actual=reader.file_bytes_identity
        def consumed(path,*args,**kwargs):
            value=actual(path,*args,**kwargs)
            if Path(path)==self.version:now[0]+=30
            return value
        with patch.object(job_budget,'load',return_value=budget),patch.object(reader.time,'monotonic',side_effect=lambda:now[0]),patch.object(reader,'file_bytes_identity',side_effect=consumed):
            with self.assertRaisesRegex(ValueError,'Full early lookup allowance does not fit'):self.prepare()
        self.resolve.assert_not_called();self.assertFalse((self.temp/reader.READER_RECEIPT).exists())

    def test_missing_receipt_and_unknown_owner_fail_without_lookup(self):
        with self.assertRaises(FileNotFoundError):self.select()
        with patch.dict(os.environ,{'RUNNER_TEMP':''}),self.assertRaises(ValueError):self.prepare()
        self.resolve.assert_not_called()

    def test_source_run_attempt_row_environment_owner_budget_identity_cannot_be_reused(self):
        self.prepare()
        for key,value in [('GITHUB_SHA','b'*40),('GITHUB_RUN_ID','456'),('GITHUB_RUN_ATTEMPT','3'),
                          ('TOUCHCOLOR_JOB_LANE','vision-photos'),('DEVELOPER_DIR',str(self.home)),('RUNNER_TEMP',str(self.root))]:
            with self.subTest(key=key),patch.dict(os.environ,{key:value}),self.assertRaises(ValueError):self.select()
        target=self.temp/reader.READER_RECEIPT
        other=self.home/'foreign-runner';other.mkdir();(other/'touchcolor-vision-reader').mkdir(mode=0o700)
        (other/reader.READER_RECEIPT).write_bytes(target.read_bytes())
        with patch.dict(os.environ,{'RUNNER_TEMP':str(other)}),self.assertRaises(ValueError):self.select()
        path=self.root/'build/job-budget.json';raw=path.read_bytes();path.unlink();path.write_bytes(raw)
        with self.assertRaises(ValueError):self.select()

    def test_changed_executable_bytes_inode_mode_version_and_receipt_are_closed(self):
        self.prepare();original=self.tool.read_bytes()
        self.tool.write_bytes(b'changed same VM reader')
        with self.assertRaises(ValueError):self.select()
        self.tool.write_bytes(original)
        with self.assertRaises(ValueError):self.select()  # Restored bytes do not restore inode metadata.
        self.tool.unlink();self.tool.symlink_to('/bin/echo')
        with self.assertRaises(ValueError):self.select()

    def test_version_observation_changes_and_stale_version_are_rejected(self):
        self.prepare();self.version.write_text('Xcode other\n')
        with self.assertRaises(ValueError):self.select()
        path=self.temp/reader.READER_RECEIPT;path.unlink();path.parent.rmdir()
        self.version.write_bytes((reader.XCODE_VERSION+'\n').encode());os.utime(self.version,(1,1))
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.resolve.call_count,1)

    def test_unsupported_resolved_path_or_symlink_is_never_stored(self):
        self.tool.unlink();self.tool.symlink_to('/bin/echo')
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.temp/reader.READER_RECEIPT).exists())

    def test_duplicate_unknown_and_legacy_receipt_contracts_reject(self):
        value=self.prepare();target=self.temp/reader.READER_RECEIPT
        for change in [lambda r:r.update(schema=1),lambda r:r.update(extra=True),lambda r:r['selection'].update(timeout_seconds=31),
                       lambda r:r['context'].update(run_attempt='0'),lambda r:r['identity'].update(sha256='0'*64),
                       lambda r:r['selection'].update(finished_at=r['selection']['deadline']),
                       lambda r:r['version_observation']['identity'].update(sha256='0'*64)]:
            modified=copy.deepcopy(value);change(modified);target.write_text(json.dumps(modified))
            with self.assertRaises(ValueError):self.select()
        target.write_text('{"schema":2,"schema":2}')
        with self.assertRaises(ValueError):self.select()

    def test_lookup_exact_deadline_cannot_become_zero_exit_success(self):
        real=time.monotonic();now=[real]
        def late(*args,**kwargs):now[0]+=30;return self.resolve.return_value
        with patch.object(reader.time,'monotonic',side_effect=lambda:now[0]),self.assertRaises(ValueError):
            reader.prepare_reader(self.root,version_observation=self.version,invoke=late)
        self.assertFalse((self.temp/reader.READER_RECEIPT).exists())

    def test_post_persistence_deadline_removes_receipt_and_forbids_retry(self):
        original=reader.write_json;now=[time.monotonic()]
        def late(*args,**kwargs):original(*args,**kwargs);now[0]+=5
        with patch.object(reader.time,'monotonic',side_effect=lambda:now[0]),patch.object(reader,'write_json',side_effect=late),self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.temp/reader.READER_RECEIPT).exists())
        with self.assertRaises(FileExistsError):self.prepare()

    def test_late_hash_and_file_mutation_fail(self):
        now=[time.monotonic()];actual=reader.hashlib.sha256
        class Digest:
            def __init__(self):self.inner=actual()
            def update(self,value):self.inner.update(value);now[0]+=5
            def hexdigest(self):return self.inner.hexdigest()
        with patch.object(reader.time,'monotonic',side_effect=lambda:now[0]),patch.object(reader.hashlib,'sha256',Digest),self.assertRaises(ValueError):
            reader.file_bytes_identity(self.tool,now[0]+5,executable=True)
        class MutatingDigest:
            def __init__(self):self.inner=actual()
            def update(self,value):self.inner.update(value);os.utime(str(tool),None)
            def hexdigest(self):return self.inner.hexdigest()
        tool=self.tool
        with patch.object(reader.hashlib,'sha256',MutatingDigest),self.assertRaises(ValueError):reader.file_bytes_identity(tool,time.monotonic()+5,executable=True)

class VisionScheduleTests(unittest.TestCase):
    def budget(self):
        clock=Clock();record=job_budget.create_record({'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_JOB_MINUTES':'35',
            'TOUCHCOLOR_JOB_STARTED_EPOCH':str(clock.wall),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(clock.mono),
            'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'1'},wall=lambda:clock.wall,monotonic=lambda:clock.mono)
        return clock,job_budget.JobBudget(record,wall=lambda:clock.wall,monotonic=lambda:clock.mono)

    def test_measured740_plus30_plus_full600_leaves130_work(self):
        clock,budget=self.budget();self.assertEqual(budget.remaining(),1500)
        clock.advance(740+30)
        self.assertEqual(budget.admit('Full Chinese UI',600,minimum=420,cleanup=0),600)
        clock.advance(600);self.assertEqual(budget.remaining(),130)
        self.assertLess(1020-740-30,420)
        legacy=dict(budget.record,minutes=25,reserves=job_budget.RESERVES)
        with self.assertRaises(ValueError):job_budget.JobBudget(legacy,wall=lambda:clock.wall,monotonic=lambda:clock.mono)

    def test_full_ui_minimum_and_exhausted_tail_do_not_borrow(self):
        clock,budget=self.budget();clock.advance(1080)
        self.assertEqual(budget.admit('Boundary UI',600,minimum=420,cleanup=0),420)
        clock.advance(.001)
        with self.assertRaises(job_budget.BudgetExhausted):budget.admit('Late UI',600,minimum=420,cleanup=0)
        clock.advance(budget.remaining('work'))
        self.assertEqual(budget.remaining('cleanup'),130);clock.advance(130)
        self.assertEqual(budget.remaining('evidence'),300)
        self.assertEqual(budget.admit('Evidence',300,minimum=300,cleanup=0,phase='evidence'),300)
        clock.advance(300)
        with self.assertRaises(job_budget.BudgetExhausted):budget.admit('Late evidence',1,phase='evidence',cleanup=0)
        self.assertEqual(budget.remaining('validation'),60);self.assertEqual(budget.remaining('upload'),120)

if __name__=='__main__':unittest.main()
