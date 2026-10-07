"""Fixed Chinese sandbox contact source/fault contracts, no native execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import job_budget
import mac_chinese_contact as m
import mac_chinese_contract as contract
import mac_scene_reset_only as previous
from test_mac_launch_comparison import Clock, PRODUCT as OLD_PRODUCT, contact_export
from test_mac_reset_source_helpers import restore_chinese_setup
CHECKOUT=Path(__file__).resolve().parents[1]
PRODUCT={k:v.replace('/mac-tests/','/mac-sandbox/') if isinstance(v,str) else v for k,v in OLD_PRODUCT.items()}
SOURCE=dict(repository='100mango/ColorPicker',ref=m.BRANCH,workflow=m.WORKFLOW,workflow_ref='100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,
 event='push',sha='a'*40,run='1',attempt='1',parent=m.PARENT,route='Chinese-sandbox-test-plan')
LOCALE={'localeIdentifier':'en_US','preferredLanguages':['en-US']}
def env():
 return dict(GITHUB_REPOSITORY=SOURCE['repository'],GITHUB_REF=m.BRANCH,GITHUB_WORKFLOW_REF=SOURCE['workflow_ref'],GITHUB_EVENT_NAME='push',
 GITHUB_SHA=SOURCE['sha'],GITHUB_WORKFLOW_SHA=SOURCE['sha'],GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',TOUCHCOLOR_JOB_PLATFORM=m.PLATFORM,
 TOUCHCOLOR_JOB_LANE=m.PLATFORM,TOUCHCOLOR_JOB_MINUTES='25',TOUCHCOLOR_EVIDENCE_LIMIT='3000000',TOUCHCOLOR_JOB_STARTED_EPOCH='100',TOUCHCOLOR_JOB_STARTED_MONOTONIC='100')
class Harness(unittest.TestCase):
 def setUp(self):
  self.old=Path.cwd();self.temp=tempfile.TemporaryDirectory();os.chdir(self.temp.name);m.ROOT.mkdir(parents=True)
  Path('source.txt').write_text('bound Chinese source');Path('TouchColorMac').mkdir();Path('TouchColorMac/TouchColorMac.entitlements').write_bytes(plistlib.dumps({k:v for k,v in m.MINIMAL_ENTITLEMENTS.items() if k!='com.apple.security.get-task-allow'}))
  self.clock=Clock();self.calls=[];self.fault=None;self.failed=False;self.product=dict(PRODUCT);self.before=dict(m.MINIMAL_ENTITLEMENTS);self.after=dict(m.MINIMAL_ENTITLEMENTS)
  self.source_patch=patch.object(m,'SOURCES',('source.txt',));self.source_patch.start();self.product_patch=patch.object(m,'product_identity',side_effect=lambda:dict(self.product));self.product_patch.start()
  self.budget=job_budget.JobBudget(job_budget.create_record(env(),wall=self.clock,monotonic=self.clock),wall=self.clock,monotonic=self.clock)
  self.d=m.Diagnostic(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
 def tearDown(self):
  self.product_patch.stop();self.source_patch.stop();os.chdir(self.old);self.temp.cleanup()
 def export(self):
  receipt=contact_export(m.ROOT,failed=self.failed);delta=self.clock.value+.2-99
  r=json.loads(receipt.read_bytes());r.update(self.product);r['expectedPath']=self.product['applicationPath'];r.update(args=['--ui-test-reset'],sandbox=True,test='-[TouchColorMacUITests '+m.CASE+']')
  for k in ['started','captured']:r[k]+=delta
  receipt.write_bytes(m.encode(r))
  p=m.ROOT/'mac-ui-summary.json';summary=json.loads(p.read_bytes())
  for k in ['startTime','finishTime']:summary[k]+=delta
  summary['devicesAndConfigurations'][0]['testPlanConfiguration']['configurationName']='Chinese'
  for f in summary.get('testFailures',[]):
   for k in ['testIdentifierString','testIdentifierURL','testName']:f[k]=f[k].replace(previous.CASE,m.CASE)
  p.write_bytes(m.encode(summary));p=m.ROOT/'screenshots/manifest.json';groups=json.loads(p.read_bytes())
  for g in groups:
   g['testIdentifier']=g['testIdentifier'].replace(previous.CASE,m.CASE);g['testIdentifierURL']=g['testIdentifierURL'].replace(previous.CASE,m.CASE)
   for a in g['attachments']:a['timestamp']+=delta;a['configurationName']='Chinese'
  p.write_bytes(m.encode(groups))
 def runner(self,argv,**kwargs):
  i=len(self.calls);self.calls.append((argv,kwargs))
  if self.fault:
   value=self.fault(i,argv,kwargs)
   if value is not None:return value
  raw=b'';code=0
  if i==0:raw=(SOURCE['sha']+'\n'+m.PARENT+'\n').encode()
  elif i==2:raw=b'26A428\n'
  elif i==3:raw=b'arm64\n'
  elif i==4:raw=(m.TOOLCHAIN['xcode']+'\n').encode()
  elif i==5:raw=m.encode(LOCALE)
  elif i==9:raw=plistlib.dumps(self.before)
  elif i==10:self.export();self.clock.advance(22);code=65 if self.failed else 0
  elif i==12:raw=plistlib.dumps(self.after)
  elif i==13:raw=(m.ROOT/'mac-ui-summary.json').read_bytes()
  self.clock.advance(.05);return subprocess.CompletedProcess(argv,code,raw,b'')
 def execute(self):
  value=self.d.run();self.assertEqual(value['status'],'test-closed',value);self.assertEqual(len(self.calls),13);return value
 def packet(self):
  self.execute();r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);m.validate_packet(m.EVIDENCE,SOURCE);return r
class SourceContracts(unittest.TestCase):
 def test_fixed_plan_has_only_original_chinese_case(self):
  p=json.loads((CHECKOUT/'TouchColorMacChineseContact.xctestplan').read_bytes());self.assertEqual(p['version'],1);self.assertEqual(len(p['configurations']),1)
  self.assertEqual(p['configurations'][0]['name'],'Chinese');self.assertEqual(p['configurations'][0]['options'],{'language':'zh-Hans','region':'CN'})
  self.assertEqual(p['defaultOptions'],{});self.assertEqual(len(p['testTargets']),1);self.assertFalse(p['testTargets'][0]['parallelizable'])
  self.assertEqual(p['testTargets'][0]['selectedTests'],['TouchColorMacUITests/'+m.CASE+'()'])
  self.assertEqual(p['testTargets'][0]['target'],{'containerPath':'container:TouchColorMac.xcodeproj','identifier':'EDEF04536BDD07E17940AE61','name':'TouchColorMacUITests'})
 def test_new_scheme_reuses_original_sandbox_except_testplan(self):
  root=CHECKOUT/'TouchColorMac.xcodeproj/xcshareddata/xcschemes';new=ET.parse(root/'TouchColorMacSandboxChineseContact.xcscheme').getroot();old=ET.parse(root/'TouchColorMacSandbox.xcscheme').getroot()
  plans=new.find('TestAction/TestPlans');self.assertEqual(len(plans),1);self.assertEqual(plans[0].attrib,{'reference':'container:TouchColorMacChineseContact.xctestplan','default':'YES'})
  new.find('TestAction').remove(plans);new.find('TestAction').append(old.find('TestAction/Testables'));self.assertEqual(ET.tostring(new),ET.tostring(old))
 def test_only_necessary_chinese_setup_edit_and_assertions_retained(self):
  f=CHECKOUT/'TouchColorMacUITests/TouchColorMacUITests.swift';text=f.read_text();restored=restore_chinese_setup(text)
  reference=json.loads((CHECKOUT/'scripts/fixtures/mac-chinese-source-baseline.json').read_bytes())
  self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),reference['previous_ui_sha256'])
  setup=text.split('override func setUpWithError()',1)[1].split('override func tearDownWithError()',1)[0]
  self.assertNotIn('-AppleLanguages',setup);self.assertEqual(setup.count('app.launch()'),1)
  self.assertIn('assertPrivacyContact(label: "联系开发者咨询隐私问题")',text)
 def test_app_resources_original_schemes_and_runtime_helpers_unchanged(self):
  f=json.loads((CHECKOUT/'scripts/fixtures/mac-chinese-source-baseline.json').read_bytes())
  for name,digest in f['unchanged'].items():
   with self.subTest(path=name):self.assertEqual(hashlib.sha256((CHECKOUT/name).read_bytes()).hexdigest(),digest)
 def test_native_plan_is_single_build_single_test_no_probe_or_query(self):
  plan=m.plan();self.assertEqual(len(plan),15);self.assertEqual(sum('build-for-testing' in a for _,a,*_ in plan),1);self.assertEqual(sum('test-without-building' in a for _,a,*_ in plan),1)
  allargs=' '.join(' '.join(x[1]) for x in plan)
  for bad in ['NSWorkspace','test_mac_sandbox.sh','prepare_sandbox_probe','AppleLanguages','AppleLocale','log show','allowProvisioning']:self.assertNotIn(bad,allargs)
  self.assertIn('-testPlan TouchColorMacChineseContact',allargs);self.assertIn('CODE_SIGN_IDENTITY=-',allargs)
 def test_no_new_permissions_or_distribution_signing(self):
  expected={'com.apple.security.app-sandbox':True,'com.apple.security.files.user-selected.read-write':True,'com.apple.security.device.camera':True,'com.apple.security.get-task-allow':True}
  self.assertEqual(m.MINIMAL_ENTITLEMENTS,expected)
  old=(CHECKOUT/'scripts/test_mac_sandbox.sh').read_text()
  for key in expected:self.assertIn(key,old)
 def test_clock_budget_has_no_extension_and_fixed_workflow(self):
  for k in ['minutes','workSeconds','preparationSeconds','testCommandSeconds','testCleanupSeconds','maximumWorkPhases','workHeadroom','evidenceSeconds','summaryWithCleanup','attachmentsWithCleanup','reserves','startupMargin']:self.assertEqual(m.BUDGET[k],previous.BUDGET[k],k)
  self.assertEqual(m.BUDGET['sandboxPreparationCommandsWithCleanup'],120);self.assertEqual(m.BUDGET['sandboxPostflightInsideTestAllocation'],80)
  self.assertEqual(m.BUDGET['queryWithCleanup'],0);self.assertEqual(m.BUDGET['evidenceLocalHeadroom'],100)
  w=(CHECKOUT/m.WORKFLOW).read_text();self.assertEqual(w.count('runs-on: xcode-27'),1);self.assertIn('timeout-minutes: 25',w)
  for bad in ['matrix:','workflow_dispatch','retry','test_mac_sandbox']:self.assertNotIn(bad,w)
 def test_source_route_cannot_impersonate_reset_control(self):
  self.assertEqual(m.source_identity(env()),SOURCE);bad=env();bad['GITHUB_REF']=previous.BRANCH
  with self.assertRaises(ValueError):m.source_identity(bad)
class Runtime(Harness):
 def test_pass_qualifies_only_actual_chinese_sandbox_case(self):
  r=self.packet();self.assertEqual(len(self.calls),15);self.assertTrue(r['singleChineseSandboxContactQualification']);self.assertFalse(r['acceptance'])
  self.assertEqual(r['contactOutcome'],'passed');self.assertEqual(r['appLanguageObservation']['observation'],'simplified-chinese-strings');self.assertEqual(r['appLanguageObservation']['effectiveLocale'],'unknown')
  self.assertEqual(r['runnerLocale'],LOCALE);self.assertEqual(r['requestedLocalization'],m.LOCALIZATION)
  m.validate_once(self.budget,SOURCE,clock=self.clock);self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),0)
 def test_original_failure_is_not_changed_to_pass(self):
  self.failed=True;r=self.packet();self.assertEqual(r['contactOutcome'],'failed');self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_once(self.budget,SOURCE,clock=self.clock);self.assertEqual(m.contact_result(self.budget,SOURCE,clock=self.clock),1)
 def test_postflight_stays_inside_original_test_allocation(self):
  v=self.execute();ceiling=v['commands'][10]['deadlineMonotonic']
  for row in v['commands'][11:13]:self.assertEqual(row['phaseCeilingMonotonic'],ceiling);self.assertLessEqual(row['cleanupDeadlineMonotonic'],ceiling)
 def test_late_test_leaves_no_time_for_postflight_and_no_retry(self):
  def late(i,a,k):
   if i==10:self.export();self.clock.advance(290);return subprocess.CompletedProcess(a,0,b'',b'')
  self.fault=late;v=self.d.run();self.assertEqual(v['status'],'incomplete');self.assertEqual(len(self.calls),11)
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),11);self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_extra_pre_entitlement_stops_before_case(self):
  self.before['com.apple.security.network.client']=True;v=self.d.run();self.assertEqual(v['status'],'incomplete');self.assertEqual(len(self.calls),10)
 def test_post_entitlement_change_prevents_result_commands(self):
  self.after['com.apple.security.network.client']=True;v=self.d.run();self.assertEqual(v['status'],'incomplete');self.assertEqual(len(self.calls),13)
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),13);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_product_changed_after_test_is_incomplete(self):
  def change(i,a,k):
   if i==12:self.product['logicSHA256']='f'*64
  self.fault=change;v=self.d.run();self.assertEqual(v['status'],'incomplete');self.assertIn('runtime-product',v['reason']);self.assertEqual(len(self.calls),13)
 def test_sign_failure_never_launches_app(self):
  self.fault=lambda i,a,k:subprocess.CompletedProcess(a,1,b'',b'sign failure') if i==7 else None
  self.d.run();self.assertEqual(len(self.calls),8);r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_unconfirmed_capture_stops_every_later_command(self):
  self.fault=lambda i,a,k:(_ for _ in ()).throw(m.CaptureStopped('uncertain',False)) if i==10 else None
  self.d.run();r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),11);self.assertEqual(r['contactOutcome'],'unknown');m.validate_packet(m.EVIDENCE,SOURCE)
 def test_zero_case_stops_before_export(self):
  self.execute();p=m.ROOT/'mac-ui-summary.json';v=json.loads(p.read_bytes());v.update(totalTestCount=0,passedTests=0);p.write_bytes(m.encode(v))
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),14);self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_late_summary_stops_before_export(self):
  self.execute();p=m.ROOT/'mac-ui-summary.json';v=json.loads(p.read_bytes());v['finishTime']=self.d.value['commands'][10]['finishedEpoch']+1;p.write_bytes(m.encode(v))
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),14);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_wrong_configuration_is_not_chinese_qualification(self):
  self.execute();p=m.ROOT/'mac-ui-summary.json';v=json.loads(p.read_bytes());v['devicesAndConfigurations'][0]['testPlanConfiguration']['configurationName']='Test Scheme Action';p.write_bytes(m.encode(v))
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_manual_tuple_and_standard_lane_receipts_rejected(self):
  self.execute();groups=json.loads((m.ROOT/'screenshots/manifest.json').read_bytes());p=m.ROOT/'screenshots'/groups[0]['attachments'][0]['exportedFileName'];raw=p.read_bytes();v=json.loads(raw)
  for change in [dict(args=['--ui-test-reset','-AppleLanguages','(zh-Hans)','-AppleLocale','zh_CN']),dict(sandbox=False),dict(ordinal=2),dict(pid=0),dict(token='bad'),dict(logicSHA256='f'*64)]:
   p.write_bytes(m.encode(v|change))
   with self.subTest(change=change),self.assertRaises(ValueError):contract.validate_chinese_contact(m.ROOT,self.product,0)
  p.write_bytes(raw)
 def test_false_or_integer_entitlements_rejected(self):
  for value in [False,1,'true']:
   v=dict(m.MINIMAL_ENTITLEMENTS);v['com.apple.security.app-sandbox']=value
   with self.subTest(value=value),self.assertRaises(ValueError):m.parse_entitlements(plistlib.dumps(v))
 def test_source_hash_change_is_rejected_before_export(self):
  self.execute();Path('source.txt').write_text('changed')
  with self.assertRaises(ValueError):m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock)
 def test_retained_entitlements_and_report_claims_are_bound(self):
  r=self.packet();original=m.REPORT.read_bytes()
  for field,value in [('requestedLocalization',m.LOCALIZATION|{'language':'en'}),('singleChineseSandboxContactQualification',False),('acceptance',True)]:
   altered=copy.deepcopy(r);altered[field]=value;m.REPORT.write_bytes(m.encode(altered))
   with self.subTest(field=field),self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
  m.REPORT.write_bytes(original);p=m.EVIDENCE/'sandbox-after.plist';p.write_bytes(p.read_bytes()+b' ')
  with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
 def test_entitlement_command_hash_cannot_be_rewritten(self):
  self.packet();p=m.EVIDENCE/'state.json';state=json.loads(p.read_bytes());state['commands'][12]['stdoutSHA256']='f'*64;raw=m.encode(state);p.write_bytes(raw)
  r=json.loads(m.REPORT.read_bytes());r['files']['state.json']={'bytes':len(raw),'sha256':m.digest(raw)};m.REPORT.write_bytes(m.encode(r))
  with self.assertRaises(ValueError):m.validate_packet(m.EVIDENCE,SOURCE)
 def test_post_signature_failure_does_not_export_or_retry(self):
  self.fault=lambda i,a,k:subprocess.CompletedProcess(a,1,b'',b'verification failed') if i==11 else None
  self.d.run();r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),12);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_preparation_cannot_expand_for_signing(self):
  def late(i,a,k):
   if i==6:self.clock.value=self.d.value['preparationDeadlineMonotonic']-25;return subprocess.CompletedProcess(a,0,b'',b'')
  self.fault=late;v=self.d.run();self.assertEqual(v['status'],'incomplete');self.assertEqual(len(self.calls),7)
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),7);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_second_case_and_skip_cannot_qualify(self):
  self.execute();p=m.ROOT/'mac-ui-summary.json';s=json.loads(p.read_bytes());s.update(totalTestCount=2,skippedTests=1);p.write_bytes(m.encode(s))
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertEqual(len(self.calls),14);self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_foreign_manifest_configuration_rejected(self):
  self.execute();p=m.ROOT/'screenshots/manifest.json';v=json.loads(p.read_bytes());v[0]['attachments'][0]['configurationName']='English';p.write_bytes(m.encode(v))
  r=m.evidence(self.budget,SOURCE,runner=self.runner,clock=self.clock,wall=self.clock);self.assertFalse(r['singleChineseSandboxContactQualification']);m.validate_packet(m.EVIDENCE,SOURCE)
 def test_failed_final_hash_guard_cannot_turn_failure_into_pass(self):
  self.failed=True;r=self.packet();m.validate_once(self.budget,SOURCE,clock=self.clock);r['contactOutcome']='passed';m.REPORT.write_bytes(m.encode(r))
  with self.assertRaises(ValueError):m.contact_result(self.budget,SOURCE,clock=self.clock)
if __name__=='__main__':unittest.main()
