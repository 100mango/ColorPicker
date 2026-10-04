"""Source contracts for the optional one-lane paired qualifier; no CI launch."""
import hashlib
from pathlib import Path
import re
import subprocess
import unittest
from job_budget import EXPECTED_MINUTES, RESERVES, STARTUP_MARGIN

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'.github/workflows/apple-platforms.yml'
PAIR=ROOT/'.github/workflows/paired-qualification.yml'

def block(text,name):
    parts=text.split('      - name: '+name+'\n',1)
    if len(parts)!=2:raise AssertionError('Missing step '+name)
    return parts[1].split('\n      - name:',1)[0]

def body(step):
    value=step.split('        run: |\n',1)[1]
    return '\n'.join(line[10:] if line.startswith(' '*10) else line for line in value.splitlines()).rstrip()+'\n'

class PairedWorkflowTests(unittest.TestCase):
    def setUp(self):self.native=NATIVE.read_text();self.paired=PAIR.read_text()

    def test_exact_single_branch_single_job_and_read_only_permissions(self):
        self.assertIn('on:\n  push:\n    branches: [codex/apple-platforms]\n',self.paired)
        self.assertNotIn('workflow_dispatch',self.paired)
        self.assertNotIn('pull_request',self.paired)
        self.assertEqual(re.findall(r'^  ([A-Za-z0-9_-]+):$',self.paired.split('jobs:\n',1)[1],re.M),['paired-qualification'])
        self.assertIn('permissions:\n  contents: read\n',self.paired)
        self.assertIn('group: touchcolor-paired-diagnostic-${{ github.ref }}',self.paired)
        self.assertIn('cancel-in-progress: false',self.paired)
        self.assertIn('runs-on: xcode-27',self.paired)
        self.assertNotIn('matrix.',self.paired)
        for expected in ('test "$GITHUB_EVENT_NAME" = push', 'test "$GITHUB_REPOSITORY" = 100mango/ColorPicker',
                         'test "$GITHUB_REF" = refs/heads/codex/apple-platforms',
                         'test "$GITHUB_WORKFLOW_SHA" = "$GITHUB_SHA"', 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
                         'persist-credentials: false','ref: ${{ github.sha }}'):
            self.assertIn(expected,self.paired)

    def test_existing_full_workflows_are_not_rebound_or_truncated(self):
        self.assertEqual(hashlib.sha256(NATIVE.read_bytes()).hexdigest(),'d9a1c0b0144459bf209a039ba75d63a88a6a6bf05feda3f4ae9bde5af028e168')
        ios=(ROOT/'.github/workflows/ios.yml').read_text()
        self.assertIn('branches: [codex/platform-integration]',ios)
        self.assertIn('branches: [codex/platform-integration]',self.native)
        self.assertNotIn('codex/apple-platforms',self.native)
        self.assertNotIn('codex/apple-platforms',ios)

    def test_exact_paired_driver_body_and_guard_preserve_failure(self):
        name='Real paired foreground Watch and phone review workflows'
        self.assertEqual(body(block(self.paired,name)),body(block(self.native,name)))
        item=block(self.paired,name)
        self.assertIn("steps.toolchain.outcome == 'success' && steps.regressions.outcome == 'success'",item)
        self.assertNotIn('continue-on-error',item)
        self.assertNotIn('|| true',item)
        self.assertIn('--cleanup-driver',item)
        self.assertIn('--seconds 2520 --phase work',item)

    def test_all_existing_prerequisites_run_with_isolated_alias_fixtures(self):
        def commands(text):return [line.strip().split('python3 ',1)[1] for line in text.splitlines() if '-m unittest -v ' in line]
        actual=commands(self.paired);expected=commands(self.native.split('  native-platform:',1)[0])
        self.assertEqual(actual,[line+' test_paired_qualification_workflow' for line in expected])
        for mode in ('normal','optimized'):
            self.assertIn('TMPDIR="$fixture_root/alias" GITHUB_ENV="$fixture_root/'+mode+'-env" GITHUB_OUTPUT="$fixture_root/'+mode+'-output"',self.paired)
        self.assertIn('ln -s physical "$fixture_root/alias"',self.paired)
        self.assertIn('python3 test_evidence_guard.py',self.paired)

    def test_exact_job_budget_evidence_guard_and_upload_reserve(self):
        self.assertEqual(EXPECTED_MINUTES['paired'],45)
        self.assertEqual(sum(RESERVES.values()),450);self.assertEqual(STARTUP_MARGIN,30)
        self.assertIn('    timeout-minutes: 45\n',self.paired)
        self.assertIn('TOUCHCOLOR_JOB_PLATFORM: paired',self.paired)
        self.assertIn('TOUCHCOLOR_JOB_MINUTES: 45',self.paired)
        self.assertIn('TOUCHCOLOR_EVIDENCE_LIMIT: 1000000',self.paired)
        self.assertLess(self.paired.index('Start exact native job clock'),self.paired.index('Initialize exact row budget'))
        self.assertIn('--seconds 180 --phase evidence',self.paired)
        for name in ('Validate final evidence byte and path limits','Verify artifact upload reserve'):
            self.assertEqual(block(self.paired,name),block(self.native,name))
        upload=block(self.paired,'Retain small test evidence for review')
        self.assertIn("steps.evidence_guard.outcome == 'success' && steps.upload_budget.outcome == 'success'",upload)
        self.assertIn('retention-days: 1',upload)
        self.assertIn('timeout-minutes: 1',upload)
        self.assertIn('actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',upload)

    def test_evidence_collector_is_the_existing_bounded_body(self):
        name='Report bounded evidence and unchanged source'
        original=body(block(self.native,name)).replace("echo 'Intel slice build outcome: ${{ steps.intel.outcome }}; Intel runtime: not tested'", "echo 'arm64 owned paired Simulator qualification; no Intel or physical-device claim'")
        self.assertEqual(body(block(self.paired,name)),original)
        self.assertIn('if: always()',block(self.paired,name))

    def test_all_shell_blocks_parse_without_untrusted_expression_evaluation(self):
        count=0
        for part in self.paired.split('      - name: ')[1:]:
            if '        run: |\n' in part:script=body(part)
            elif '        run: ' in part:script=part.split('        run: ',1)[1].splitlines()[0]
            else:continue
            script=re.sub(r'\$\{\{.*?\}\}','FIXTURE',script)
            result=subprocess.run(['bash','-n'],input=script,text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr);count+=1
        self.assertEqual(count,8)

if __name__=='__main__':unittest.main()
