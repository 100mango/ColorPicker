"""Bounded advisory stdout only: no simulator, verdict or budget changes."""
import copy
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import run_watch_crown_control as driver
from test_watch_crown_driver import environment, Clock


def report():
    return {'source':{'sha':'a'*40,'run_id':'123','attempt':'1'},'run_id':'123','attempt':'1',
            'budget':{'sha':'a'*40,'run_id':'123'},'phases':[{'name':'preflight','completed':True}],
            'stages':[],'cases':[],'cleanup':{},'errors':[],'acceptance':False}


def decode(raw):
    value=json.loads(raw.decode().removeprefix('WATCH_CROWN_STATUS '))
    return {'sha':value['sha'],'run_id':value['run'],'attempt':value['try'],
        'boundary':value['phase'],'phase_completed':value['done'],'stage_count':value['stages'],
        'last':dict(zip(('phase','operation','exit','raw_exit','timed_out','group_gone','reader_finished'),value['last'])),
        'cases':[dict(zip(('started','result','exit','cleanup_confirmed'),value['cases'][key]))
                 for key in ('static',)],
        'cleanup_confirmed':value['cleanup'],'error_count':value['errors'],
        'acceptance':value['acceptance'],'console_omitted':value['omitted'],'delivery':value['delivery']}


class ConsoleProjectionTests(unittest.TestCase):
    def test_unknown_native_results_remain_null(self):
        value=report();before=copy.deepcopy(value)
        raw=driver._console_record(value,'preflight',0);result=decode(raw)
        self.assertEqual(value,before)
        self.assertLessEqual(len(raw),512)
        self.assertEqual(result['sha'],'a'*40);self.assertEqual(result['run_id'],'123')
        self.assertTrue(result['phase_completed']);self.assertFalse(result['acceptance'])
        self.assertIsNone(result['cleanup_confirmed'])
        for case in result['cases']:
            self.assertIsNone(case['result']);self.assertIsNone(case['started']);self.assertIsNone(case['exit'])
            self.assertIsNone(case['cleanup_confirmed'])
        self.assertTrue(all(v is None for v in result['last'].values()))

    def test_real_failure_is_mirrored_without_alias_or_sensitive_text(self):
        value=report();secret='PRIVATE_SENTINEL\nUNTRUSTED_OUTPUT'
        value['errors']=[secret]
        value['stages']=[dict(command=['xcodebuild','test-without-building',secret],phase='isolated_static',started=True,
                             exit=65,raw_exit=65,timed_out=False,process_group_gone=True,capture_reader_finished=True,
                             failure_output_tail=secret)]
        value['cases']=[dict(name='isolated_static',stage_index=0,observed_command_result='failed',cleanup_confirmed=True,notes=secret)]
        raw=driver._console_record(value,'final',2);result=decode(raw)
        self.assertNotIn(b'PRIVATE_SENTINEL',raw);self.assertNotIn(b'UNTRUSTED_OUTPUT',raw)
        self.assertEqual(result['cases'][0]['result'],'failed');self.assertEqual(result['cases'][0]['exit'],65)
        self.assertEqual(result['last']['operation'],'xctest');self.assertEqual(result['error_count'],1)
        self.assertEqual(result['console_omitted'],2);self.assertFalse(result['acceptance'])

    def test_actual_generated_records_write_once_with_darwin_512_pipe_buf(self):
        clock=Clock();d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall)
        d.report=report();sent=[]
        with patch.object(driver.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)), \
             patch.object(driver.os,'fpathconf',return_value=512), \
             patch.object(driver.os,'get_blocking',return_value=True),patch.object(driver.os,'set_blocking'), \
             patch.object(driver.os,'write',side_effect=lambda fd,raw:sent.append(raw) or len(raw)):
            for boundary in driver.CONSOLE_BOUNDARIES:d.console_summary(boundary)
        self.assertEqual(len(sent),7);self.assertEqual(d.console_omitted,0)
        self.assertTrue(all(len(raw)<=512 for raw in sent))
        self.assertEqual([decode(raw)['boundary'] for raw in sent],list(driver.CONSOLE_BOUNDARIES))
        for raw in sent:
            value=json.loads(raw.decode().removeprefix('WATCH_CROWN_STATUS '))
            self.assertEqual(value['v'],1);self.assertEqual(len(value['last']),7)
            self.assertEqual(set(value['cases']),{'static'})
            self.assertTrue(all(len(fields)==4 for fields in value['cases'].values()))

    def test_maximum_allowed_generated_fields_fit_512_without_omission(self):
        value=report();value['source'].update(run_id='9'*24,attempt='9'*6)
        value.update(run_id='9'*24,attempt='9'*6);value['budget']['run_id']='9'*24
        stage=dict(command=['xcrun','simctl','spawn'],phase='isolated_static',started=False,
                   exit=1_000_000_000,raw_exit=1_000_000_000,timed_out=False,
                   process_group_gone=False,capture_reader_finished=False)
        value['stages']=[stage]*192;value['errors']=['private']*192
        value['cases']=[dict(name=m['key'],stage_index=0,observed_command_result='failed',cleanup_confirmed=False)
                        for m in driver.METHODS]
        value['cleanup']={'confirmed':False}
        value['phases']=[{'name':b,'completed':False} for b in driver.CONSOLE_BOUNDARIES]
        for boundary in driver.CONSOLE_BOUNDARIES:
            raw=driver._console_record(value,boundary,9)
            self.assertIsNotNone(raw);self.assertLessEqual(len(raw),512)
            result=decode(raw)
            self.assertEqual(result['console_omitted'],9)
            self.assertTrue(all(c['result']=='failed' and c['exit']==1_000_000_000 for c in result['cases']))
        self.assertIsNone(driver._console_record(value,'final',10))
        self.assertIsNone(driver._console_record(value,'final',True))

    def test_source_and_run_mismatch_drop_instead_of_misattributing(self):
        for mutate in (lambda v:v['budget'].update(sha='b'*40),lambda v:v.update(run_id='999'),
                       lambda v:v.update(attempt='2'),lambda v:v['source'].update(sha='not-a-source'),
                       lambda v:v['source'].update(run_id='1'*1000)):
            value=report();mutate(value)
            self.assertIsNone(driver._console_record(value,'final',0))
        self.assertIsNone(driver._console_record(report(),'raw-user-provided-boundary',0))

    def test_malformed_fields_and_ambiguous_cases_never_become_passed(self):
        value=report();value['stages']=[{'command':['private-command','sensitive-argument'],'phase':'SECRET',
                                      'exit':10**100,'raw_exit':True,'timed_out':'false'}]
        value['cases']=[{'name':'isolated_static','stage_index':False,'observed_command_result':'PRIVATE'}]*2
        self.assertIsNone(driver._console_record(value,'final',0))
        value['cases']=value['cases'][:1]
        result=decode(driver._console_record(value,'final',0))
        self.assertIsNone(result['cases'][0]['result']);self.assertIsNone(result['cases'][0]['started'])
        self.assertIsNone(result['last']['operation']);self.assertIsNone(result['last']['phase'])
        self.assertIsNone(result['last']['exit']);self.assertIsNone(result['last']['raw_exit']);self.assertIsNone(result['last']['timed_out'])
        value['phases']*=2
        self.assertIsNone(decode(driver._console_record(value,'preflight',0))['phase_completed'])

    def test_count_encoded_size_and_total_caps_are_fixed(self):
        value=report();value['stages']=[{}]*193
        self.assertIsNone(driver._console_record(value,'final',0))
        value=report();value['cases']=[{}]*4
        self.assertIsNone(driver._console_record(value,'final',0))
        clock=Clock();d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall)
        d.report=report();sent=[]
        with patch.object(driver,'_write_console_nonblocking',side_effect=lambda raw:sent.append(raw) or True):
            for _ in range(100):
                for boundary in driver.CONSOLE_BOUNDARIES:d.console_summary(boundary)
        self.assertEqual(len(sent),7);self.assertTrue(all(len(raw)<=512 for raw in sent))
        self.assertEqual(d.console_bytes,sum(map(len,sent)));self.assertLessEqual(d.console_bytes,4608)

    def test_dropped_write_is_accounted_without_retry(self):
        clock=Clock();d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall);d.report=report()
        sent=[]
        def write(raw):sent.append(raw);return len(sent)>1
        with patch.object(driver,'_write_console_nonblocking',side_effect=write):
            d.console_summary('preflight');d.console_summary('preflight');d.console_summary('final')
        self.assertEqual(len(sent),2);self.assertEqual(decode(sent[1])['console_omitted'],1)
        self.assertEqual(d.console_omitted,1)

    def test_phase_emits_only_after_persist_and_charges_original_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            old=Path.cwd();os.chdir(folder)
            try:
                Path('build/evidence').mkdir(parents=True)
                clock=Clock();d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall)
                started=dict(d.budget.record);before=d.budget.remaining();captured=[]
                def write(raw):
                    persisted=json.loads(Path('build/evidence/report.json').read_text())
                    self.assertTrue(persisted['phases'][-1]['completed'])
                    captured.append(raw);clock.advance(0.25);return True
                with patch.object(driver,'_write_console_nonblocking',side_effect=write):
                    with d.phase('preflight',30):pass
                self.assertEqual(len(captured),1);self.assertEqual(d.budget.record,started)
                self.assertAlmostEqual(d.budget.remaining(),before-0.25)
                persisted=json.loads(Path('build/evidence/report.json').read_text())
                self.assertNotIn('console_omitted',persisted);self.assertEqual(persisted['stages'],[])
            finally:os.chdir(old)

    def test_logging_error_cannot_change_receipt_or_abort_cleanup(self):
        clock=Clock();d=driver.Driver(environment(),clock=lambda:clock.mono,wall=lambda:clock.wall);d.report=report()
        original=copy.deepcopy(d.report)
        with patch.object(driver,'_write_console_nonblocking',side_effect=OSError('private')):d.console_summary('cleanup')
        self.assertEqual(d.report,original);self.assertEqual(d.console_omitted,1)
        self.assertFalse(d.work_stopped);self.assertFalse(d.budget.cleanup_unconfirmed)


