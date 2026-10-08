"""Portable source/byte/omission boundary tests; no native execution claim."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import native_text_evidence as keep
from native_text_rows import row
from native_content_size import WATCH_CASES, verify_summary
from simulator_content_size import LARGEST

SHA = 'a' * 40
DEVICE = '11111111-1111-4111-8111-111111111111'
HELP = 'Usage: simctl ui <device> <option>\n    content_size\n        medium, large, accessibility-extra-extra-extra-large.\n'


def probe_operations(command, original='large'):
    base=['xcrun','simctl','ui',DEVICE,'content_size']
    entries=[('help',['xcrun','simctl','help','ui'],HELP),
             ('device_inventory',['xcrun','simctl','list','devices','-j'],'Bounded inventory diagnostic'),
             ('read_original',base,original+'\n')]
    if original!=LARGEST:entries.append(('set_largest',base+[LARGEST],''))
    entries += [('read_largest',base,LARGEST+'\n'),('actual_ui',command,''),('read_before_restore',base,LARGEST+'\n')]
    if original!=LARGEST:entries.append(('restore_original',base+[original],''))
    entries.append(('read_restored',base,original+'\n'))
    return [{'label':label,'output':output,'operation':{'command':args,'exit':0,'state':'completed',
                'cleanup_confirmed':True,'timeout_seconds':600 if label=='actual_ui' else 15,
                **({'process_group_gone':True,'capture_reader_finished':True,'command_started':True} if label=='actual_ui' else {})}}
            for label,args,output in entries]


def summary(total, skipped=0, platform='watchOS Simulator'):
    counts = {'passedTests': total-skipped, 'failedTests': 0, 'skippedTests': skipped, 'expectedFailures': 0}
    return {'result': 'Passed', 'totalTestCount': total, **counts, 'testFailures': [],
            'startTime': 10, 'finishTime': 20, 'devicesAndConfigurations': [{**counts,
                'device': {'deviceId': DEVICE, 'platform': platform, 'architecture': 'arm64', 'osVersion': '27.0'}}]}


def stage(bundle, selectors):
    return {'command': ['xcodebuild', 'test-without-building', '-destination',
                       'platform=watchOS Simulator,id='+DEVICE, '-resultBundlePath', bundle, *selectors],
            'exit': 0, 'started': True, 'process_group_gone': True, 'capture_reader_finished': True,
            'reader_errors': [], 'cleanup_error': None, 'timed_out': False,
            'started_at': '1970-01-01T00:00:05+00:00', 'finished_at': '1970-01-01T00:00:25+00:00'}


class Fixture:
    def __init__(self, root, platform='watch', phase='system-largest', case='chinese', profile='largest', image_bytes=1000):
        self.root = root
        self.binding = row(platform, phase, case if platform=='vision' else '', profile if platform=='watch' else '', SHA)
        self.runtime = {'platform': platform, 'sha': SHA, 'native_text_row': self.binding,
                        'result': 'passed', 'tests': 'passed', 'device': {'udid': DEVICE}, 'captures': [],
                        'stages': [], 'watch_profile': profile, 'runtime':'com.apple.CoreSimulator.SimRuntime.watchOS-27-0'}
        self.manifests = {}; self.images = []
        (root/'architecture.txt').write_text('Actual source diagnostic remains unchanged\n')
        if platform == 'watch':
            hosted = summary(52, 1); self.write('watch-summary.json', hosted)
            self.runtime['xctest_summary'] = {key: hosted[key] for key in ('result','passedTests','failedTests','skippedTests','totalTestCount')}
            self.runtime['xctest_summary']['failures'] = []
            self.runtime['stages'].append(stage('build/watch-tests.xcresult', ['-only-testing:TouchColorWatchTests']))
            folder = 'watch-ui-screenshots' if phase == 'normal' else 'watch-largest-text-screenshots'
            for method, title in keep.WATCH_PIXELS:
                self.add(folder, title, image_bytes, 'WatchWorkflowTests/'+method+'()')
            if phase == 'normal':
                self.write('watch-ui-summary.json', summary(11, 1))
                self.runtime['normal_watch_ui'] = {'exit': 0, 'result': 'passed', 'stage_index': 1}
                self.runtime['stages'].append(stage('build/watch-ui.xcresult', ['-only-testing:TouchColorWatchUITests',
                    '-skip-testing:TouchColorWatchUITests/WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave']))
            else:
                largest = summary(3); self.write('watch-largest-text-summary.json', largest)
                self.runtime['largest_system_text'] = {'status': 'largest_ui_passed', 'restore_verified': True,
                    'ui_executed': True, 'ui_exit': 0, 'requested_largest': LARGEST, 'observed_largest': LARGEST,
                    'observed_original': 'large', 'observed_restored': 'large', 'device': DEVICE,
                    'verified_results': verify_summary(largest, DEVICE, 'watchOS Simulator', 3),
                    'summary_operation': {'command': ['xcrun','xcresulttool','get','test-results','summary','--path','build/watch-largest-text.xcresult'],
                                          'exit': 0, 'cleanup_confirmed': True,'timeout_seconds':30,'state':'completed'}}
                self.runtime['largest_text_outcome'] = {'result': 'passed'}
                self.runtime['stages'].append(stage('build/watch-largest-text.xcresult',
                    ['-only-testing:TouchColorWatchUITests/WatchWorkflowTests/'+name for name in WATCH_CASES]))
                setting=self.runtime['largest_system_text']
                setting.update(native_text_row=self.binding,runtime=self.runtime['runtime'],
                    operations=probe_operations(self.runtime['stages'][-1]['command']),
                    help_sha256=keep.hashlib.sha256(HELP.strip().encode()).hexdigest(),
                    help_advertised_sizes=['accessibility-extra-extra-extra-large','large','medium'])
        else:
            self.write('vision-summary.json', summary(42, platform='visionOS Simulator'))
            self.write('vision-ui-summary.json' if phase=='normal' else 'vision-largest-text-summary.json', summary(1, platform='visionOS Simulator'))
            for title in keep.VISION_PIXELS[case]:
                name = self.add('vision-checkpoints', title, image_bytes)
                capture = {'name': title, 'file': Path(name).name, 'success': True}
                if phase == 'system-largest': capture['system_text_size'] = LARGEST
                self.runtime['captures'].append(capture)
        self.save()

    def write(self, name, value):
        (self.root/name).write_bytes(keep.encoded(value))

    def add(self, folder, title, size, method=None):
        path = self.root/folder; path.mkdir(exist_ok=True)
        name = str(uuid.uuid4()).upper()+'.png'
        (path/name).write_bytes(b'\x89PNG\r\n\x1a\n'+b'x'*(size-8))
        group = {'attachments': [{'exportedFileName': name, 'suggestedHumanReadableName': title,
                                  'deviceId': DEVICE}]}
        if method: group['testIdentifier'] = method
        self.manifests.setdefault(folder+'/manifest.json', []).append(group)
        self.images.append(folder+'/'+name)
        return folder+'/'+name

    def save(self):
        self.write(self.binding['platform']+'-runtime.json', self.runtime)
        for path, groups in self.manifests.items(): self.write(path, groups)

    def environment(self):
        b = self.binding
        return {'TOUCHCOLOR_JOB_PLATFORM': b['platform'], 'GITHUB_SHA': SHA, 'TOUCHCOLOR_TEXT_PHASE': b['phase'],
                'TOUCHCOLOR_VISION_CASE': b['case'], 'TOUCHCOLOR_WATCH_PROFILE': b['profile'],
                'TOUCHCOLOR_JOB_LANE': b['lane'], 'TOUCHCOLOR_JOB_MINUTES': str(b['minutes']),
                'TOUCHCOLOR_EVIDENCE_LIMIT': str(b['evidence_bytes'])}


class NativeTextEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True); self.env.start(); self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def assertBounded(self, fixture):
        files = [p for p in self.root.rglob('*') if p.is_file()]
        self.assertLessEqual(sum(p.stat().st_size for p in files), fixture.binding['evidence_bytes'])
        self.assertLessEqual(sum(p.stat().st_size for p in files if p.name!='job-budget.json'), fixture.binding['evidence_bytes']-keep.RESERVE)

    def test_watch_largest_complete_preserves_every_original_raw_byte(self):
        fixture = Fixture(self.root)
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name!='manifest.json'}
        result = keep.retain(self.root)
        self.assertTrue(result['complete']); self.assertTrue(keep.evidence_complete(self.root)); self.assertBounded(fixture)
        for path, raw in before.items(): self.assertEqual((self.root/path).read_bytes(), raw)
        self.assertEqual(result['omissions'], {})

    def test_hosted_all_52_pass_or_one_encoder_skip_are_both_allowed(self):
        for skipped in [0,1,2,True]:
            with self.subTest(skipped=skipped),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root);v=summary(52,skipped)
                f.write('watch-summary.json',v)
                f.runtime['xctest_summary']={key:v[key] for key in ('result','passedTests','failedTests','skippedTests','totalTestCount')}
                f.runtime['xctest_summary']['failures']=[];f.save()
                self.assertEqual(keep.retain(root)['complete'],type(skipped) is int and skipped in (0,1))

    def test_watch_hosted_inventory_rejects_old_or_extra_case_counts(self):
        # One new test-only geometry case raises the exact hosted inventory.
        for total in (51, 53):
            with self.subTest(total=total), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root);v=summary(total,1)
                f.write('watch-summary.json',v)
                f.runtime['xctest_summary']={key:v[key] for key in ('result','passedTests','failedTests','skippedTests','totalTestCount')}
                f.runtime['xctest_summary']['failures']=[];f.save()
                self.assertFalse(keep.retain(root)['complete'])

    def test_watch_normal_is_separate_and_retains_other_existing_method_pixels(self):
        fixture = Fixture(self.root, phase='normal')
        extra = fixture.add('watch-ui-screenshots', 'Native Watch persisted ordered palette', 350000,
                            'WatchWorkflowTests/testNativeRGBEditSaveDuplicateAndOfflineRelaunch()')
        fixture.save(); result = keep.retain(self.root)
        self.assertTrue(result['complete']); self.assertIn(extra, result['requiredFiles']); self.assertBounded(fixture)

    def test_actual_cap_keeps_safe_partial_and_explicit_required_pixel_omission(self):
        fixture = Fixture(self.root, image_bytes=230000)
        result = keep.retain(self.root)
        self.assertFalse(result['complete']); self.assertFalse(keep.evidence_complete(self.root)); self.assertBounded(fixture)
        omitted = [name for name in fixture.images if not (self.root/name).exists()]
        self.assertTrue(omitted)
        for name in omitted:
            self.assertTrue(result['omissions'][name]['mandatory'])
            self.assertRegex(result['omissions'][name]['sha256'], '^[0-9a-f]{64}$')
        groups = json.loads((self.root/'watch-largest-text-screenshots/manifest.json').read_text())
        self.assertEqual(sum(len(g['omittedAttachments']) for g in groups), len(omitted))

    def test_aggregate_input_cap_fails_before_large_payload_reads_without_allocation(self):
        f=Fixture(self.root);original=Path.lstat;read=keep.read_file
        image_paths={self.root/name for name in f.images}
        def large_stat(path,*args,**kwargs):
            info=original(path,*args,**kwargs)
            if path in image_paths:
                return SimpleNamespace(st_mode=info.st_mode,st_nlink=info.st_nlink,st_size=keep.MAX_INPUT_BYTES//2)
            return info
        with patch.object(Path,'lstat',large_stat),patch.object(keep,'read_file',wraps=read) as reads:
            with self.assertRaisesRegex(ValueError,'source bytes exceed finite bound'):keep.retain(self.root)
            self.assertFalse(any(call.args[0] in image_paths for call in reads.call_args_list))
        self.assertFalse((self.root/keep.REPORT).exists())
        self.assertTrue(all(path.stat().st_size==1000 for path in image_paths))

    def test_growth_after_scan_still_hits_remaining_aggregate_read_bound(self):
        f=Fixture(self.root);paths=keep.scan(self.root,f.binding)
        # Represent a post-scan growth using a lower aggregate admission bound;
        # actual fixture files are only kilobytes and are never modified.
        with patch.object(keep,'scan',return_value=paths),patch.object(keep,'MAX_INPUT_BYTES',2500):
            with self.assertRaisesRegex(ValueError,'exceeds bounded read'):keep.retain(self.root)
        self.assertFalse((self.root/keep.REPORT).exists())

    def test_missing_runtime_still_uploads_bounded_incomplete_metadata(self):
        fixture = Fixture(self.root)
        (self.root/'watch-runtime.json').unlink()
        with patch.dict(os.environ, fixture.environment()):
            result = keep.retain(self.root)
            self.assertFalse(result['complete']); self.assertFalse(keep.evidence_complete(self.root))
        self.assertIn('watch-runtime.json', result['requiredFiles']); self.assertBounded(fixture)

    def test_missing_raw_role_summary_fails_completeness(self):
        for filename in ['watch-summary.json', 'watch-largest-text-summary.json']:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); Fixture(root); (root/filename).unlink()
                self.assertFalse(keep.retain(root)['complete'])
                self.assertFalse(keep.evidence_complete(root))

    def test_runtime_over_cap_is_omitted_with_original_hash_and_never_qualifies(self):
        fixture = Fixture(self.root); fixture.runtime['diagnostic_padding'] = 'd'*700000; fixture.save()
        result = keep.retain(self.root)
        self.assertFalse(result['complete']); self.assertFalse((self.root/'watch-runtime.json').exists())
        self.assertTrue(result['omissions']['watch-runtime.json']['mandatory']); self.assertBounded(fixture)

    def test_failed_result_and_exact_raw_failure_remain_failed(self):
        fixture = Fixture(self.root); fixture.runtime['result'] = 'failed'; fixture.runtime['failures'] = [{'error':'Original audit failure'}]; fixture.save()
        raw = (self.root/'watch-runtime.json').read_bytes()
        self.assertFalse(keep.retain(self.root)['complete']); self.assertEqual((self.root/'watch-runtime.json').read_bytes(), raw)

    def test_not_started_unsupported_restore_failure_and_public_trait_cannot_pass(self):
        for change in ['not_started', 'unsupported', 'restore', 'public_trait', 'cleanup', 'failed-summary']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); f=Fixture(root)
                if change in ('not_started','unsupported'): f.runtime['largest_system_text']['status']=change
                elif change=='restore': f.runtime['largest_system_text']['restore_verified']=False
                elif change=='public_trait':
                    f.runtime['public_trait_layout']={'status':'public_trait_ui_passed', 'system_propagation_verified':False}
                    f.write('watch-public-trait-summary.json',summary(1))
                elif change=='cleanup': f.runtime['cleanup_unconfirmed']=True
                else:
                    v=summary(3);v['result']='Failed';f.write('watch-largest-text-summary.json',v)
                f.save(); self.assertFalse(keep.retain(root)['complete'])

    def test_public_trait_raw_summary_required_even_if_runtime_omits_key(self):
        f=Fixture(self.root)
        f.add('watch-public-trait-screenshots','Native Watch largest public trait Send and Cancel',1000,
              'WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave()');f.save()
        result=keep.retain(self.root)
        self.assertIn('watch-public-trait-summary.json',result['requiredFiles']);self.assertFalse(result['complete'])

    def test_missing_pixel_before_selection_is_explicit(self):
        f=Fixture(self.root);(self.root/f.images[0]).unlink()
        result=keep.retain(self.root)
        self.assertFalse(result['complete']);self.assertTrue(result['omissions'][f.images[0]]['missing'])

    def test_missing_mandatory_file_after_selection_returns_false(self):
        f=Fixture(self.root);keep.retain(self.root);(self.root/f.images[0]).unlink()
        self.assertFalse(keep.evidence_complete(self.root))

    def test_hash_mutation_after_selection_raises(self):
        f=Fixture(self.root);keep.retain(self.root);(self.root/f.images[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash/bytes changed'):keep.evidence_complete(self.root)

    def test_changed_manifest_and_omission_provenance_raise(self):
        f=Fixture(self.root);keep.retain(self.root)
        manifest=self.root/'watch-largest-text-screenshots/manifest.json'
        value=json.loads(manifest.read_text());value[0]['attachments']=[];manifest.write_bytes(keep.encoded(value))
        with self.assertRaises(ValueError):keep.evidence_complete(self.root)

    def test_changed_required_inventory_raises_even_if_report_is_reencoded(self):
        Fixture(self.root);keep.retain(self.root)
        p=self.root/keep.REPORT;value=json.loads(p.read_text());value['requiredFiles']=[];p.write_bytes(keep.encoded(value))
        with self.assertRaisesRegex(ValueError,'Required proof inventory changed'):keep.evidence_complete(self.root)

    def test_laundering_omission_to_optional_raises(self):
        Fixture(self.root,image_bytes=230000);keep.retain(self.root)
        p=self.root/keep.REPORT;value=json.loads(p.read_text());next(iter(value['omissions'].values()))['mandatory']=False;p.write_bytes(keep.encoded(value))
        with self.assertRaises(ValueError):keep.evidence_complete(self.root)

    def test_wrong_source_row_phase_and_cap_raise(self):
        f=Fixture(self.root);keep.retain(self.root)
        for key,value in [('GITHUB_SHA','b'*40),('TOUCHCOLOR_TEXT_PHASE','normal'),('TOUCHCOLOR_EVIDENCE_LIMIT','2000000'),('TOUCHCOLOR_WATCH_PROFILE','smallest')]:
            env=f.environment();env[key]=value
            with self.subTest(key=key),patch.dict(os.environ,env):
                with self.assertRaises(ValueError):keep.evidence_complete(self.root)

    def test_duplicate_manifest_attachment_and_path_escape_raise(self):
        for kind in ['duplicate','escape']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root);groups=next(iter(f.manifests.values()))
                if kind=='duplicate':groups[0]['attachments'].append(copy.deepcopy(groups[0]['attachments'][0]))
                else:groups[0]['attachments'][0]['exportedFileName']='../watch-runtime.json'
                f.save()
                with self.assertRaises(ValueError):keep.retain(root)

    def test_symlink_hardlink_and_unmanifested_file_raise(self):
        for kind in ['symlink','hardlink','unmanifested']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root);target=root/f.images[0];extra=target.with_name(str(uuid.uuid4()).upper()+'.png')
                if kind=='symlink':extra.symlink_to(target)
                elif kind=='hardlink':os.link(target,extra)
                else:extra.write_bytes(b'unmanifested')
                with self.assertRaises(ValueError):keep.retain(root)

    def test_duplicate_json_and_nonfinite_json_raise(self):
        Fixture(self.root)
        p=self.root/'watch-largest-text-summary.json';p.write_text('{"key": 1, "key": 2}')
        with self.assertRaises(ValueError):keep.retain(self.root)

    def test_job_metadata_refresh_is_allowed_within_its_unchanged_reserve(self):
        f=Fixture(self.root);(self.root/'job-budget.json').write_text('{}')
        self.assertTrue(keep.retain(self.root)['complete'])
        (self.root/'job-budget.json').write_bytes(b'{}'+b' '*(keep.RESERVE-2))
        self.assertTrue(keep.evidence_complete(self.root));self.assertBounded(f)
        (self.root/'job-budget.json').write_bytes(b' '*(keep.RESERVE+1))
        with self.assertRaises(ValueError):keep.evidence_complete(self.root)

    def test_late_budget_failure_never_becomes_evidence_acceptance(self):
        f=Fixture(self.root);self.assertTrue(keep.retain(self.root)['complete'])
        f.write('job-budget.json',{'sha':SHA,'platform':'watch','result':'failed_or_incomplete','phase_failures':{'evidence':{'reason':'export failed'}}})
        self.assertFalse(keep.evidence_complete(self.root))

    def test_wrong_profile_phase_overlap_or_unrequested_largest_setting_fails(self):
        for kind in ['profile','phase','request','outcome']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root)
                if kind=='profile':f.runtime['watch_profile']='smallest'
                elif kind=='phase':f.runtime['stages'].append(stage('build/watch-ui.xcresult',[]))
                elif kind=='request':f.runtime['largest_system_text']['requested_largest']='large'
                else:f.runtime['largest_text_outcome']={'result':'not_started'}
                f.save();self.assertFalse(keep.retain(root)['complete'])

    def test_probe_operations_are_required_and_cannot_be_replaced_by_booleans(self):
        for kind in ['missing','row','readback','restoration','set-command','cleanup','order','summary-timeout']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root);s=f.runtime['largest_system_text']
                if kind=='missing':s['operations']=[]
                elif kind=='row':s['native_text_row']=row('watch','system-largest','','smallest',SHA)
                elif kind=='readback':s['operations'][4]['output']='large\n'
                elif kind=='restoration':s['operations'][-1]['output']=LARGEST+'\n'
                elif kind=='set-command':s['operations'][3]['operation']['command'][-1]='large'
                elif kind=='cleanup':s['operations'][3]['operation']['cleanup_confirmed']=False
                elif kind=='order':s['operations'][3:5]=reversed(s['operations'][3:5])
                else:s['summary_operation']['timeout_seconds']=31
                f.save();self.assertFalse(keep.retain(root)['complete'])

    def test_already_largest_needs_readback_and_restore_readback_but_no_setter(self):
        f=Fixture(self.root);s=f.runtime['largest_system_text']
        s.update(observed_original=LARGEST,observed_restored=LARGEST,
                 operations=probe_operations(f.runtime['stages'][-1]['command'],LARGEST))
        f.save();self.assertTrue(keep.retain(self.root)['complete'])

    def test_real_probe_report_with_newlines_and_reconciled_setter_failures(self):
        from native_content_size import TouchSizeRunner, run_largest
        for variant in ['normal','set-failure','restore-failure','before-restore-failure']:
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as folder,tempfile.TemporaryDirectory() as evidence:
                work=Path(folder);root=Path(evidence);f=Fixture(root)
                (work/'TouchColorWatch.xcodeproj').mkdir();(work/'build/watch-tests').mkdir(parents=True)
                contract={'root':str(work),'project':'TouchColorWatch.xcodeproj','scheme':'TouchColorWatch',
                          'derived_data':'build/watch-tests','test_bundle':'TouchColorWatchUITests','platform':'watchOS Simulator'}
                command=['xcodebuild','test-without-building','-project','TouchColorWatch.xcodeproj','-scheme','TouchColorWatch',
                    '-derivedDataPath','build/watch-tests','-destination','platform=watchOS Simulator,id='+DEVICE,
                    '-configuration','Debug','-resultBundlePath','build/watch-largest-text.xcresult','CODE_SIGNING_ALLOWED=NO',
                    '-parallel-testing-enabled','NO','-collect-test-diagnostics','never','-test-timeouts-enabled','YES',
                    '-maximum-concurrent-test-simulator-destinations','1']
                command+=['-only-testing:TouchColorWatchUITests/WatchWorkflowTests/'+name for name in WATCH_CASES]
                f.runtime['stages'][1]['command']=command
                current='large';ui_done=False
                def execute(args,timeout,**kwargs):
                    nonlocal current
                    code=0
                    if args==['xcrun','simctl','help','ui']:text='\n'+HELP+'\n'
                    elif args==['xcrun','simctl','list','devices','-j']:
                        text=json.dumps({'devices':{f.runtime['runtime']:[{'udid':DEVICE,'state':'Booted'}]}})+'\n'
                    elif args[:3]==['xcrun','xcresulttool','get']:text=json.dumps(summary(3))
                    elif len(args)==6:
                        current=args[-1];text='\n'
                        if (current==LARGEST and variant=='set-failure') or (current=='large' and variant=='restore-failure'):code=1
                    else:
                        text=current+'\n'
                        if ui_done and current==LARGEST and variant=='before-restore-failure':code=1
                    return subprocess.CompletedProcess(args,code,text,'')
                def ui(args,seconds):
                    nonlocal ui_done
                    self.assertEqual(current,LARGEST);ui_done=True
                    return 0,'',copy.deepcopy(f.runtime['stages'][1])
                prior=Path.cwd()
                try:
                    os.chdir(work)
                    setting=run_largest(DEVICE,work/'probe.json',command,contract,WATCH_CASES,TouchSizeRunner(ui,execute),timeout=600)
                finally:os.chdir(prior)
                self.assertEqual(setting['status'],'largest_ui_passed')
                self.assertTrue(setting['restore_verified']);setting['native_text_row']=f.binding
                f.runtime['largest_system_text']=setting;f.save()
                self.assertTrue(keep.retain(root)['complete'])

    def test_early_native_packet_without_selection_is_incomplete_without_full_env(self):
        with patch.dict(os.environ,{'TOUCHCOLOR_JOB_PLATFORM':'vision'}):
            self.assertFalse(keep.evidence_complete(self.root))
            with self.assertRaises(ValueError):keep.retain(self.root)

    def test_stale_wrong_device_or_wrong_scope_summary_never_passes(self):
        for kind in ['stale','device','scope','skip','duplicate-stage']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);f=Fixture(root)
                if kind=='stale':f.runtime['stages'][1]['finished_at']='1970-01-01T00:00:15+00:00'
                elif kind=='scope':f.runtime['stages'][1]['command'][-1]='-only-testing:Other/testCase'
                elif kind=='duplicate-stage':f.runtime['stages'].append(copy.deepcopy(f.runtime['stages'][1]))
                else:
                    v=summary(3)
                    if kind=='device':v['devicesAndConfigurations'][0]['device']['deviceId']='foreign'
                    else:v['skippedTests']=1
                    f.write('watch-largest-text-summary.json',v)
                f.save();self.assertFalse(keep.retain(root)['complete'])

    def test_vision_chinese_phase_bound_capture_and_cached_summaries(self):
        for phase in ['normal','system-largest']:
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as tmp,patch('vision_offline_result.evidence_complete',return_value=True) as qualify:
                root=Path(tmp);Fixture(root,'vision',phase)
                self.assertTrue(keep.retain(root)['complete']);qualify.assert_called_once_with(root)

    def test_vision_normal_requires_normal_raw_summary(self):
        f=Fixture(self.root,'vision','normal');(self.root/'vision-ui-summary.json').unlink()
        with patch('vision_offline_result.evidence_complete',return_value=True) as qualify:
            self.assertFalse(keep.retain(self.root)['complete']);qualify.assert_not_called()

    def test_vision_largest_does_not_accept_normal_checkpoint(self):
        f=Fixture(self.root,'vision');f.runtime['captures'][0].pop('system_text_size');f.save()
        with patch('vision_offline_result.evidence_complete',return_value=True):
            self.assertFalse(keep.retain(self.root)['complete'])

    def test_canvas_explicitly_has_no_mandatory_pixel_and_preserves_deferred_failure(self):
        Fixture(self.root,'vision',case='canvas-audit')
        with patch('vision_offline_result.evidence_complete',return_value=False):
            result=keep.retain(self.root);self.assertFalse(result['complete']);self.assertFalse(result['missingProof'])
        with patch('vision_offline_result.evidence_complete',return_value=True):
            self.assertTrue(keep.evidence_complete(self.root))

    def test_vision_image_omission_cannot_be_hidden_by_filtered_manifest(self):
        f=Fixture(self.root,'vision',image_bytes=710000)
        with patch('vision_offline_result.evidence_complete',return_value=True):
            result=keep.retain(self.root);self.assertFalse(result['complete']);self.assertTrue(result['omissions'][f.images[0]]['mandatory'])
        self.assertBounded(f)

    def test_missing_selection_never_certifies_native_packet(self):
        Fixture(self.root);self.assertFalse(keep.evidence_complete(self.root))

    def test_other_platform_is_unaffected(self):
        with patch.dict(os.environ,{'TOUCHCOLOR_JOB_PLATFORM':'mac'}):
            self.assertIsNone(keep.retain(self.root));self.assertTrue(keep.evidence_complete(self.root))

    def test_repeat_retain_is_validation_only_and_does_not_clear_omissions(self):
        Fixture(self.root,image_bytes=230000);first=keep.retain(self.root)
        raw=(self.root/keep.REPORT).read_bytes();second=keep.retain(self.root)
        self.assertFalse(second['complete']);self.assertEqual(first['omissions'],second['omissions'])
        self.assertEqual(raw,(self.root/keep.REPORT).read_bytes())

    def test_cli_is_filesystem_only_and_emits_completion(self):
        f=Fixture(self.root)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',**f.environment())
        result=subprocess.run([sys.executable,str(Path(keep.__file__)),'retain',str(self.root)],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),{'platform':'watch','complete':True})


if __name__=='__main__':
    unittest.main()
