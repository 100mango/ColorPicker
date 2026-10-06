import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import job_budget as budgets
import run_budgeted_step as steps
import budget_command
from test_job_budget import Clock

class FakeProcess:
    def __init__(self, outcome=0):self.outcome=outcome
    def wait(self, timeout):
        self.wait_timeout=timeout
        if self.outcome=='timeout':raise subprocess.TimeoutExpired('synthetic',timeout)
        return self.outcome

class BudgetControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        old=Path.cwd();os.chdir(self.temp.name);self.addCleanup(os.chdir,old)
        self.clock=Clock()
        self.environment={'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','TOUCHCOLOR_JOB_PLATFORM':'vision',
            'TOUCHCOLOR_JOB_MINUTES':'35','TOUCHCOLOR_JOB_STARTED_EPOCH':str(self.clock.wall),
            'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(self.clock.mono)}
        env=patch.dict(os.environ,self.environment);env.start();self.addCleanup(env.stop)
        record=budgets.create_record(self.environment,wall=lambda:self.clock.wall,monotonic=lambda:self.clock.mono)
        self.budget=budgets.JobBudget(record,wall=lambda:self.clock.wall,monotonic=lambda:self.clock.mono)
    def execute(self,outcome=0,phase='work',cleanup=True):
        process=FakeProcess(outcome);calls=[]
        def factory(command,**kwargs):calls.append((command,kwargs));return process
        with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'stop_group',return_value=cleanup),patch.object(steps,'retain_metadata') as retained,contextlib.redirect_stderr(io.StringIO()):
            code=steps.execute('echo synthetic',label='synthetic',seconds=60,phase=phase,process_factory=factory)
        return code,calls,retained.call_count
    def test_unchanged_body_uses_owned_group_and_exact_phase(self):
        code,calls,_=self.execute()
        self.assertEqual(code,0);self.assertEqual(calls[0][0],['bash','-euo','pipefail','-c','echo synthetic'])
        self.assertTrue(calls[0][1]['start_new_session'])
        self.assertEqual(calls[0][1]['env']['TOUCHCOLOR_BUDGET_PHASE'],'work')
    def test_evidence_body_inherits_its_original_absolute_deadline(self):
        code,calls,_=self.execute(phase='evidence')
        self.assertEqual(code,0)
        self.assertEqual(float(calls[0][1]['env']['TOUCHCOLOR_EVIDENCE_DEADLINE_MONOTONIC']),self.clock.mono+60)
    def test_failed_vision_qualifier_with_pending_owned_reader_fences_later_commands(self):
        root=Path('build/vision-runtime');root.mkdir(parents=True)
        (root/'runtime.json').write_text(json.dumps({'sha':'a'*40,'result':'pending_offline_qualification',
            'vision_hosted_result':{'summary_operation':{'state':'running','cleanup_confirmed':False}}}))
        code,_,_=self.execute(outcome=137,phase='evidence')
        self.assertEqual(code,137);self.assertTrue(budgets.UNCLEAN.exists())
        self.assertTrue(json.loads((root/'runtime.json').read_bytes())['cleanup_unconfirmed'])
        _,calls,_=self.execute(phase='evidence');self.assertEqual(calls,[])
    def test_original_raw_body_cap_cannot_become_late_success(self):
        process=FakeProcess()
        def late_return(timeout):
            self.assertEqual(timeout,60)
            self.clock.advance(100)
            return 0
        process.wait=late_return
        with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'stop_group',return_value=True),contextlib.redirect_stderr(io.StringIO()):
            code=steps.execute('echo synthetic',label='late raw body',seconds=60,phase='work',process_factory=lambda *a,**k:process)
        self.assertEqual(code,124)
        self.assertIn('after its admitted work deadline',json.loads(budgets.INCOMPLETE.read_text())['reason'])
    def test_process_creation_time_does_not_reset_the_raw_body_cap(self):
        process=FakeProcess()
        def factory(*args,**kwargs):self.clock.advance(30);return process
        with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'stop_group',return_value=True),contextlib.redirect_stderr(io.StringIO()):
            code=steps.execute('echo synthetic',label='slow spawn',seconds=60,phase='work',process_factory=factory)
        self.assertEqual(code,0);self.assertEqual(process.wait_timeout,30)
    def test_cleanup_tail_is_only_for_exact_aggregate_aware_driver(self):
        process=FakeProcess()
        with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'stop_group',return_value=True),contextlib.redirect_stderr(io.StringIO()):
            code=steps.execute('python3 scripts/test_extra_platforms.py vision\n',label='native',seconds=1500,phase='work',cleanup_driver=True,process_factory=lambda *a,**k:process)
        self.assertEqual(code,0);self.assertEqual(process.wait_timeout,1500+130)
        for body,seconds,phase in [('echo synthetic',1500,'work'),('python3 scripts/test_extra_platforms.py watch',1500,'work'),('python3 scripts/test_extra_platforms.py vision',60,'work'),('python3 scripts/test_extra_platforms.py vision',1500,'evidence')]:
            with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'retain_metadata'),contextlib.redirect_stderr(io.StringIO()):
                factory=unittest.mock.Mock()
                self.assertNotEqual(steps.execute(body,label='invalid tail',seconds=seconds,phase=phase,cleanup_driver=True,process_factory=factory),0)
                factory.assert_not_called()
    def test_native_driver_grace_cannot_make_late_zero_exit_successful(self):
        process=FakeProcess()
        def late_return(timeout):self.clock.advance(1510);return 0
        process.wait=late_return
        with patch.object(steps,'load',return_value=self.budget),patch.object(steps,'stop_group',return_value=True),contextlib.redirect_stderr(io.StringIO()):
            code=steps.execute('python3 scripts/test_extra_platforms.py vision',label='native late',seconds=1500,phase='work',cleanup_driver=True,process_factory=lambda *a,**k:process)
        self.assertEqual(code,124)
    def test_shell_timeout_cannot_claim_nested_session_cleanup(self):
        code,_,_=self.execute('timeout')
        self.assertEqual(code,124);self.assertTrue(budgets.UNCLEAN.exists())
        self.assertTrue(json.loads(budgets.UNCLEAN.read_text())['cleanup_unconfirmed'])
    def test_failed_cleanup_cannot_leave_zero_exit(self):
        code,_,_=self.execute(cleanup=False)
        self.assertEqual(code,124);self.assertTrue(budgets.UNCLEAN.exists())
    def test_unknown_cleanup_skips_every_evidence_command_but_retains_metadata(self):
        budgets.fail_record('synthetic unknown group',cleanup_unconfirmed=True)
        code,calls,retained=self.execute(phase='evidence')
        self.assertNotEqual(code,0);self.assertEqual(calls,[]);self.assertEqual(retained,1)
    def test_existing_app_failure_does_not_falsify_later_collection_result(self):
        budgets.fail_record('synthetic earlier XCTest assertion',phase='work')
        code,_,retained=self.execute(phase='evidence')
        self.assertEqual(code,0);self.assertEqual(retained,1)
    def test_swallowed_export_failure_still_marks_collection_incomplete(self):
        budgets.fail_record('synthetic export failed',phase='evidence')
        code,_,_=self.execute(phase='evidence')
        self.assertNotEqual(code,0)
    def test_expired_phase_does_not_start_body(self):
        self.clock.advance(1580)
        code,calls,_=self.execute()
        self.assertNotEqual(code,0);self.assertEqual(calls,[])
    def test_retained_budget_metadata_needs_no_external_command(self):
        budgets.fail_record('synthetic expiry',phase='work')
        Path('build/vision-runtime').mkdir();Path('build/vision-runtime/runtime.json').write_text(json.dumps({'result':'failed','sha':'a'*40}))
        with patch.object(budgets,'load',return_value=self.budget):value=budgets.retain_metadata()
        self.assertEqual(value['result'],'failed_or_incomplete')
        self.assertTrue(Path('build/evidence/job-budget.json').is_file())
        self.assertTrue(Path('build/evidence/vision-runtime.json').is_file())
    def test_interrupted_export_retains_honest_metadata_within_same_byte_cap(self):
        root=Path('build/evidence');root.mkdir(parents=True)
        (root/'unvalidated-partial.bin').write_bytes(b'x'*100000)
        budgets.fail_record('synthetic export deadline',phase='evidence')
        with patch.object(budgets,'load',return_value=self.budget):
            value=budgets.retain_metadata(fallback_reason='synthetic incomplete exporter')
        self.assertEqual([p.name for p in root.iterdir()],['job-budget.json'])
        self.assertTrue(Path('build/evidence-incomplete/unvalidated-partial.bin').exists())
        self.assertIn('unpublished_partial_evidence',value)
        self.assertEqual(value['result'],'failed_or_incomplete')
    def test_exact_runtime_retention_rejects_other_source_and_respects_row_cap(self):
        Path('build/vision-runtime').mkdir(parents=True)
        source=Path('build/vision-runtime/runtime.json')
        source.write_text(json.dumps({'sha':'b'*40,'result':'passed'}))
        with patch.object(budgets,'load',return_value=self.budget):budgets.retain_metadata()
        self.assertFalse(Path('build/evidence/vision-runtime.json').exists())
        source.write_text(json.dumps({'sha':'a'*40,'result':'failed','synthetic':'x'*20000}))
        with patch.object(budgets,'load',return_value=self.budget),patch.dict(os.environ,{'TOUCHCOLOR_EVIDENCE_LIMIT':'20000'}):
            value=budgets.retain_metadata()
        self.assertFalse(value['runtime_retention'][0]['retained'])
        self.assertLess(Path('build/evidence/job-budget.json').stat().st_size,budgets.METADATA_RESERVE)
    def test_core_runner_does_not_start_after_aggregate_work_expiry(self):
        import bounded_process
        self.clock.advance(1580)
        with patch.object(budgets,'enabled_budget',return_value=self.budget),patch.object(bounded_process.subprocess,'Popen') as start:
            with self.assertRaises(budgets.BudgetExhausted):bounded_process.run_captured(['synthetic'],30)
        start.assert_not_called()
    def test_real_controller_runs_bounded_owned_shell_and_preserves_exit(self):
        with patch.object(steps,'load',return_value=self.budget),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(steps.execute('exit 7',label='synthetic real shell',seconds=2,phase='work'),7)
        self.assertIn('returned 7',json.loads(budgets.INCOMPLETE.read_text())['reason'])
    def test_exporter_launch_error_records_failure_even_when_shell_would_swallow(self):
        with patch.object(budget_command,'load',return_value=self.budget),patch.object(budget_command,'run_captured',side_effect=OSError('synthetic process creation failed')),contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(budget_command.execute(['xcrun','xcresulttool'],20),0)
        self.assertTrue(Path('build/job-budget-phase-evidence.json').exists())
        self.assertTrue(budgets.UNCLEAN.exists())
        code,calls,_=self.execute(phase='evidence')
        self.assertNotEqual(code,0);self.assertEqual(calls,[])
    def test_unexpected_value_error_after_attempt_is_not_misclassified_as_admission(self):
        with patch.object(budget_command,'load',return_value=self.budget),patch.object(budget_command,'run_captured',side_effect=ValueError('synthetic unexpected pipe error')),contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(budget_command.execute(['xcrun','xcresulttool'],20),0)
        self.assertTrue(budgets.UNCLEAN.exists())
    def test_unexpected_exporter_error_preserves_known_cleanup_proof(self):
        error=RuntimeError('synthetic decoder failure');error.cleanup_confirmed=True
        with patch.object(budget_command,'load',return_value=self.budget),patch.object(budget_command,'run_captured',side_effect=error),contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(budget_command.execute(['xcrun','xcresulttool'],20),0)
        self.assertTrue(Path('build/job-budget-phase-evidence.json').exists())
        self.assertFalse(budgets.UNCLEAN.exists())
    def test_evidence_command_obeys_owned_timeout_and_stdout_bound(self):
        with patch.object(budget_command,'load',return_value=self.budget),patch.object(budget_command,'run_captured',return_value=subprocess.CompletedProcess(['fake'],0,'x'*500001,'')) as run,contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(budget_command.execute(['xcrun','xcresulttool'],20),0)
        self.assertLessEqual(run.call_args.kwargs['timeout'],20)
        self.assertTrue(Path('build/job-budget-phase-evidence.json').exists())

if __name__=='__main__':unittest.main()
