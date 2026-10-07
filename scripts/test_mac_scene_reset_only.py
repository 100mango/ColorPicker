"""Portable reset-only control tests; no native execution or App mutation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import job_budget
import mac_scene_reset_only as m
import mac_reset_contract as contract
import mac_scene_diagnostic as original
from test_mac_launch_comparison import Clock, PRODUCT as OLD_PRODUCT, contact_export
from test_mac_passive_lifecycle import event, envelope
from test_mac_reset_source_helpers import restore_english_setup, restore_chinese_setup, RESET_SETUP, ENGLISH_SETUP
from test_mac_store_source_helpers import restore_store_app

CHECKOUT=Path(__file__).resolve().parents[1]
REFERENCE=json.loads((CHECKOUT/'scripts/fixtures/mac-d238-reset-reference.json').read_bytes())
PRODUCT={**OLD_PRODUCT,**m.REFERENCE_PRODUCT}
SOURCE=dict(repository='100mango/ColorPicker',ref=m.BRANCH,workflow=m.WORKFLOW,
    workflow_ref='100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,event='push',sha='a'*40,run='1',attempt='1',parent=m.PARENT,route='reset-only')
LOCALE={'localeIdentifier':'en_US','preferredLanguages':['en-US']}


def env():
    return dict(GITHUB_REPOSITORY=SOURCE['repository'],GITHUB_REF=m.BRANCH,GITHUB_WORKFLOW_REF=SOURCE['workflow_ref'],GITHUB_EVENT_NAME='push',
        GITHUB_SHA=SOURCE['sha'],GITHUB_WORKFLOW_SHA=SOURCE['sha'],GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',TOUCHCOLOR_JOB_PLATFORM=m.PLATFORM,
        TOUCHCOLOR_JOB_LANE=m.PLATFORM,TOUCHCOLOR_JOB_MINUTES='25',TOUCHCOLOR_EVIDENCE_LIMIT='3000000',
        TOUCHCOLOR_JOB_STARTED_EPOCH='100',TOUCHCOLOR_JOB_STARTED_MONOTONIC='100')


def hierarchy(pid=345,labels=('Sample','Save Color'),*,root_pid=None,root_title='TouchColor',outside=''):
    root_pid=pid if root_pid is None else root_pid
    rows='\n'.join("    MenuItem, 0x12, {{0, 0}, {0, 0}}, title: '"+label+"'" for label in labels)
    return ("XCTAssertTrue failed - Optional(Attributes: Application, 0x10, pid: "+str(pid)+", title: 'TouchColor', Disabled\n"
        "Element subtree:\n →Application, 0x11, pid: "+str(root_pid)+", title: '"+root_title+"', Disabled\n"+rows+
        "\nPath to element:\n →Application, 0x11, pid: "+str(pid)+", title: 'TouchColor'\nQuery chain:\n"+outside+")")


class Harness(unittest.TestCase):
    def setUp(self):
        self.old=Path.cwd();self.temp=tempfile.TemporaryDirectory();os.chdir(self.temp.name)
        Path('source.txt').write_text('bound reset-only source\n');m.ROOT.mkdir(parents=True)
        self.clock=Clock();self.calls=[];self.fault=None;self.failed=True;self.delta=None;self.locale=copy.deepcopy(LOCALE);self.actual_product=dict(PRODUCT)
        self.language_text=hierarchy()
        self.sources=patch.object(m,'SOURCES',('source.txt',));self.sources.start()
        self.product=patch.object(m,'product_identity',side_effect=lambda:self.actual_product);self.product.start()
        self.budget=job_budget.JobBudget(job_budget.create_record(env(),wall=self.clock,monotonic=self.clock),wall=self.clock,monotonic=self.clock)
        self.diagnostic=m.Diagnostic(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)

    def tearDown(self):
        self.product.stop();self.sources.stop();os.chdir(self.old);self.temp.cleanup()

    def export_contact(self):
        path=contact_export(m.ROOT,failed=self.failed);self.delta=self.clock.value+.2-99
        receipt=json.loads(path.read_bytes());receipt.update(args=['--ui-test-reset'],**{k:self.actual_product[k] for k in m.REFERENCE_PRODUCT})
        for key in ('started','captured'):receipt[key]+=self.delta
        path.write_bytes(m.encode(receipt))
        summary_path=m.ROOT/'mac-ui-summary.json';summary=json.loads(summary_path.read_bytes())
        for key in ('startTime','finishTime'):summary[key]+=self.delta
        if self.failed:summary['testFailures'][0]['failureText']=self.language_text
        summary_path.write_bytes(m.encode(summary))
        manifest=m.ROOT/'screenshots/manifest.json';groups=json.loads(manifest.read_bytes())
        for group in groups:
            for item in group['attachments']:item['timestamp']+=self.delta
        manifest.write_bytes(m.encode(groups))

    def logs(self):
        values=[event()];values[0]['product'].update(language=None,locale=None)
        for index,name in enumerate(('sceneBody','windowContentEntered','windowContentReturned','colorWindowBody')):
            e=event(event=name,sequence=index+2,elapsed=.2+index*.1,epoch=100.2+index*.1)
            e.pop('app');e.pop('product');values.append(e)
        app=dict(present=True,running=True,active=True,hidden=False,policy=0,count=0,omitted=0,key=None,main=None,windows=[])
        for seq,elapsed in [(6,1.05),(7,5.1)]:
            e=event(event='census',sequence=seq,elapsed=elapsed,epoch=100+elapsed,app=app);e.pop('product');values.append(e)
        e=event(event='final',sequence=8,elapsed=10.1,epoch=110.1,late=True);e.pop('app');e.pop('product');values.append(e)
        for e in values:e['epoch']+=self.delta
        return m.encode([envelope(e) for e in values])

    def runner(self,argv,**kwargs):
        index=len(self.calls);self.calls.append((argv,kwargs))
        if self.fault:
            value=self.fault(index,argv,kwargs)
            if value is not None:return value
        raw=b'';code=0
        if index==0:raw=(SOURCE['sha']+'\n'+m.PARENT+'\n').encode()
        elif index==2:raw=b'26A428\n'
        elif index==3:raw=b'arm64\n'
        elif index==4:raw=(m.TOOLCHAIN['xcode']+'\n').encode()
        elif index==5:raw=m.encode(self.locale)
        elif index==7:self.export_contact();self.clock.advance(22);code=65 if self.failed else 0
        elif index==8:raw=(m.ROOT/'mac-ui-summary.json').read_bytes()
        elif index==10:raw=self.logs()
        self.clock.advance(.05)
        return subprocess.CompletedProcess(argv,code,raw,b'')

    def execute(self):
        value=self.diagnostic.run();self.assertEqual(value['status'],'test-closed',value)
        self.assertEqual(len(self.calls),8);return value

    def packet(self):
        self.execute();r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        m.validate_packet(m.EVIDENCE,SOURCE);return r


class SourceContracts(unittest.TestCase):
    def test_app_product_scene_checkpoint_sources_are_byte_identical_to_d238(self):
        self.assertEqual(m.REFERENCE_PRODUCT,REFERENCE['reference_product'])
        self.assertEqual(REFERENCE['reference_commit'],'d238410a5a45818e20116e835669f1740a81eec2')
        for name,digest in REFERENCE['app_product_source_files'].items():
            with self.subTest(path=name):self.assertEqual(hashlib.sha256(restore_store_app((CHECKOUT/name).read_text()).encode() if name=='TouchColorMac/TouchColorMacApp.swift' else (CHECKOUT/name).read_bytes()).hexdigest(),digest)

    def test_only_ui_launch_tuple_changed_all_assertions_and_other_code_preserved(self):
        text=(CHECKOUT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        self.assertEqual(restore_chinese_setup(text).count(RESET_SETUP),1);self.assertNotIn(ENGLISH_SETUP,text)
        restored=restore_english_setup(text)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),REFERENCE['original_ui_test_sha256'])
        self.assertIn('app.launchArguments = ["--ui-test-reset"]',text)
        self.assertIn('assertPrivacyContact(label: "Contact the developer about privacy")',text)

    def test_original_explicit_english_route_validators_and_capture_are_unchanged(self):
        for name,digest in REFERENCE['unchanged_explicit_contract_files'].items():
            with self.subTest(path=name):self.assertEqual(hashlib.sha256(restore_store_app((CHECKOUT/name).read_text()).encode() if name=='TouchColorMac/TouchColorMacApp.swift' else (CHECKOUT/name).read_bytes()).hexdigest(),digest)
        self.assertEqual(original.passive.launch_args(m.CASE,1),['--ui-test-reset','-AppleLanguages','(en)','-AppleLocale','en_US'])
        self.assertEqual(contract.ARGS,['--ui-test-reset'])

    def test_new_route_is_fixed_and_cannot_impersonate_original(self):
        self.assertEqual(m.source_identity(env()),SOURCE)
        self.assertEqual(m.BRANCH,'refs/heads/codex/mac-scene-reset-only')
        wrong=env();wrong['GITHUB_REF']=original.BRANCH
        with self.assertRaises(ValueError):m.source_identity(wrong)
        self.assertNotEqual(m.REPORT,original.REPORT)
        self.assertEqual(m.PARENT,original.PARENT)

    def test_read_only_runner_locale_probe_is_one_prep_command_no_app_hook(self):
        p=m.plan();self.assertEqual(len(p),10)
        self.assertEqual(p[5],('runner-locale',['xcrun','swift','-swift-version','5','scripts/MacRunnerLocale.swift'],20,20,20,'preparation'))
        swift=(CHECKOUT/'scripts/MacRunnerLocale.swift').read_text()
        for value in ['Locale.current.identifier','Locale.preferredLanguages','JSONSerialization.data','standardOutput.write']:self.assertIn(value,swift)
        for bad in ['AppKit','NSApplication','NSApp','UserDefaults','setenv','AXUIElement','sleep','DispatchQueue','NSWindow']:self.assertNotIn(bad,swift)
        self.assertEqual(sum('build-for-testing' in row[1] for row in p),1)
        self.assertEqual(sum('test-without-building' in row[1] for row in p),1)
        self.assertEqual(p[6][1],original.plan()[5][1])
        self.assertEqual(m.test_command(),[str(m.RESULT) if x==str(original.RESULT) else x for x in original.test_command()])

    def test_same_job_and_phase_limits_plus_only_internal_probe_accounting(self):
        current={k:v for k,v in m.BUDGET.items() if k not in ('platform','runnerLocaleProbeWithCleanup')}
        expected={k:v for k,v in original.BUDGET.items() if k!='platform'}
        self.assertEqual(current,expected);self.assertEqual(m.BUDGET['runnerLocaleProbeWithCleanup'],40)
        self.assertEqual(job_budget.EXPECTED_MINUTES[m.PLATFORM],25)
        self.assertEqual(m.LIMIT,original.LIMIT);self.assertEqual(m.EVIDENCE_SECONDS,original.EVIDENCE_SECONDS)
        workflow=(CHECKOUT/m.WORKFLOW).read_text()
        self.assertEqual(workflow.count('runs-on: xcode-27'),1);self.assertIn('timeout-minutes: 25',workflow)
        for bad in ['matrix:','workflow_dispatch','schedule:','retry','NSWorkspace']:self.assertNotIn(bad,workflow)
        self.assertIn('branches: [codex/mac-scene-reset-only]',workflow)


class LocaleContractTests(unittest.TestCase):
    def test_locale_json_is_bounded_closed_and_not_an_app_locale(self):
        self.assertEqual(contract.parse_runner_locale(m.encode(LOCALE)),LOCALE)
        changes=[{'localeIdentifier':None},{'localeIdentifier':'secret\nvalue'},{'preferredLanguages':[]},
            {'preferredLanguages':['en-US']*17},{'preferredLanguages':['en-US','en-US']},{'preferredLanguages':[{}]},
            {'preferredLanguages':['en\nUS']},{'extra':'unbounded environment'}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):contract.parse_runner_locale(m.encode({**LOCALE,**change}))
        with self.assertRaises(ValueError):contract.parse_runner_locale(b'x'*4097)

    def observe(self,text,contact=None):
        contact=contact or {'outcome':'failed','identity':{'pid':345}}
        return contract.app_language_observation({'testFailures':[{'failureText':text}]},contact)

    def test_owned_english_chinese_mixed_and_insufficient_labels(self):
        cases=[(('Sample','Save Color'),'english-strings'),(('取色','保存颜色'),'simplified-chinese-strings'),
            (('Sample','保存颜色'),'mixed-observed-strings'),(('Sample',),'unknown'),((),'unknown')]
        for labels,wanted in cases:
            with self.subTest(labels=labels):
                result=self.observe(hierarchy(labels=labels));self.assertEqual(result['observation'],wanted)
                self.assertEqual(result['effectiveLocale'],'unknown')

    def test_foreign_mismatched_missing_ambiguous_owner_and_outside_labels_stay_unknown(self):
        valid=hierarchy();foreign=hierarchy(root_pid=456,root_title='OtherApp')
        duplicate=valid.replace('Path to element:'," →Application, 0x13, pid: 345, title: 'TouchColor'\nPath to element:")
        outside=hierarchy(labels=(),outside="    MenuItem, 0x1, title: 'Sample'\n    MenuItem, 0x2, title: 'Save Color'\n")
        no_owner=valid.replace('Element subtree:\n','No subtree:\n')
        for text in [foreign,duplicate,outside,no_owner,valid.replace('pid: 345','pid: 346'),valid+valid]:
            with self.subTest(text=text[:80]):self.assertEqual(self.observe(text)['observation'],'unknown')

    def test_passed_original_assertion_proves_only_english_label_not_effective_locale(self):
        result=self.observe('',{'outcome':'passed','identity':{'pid':345}})
        self.assertEqual(result['observation'],'english-strings')
        self.assertEqual(result['basis'],'unchanged-English-contact-label-assertion-passed')
        self.assertEqual(result['effectiveLocale'],'unknown')
        self.assertEqual(contract.app_language_observation({},None)['observation'],'unknown')


class ResetRuntime(Harness):
    def test_failed_control_retains_separate_runner_and_app_observations(self):
        report=self.packet();self.assertEqual(len(self.calls),11)
        self.assertEqual(report['diagnosticRoute'],'reset-only');self.assertFalse(report['explicitEnglishQualification'])
        self.assertEqual(report['runnerLocale'],LOCALE);self.assertEqual(report['appLanguageObservation']['observation'],'english-strings')
        self.assertEqual(report['appLanguageObservation']['effectiveLocale'],'unknown')
        self.assertEqual(report['contactOutcome'],'failed');self.assertFalse(report['acceptance'])
        self.assertEqual(report['productComparability'],'exact-reference-bytes')
        self.assertEqual(self.calls[5][1]['cap'],4096)
        m.validate_once(self.budget,SOURCE,clock=self.clock);self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),1)

    def test_pass_is_not_explicit_english_qualification_or_repair(self):
        self.failed=False;report=self.packet()
        self.assertEqual(report['contactOutcome'],'passed');self.assertFalse(report['explicitEnglishQualification']);self.assertFalse(report['acceptance'])
        self.assertIn('not-explicit-English',report['interpretation'])
        self.assertEqual(report['appLanguageObservation']['basis'],'unchanged-English-contact-label-assertion-passed')
        m.validate_once(self.budget,SOURCE,clock=self.clock);self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),0)

    def test_host_language_does_not_become_app_language(self):
        self.locale={'localeIdentifier':'zh_CN','preferredLanguages':['zh-Hans']};self.language_text='XCTAssertTrue failed - no retained application hierarchy'
        report=self.packet();self.assertEqual(report['runnerLocale'],self.locale)
        self.assertEqual(report['appLanguageObservation']['observation'],'unknown')

    def test_new_build_byte_difference_is_observation_not_cross_build_gate(self):
        self.actual_product['logicSHA256']='f'*64
        report=self.packet()
        self.assertEqual(len(self.calls),11);self.assertEqual(report['productComparability'],'different-bytes')
        self.assertEqual(report['contactOutcome'],'failed');self.assertFalse(report['acceptance'])
        self.assertEqual(report['referenceProductHashes'],m.REFERENCE_PRODUCT)
        self.assertEqual(report['binaryUUIDComparison'],'unknown-reference-UUIDs-not-retained-current-UUIDs-not-collected')
        self.assertEqual(json.loads((m.EVIDENCE/'state.json').read_bytes())['product']['logicSHA256'],'f'*64)

    def test_locale_failure_stops_before_build_or_app_case(self):
        self.fault=lambda i,a,k:subprocess.CompletedProcess(a,1,b'',b'locale unavailable') if i==5 else None
        value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete');self.assertEqual(len(self.calls),6)
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertIsNone(report['runnerLocale']);self.assertEqual(report['appLanguageObservation']['observation'],'unknown')
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_invalid_locale_output_is_not_replaced_by_default(self):
        self.fault=lambda i,a,k:subprocess.CompletedProcess(a,0,b'{"localeIdentifier":null,"preferredLanguages":[]}',b'') if i==5 else None
        value=self.diagnostic.run();self.assertEqual(value['status'],'incomplete');self.assertEqual(len(self.calls),6)
        self.assertIsNone(value['runnerLocale']);self.assertTrue(m.LATCH.exists())

    def test_late_locale_and_failed_containment_stop_no_retry(self):
        def late(i,a,k):
            if i==5:self.clock.advance(k['seconds']+.1);return subprocess.CompletedProcess(a,0,m.encode(LOCALE),b'')
        self.fault=late;self.diagnostic.run();self.assertEqual(len(self.calls),6)
        m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),6)

    def test_locale_hashing_persistence_cannot_extend_preparation(self):
        real=m.parse_runner_locale
        def slow(raw):
            value=real(raw);self.clock.value=self.diagnostic.value['preparationDeadlineMonotonic']+.1;return value
        with patch.object(m,'parse_runner_locale',side_effect=slow):value=self.diagnostic.run()
        self.assertEqual(value['status'],'incomplete');self.assertEqual(len(self.calls),6)

    def test_uncertain_test_stops_all_evidence_commands(self):
        self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('unknown',False)) if i==7 else None
        self.diagnostic.run();report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),8);self.assertEqual(report['contactOutcome'],'unknown');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_zero_case_summary_still_stops_before_attachment_export(self):
        self.execute();p=m.ROOT/'mac-ui-summary.json';s=json.loads(p.read_bytes());s.update(totalTestCount=0,passedTests=0,failedTests=0);p.write_bytes(m.encode(s))
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),9);self.assertEqual(report['contactOutcome'],'unknown')
        self.assertFalse(any(a[:3]==['xcrun','xcresulttool','export'] for a,_ in self.calls));m.validate_packet(m.EVIDENCE,SOURCE)

    def test_explicit_english_tuple_is_rejected_by_reset_only_receipt_contract(self):
        self.execute();groups=json.loads((m.ROOT/'screenshots/manifest.json').read_bytes());p=m.ROOT/'screenshots'/groups[0]['attachments'][0]['exportedFileName']
        r=json.loads(p.read_bytes());r['args']=original.passive.launch_args(m.CASE,1);p.write_bytes(m.encode(r))
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),10);self.assertEqual(report['contactOutcome'],'unknown');self.assertEqual(report['records'],[])
        m.validate_packet(m.EVIDENCE,SOURCE)

    def test_original_explicit_english_parser_rejects_actual_reset_receipt(self):
        self.execute()
        with self.assertRaises(ValueError):original.passive.identities(m.ROOT)
        identity=contract.reset_identities(m.ROOT)[0];self.assertEqual(identity['args'],['--ui-test-reset'])

    def test_receipt_scope_pid_token_time_path_hash_and_destination_fail_closed(self):
        self.execute();groups_path=m.ROOT/'screenshots/manifest.json';groups=json.loads(groups_path.read_bytes())
        receipt_path=m.ROOT/'screenshots'/groups[0]['attachments'][0]['exportedFileName'];raw=receipt_path.read_bytes();receipt=json.loads(raw)
        for change in [dict(pid=0),dict(pid=True),dict(token='foreign'),dict(ordinal=2),dict(sandbox=True),dict(args=[]),
            dict(started=receipt['started']-1000),dict(captured=receipt['captured']+1000),dict(expectedPath='/other.app'),
            dict(logicSHA256='f'*64),dict(executableSHA256='f'*64),dict(xctestPID=345),dict(extra='unknown')]:
            receipt_path.write_bytes(m.encode(receipt|change))
            with self.subTest(change=change),self.assertRaises(ValueError):contract.validate_reset_contact(m.ROOT,self.actual_product,65)
        receipt_path.write_bytes(raw)
        for change in [dict(deviceId='other'),dict(timestamp=0),dict(configurationName='Other Configuration')]:
            mutated=copy.deepcopy(groups);mutated[0]['attachments'][0].update(change);groups_path.write_bytes(m.encode(mutated))
            with self.subTest(change=change),self.assertRaises(ValueError):contract.validate_reset_contact(m.ROOT,self.actual_product,65)
        groups_path.write_bytes(m.encode(groups))

    def test_app_header_must_report_no_requested_locale_tuple(self):
        self.execute();real=self.logs
        def wrong_header():
            rows=json.loads(real());value=json.loads(rows[0]['eventMessage'][len(m.passive.PREFIX):])
            value['product'].update(language='(en)',locale='en_US');rows[0]['eventMessage']=m.passive.PREFIX+json.dumps(value)
            return m.encode(rows)
        with patch.object(self,'logs',side_effect=wrong_header):report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['records'],[])
        self.assertEqual(report['contactOutcome'],'failed');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_late_summary_finish_stops_before_export(self):
        self.execute();p=m.ROOT/'mac-ui-summary.json';s=json.loads(p.read_bytes());s['finishTime']=self.diagnostic.value['commands'][7]['finishedEpoch']+1;p.write_bytes(m.encode(s))
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(len(self.calls),9);self.assertEqual(report['contactOutcome'],'unknown');m.validate_packet(m.EVIDENCE,SOURCE)

    def test_query_failure_keeps_validated_case_and_derived_existing_language(self):
        self.execute();self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('query stopped',True)) if i==10 else None
        report=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['contactOutcome'],'failed')
        self.assertEqual(report['appLanguageObservation']['observation'],'english-strings');m.validate_packet(m.EVIDENCE,SOURCE)


class ResetMutations(Harness):
    def mutate_state(self,fn):
        path=m.EVIDENCE/'state.json';raw=path.read_bytes();report=m.REPORT.read_bytes();s=json.loads(raw);fn(s)
        changed=m.encode(s);path.write_bytes(changed);r=json.loads(report);r['files']['state.json']=dict(bytes=len(changed),sha256=m.digest(changed));m.REPORT.write_bytes(m.encode(r))
        return raw,report

    def test_locale_source_command_cap_and_time_are_bound(self):
        self.packet()
        for change in [lambda s:s['commands'][5]['argv'].append('--extra'),lambda s:s['commands'][5].update(captureCap=512*1024),
            lambda s:s['commands'][5].update(stdoutSHA256='f'*64),lambda s:s.update(runnerLocale=LOCALE|{'localeIdentifier':'zh_CN'}),
            lambda s:s['commands'][5].update(cleanupConfirmed=False)]:
            raw,report=self.mutate_state(change)
            with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
            (m.EVIDENCE/'state.json').write_bytes(raw);m.REPORT.write_bytes(report)

    def test_host_locale_and_app_language_cannot_be_relabelled_or_promoted(self):
        report=self.packet();raw=m.REPORT.read_bytes()
        changes=[('runnerLocale',{'localeIdentifier':'zh_CN','preferredLanguages':['zh-Hans']}),('explicitEnglishQualification',True),
            ('diagnosticRoute','explicit-English'),('productComparability','different-bytes'),
            ('referenceProductHashes',{'executableSHA256':'f'*64,'logicSHA256':'f'*64}),('binaryUUIDComparison','identical'),
            ('appLanguageObservation',dict(observation='english-strings',basis='runner-locale',observedLabels=[],effectiveLocale='en_US'))]
        for key,value in changes:
            changed=copy.deepcopy(report);changed[key]=value;m.REPORT.write_bytes(m.encode(changed))
            with self.subTest(key=key),self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
        m.REPORT.write_bytes(raw)

    def test_missing_locale_file_or_changed_raw_bytes_fail(self):
        self.packet();p=m.EVIDENCE/'runner-locale.json';raw=p.read_bytes();p.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
        p.write_bytes(raw);p.unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_same_run_receipt_product_mismatch_is_still_rejected(self):
        self.packet();self.mutate_state(lambda s:s['product'].update(logicSHA256='f'*64))
        with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)

    def test_failed_assertion_cannot_be_changed_to_pass_after_upload(self):
        report=self.packet();m.validate_once(self.budget,SOURCE,clock=self.clock)
        report['contactOutcome']='passed';m.REPORT.write_bytes(m.encode(report))
        with self.assertRaises(ValueError):m.contact_result(self.budget,SOURCE,clock=self.clock)


if __name__=='__main__':unittest.main()
