"""Focused fixed-group selection, honest bootstrap and uncertainty adversaries."""
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import uikit_completion as c
import uikit_managed_device as d
import uikit_managed_tests as m
from palette_lifecycle_diagnostics import CaptureStopped
from test_uikit_managed_tests import DEVICE, ROOT, SETUP
from test_uikit_managed_device import ManagedFixture, NEW
FULL_OR_SELECTED_HOSTED = m.require_hosted


def environment(group='ipad-mini'):
    return {'GITHUB_REPOSITORY': d.REPOSITORY, 'GITHUB_REF': c.REF,
        'GITHUB_WORKFLOW_REF': c.WORKFLOW, 'GITHUB_ACTIONS': 'true', 'GITHUB_JOB': 'completion',
        'RUNNER_OS': 'macOS', 'TC_TEST_FAMILY': c.GROUPS[group]['family'], 'TC_COMPLETION_GROUP': group,
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_SHA': 'a'*40, 'GITHUB_WORKFLOW_SHA': 'a'*40,
        'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


def summary(selected, failed=0):
    count = len(selected['cases'])
    fields = {'totalTestCount': count, 'passedTests': count-failed, 'failedTests': failed,
              'skippedTests': 0, 'expectedFailures': 0}
    return {**fields, 'result': 'Failed' if failed else 'Passed', 'startTime': 1000.1, 'finishTime': 1000.9,
        'devicesAndConfigurations': [{**{k:v for k,v in fields.items() if k != 'totalTestCount'},
            'device': {'deviceId': DEVICE, 'platform': 'iOS Simulator', 'osVersion': '27.0'}}]}


class ClosedGroups(unittest.TestCase):
    def test_resource_requirements_match_selected_method_dependencies(self):
        def method(path, name):
            source = (ROOT/'TouchColorUITests'/path).read_text()
            return source.split('- (void)'+name, 1)[1].split('\n- (', 1)[0]
        helpers = 'TCPaletteUIHelpers.m'
        for name in ('exercisePalettePasteReviewAcceptAndRelaunch',
                     'exerciseInvalidPalettePastePreservesHistory',
                     'exerciseLargestTextPaletteReviewAndImportHelp'):
            body = method(helpers, name)
            self.assertIn('pastePalette:', body)
            for consumer in ('selectSyntheticPaletteFile:', 'importFixture', 'choosePhoto'):
                self.assertNotIn(consumer, body)
        phone_setup = method('TouchColorUITests.m', 'setUp')
        self.assertIn('@"--ui-test-image"', phone_setup)
        cancellation = method(helpers, 'exercisePaletteFileCancelAndImportReturn')
        self.assertIn('waitForPaletteFilesPresentation:', cancellation)
        self.assertIn('[cancel tap]', cancellation)
        self.assertNotIn('selectSyntheticPaletteFile:', cancellation)
        file_consumer = method(helpers, 'exercisePaletteFileSelectionReviewAndRelaunch')
        self.assertIn('selectSyntheticPaletteFile:', file_consumer)
        for name in ('testPrivacyCloseRetainsPhotoSelection',
                     'testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState',
                     'testLiveCanvasPickerCancellationAndSceneLifecycle'):
            self.assertIn('[self importFixture]', method('TouchColorIPadUITests.m', name))
        live = method('TouchColorIPadUITests.m', 'testLiveCanvasPickerCancellationAndSceneLifecycle')
        self.assertLess(live.index('[self cancelPicker]'), live.index('XCUIDeviceButtonHome'))
        self.assertLess(live.index('XCUIDeviceButtonHome'), live.index('[self importFixture]'))
        photo = method('TouchColorIPadUITests.m', 'importFixture')
        self.assertIn('[self choosePhoto]', photo); self.assertIn('[photo tap]', photo)
        audit = method('TouchColorAccessibilityUITests.m', 'testAccessibilityLiveCameraUnavailable')
        self.assertNotIn('importAndSample', audit); self.assertNotIn('choosePhoto', audit)
        for key, group in c.GROUPS.items():
            with patch.dict(os.environ, environment(key), clear=True):
                resources = c.resource_selection(group['family'])
                self.assertEqual(resources['required'], {'files': False, 'photos': key.startswith('ipad-')})
                self.assertEqual(resources['functional'], list(group['functional']))
                self.assertEqual(resources['audits'], list(group['audits']))
                self.assertEqual(resources['bootstrap'], list(c.BOOTSTRAP))
                self.assertFalse(any('FileSelection' in case for case in resources['functional']))
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(c.resource_selection('iPadMini'))

    def test_ten_missing_and_one_affected_recheck_are_the_exact_closed_source_inventory(self):
        expected = {
            'iphone-compact': ('iPhoneCompact', ('testInvalidPalettePastePreservesHistory', 'testPalettePasteReviewAcceptAndRelaunch'), ()),
            'iphone-large': ('iPhoneLarge', ('testInvalidPalettePastePreservesHistory',
                'testLargestTextPaletteReviewAndImportHelp', 'testPalettePasteReviewAcceptAndRelaunch'), ()),
            'ipad-mini': ('iPadMini', ('testPaletteFileCancellationAndImportReturn',
                'testPrivacyCloseRetainsPhotoSelection'), ('testAccessibilityLiveCameraUnavailable',)),
            'ipad-large': ('iPadLarge', ('testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState',
                'testPalettePasteReviewAcceptAndRelaunch', 'testLiveCanvasPickerCancellationAndSceneLifecycle'), ()),
        }
        self.assertEqual(list(c.GROUPS), list(expected))
        self.assertEqual([(len(g['functional']),len(g['audits'])) for g in c.GROUPS.values()],
                         [(2,0),(3,0),(2,1),(3,0)])
        self.assertEqual(sum(len(g['functional']) for g in c.GROUPS.values()), 10)
        self.assertEqual(sum(len(g['audits']) for g in c.GROUPS.values()), 1)
        for identity, (family, functional, audits) in expected.items():
            selected = c.GROUPS[identity]
            cls = 'TouchColorIPadUITests' if family.startswith('iPad') else 'TouchColorUITests'
            self.assertEqual(selected['id'], identity)
            self.assertEqual(selected['family'], family)
            self.assertEqual(selected['functional'], tuple('TouchColorUITests/'+cls+'/'+name for name in functional))
            self.assertEqual(selected['audits'], tuple('TouchColorUITests/TouchColorAccessibilityUITests/'+name for name in audits))
            for selector in selected['functional'] + selected['audits']:
                target, klass, method = selector.split('/')
                self.assertEqual(target, 'TouchColorUITests')
                source = (ROOT/target/(klass+'.m')).read_text()
                self.assertIn('@implementation '+klass, source)
                self.assertEqual(len(re.findall(r'-\s*\(void\)\s*'+method+r'\s*\{', source)), 1)
        hosted=(ROOT/'TouchColorPhoneCompanion/Tests/PhonePaletteImportTests.swift').read_text()
        self.assertEqual(c.BOOTSTRAP, (
            'TouchColorTests/PhonePaletteImportTests/testOriginalIOSImportIsPresentWithoutCompanion',
            'TouchColorTests/PhonePaletteImportTests/testCancelledFileSelectionAndUnsupportedPasteRejectLatePriorRead'))
        for case in c.BOOTSTRAP:self.assertEqual(hosted.count('func '+case.rsplit('/',1)[1]+'('),1)
        executions=[(g['family'],case) for g in c.GROUPS.values() for case in g['bootstrap']]
        self.assertEqual(len(executions),8);self.assertEqual(len(set(executions)),8)
        self.assertEqual(212+36+47+4+11,310)  # Compact normal-paste is affected; old48 remain historical,47 reusable here.

    def test_nonmodal_bootstrap_is_existing_hosted_source_not_new_business_qualification(self):
        source=(ROOT/'TouchColorPhoneCompanion/Tests/PhonePaletteImportTests.swift').read_text()
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                         '11dad2857d71a00dee7aa845731af1db47a7a9891afa00c35aaa90568306c7c1')
        for selector in c.BOOTSTRAP:
            name=selector.rsplit('/',1)[1]
            body=source.split('func '+name+'()',1)[1].split('\n    func ',1)[0]
            for operation in ('UIWindow(','.present(','await fulfillment(','sendAction('):
                self.assertNotIn(operation,body)
            self.assertIn('PhonePaletteImportController(defaults:',body)
            self.assertIn('loadViewIfNeeded()',body)
            self.assertIn('XCTAssertEqual',body)
        self.assertNotIn('testActualAddColorsBarActionAppendsDuplicateSelectionAndDismisses',str(c.BOOTSTRAP))
        self.assertIn('func testActualAddColorsBarActionAppendsDuplicateSelectionAndDismisses()',source)

    def test_retired_split_groups_reject_in_all_route_guards(self):
        for family in ('iPadMini', 'iPadLarge'):
            for identity in ('ipad-mini-palette', 'ipad-mini-canvas',
                             'ipad-large-palette', 'ipad-large-canvas'):
                with self.subTest(family=family, group=identity), patch.dict(os.environ,
                        {**environment(), 'TC_COMPLETION_GROUP':identity, 'TC_TEST_FAMILY':family}, clear=True):
                    with self.assertRaises(ValueError):c.completion_group(family)
                    with self.assertRaises(ValueError):d.require_job(family)
                    for suite in m.STEPS:
                        with self.assertRaises(ValueError):c.selection(family,suite)
                        with self.assertRaises(ValueError):m.test_argv(family,suite,DEVICE)

    def test_exact_group_context_and_distinct_owned_names(self):
        names=[]
        for key,g in c.GROUPS.items():
            with patch.dict(os.environ,environment(key),clear=True):
                context=d.require_job(g['family'])
                self.assertEqual(context['completion_group'],key)
                self.assertFalse(context['full_original_row'])
                names.append(d.owned_name(context))
        self.assertEqual(len(set(names)),4)

    def test_foreign_source_ref_workflow_job_group_and_attempt_reject(self):
        mutations={'GITHUB_REPOSITORY':'other/ColorPicker','GITHUB_REF':d.REF,'GITHUB_WORKFLOW_REF':d.WORKFLOW,
            'GITHUB_JOB':'compatibility','GITHUB_WORKFLOW_SHA':'b'*40,'GITHUB_RUN_ID':'0',
            'GITHUB_RUN_ATTEMPT':'0','GITHUB_EVENT_NAME':'pull_request','TC_TEST_FAMILY':'iPhoneLarge',
            'TC_COMPLETION_GROUP':'ipad-large','RUNNER_OS':'Linux'}
        for key,value in mutations.items():
            with self.subTest(key=key),patch.dict(os.environ,{**environment(),key:value},clear=True):
                with self.assertRaises(ValueError):d.require_job('iPadMini')
        for absent in ('TC_COMPLETION_GROUP','GITHUB_SHA'):
            env=environment();del env[absent]
            with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):d.require_job('iPadMini')
        with patch.dict(os.environ,{'TC_COMPLETION_GROUP':'testWhatever'},clear=True),self.assertRaises(ValueError):
            c.completion_group('iPadMini')

    def test_exact_selection_argv_and_original_case_clocks(self):
        for key,g in c.GROUPS.items():
            with patch.dict(os.environ,environment(key),clear=True):
                for suite in m.STEPS:
                    cases=g[{'TouchColorTests':'bootstrap','TouchColorUITests':'functional','AccessibilityAudits':'audits'}[suite]]
                    if not cases:
                        with self.assertRaises(ValueError):m.test_argv(g['family'],suite,DEVICE)
                        continue
                    argv=m.test_argv(g['family'],suite,DEVICE)
                    self.assertEqual([v.removeprefix('-only-testing:') for v in argv if v.startswith('-only-testing:')],list(cases))
                    self.assertEqual(argv[argv.index('-default-test-execution-time-allowance')+1],'180')
                    self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance')+1],'240')
                    self.assertEqual(argv[-1],'test-without-building')
                    self.assertFalse(any('retry' in v or 'skip-testing' in v for v in argv))
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual([v for v in m.test_argv('iPadMini','TouchColorTests',DEVICE) if v.startswith('-only-testing:')],
                             ['-only-testing:TouchColorTests'])

    def test_workflow_has_four_closed_groups_and_original_finite_ceiling(self):
        text=(ROOT/'.github/workflows/ios-completion.yml').read_text()
        self.assertIn('branches: [codex/ios-original-completion]',text)
        self.assertIn('group: touchcolor-ios-refs/heads/codex/ios-original-release',text)
        self.assertIn('cancel-in-progress: false',text);self.assertIn('max-parallel: 2',text)
        self.assertNotIn('inputs:',text)
        for key,g in c.GROUPS.items():self.assertIn('{group: '+key+', family: '+g['family']+', audits: '+str(bool(g['audits'])).lower()+'}',text)
        matrix = re.findall(r'\{group: ([a-z-]+), family: ([A-Za-z]+), audits: (true|false)\}', text)
        self.assertEqual(matrix, [(key,g['family'],str(bool(g['audits'])).lower()) for key,g in c.GROUPS.items()])
        for retired in ('ipad-mini-palette','ipad-mini-canvas','ipad-large-palette','ipad-large-canvas'):
            self.assertNotIn(retired,text)
        self.assertLess(text.index('- name: Execute required selected StrictAll audits'),text.index('- name: Read bounded app diagnostics after required UI and audits'))
        audit=text.split('- name: Execute required selected StrictAll audits',1)[1].split('- name:',1)[0]
        self.assertIn("steps.seed-device.outcome == 'success'",audit)
        self.assertNotIn("functional-tests.outcome == 'success'",audit)
        self.assertIn('test_uikit_completion test_uikit_completion_evidence',text)
        self.assertIn("timeout-minutes: ${{ matrix.family == 'iPadMini' && 70 || 60 }}",text)
        self.assertEqual(sum(70 if g['family']=='iPadMini' else 60 for g in c.GROUPS.values()),250)
        self.assertEqual(sum((800 if g['family']=='iPadMini' else 500)+1100+(620 if g['audits'] else 0) for g in c.GROUPS.values()),7320)
        self.assertEqual(sum((960 if g['family']=='iPadMini' else 600)+1200+(720 if g['audits'] else 0) for g in c.GROUPS.values()),8280)


