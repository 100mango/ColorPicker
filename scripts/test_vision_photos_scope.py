"""Selective Photos completion adversaries; no native execution claim."""
import ast
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
import native_text_rows as rows
import vision_photos_scope as scope
from native_text_evidence import requirements
from test_native_text_rows import environment

ROOT=Path(__file__).resolve().parents[1]
SHA='a'*40
DEVICE='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'


class PhotosCompletionTests(unittest.TestCase):
    def binding(self):return rows.row('vision','normal','photos','',SHA,qualification_scope='photos-only')

    def test_only_exact_photos_normal_scope_can_omit_current_hosted_role(self):
        binding=self.binding();self.assertEqual(rows.validate(binding),binding)
        self.assertEqual(rows.vision_roles(binding),['normal'])
        canonical=rows.row('vision','normal','photos','',SHA)
        self.assertEqual(rows.vision_roles(canonical),['hosted','normal'])
        for args in [('vision','normal','chinese',''),('vision','system-largest','chinese',''),('watch','normal','','smallest')]:
            with self.assertRaises(ValueError):rows.row(*args,SHA,qualification_scope='photos-only')
        with self.assertRaises(ValueError):rows.row('vision','normal','photos','',SHA,qualification_scope='anything')
        with self.assertRaises(ValueError):rows.validate(dict(canonical,schema=3))

    def test_current_environment_must_explicitly_match_scope(self):
        binding=self.binding();env=environment(binding);env[scope.ENV]='photos-only'
        self.assertEqual(rows.from_environment('vision',SHA,env),binding)
        with self.assertRaises(ValueError):rows.report_binding({'sha':SHA,'native_text_row':binding},environment(binding))
        env[scope.ENV]='foreign'
        with self.assertRaises(ValueError):rows.from_environment('vision',SHA,env)

    def test_actual_hosted_inputs_match_verified_historical_42_case_reference(self):
        proof=scope.verify_reuse(ROOT)
        self.assertFalse(proof['executed_this_job'])
        self.assertTrue(proof['source_inputs_verified'])
        self.assertEqual(proof['reference']['source_sha'],'c29fb2df383a328b42b7b86e26a580407459f1c2')
        self.assertEqual(proof['reference']['run'],37408865228)
        self.assertEqual(proof['reference']['job'],112093901243)
        self.assertEqual(proof['reference']['hosted_count'],42)
        self.assertTrue(proof['reference']['hosted_qualified'])

    def copy_reference(self,root):
        reference=scope.reference(ROOT)
        for name in [scope.REFERENCE_NAME,*[item['path'] for item in reference['inputs']]]:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
        return reference

    def test_changed_missing_added_and_symlinked_input_reject_reuse(self):
        for kind in ('changed','missing','added','symlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve();reference=self.copy_reference(root);p=root/reference['inputs'][0]['path']
                if kind=='changed':p.write_bytes(p.read_bytes()+b'X')
                elif kind=='missing':p.unlink()
                elif kind=='added':(root/'TouchColorVision/Unexpected.swift').write_text('// new source')
                else:p.unlink();p.symlink_to(ROOT/reference['inputs'][0]['path'])
                with self.assertRaises(ValueError):scope.verify_reuse(root)

    def test_ancestor_symlink_root_has_the_same_canonical_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            top=Path(folder).resolve();parent=top/'actual';parent.mkdir();root=parent/'fixture';root.mkdir()
            self.copy_reference(root)
            alias=top/'alias';alias.symlink_to(parent,target_is_directory=True)
            self.assertEqual(scope.verify_reuse(alias/'fixture'),scope.verify_reuse(root))
            self.assertEqual(scope.reference(alias/'fixture'),scope.reference(root))

    def test_changed_reference_cannot_relabel_old_failed_hosted_as_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();self.copy_reference(root)
            p=root/scope.REFERENCE_NAME;j=json.loads(p.read_text());j['job']=112093901212;p.write_text(json.dumps(j))
            with self.assertRaises(ValueError):scope.verify_reuse(root)

    def test_report_requires_explicit_reuse_and_rejects_current_hosted_claim(self):
        good={'hosted_reuse':scope.verify_reuse(ROOT),'stages':[]};scope.validate_reuse_report(good)
        for changed in ({},dict(good,vision_hosted_result={'status':'hosted_result_passed'}),dict(good,xctest_summary={'passedTests':42}),
                        dict(good,stages=[{'command':['xcodebuild','test-without-building','-only-testing:TouchColorVisionTests']}])):
            with self.assertRaises(ValueError):scope.validate_reuse_report(changed)

    def test_photos_still_requires_current_ui_summary_and_actual_import_pixels(self):
        binding=self.binding()
        required,missing=requirements(binding,{'captures':[]},{},{})
        self.assertNotIn('vision-summary.json',required)
        self.assertIn('vision-ui-summary.json',required)
        self.assertIn('vision-runtime.json',required)
        with self.assertRaises(ValueError):requirements(binding,{'captures':[]},{},{'vision-summary.json':{}})
        self.assertIn('Missing or ambiguous checkpoint: Native Vision actual system Photos import',missing)
        canonical=rows.row('vision','normal','photos','',SHA)
        self.assertIn('vision-summary.json',requirements(canonical,{'captures':[]},{},{})[0])

    def test_real_normal_binding_accepts_one_current_photos_result_not_hosted(self):
        import vision_offline_result as offline
        from test_native_text_evidence import summary
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root=Path(folder).resolve();bundle=root/offline.NORMAL_BUNDLE;bundle.mkdir(parents=True)
            (bundle/'Info.plist').write_bytes(b'portable normal result')
            contract={'root':str(root),'project':'TouchColorVision.xcodeproj','scheme':'TouchColorVision',
                      'derived_data':'build/vision-tests','test_bundle':'TouchColorVisionUITests','platform':'visionOS Simulator'}
            name='testRealPhotosImport';command=['xcodebuild','test-without-building','-resultBundlePath',offline.NORMAL_BUNDLE,
                '-destination','platform=visionOS Simulator,id='+DEVICE,'-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+name]
            stage={'command':command,'exit':0,'process_group_gone':True,'capture_reader_finished':True,'reader_errors':[],
                   'cleanup_error':None,'started_at':'1970-01-01T00:00:05+00:00','finished_at':'1970-01-01T00:00:25+00:00'}
            binding=self.binding()
            setting=offline.prepare_normal(command,contract,[name],SHA,DEVICE,'vision-runtime',stage,row_binding=binding)
            self.assertEqual(setting['deferred_result']['native_text_row'],binding)
            self.assertEqual(setting['deferred_result']['role'],'normal')
            report={'sha':SHA,'native_text_row':binding,'vision_offline_case':'photos','vision_offline_expected':['normal'],
                    'vision_normal_result':setting,'hosted_reuse':scope.verify_reuse(ROOT),'stages':[stage]}
            self.assertEqual(offline.expected_roles(report),['normal'])
            result=summary(1,platform='visionOS Simulator')
            result['devicesAndConfigurations'][0]['device']['deviceId']=DEVICE
            result['devicesAndConfigurations'][0]['testPlanConfiguration']={'configurationId':'1','configurationName':'Test Scheme Action'}
            self.assertEqual(offline.verify_offline_summary(result,setting['deferred_result'],DEVICE,role='normal')['passedTests'],1)
            bad=copy.deepcopy(report);bad['vision_offline_expected']=['hosted','normal']
            with self.assertRaises(ValueError):offline.expected_roles(bad)
            bad=copy.deepcopy(report);bad['vision_hosted_result']={'status':'hosted_result_passed'}
            with self.assertRaises(ValueError):offline.expected_roles(bad)

    def test_real_driver_vision_branch_executes_only_one_photos_ui_command(self):
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text())
        block=None
        for node in ast.walk(source):
            if isinstance(node,ast.If) and any(isinstance(child,ast.Call) and isinstance(child.func,ast.Attribute)
                    and child.func.attr=='get' and child.args and isinstance(child.args[0],ast.Constant)
                    and child.args[0].value=='qualification_scope' for child in ast.walk(node)):
                if isinstance(node.test,ast.Compare) and isinstance(node.test.left,ast.Name) and node.test.left.id=='kind':
                    block=node;break
        self.assertIsNotNone(block)
        # Compile the actual Vision branch, without starting the module's native setup.
        module=ast.Module(body=block.body,type_ignores=[]);ast.fix_missing_locations(module)
        report={'sha':SHA,'stages':[],'resources':[{}]};commands=[]
        def run(command,timeout,required=False):
            commands.append(command);report['stages'].append({'exit':0});return 0
        seed=Mock();binding=self.binding()
        context={'text_row':binding,'text_phase':'normal','report':report,'json':json,'print':lambda *a,**k:None,
                 'seed_photos':seed,'photo_seed_failed':False,'skip':[], 'os':os,'Path':Path,
                 'check_output':lambda *a,**k:json.dumps({'devices':{'vision-runtime':[{'state':'Booted','udid':DEVICE,'name':'Apple Vision Pro'}]}}),
                 'device':{'udid':DEVICE},'runtime':'vision-runtime','VISION_CASES':{'photos':('testRealPhotosImport',950000)},
                 'resources':lambda *a:None,'require_responsive':lambda *a:None,'test_common':['xcodebuild','test-without-building'],
                 'test_arguments':[],'run':run,'project':'TouchColorVision.xcodeproj','name':'TouchColorVision','platform':'visionOS',
                 'prepare_vision_normal':lambda *a,**k:{'deferred_result':{'role':'normal'}},'prepare_vision_hosted':Mock(side_effect=AssertionError('hosted must not run'))}
        with patch.dict(os.environ,{'TOUCHCOLOR_VISION_CASE':'photos'},clear=False):exec(compile(module,'<actual Vision branch>','exec'),context)
        seed.assert_called_once();self.assertEqual(len(commands),1)
        self.assertIn('-only-testing:TouchColorVisionUITests/VisionWorkflowTests/testRealPhotosImport',commands[0])
        self.assertFalse(report['hosted_reuse']['executed_this_job'])
        self.assertNotIn('vision_hosted_result',report)
        commands.clear();context['photo_seed_failed']=True
        with patch.dict(os.environ,{'TOUCHCOLOR_VISION_CASE':'photos'},clear=False), self.assertRaisesRegex(RuntimeError,'fixture seed'):
            exec(compile(module,'<actual Vision branch>','exec'),context)
        self.assertEqual(commands,[])


if __name__=='__main__':unittest.main()
