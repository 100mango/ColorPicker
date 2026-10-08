"""No Apple execution: failure and coordination checks for the real-pair harness."""
import json
import hashlib
import copy
import collections
import io
import queue
import threading
import time
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_paired_watch as harness
from paired_product_diagnostics import CommandResult
# Existing workflow module suites also execute the new helper's negative cases.
from test_paired_product_diagnostics import ProductDiagnosticsTests, RegistrationTests, BoundedInspectionTests


class PairedHarnessTests(unittest.TestCase):
    def setUp(self):
        harness.report.clear()
        harness.report.update(result='passed', stages=[], receipt_barrier='acknowledged')

    def observation(self, role='watch', phase='pre-send'):
        value = {'schema':'2','role':role,'source':'public-WCSession','event':'activation-completed',
                 'sequence':'2','supported':'true','sessionPresent':'true','activationState':'2',
                 'activationCallbackState':'2','activationErrorDomain':'','activationErrorCode':'',
                 'reachable':'true','selectedTransport':'none','runID':'synthetic-run','phase':phase,
                 'sampleEpoch':'12345678-1234-1234-1234-123456789ABC','sampleUptimeMilliseconds':'1000',
                 'explicitSampleSequence':'1','latestDelegateEvent':'activation-completed','delegateSequence':'1',
                 'samplingFreshness':'newly-observed'}
        value.update({'companionInstalled':'true'} if role == 'watch' else {'paired':'true','watchInstalled':'true'})
        return value

    def process(self, role):
        start = self.observation(role, 'bootstrap' if role == 'phone' else 'pre-send')
        receipt = {**start, 'phase':'receipt','event':'sendMessage','selectedTransport':'sendMessage'}
        return SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_'+role.upper()+'_RELAUNCH_VERIFIED'], cleanup_confirmed=True,
                               readiness=[start, receipt], readiness_errors=0, readiness_overflow=False, sample_incomplete=[])

    def test_job_budget_expiry_retains_not_started_paired_command(self):
        from job_budget import BudgetExhausted
        with patch.object(harness,'run_captured',side_effect=BudgetExhausted('synthetic work reserve exhausted')),patch.object(harness,'save_report'):
            with self.assertRaises(RuntimeError):harness.run(['synthetic'],60)
        self.assertFalse(harness.report['budget_incomplete']['started'])
        self.assertEqual(harness.report['stages'][-1]['exit'],124)
        self.assertFalse(harness.report.get('cleanup_unconfirmed',False))

    def test_failure_diagnostic_is_specific_and_bounded(self):
        text='unrelated output\n/owned/PhonePairedTransferTests.swift:90: error: test: expected enabled\n'
        text += "Test Case 'case' failed (1 seconds).\n"
        self.assertEqual(len(harness.bounded_failure_lines(text)),2)
        self.assertNotIn('unrelated',str(harness.bounded_failure_lines(text)))
        large=('file.swift:1: error: '+('x'*5000)+'\n')*100
        values=harness.bounded_failure_lines(large)
        self.assertLessEqual(len(values),8);self.assertLessEqual(sum(map(len,values)),8000)

    def test_failed_exit_missing_marker_and_unclean_group_reject(self):
        phone, watch = self.process('phone'), self.process('watch')
        harness.validate_outcome(phone, watch, 0, 0)
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 65, 0)
        phone.markers=[]
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 0, 0)
        phone.markers=['TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED']; watch.cleanup_confirmed=False
        with self.assertRaises(RuntimeError): harness.validate_outcome(phone, watch, 0, 0)

    def test_cleanup_failures_cannot_retain_passed_result(self):
        with patch.object(harness, 'run', side_effect=RuntimeError('synthetic owned delete failure')):
            self.assertFalse(harness.cleanup({}, [], None, {}, {}, {}, []))
        self.assertEqual(harness.report['result'],'failed')

    def test_original_pair_cannot_be_activated_or_cleaned_as_owned(self):
        # verify_pair is required before activation and again before unpair.
        with self.assertRaises(ValueError):
            harness.verify_pair({'pairs':{'old':{'phone':{'udid':'p'},'watch':{'udid':'w'}}}},'old','w','p',{'old':{}})

    def test_generated_target_environment_is_exact_and_linked(self):
        with tempfile.TemporaryDirectory() as folder:
            product=Path(folder)/'Build/Products'; product.mkdir(parents=True)
            path=product/'observed.xctestrun'
            path.write_bytes(plistlib.dumps({'UITests':{'TestBundlePath':'__TESTROOT__/TouchColorUITests.xctest','TestHostPath':'__TESTROOT__/Runner.app','UITargetAppPath':'__TESTROOT__/Debug-iphonesimulator/TouchColor.app','IsUITestBundle':True}}))
            out=harness.configured_test_run(folder,'phone','synthetic-run')
            actual=plistlib.loads(out.read_bytes())['UITests']
            self.assertEqual(actual['EnvironmentVariables'],{'TOUCHCOLOR_PAIRED_E2E':'1','TOUCHCOLOR_PAIRED_RUN_ID':'synthetic-run'})
            self.assertEqual(actual['UITargetAppPath'],'__TESTROOT__/Debug-iphonesimulator/TouchColor.app')
            path.write_bytes(plistlib.dumps({'wrong':{'TestBundlePath':'Other.xctest'}}))
            with self.assertRaises(RuntimeError): harness.configured_test_run(folder,'phone','synthetic-run')

    def test_receipts_must_match_payload_protocol_uuid_and_foreground_channel(self):
        identifier='12345678-1234-1234-1234-123456789ABC'
        digest=hashlib.sha256(json.dumps({'version':1,'id':identifier,'colors':['#fe0000']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        values={role:{'role':role,'runID':'run','requestID':identifier,'requestProtocol':'touchColorPaletteV1','receiptProtocol':'touchColorReceiptV1','version':'1','outcome':'accepted','receiveChannel':'sendMessage','fingerprint':digest} for role in ('phone','watch')}
        self.assertEqual(harness.validate_receipt_observations(values,'run'),(identifier,digest))
        for key,bad in [('requestID','other'),('requestProtocol','other'),('receiptProtocol','other'),('version','2'),('outcome','rejected'),('receiveChannel','transferUserInfo'),('fingerprint','0'*64)]:
            changed=copy.deepcopy(values);changed['watch'][key]=bad
            with self.assertRaises(RuntimeError,msg=key):harness.validate_receipt_observations(changed,'run')
        changed=copy.deepcopy(values)
        for value in changed.values():value['fingerprint']='0'*64
        with self.assertRaises(RuntimeError):harness.validate_receipt_observations(changed,'run')

    def test_installed_record_includes_debug_dylib_not_only_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)/'TouchColor.app';app.mkdir()
            (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.mango.touchColor.watchkitapp','CFBundleExecutable':'TouchColor','CFBundleShortVersionString':'2.0','CFBundleVersion':'20001','CFBundleSupportedPlatforms':['WatchSimulator'],'WKCompanionAppBundleIdentifier':'com.mango.touchColor'}))
            (app/'TouchColor').write_bytes(b'fixed launcher');(app/'TouchColor.debug.dylib').write_bytes(b'first actual implementation')
            before=harness.product_record(app,'watch')
            (app/'TouchColor.debug.dylib').write_bytes(b'changed actual implementation')
            self.assertNotEqual(before,harness.product_record(app,'watch'))

    def test_both_owned_devices_boot_before_unchanged_bounded_installs(self):
        calls=[]; selected={'phone':'p','watch':'w'}; booted=[]
        inventory={'runtime':[{'udid':'p','state':'Booted'},{'udid':'w','state':'Booted'}]}
        with patch.object(harness,'run',side_effect=lambda command,timeout:calls.append((command,timeout))), \
             patch.object(harness,'resources'), patch.object(harness,'runtime_inventory',return_value=inventory):
            harness.prepare_owned_pair(selected,booted,{}, {},'pair')
        self.assertEqual([row[0][2] for row in calls],['boot','bootstatus','boot','bootstatus','install','install'])
        self.assertEqual(booted,['p','w'])
        self.assertEqual([row[1] for row in calls[-2:]],[120,120])
        self.assertEqual(calls[-2][0][3],'p'); self.assertEqual(calls[-1][0][3],'w')

    def test_failed_watch_boot_or_wrong_booted_inventory_prevents_install(self):
        for failure in ('watch boot','extra device'):
            calls=[]
            def run(command,timeout):
                calls.append(command)
                if failure=='watch boot' and command[2:4]==['boot','w']: raise RuntimeError('synthetic boot failure')
            inventory={'r':[{'udid':x,'state':'Booted'} for x in ('p','w','unowned')]}
            with patch.object(harness,'run',side_effect=run),patch.object(harness,'resources'),patch.object(harness,'runtime_inventory',return_value=inventory):
                with self.assertRaises(RuntimeError):harness.prepare_owned_pair({'phone':'p','watch':'w'},[],{},{},'pair')
            self.assertFalse(any(command[2]=='install' for command in calls))

    def test_unknown_resource_cleanup_latches_before_any_device_command(self):
        with patch.object(harness,'resource_snapshot',return_value={'cleanup_unconfirmed':True}),patch.object(harness,'save_report'),patch.object(harness,'run') as run:
            with self.assertRaises(RuntimeError):harness.prepare_owned_pair({'phone':'p','watch':'w'},[],{},{},'pair')
            run.assert_not_called()
        self.assertTrue(harness.report['cleanup_unconfirmed'])
        with patch.object(harness,'resource_snapshot') as sample:
            with self.assertRaises(RuntimeError):harness.resources('must stop')
            sample.assert_not_called()

    def test_product_size_is_bounded_and_never_follows_external_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=root/'TouchColor.app';app.mkdir()
            (app/'payload').write_bytes(b'12345');outside=root/'outside';outside.mkdir();(outside/'large').write_bytes(b'x'*100)
            (app/'external').symlink_to(outside,target_is_directory=True)
            value=harness.product_size(app)
            self.assertEqual(value['bytes_observed'],5);self.assertEqual(value['files_observed'],1);self.assertFalse(value['partial'])
            self.assertTrue(harness.product_size(app,maximum_entries=1)['partial'])
            self.assertTrue(harness.product_size(app,maximum_seconds=0)['partial'])

    def test_actual_summary_requires_one_non_skipped_case_on_the_owned_destination(self):
        counts={'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}
        row={**counts,'device':{'deviceId':'owned','platform':'watchOS Simulator','osVersion':'27.0','architecture':'arm64'}}
        value={**counts,'result':'Passed','totalTestCount':1,'devicesAndConfigurations':[row],'testFailures':[]}
        self.assertEqual(harness.verify_result_summary(value,'owned','watch')['totalTestCount'],1)
        for key,bad in [('totalTestCount',0),('skippedTests',1),('expectedFailures',1),('passedTests',2),('result','Skipped')]:
            changed=copy.deepcopy(value);changed[key]=bad
            with self.assertRaises(RuntimeError,msg=key):harness.verify_result_summary(changed,'owned','watch')
        changed=copy.deepcopy(value);changed['devicesAndConfigurations'][0]['device']['deviceId']='clone'
        with self.assertRaises(RuntimeError):harness.verify_result_summary(changed,'owned','watch')

    def test_readiness_exact_schema_correlation_and_inactive_unknowns(self):
        for role in ('phone', 'watch'):
            value = self.observation(role)
            self.assertEqual(harness.decode_readiness(json.dumps(value), role, 'synthetic-run'), value)
            absent = {**value, 'event':'initialized', 'sessionPresent':'false','activationState':'absent','activationCallbackState':'','reachable':'unknown'}
            for key in ('companionInstalled', 'paired', 'watchInstalled'):
                if key in absent: absent[key] = 'unknown'
            self.assertEqual(harness.decode_readiness(json.dumps(absent), role, 'synthetic-run'), absent)
            for key,bad in [('schema','1'),('role','different'),('runID','other'),('source','mock'),
                            ('supported','yes'),('activationState','3'),('phase','invented'),('event','invented'),
                            ('sequence','1000001'),('activationErrorDomain','x'*129),('selectedTransport','injected')]:
                with self.assertRaises(RuntimeError,msg=key):
                    harness.decode_readiness(json.dumps({**value,key:bad}), role, 'synthetic-run')
            with self.assertRaises(RuntimeError): harness.decode_readiness(json.dumps({**value,'extra':'data'}),role,'synthetic-run')
            with self.assertRaises(RuntimeError): harness.decode_readiness(json.dumps({**absent,'reachable':'false'}),role,'synthetic-run')
        with self.assertRaises(RuntimeError): harness.decode_readiness(' '*2049,'watch','synthetic-run')
        with self.assertRaises(RuntimeError): harness.decode_readiness('[]','watch','synthetic-run')
        with self.assertRaises(ValueError): harness.decode_readiness('not JSON','watch','synthetic-run')

    def test_readiness_distinguishes_absence_activation_install_reachability_and_error(self):
        ready = self.observation()
        self.assertTrue(harness.watch_foreground_ready(ready))
        self.assertEqual(harness.decode_readiness(json.dumps({**ready,'event':'initialized'}),'watch','synthetic-run')['event'],'initialized')
        for key,bad in [('sessionPresent','false'),('supported','false'),('activationState','0'),
                        ('activationCallbackState',''),('companionInstalled','false'),('reachable','false'),
                        ('activationErrorDomain','WCErrorDomain'),('activationErrorCode','7004')]:
            self.assertFalse(harness.watch_foreground_ready({**ready,key:bad}),key)
        failed_activation = {**ready,'activationState':'0','activationCallbackState':'0',
                             'companionInstalled':'unknown','reachable':'unknown',
                             'activationErrorDomain':'WCErrorDomain','activationErrorCode':'7004'}
        actual = harness.decode_readiness(json.dumps(failed_activation),'watch','synthetic-run')
        self.assertEqual(actual['activationErrorCode'],'7004')
        self.assertFalse(harness.watch_foreground_ready(actual))

    def test_readiness_alone_never_substitutes_for_receipts_foreground_or_success(self):
        for change in ('no receipt','background','no gate','invalid','overflow'):
            phone,watch = self.process('phone'),self.process('watch')
            if change == 'no receipt': watch.readiness = watch.readiness[:1]
            elif change == 'background': watch.readiness[-1]['selectedTransport'] = 'transferUserInfo'
            elif change == 'no gate': watch.readiness = watch.readiness[1:]
            elif change == 'invalid': watch.readiness_errors = 1
            elif change == 'overflow': watch.readiness_overflow = True
            with self.assertRaises(RuntimeError,msg=change): harness.validate_readiness_evidence(phone,watch)
        with self.assertRaises(RuntimeError): harness.validate_outcome(self.process('phone'),self.process('watch'),0,65)
        harness.report['receipt_barrier'] = None
        with self.assertRaises(RuntimeError): harness.validate_outcome(self.process('phone'),self.process('watch'),0,0)

    def test_reader_bounds_observations_retains_last_and_reports_invalid(self):
        process = object.__new__(harness.RunningTests)
        process.label = 'watch'; process.run_id = 'synthetic-run'
        process.readiness = []; process.readiness_errors = 0; process.readiness_overflow = False; process.sample_incomplete = []
        process.tail = collections.deque(maxlen=1000); process.lock = threading.Lock()
        process.markers = []; process.ready = threading.Event(); process.barriers = queue.Queue()
        lines = [harness.READINESS_PREFIX + json.dumps({**self.observation(),'sequence':str(i+1)}) + '\n' for i in range(70)]
        lines += [harness.READINESS_PREFIX + '{}\n', harness.READINESS_PREFIX + 'bad JSON\n']
        process.process = SimpleNamespace(stdout=io.StringIO(''.join(lines)),wait=lambda timeout:65)
        with patch('builtins.print'): process.read()
        self.assertEqual(len(process.readiness),64)
        self.assertEqual(process.readiness[0]['sequence'],'1')
        self.assertEqual(process.readiness[-1]['sequence'],'70')
        self.assertEqual(process.readiness_errors,2); self.assertTrue(process.readiness_overflow)
        process.readiness_overflow = False
        marker = harness.READINESS_OVERFLOW_PREFIX + json.dumps({'role':'watch','runID':'synthetic-run'}) + '\n'
        process.process.stdout = io.StringIO(marker)
        with patch('builtins.print'): process.read()
        self.assertTrue(process.readiness_overflow)
        process.process.stdout = io.StringIO(marker.replace('synthetic-run','other-run'))
        with patch('builtins.print'): process.read()
        self.assertEqual(process.readiness_errors,3)
        process.process.stdout = io.StringIO(marker.replace('"watch"','"phone"'))
        with patch('builtins.print'): process.read()
        self.assertEqual(process.readiness_errors,4)
        process.process.stdout = io.StringIO(marker*200)
        with patch('builtins.print'): process.read()
        self.assertEqual(process.readiness_errors,4)
        self.assertEqual(len(process.readiness),64)
        self.assertEqual(process.markers,[])
        process.cleanup_confirmed = True; process.started = time.monotonic(); process.wall_started = time.time()
        process.reader = SimpleNamespace(join=lambda timeout:None)
        with tempfile.TemporaryDirectory() as directory, patch.object(harness,'OUT',Path(directory)):
            self.assertEqual(process.finish(1),65)
        self.assertEqual(harness.report['watch']['readiness'],process.readiness)
        self.assertEqual(harness.report['watch']['readiness_errors'],4)
        self.assertTrue(harness.report['watch']['readiness_overflow'])
        self.assertLess(len(json.dumps(process.readiness).encode()),64*2048)

    def test_swift_gate_stays_before_send_and_inside_original_observation_budget(self):
        root = Path(__file__).resolve().parents[1]
        watch = (root/'TouchColorPhoneCompanion/PairedTests/WatchPairedTransferTests.swift').read_text()
        self.assertIn('let transportDeadline = ProcessInfo.processInfo.systemUptime + 60',watch)
        self.assertIn('let readinessDeadline = ProcessInfo.processInfo.systemUptime + 20',watch)
        self.assertLess(watch.index('requestFreshSample(refresh'),watch.index('send.tap()'))
        self.assertLess(watch.index('guard readinessResult == .completed else { return }'),watch.index('send.tap()'))
        self.assertIn('confirmsFreshSample(value, after: request)',watch)
        self.assertIn('timeout: min(20, remaining)',watch)
        phone = (root/'TouchColorPhoneCompanion/PairedTests/PhonePairedTransferTests.swift').read_text()
        self.assertIn('timeout: 120',phone)
        self.assertLess(phone.index('healthyInbox(receipts: 0)'),phone.index('TOUCHCOLOR_PAIRED_PHONE_READY'))
        harness_source = (root/'scripts/test_paired_watch.py').read_text()
        self.assertIn("'-maximum-test-execution-time-allowance','240'",harness_source)
        self.assertIn('run_id, timeout=150',harness_source)
        common = (root/'TouchColorPhoneCompanion/PairedTests/PairedReceiptBarrier.swift').read_text()
        self.assertIn('var value = observation.filter { receiptKeys.contains($0.key) }',common)
        self.assertNotIn('"connection"',common.split('let receiptKeys = Set(',1)[1].split(')',1)[0])
        for key in ('requestID','requestProtocol','receiptProtocol','version','fingerprint','outcome','receiveChannel'):
            self.assertIn('"'+key+'"',common.split('let receiptKeys = Set(',1)[1].split(')',1)[0])

    def test_fresh_schema_labels_and_explicit_sampling_are_required(self):
        value=self.observation()
        for key,bad in [('sampleEpoch','not-a-uuid'),('sampleUptimeMilliseconds','nan'),
                        ('explicitSampleSequence','-1'),('delegateSequence','1000001'),
                        ('latestDelegateEvent','sendMessage'),('samplingFreshness','fresh-by-assumption')]:
            with self.assertRaises((RuntimeError,ValueError),msg=key):
                harness.decode_readiness(json.dumps({**value,key:bad}),'watch','synthetic-run')
        for role in ('phone','watch'):
            phone,watch=self.process('phone'),self.process('watch')
            (phone if role=='phone' else watch).readiness[0]['explicitSampleSequence']='0'
            with self.assertRaises(RuntimeError):harness.validate_readiness_evidence(phone,watch)
        common=(Path(__file__).resolve().parents[1]/'TouchColorPhoneCompanion/PairedTests/PairedReceiptBarrier.swift').read_text()
        self.assertIn('value["sampleEpoch"] == request.epoch',common)
        self.assertIn('return count > request.previousExplicitSequence',common)
        self.assertGreaterEqual(common.count('ProcessInfo.processInfo.systemUptime < deadline'),2)
        self.assertIn('"repeated" : "newly-observed"',common)

    def stopped_processes(self, clean=True):
        values={}
        for role in ('phone','watch'):
            process=SimpleNamespace(label=role,cleanup_confirmed=None)
            def stop(process=process):
                process.cleanup_confirmed=clean;return clean
            process.stop=stop
            process.finish=lambda timeout,role=role:harness.report.setdefault(role,{'exit':65})
            values[role]=process
        return values

    def selected_pair(self):
        return {'phone':'12345678-1234-1234-1234-123456789ABC','watch':'ABCDEF12-1234-1234-1234-123456789ABC'}

    def test_post_diagnostics_refuse_unknown_cleanup_missing_or_wrong_phase_budget(self):
        for mode in ('unclean','missing','cleanup-phase','exhausted'):
            harness.report.clear();harness.report.update(result='failed',error='original assertion')
            processes=self.stopped_processes(clean=mode!='unclean')
            budget=None if mode=='missing' else SimpleNamespace(phase='cleanup' if mode=='cleanup-phase' else 'work',admit=lambda *a,**k:300)
            if mode=='exhausted':budget.admit=lambda *a,**k:(_ for _ in ()).throw(harness.BudgetExhausted('synthetic'))
            with patch.object(harness,'enabled_budget',return_value=budget),patch.object(harness,'diagnostic_execute') as execute,patch.object(harness,'identity_receipt') as identity:
                harness.post_xctest_diagnostics(processes,self.selected_pair())
            execute.assert_not_called();identity.assert_not_called()
            self.assertEqual(harness.report['result'],'failed');self.assertEqual(harness.report['error'],'original assertion')
            self.assertEqual(harness.report['post_xctest_diagnostics']['status'],'incomplete')

    def test_post_diagnostics_stop_both_groups_before_owned_reads_and_preserve_failure(self):
        harness.report.update(result='failed',error='original assertion')
        processes=self.stopped_processes();selected=self.selected_pair();calls=[]
        budget=SimpleNamespace(phase='work',admit=lambda *a,**k:calls.append(('admit',a,k)))
        def execute(command,**kwargs):
            self.assertTrue(all(p.cleanup_confirmed is True for p in processes.values()))
            self.assertEqual(command[:3],['xcrun','simctl','get_app_container'])
            self.assertEqual(command[-1],'app');self.assertIn(command[3],selected.values())
            calls.append(('execute',command))
            return CommandResult(0,('/owned/'+command[3]+'/TouchColor.app\n').encode(),True)
        with patch.object(harness,'enabled_budget',return_value=budget),patch.object(harness,'diagnostic_execute',side_effect=execute), \
             patch.object(harness,'identity_receipt',return_value={'status':'observed'}) as identity, \
             patch.object(harness,'collect_registration_receipt',return_value={'status':'observed'}) as registration:
            harness.post_xctest_diagnostics(processes,selected)
        self.assertEqual(calls[0][0],'admit');self.assertEqual(calls[0][1][1],300)
        self.assertEqual(calls[0][2],{'minimum':300,'cleanup':0,'phase':'work'})
        self.assertEqual(len([x for x in calls if x[0]=='execute']),2)
        self.assertEqual(set(identity.call_args.args[0]),{'phone','watch'})
        self.assertEqual(registration.call_count,2)
        self.assertEqual(harness.report['post_xctest_diagnostics']['status'],'observed')
        self.assertEqual(harness.report['result'],'failed');self.assertEqual(harness.report['error'],'original assertion')

    def test_post_lifecycle_reaches_real_capability_helper_with_supported_bound(self):
        processes=self.stopped_processes();selected=self.selected_pair();calls=[]
        harness.report.update(result='failed',error='original readiness assertion')
        budget=SimpleNamespace(phase='work',admit=lambda *a,**k:300)
        def inspect(command,timeout,max_output_bytes):
            self.assertTrue(all(p.cleanup_confirmed is True for p in processes.values()))
            self.assertEqual(timeout,10);calls.append(command)
            if command[2]=='get_app_container':
                body=('/owned/'+command[3]+'/TouchColor.app\n').encode()
            elif command==['xcrun','simctl','help']:body=RegistrationTests.help
            elif command==['xcrun','simctl','help','appinfo']:body=RegistrationTests.usage
            else:
                self.assertEqual(command[2],'appinfo')
                body=json.dumps({'CFBundleIdentifier':command[4],'DataContainer':'DO_NOT_RETAIN'}).encode()
            return CommandResult(0,body,True)
        with patch.object(harness,'enabled_budget',return_value=budget),patch.object(harness,'run_inspection',side_effect=inspect), \
             patch.object(harness,'identity_receipt',return_value={'status':'observed'}):
            harness.post_xctest_diagnostics(processes,selected)
        receipt=harness.report['post_xctest_diagnostics']
        self.assertEqual(receipt['status'],'observed')
        self.assertEqual(len(calls),8);self.assertEqual(len(harness.report['inspection_commands']),8)
        for role in ('phone','watch'):
            self.assertTrue(receipt['registration'][role]['capability']['usageVerified'])
            self.assertEqual(receipt['registration'][role]['status'],'observed')
        self.assertNotIn('DO_NOT_RETAIN',json.dumps(harness.report))
        self.assertEqual(harness.report['error'],'original readiness assertion')

    def test_inspection_uncertain_cleanup_latches_and_forbids_next_command(self):
        budget=SimpleNamespace(phase='work',admit=lambda *a,**k:10)
        with patch.object(harness,'enabled_budget',return_value=budget),patch.object(harness,'run_inspection',return_value=CommandResult(124,b'',False,timed_out=True)) as run,patch.object(harness,'fail_record') as fail:
            harness.diagnostic_execute(['synthetic'],timeout=1,max_output_bytes=10)
            self.assertTrue(harness.report['cleanup_unconfirmed']);fail.assert_called_once()
            with self.assertRaises(RuntimeError):harness.diagnostic_execute(['synthetic'],timeout=1,max_output_bytes=10)
            self.assertEqual(run.call_count,1)
        harness.report.clear()
        error=OSError('synthetic');error.cleanup_confirmed=False
        with patch.object(harness,'enabled_budget',return_value=budget),patch.object(harness,'run_inspection',side_effect=error),patch.object(harness,'fail_record'):
            with self.assertRaises(OSError):harness.diagnostic_execute(['synthetic'],timeout=1,max_output_bytes=10)
        self.assertTrue(harness.report['cleanup_unconfirmed'])

    def test_inspection_admission_and_receipt_caps_are_not_silent(self):
        with patch.object(harness,'enabled_budget',return_value=None),patch.object(harness,'run_inspection') as run:
            with self.assertRaises(RuntimeError):harness.diagnostic_execute(['synthetic'],timeout=1,max_output_bytes=10)
        run.assert_not_called();self.assertFalse(harness.report['inspection_commands'][0]['started'])
        self.assertEqual(harness.report['inspection_commands'][0]['reason'],'work_admission_unavailable')
        self.assertEqual(harness.bounded_diagnostic_record({'oversize':'x'*70000})['status'],'incomplete')
        harness.report['inspection_commands']=[{}]*8
        with patch.object(harness,'run_inspection') as run:
            with self.assertRaises(RuntimeError):harness.diagnostic_execute(['synthetic'],timeout=1,max_output_bytes=10)
        run.assert_not_called()

    def test_incomplete_fresh_sample_markers_are_bounded_correlated_and_never_readiness(self):
        process=object.__new__(harness.RunningTests)
        process.label='watch';process.run_id='synthetic-run';process.sample_incomplete=[]
        process.readiness=[];process.readiness_errors=0;process.readiness_overflow=False
        process.tail=collections.deque(maxlen=1000);process.lock=threading.Lock()
        process.markers=[];process.ready=threading.Event();process.barriers=queue.Queue()
        value={'role':'watch','runID':'synthetic-run','phase':'pre-send','reason':'fresh-read-unconfirmed'}
        line=harness.SAMPLE_INCOMPLETE_PREFIX+json.dumps(value)+'\n'
        process.process=SimpleNamespace(stdout=io.StringIO(line*10+line.replace('synthetic-run','wrong')))
        with patch('builtins.print'):process.read()
        self.assertEqual(len(process.sample_incomplete),8);self.assertTrue(process.readiness_overflow)
        self.assertEqual(process.readiness_errors,1);self.assertEqual(process.markers,[]);self.assertEqual(process.readiness,[])

    def test_optimized_python_keeps_failed_exit_and_cleanup_gates(self):
        code='''
from types import SimpleNamespace
from unittest.mock import patch
import test_paired_watch as h
p=SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED'],cleanup_confirmed=True)
w=SimpleNamespace(markers=['TOUCHCOLOR_PAIRED_WATCH_RELAUNCH_VERIFIED'],cleanup_confirmed=True)
h.report.update(result='passed',stages=[],receipt_barrier='acknowledged')
try: h.validate_outcome(p,w,65,0)
except RuntimeError: pass
else: raise SystemExit('optimized interpreter accepted failed XCTest')
with patch.object(h,'run',side_effect=RuntimeError('owned unpair/delete failure')):
    if h.cleanup({},[],None,{},{},{},[]): raise SystemExit('accepted failed cleanup')
if h.report['result']!='failed': raise SystemExit('failed cleanup retained passed result')
try: h.require(False,'readiness missing')
except RuntimeError: pass
else: raise SystemExit('optimized interpreter removed readiness gate')
try: h.verify_result_summary({'result':'Passed','totalTestCount':0},'owned','phone')
except RuntimeError: pass
else: raise SystemExit('optimized interpreter accepted zero executed tests')
'''
        result=subprocess.run([sys.executable,'-O','-c',code],cwd=Path(__file__).parent,env={**os.environ,'PYTHONOPTIMIZE':'1'},capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__': unittest.main()
