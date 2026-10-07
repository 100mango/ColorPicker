"""Closed one-job Photos route; standard-library-only prerequisite checks."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
BRANCH='codex/vision-row-repair'
WORKFLOW='100mango/ColorPicker/.github/workflows/vision-row-repair.yml@refs/heads/'+BRANCH
ROW='vision-photos'


def steps(text):
    return dict((m.group(1),m.group(0)) for m in re.finditer(
        r'^      - name: ([^\n]+)\n.*?(?=^      - name: |\Z)',text,re.M|re.S))


def projected_workflow(canonical):
    """Named closed projection from the unchanged canonical workflow bytes."""
    prefix=canonical.split('jobs:\n',1)[0]
    prefix=prefix.replace('name: Native Apple platform milestone','name: Fixed Vision Photos qualification',1)
    prefix=prefix.replace('branches: [codex/platform-integration]\n  workflow_dispatch:\n','branches: ['+BRANCH+']\n',1)
    prefix=prefix.replace('group: touchcolor-platforms-${{ github.ref }}','group: touchcolor-platforms-refs/heads/codex/platform-integration',1)
    prerequisite=steps(canonical.split('  native-prerequisites:\n',1)[1].split('  native-platform:\n',1)[0])
    row=steps(canonical.split('  native-platform:\n',1)[1])
    portable=prerequisite['Fail closed on setup regression failures']
    portable=portable.replace('          set -euo pipefail\n', '          set -euo pipefail\n          unset TOUCHCOLOR_VISION_COMPLETION_SCOPE # Portable fixtures cover canonical and completion scopes explicitly.\n',1)
    portable=portable.replace(' test_uikit_warmup\n',' test_uikit_warmup test_vision_repair_route test_vision_photos_scope\n')
    portable=portable.replace(' test_native_text_evidence\n',' test_native_text_evidence test_vision_repair_route test_vision_photos_scope\n')
    toolchain=row['Verify source and stable toolchain']
    toolchain=toolchain.replace('test "$GITHUB_REF" = refs/heads/codex/platform-integration',
        'test "$GITHUB_REF" = refs/heads/'+BRANCH+'\n          test "$GITHUB_WORKFLOW_REF" = '+WORKFLOW)
    # Portable checks move intact into this same job; only Vision is generated.
    remove=('generate_project.py','generate_mac_project.py','generate_watch_project.py','generate_tv_project.py','verify_mac_icons.py')
    toolchain='\n'.join(line for line in toolchain.split('\n') if not any('scripts/'+name in line for name in remove)
        and not line.strip().startswith('python3 scripts/test_')
        and 'xcodebuild -list -project TouchColorMac.xcodeproj' not in line)
    toolchain=toolchain.replace('if test "$TOUCHCOLOR_JOB_PLATFORM" = vision; then python3 scripts/vision_offline_result.py prepare-reader; fi',
                                'python3 scripts/vision_offline_result.py prepare-reader')
    header='''jobs:
  native-platform:
    name: Vision Photos on one fresh standard VM
    runs-on: xcode-27
    timeout-minutes: 35
    env:
      TOUCHCOLOR_JOB_PLATFORM: vision
      TOUCHCOLOR_JOB_MINUTES: 35
      TOUCHCOLOR_JOB_LANE: vision-photos
      DEVELOPER_DIR: /Applications/Xcode_27.app/Contents/Developer
      TOUCHCOLOR_WATCH_PROFILE: ''
      TOUCHCOLOR_TEXT_PHASE: normal
      TOUCHCOLOR_VISION_CASE: photos
      TOUCHCOLOR_EVIDENCE_LIMIT: 950000
    steps:
'''
    ordered=[row['Start exact native job clock'],row['Check out exact source'],row['Initialize exact row budget'],
        portable,toolchain,row['Native visionOS executable and real simulator workflows'],
        row['Report bounded evidence and unchanged source'],row['Validate final evidence byte and path limits'],
        row['Verify artifact upload reserve'],row['Retain small test evidence for review'],
        row['Require every deferred Vision result qualification'],row['Require complete exact native text row evidence']]
    result=prefix+header+''.join(ordered)
    result=result.replace("!cancelled() && matrix.platform == 'vision' &&", "!cancelled() &&")
    result=result.replace("${{ matrix.platform == 'vision' && 6 || 4 }}",'6')
    result=result.replace("${{ matrix.platform == 'vision' && 300 || 180 }}",'300')
    result=result.replace('${{ matrix.lane || matrix.platform }}',ROW)
    result=result.replace("${{ always() && matrix.platform == 'vision' }}",'always()')
    result=result.replace("${{ always() && (matrix.platform == 'vision' || matrix.platform == 'watch') }}",'always()')
    return result


class FixedVisionRepairRouteTests(unittest.TestCase):
    def setUp(self):
        self.base=(ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.text=(ROOT/'.github/workflows/vision-row-repair.yml').read_text()

    def test_exact_push_only_identity_no_selector_inputs(self):
        self.assertEqual(self.text.split('on:\n',1)[1].split('permissions:',1)[0],
                         '  push:\n    branches: ['+BRANCH+']\n')
        self.assertIn('permissions:\n  contents: read\n',self.text)
        self.assertNotIn(BRANCH,(ROOT/'.github/workflows/ios.yml').read_text())
        self.assertIn('group: touchcolor-platforms-refs/heads/codex/platform-integration\n  cancel-in-progress: false',self.text)
        self.assertNotIn('workflow_dispatch',self.text);self.assertNotIn('inputs.',self.text)

    def test_exact_one_job_one_photos_slice_no_prerequisite_or_matrix(self):
        self.assertEqual(re.findall(r'^  ([a-z-]+):$',self.text.split('jobs:\n',1)[1],re.M),['native-platform'])
        self.assertEqual(self.text.count('    runs-on: xcode-27\n'),1)
        self.assertIn('    timeout-minutes: 35\n',self.text)
        for field,value in [('TOUCHCOLOR_JOB_PLATFORM','vision'),('TOUCHCOLOR_JOB_LANE','vision-photos'),
                            ('TOUCHCOLOR_VISION_CASE','photos'),('TOUCHCOLOR_TEXT_PHASE','normal'),('TOUCHCOLOR_EVIDENCE_LIMIT','950000')]:
            self.assertIn('      '+field+': '+value+'\n',self.text)
        for forbidden in ('strategy:','matrix.','needs:','native-prerequisites:', 'max-parallel:'):
            self.assertNotIn(forbidden,self.text)
        for project in ('TouchColorMac.xcodeproj','TouchColorTV.xcodeproj','TouchColorWatch.xcodeproj','TouchColor.xcodeproj'):
            self.assertNotIn(project,self.text)

    def test_exact_projection_preserves_admitted_vision_runtime_and_evidence(self):
        self.assertEqual(self.text,projected_workflow(self.base))
        for label in ('Native visionOS executable and real simulator workflows','Report bounded evidence and unchanged source',
                      'Validate final evidence byte and path limits','Verify artifact upload reserve',
                      'Require every deferred Vision result qualification','Require complete exact native text row evidence'):
            self.assertEqual(self.text.count('- name: '+label+'\n'),1)
        self.assertIn('--seconds 1500 --phase work',self.text)
        self.assertIn('--seconds 300 --phase evidence',self.text)
        self.assertIn('retention-days: 1',self.text)

    def test_portable_checks_move_intact_without_native_unrelated_rebuilds(self):
        self.assertEqual(self.text.count(' test_vision_repair_route test_vision_photos_scope\n'),2)
        self.assertIn('      - name: Fail closed on setup regression failures\n',self.text)
        self.assertIn('unset TOUCHCOLOR_VISION_COMPLETION_SCOPE',self.text)
        self.assertIn('python3 scripts/generate_vision_project.py',self.text)
        for forbidden in ('generate_mac_project.py','generate_watch_project.py','generate_tv_project.py','generate_project.py',
                          'swift test --package-path','Compile both native Mac','Compile real paired','Compile native Vision and TV'):
            self.assertNotIn(forbidden,self.text)
        self.assertNotIn('pip install',self.text)

    def test_guards_bind_actual_repository_workflow_source(self):
        for line in ['test "$GITHUB_REPOSITORY" = 100mango/ColorPicker','test "$GITHUB_REF" = refs/heads/'+BRANCH,
                     'test "$GITHUB_WORKFLOW_REF" = '+WORKFLOW,'test "$GITHUB_WORKFLOW_SHA" = "$GITHUB_SHA"',
                     'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"']:
            self.assertIn(line,self.text)
        self.assertIn('persist-credentials: false',self.text)
        self.assertIn('ref: ${{ github.sha }}',self.text)
        self.assertIn('git diff --exit-code HEAD --',self.text)

    def test_current_photos_runs_real_hosted_then_normal_with_canonical_roles(self):
        from native_text_rows import row, vision_roles
        binding=row('vision','normal','photos','','a'*40)
        self.assertEqual(binding['schema'],2)
        self.assertEqual(vision_roles(binding),['hosted','normal'])
        self.assertNotIn('      TOUCHCOLOR_VISION_COMPLETION_SCOPE:',self.text)
        self.assertNotIn('python3 scripts/vision_photos_scope.py',self.text)
        self.assertNotIn('hosted_reuse',self.text)
        self.assertIn('python3 scripts/test_extra_platforms.py vision',self.text)

    def test_failed_photos_seed_never_falls_through_to_skipped_xctest(self):
        import ast
        from unittest.mock import Mock
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text())
        gate=next(node for node in ast.walk(source) if isinstance(node,ast.If)
            and isinstance(node.test,ast.Name) and node.test.id=='photo_seed_failed'
            and any(isinstance(value,ast.Constant) and value.value=='Photos completion fixture seed did not succeed'
                    for value in ast.walk(node)))
        self.assertFalse(any(isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value.startswith('-skip-testing:') for value in ast.walk(gate)))
        for started,timeout,code,confirmed,expected_fence in [(True,True,124,True,True),(True,False,1,True,False),
                (False,False,124,True,False),(True,False,124,True,True),(True,False,1,False,True)]:
            with self.subTest(started=started,timeout=timeout,code=code,confirmed=confirmed):
                report={'stages':[{'started':started,'timed_out':timeout,'exit':code,'process_group_gone':confirmed,'capture_reader_finished':True}]}
                state={'photo_seed_failed':True,'report':report,'fail_record':Mock()}
                with self.assertRaisesRegex(RuntimeError,'fixture seed'):
                    exec(compile(ast.Module(body=[gate],type_ignores=[]),'actual Photos seed gate','exec'),state)
                self.assertEqual(report.get('cleanup_unconfirmed',False),expected_fence)
                self.assertEqual(report.get('simulator_operation_unconfirmed',False),expected_fence)
                self.assertEqual(state['fail_record'].called,expected_fence)

    def test_real_timed_out_host_process_still_fences_actual_driver_cleanup(self):
        import ast
        import subprocess
        import sys
        from unittest.mock import Mock, patch
        import test_vision_runner_lease as lease
        harness=lease.RunnerLeaseDriverTests(methodName='runTest');harness.setUp()
        harness.state['out']=harness.state['out'].resolve()
        self.addCleanup(harness.doCleanups)
        # A real disposable local child exercises the production run/termination
        # path. It is not a native simulator execution or a canned timeout result.
        with patch('job_budget.enabled_budget',return_value=None):
            code=harness.state['run']([sys.executable,'-c','import time; time.sleep(1)'],.02,required=False)
        self.assertEqual(code,124)
        stage=harness.state['report']['stages'][-1]
        self.assertTrue(stage['timed_out']);self.assertTrue(stage['process_group_gone'])
        self.assertTrue(stage['capture_reader_finished'])
        source=ast.parse((ROOT/'scripts/test_extra_platforms.py').read_text())
        gate=next(node for node in ast.walk(source) if isinstance(node,ast.If)
            and isinstance(node.test,ast.Name) and node.test.id=='photo_seed_failed'
            and any(isinstance(value,ast.Constant) and value.value=='Photos completion fixture seed did not succeed'
                    for value in ast.walk(node)))
        import os
        import json
        from job_budget import fail_record, UNCLEAN
        harness.state.update(photo_seed_failed=True,fail_record=fail_record)
        previous=Path.cwd()
        try:
            os.chdir(harness.state['out'])
            with self.assertRaisesRegex(RuntimeError,'fixture seed'):
                exec(compile(ast.Module(body=[gate],type_ignores=[]),'actual Photos seed gate','exec'),harness.state)
            self.assertTrue(json.loads(UNCLEAN.read_text())['cleanup_unconfirmed'])
        finally:os.chdir(previous)
        with patch('job_budget.enabled_budget',return_value=None),patch.object(subprocess,'Popen') as start:
            self.assertEqual(harness.state['run'](['xcrun','simctl','shutdown',lease.DEVICE],3,required=False),124)
        start.assert_not_called()
        # Execute the actual finally body: no resource/device query, shutdown or
        # readback is allowed; host-only failure JSON must still be written.
        harness.final_cleanup()

    def test_projection_detects_added_row_or_relaxed_gate(self):
        expected=projected_workflow(self.base)
        mutations=[expected.replace('    timeout-minutes: 35','    timeout-minutes: 36',1),
                   expected.replace('TOUCHCOLOR_VISION_CASE: photos','TOUCHCOLOR_VISION_CASE: chinese',1),
                   expected.replace('    runs-on: xcode-27','    runs-on: xcode-27-xlarge',1),
                   expected.replace('        run: test "$NATIVE_TEXT_EVIDENCE_COMPLETE" = true','        run: true',1),
                   expected+'  extra-job:\n    runs-on: xcode-27\n']
        for changed in mutations:self.assertNotEqual(changed,expected)


if __name__=='__main__':unittest.main()
