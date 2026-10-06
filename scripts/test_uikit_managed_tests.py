"""Portable closed-route, absolute-clock and real owned-process regressions."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import uikit_managed_tests as m
from palette_lifecycle_diagnostics import CaptureStopped

ROOT = Path(__file__).resolve().parents[1]
DEVICE = '7EBB1450-0922-41FE-984D-B2B14D1C34C3'
IDENTITY = {'family': 'iPadMini', 'udid': DEVICE, 'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 1}
SETUP = {'schema': 1, 'binding': {'identity': IDENTITY, 'context': {'sha': 'a'*40}},
         'products': {'tree_sha256': 'b'*64, 'files': 1, 'bytes': 1, 'claim': 'built_product_bytes_only'}}


def summary(family='iPadMini', suite='TouchColorTests', failures=0):
    total = {'TouchColorTests': 53, 'TouchColorUITests': 15 if family.startswith('iPad') else 17,
             'AccessibilityAudits': 7}[suite]
    skips = int(suite == 'TouchColorTests' and family.startswith('iPhone'))
    fields = {'totalTestCount': total, 'passedTests': total-skips-failures, 'failedTests': failures,
              'skippedTests': skips, 'expectedFailures': 0}
    return {**fields, 'result': 'Failed' if failures else 'Passed', 'startTime': 1000.1, 'finishTime': 1000.9,
            'devicesAndConfigurations': [{**{k:v for k,v in fields.items() if k!='totalTestCount'},
                'device': {'deviceId': DEVICE, 'platform': 'iOS Simulator', 'osVersion': '27.0'}}]}


class SummaryTests(unittest.TestCase):
    def check(self, value, family='iPadMini', suite='TouchColorTests', code=0):
        return m.summary_fields(json.dumps(value), family, suite, IDENTITY, 1000, 1001, code)
    def test_all_full_inventories(self):
        for family in ('iPadMini','iPadLarge','iPhoneCompact','iPhoneLarge'):
            for suite in m.STEPS:
                with self.subTest(family=family,suite=suite):
                    self.assertTrue(self.check(summary(family,suite),family,suite)['qualified'])
    def test_known_failed_remains_failed(self):
        value=self.check(summary(failures=1),code=65)
        self.assertFalse(value['qualified']); self.assertEqual(value['failedTests'],1)
    def test_destination_and_clock_adversaries(self):
        mutations=[lambda s:s.update(startTime=999.999),lambda s:s.update(finishTime=1001.001),
            lambda s:s.update(startTime=float('nan')),lambda s:s['devicesAndConfigurations'].append(copy.deepcopy(s['devicesAndConfigurations'][0])),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(deviceId='A'*36),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(platform='iOS'),
            lambda s:s['devicesAndConfigurations'][0]['device'].update(osVersion='26.0')]
        for mutate in mutations:
            value=summary();mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):self.check(value)
    def test_count_skip_outcome_adversaries(self):
        mutations=[lambda s:s.update(totalTestCount=1),lambda s:s.update(passedTests=52),
            lambda s:s.update(failedTests=True),lambda s:s.update(skippedTests=1,passedTests=52),
            lambda s:s.update(expectedFailures=1),lambda s:s.update(result='Failed'),
            lambda s:s['devicesAndConfigurations'][0].update(passedTests=0)]
        for mutate in mutations:
            value=summary();mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.check(value)
        with self.assertRaises(ValueError):self.check(summary(),code=65)
        with self.assertRaises(ValueError):self.check(summary(failures=1),code=0)
    def test_phone_capability_skip_not_inherited_by_ipad(self):
        with self.assertRaises(ValueError):self.check(summary('iPhoneCompact'))
    def test_duplicates_fail(self):
        raw=json.dumps(summary()).replace('"passedTests": 53','"passedTests": 53, "passedTests": 53',1)
        with self.assertRaises(ValueError):m.summary_fields(raw,'iPadMini','TouchColorTests',IDENTITY,1000,1001,0)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
        self.tick=0.;self.calls=[];self.reader_calls=[];self.inject=None;self.read_inject=None
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(m,'load_setup',return_value=copy.deepcopy(SETUP)))
        self.stack.enter_context(patch.object(m,'read_binding',return_value=copy.deepcopy(SETUP['binding'])))
        self.stack.enter_context(patch.object(m,'verify_source'))
        self.stack.enter_context(patch.object(m,'require_hosted'))
        self.stack.enter_context(patch.object(m,'require_fixtures'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    def tearDown(self):
        self.stack.close();os.chdir(self.old);self.tmp.cleanup()
    def runner(self,command,deadline):
        self.calls.append((command,deadline));self.tick+=1
        value={'status':'timely_exit','exit_code':0,'host_cleanup_confirmed':True,'simulator_completion':'xcode_command_returned_only'}
        if self.inject:self.inject(value,deadline)
        return value
    def reader(self,command,**kw):
        self.reader_calls.append((command,kw))
        if self.read_inject:self.read_inject(kw)
        return subprocess.CompletedProcess(command,0,json.dumps(summary()).encode(),b'')
    def run_case(self,**kwargs):
        products=kwargs.pop('products',lambda **kw:copy.deepcopy(SETUP['products']))
        return m.run_suite('iPadMini','TouchColorTests',started=0,clock=lambda:self.tick,
            wall=lambda:1000+self.tick,runner=self.runner,reader=self.reader,
            products=products,**kwargs)
    def record(self):return json.loads(m.record_path('iPadMini','TouchColorTests').read_text())
    def pending(self):return Path('build/iPadMini-runtime-command-uncertain').exists()
    def test_exact_success(self):
        self.assertEqual(self.run_case(),0);self.assertFalse(self.pending());self.assertTrue(self.record()['qualified'])
        self.assertEqual(self.calls[0][1],500)
        self.assertEqual(self.reader_calls[0][1],{'seconds':20,'cap':1048576,'cleanup_grace':10})
    def test_39_seconds_entry_fits(self):
        self.tick=39
        # Make summary dates correspond to this injected entry time.
        def read(command,**kw):
            value=summary();value.update(startTime=1039.1,finishTime=1039.9)
            return subprocess.CompletedProcess(command,0,json.dumps(value).encode(),b'')
        self.reader=read
        self.assertEqual(self.run_case(),0);self.assertEqual(self.calls[0][1],539)
    def test_exact_40_seconds_entry_refuses_full_admission(self):
        self.tick=40;self.assertEqual(self.run_case(),3);self.assertEqual(self.calls,[])
    def test_persist_overhead_cannot_start_expired_grant(self):
        original=m.write_json
        def delayed(*args,**kw):
            original(*args,**kw);self.tick=41
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.calls,[]);self.assertTrue(self.pending())
    def test_late_xctest_retains_fence_and_early_outcome(self):
        self.inject=lambda value,deadline:setattr(self,'tick',deadline)
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
        self.assertEqual(self.record()['command']['status'],'timely_exit')
        self.assertFalse(self.record()['qualified'])
    def test_timeout_unknown_or_cancel_cannot_start_reader(self):
        for status in ('incomplete','not_started'):
            self.inject=lambda value,deadline:value.update(status=status,host_cleanup_confirmed=False)
            self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
            Path('build/iPadMini-runtime-command-uncertain').unlink();m.record_path('iPadMini','TouchColorTests').unlink()
    def test_late_summary_keeps_fence(self):
        self.read_inject=lambda kw:setattr(self,'tick',1+kw['seconds'])
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertFalse(self.record()['qualified'])
    def test_summary_persistence_cost_is_subtracted_before_capture(self):
        original=m.write_json;calls=[0]
        def delayed(*args,**kwargs):
            original(*args,**kwargs);calls[0]+=1
            if calls[0]==3:self.tick+=19
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),0)
        self.assertEqual(self.reader_calls[0][1]['seconds'],1)
    def test_expired_summary_persistence_never_dispatches_reader(self):
        original=m.write_json;calls=[0]
        def delayed(*args,**kwargs):
            original(*args,**kwargs);calls[0]+=1
            if calls[0]==3:self.tick+=20
        with patch.object(m,'write_json',side_effect=delayed):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_summary_unknown_cleanup_keeps_fence(self):
        def fail(kw):raise CaptureStopped('duration-limit',False)
        self.read_inject=fail
        self.assertEqual(self.run_case(),3);self.assertTrue(self.pending());self.assertFalse(self.record()['qualified'])
        self.assertIs(self.record()['summary']['host_cleanup_confirmed'],False)
    def test_known_failed_suite_retains_complete_failed_result(self):
        self.inject=lambda value,deadline:value.update(exit_code=65)
        self.reader=lambda command,**kw:subprocess.CompletedProcess(command,0,json.dumps(summary(failures=1)).encode(),b'')
        self.assertEqual(self.run_case(),65);self.assertFalse(self.pending())
        self.assertEqual(self.record()['summary']['status'],'complete');self.assertFalse(self.record()['qualified'])
    def test_prepare_marker_overhead_cannot_reset_nominal_cap(self):
        calls=[]
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,
            host_runner=lambda command,timeout:(calls.append(timeout) or subprocess.CompletedProcess(command,0,'','')))
        original=Path.open
        class DelayedMarker:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):self.tick=0;return self
            def write(inner,data):self.tick=31;return inner.stream.write(data)
            def __exit__(inner,*args):inner.stream.close()
        def opening(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return DelayedMarker(stream) if str(path).endswith('-runtime-command-uncertain') else stream
        with patch.object(Path,'open',new=opening):
            with self.assertRaises(ValueError):w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[]);self.assertTrue(self.pending())
    def test_all_managed_finalizers_stop_at_existing_uncertainty(self):
        Path('build').mkdir();Path('build/iPadMini-runtime-command-uncertain').write_text('old')
        with patch.object(m,'read_managed_device') as inventory,patch.object(m,'setup_capture') as capture:
            with self.assertRaises(Exception):m.fixture_seed('iPadMini',started=0)
            with patch.object(sys,'argv',['tool','iPadMini','managed-shutdown']):
                with self.assertRaises(Exception):m.main()
            inventory.assert_not_called();capture.assert_not_called()
    def test_known_reader_nonzero_preserves_command_and_no_false_uncertainty(self):
        self.reader=lambda command,**kw:subprocess.CompletedProcess(command,1,b'',b'error')
        self.assertEqual(self.run_case(),3);self.assertFalse(self.pending());self.assertEqual(self.record()['command']['exit_code'],0)
    def test_changed_product_stops_before_summary(self):
        with patch.object(m,'read_binding',return_value={}):self.assertEqual(self.run_case(),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_post_product_scan_uses_original_phase_and_retains_failure(self):
        seen=[];observation={'status':'failed','complete':False,'reason':'elapsed_limit',
                           'files':204,'bytes':26142729,'elapsed_seconds':20.25}
        self.inject=lambda value,deadline:value.update(exit_code=65)
        def scan(**kw):
            seen.append(kw);self.tick=21.25
            raise m.ProductInventoryError(observation)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(seen[0]['post_test_deadline'],560)
        self.assertIsNotNone(seen[0]['clock']);self.assertEqual(self.reader_calls,[])
        record=self.record();self.assertEqual(record['command']['exit_code'],65)
        self.assertIs(record['command']['host_cleanup_confirmed'],True)
        self.assertEqual(record['summary'],{'status':'not_started'})
        self.assertEqual(record['product_inventory'],observation)
        self.assertFalse(record['qualified']);self.assertTrue(self.pending())
        printed=json.loads(output.getvalue().split('UIKIT_MANAGED_RESULT:',1)[1])
        self.assertEqual(printed['product_inventory'],observation)
        with patch.object(m,'read_managed_device') as inventory,patch.object(m,'setup_capture') as capture:
            with self.assertRaises(Exception):m.fixture_seed('iPadMini',started=0)
            with patch.object(sys,'argv',['tool','iPadMini','managed-shutdown']):
                with self.assertRaises(Exception):m.main()
            inventory.assert_not_called();capture.assert_not_called()
    def test_changed_product_digest_remains_unqualified(self):
        def scan(**kw):
            kw['observation'].update(status='complete',complete=True,reason=None)
            return {**SETUP['products'],'tree_sha256':'c'*64}
        self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
        self.assertEqual(self.record()['error'],'Post-test products changed')
        self.assertTrue(self.record()['product_inventory']['complete'])
        self.assertFalse(self.record()['qualified'])
    def test_product_scan_at_phase_tail_cannot_start_summary(self):
        def scan(**kw):
            self.tick=kw['post_test_deadline']
            return copy.deepcopy(SETUP['products'])
        self.assertEqual(self.run_case(products=scan),3)
        self.assertEqual(self.reader_calls,[]);self.assertTrue(self.pending())
    def test_interrupted_real_scan_retains_completed_reads_and_command(self):
        root=Path('build/simulator/Build/Products')
        for path in (root/'Debug-iphonesimulator/TouchColor.app',
                     root/'Debug-iphonesimulator/TouchColorUITests-Runner.app',
                     Path('build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app')):
            path.mkdir(parents=True);(path/'binary').write_bytes(b'binary')
        (root/'TouchColor.xctestrun').write_bytes(b'configuration')
        original=m.read_regular;calls=[0]
        def interrupted(*args,**kw):
            calls[0]+=1
            if calls[0]==2:
                self.tick=1.125
                raise m.WarmupFailed('UIKit owned command interrupted by signal 15')
            return original(*args,**kw)
        self.inject=lambda value,deadline:value.update(exit_code=65)
        with patch.object(m,'read_regular',side_effect=interrupted):
            self.assertEqual(self.run_case(products=m.product_identity),3)
        record=self.record();value=record['product_inventory']
        self.assertEqual(value['reason'],'interrupted');self.assertEqual(value['status'],'failed')
        self.assertFalse(value['complete']);self.assertEqual(value['files'],1)
        self.assertEqual(value['bytes'],len(b'configuration'));self.assertEqual(value['elapsed_seconds'],.125)
        self.assertEqual(record['command']['exit_code'],65);self.assertTrue(record['command']['host_cleanup_confirmed'])
        self.assertEqual(record['summary'],{'status':'not_started'})
        self.assertFalse(record['qualified']);self.assertTrue(self.pending());self.assertEqual(self.reader_calls,[])
    def test_repeated_result_refused(self):
        self.assertEqual(self.run_case(),0)
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(len(self.calls),1)
    def test_existing_uncertainty_blocks_all_calls(self):
        Path('build').mkdir();Path('build/iPadMini-runtime-command-uncertain').write_text('old')
        with self.assertRaises(Exception):self.run_case()
        self.assertEqual(self.calls,[]);self.assertEqual(self.reader_calls,[])
    def test_pre_capture_setup_deadline_clamp(self):
        calls=[];self.tick=579
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,
            host_runner=lambda command,timeout:(calls.append(timeout) or subprocess.CompletedProcess(command,0,'','')))
        w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[1])
        self.tick=580
        with self.assertRaises(Exception):w.command(['host-only-proof'],30,simulator=False)
        self.assertEqual(calls,[1])
    def test_late_setup_result_rejected(self):
        def late(command,timeout):self.tick+=timeout;return subprocess.CompletedProcess(command,0,'','')
        w=m.ManagedWarmup('iPadMini',started=0,clock=lambda:self.tick,host_runner=late)
        with self.assertRaises(ValueError):w.command(['host-only-proof'],30,simulator=False)
        self.assertTrue(self.pending())


class ProductInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
        self.tick=0.;self.observation={}
        self.roots=(Path('build/simulator/Build/Products'),Path('build/palette-fixtures/Build/Products'))
        self.bundles=(self.roots[0]/'Debug-iphonesimulator/TouchColor.app',
                      self.roots[0]/'Debug-iphonesimulator/TouchColorUITests-Runner.app',
                      self.roots[1]/'Debug-iphonesimulator/PaletteFixtures.app')
        for bundle in self.bundles:
            bundle.mkdir(parents=True);(bundle/'binary').write_bytes(b'built bytes')
        (self.roots[0]/'TouchColor.xctestrun').write_bytes(b'configuration')
    def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
    def scan(self,**kw):
        return m.product_identity(clock=lambda:self.tick,observation=self.observation,**kw)
    def failure(self,reason,**kw):
        with self.assertRaises(m.ProductInventoryError) as raised:self.scan(**kw)
        self.assertEqual(raised.exception.observation,self.observation)
        self.assertEqual(self.observation['reason'],reason)
        self.assertEqual(self.observation['status'],'failed');self.assertFalse(self.observation['complete'])
        self.assertLess(len(json.dumps(self.observation).encode()),2048)
        self.assertNotIn(str(Path.cwd()),json.dumps(self.observation))
        return self.observation
    def test_identity_recipe_and_full_auxiliary_scope_are_unchanged(self):
        auxiliary=self.roots[0]/'unselected.swiftmodule';auxiliary.write_bytes(b'auxiliary')
        expected=hashlib.sha256();count=size=0
        for root in self.roots:
            for parent,directories,files in os.walk(root):
                directories.sort()
                for name in sorted(files):
                    path=Path(parent)/name;raw=path.read_bytes();count+=1;size+=len(raw)
                    expected.update(path.as_posix().encode()+b'\0'+str(len(raw)).encode()+b'\0'+raw)
        identity=self.scan()
        self.assertEqual(identity,{'tree_sha256':expected.hexdigest(),'files':count,'bytes':size,
                                   'claim':'built_product_bytes_only'})
        self.assertTrue(self.observation['complete']);self.assertEqual(self.observation['allowance_seconds'],10)
        self.tick=100;self.assertEqual(self.scan(post_test_deadline=200),identity)
        self.assertEqual(self.observation['allowance_seconds'],20)
        auxiliary.write_bytes(b'changedxx');self.assertNotEqual(self.scan(),identity)
    def test_changed_consumed_binary_changes_identity(self):
        identity=self.scan();binary=self.bundles[0]/'binary'
        binary.write_bytes(b'other bytes');self.assertNotEqual(self.scan(),identity)
    def test_initial_ten_second_boundary_is_unchanged(self):
        original=m.read_regular
        def slow(*args,**kw):
            raw=original(*args,**kw);self.tick=10;return raw
        with patch.object(m,'read_regular',side_effect=slow):value=self.failure('elapsed_limit')
        self.assertEqual(value['allowance_seconds'],10);self.assertEqual(value['elapsed_seconds'],10)
        self.assertEqual(value['files'],1);self.assertEqual(value['bytes'],len(b'configuration'))
    def test_post_scan_accepts_ten_but_rejects_twenty_seconds(self):
        original=m.read_regular
        def slow(*args,**kw):
            raw=original(*args,**kw);self.tick=10;return raw
        with patch.object(m,'read_regular',side_effect=slow):self.scan(post_test_deadline=100)
        self.assertTrue(self.observation['complete']);self.assertEqual(self.observation['elapsed_seconds'],10)
        self.tick=0
        def late(*args,**kw):
            raw=original(*args,**kw);self.tick=20;return raw
        with patch.object(m,'read_regular',side_effect=late):value=self.failure('elapsed_limit',post_test_deadline=100)
        self.assertEqual(value['granted_seconds'],20)
    def test_original_phase_clips_post_scan_and_refuses_expired_entry(self):
        original=m.read_regular;self.tick=550
        def late(*args,**kw):
            raw=original(*args,**kw);self.tick=560;return raw
        with patch.object(m,'read_regular',side_effect=late):value=self.failure('phase_deadline',post_test_deadline=560)
        self.assertEqual(value['granted_seconds'],10);self.assertEqual(value['deadline_monotonic'],560)
        with patch.object(m,'read_regular') as read:value=self.failure('phase_deadline',post_test_deadline=560)
        read.assert_not_called();self.assertEqual(value['files'],0);self.assertEqual(value['granted_seconds'],0)
    def test_final_hash_cost_cannot_escape_deadline(self):
        real=hashlib.sha256()
        class SlowDigest:
            def update(inner,data):real.update(data);self.tick=20
            def hexdigest(inner):return real.hexdigest()
        with patch.object(m.hashlib,'sha256',return_value=SlowDigest()):
            self.failure('elapsed_limit',post_test_deadline=100)
    def test_directory_fanout_has_its_own_reason(self):
        with patch.object(m.os,'walk',return_value=iter([(str(self.roots[0]),[],['x']*8193)])):
            value=self.failure('directory_entries_limit')
        self.assertEqual(value['directory_entries'],8193);self.assertEqual(value['files'],0)
    def counted_walk(self,count):
        def walk(root,**kw):
            if Path(root)==self.roots[0]:
                for start in range(0,count,1024):
                    yield str(root),[],[str(i) for i in range(start,min(start+1024,count))]
        return walk
    def test_aggregate_file_count_boundary_is_unchanged(self):
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8192)),patch.object(m,'read_regular',return_value=b''):
            self.assertEqual(self.scan()['files'],8192)
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8193)),patch.object(m,'read_regular',return_value=b''):
            value=self.failure('file_count_limit')
        self.assertEqual(value['files'],8193);self.assertEqual(value['bytes'],0)
    def test_aggregate_byte_boundary_does_not_allocate_a_gibibyte(self):
        class SizedBytes(bytes):
            def __len__(self):return 128*1024*1024
        def read(path,cap,**kw):
            self.assertEqual(cap,128*1024*1024);return SizedBytes(b'x')
        with patch.object(m.os,'walk',side_effect=self.counted_walk(8)),patch.object(m,'read_regular',side_effect=read):
            self.assertEqual(self.scan()['bytes'],1024**3)
        with patch.object(m.os,'walk',side_effect=self.counted_walk(9)),patch.object(m,'read_regular',side_effect=read):
            value=self.failure('total_bytes_limit')
        self.assertEqual(value['bytes'],9*128*1024*1024);self.assertEqual(value['files'],9)
    def test_single_file_cap_remains_safety_failure(self):
        with (self.roots[0]/'oversized').open('wb') as stream:stream.truncate(128*1024*1024+1)
        value=self.failure('safety');self.assertEqual(value['safety_detail'],'unsafe_or_unreadable_file')
        self.assertEqual(value['limits']['file_bytes'],128*1024*1024)
    def test_linked_product_and_file_fail_without_disclosing_path(self):
        (self.roots[0]/'linked').symlink_to(self.bundles[0]/'binary')
        value=self.failure('safety');self.assertEqual(value['safety_detail'],'unsafe_or_unreadable_file')
    def test_walk_read_error_is_not_silently_omitted(self):
        def walk(root,**kw):
            kw['onerror'](PermissionError('/private/unrelated/path'));return iter(())
        with patch.object(m.os,'walk',side_effect=walk):value=self.failure('safety')
        self.assertEqual(value['safety_detail'],'unreadable_directory')
        self.assertNotIn('/private',json.dumps(value))


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name);Path('build').mkdir()
    def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
    def hosted(self):
        fields=m.summary_fields(json.dumps(summary()),'iPadMini','TouchColorTests',IDENTITY,1000,1001,0)
        return {'schema':1,'suite':'TouchColorTests','setup':SETUP,'qualified':True,
                'command':{'status':'timely_exit','exit_code':0,'host_cleanup_confirmed':True},
                'summary':{'status':'complete','fields':fields}}
    def test_full_hosted_receipt_required(self):
        value=self.hosted();m.write_json(m.record_path('iPadMini','TouchColorTests'),value)
        self.assertEqual(m.require_hosted('iPadMini',SETUP),value)
    def test_flags_alone_cannot_hide_failed_or_missing_counts(self):
        changes=[lambda v:v['summary'].update(status='pending'),lambda v:v['summary'].update(fields={}),
            lambda v:v['summary']['fields'].update(totalTestCount=1),lambda v:v['summary']['fields'].update(failedTests=1),
            lambda v:v['summary']['fields'].update(device='foreign'),lambda v:v.update(error='late'),
            lambda v:v.update(schema=True),lambda v:v['command'].update(host_cleanup_confirmed=False)]
        for change in changes:
            value=self.hosted();change(value);m.write_json(m.record_path('iPadMini','TouchColorTests'),value)
            with self.subTest(change=change),self.assertRaises(ValueError):m.require_hosted('iPadMini',SETUP)
    def test_fixture_receipt_and_seed_both_bound(self):
        m.write_json(m.record_path('iPadMini','fixtures'),{'schema':1,'setup':SETUP,'complete':True})
        m.write_json(Path('build/iPadMini-fixture-seeded'),IDENTITY)
        m.require_fixtures('iPadMini',SETUP)
        value={**IDENTITY,'udid':'foreign'};m.write_json(Path('build/iPadMini-fixture-seeded'),value)
        with self.assertRaises(ValueError):m.require_fixtures('iPadMini',SETUP)
    def test_trusted_file_rejects_links_and_bounded_oversize(self):
        path=Path('build/plain');path.write_bytes(b'123')
        self.assertEqual(m.read_regular(path,3),b'123')
        with self.assertRaises(ValueError):m.read_regular(path,2)
        link=Path('build/link');link.symlink_to('plain')
        with self.assertRaises(ValueError):m.read_regular(link,3)
    def test_setup_capture_uses_existing_bounded_reader(self):
        with patch.object(m,'capture',return_value=subprocess.CompletedProcess([],0,b'ok',b'')) as capture:
            result=m.setup_capture(['host-only-proof'],3)
        capture.assert_called_once_with(['host-only-proof'],seconds=3,cap=1000000,cleanup_grace=10)
        self.assertEqual(result.stdout,'ok')


class ProcessTests(unittest.TestCase):
    def test_actual_host_exit(self):
        value=m.invoke([sys.executable,'-c','pass'],m.time.monotonic()+3)
        self.assertEqual(value['status'],'timely_exit');self.assertTrue(value['host_cleanup_confirmed'])
    def test_actual_host_failure(self):
        value=m.invoke([sys.executable,'-c','raise SystemExit(65)'],m.time.monotonic()+3)
        self.assertEqual(value['exit_code'],65);self.assertEqual(value['status'],'timely_exit')
    def test_actual_timeout_owned_cleanup(self):
        value=m.invoke([sys.executable,'-c','import time;time.sleep(10)'],m.time.monotonic()+.05)
        self.assertEqual(value['status'],'incomplete');self.assertTrue(value['host_cleanup_confirmed'])
    def test_expired_entry_does_not_spawn(self):
        calls=[]
        value=m.invoke(['unused'],0,clock=lambda:1,popen=lambda *a,**k:calls.append(a))
        self.assertEqual(calls,[]);self.assertEqual(value['status'],'incomplete')


class SourceTests(unittest.TestCase):
    def test_original_case_and_target_arguments(self):
        for family in ('iPhoneCompact','iPhoneLarge','iPadMini','iPadLarge'):
            for suite in m.STEPS:
                argv=m.test_argv(family,suite,DEVICE)
                self.assertEqual(argv.count('test-without-building'),1)
                self.assertEqual(argv[argv.index('-default-test-execution-time-allowance')+1],'180')
                self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance')+1],'240')
                self.assertNotIn('-test-iterations',argv);self.assertFalse(any('retry' in a for a in argv))
                self.assertIn('platform=iOS Simulator,id='+DEVICE,argv)
    def test_source_inventory_matches_complete_counts(self):
        import re
        files=['ColorPickerTests/'+n for n in ('ColorPickerTests.m','TCAdaptiveLayoutTests.m','TCWorkspaceTests.m',
             'TCPhotoImportLifecycleTests.m','ColorCoreEquivalenceTests.swift','TCPhotoImportTests.swift')]
        files+=['TouchColorPhoneCompanion/Tests/PhonePaletteImportTests.swift']
        count=sum(len(re.findall(r'(?:-\s*\(void\)\s*|func\s+)(test\w+)\b', (ROOT/p).read_text())) for p in files)
        self.assertEqual(count,53)
        for name,count in [('TouchColorUITests',17),('TouchColorIPadUITests',15),('TouchColorAccessibilityUITests',7)]:
            text=(ROOT/'TouchColorUITests'/(name+'.m')).read_text()
            self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',text)),count)
    def test_closed_workflow_budgets_and_gates(self):
        import re
        text=(ROOT/'.github/workflows/ios.yml').read_text()
        job=text.split('  compatibility:\n',1)[1]
        self.assertIn('    timeout-minutes: 60\n',job)
        self.assertEqual(re.findall(r'^      max-parallel: (.+)$',job,re.M),["${{ github.ref == 'refs/heads/codex/uikit-hosted-repair' && 2 || 1 }}"])
        def step(name):return job.split('      - name: '+name+'\n',1)[1].split('      - name:',1)[0]
        hosted=step('Unit and constrained-window layout tests')
        functional=step('Functional UI tests')
        seeded=step('Prepare Files fixture and seed synthetic photo')
        self.assertIn("steps.hosted-tests.outcome == 'success'",seeded)
        self.assertIn('timeout-minutes: 10',hosted);self.assertIn('timeout-minutes: 20',functional)
        self.assertIn('timeout-minutes: 10',seeded)
    def test_live_phone_pipe_and_legacy_paths_preserved(self):
        text=(ROOT/'scripts/test_simulators.sh').read_text()
        self.assertIn('set -euo pipefail',text)
        self.assertIn('"$suite" == managed-functional',text)
        self.assertIn('palette_lifecycle_diagnostics.py" retain "$family"',text)
        self.assertIn('run_test_suite()',text);self.assertIn('uikit_warmup.py" "$family" "$suite"',text)
    def test_no_prehosted_boot_or_standalone_touchcolor_launch(self):
        import inspect
        prehosted=inspect.getsource(m.configure)
        self.assertNotIn("'boot'",prehosted);self.assertNotIn("'bootstatus'",prehosted)
        text=prehosted+inspect.getsource(m.fixture_seed)+inspect.getsource(m.ManagedWarmup.fixture_device)
        self.assertIn('warmup.fixture_device(setup)',text)
        self.assertNotIn("device, 'com.mango.touchColor'",text)
        self.assertIn('warmup.fixture(container)',text);self.assertIn('warmup.seed(device)',text)
    def test_finite_schedule_arithmetic(self):
        for step,command,_ in m.STEPS.values():
            self.assertEqual(step-command-2*m.CLEANUP-m.SUMMARY,40)


if __name__=='__main__':unittest.main()