class SelectedExecution(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        self.stack=contextlib.ExitStack();self.stack.enter_context(patch.dict(os.environ,environment(),clear=True))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.setup=copy.deepcopy(SETUP);self.setup['binding']['context']=d.require_job('iPadMini')
        self.stack.enter_context(patch.object(m,'load_setup',return_value=self.setup))
        self.stack.enter_context(patch.object(m,'read_binding',return_value=self.setup['binding']))
        self.stack.enter_context(patch.object(m,'verify_source'))
        self.stack.enter_context(patch.object(m,'require_hosted'))
        self.stack.enter_context(patch.object(m,'require_fixtures'))
        self.tick=0.;self.calls=[];self.reads=[];self.failures=0;self.runner_change=None;self.reader_change=None
        self.suite='TouchColorTests';self.family='iPadMini'
    def tearDown(self):self.stack.close();os.chdir(self.old);self.temp.cleanup()
    def runner(self,argv,deadline):
        self.calls.append(argv);self.tick+=1
        value={'status':'timely_exit','exit_code':65 if self.failures else 0,'host_cleanup_confirmed':True,
            'argv':argv,'started_monotonic':0.,'finished_monotonic':self.tick,'deadline_monotonic':deadline,
            'elapsed_seconds':self.tick,'simulator_completion':'xcode_command_returned_only'}
        if self.runner_change:self.runner_change(value)
        return value
    def reader(self,argv,**kw):
        self.reads.append((argv,kw));selected=c.selection(self.family,self.suite)
        self.assertEqual(argv[4],'summary')
        value=summary(selected,self.failures)
        result=subprocess.CompletedProcess(argv,0,json.dumps(value).encode(),b'')
        if self.reader_change:self.reader_change(result,kw)
        return result
    def execute(self):
        return m.run_suite(self.family,self.suite,started=0,clock=lambda:self.tick,wall=lambda:1000+self.tick,
            runner=self.runner,reader=self.reader,products=lambda **kw:self.setup['products'])
    def receipt(self):return json.loads(m.record_path(self.family,self.suite).read_text())
    def pending(self):return Path('build/iPadMini-runtime-command-uncertain').exists()

    def test_real_two_case_bootstrap_receipt_and_raw_observations(self):
        self.assertEqual(self.execute(),0);r=self.receipt()
        self.assertEqual(r['schema'],3);self.assertEqual(r['selection']['kind'],'selected_bootstrap')
        self.assertFalse(r['selection']['full_target']);self.assertEqual(r['summary']['fields']['totalTestCount'],2)
        self.assertNotIn('cases',r);self.assertFalse(self.pending())
        self.assertTrue(r['summary_qualification_only'])
        self.assertEqual(r['case_identity_basis'],'fixed_executed_argv_and_complete_summary')
        self.assertEqual(r['per_case_log_reconciliation'],'pending_external_review')
        self.assertEqual([r[0][4] for r in self.reads],['summary'])
        for kind in ('summary',):
            raw=Path('build/iPadMini-TouchColorTests-selected-'+kind+'.json').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),r[kind]['sha256'])
        self.assertEqual(m.require_selected_bootstrap(self.family,self.setup,r,c.selection(self.family,self.suite)),r)
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):
            FULL_OR_SELECTED_HOSTED(self.family,self.setup)

    def test_later_seed_failure_cannot_erase_executed_bootstrap_evidence(self):
        self.assertEqual(self.execute(),0)
        paths=[m.record_path(self.family,self.suite),
            Path('build/iPadMini-TouchColorTests-selected-summary.json')]
        before=[path.read_bytes() for path in paths]
        with patch.object(m,'require_hosted',side_effect=FULL_OR_SELECTED_HOSTED), \
             patch.object(m.ManagedWarmup,'fixture_device',side_effect=RuntimeError('fixture failed')):
            with self.assertRaisesRegex(RuntimeError,'fixture failed'):
                m.fixture_seed(self.family,started=0,clock=lambda:self.tick)
        self.assertEqual([path.read_bytes() for path in paths],before)

    def test_fabricated_full_count_foreign_group_and_missing_case_cannot_bootstrap(self):
        self.execute();original=self.receipt();selected=c.selection(self.family,self.suite)
        for mutate in (lambda r:r.update(schema=1),lambda r:r['selection'].update(group='ipad-mini-palette'),
            lambda r:r['summary']['fields'].update(totalTestCount=54,passedTests=54),
            lambda r:r['summary'].pop('reader'),lambda r:r['command'].update(argv=['xcodebuild']),
            lambda r:r['command'].update(finished_monotonic=r['command']['deadline_monotonic']),
            lambda r:r['setup']['binding']['context'].update(sha='b'*40)):
            r=copy.deepcopy(original);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):m.require_selected_bootstrap(self.family,self.setup,r,selected)

    def test_complete_failed65_remains_failed_and_allows_required_audits(self):
        self.suite='TouchColorUITests';self.failures=1
        self.assertEqual(self.execute(),65);self.assertFalse(self.receipt()['qualified']);self.assertFalse(self.pending())
        self.assertEqual(self.receipt()['summary']['fields']['failedTests'],1)
        self.suite='AccessibilityAudits';self.tick=0.;self.failures=0
        self.assertEqual(self.execute(),0);self.assertEqual(len(self.calls),2)
        self.assertEqual(self.receipt()['summary']['fields']['totalTestCount'],1)

    def test_unknown_xctest_stops_before_readers_and_every_later_device_command(self):
        self.suite='TouchColorUITests'
        self.runner_change=lambda r:r.update(status='incomplete',host_cleanup_confirmed=True)
        self.assertEqual(self.execute(),3);self.assertTrue(self.pending());self.assertFalse(self.reads)
        self.suite='AccessibilityAudits'
        with self.assertRaises(m.WarmupFailed):self.execute()
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(m.WarmupFailed):m.ManagedWarmup(self.family,started=0,clock=lambda:self.tick)

    def test_unknown_exit_code_cannot_be_known_failed65(self):
        self.suite='TouchColorUITests';self.failures=1
        self.runner_change=lambda r:r.update(exit_code=70)
        self.assertEqual(self.execute(),3);self.assertTrue(self.pending());self.assertEqual(len(self.reads),1)

    def test_single_verified_summary_reader_keeps_original20_seconds(self):
        self.reader_change=lambda result,kw:setattr(self,'tick',self.tick+7)
        self.assertEqual(self.execute(),0)
        self.assertEqual([kw['seconds'] for _,kw in self.reads],[20])
        self.assertEqual(self.receipt()['summary']['reader']['returned_monotonic'],8)
        self.assertEqual(self.receipt()['timing']['reader_deadline_monotonic'],21)

    def test_late_summary_reader_keeps_command_and_stop_fence(self):
        self.reader_change=lambda result,kw:setattr(self,'tick',self.tick+kw['seconds'])
        self.assertEqual(self.execute(),3);self.assertTrue(self.pending())
        r=self.receipt();self.assertEqual(r['command']['status'],'timely_exit')
        self.assertEqual(r['summary']['status'],'reader_returned')

    def test_summary_reader_timeout_keeps_command_receipt(self):
        def fail(result,kw):raise CaptureStopped('timeout',True)
        self.reader_change=fail
        self.assertEqual(self.execute(),3);r=self.receipt()
        self.assertEqual(r['command']['status'],'timely_exit');self.assertEqual(r['summary']['status'],'unavailable')
        self.assertIn('reader',r['summary']);self.assertFalse(r['qualified']);self.assertTrue(self.pending())

    def probe_fixture(self):
        class ReachedLookup(Exception): pass
        with patch.object(m,'require_hosted',side_effect=FULL_OR_SELECTED_HOSTED), \
             patch.object(m,'read_managed_device_state',side_effect=ReachedLookup()) as lookup:
            try:
                m.fixture_seed(self.family,started=0,clock=lambda:self.tick)
            except ReachedLookup:
                return True, None
            except Exception as error:
                return lookup.called, error
        raise AssertionError('Fixture unexpectedly completed')

    def test_all12_reproduced_receipt_mutations_stop_before_fixture_lookup(self):
        self.assertEqual(self.execute(),0)
        original=self.receipt();raw_path=Path('build/iPadMini-TouchColorTests-selected-summary.json')
        raw=raw_path.read_bytes()
        mutations={
            'summary_exit_nonzero':lambda r:r['summary'].update(exit_code=9),
            'summary_cleanup_false':lambda r:r['summary'].update(host_cleanup_confirmed=False),
            'summary_digest_wrong':lambda r:r['summary'].update(sha256='0'*64),
            'summary_size_wrong':lambda r:r['summary'].update(bytes=0),
            'retired_case_exit_field':lambda r:r.update(cases={'status':'complete','exit_code':9}),
            'retired_case_cleanup_field':lambda r:r.update(cases={'status':'complete','host_cleanup_confirmed':False}),
            'retired_case_digest_field':lambda r:r.update(cases={'status':'complete','sha256':'0'*64}),
            'summary_original_interval_wrong':lambda r:r['summary']['fields'].update(startTime=-100,finishTime=999999999),
            'summary_interval_removed':lambda r:(r['summary']['fields'].pop('startTime'),r['summary']['fields'].pop('finishTime')),
            'command_deadline_expanded':lambda r:r['command'].update(deadline_monotonic=1000000000),
            'reader_proofs_removed':lambda r:[r['summary'].pop(k) for k in ('exit_code','host_cleanup_confirmed','sha256','bytes')],
            'raw_summary_missing':lambda r:None,
        }
        self.assertEqual(len(mutations),12)
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                value=copy.deepcopy(original);mutate(value)
                m.write_json(m.record_path(self.family,self.suite),value,limit=32768)
                raw_path.write_bytes(raw)
                if name=='raw_summary_missing':raw_path.unlink()
                entered,error=self.probe_fixture()
                self.assertFalse(entered);self.assertIsInstance(error,(ValueError,OSError))
                self.assertFalse(self.pending())

    def test_valid_reconstructed_receipt_reaches_the_original_fixture_lookup(self):
        self.assertEqual(self.execute(),0)
        entered,error=self.probe_fixture()
        self.assertTrue(entered);self.assertIsNone(error)

    def test_original_phase_admission_reader_boundaries_and_wall_bounds_reject(self):
        self.assertEqual(self.execute(),0);original=self.receipt()
        mutations=[
            lambda r:r['timing'].update(phase_deadline_monotonic=961),
            lambda r:r['timing'].update(admitted_monotonic=101),
            lambda r:r['timing'].update(command_origin_monotonic=.1),
            lambda r:r['timing'].update(command_wall_started=1000.2),
            lambda r:r['timing'].update(command_wall_finished=1000.8),
            lambda r:r['timing'].update(reader_deadline_monotonic=math.nextafter(21,math.inf)),
            lambda r:r['timing'].update(evidence_completed_monotonic=21),
            lambda r:r['summary']['reader'].update(entered_monotonic=.9),
            lambda r:r['summary']['reader'].update(returned_monotonic=21),
            lambda r:r['summary']['reader'].update(deadline_monotonic=math.nextafter(21,-math.inf)),
            lambda r:r['summary']['reader'].update(argv=['xcrun','xcresulttool','get','test-results','tests']),
            lambda r:r.update(schema=2),
        ]
        for mutate in mutations:
            value=copy.deepcopy(original);mutate(value)
            m.write_json(m.record_path(self.family,self.suite),value,limit=32768)
            with self.subTest(mutate=mutate):
                entered,error=self.probe_fixture();self.assertFalse(entered);self.assertIsInstance(error,ValueError)

    def test_actual_runner_entry_may_follow_original_mini_admission(self):
        self.runner_change=lambda r:r.update(started_monotonic=.25)
        self.assertEqual(self.execute(),0);value=self.receipt()
        self.assertEqual(value['timing']['command_origin_monotonic'],0)
        self.assertEqual(value['command']['deadline_monotonic'],800)
        self.assertEqual(value['command']['started_monotonic'],.25)
        entered,error=self.probe_fixture();self.assertTrue(entered);self.assertIsNone(error)

    def test_nonmini_origin_and_delayed_spawn_are_both_preserved(self):
        self.family='iPhoneCompact'
        with patch.dict(os.environ,environment('iphone-compact'),clear=True):
            self.setup['binding']['context']=d.require_job(self.family)
            self.setup['binding']['identity']['family']=self.family
            self.runner_change=lambda r:r.update(started_monotonic=.75)
            walls=[]
            def wall():
                if not walls:self.tick=.5;walls.append(True);return 1000
                return 1000+self.tick
            result=m.run_suite(self.family,self.suite,started=0,clock=lambda:self.tick,wall=wall,
                runner=self.runner,reader=self.reader,products=lambda **kw:self.setup['products'])
            self.assertEqual(result,0);value=self.receipt()
            self.assertEqual(value['timing']['admitted_monotonic'],0)
            self.assertEqual(value['timing']['command_origin_monotonic'],.5)
            self.assertEqual(value['command']['started_monotonic'],.75)
            self.assertEqual(value['command']['deadline_monotonic'],500.5)
            entered,error=self.probe_fixture();self.assertTrue(entered);self.assertIsNone(error)

    def test_reader_admission_and_later_clipped_entry_remain_distinct(self):
        stages=[]
        def products(**kwargs):
            stages.extend([919.5,920.5])
            return self.setup['products']
        def clock():
            if stages:self.tick=stages.pop(0)
            return self.tick
        result=m.run_suite(self.family,self.suite,started=0,clock=clock,wall=lambda:1000+self.tick,
            runner=self.runner,reader=self.reader,products=products)
        self.assertEqual(result,0);value=self.receipt()
        self.assertEqual(value['timing']['reader_admitted_monotonic'],919.5)
        self.assertEqual(value['timing']['reader_started_monotonic'],920.5)
        self.assertEqual(value['timing']['reader_deadline_monotonic'],940)
        self.assertEqual(self.reads[0][1]['seconds'],19.5)
        self.assertEqual(m.require_selected_bootstrap(self.family,self.setup,value,c.selection(self.family,self.suite)),value)

    def test_raw_summary_is_reparsed_even_with_updated_digest_and_saved_flags(self):
        self.assertEqual(self.execute(),0);original=self.receipt()
        raw_path=Path('build/iPadMini-TouchColorTests-selected-summary.json');raw=raw_path.read_bytes()
        for mutate in (lambda v:v.update(totalTestCount=54,passedTests=54),
                       lambda v:v.update(startTime=0),
                       lambda v:v['devicesAndConfigurations'][0]['device'].update(deviceId='foreign'),
                       lambda v:v.update(skippedTests=1,passedTests=1)):
            value=copy.deepcopy(original);body=json.loads(raw);mutate(body);changed=json.dumps(body).encode()
            raw_path.write_bytes(changed)
            value['summary'].update(bytes=len(changed),sha256=hashlib.sha256(changed).hexdigest())
            m.write_json(m.record_path(self.family,self.suite),value,limit=32768)
            with self.subTest(mutate=mutate):
                entered,error=self.probe_fixture();self.assertFalse(entered);self.assertIsInstance(error,ValueError)

    def reread_cost(self,tick):
        original=m.read_regular
        def delayed(path,*args,**kwargs):
            raw=original(path,*args,**kwargs)
            if str(path).endswith('-selected-summary.json'):self.tick=tick
            return raw
        return patch.object(m,'read_regular',side_effect=delayed)

    def test_raw_reread_overhead_at_original_fixture_cleanup_boundary_stops(self):
        self.assertEqual(self.execute(),0)
        with self.reread_cost(580):
            entered,error=self.probe_fixture()
        self.assertFalse(entered);self.assertIsInstance(error,ValueError)
        self.assertIn('caller phase',str(error))

    def test_raw_reread_before_original_fixture_cleanup_boundary_continues(self):
        self.assertEqual(self.execute(),0)
        with self.reread_cost(math.nextafter(580,-math.inf)):
            entered,error=self.probe_fixture()
        self.assertTrue(entered);self.assertIsNone(error)

    def test_known_failed_bootstrap_stays_failed_and_cannot_seed(self):
        self.failures=1
        self.assertEqual(self.execute(),65);value=self.receipt()
        self.assertFalse(value['qualified']);self.assertEqual(value['summary']['fields']['result'],'Failed')
        self.assertEqual(value['command']['exit_code'],65);self.assertFalse(self.pending())
        entered,error=self.probe_fixture();self.assertFalse(entered);self.assertIsInstance(error,ValueError)
        self.assertEqual(self.receipt(),value)

    def test_full_command_and_tails_must_fit_before_execution(self):
        self.suite='TouchColorUITests';self.tick=40
        self.assertEqual(self.execute(),3);self.assertFalse(self.calls);self.assertFalse(self.reads)


