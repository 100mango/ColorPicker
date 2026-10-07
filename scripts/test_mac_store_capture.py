"""Portable source, failure and retention contracts. Native capture remains unrun."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mac_store_capture as m
import mac_store_contract as contract
from test_mac_store_png import png
from test_mac_store_source_helpers import restore_store_app,restore_store_ui,STORE_CLASS,STORE_SETUP,STORE_METHODS

CHECKOUT=Path(__file__).resolve().parents[1]
SHA='a'*40;TREE='b'*40;TOKEN='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'


class Clock:
    def __init__(self):self.value=100.
    def __call__(self):return self.value
    def advance(self,value):self.value+=value


def env():
    return {'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':m.BRANCH,
        'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/'+m.WORKFLOW+'@'+m.BRANCH,
        'GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'capture','GITHUB_EVENT_NAME':'push',
        'GITHUB_SHA':SHA,'GITHUB_WORKFLOW_SHA':SHA,'GITHUB_RUN_ID':'123',
        'DEVELOPER_DIR':'/Applications/Xcode_27.app/Contents/Developer'}


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def exported(start,product,failed=False):
    counts={'passedTests':0 if failed else 1,'failedTests':1 if failed else 0,'skippedTests':0,'expectedFailures':0}
    identity='TouchColorMacUITests/'+m.CASE+'()'
    url='test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+m.CASE
    summary={**counts,'totalTestCount':1,'result':'Failed' if failed else 'Passed','startTime':start+.1,'finishTime':start+1.8,
        'devicesAndConfigurations':[{**counts,'device':{'deviceId':'owned-Mac','platform':'macOS','architecture':'arm64','osVersion':'27.0'},
            'testPlanConfiguration':{'configurationName':'Test Scheme Action'}}],
        'testFailures':[{'testIdentifierString':identity,'testIdentifierURL':url}] if failed else []}
    items=[];files={}
    for index,(state,count) in enumerate(contract.STATES.items()):
        raw=png(color=(35+index,90,170));captured=start+.4+index*.6
        row={'v':1,'state':state,'token':TOKEN,'pid':456,'test':'-[TouchColorMacUITests '+m.CASE+']',
            'started':start+.2,'captured':captured,'sequential':True,'args':contract.ARGS,'sandbox':False,
            'bundle':'com.mango.touchColor',**product,'expectedPath':product['applicationPath'],
            'imageName':'Native Mac Store window '+state,'pngSHA256':contract.digest(raw),'pngBytes':len(raw),
            'width':1280,'height':800,'windowFrame':[10.,20.,1280.,800.],'sampleHex':'#ff00ff','paletteCount':count}
        for offset,(kind,ext,data) in enumerate([('window','png',raw),('proof','txt',encoded(row))]):
            uid='00000000-0000-4000-8000-'+str(index*2+offset+1).zfill(12);filename=uid+'.'+ext;files[filename]=data
            items.append({'configurationName':'Test Scheme Action','deviceId':'owned-Mac','deviceName':'My Mac',
                'exportedFileName':filename,'isAssociatedWithFailure':False,
                'suggestedHumanReadableName':'Native Mac Store '+kind+' '+state+'_0_'+uid+'.'+ext,'timestamp':captured+.01+offset*.01})
    files['manifest.json']=encoded([{'testIdentifier':identity,'testIdentifierURL':url,'attachments':items}])
    return summary,files


def release_projection(text):
    active=[True];out=[]
    for line in text.splitlines(keepends=True):
        directive=line.strip()
        if directive=='#if DEBUG':active.append(False)
        elif directive=='#else':active[-1]=active[-2] and not active[-1]
        elif directive=='#endif':active.pop()
        elif directive.startswith('#if '):raise ValueError('unknown conditional')
        elif active[-1]:out.append(line)
    if len(active)!=1:raise ValueError('unbalanced DEBUG')
    return ''.join(out)


class SourceTests(unittest.TestCase):
    def test_only_exact_debug_additions_and_new_test_are_removed(self):
        f=json.loads((CHECKOUT/'scripts/fixtures/mac-store-source-baseline.json').read_bytes())
        app=(CHECKOUT/'TouchColorMac/TouchColorMacApp.swift').read_text();ui=(CHECKOUT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        self.assertEqual(hashlib.sha256(restore_store_app(app).encode()).hexdigest(),f['original_app_inputs']['TouchColorMac/TouchColorMacApp.swift'])
        self.assertEqual(hashlib.sha256(restore_store_ui(ui).encode()).hexdigest(),f['ui_sha256'])
        self.assertEqual(release_projection(app),release_projection(restore_store_app(app)))
        self.assertNotIn('MacStoreCapture',release_projection(app))
    def test_fifty_product_inputs_have_one_controlled_debug_difference(self):
        f=json.loads((CHECKOUT/'scripts/fixtures/mac-store-source-baseline.json').read_bytes());self.assertEqual(len(f['original_app_inputs']),50)
        self.assertEqual([k for k in f['original_app_inputs'] if f['original_app_inputs'][k]!=f['current_app_inputs'][k]],['TouchColorMac/TouchColorMacApp.swift'])
        for path,value in f['current_app_inputs'].items():self.assertEqual(hashlib.sha256((CHECKOUT/path).read_bytes()).hexdigest(),value,path)
    def test_resize_gate_is_debug_token_scoped_and_only_existing_window(self):
        self.assertIn('UUID(uuidString: token)?.uuidString == token',STORE_CLASS)
        self.assertIn('suite.hasPrefix("TouchColor.mac-ui.")',STORE_CLASS)
        self.assertIn('guard !applied, let window else { return }',STORE_CLASS)
        self.assertLess(STORE_CLASS.index('applied = true'),STORE_CLASS.index('window.setFrame'))
        for bad in ['NSWindow(', 'NSApp','NSApplication','activate','makeKey','openWindow','Timer','DispatchQueue','UserDefaults']:
            self.assertNotIn(bad,STORE_CLASS)
        self.assertEqual(STORE_CLASS.count('window.setFrame'),1)
    def test_case_uses_real_product_actions_and_original_png(self):
        self.assertIn('try makePhotosFixture(at: imageURL)',STORE_METHODS);self.assertEqual(STORE_METHODS.count('app.typeKey("v", modifierFlags: [.command, .shift])'),2)
        self.assertIn('let png = window.screenshot().pngRepresentation',STORE_METHODS)
        self.assertIn('XCTAssertEqual(app.sheets.count, 0)',STORE_METHODS);self.assertIn('XCTAssertEqual(app.dialogs.count, 0)',STORE_METHODS)
        for bad in ['app.launch()', 'NSWorkspace', 'NSWindow(', 'resize(', 'cropped(', 'draw(', 'AppleLanguages','AppleLocale']:
            self.assertNotIn(bad,STORE_METHODS+STORE_SETUP)
    def test_single_build_test_and_fixed_push_workflow(self):
        argv=m.test_command();self.assertEqual(argv[-1],'test-without-building');self.assertEqual([x for x in argv if x.startswith('-only-testing:')],['-only-testing:TouchColorMacUITests/TouchColorMacUITests/'+m.CASE])
        self.assertNotIn('-test-iterations',argv);self.assertIn('120',argv)
        text=(CHECKOUT/m.WORKFLOW).read_text();self.assertIn('timeout-minutes: 25',text);self.assertEqual(text.count('runs-on: xcode-27'),1)
        for bad in ['matrix:','workflow_dispatch','retry','continue-on-error','*.xcarchive','allowProvisioning']:self.assertNotIn(bad,text)
        self.assertIn('path: build/mac-store-proof/',text)
    def test_fixed_environment_excludes_retries_dispatch_and_other_branches(self):
        self.assertEqual(m.environment(env()),env())
        for key,value in [('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/main')]:
            with self.subTest(key=key),self.assertRaises(m.Rejected):m.environment(env()|{key:value})
    def test_concrete_cohort_and_packet_caps(self):
        self.assertEqual(m.PHASE_END['finalization']+60,1310);self.assertEqual(1500-1310,190)
        self.assertEqual(contract.MAX_PACKET,14*1024*1024);self.assertEqual(m.MAX_REPORT,2*1024*1024)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.old=Path.cwd();os.chdir(self.root)
        self.clock=Clock();self.calls=[];self.failed=False;self.zero=False;self.late=False;self.mutate=None;self.late_summary=False;self.cleanup_unknown=False
        app=self.root/'build/mac-tests/Build/Products/Debug/TouchColor.app'
        self.product={'applicationPath':str(app),'executable':str(app/'Contents/MacOS/TouchColor'),'executableSHA256':'c'*64,'logicSHA256':'d'*64}
        source=m.source_identity
        self.source_patch=patch.object(m,'source_identity',side_effect=lambda e,run,root:source(e,run,CHECKOUT));self.source_patch.start()
        self.product_patch=patch.object(m,'product_identity',side_effect=lambda:dict(self.product));self.product_patch.start()
    def tearDown(self):
        self.product_patch.stop();self.source_patch.stop();os.chdir(self.old);self.temp.cleanup()
    def runner(self,argv,**kwargs):
        self.calls.append(argv);raw=b'';code=0
        if argv[0]=='git':
            if argv[1:]==['rev-parse','HEAD']:raw=(SHA+'\n').encode()
            elif argv[1:]==['rev-parse',m.BASE+'^{tree}']:raw=(m.BASE_TREE+'\n').encode()
            elif argv[1:]==['rev-parse','HEAD^{tree}']:raw=(TREE+'\n').encode()
            elif argv[1]=='rev-list':raw=(SHA+' '+m.BASE+'\n').encode()
            elif argv[1]=='diff':raw=('\n'.join(sorted(['A\t'+x for x in m.NEW_PATHS]+['M\t'+x for x in m.MODIFIED_PATHS]))+'\n').encode()
            else:self.assertEqual(argv[1],'status')
        elif argv==['sw_vers','-buildVersion']:raw=b'26A428\n'
        elif argv==['uname','-m']:raw=b'arm64\n'
        elif argv==['xcodebuild','-version']:raw=b'Xcode 27.0\nBuild version 27A266a\n'
        elif argv==m.base_command()+['build-for-testing']:pass
        elif argv==m.test_command():
            if self.cleanup_unknown:raise m.CaptureStopped('unconfirmed owned capture',False)
            self.summary,self.files=exported(self.clock(),self.product,self.failed)
            if self.zero:self.summary.update(totalTestCount=0,passedTests=0,failedTests=0)
            if self.late_summary:self.summary['finishTime']+=300
            self.clock.advance(301 if self.late else 2);code=65 if self.failed else 0
        elif argv[:5]==['xcrun','xcresulttool','get','test-results','summary']:raw=encoded(self.summary)
        elif argv[:3]==['xcrun','xcresulttool','export']:
            folder=self.root/m.EXPORT;folder.mkdir(parents=True)
            if self.mutate:self.mutate(self.files)
            for name,data in self.files.items():(folder/name).write_bytes(data)
        else:self.assertIn('unittest',argv)
        self.clock.advance(.1);return subprocess.CompletedProcess(argv,code,raw,b'')
    def execute(self):return m.execute(env=env(),root=self.root,clock=self.clock,wall=self.clock,runner=self.runner)
    def retained(self):
        result=self.execute();self.assertTrue(result['qualified'],result.get('failure'));marker=self.root/'output';marker.write_text('')
        value=m.retain_report(result,self.root/m.OUTPUT,marker,root=self.root,clock=self.clock)
        m.validate_packet(self.root/m.OUTPUT,sha=SHA,tree=TREE,run_id=123,source_root=CHECKOUT)
        return value,marker
    def test_success_retains_two_native_and_two_rgb_files_pending_visual_review(self):
        value,marker=self.retained();self.assertEqual(len(value['commands']),21);self.assertEqual(set(value['image_files']),set(m.IMAGE_NAMES))
        self.assertFalse(value['store_qualified']);self.assertEqual(value['visual_acceptance'],'pending-human-review');self.assertEqual(marker.read_text(),'evidence_ready=true\n')
        self.assertEqual(self.calls.count(m.base_command()+['build-for-testing']),1);self.assertEqual(self.calls.count(m.test_command()),1)
    def test_original_failed_case_stays_failed_and_no_export(self):
        self.failed=True;value=self.execute();self.assertFalse(value['qualified']);self.assertEqual(value['test_outcome'],'failed');self.assertEqual(value['image_files'],{})
        self.assertEqual(len(self.calls),14);self.assertNotIn('export',self.calls[-1])
    def test_zero_case_fails_before_export(self):
        self.zero=True;value=self.execute();self.assertFalse(value['qualified']);self.assertEqual(len(self.calls),14)
    def test_late_summary_fails_before_export(self):
        self.late_summary=True;value=self.execute();self.assertFalse(value['qualified']);self.assertEqual(len(self.calls),14)
    def test_native_test_late_return_stops_before_evidence(self):
        self.late=True;value=self.execute();self.assertFalse(value['qualified']);self.assertEqual(len(self.calls),13)
    def test_uncertain_cleanup_never_starts_evidence_or_retries(self):
        self.cleanup_unknown=True;value=self.execute();self.assertFalse(value['qualified']);self.assertFalse(value['commands'][-1]['owned_cleanup_confirmed']);self.assertEqual(len(self.calls),13)
    def test_wrong_pid_on_second_capture_rejects_packet(self):
        def mutate(files):
            name=sorted(x for x in files if x.endswith('.txt'))[-1];r=json.loads(files[name]);r['pid']+=1;files[name]=encoded(r)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('second-launch',value['failure']['reason'])
    def test_wrong_product_hash_rejects_packet(self):
        def mutate(files):
            name=next(x for x in files if x.endswith('.txt'));r=json.loads(files[name]);r['logicSHA256']='f'*64;files[name]=encoded(r)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('capture-product',value['failure']['reason'])
    def test_image_digest_mismatch_rejects_packet(self):
        def mutate(files):
            name=next(x for x in files if x.endswith('.txt'));r=json.loads(files[name]);r['pngSHA256']='f'*64;files[name]=encoded(r)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('pixel-binding',value['failure']['reason'])
    def test_transparency_keeps_bound_originals_but_fails_store_format(self):
        def mutate(files):
            groups=json.loads(files['manifest.json']);image=groups[0]['attachments'][0]['exportedFileName'];record=groups[0]['attachments'][1]['exportedFileName']
            files[image]=png(alpha=254);row=json.loads(files[record]);row['pngSHA256']=contract.digest(files[image]);row['pngBytes']=len(files[image]);files[record]=encoded(row)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertEqual(value['source_after'],value['source_before'])
        self.assertIn('native-sampling.png',value['image_files']);self.assertNotIn('store-sampling.png',value['image_files']);self.assertIn('sampling',value['proof']['formatFailures'])
        marker=self.root/'output';marker.write_text('');retained=m.retain_report(value,self.root/m.OUTPUT,marker,root=self.root,clock=self.clock)
        self.assertFalse(retained['qualified']);self.assertTrue((self.root/m.OUTPUT/'native-sampling.png').is_file())
    def test_exported_foreign_case_rejects_packet(self):
        def mutate(files):
            groups=json.loads(files['manifest.json']);groups[0]['testIdentifier']='Another/test()';files['manifest.json']=encoded(groups)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('foreign-exported',value['failure']['reason'])
    def test_unsafe_exported_name_rejects_packet(self):
        def mutate(files):
            groups=json.loads(files['manifest.json']);groups[0]['attachments'][0]['exportedFileName']='../other.png';files['manifest.json']=encoded(groups)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('file-name',value['failure']['reason'])
    def test_wrong_frame_rejects_packet(self):
        def mutate(files):
            name=next(x for x in files if x.endswith('.txt'));r=json.loads(files[name]);r['windowFrame'][2]=1024;files[name]=encoded(r)
        self.mutate=mutate;value=self.execute();self.assertFalse(value['qualified']);self.assertIn('window-size',value['failure']['reason'])
    def test_retained_image_tampering_is_rejected(self):
        self.retained();p=self.root/m.OUTPUT/'store-sampling.png';p.write_bytes(p.read_bytes()+b'x')
        with self.assertRaises(m.Rejected):m.validate_packet(self.root/m.OUTPUT,sha=SHA,tree=TREE,run_id=123,source_root=CHECKOUT)
    def test_forged_source_or_visual_acceptance_is_rejected(self):
        self.retained();p=self.root/m.OUTPUT/'report.json';original=json.loads(p.read_bytes())
        for key,value in [('store_qualified',True),('visual_acceptance','approved')]:
            changed=copy.deepcopy(original);changed[key]=value;p.write_bytes(m.report_bytes(changed))
            with self.subTest(key=key),self.assertRaises(m.Rejected):m.validate_packet(self.root/m.OUTPUT,sha=SHA,tree=TREE,run_id=123,source_root=CHECKOUT)
        p.write_bytes(m.report_bytes(original))
        with self.assertRaises(m.Rejected):m.validate_packet(self.root/m.OUTPUT,sha='e'*40,tree=TREE,run_id=123,source_root=CHECKOUT)
    def test_upload_full_reserve_and_original_clock_are_required(self):
        value,_=self.retained();value['upload_observation']=m.admit_upload(value,clock=self.clock)
        self.assertTrue(m.finish_upload(value,'success',clock=self.clock)['upload_qualified']);self.assertFalse(m.finish_upload(value,'failure',clock=self.clock)['upload_qualified'])
        self.clock.advance(61);self.assertFalse(m.finish_upload(value,'success',clock=self.clock)['upload_qualified'])
    def test_retention_lateness_never_emits_upload_marker(self):
        value=self.execute();self.assertTrue(value['qualified']);value['clock']['report_ready_deadline']=self.clock();marker=self.root/'output';marker.write_text('previous\n')
        with self.assertRaises(m.Rejected):m.retain_report(value,self.root/m.OUTPUT,marker,root=self.root,clock=self.clock)
        self.assertEqual(marker.read_text(),'previous\n')
    def test_oversized_report_does_not_publish_images_as_qualified(self):
        value=self.execute();value['commands']=['x'*(m.MAX_REPORT+1)];decoded=json.loads(m.report_bytes(value));self.assertFalse(decoded['qualified']);self.assertEqual(decoded['image_files'],{})


if __name__=='__main__':unittest.main()
