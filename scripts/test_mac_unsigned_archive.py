"""Portable Mac archive structure/failure/clock contracts; no native launch."""
import ast,datetime,hashlib,json,os
from pathlib import Path
import plistlib,struct,subprocess,tempfile,unittest
from unittest.mock import patch
import mac_unsigned_archive as m
ROOT=Path(__file__).resolve().parents[1]
CPUS=(0x100000c,0x1000007)
UUIDS={'arm64':'11111111-2222-3333-4444-555555555555','x86_64':'66666666-7777-8888-9999-AAAAAAAAAAAA'}
def thin(cpu,kind=2,platform=1,minimum=0x0d0000):
 cmd=struct.pack('<6I',0x32,24,platform,minimum,0x1b0000,0)
 return struct.pack('<8I',0xfeedfacf,cpu,0,kind,1,len(cmd),0,0)+cmd

def fat(kind=2):
 payloads=[thin(cpu,kind) for cpu in CPUS];offset=8+20*2;table=[]
 for cpu,raw in zip(CPUS,payloads):table.append(struct.pack('>5I',cpu,0,offset,len(raw),0));offset+=len(raw)
 return struct.pack('>2I',0xcafebabe,2)+b''.join(table)+b''.join(payloads)
class Clock:
 def __init__(self,value=100):self.value=value
 def __call__(self):return self.value
 def advance(self,n):self.value+=n