class SelectedResources(ManagedFixture):
    """Run the actual receipt producer/reader with synthetic process responses."""
    @contextlib.contextmanager
    def rig(self, group, state='Booted'):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            os.chdir(folder)
            stack.callback(os.chdir, previous)
            stack.enter_context(patch.dict(os.environ, environment(group), clear=True))
            self.family = c.GROUPS[group]['family']
            self.tick = 100.
            self.create(family=self.family)
            self.binding = d.read_binding(self.family)
            self.setup = {'schema': 1, 'binding': self.binding, 'products': SETUP['products']}
            stack.enter_context(patch.object(m, 'product_identity', return_value=self.setup['products']))
            m.write_json(m.record_path(self.family, 'setup'), self.setup)
            self.state, self.action, self.calls = state, None, []
            self.tick = 100.
            self.controller = m.ManagedWarmup(self.family, started=100, clock=lambda: self.tick,
                                               host_runner=self.host_runner)
            with patch.object(m, 'ManagedWarmup', return_value=self.controller):
                result = m.run_suite(self.family, 'TouchColorTests', started=100, clock=lambda: self.tick,
                    wall=lambda: 1000+self.tick, runner=self.bootstrap_runner, reader=self.bootstrap_reader,
                    products=lambda **kw: self.setup['products'])
            self.assertEqual(result, 0)
            self.started = self.tick
            self.controller = m.ManagedWarmup(self.family, started=self.started, clock=lambda: self.tick,
                                               host_runner=self.host_runner)
            self.calls = []
            yield

    def bootstrap_runner(self, argv, deadline):
        began = self.tick; self.tick += 1
        return {'status': 'timely_exit', 'exit_code': 0, 'host_cleanup_confirmed': True,
                'argv': argv, 'started_monotonic': began, 'finished_monotonic': self.tick,
                'deadline_monotonic': deadline, 'simulator_completion': 'xcode_command_returned_only'}

    def bootstrap_reader(self, argv, **kwargs):
        value = summary(c.selection(self.family, 'TouchColorTests'))
        value.update(startTime=1000+self.tick-.9, finishTime=1000+self.tick-.1)
        value['devicesAndConfigurations'][0]['device']['deviceId'] = NEW
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b'')

    def host_runner(self, argv, *, timeout):
        self.calls.append((list(argv), timeout))
        self.assertTrue(self.controller.pending.exists())
        self.tick += .01
        if self.action:
            result = self.action(argv, timeout)
            if result is not None: return result
        if argv == ['git', 'rev-parse', 'HEAD']:
            output = self.binding['context']['sha']
        elif argv == d.READBACK:
            output = json.dumps(self.after(self.family, state=self.state))
        elif argv[2:3] == ['bootstatus']:
            output = ('Monitoring boot status for '+self.binding['receipt']['requested_name']+' ('+NEW+').\n'
                      'Device already booted, nothing to do.\n\n')
        else:
            output = ''
        if argv[2:3] == ['addmedia']:
            self.assertTrue(Path(argv[-1]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        return subprocess.CompletedProcess(argv, 0, output, '')

    def seed(self):
        with patch.object(m, 'ManagedWarmup', return_value=self.controller):
            m.fixture_seed(self.family, started=self.started, clock=lambda: self.tick)

    def operations(self):
        return [argv[2] if argv[:2] == ['xcrun', 'simctl'] else argv[0] for argv, _ in self.calls]

    def receipt(self):
        return json.loads(m.record_path(self.family, 'fixtures').read_text())

    def test_all_four_skip_files_and_only_ipads_seed_photos(self):
        for group in c.GROUPS:
            with self.subTest(group=group), self.rig(group), patch.object(self.controller, 'fixture') as fixture:
                before = self.binding
                self.seed(); value = self.receipt()
                fixture.assert_not_called()
                photos = group.startswith('ipad-')
                self.assertEqual(self.operations(), ['git', 'git', 'list'] + (['addmedia'] if photos else []))
                self.assertEqual(value['schema'], 3)
                self.assertEqual(value['selection'], c.resource_selection(self.family))
                self.assertEqual(value['resources'], {'files': 'not-required-by-exact-selection',
                    'photos': 'performed-success' if photos else 'not-required-by-exact-selection'})
                self.assertEqual(Path('build', self.family+'-fixture-seeded').exists(), photos)
                self.assertEqual(value['readiness']['basis'], 'owned_booted_inventory_snapshot_only')
                self.assertEqual(d.read_binding(self.family), before)
                self.assertEqual(self.controller.deadline, self.started+600)
                self.assertFalse(self.controller.pending.exists())
                m.require_fixtures(self.family, self.setup)

    def test_shutdown_readiness_keeps_exact_boot_pair_and_original_caps(self):
        for group in c.GROUPS:
            with self.subTest(group=group), self.rig(group, state='Shutdown'):
                self.seed()
                self.assertEqual(self.operations(), ['git', 'git', 'list', 'boot', 'bootstatus'] +
                                 (['addmedia'] if group.startswith('ipad-') else []))
                grants = [grant for argv, grant in self.calls if argv[2:3] in (['boot'], ['bootstatus'])]
                self.assertEqual(len(grants), 2)
                for grant, cap in zip(grants, (180, 240)): self.assertAlmostEqual(grant, cap)
                self.assertEqual(self.receipt()['readiness']['basis'], 'owned_bootstatus_completion_observation_only')
                m.require_fixtures(self.family, self.setup)

    def test_forged_omissions_and_false_success_or_foreign_selection_reject(self):
        for group in ('iphone-compact', 'ipad-mini'):
            with self.subTest(group=group), self.rig(group):
                self.seed(); original = self.receipt()
                mutations = [lambda r: r['resources'].pop('photos'),
                    lambda r: r['resources'].update(files='performed-success'),
                    lambda r: r['selection']['functional'].pop(),
                    lambda r: r['selection'].update(group='ipad-large'),
                    lambda r: r['selection']['functional'].append(
                        'TouchColorUITests/TouchColorIPadUITests/testPaletteFileSelectionReviewAndRelaunch'),
                    lambda r: r['selection']['required'].update(photos=not group.startswith('ipad-')),
                    lambda r: r['selection']['required'].update(files=0),
                    lambda r: r.update(complete=False), lambda r: r.update(schema=2),
                    lambda r: r['setup']['binding']['context'].update(sha='b'*40),
                    lambda r: r['setup']['products'].update(tree_sha256='c'*64),
                    lambda r: r['readiness'].update(binding_sha256='d'*64)]
                for mutate in mutations:
                    value = copy.deepcopy(original); mutate(value)
                    m.write_json(m.record_path(self.family, 'fixtures'), value)
                    with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                        m.require_fixtures(self.family, self.setup)
                value = copy.deepcopy(original)
                value['resources']['photos'] = 'not-required-by-exact-selection' if group.startswith('ipad-') else 'performed-success'
                m.write_json(m.record_path(self.family, 'fixtures'), value)
                with self.assertRaises(ValueError): m.require_fixtures(self.family, self.setup)

    def test_required_photo_marker_cannot_be_missing_or_foreign(self):
        for group in ('ipad-mini', 'ipad-large'):
            with self.subTest(group=group), self.rig(group):
                self.seed(); marker = Path('build', self.family+'-fixture-seeded')
                marker.unlink()
                with self.assertRaises(OSError): m.require_fixtures(self.family, self.setup)
                m.write_json(marker, {**self.binding['identity'], 'udid': DEVICE})
                with self.assertRaises(ValueError): m.require_fixtures(self.family, self.setup)

    def test_selected_receipt_cannot_admit_original_or_foreign_source_route(self):
        with self.rig('ipad-mini'):
            self.seed()
            changes = [{'GITHUB_REF': d.REF, 'GITHUB_WORKFLOW_REF': d.WORKFLOW, 'GITHUB_JOB': 'compatibility'},
                {'GITHUB_SHA': 'b'*40, 'GITHUB_WORKFLOW_SHA': 'b'*40},
                {'GITHUB_RUN_ATTEMPT': '2'}, {'TC_COMPLETION_GROUP': 'ipad-large'},
                {'GITHUB_REPOSITORY': 'other/ColorPicker'}]
            for change in changes:
                with self.subTest(change=change), patch.dict(os.environ, change), self.assertRaises(ValueError):
                    m.require_fixtures(self.family, self.setup)
            with patch.dict(os.environ, {k:v for k,v in os.environ.items() if k!='TC_COMPLETION_GROUP'}, clear=True), \
                    self.assertRaises(ValueError):
                m.require_fixtures(self.family, self.setup)

    def test_bad_bootstrap_blocks_resource_omission_before_simulator_lookup(self):
        with self.rig('iphone-compact'):
            path = m.record_path(self.family, 'TouchColorTests')
            value = json.loads(path.read_text()); value['summary']['fields']['passedTests'] = 54
            m.write_json(path, value)
            with self.assertRaises(ValueError): self.seed()
            self.assertEqual(self.calls, [])
            self.assertFalse(m.record_path(self.family, 'fixtures').exists())

    def test_source_and_products_still_checked_before_resource_handoff(self):
        for changed in ('source', 'products'):
            with self.subTest(changed=changed), self.rig('iphone-large'):
                if changed == 'source':
                    self.action = lambda argv, timeout: subprocess.CompletedProcess(argv, 0, 'b'*40, '')
                    context = contextlib.nullcontext()
                else:
                    context = patch.object(m, 'product_identity', return_value={'changed': True})
                with context, self.assertRaises(ValueError): self.seed()
                self.assertNotIn('list', self.operations())
                self.assertFalse(m.record_path(self.family, 'fixtures').exists())

    def test_handoff_and_photo_work_share_original_remaining_preparation_budget(self):
        with self.rig('ipad-large', state='Shutdown'):
            def spend(argv, timeout):
                if argv[2:3] == ['boot']: self.tick += 170
                if argv[2:3] == ['bootstatus']: self.tick += 230
            self.action = spend
            self.seed()
            grant = next(grant for argv, grant in self.calls if argv[2:3] == ['addmedia'])
            self.assertLess(grant, 180); self.assertGreater(grant, 179)
            self.assertEqual(self.controller.deadline, self.started+600)
            m.require_fixtures(self.family, self.setup)

    def test_final_setup_read_cannot_publish_after_original_cleanup_boundary(self):
        for group in ('iphone-large', 'ipad-mini'):
            with self.subTest(group=group), self.rig(group):
                original = m.load_setup
                count = []
                def slow(family):
                    value = original(family); count.append(family)
                    if len(count) == 2: self.tick = self.controller.deadline-20
                    return value
                with patch.object(m, 'load_setup', side_effect=slow), self.assertRaises(m.WarmupFailed):
                    self.seed()
                self.assertFalse(m.record_path(self.family, 'fixtures').exists())

    def test_uncertain_boot_or_photos_never_publish_or_allow_later_commands(self):
        for operation, group in (('boot', 'iphone-compact'), ('bootstatus', 'ipad-mini'), ('addmedia', 'ipad-large')):
            with self.subTest(operation=operation), self.rig(group, state='Shutdown'):
                def fail(argv, timeout):
                    if argv[2:3] == [operation]:
                        error = subprocess.TimeoutExpired(argv, timeout); error.cleanup_confirmed = True
                        raise error
                self.action = fail
                with self.assertRaises(m.WarmupFailed): self.seed()
                self.assertEqual(self.operations()[-1], operation)
                self.assertTrue(self.controller.pending.exists())
                self.assertFalse(m.record_path(self.family, 'fixtures').exists())
                before = len(self.calls)
                with self.assertRaises(m.WarmupFailed):
                    m.ManagedWarmup(self.family, started=self.started, clock=lambda: self.tick)
                self.assertEqual(len(self.calls), before)


if __name__=='__main__':unittest.main()