class NonblockingWriterTests(unittest.TestCase):
    def test_one_atomic_write_restores_original_flag_and_never_retries_eagain(self):
        with patch.object(driver.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)),\
             patch.object(driver.os,'fpathconf',return_value=4096),patch.object(driver.os,'get_blocking',return_value=True),\
             patch.object(driver.os,'set_blocking') as flags,patch.object(driver.os,'write',side_effect=BlockingIOError()) as write:
            self.assertFalse(driver._write_console_nonblocking(b'record\n'))
            self.assertEqual(write.call_count,1);self.assertEqual(flags.call_args_list,[( (1,False), ),( (1,True), )])

    def test_regular_files_and_oversized_atomic_records_are_skipped(self):
        with patch.object(driver.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFREG)),patch.object(driver.os,'write') as write:
            self.assertFalse(driver._write_console_nonblocking(b'record\n'));write.assert_not_called()
        with patch.object(driver.os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)),\
             patch.object(driver.os,'fpathconf',return_value=512),patch.object(driver.os,'write') as write:
            self.assertFalse(driver._write_console_nonblocking(b'x'*513));write.assert_not_called()

    def test_actual_full_pipe_returns_without_waiting(self):
        code='''import os,time
from run_watch_crown_control import _write_console_nonblocking
r,w=os.pipe();os.dup2(w,1);os.set_blocking(1,False)
for _ in range(4096):
 try:os.write(1,b'x'*4096)
 except BlockingIOError:break
else:raise RuntimeError('Pipe never reached finite bound')
os.set_blocking(1,True);started=time.monotonic()
if _write_console_nonblocking(b'record\\n') is not False:raise RuntimeError('Unexpected accepted full-pipe write')
if time.monotonic()-started>1:raise RuntimeError('Console waited for stdout')
if os.get_blocking(1) is not True:raise RuntimeError('Original stdout flag changed')
os.close(r);os.close(w)
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(driver.__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
        self.assertEqual(result.returncode,0,result.stderr.decode())

if __name__=='__main__':unittest.main()
