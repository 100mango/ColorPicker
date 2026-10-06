"""Portable contract/fault-injection tests; native AppKit execution is not implied."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_launch_comparison as m
from job_budget import JobBudget, create_record, BudgetExhausted
from palette_lifecycle_diagnostics import CaptureStopped
from test_mac_passive_lifecycle import exported, receipt, event, envelope, APP

ROOT=Path(__file__).resolve().parents[1]
SOURCE={'repository':'100mango/ColorPicker','ref':m.BRANCH,'workflow':m.WORKFLOW,
    'workflow_ref':'100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,'event':'push','sha':'a'*40,'run':'1','attempt':'1'}
PRODUCT={k:receipt()[k] for k in ('applicationPath','executable','executableSHA256','logicSHA256')}
TOKEN='BBBBBBBB-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
SUITE='TouchColor.mac-ui.CCCCCCCC-BBBB-CCCC-DDDD-EEEEEEEEEEEE'


def caller():
    return dict(inspection='validated-Security-signing-information',entitlementsState='no-embedded-entitlements',
        sandboxEnabled=False,inheritedSandbox='not-independently-measured',executableSHA256='d'*64)


def request():
    return dict(schema=1,source=SOURCE,product=PRODUCT,token=TOKEN,suite=SUITE,args=m.ARGS,deadlineMonotonic=292.)


def control():
    return dict(schema=1,route='NSWorkspace',source=SOURCE,requestSHA256=m.digest(m.encode(request())),status='completed',
        started=200.,controllerStartedMonotonic=200.,deadlineMonotonic=292.,launchRequests=1,terminateRequests=1,
        preexistingCount=0,caller=caller(),identity=dict(product={**PRODUCT,'bundle':'com.mango.touchColor'},pid=346,token=TOKEN,suite=SUITE,args=m.ARGS),
        callback=202.,terminated=214.,cleanupConfirmed=True,reason='process-launch-only-not-window-readiness',
        finished=214.1,finishedMonotonic=214.1,requested=201.,requestedMonotonic=201.,callbackDeadlineMonotonic=260.,
        callbackMonotonic=202.,observationDeadlineMonotonic=214.,terminationRequested=213.5,
        terminationRequestedMonotonic=213.5,terminationDeadlineMonotonic=233.5,terminatedMonotonic=214.)


def contact_export(root, failed=True):
    file=exported(root)
    path=root/'mac-ui-summary.json';summary=json.loads(path.read_text())
    summary.update(passedTests=0 if failed else 1,failedTests=1 if failed else 0,skippedTests=0,expectedFailures=0,totalTestCount=1,
        result='Failed' if failed else 'Passed',testFailures=[{'targetName':'TouchColorMacUITests','testName':m.CASE+'()',
        'testIdentifier':1,'failureText':'XCTAssertTrue failed - synthetic test fixture','testIdentifierString':'TouchColorMacUITests/'+m.CASE+'()',
        'testIdentifierURL':'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+m.CASE}] if failed else [])
    summary['devicesAndConfigurations'][0].update({k:summary[k] for k in ('passedTests','failedTests','skippedTests','expectedFailures')})
    path.write_bytes(m.encode(summary));return file


class Clock:
    def __init__(self):self.value=100.
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds


def budget(clock):
    env=dict(TOUCHCOLOR_JOB_PLATFORM=m.PLATFORM,TOUCHCOLOR_JOB_MINUTES='25',TOUCHCOLOR_JOB_STARTED_EPOCH='100',
        TOUCHCOLOR_JOB_STARTED_MONOTONIC='100',GITHUB_SHA='a'*40,GITHUB_RUN_ID='1')
    return JobBudget(create_record(env,wall=clock,monotonic=clock),wall=clock,monotonic=clock)


class ReceiptTests(unittest.TestCase):
    def validate(self,c=None,r=None):
        return m.validate_control(m.encode(control() if c is None else c),m.encode(request() if r is None else r),SOURCE,PRODUCT,'d'*64)

    def test_distinct_receipt_never_fabricates_xctest_identity(self):
        value=self.validate()
        self.assertEqual(value['route'],'NSWorkspace')
        for forbidden in ('test','case','ordinal','xctestPID','sandbox','expectedPath'):self.assertNotIn(forbidden,value)
        self.assertEqual(value['receipt_sha256'],m.digest(m.encode(control())))

    def test_control_missing_and_unknown_fields_fail(self):
        for key in control():
            c=control();c.pop(key)
            with self.subTest(key=key),self.assertRaises((ValueError,TypeError,KeyError)):self.validate(c)
        c=control();c['case']=m.CASE
        with self.assertRaises(ValueError):self.validate(c)

    def test_preexisting_duplicate_wrong_path_and_pid_fail(self):
        for key,value in [('preexistingCount',1),('preexistingCount',2),('launchRequests',2),('terminateRequests',2),
            ('cleanupConfirmed',False),('requestSHA256','f'*64),('route','XCTest')]:
            c=control();c[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(c)
        for key,value in [('pid',0),('pid',True),('token','invalid'),('token',receipt()['token']),('args',['--ui-test-reset']),('suite','anything')]:
            c=control();c['identity'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(c)
        for key in PRODUCT:
            c=control();c['identity']['product'][key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(c)

    def test_callback_missing_error_late_and_wrong_source_fail(self):
        for key,value in [('callback',None),('status','error'),('callbackMonotonic',260.),('deadlineMonotonic',300.),
            ('finishedMonotonic',292.),('terminationRequestedMonotonic',214.),('terminatedMonotonic',233.5),
            ('terminationDeadlineMonotonic',260.),('observationDeadlineMonotonic',250.),('source',{**SOURCE,'run':'2'})]:
            c=control();c[key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,TypeError)):self.validate(c)

    def test_sandboxed_missing_or_unreadable_caller_fails(self):
        for key,value in [('sandboxEnabled',True),('sandboxEnabled',0),('entitlementsState','missing'),('entitlementsState','blob-only'),
            ('inspection','error'),('executableSHA256','f'*64),('inheritedSandbox','unsandboxed-proven')]:
            c=control();c['caller'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(c)
        c=control();c['caller']=None
        with self.assertRaises(ValueError):self.validate(c)
        c=control();c['caller']['entitlementsState']='readable-dictionary';self.validate(c)

    def test_exact_locale_two_tokens_and_request_hash_bound(self):
        for key,value in [('args',[]),('token','invalid'),('suite','TouchColor.mac-ui.'+TOKEN),('schema',True),
            ('source',{**SOURCE,'attempt':'2'}),('product',{**PRODUCT,'logicSHA256':'f'*64})]:
            r=request();r[key]=value;c=control();c['requestSHA256']=m.digest(m.encode(r))
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(c,r)

    def test_missing_receipt_not_optional_and_failed_contact_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);file=contact_export(root)
            failed=m.validate_contact(root,PRODUCT,65);self.assertEqual(failed['outcome'],'failed')
            with self.assertRaises(ValueError):m.validate_contact(root,PRODUCT,0)
            file.unlink()
            with self.assertRaises((ValueError,FileNotFoundError)):m.validate_contact(root,PRODUCT,65)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);contact_export(root,False)
            self.assertEqual(m.validate_contact(root,PRODUCT,0)['outcome'],'passed')

    def test_wrong_method_counts_configuration_or_product_fail(self):
        for change in [lambda s:s.update(totalTestCount=2),lambda s:s.update(skippedTests=1),
            lambda s:s['testFailures'][0].update(testIdentifierString='other'),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(architecture='x86_64')]:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);contact_export(root);p=root/'mac-ui-summary.json';value=json.loads(p.read_text());change(value);p.write_bytes(m.encode(value))
                with self.assertRaises(ValueError):m.validate_contact(root,PRODUCT,65)


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.previous=os.getcwd();os.chdir(self.directory.name)
        m.ROOT.mkdir(parents=True);self.clock=Clock();self.calls=[]
    def tearDown(self):os.chdir(self.previous);self.directory.cleanup()
    def coordinator(self,behavior=None):
        def runner(argv,**kwargs):
            self.calls.append((argv,kwargs))
            if behavior:return behavior(argv,kwargs)
            self.clock.advance(.1);return subprocess.CompletedProcess(argv,0,b'{}',b'')
        return m.Coordinator(budget(self.clock),SOURCE,runner=runner,clock=self.clock,wall=self.clock)

    def test_full_320_and_112_admission(self):
        for seconds,remaining in [(300,319.99),(92,111.99)]:
            c=self.coordinator();self.clock.advance(c.budget.remaining()-remaining)
            with self.assertRaises(BudgetExhausted):c.invoke('fixed',['owned'],seconds)
            self.assertEqual(self.calls,[])
            self.clock.value=100.
        self.assertEqual(sum([500,320,80,112]),1012)
        self.assertEqual(budget(self.clock).remaining(),1020)

    def test_persistence_time_cannot_reset_deadline_or_spawn_after_it(self):
        c=self.coordinator();real=c.persist
        def delayed():real();self.clock.advance(301)
        c.persist=delayed
        with self.assertRaises(BudgetExhausted):c.invoke('fixed',['owned'],300)
        self.assertEqual(self.calls,[]);self.assertTrue(m.LATCH.exists())

    def test_persistence_rechecks_original_absolute_deadline(self):
        c=self.coordinator();real=c.persist
        def delayed():real();self.clock.advance(2)
        c.persist=delayed;c.invoke('fixed',['owned'],300)
        self.assertAlmostEqual(self.calls[0][1]['seconds'],298.)
        self.assertEqual(c.value['commands'][0]['deadlineMonotonic'],400.)
        self.assertEqual(c.value['commands'][0]['cleanupDeadlineMonotonic'],420.)

    def test_late_return_and_timeout_fence_every_next_command(self):
        behaviors=[lambda a,k:(self.clock.advance(301) or subprocess.CompletedProcess(a,0,b'{}',b'')),
            lambda a,k:(_ for _ in ()).throw(CaptureStopped('timeout',True)),
            lambda a,k:(_ for _ in ()).throw(CaptureStopped('unknown-cleanup',False)),
            lambda a,k:(_ for _ in ()).throw(CaptureStopped('cancelled',True,15))]
        for behavior in behaviors:
            m.LATCH.unlink(missing_ok=True);self.calls=[];self.clock.value=100.;c=self.coordinator(behavior)
            with self.assertRaises((ValueError,CaptureStopped)):c.invoke('fixed',['owned'],300)
            self.assertTrue(m.LATCH.exists());self.assertTrue(c.stopped)
            with self.assertRaises(ValueError):c.invoke('forbidden',['app-query'],1)
            self.assertEqual(len(self.calls),1)

    def test_exhausted_preparation_and_intermediate_ceilings(self):
        c=self.coordinator();self.clock.advance(480.01)
        with self.assertRaises(ValueError):c.invoke('compile',['swiftc'],60,minimum=1,deadline=c.preparation_deadline)
        self.assertEqual(self.calls,[])
        self.clock.value=100.;c=self.coordinator();deadline=180.
        c.invoke('summary',['summary'],20,deadline=deadline)
        self.clock.value=160.01
        with self.assertRaises(ValueError):c.invoke('export',['export'],20,deadline=deadline)
        self.assertEqual(len(self.calls),1)

    def test_unknown_capture_exception_and_output_flood_fence(self):
        for behavior in [lambda a,k:(_ for _ in ()).throw(OSError('spawn')),
            lambda a,k:subprocess.CompletedProcess(a,0,b'x'*11,b'')]:
            m.LATCH.unlink(missing_ok=True);self.calls=[];c=self.coordinator(behavior)
            with self.assertRaises((ValueError,OSError)):c.invoke('fixed',['owned'],1,cap=10)
            self.assertTrue(m.LATCH.exists())

    def test_known_failed_test_may_continue_only_through_valid_receipt_gate(self):
        c=self.coordinator();c.value['product']=PRODUCT
        c.value['commands']=[{}]*8+[{'startedEpoch':98.,'finishedEpoch':121.}]
        def invoke(label,argv,*args,**kwargs):
            self.calls.append(label)
            if label=='single-contact-test':return subprocess.CompletedProcess(argv,65,b'',b'')
            if label=='contact-summary':
                contact_export(m.ROOT);return subprocess.CompletedProcess(argv,0,(m.ROOT/'mac-ui-summary.json').read_bytes(),b'')
            return subprocess.CompletedProcess(argv,0,b'',b'')
        c.invoke=invoke;c.contact()
        self.assertEqual(c.value['contact']['outcome'],'failed');self.assertEqual(len(self.calls),3)

    def test_after_uncertainty_final_evidence_uses_files_only(self):
        c=self.coordinator();c.stop('test-timeout')
        def forbidden(*a,**k):raise AssertionError('No host query after uncertainty')
        report=m.final_evidence(c.budget,SOURCE,runner=forbidden,clock=self.clock)
        self.assertEqual(report['status'],'incomplete');self.assertIsNone(report['query'])
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_contact_final_persistence_expiry_latches_before_control(self):
        c=self.coordinator();c.value['product']=PRODUCT
        c.value['commands']=[{}]*8+[{'startedEpoch':98.,'finishedEpoch':121.}]
        def invoke(label,argv,*args,**kwargs):
            self.calls.append(label)
            if label=='single-contact-test':return subprocess.CompletedProcess(argv,65,b'',b'')
            if label=='contact-summary':
                contact_export(m.ROOT);return subprocess.CompletedProcess(argv,0,(m.ROOT/'mac-ui-summary.json').read_bytes(),b'')
            return subprocess.CompletedProcess(argv,0,b'',b'')
        c.invoke=invoke
        real=c.persist
        def delayed():
            real()
            if c.value['status']!='incomplete' or c.value.get('contact') is not None:
                self.clock.value=180.1
        c.persist=delayed;c.prepare=lambda:None
        control_calls=[];c.control=lambda:control_calls.append('forbidden')
        result=c.run()
        self.assertTrue(m.LATCH.exists());self.assertTrue(c.stopped)
        self.assertEqual(result['reason'],'intermediate-final-persistence-late')
        self.assertEqual(control_calls,[]);self.assertEqual(len(self.calls),3)

    def test_control_final_persistence_expiry_latches_before_evidence_query(self):
        c=self.coordinator();c.value['product']=PRODUCT;c.value['controllerSHA256']='d'*64
        c.value['contact']={'identity':{'token':'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'}}
        (m.ROOT/'control.json').write_text('{}')
        real=c.persist
        def delayed():
            real()
            if c.value['status']=='routes-completed':self.clock.value=192.1
        c.persist=delayed
        with patch.object(m,'product_identity',return_value=PRODUCT),patch.object(m,'validate_control',return_value={'controlled':'fixture'}),patch.object(c,'invoke',return_value=subprocess.CompletedProcess([],0,b'',b'')):
            with self.assertRaisesRegex(ValueError,'control-final-persistence-late'):c.control()
        self.assertTrue(m.LATCH.exists());self.assertTrue(c.stopped)
        self.assertEqual(c.value['status'],'incomplete')

    def test_final_evidence_write_cannot_turn_lateness_into_durable_success(self):
        c=self.coordinator();c.stop('existing-test-unknown')
        real=m.durable;writes=[]
        def delayed(path,value,**kwargs):
            real(path,value,**kwargs);writes.append(path)
            if path==m.REPORT and len([p for p in writes if p==m.REPORT])==1:self.clock.value=280.1
        with patch.object(m,'durable',side_effect=delayed):
            with self.assertRaisesRegex(ValueError,'evidence-final-persistence-late'):
                m.final_evidence(c.budget,SOURCE,runner=lambda *a,**k:self.fail('no query'),clock=self.clock)
        report=json.loads(m.REPORT.read_text())
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['reason'],'evidence-final-persistence-late')
        self.assertGreaterEqual(report['elapsedSeconds'],180)
        with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_failed_evidence_step_cannot_validate_or_upload_a_stale_report(self):
        workflow=(ROOT/'.github/workflows/mac-launch-comparison.yml').read_text()
        evidence=workflow.split('      - name: Retain bounded host-only evidence\n',1)[1].split('      - name:',1)[0]
        validation=workflow.split('      - name: Validate distinct observation packet\n',1)[1].split('      - name:',1)[0]
        self.assertIn('id: evidence',evidence)
        self.assertIn("steps.evidence.outcome == 'success'",validation)
        self.assertIn("steps.validation.outcome == 'success'",workflow)


class ObservationTests(unittest.TestCase):
    def projected(self,events):
        identity=m.validate_control(m.encode(control()),m.encode(request()),SOURCE,PRODUCT,'d'*64)
        rows=[]
        for value in events:
            value=copy.deepcopy(value);value.update(pid=346,token=TOKEN,epoch=201+value['elapsed'])
            rows.append(dict(processID=346,processImagePath=PRODUCT['executable'],eventMessage=m.passive.PREFIX+json.dumps(value)))
        return m.passive.project(m.encode(rows),[identity])[0]

    def test_silence_missing_header_and_late_are_unknown(self):
        row=self.projected([]);self.assertEqual(m.observation(row),'unknown')
        value=event(event='final',sequence=2,elapsed=11.,late=True);value.pop('app');value.pop('product')
        row=self.projected([value]);self.assertEqual(m.observation(row),'unknown')
        self.assertEqual(row['sequence_gaps'],[1])

    def test_two_timely_zero_censuses_with_complete_stream_only(self):
        app=dict(present=True,running=True,active=True,hidden=False,policy=0,count=0,omitted=0,key=None,main=None,windows=[])
        values=[event(app=app)]
        for i,name,elapsed in [(2,'census',1),(3,'census',5),(4,'final',9)]:
            value=event(event=name,sequence=i,elapsed=elapsed,app=app);value.pop('product');values.append(value)
        self.assertEqual(m.observation(self.projected(values)),'zero-windows-at-retained-censuses')
        values[-2]['omittedRecords']=1
        self.assertEqual(m.observation(self.projected(values)),'unknown')
        values=values[1:]
        self.assertEqual(m.observation(self.projected(values)),'unknown')

    def test_positive_window_is_positive_without_filling_missing_records(self):
        window=dict(id=1,number=5,frame=[0,0,960,640],visible=True,miniaturized=False,key=True,main=True,occlusion=2,
            restorable=True,restorationClass=False,autosaveName=True,sheet=False,workspace=True)
        app=dict(present=True,running=True,active=True,hidden=False,policy=0,count=1,omitted=0,key=1,main=1,windows=[window])
        row=self.projected([event(app=app)])
        self.assertEqual(m.observation(row),'visible-workspace-observed');self.assertFalse(row['final_observed'])


class PacketTests(unittest.TestCase):
    setUp=DeadlineTests.setUp
    tearDown=DeadlineTests.tearDown
    coordinator=DeadlineTests.coordinator
    # Exercise a complete synthetic packet without invoking any native API.
    def fixture(self):
        (Path('source.txt')).write_text('fixed fixture source')
        c=self.coordinator();c.value['sourceFiles']={'source.txt':m.digest(b'fixed fixture source')}
        c.value['product']=PRODUCT;c.value['caller']=caller();c.value['controllerSHA256']='d'*64
        c.value['toolchain']={'xcode':'Xcode 27.0\nBuild version 27A266a','macOS':'27.0','build':'26A428','architecture':'arm64'}
        caller_raw=m.encode(caller());(m.ROOT/'caller.json').write_bytes(caller_raw)
        summary_file=contact_export(m.ROOT);summary=(m.ROOT/'mac-ui-summary.json').read_bytes()
        labels=['source-head','source-clean','system-build','architecture','toolchain','build-for-testing','compile-controller','inspect-caller']
        for label in labels:c.invoke(label,[label],20,minimum=1,deadline=c.preparation_deadline)
        c.value['commands'][7]['stdoutBytes']=len(caller_raw);c.value['commands'][7]['stdoutSHA256']=m.digest(caller_raw)
        c.value['phase']='xctest';c.invoke('single-contact-test',m.test_command(),300)
        c.value['commands'][8].update(exit=65,startedEpoch=98.,finishedEpoch=121.)
        c.value['contactCommandExit']=65;c.value['phase']='intermediate-host-evidence'
        c.invoke('contact-summary',['summary'],20,deadline=self.clock()+80)
        c.value['commands'][9]['stdoutBytes']=len(summary);c.value['commands'][9]['stdoutSHA256']=m.digest(summary)
        c.invoke('contact-attachments',['export'],20,deadline=self.clock()+40)
        c.value['contact']=m.validate_contact(m.ROOT,PRODUCT,65)
        c.value['phase']='nsworkspace';self.clock.value=199.9
        c.budget.admit('ordinary-launch-controller',92,minimum=92,cleanup=20)
        def run(argv,**kwargs):
            self.clock.value=214.2
            return subprocess.CompletedProcess(argv,0,b'',b'')
        c.runner=run;c.invoke('ordinary-launch-controller',['controller'],92,minimum=.001,deadline=312.)
        # Receipt and command share the request's fixed deadline.
        c.value['commands'][-1]['deadlineMonotonic']=292.
        c.value['commands'][-1]['cleanupDeadlineMonotonic']=312.
        c.value['commands'][-1]['startedMonotonic']=200.
        c.value['commands'][-1]['requestedSeconds']=92.
        (m.ROOT/'request.json').write_bytes(m.encode(request()));(m.ROOT/'control.json').write_bytes(m.encode(control()))
        c.value['control']=m.validate_control(m.encode(control()),m.encode(request()),SOURCE,PRODUCT,'d'*64)
        c.value.update(status='routes-completed',reason='awaiting-passive-evidence');c.persist()
        def query(argv,**kwargs):
            self.clock.advance(.1);return subprocess.CompletedProcess(argv,0,b'[]',b'')
        report=m.final_evidence(c.budget,SOURCE,runner=query,clock=self.clock)
        return c,report

    def test_full_packet_reconstructs_both_routes_and_silent_unknowns(self):
        with patch.object(m,'SOURCES',('source.txt',)):
            c,report=self.fixture();checked=m.validate_packet(m.EVIDENCE,SOURCE)
            self.assertEqual(checked['status'],'observation-only')
            self.assertEqual(checked['contactOutcome'],'failed')
            self.assertEqual(checked['observations'],{'XCTest':'unknown','NSWorkspace':'unknown'})
            self.assertNotIn('case',checked['records'][1]['identity'])

    def test_raw_capture_hash_and_projected_observation_tampering_fail(self):
        with patch.object(m,'SOURCES',('source.txt',)):
            self.fixture();path=m.EVIDENCE/'lifecycle-query.json';path.write_bytes(b'[ ]')
            with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
            path.write_bytes(b'[]')
            report=json.loads(m.REPORT.read_text());report['observations']['NSWorkspace']='zero-windows-at-retained-censuses';m.REPORT.write_bytes(m.encode(report))
            with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_phase_source_and_command_mutation_are_rejected_even_with_updated_file_hash(self):
        with patch.object(m,'SOURCES',('source.txt',)):
            self.fixture();original=(m.EVIDENCE/'state.json').read_bytes();report_original=m.REPORT.read_bytes()
            for mutation in [lambda s:s['commands'][8].update(phase='preparation'),
                lambda s:s['commands'][8].update(requestedSeconds=299),
                lambda s:s['commands'][11].update(cleanupDeadlineMonotonic=300),
                lambda s:s['sourceFiles'].update({'source.txt':'a'*64}),
                lambda s:s['commands'][8].update(finishedEpoch=110.),
                lambda s:s['commands'][9].update(stdoutSHA256='a'*64),
                lambda s:s['admissions'][-2].update(minimum_seconds=1)]:
                value=json.loads(original);mutation(value);raw=m.encode(value);(m.EVIDENCE/'state.json').write_bytes(raw)
                report=json.loads(report_original);report['files']['state.json']={'bytes':len(raw),'sha256':m.digest(raw)};m.REPORT.write_bytes(m.encode(report))
                with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)



class SourceTests(unittest.TestCase):
    def test_exact_single_case_and_unchanged_canonical_collectors(self):
        command=m.test_command();self.assertEqual([x for x in command if x.startswith('-only-testing:')],['-only-testing:'+m.METHOD])
        self.assertEqual(command[-1],'test-without-building');self.assertIn('platform=macOS,arch=arm64',command)
        self.assertEqual(command[command.index('-maximum-test-execution-time-allowance')+1],'120')
        self.assertEqual(command[command.index('-parallel-testing-enabled')+1],'NO')
        for forbidden in ('retry','repetition','skip-testing','test-iterations'):self.assertNotIn(forbidden,' '.join(command))
        self.assertEqual(len(m.passive.CASES),4);self.assertNotIn('NSWorkspace',m.passive.CASES)

    def test_swift_fences_public_defaults_and_no_recovery_routes(self):
        text=(ROOT/'scripts/MacLaunchComparison.swift').read_text()
        self.assertEqual(text.count('NSWorkspace.shared.openApplication('),1)
        self.assertEqual(text.count('app.terminate()'),1)
        for forbidden in ('forceTerminate','activate(', 'AXUIElement','screenshot','removePersistentDomain','ProcessInfo.processInfo.environment','UserDefaults('):self.assertNotIn(forbidden,text)
        self.assertIn('configuration.allowsRunningApplicationSubstitution = false',text)
        self.assertIn('configuration.promptsUserIfNeeded = false',text)
        self.assertIn('configuration.activates && !configuration.hides && !configuration.createsNewApplicationInstance',text)
        self.assertIn('DispatchQueue.main.async { [weak self]',text)
        callback=text.split('private func completed(',1)[1].split('private func terminateOwned',1)[0]
        self.assertLess(callback.index('guard live("callback"'),callback.index('try verify(app,'))
        failure=text.split('private func fail(',1)[1].split('private func live(',1)[0]
        for forbidden in ('NSRunningApplication.','owned.','terminate()','NSWorkspace.'):self.assertNotIn(forbidden,failure)
        self.assertLess(failure.index('try atomic(fence'),failure.index('try? persist'))
        self.assertIn('SecCSFlags(rawValue: kSecCSSigningInformation | kSecCSRequirementInformation)',text)
        self.assertIn('dictionary == nil && blob == nil',text)
        self.assertIn('let entitlements = dictionary as? [String: Any]',text)
        self.assertIn('let data = blob as? Data, !data.isEmpty',text)
        self.assertNotIn('codesign --',text)
        poll=text.split('private func pollTermination()',1)[1]
        self.assertIn('let terminated = app.isTerminated\n        guard live("terminating", until: terminationDeadline)',poll)
        self.assertIn('let accepted = app.terminate()\n            guard live("terminating", until: terminationDeadline)',text)

    def test_separate_workflow_identity_and_no_schedule_or_dispatch(self):
        text=(ROOT/m.WORKFLOW).read_text()
        self.assertIn('branches: [codex/mac-launch-comparison]',text)
        self.assertIn('timeout-minutes: 25',text);self.assertIn('runs-on: xcode-27',text)
        self.assertNotIn('workflow_dispatch',text);self.assertNotIn('schedule:',text)
        self.assertNotIn('mac_passive_lifecycle.py',text);self.assertNotIn('validate_evidence.py',text)
        self.assertIn('contents: read',text);self.assertIn('persist-credentials: false',text)
        self.assertLess(text.index('uses: actions/upload-artifact@'),text.index('mac_launch_comparison.py contact-result'))
        self.assertEqual(m.RESERVES,dict(cleanup=130,evidence=180,validation=60,upload=60,overhead=20))


if __name__=='__main__':unittest.main()