def fixture(root):
 a=root/m.ARCHIVE;app=a/m.APP;dwarf=a/m.DWARF
 for p in [app/'Contents/MacOS',app/'Contents/Resources',dwarf.parent]:p.mkdir(parents=True,exist_ok=True)
 meta={'ArchiveVersion':2,'SchemeName':'TouchColorMac','CreationDate':datetime.datetime(2026,10,7),'ApplicationProperties':{'ApplicationPath':'Applications/TouchColor.app','CFBundleIdentifier':'com.mango.touchColor','CFBundleShortVersionString':'2.0','CFBundleVersion':'20001'}}
 info={'CFBundleIdentifier':'com.mango.touchColor','CFBundleExecutable':'TouchColor','CFBundlePackageType':'APPL','CFBundleShortVersionString':'2.0','CFBundleVersion':'20001','LSMinimumSystemVersion':'13.0','NSCameraUsageDescription':'Sample colors from camera frames.'}
 (a/'Info.plist').write_bytes(plistlib.dumps(meta));(app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
 (a/m.DSYM/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.apple.xcode.dsym.com.mango.touchColor','CFBundlePackageType':'dSYM','CFBundleVersion':'1.0'}))
 (a/m.EXECUTABLE).write_bytes(fat());dwarf.write_bytes(fat(10))
 source=root/'TouchColorMac/PrivacyInfo.xcprivacy';source.parent.mkdir(exist_ok=True)
 privacy=(ROOT/'TouchColorMac/PrivacyInfo.xcprivacy').read_bytes();source.write_bytes(privacy);(app/'Contents/Resources/PrivacyInfo.xcprivacy').write_bytes(privacy)
 for loc in ['en','zh-Hans']:
  d=app/'Contents/Resources'/f'{loc}.lproj';d.mkdir()
  for name in ['Localizable.strings','InfoPlist.strings']:(d/name).write_text('"A" = "B";')
 for name in ['Assets.car','AppIcon.icns','AppIcon512x512@2x.png']:(app/'Contents/Resources'/name).write_bytes(b'normal generated asset')
 return a

def uuid_output(a):
 return ''.join(f'UUID: {UUIDS[arch]} ({arch}) {a/path}\n' for path in [m.EXECUTABLE,m.DWARF] for arch in ['arm64','x86_64']).encode()
class ArchiveTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.a=fixture(self.root);self.clock=Clock();self.report={};self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def invoke(self,argv,**kwargs):
  self.calls.append(argv)
  if argv[:3]==['xcrun','dwarfdump','--uuid']:return uuid_output(self.a)
  return b'Required API reasons verified: selected\n'
 def verify(self):return m.verify_archive(self.a,self.invoke,1000,root=self.root,clock=self.clock,report=self.report)
 def test_universal_archive_and_normal_generated_assets(self):
  proof=self.verify();self.assertEqual(set(proof['uuids']),{'arm64','x86_64'});self.assertTrue(self.report['archive_inventory']['complete']);self.assertTrue((self.root/'build/archive-inventory.json').exists())
  self.assertEqual(proof['dSYM_version_observations']['CFBundleVersion']['comparison'],'different')
 def test_no_resource_filename_whitelist(self):
  extra=self.a/m.APP/'Contents/Resources/Standard.Future.Icon-128.png';extra.write_bytes(b'ordinary resource');self.verify();self.assertIn(str(extra.relative_to(self.a)),self.report['archive_inventory']['paths'])
 def test_semantic_failure_retains_complete_structure_and_path(self):
  p=self.a/m.APP/'Contents/Info.plist';v=plistlib.loads(p.read_bytes());v['CFBundleIdentifier']='other';p.write_bytes(plistlib.dumps(v))
  with self.assertRaises(m.Rejected):self.verify()
  self.assertTrue(self.report['archive_inventory']['complete']);self.assertEqual(self.report['offending_path'],str(p.relative_to(self.a)));self.assertTrue((self.root/'build/archive-inventory.json').is_file())
 def test_metadata_read_error_keeps_other_plist_observations(self):
  p=self.a/'Info.plist';p.write_bytes(b'not a plist')
  with self.assertRaises(plistlib.InvalidFileException):self.verify()
  rows=self.report['archive_metadata_diagnostics'];self.assertEqual(len(rows),3)
  self.assertEqual(rows['Info.plist']['read_error']['type'],'InvalidFileException')
  self.assertEqual(rows[m.APP+'/Contents/Info.plist']['metadata']['CFBundleVersion'],'20001')
  self.assertEqual(rows[m.DSYM+'/Contents/Info.plist']['metadata']['CFBundlePackageType'],'dSYM')
  self.assertEqual(self.report['current_proof_path'],'Info.plist');self.assertEqual(self.calls,[])
 def test_relative_internal_symlink_is_catalogued_without_double_read(self):
  p=self.a/m.APP/'Contents/Resources/icon-alias';p.symlink_to('AppIcon.icns');self.verify();row=self.report['archive_inventory']['paths'][str(p.relative_to(self.a))];self.assertEqual(row['type'],'symlink');self.assertEqual(row['target'],'AppIcon.icns')
 def test_escaping_symlink_retains_bounded_offending_path(self):
  p=self.a/m.APP/'Contents/Resources/escape';p.symlink_to('/etc/passwd')
  with self.assertRaises(m.Rejected):self.verify()
  self.assertFalse(self.report['archive_inventory']['complete']);self.assertEqual(self.report['archive_inventory']['last_path'],str(p.relative_to(self.a)))
 def test_entry_bound_fails_closed_without_dropping_partial_inventory(self):
  with patch.object(m,'MAX_ENTRIES',2),self.assertRaises(m.Rejected):self.verify()
  self.assertFalse(self.report['archive_inventory']['complete']);self.assertTrue(self.report['archive_inventory']['paths'])
 def test_byte_bound_fails_closed(self):
  with patch.object(m,'MAX_BYTES',1),self.assertRaises(m.Rejected):self.verify()
 def test_inventory_metadata_bound_is_explicit(self):
  with patch.object(m,'MAX_INVENTORY',64),self.assertRaises(m.Rejected):self.verify()
 def test_debug_seam_is_rejected_after_catalogue(self):
  p=self.a/m.EXECUTABLE;p.write_bytes(p.read_bytes()+b'TOUCHCOLOR_MAC_LIFECYCLE')
  with self.assertRaises(m.Rejected):self.verify()
  self.assertTrue(self.report['archive_inventory']['complete']);self.assertEqual(self.report['offending_path'],m.EXECUTABLE)
 def test_unexpected_test_payload_is_not_a_resource_exception(self):
  p=self.a/m.APP/'Contents/PlugIns/Tests.xctest';p.mkdir(parents=True)
  with self.assertRaises(m.Rejected):self.verify()
  self.assertEqual(self.report['offending_path'],str(p.relative_to(self.a)))
  self.assertEqual(len(self.report['archive_metadata_diagnostics']),3)
 def test_single_architecture_fails(self):
  (self.a/m.EXECUTABLE).write_bytes(thin(CPUS[0]));
  with self.assertRaises(m.Rejected):self.verify()
 def test_nonmac_binary_rejected(self):
  raw=fat().replace(struct.pack('<6I',0x32,24,1,0x0d0000,0x1b0000,0),struct.pack('<6I',0x32,24,2,0x0d0000,0x1b0000,0));(self.a/m.EXECUTABLE).write_bytes(raw)
  with self.assertRaises(m.Rejected):self.verify()
 def test_fake_dwarf_data_not_accepted_by_uuid_text(self):
  (self.a/m.DWARF).write_bytes(fat(2))
  with self.assertRaises(m.Rejected):self.verify()
 def test_unequal_uuids_rejected(self):
  raw=uuid_output(self.a).replace(UUIDS['arm64'].encode(),b'FFFFFFFF-2222-3333-4444-555555555555',1)
  with self.assertRaises(m.Rejected):m.matching_uuid(raw,self.a/m.EXECUTABLE,self.a/m.DWARF)
 def test_privacy_change_identifies_resource(self):
  p=self.a/m.APP/'Contents/Resources/PrivacyInfo.xcprivacy';p.write_bytes(plistlib.dumps({}))
  with self.assertRaises(m.Rejected):self.verify()
  self.assertEqual(self.report['offending_path'],str(p.relative_to(self.a)))
 def test_distribution_identity_is_not_unsigned_qualification(self):
  p=self.a/'Info.plist';v=plistlib.loads(p.read_bytes());v['ApplicationProperties']['SigningIdentity']='Developer ID';p.write_bytes(plistlib.dumps(v))
  with self.assertRaises(m.Rejected):self.verify()
 def test_dsym_version_missing_or_default_is_observation(self):
  p=self.a/m.DSYM/'Contents/Info.plist';v=plistlib.loads(p.read_bytes());v.pop('CFBundleVersion');p.write_bytes(plistlib.dumps(v));proof=self.verify();self.assertEqual(proof['dSYM_version_observations']['CFBundleVersion']['comparison'],'missing')
 def test_archive_mutation_during_uuid_query_rejected(self):
  old=self.invoke
  def mutate(argv,**kw):
   raw=old(argv,**kw)
   if argv[0]=='xcrun':(self.a/m.APP/'Contents/Resources/late.bin').write_bytes(b'late')
   return raw
  with self.assertRaises(m.Rejected):m.verify_archive(self.a,mutate,1000,root=self.root,clock=self.clock,report=self.report)
class SourceAndClock(unittest.TestCase):
 def test_pure_macho_functions_match_reviewed_mature_parser(self):
  f=json.loads((ROOT/'scripts/fixtures/mac-archive-inputs.json').read_bytes());raw=(ROOT/'scripts/mac_archive_macho.py').read_text();tree=ast.parse(raw)
  for n in tree.body:
   if isinstance(n,ast.FunctionDef):self.assertEqual(hashlib.sha256(ast.get_source_segment(raw,n).encode()).hexdigest(),f['mature_functions'][n.name])
 def test_all_fifty_product_inputs_unchanged(self):
  f=json.loads((ROOT/'scripts/fixtures/mac-archive-inputs.json').read_bytes());self.assertEqual(len(f['app_inputs']),50)
  for path,h in f['app_inputs'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h,path)
 def test_fixed_archive_has_no_signing_launch_or_test(self):
  a=m.ARCHIVE_COMMAND;self.assertEqual(a[-1],'archive');self.assertIn('CODE_SIGNING_ALLOWED=NO',a);self.assertIn('ARCHS=arm64 x86_64',a);self.assertIn('generic/platform=macOS',a)
  for bad in ['test','test-without-building','allowProvisioning','exportArchive','codesign']:self.assertFalse(any(bad==x or bad in x.lstrip('-') for x in a if x.startswith('-')),bad)
 def test_workflow_uploads_only_proof_and_is_push_once(self):
  w=(ROOT/m.WORKFLOW).read_text();self.assertIn('path: build/archive-proof/report.json',w);self.assertIn('timeout-minutes: 20',w);self.assertEqual(w.count('runs-on: xcode-27'),1)
  for bad in ['workflow_dispatch','matrix:','retry','*.xcarchive','*.app']:self.assertNotIn(bad,w)
 def test_command_cleanup_has_separate_reserve(self):
  c=Clock();receipts=[]
  def runner(argv,**kw):self.assertEqual(kw['seconds'],20);c.advance(1);return subprocess.CompletedProcess(argv,0,b'ok',b'')
  self.assertEqual(m.command(['safe'],deadline=124,seconds=30,cap=20,receipts=receipts,clock=c,runner=runner,cleanup=2),b'ok');self.assertEqual(receipts[0]['cleanup_reserve_seconds'],4)
 def test_late_return_never_qualifies(self):
  c=Clock()
  def runner(argv,**kw):c.advance(kw['seconds']+1);return subprocess.CompletedProcess(argv,0,b'',b'')
  with self.assertRaises(m.Rejected):m.command(['safe'],deadline=130,seconds=10,cap=20,receipts=[],clock=c,runner=runner)
 def test_unconfirmed_capture_stops_without_followup(self):
  def runner(*a,**k):raise m.CaptureStopped('uncertain',False)
  rows=[]
  with self.assertRaises(m.Rejected):m.command(['safe'],deadline=130,seconds=10,cap=20,receipts=rows,clock=Clock(),runner=runner)
  self.assertEqual(len(rows),1);self.assertFalse(rows[0]['owned_cleanup_confirmed'])
 def test_report_overflow_preserves_bounded_catalogue_and_identity(self):
  report={'schema':1,'qualified':True,'clock':{'report_ready_deadline':200},'source_before':{'GITHUB_SHA':'a'*40},'archive_inventory':{'complete':True,'paths':{'Assets.car':{'bytes':4}}},'archive_metadata_diagnostics':{'Info.plist':{'read_error':{'type':'InvalidFileException','reason':'Invalid file'}}},'commands':['x'*(m.MAX_REPORT+1)]}
  v=json.loads(m.report_bytes(report));self.assertFalse(v['qualified']);self.assertEqual(v['archive_inventory'],report['archive_inventory']);self.assertEqual(v['source_before'],report['source_before']);self.assertEqual(v['archive_metadata_diagnostics'],report['archive_metadata_diagnostics'])
 def test_uuid_missing_or_duplicate_slice_rejected(self):
  with self.assertRaises(m.Rejected):m.matching_uuid(b'',Path('app'),Path('dwarf'))
 def test_dwarf_overlap_or_wrong_kind_rejected(self):
  raw=bytearray(fat(10));struct.pack_into('>I',raw,8+20+8,48)
  with self.assertRaises(m.Rejected):m.dwarf_headers(bytes(raw))
  with self.assertRaises(m.Rejected):m.dwarf_headers(thin(CPUS[0],2))

class ExecuteAndRetention(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.clock=Clock();self.calls=[];self.fail_archive=False
  self.identity={'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':m.BRANCH,'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,'GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'archive','DEVELOPER_DIR':'/Applications/Xcode_27.app/Contents/Developer','GITHUB_EVENT_NAME':'push','GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'1'}
 def tearDown(self):self.temp.cleanup()
 def runner(self,argv,**kwargs):
  self.calls.append(argv);raw=b'';code=0
  if argv==['xcodebuild','-version']:raw=b'Xcode 27.0\nBuild version 27A266a\n'
  elif argv==['xcodebuild','-showsdks']:raw=b'macosx27.0\n'
  elif argv==['sw_vers']:raw=b'ProductVersion: 27.0\nBuildVersion: 26A428\n'
  elif argv==m.ARCHIVE_COMMAND:
   if self.fail_archive:code=65;raw=b'Archive failed, bounded compiler details'
   else:fixture(self.root)
  elif argv[:3]==['xcrun','dwarfdump','--uuid']:raw=uuid_output(self.root/m.ARCHIVE)
  self.clock.advance(.1);return subprocess.CompletedProcess(argv,code,raw,b'')
 def execute(self):
  with patch.object(m,'source_identity',return_value=dict(self.identity)):
   return m.execute(env=self.identity,root=self.root,clock=self.clock,runner=self.runner)
 def test_full_fixed_pipeline_qualifies_proof_only(self):
  r=self.execute();self.assertTrue(r['qualified'],r.get('failure'));self.assertFalse(r['binary_handoff']);self.assertFalse(r['signing_qualified']);self.assertFalse(r['store_qualified']);self.assertEqual(self.calls.count(m.ARCHIVE_COMMAND),1)
  output=self.root/'build/archive-proof';marker=self.root/'step-output';marker.write_text('');decoded=m.retain_report(r,output,marker,clock=self.clock)
  self.assertTrue(decoded['qualified']);self.assertTrue(decoded['archive_inventory']['complete']);self.assertEqual(set(x.name for x in output.iterdir()),{'report.json'});self.assertEqual(marker.read_text(),'evidence_ready=true\n')
 def test_archive_failure_keeps_native_diagnostic_and_never_proves_or_retries(self):
  self.fail_archive=True;r=self.execute();self.assertFalse(r['qualified']);self.assertEqual(r['failure']['phase'],'archive');self.assertEqual(self.calls.count(m.ARCHIVE_COMMAND),1);self.assertEqual(self.calls[-1],m.ARCHIVE_COMMAND)
  self.assertIn('bounded compiler details',r['commands'][-1]['stdout']);self.assertNotIn('proof',r)
 def check_metadata_failure(self,path,key,value,reason):
  original=self.runner
  def mutate(argv,**kwargs):
   result=original(argv,**kwargs)
   if argv==m.ARCHIVE_COMMAND:
    p=self.root/m.ARCHIVE/path;v=plistlib.loads(p.read_bytes());v[key]=value;p.write_bytes(plistlib.dumps(v))
   return result
  with patch.object(self,'runner',side_effect=mutate):r=self.execute()
  self.assertFalse(r['qualified']);self.assertNotIn('proof',r);self.assertEqual(r['failure']['phase'],'proof');self.assertIn(reason,r['failure']['reason']);self.assertEqual(r['failure']['offending_path'],path)
  self.assertTrue(r['archive_inventory']['complete']);self.assertEqual(self.calls.count(m.ARCHIVE_COMMAND),1)
  rows=r['archive_metadata_diagnostics'];self.assertEqual(set(rows),{'Info.plist',m.APP+'/Contents/Info.plist',m.DSYM+'/Contents/Info.plist'})
  for name,row in rows.items():self.assertEqual(row['metadata'],plistlib.loads((self.root/m.ARCHIVE/name).read_bytes()))
  self.assertEqual(rows[path]['metadata'][key],value)
  output=self.root/'build/archive-proof';marker=self.root/'step-output';marker.write_text('')
  retained=m.retain_report(r,output,marker,clock=self.clock);self.assertEqual(retained['archive_metadata_diagnostics'][path]['metadata'][key],value)
  overflow=json.loads(m.report_bytes(r|{'commands':['x'*(m.MAX_REPORT+1)]}))
  self.assertEqual(overflow['archive_metadata_diagnostics'],retained['archive_metadata_diagnostics']);self.assertEqual(overflow['failure']['original_failure'],r['failure']);self.assertFalse(overflow['qualified'])
 def test_archive_version_failure_retains_all_three_plists(self):
  self.check_metadata_failure('Info.plist','ArchiveVersion',999,'archive-metadata-mismatch')
 def test_application_version_failure_retains_all_three_plists(self):
  self.check_metadata_failure(m.APP+'/Contents/Info.plist','CFBundleVersion','unexpected-build','application-identity-mismatch')
 def test_dsym_identity_failure_retains_all_three_plists(self):
  self.check_metadata_failure(m.DSYM+'/Contents/Info.plist','CFBundleIdentifier','unexpected.dsym','dSYM-metadata-mismatch')
 def test_source_failure_starts_no_command(self):
  with patch.object(m,'source_identity',side_effect=m.Rejected('source mismatch')):r=m.execute(env=self.identity,root=self.root,clock=self.clock,runner=self.runner)
  self.assertFalse(r['qualified']);self.assertEqual(self.calls,[])
 def test_late_report_cannot_emit_upload_marker(self):
  r=self.execute();r['clock']['report_ready_deadline']=self.clock();marker=self.root/'output';marker.write_text('prior\n')
  result=m.retain_report(r,self.root/'build/proof',marker,clock=self.clock);self.assertFalse(result['qualified']);self.assertEqual(marker.read_text(),'prior\n')
 def test_full_upload_reserve_is_required_and_failed_action_stays_failed(self):
  r=self.execute();r['upload_observation']=m.admit_upload(r,clock=self.clock)
  self.assertFalse(m.finish_upload(r,'failure',clock=self.clock)['upload_qualified']);self.assertTrue(m.finish_upload(r,'success',clock=self.clock)['upload_qualified'])
  self.clock.value=r['clock']['started_monotonic']+m.PHASE_END['evidence']-59
  with self.assertRaises(m.Rejected):m.admit_upload(r,clock=self.clock)
 def test_late_upload_does_not_reset_deadline(self):
  r=self.execute();r['upload_observation']=m.admit_upload(r,clock=self.clock);self.clock.advance(61);self.assertFalse(m.finish_upload(r,'success',clock=self.clock)['upload_qualified'])
 def test_retry_and_dispatch_identity_rejected(self):
  self.assertEqual(m.environment(self.identity),self.identity)
  for key,value in [('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/main')]:
   with self.subTest(key=key),self.assertRaises(m.Rejected):m.environment(self.identity|{key:value})

if __name__=='__main__':unittest.main()
