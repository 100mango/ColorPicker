"""Fixed one-case fault tests; no native command or AppKit execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_scene_diagnostic as m
import job_budget
from test_mac_launch_comparison import Clock, PRODUCT, contact_export
from test_mac_passive_lifecycle import event, envelope

SOURCE=dict(repository='100mango/ColorPicker',ref=m.BRANCH,workflow=m.WORKFLOW,
    workflow_ref='100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,event='push',sha='a'*40,run='1',attempt='1',parent=m.PARENT)
CHECKOUT=Path(__file__).resolve().parents[1]


def env():
    return dict(GITHUB_REPOSITORY=SOURCE['repository'],GITHUB_REF=m.BRANCH,GITHUB_WORKFLOW_REF=SOURCE['workflow_ref'],
        GITHUB_EVENT_NAME='push',GITHUB_SHA=SOURCE['sha'],GITHUB_WORKFLOW_SHA=SOURCE['sha'],GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',
        TOUCHCOLOR_JOB_PLATFORM=m.PLATFORM,TOUCHCOLOR_JOB_LANE=m.PLATFORM,TOUCHCOLOR_JOB_MINUTES='25',TOUCHCOLOR_EVIDENCE_LIMIT='3000000',
        TOUCHCOLOR_JOB_STARTED_EPOCH='100',TOUCHCOLOR_JOB_STARTED_MONOTONIC='100')


class Harness(unittest.TestCase):
    def setUp(self):
        self.old=Path.cwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        Path('source.txt').write_text('exact source fixture\n');m.ROOT.mkdir(parents=True)
        self.clock=Clock();self.calls=[];self.failed=True;self.fault=None;self.delta=None
        self.sources=patch.object(m,'SOURCES',('source.txt',));self.sources.start()
        self.product=patch.object(m,'product_identity',return_value=PRODUCT);self.product.start()
        self.budget=job_budget.JobBudget(job_budget.create_record(env(),wall=self.clock,monotonic=self.clock),wall=self.clock,monotonic=self.clock)
        self.diagnostic=m.Diagnostic(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)

    def tearDown(self):
        self.product.stop();self.sources.stop();os.chdir(self.old);self.tmp.cleanup()

    def export_contact(self):
        identity_path=contact_export(m.ROOT,failed=self.failed)
        self.delta=self.clock.value+.2-99.
        identity=json.loads(identity_path.read_bytes())
        for key in ('started','captured'):identity[key]+=self.delta
        identity_path.write_bytes(m.encode(identity))
        summary_path=m.ROOT/'mac-ui-summary.json';summary=json.loads(summary_path.read_bytes())
        for key in ('startTime','finishTime'):summary[key]+=self.delta
        summary_path.write_bytes(m.encode(summary))
        manifest=m.ROOT/'screenshots/manifest.json';groups=json.loads(manifest.read_bytes())
        for group in groups:
            for item in group['attachments']:item['timestamp']+=self.delta
        manifest.write_bytes(m.encode(groups))

    def logs(self):
        values=[event()]
        for index,name in enumerate(('sceneBody','windowContentEntered','windowContentReturned','colorWindowBody')):
            value=event(event=name,sequence=index+2,elapsed=.2+index*.1,epoch=100.2+index*.1)
            value.pop('product');value.pop('app');values.append(value)
        app=dict(present=True,running=True,active=True,hidden=False,policy=0,count=0,omitted=0,key=None,main=None,windows=[])
        for seq,elapsed in [(6,1.05),(7,5.1)]:
            value=event(event='census',sequence=seq,elapsed=elapsed,epoch=100.+elapsed,app=app)
            value.pop('product');values.append(value)
        final=event(event='final',sequence=8,elapsed=10.1,epoch=110.1,late=True)
        final.pop('product');final.pop('app');values.append(final)
        for value in values:value['epoch']+=self.delta
        return m.encode([envelope(value) for value in values])

    def runner(self,argv,**kwargs):
        index=len(self.calls);self.calls.append((argv,kwargs))
        if self.fault:
            result=self.fault(index,argv,kwargs)
            if result is not None:return result
        output=b'';code=0
        if index==0:output=(SOURCE['sha']+'\n'+m.PARENT+'\n').encode()
        elif index==1:output=b''
        elif index==2:output=b'26A428\n'
        elif index==3:output=b'arm64\n'
        elif index==4:output=(m.TOOLCHAIN['xcode']+'\n').encode()
        elif index==6:
            self.export_contact();self.clock.advance(22.);code=65 if self.failed else 0
        elif index==7:output=(m.ROOT/'mac-ui-summary.json').read_bytes()
        elif index==9:output=self.logs()
        self.clock.advance(.05)
        return subprocess.CompletedProcess(argv,code,output,b'')

    def execute(self):
        value=self.diagnostic.run()
        self.assertEqual(value['status'],'test-closed',value)
        self.assertEqual(len(self.calls),7)
        return value

    def packet(self):
        self.execute()
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        m.validate_packet(m.EVIDENCE,SOURCE)
        return report

    def mutate_state(self,mutation):
        state_path=m.EVIDENCE/'state.json';original=state_path.read_bytes();report_original=m.REPORT.read_bytes()
        state=json.loads(original);mutation(state);raw=m.encode(state);state_path.write_bytes(raw)
        report=json.loads(report_original);report['files']['state.json']=dict(bytes=len(raw),sha256=m.digest(raw));m.REPORT.write_bytes(m.encode(report))
        return original,report_original


class WorkflowContracts(unittest.TestCase):
    def test_exact_source_ref_workflow_run_and_parent_identity(self):
        self.assertEqual(m.source_identity(env()),SOURCE)
        for key,value in [('GITHUB_REF','refs/heads/codex/mac-launch-comparison'),('GITHUB_EVENT_NAME','workflow_dispatch'),
            ('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_RUN_ATTEMPT','0'),('TOUCHCOLOR_JOB_MINUTES','40'),
            ('TOUCHCOLOR_EVIDENCE_LIMIT','4000000'),('TOUCHCOLOR_JOB_PLATFORM','mac')]:
            wrong=env();wrong[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):m.source_identity(wrong)

    def test_only_one_original_case_build_and_scoped_query_plan(self):
        plan=m.plan({'identity':{'pid':345,'token':'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE','started':100.,'result_end':120.}})
        text=' '.join(' '.join(row[1]) for row in plan)
        self.assertEqual(sum('build-for-testing' in row[1] for row in plan),1)
        self.assertEqual(sum('test-without-building' in row[1] for row in plan),1)
        self.assertEqual(sum(row[1][:2]==['/usr/bin/log','show'] for row in plan),1)
        self.assertEqual(len(plan),10)
        self.assertEqual([x for x in m.test_command() if x.startswith('-only-testing:')],
            ['-only-testing:TouchColorMacUITests/TouchColorMacUITests/'+m.CASE])
        for forbidden in ['NSWorkspace','MacLaunchComparison','simctl','retry','test-iterations','skip-testing']:
            self.assertNotIn(forbidden,text)
        self.assertEqual(m.BUDGET['maximumWorkPhases'],820);self.assertEqual(m.BUDGET['workSeconds'],1020)
        self.assertEqual(40+40+30+70,m.EVIDENCE_SECONDS)
        self.assertEqual(sum(job_budget.RESERVES.values()),450)

    def test_workflow_is_one_pinned_standard_job_with_no_dispatch_or_matrix(self):
        text=(CHECKOUT/m.WORKFLOW).read_text()
        for required in ['branches: [codex/mac-scene-checkpoints]','runs-on: xcode-27','timeout-minutes: 25',
            'fetch-depth: 2','persist-credentials: false','TOUCHCOLOR_EVIDENCE_LIMIT: \'3000000\'',
            'python3 scripts/mac_scene_diagnostic.py run','python3 scripts/mac_scene_diagnostic.py evidence']:
            self.assertIn(required,text)
        for forbidden in ['matrix:','workflow_dispatch','schedule:','mac_launch_comparison.py run','continue-on-error','rerun']:
            self.assertNotIn(forbidden,text)
        self.assertEqual(text.count('runs-on:'),1)
        self.assertLess(text.index('uses: actions/upload-artifact@'),text.index('mac_scene_diagnostic.py contact-result'))

    def test_f221_instrumented_swift_files_are_exactly_frozen(self):
        fixture=json.loads((CHECKOUT/'scripts/fixtures/mac-f221-driver-baseline.json').read_bytes())
        for name,digest in fixture['frozen'].items():
            self.assertEqual(hashlib.sha256((CHECKOUT/name).read_bytes()).hexdigest(),digest)
        self.assertEqual(fixture['tree'],'f2211e7f70aa5cbc531aecacfa95a1c54e974956')
        self.assertEqual(set(fixture['instrumented_swift']),{'TouchColorMac/TouchColorMacApp.swift','TouchColorMac/ColorWindow.swift'})

    def test_one_budget_literal_extension_preserves_all_old_rows_and_guards(self):
        self.assertEqual(job_budget.EXPECTED_MINUTES[m.PLATFORM],25)
        text=(CHECKOUT/'scripts/job_budget.py').read_text()
        self.assertEqual(text.count("'mac-scene-checkpoints': 25"),1)
        old=text.replace(", 'mac-scene-checkpoints': 25",'')
        fixture=json.loads((CHECKOUT/'scripts/fixtures/mac-ea9-scene-baseline.json').read_bytes())
        self.assertEqual(hashlib.sha256(old.encode()).hexdigest(),fixture['protected']['scripts/job_budget.py'])

    def test_shallow_checkout_two_levels_exposes_one_parent(self):
        # Local throwaway Git fixtures only; no repository/remote publication.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);repo=root/'source';repo.mkdir()
            def git(folder,*args):return subprocess.check_output(['git','-C',str(folder),*args],stderr=subprocess.DEVNULL)
            git(repo,'init','-q');git(repo,'config','user.name','Fixture');git(repo,'config','user.email','fixture@example.invalid')
            (repo/'a').write_text('one');git(repo,'add','a');git(repo,'commit','-qm','base');parent=git(repo,'rev-parse','HEAD').decode().strip()
            (repo/'a').write_text('two');git(repo,'commit','-qam','successor')
            shallow=root/'one';two=root/'two'
            subprocess.run(['git','clone','-q','--depth','1',repo.as_uri(),str(shallow)],check=True)
            subprocess.run(['git','clone','-q','--depth','2',repo.as_uri(),str(two)],check=True)
            self.assertEqual(len(git(shallow,'show','--no-patch','--format=%H%n%P','HEAD').decode().strip().splitlines()),1)
            self.assertEqual(git(two,'show','--no-patch','--format=%H%n%P','HEAD').decode().strip().splitlines()[1],parent)


class RuntimeFaults(Harness):
    def test_dangling_evidence_symlink_blocks_before_any_native_command(self):
        m.EVIDENCE.symlink_to('missing-output-directory',target_is_directory=True)
        self.assertFalse(m.EVIDENCE.exists())
        with self.assertRaisesRegex(ValueError,'stale-run'):m.require_fresh_run()
        self.assertEqual(self.calls,[])

    def test_stale_state_latch_report_outcome_and_result_all_block_run(self):
        m.require_fresh_run()
        for path in (m.STATE,m.LATCH,m.REPORT,m.VALIDATED,m.VALIDATION_ATTEMPT,m.RESULT):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text('stale')
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'stale-run'):m.require_fresh_run()
            path.unlink()
            if m.EVIDENCE.exists():m.EVIDENCE.rmdir()
        self.assertEqual(self.calls,[])

    def test_fresh_root_failed_case_retains_complete_observation_and_stays_failed(self):
        self.assertFalse(m.EVIDENCE.exists())
        report=self.packet()
        self.assertEqual(report['status'],'observation-only');self.assertEqual(report['contactOutcome'],'failed')
        self.assertFalse(report['acceptance']);self.assertEqual(report['observation'],'zero-windows-at-retained-censuses')
        self.assertEqual(len(report['checkpointsObserved']),4);self.assertEqual(len(self.calls),10)
        self.assertTrue(all(kwargs['cleanup_grace']==10 for _,kwargs in self.calls[:9]))
        self.assertEqual(self.calls[9][1]['cleanup_grace'],2)
        self.assertNotIn('NSWorkspace',str(self.calls))
        m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),1)

    def test_instrumented_original_case_pass_remains_inconclusive_and_not_release_acceptance(self):
        self.failed=False;report=self.packet()
        self.assertEqual(report['contactOutcome'],'passed');self.assertFalse(report['acceptance'])
        self.assertEqual(report['interpretation'],m.INTERPRETATION)
        m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),0)

    def test_wrong_sole_parent_stops_before_later_preparation(self):
        self.fault=lambda i,a,k:subprocess.CompletedProcess(a,0,(SOURCE['sha']+'\n'+'b'*40+'\n').encode(),b'') if i==0 else None
        value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete');self.assertEqual(len(self.calls),1)
        self.assertTrue(m.LATCH.exists())

    def test_preparation_clock_cannot_be_reset_by_prior_work(self):
        self.clock.advance(490)
        value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete')
        self.assertLess(len(self.calls),6);self.assertEqual(value['preparationDeadlineMonotonic'],600.)

    def test_full_300_plus_20_test_admission_is_required(self):
        # Directly isolate admission after a synthetic valid preparation prefix.
        self.execute();self.calls=self.calls[:6];v=self.diagnostic.value
        v['commands']=v['commands'][:6];self.budget.events=self.budget.events[:6];v['status']='incomplete';self.clock.value=v['workDeadlineMonotonic']-319
        with self.assertRaises((ValueError,m.BudgetExhausted)):self.diagnostic.invoke_next()
        self.assertEqual(len(self.calls),6)

    def test_work_persistence_latency_prevents_spawn_without_reset(self):
        real=m.durable
        def delayed(path,value,**kw):
            real(path,value,**kw)
            if path==m.STATE and len(value['commands'])==1 and not value['commands'][0]['returned']:
                self.clock.advance(21)
        with patch.object(m,'durable',side_effect=delayed):value=self.diagnostic.run()
        self.assertEqual(self.calls,[]);self.assertEqual(value['status'],'incomplete');self.assertTrue(m.LATCH.exists())

    def test_known_and_unknown_capture_cleanup_both_fence_further_work(self):
        self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('fixture-timeout',True)) if i==6 else None
        value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete');self.assertEqual(len(self.calls),7)
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),7);self.assertEqual(report['contactOutcome'],'unknown');self.assertEqual(report['records'],[])
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_unknown_cleanup_test_does_not_export_or_query(self):
        self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('fixture-unknown',False)) if i==6 else None
        self.diagnostic.run();report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),7);self.assertEqual(report['status'],'incomplete');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_late_test_return_stops_with_no_summary_or_query(self):
        def late(i,argv,kwargs):
            if i==6:self.clock.advance(kwargs['seconds']+.1);return subprocess.CompletedProcess(argv,65,b'',b'')
        self.fault=late;value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete')
        m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),7)

    def test_late_summary_capture_fences_attachment_export(self):
        self.execute()
        def late(i,argv,kwargs):
            if i==7:self.clock.advance(kwargs['seconds']+.1);return subprocess.CompletedProcess(argv,0,b'{}',b'')
        self.fault=late;report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),8);self.assertEqual(report['status'],'incomplete');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_initial_state_rehash_time_is_inside_same_evidence_clock(self):
        self.execute();real=m.validate_state
        def slow(value,source):
            checked=real(value,source);self.clock.advance(181);return checked
        with patch.object(m,'validate_state',side_effect=slow),self.assertRaisesRegex(ValueError,'state-validation-late'):
            m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),7);self.assertFalse(m.REPORT.exists())

    def test_unknown_test_exit_is_not_promoted_to_known_assertion_failure(self):
        self.fault=lambda i,a,k:subprocess.CompletedProcess(a,1,b'',b'') if i==6 else None
        self.diagnostic.run();report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),7);self.assertEqual(report['contactOutcome'],'unknown');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_missing_thirty_second_query_reserve_does_not_start_query(self):
        self.execute();real=m.closed_contact
        def delayed(value,root):
            contact=real(value,root);self.clock.value=value['evidenceDeadlineMonotonic']-29;return contact
        with patch.object(m,'closed_contact',side_effect=delayed):
            report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),9);self.assertEqual(report['contactOutcome'],'failed')
        self.assertEqual(report['status'],'incomplete');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_query_attempt_persistence_cannot_reset_its_absolute_deadline(self):
        self.execute();real=m.durable;delayed=[]
        def slow(path,value,**kw):
            real(path,value,**kw)
            if path==m.STATE and len(value['commands'])==10 and not value['commands'][-1]['returned'] and not delayed:
                delayed.append(True);self.clock.advance(27)
        with patch.object(m,'durable',side_effect=slow):
            report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),9);self.assertEqual(report['status'],'incomplete');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_wrong_receipt_product_stops_before_query(self):
        self.execute();manifest=json.loads((m.ROOT/'screenshots/manifest.json').read_bytes())
        path=m.ROOT/'screenshots'/manifest[0]['attachments'][0]['exportedFileName']
        receipt=json.loads(path.read_bytes());receipt['logicSHA256']='f'*64;path.write_bytes(m.encode(receipt))
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),9);self.assertEqual(report['contactOutcome'],'unknown');self.assertEqual(report['records'],[])
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_query_timeout_keeps_closed_failed_case_without_raw_query(self):
        self.execute()
        self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('query-timeout',True)) if i==9 else None
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),10);self.assertEqual(report['contactOutcome'],'failed')
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['records'],[])
        self.assertNotIn('lifecycle-query.json',report['files']);m.validate_packet(m.EVIDENCE,SOURCE)

    def test_foreign_query_output_is_never_retained(self):
        self.execute()
        self.fault=lambda i,a,k:subprocess.CompletedProcess(a,0,b'[{"processID":999,"eventMessage":"foreign"}]',b'') if i==9 else None
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(report['status'],'incomplete');self.assertFalse((m.EVIDENCE/'lifecycle-query.json').exists())
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_evidence_attempt_is_not_retried(self):
        self.packet();before=len(self.calls)
        with self.assertRaisesRegex(ValueError,'already-attempted'):
            m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),before)

    def test_persistence_failure_fences_work_and_does_not_leave_complete_state(self):
        real=m.durable
        def fail(path,value,**kw):
            if path==m.STATE and value.get('status')=='test-closed':raise OSError('synthetic fsync failure')
            return real(path,value,**kw)
        with patch.object(m,'durable',side_effect=fail):value=self.diagnostic.run()
        self.assertEqual(value['status'],'incomplete');self.assertTrue(m.LATCH.exists());self.assertEqual(len(self.calls),7)

    def test_final_evidence_persistence_latency_removes_success_report(self):
        self.execute();real=m.durable
        def slow(path,value,**kw):
            real(path,value,**kw)
            if path==m.REPORT and value.get('status')=='observation-only':self.clock.advance(181)
        with patch.object(m,'durable',side_effect=slow),self.assertRaises(ValueError):
            m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertFalse(m.REPORT.exists());self.assertTrue(m.LATCH.exists())


class ValidatorFaults(Harness):
    def test_command_argv_order_caps_and_preflight_output_are_reconstructed(self):
        self.packet()
        mutations=[lambda v:v['commands'][6]['argv'].append('-test-iterations:2'),
            lambda v:v['commands'][5].update(label='build-again'),lambda v:v['commands'][6].update(minimumSeconds=1),
            lambda v:v['commands'][9].update(captureCap=1024*1024),lambda v:v['commands'][0].update(stdoutSHA256='f'*64),
            lambda v:v['commands'][9]['argv'].__setitem__(-1,'process == "TouchColor"')]
        for mutate in mutations:
            original,report=self.mutate_state(mutate)
            with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
            (m.EVIDENCE/'state.json').write_bytes(original);m.REPORT.write_bytes(report)

    def test_admission_overgrant_negative_remaining_and_missing_fields_reject(self):
        self.packet()
        mutations=[lambda v:v['admissions'][0].update(granted_seconds=9999),lambda v:v['admissions'][0].update(remaining_seconds=-1),
            lambda v:v['admissions'][6].update(admitted=False),lambda v:v['admissions'][0].pop('remaining_seconds')]
        for mutate in mutations:
            original,report=self.mutate_state(mutate)
            with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
            (m.EVIDENCE/'state.json').write_bytes(original);m.REPORT.write_bytes(report)

    def test_report_cannot_end_before_commands_or_extend_evidence_clock(self):
        original=m.encode(self.packet())
        for key,value in [('elapsedSeconds',0),('evidenceDeadlineMonotonic',9999),('acceptance',True),('contactOutcome','passed')]:
            report=json.loads(original);report[key]=value;m.REPORT.write_bytes(m.encode(report))
            with self.subTest(key=key),self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
        m.REPORT.write_bytes(original)

    def test_summary_and_receipt_outcome_cannot_be_promoted(self):
        self.packet();path=m.EVIDENCE/'mac-ui-summary.json';original=path.read_bytes();report_original=m.REPORT.read_bytes()
        summary=json.loads(original);summary.update(passedTests=1,failedTests=0,result='Passed',testFailures=[])
        raw=m.encode(summary);path.write_bytes(raw)
        report=json.loads(report_original);report['files']['mac-ui-summary.json']=dict(bytes=len(raw),sha256=m.digest(raw));report['contactOutcome']='passed';m.REPORT.write_bytes(m.encode(report))
        with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_missing_or_modified_original_source_rejects_packet(self):
        self.packet();Path('source.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'source-bytes-changed'):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_incomplete_packet_cannot_invent_contact_or_checkpoint_success(self):
        self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('unknown',False)) if i==6 else None
        self.diagnostic.run();report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        for key,value in [('contactOutcome','passed'),('checkpointsObserved',['sceneBody']),('status','observation-only')]:
            changed=copy.deepcopy(report);changed[key]=value;m.REPORT.write_bytes(m.encode(changed))
            with self.subTest(key=key),self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_final_guard_does_not_run_full_validator_again(self):
        self.packet();m.validate_once(self.budget,SOURCE,clock=self.clock)
        with patch.object(m,'validate_packet',side_effect=AssertionError('second full validation')):
            self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),1)

    def test_final_guard_rejects_changed_report_missing_receipt_and_late_reads(self):
        self.packet()
        with self.assertRaises((ValueError,FileNotFoundError)):m.contact_result(self.budget,SOURCE,clock=self.clock)
        m.validate_once(self.budget,SOURCE,clock=self.clock)
        raw=m.REPORT.read_bytes();m.REPORT.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):m.contact_result(self.budget,SOURCE,clock=self.clock)
        m.REPORT.write_bytes(raw);real=m.read_file
        def slow(path,cap):
            result=real(path,cap)
            if path==m.REPORT:self.clock.advance(21)
            return result
        with patch.object(m,'read_file',side_effect=slow),self.assertRaises(ValueError):m.contact_result(self.budget,SOURCE,clock=self.clock)

    def test_late_validation_receipt_is_removed_and_cannot_authorize_outcome(self):
        self.packet();real=m.durable
        def slow(path,value,**kw):
            real(path,value,**kw)
            if path==m.VALIDATED:self.clock.advance(61)
        with patch.object(m,'durable',side_effect=slow),self.assertRaises(ValueError):m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertFalse(m.VALIDATED.exists())

    def test_validation_fsync_failure_cannot_leave_a_validated_pass(self):
        self.failed=False;self.packet();real=m.durable
        def fail(path,value,**kw):
            real(path,value,**kw)
            if path==m.VALIDATED:raise OSError('after-rename directory fsync failure')
        with patch.object(m,'durable',side_effect=fail),self.assertRaises(OSError):m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertFalse(m.VALIDATED.exists());self.assertTrue(m.VALIDATION_ATTEMPT.exists())
        with self.assertRaises((ValueError,FileNotFoundError)):m.contact_result(self.budget,SOURCE,clock=self.clock)
        with self.assertRaisesRegex(ValueError,'already-attempted'):m.validate_once(self.budget,SOURCE,clock=self.clock)

    def test_validation_attempt_is_durable_before_work_and_cannot_be_reset(self):
        self.packet();calls=[]
        def failed(*args):calls.append(True);raise ValueError('invalid packet')
        with patch.object(m,'validate_packet',side_effect=failed),self.assertRaises(ValueError):m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertTrue(m.VALIDATION_ATTEMPT.exists());self.assertFalse(m.VALIDATED.exists())
        with self.assertRaisesRegex(ValueError,'already-attempted'):m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertEqual(calls,[True])

    def test_stale_validated_receipt_is_not_overwritten(self):
        self.packet();m.VALIDATED.write_text('previous outcome')
        with self.assertRaisesRegex(ValueError,'already-attempted'):m.validate_once(self.budget,SOURCE,clock=self.clock)
        self.assertEqual(m.VALIDATED.read_text(),'previous outcome')

    def test_final_guard_requires_matching_validation_attempt_and_run(self):
        self.packet();m.validate_once(self.budget,SOURCE,clock=self.clock)
        path=m.VALIDATION_ATTEMPT;original=path.read_bytes();attempt=json.loads(original);attempt['source']['run']='2'
        path.write_bytes(m.encode(attempt))
        with self.assertRaisesRegex(ValueError,'changed-validation-attempt'):m.contact_result(self.budget,SOURCE,clock=self.clock)


class SummaryAdmission(unittest.TestCase):
    def check_invalid(self, mutation=None, *, failed=True, raw=None):
        fixture=Harness();fixture.setUp()
        try:
            fixture.failed=failed;fixture.execute()
            path=m.ROOT/'mac-ui-summary.json'
            if raw is None:
                summary=json.loads(path.read_bytes())
                mutation(summary,fixture.diagnostic.value['commands'][6])
                raw=m.encode(summary)
            path.write_bytes(raw)
            report=m.evidence(fixture.budget,SOURCE,runner=fixture.runner,clock=fixture.clock,wall=fixture.clock)
            self.assertEqual(len(fixture.calls),8)
            self.assertFalse(any(argv[:3]==['xcrun','xcresulttool','export'] for argv,_ in fixture.calls))
            self.assertFalse(any(argv[:2]==['/usr/bin/log','show'] for argv,_ in fixture.calls))
            self.assertEqual(report['status'],'incomplete');self.assertEqual(report['contactOutcome'],'unknown')
            self.assertEqual(report['records'],[]);self.assertFalse(report['acceptance'])
            self.assertTrue(m.LATCH.exists());m.validate_packet(m.EVIDENCE,SOURCE)
        finally:fixture.tearDown()

    def test_zero_case_native65_stops_before_export(self):
        self.check_invalid(lambda s,t:s.update(totalTestCount=0,passedTests=0,failedTests=0,testFailures=[]))

    def test_invalid_case_counts_skip_expected_failure_and_count_types_stop_before_export(self):
        changes=[{'totalTestCount':2,'failedTests':2},{'skippedTests':1},{'expectedFailures':1},
            {'passedTests':1,'failedTests':1},{'passedTests':0,'failedTests':0},{'totalTestCount':True},
            {'failedTests':1.0},{'skippedTests':-1}]
        for change in changes:
            with self.subTest(change=change):self.check_invalid(lambda s,t:s.update(change))
        self.check_invalid(lambda s,t:s.pop('totalTestCount'))

    def test_native_exit_and_summary_result_must_agree_before_export(self):
        self.check_invalid(lambda s,t:s.update(passedTests=1,failedTests=0,result='Passed'),failed=True)
        self.check_invalid(lambda s,t:s.update(passedTests=0,failedTests=1,result='Failed'),failed=False)
        self.check_invalid(lambda s,t:s.update(result='Passed'),failed=True)
        self.check_invalid(lambda s,t:s.update(result='Unknown'),failed=True)

    def test_summary_interval_must_be_inside_original_test_wall_clock_before_export(self):
        changes=[lambda s,t:s.update(startTime=t['startedEpoch']-.001),
            lambda s,t:s.update(finishTime=t['finishedEpoch']+.001),
            lambda s,t:s.update(startTime=s['finishTime']),lambda s,t:s.update(startTime=s['finishTime']+1),
            lambda s,t:s.update(startTime=None),lambda s,t:s.update(finishTime=True),
            lambda s,t:s.update(finishTime='later')]
        for index,change in enumerate(changes):
            with self.subTest(index=index):self.check_invalid(change)

    def test_malformed_nonfinite_or_nonobject_summary_never_exports(self):
        for raw in (b'{',b'[]',b'null',b'{"startTime":NaN}',b'{"totalTestCount":1,"totalTestCount":0}'):
            with self.subTest(raw=raw):self.check_invalid(raw=raw)

    def test_exact_boundary_intervals_allow_original_failed_and_passed_receipt_validation(self):
        for failed in (True,False):
            fixture=Harness();fixture.setUp()
            try:
                fixture.failed=failed;fixture.execute();path=m.ROOT/'mac-ui-summary.json'
                summary=json.loads(path.read_bytes());test=fixture.diagnostic.value['commands'][6]
                summary.update(startTime=test['startedEpoch'],finishTime=test['finishedEpoch'])
                path.write_bytes(m.encode(summary))
                report=m.evidence(fixture.budget,SOURCE,runner=fixture.runner,clock=fixture.clock,wall=fixture.clock)
                self.assertEqual(len(fixture.calls),10);self.assertEqual(report['status'],'observation-only')
                self.assertEqual(report['contactOutcome'],'failed' if failed else 'passed')
                self.assertFalse(report['acceptance']);m.validate_packet(m.EVIDENCE,SOURCE)
            finally:fixture.tearDown()

    def test_summary_admission_time_does_not_reset_evidence_deadline_or_allow_export(self):
        fixture=Harness();fixture.setUp()
        try:
            fixture.execute();real=m.admit_summary
            def slow(raw,test):
                real(raw,test);fixture.clock.advance(181)
            with patch.object(m,'admit_summary',side_effect=slow),self.assertRaises(ValueError):
                m.evidence(fixture.budget,SOURCE,runner=fixture.runner,clock=fixture.clock,wall=fixture.clock)
            self.assertEqual(len(fixture.calls),8)
            self.assertFalse(any(argv[:3]==['xcrun','xcresulttool','export'] for argv,_ in fixture.calls))
            self.assertTrue(m.LATCH.exists());self.assertFalse(m.REPORT.exists())
        finally:fixture.tearDown()

    def test_local_admission_precedes_export_and_full_binding_follows_it(self):
        text=(CHECKOUT/'scripts/mac_scene_diagnostic.py').read_text()
        segment=text.split("if value['status']=='test-closed' and not LATCH.exists():",1)[1].split("result=diagnostic.invoke_next()",1)[0]
        self.assertLess(segment.index('summary=diagnostic.invoke_next().stdout'),segment.index('admit_summary(summary'))
        self.assertLess(segment.index('admit_summary(summary'),segment.index('diagnostic.invoke_next()\n'))
        self.assertLess(segment.index('diagnostic.invoke_next()\n'),segment.index('closed_contact(value,ROOT)'))
        helper=text.split('def admit_summary(',1)[1].split('def closed_contact(',1)[0]
        for forbidden in ('invoke_next','capture(', 'read_file(', 'sleep(', 'deadline=', 'validate_packet(', 'NSApp', 'NSWorkspace'):
            self.assertNotIn(forbidden,helper)


if __name__=='__main__':unittest.main()
