import copy
import hashlib
from pathlib import Path
import re
import unittest
from job_budget import JobBudget, BudgetExhausted, create_record, RESERVES

class Clock:
    def __init__(self): self.wall = 10000.; self.mono = 100.
    def advance(self, seconds): self.wall += seconds; self.mono += seconds

class JobBudgetTests(unittest.TestCase):
    def budget(self, platform='vision', minutes=25):
        c=Clock(); env={'TOUCHCOLOR_JOB_PLATFORM':platform,'TOUCHCOLOR_JOB_MINUTES':str(minutes),'TOUCHCOLOR_JOB_STARTED_EPOCH':str(c.wall),'TOUCHCOLOR_JOB_STARTED_MONOTONIC':str(c.mono),'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123'}
        record=create_record(env,wall=lambda:c.wall,monotonic=lambda:c.mono)
        return c, JobBudget(record,wall=lambda:c.wall,monotonic=lambda:c.mono)
    def test_exact_job_rows_include_setup_and_all_tail_reserves(self):
        for platform,minutes in [('vision',25),('watch',45),('tv',25),('mac',40),('ios',20),('paired',45)]:
            c,b=self.budget(platform,minutes)
            self.assertEqual(b.remaining(),minutes*60-30-sum(RESERVES.values()))
            c.advance(75)
            self.assertEqual(b.remaining(),minutes*60-105-sum(RESERVES.values()))
            self.assertGreater(b.remaining('cleanup'),b.remaining())
            self.assertEqual(b.remaining('upload')-b.remaining('validation'),60)
        with self.assertRaises(ValueError): self.budget('vision',30)
    def test_measured_watch_candidate_preserves_reserve_without_claiming_unrun_gate(self):
        _,watch=self.budget('watch',45)
        self.assertEqual(watch.remaining(),37*60)
        recorded_seconds=1138.251
        self.assertAlmostEqual(watch.remaining()-recorded_seconds,1081.749)
        self.assertAlmostEqual(watch.remaining()-recorded_seconds-600-2*120-41,200.749)
        non_ui_seconds=recorded_seconds-345.469
        self.assertAlmostEqual(watch.remaining()-(non_ui_seconds+840+600),-12.782)
        # Added cases fit inside the existing840s UI command cap, not on top of it.
        # Measured-path margin does not guarantee simultaneous full phase ceilings.
        self.assertEqual(RESERVES['evidence'],180)
        self.assertEqual(RESERVES['upload'],60)
        with self.assertRaises(ValueError):self.budget('watch',25)
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/apple-platforms.yml').read_text().split('  native-platform:',1)[1]
        rows=re.findall(r'- platform: (\w+)(.*?)(?=\n          - platform:|\n    runs-on:)',source,re.S)
        self.assertEqual(len(rows),15)
        watch_rows=0
        for platform,body in rows:
            minutes=int(re.search(r'            minutes: (\d+)',body).group(1))
            expected={'watch':45,'vision':25,'tv':25,'mac':40,'ios':20,'paired':45}[platform]
            self.assertEqual(minutes,expected)
            if platform=='watch':watch_rows+=1;self.assertIn('evidence_bytes: 2000000',body)
        self.assertEqual(watch_rows,2)
        self.assertIn("--label 'Native watchOS executable and real simulator workflows' --seconds 2520",source)
        self.assertIn('max-parallel: 2',source)

    def test_work_clock_does_not_use_wall_clock_adjustments(self):
        c,b=self.budget();before=b.remaining();c.wall += 3600
        self.assertEqual(b.remaining(),before)
        c.mono += 12;self.assertEqual(b.remaining(),before-12)
    def test_phase_cannot_start_if_its_minimum_and_cleanup_do_not_fit(self):
        c,b=self.budget();c.advance(970)
        self.assertEqual(b.admit('metadata',30,cleanup=20),30)
        with self.assertRaises(BudgetExhausted):b.admit('mandatory UI',600,minimum=180,cleanup=130)
        self.assertEqual(b.snapshot()['result'],'incomplete')
        self.assertEqual(b.events[-1]['result'],'not_started_insufficient_budget')
    def test_granted_command_is_clamped_without_borrowing_upload_time(self):
        c,b=self.budget();c.advance(400)
        self.assertEqual(b.admit('UI',600,minimum=180,cleanup=130),490)
        c.advance(490+130)
        self.assertEqual(b.remaining(),0)
        self.assertEqual(b.remaining('cleanup'),130)
        self.assertEqual(b.remaining('evidence'),310)
        self.assertEqual(b.remaining('upload'),430)
    def test_unknown_group_cleanup_blocks_work_and_diagnostics(self):
        c,b=self.budget();b.latch_cleanup_failure()
        for phase in ('work','cleanup','evidence'):
            with self.assertRaises(BudgetExhausted): b.admit('no new subprocess',3,phase=phase)
        self.assertTrue(b.snapshot()['cleanup_unconfirmed'])
    def test_missing_future_expired_and_wrong_source_contract_fail_closed(self):
        c,b=self.budget()
        for key,bad in [('started_epoch',float('nan')),('started_epoch',10010),('sha','bad'),('reserves',{}),('minutes',30)]:
            value=copy.deepcopy(b.record);value[key]=bad
            with self.assertRaises(ValueError):JobBudget(value,wall=lambda:c.wall,monotonic=lambda:c.mono)
        c.advance(2000)
        expired=JobBudget(b.record,wall=lambda:c.wall,monotonic=lambda:c.mono)
        with self.assertRaises(BudgetExhausted):expired.admit('not started',10)
    def test_reload_cannot_reset_elapsed_time_or_extend_on_backward_clock(self):
        c,b=self.budget(); original=b.remaining()
        c.advance(400)
        c.wall -= 300
        reloaded=JobBudget(b.record,wall=lambda:c.wall,monotonic=lambda:c.mono)
        self.assertEqual(reloaded.remaining(),original-400)
        c.wall += 700
        forward=JobBudget(b.record,wall=lambda:c.wall,monotonic=lambda:c.mono)
        self.assertLess(forward.remaining(),reloaded.remaining())
    def test_exhausted_work_still_has_owned_cleanup_and_full_export_upload(self):
        c,b=self.budget(); c.advance(b.remaining())
        with self.assertRaises(BudgetExhausted):b.admit('mandatory runtime',600,minimum=180,cleanup=0)
        self.assertEqual(b.admit('restore owned device',60,cleanup=20,phase='cleanup'),60)
        c.advance(RESERVES['cleanup'])
        self.assertEqual(b.remaining('evidence'),180)
        self.assertEqual(b.remaining('validation'),240)
        self.assertEqual(b.remaining('upload'),300)
        c.advance(180+60)
        self.assertEqual(b.remaining('upload'),60)
    def test_workflow_retains_all_source_owned_runtime_bodies_and_reserves(self):
        # SHA256 of the admitted 80cef6ad runtime bodies, canonical final newline.
        expected={'Probe native XCTest accessibility audit availability': '3289e3a0d40a7715405b97bfd04b60d0f0646789df4128e545e96583eb5e5b74', 'Portable domain, raster and preservation tests': '481dcff1ef190ac1a22bbe7c72c77db44d0a0197740a7d5e0d4203df327a7aa1', 'Build native arm64 Release app and inspect identity': '75e8af28e3dcc1e5c4e4da915af9d0784115ea9907ceb0c91d5c266bc73d8736', 'Build x86_64 slice only if accepted by the real SDK': '78101fa508d2534c555adac5e2484b90169832199263511eb262261c1488ca74', 'Native Mac app-hosted unit tests': '4599f3a49e43c42f3b22e9e04592e1f802257994f2ef0bfcc913fe3e5bd072b4', 'Native Mac UI runtime workflows': 'c9d9bf7d2fb9eefc0f312e56b04959d6686466eb26469fd087364d5c0163d4dd', 'Diagnose standard AppKit modal audits separately': '16bd8feeb51209e2173d6d21ddc1cdeabdf69c0fac4a3cb3d22ffeb2b3346b3d', 'Native visionOS executable and real simulator workflows': 'e1c0d694b66fe4450cbe9d9cbccd2a3b67ca30446942dce343ba3037aa764a7c', 'Native watchOS executable and real simulator workflows': '9a31c27561abb183eeef07b389090755479d61bc9a401289caab8b7e38527194', 'Native tvOS executable and real remote workflows': 'd729a7de26973b765d3c14d5e3d11cdc9babf06e59860fc881bd61a05061eecc', 'Real paired foreground Watch and phone review workflows': '36a5b8f9fd5cd9b29b59140e97adf6b6138edaec854c5229f15794987146f9b7', 'Minimal ad-hoc sandbox native Mac UI workflows': '1eedde3049ff4e1ec37e8907d1ae8d3744d5850187218a2fb9b1d319a98fd74b', 'Build original iOS app and direct cross-language equivalence tests': 'e4a9142f46e75b558cc6b84bda70b3a2938f2665ca98641c1e11147932517ac2', 'Shut down iOS test simulator': '0bc6d61609898270b7b12680c8ac56c247714fedb0818623b390b3c2f679c07a'}
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/apple-platforms.yml').read_text()
        actual={}
        for match in re.finditer(r"python3 scripts/run_budgeted_step.py (?:--cleanup-driver )?--label '([^']+)'[^\n]+<<'TC_BUDGET_BODY'\n(.*?)^          TC_BUDGET_BODY$",source,re.M|re.S):
            label,body=match.groups()
            if label in expected:
                body='\n'.join(line[10:] if line.startswith(' '*10) else line for line in body.splitlines()).rstrip('\n')+'\n'
                actual[label]=hashlib.sha256(body.encode()).hexdigest()
        self.assertEqual(actual,expected)
        self.assertLess(source.index('Start exact native job clock'),source.index('Initialize exact row budget'))
        self.assertIn("--seconds 180 --phase evidence",source)
        self.assertIn("limit=int(os.environ['TOUCHCOLOR_EVIDENCE_LIMIT'])-16384",source)
        self.assertIn("steps.upload_budget.outcome == 'success'",source)
        self.assertIn('retention-days: 1',source)
    def test_phase_restore_and_invalid_budget_values(self):
        c,b=self.budget()
        with b.using_phase('cleanup'):self.assertEqual(b.phase,'cleanup')
        self.assertEqual(b.phase,'work')
        for requested,minimum,cleanup in [(0,1,0),(5,6,0),(5,1,-1),(float('nan'),1,0)]:
            with self.assertRaises(ValueError):b.admit('bad',requested,minimum=minimum,cleanup=cleanup)

if __name__=='__main__':unittest.main()
