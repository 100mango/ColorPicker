"""Closed Mac-only selector; all existing workflow bytes otherwise preserved."""
from pathlib import Path
import hashlib
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
REMOVED='          - platform: watch\n            lane: watch-smallest\n            watch_profile: smallest\n            text_phase: normal\n            minutes: 45\n            evidence_bytes: 1200000\n          - platform: watch\n            lane: watch-largest\n            watch_profile: largest\n            text_phase: normal\n            minutes: 45\n            evidence_bytes: 1200000\n'
ORIGINAL_SHA='7d53b7e708d47927edf9d95da7cc1738a2d5cb422991d22ba2158ecf79ac1b0f'

class MacOnlyRepairRoute(unittest.TestCase):
    def setUp(self):
        self.raw=(ROOT/'.github/workflows/mac-watch-repair.yml').read_text()
        self.workflow=yaml.load(self.raw,Loader=yaml.BaseLoader)
    def test_only_two_fixed_watch_rows_removed(self):
        marker='    runs-on: xcode-27\n'
        position=self.raw.index(marker,self.raw.index('  native-platform:'))
        restored=self.raw[:position]+REMOVED+self.raw[position:]
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),ORIGINAL_SHA)
    def test_exact_one_mac_row_and_original_caps(self):
        job=self.workflow['jobs']['native-platform']
        self.assertEqual(job['strategy']['matrix']['include'],[dict(platform='mac',minutes='40',evidence_bytes='3000000')])
        self.assertEqual(job['strategy']['max-parallel'],'2')
        self.assertEqual(job['runs-on'],'xcode-27')
        self.assertEqual(job['needs'],'native-prerequisites')
    def test_exact_push_only_branch_and_existing_group(self):
        self.assertEqual(self.workflow['on'],{'push':{'branches':['codex/mac-watch-repair']}})
        self.assertEqual(self.workflow['concurrency'],{'group':'touchcolor-platforms-refs/heads/codex/platform-integration','cancel-in-progress':'false'})
        self.assertEqual(self.workflow['permissions'],{'contents':'read'})
    def test_existing_two_jobs_and_no_manual_selector(self):
        self.assertEqual(list(self.workflow['jobs']),['native-prerequisites','native-platform'])
        self.assertNotIn('workflow_dispatch',self.workflow['on'])
        self.assertNotIn('inputs.',self.raw)
    def test_collector_remains_existing_mac_tail_once(self):
        self.assertEqual(self.raw.count('python3 scripts/mac_passive_lifecycle.py'),1)
        self.assertLess(self.raw.index('python3 scripts/mac_passive_lifecycle.py'),self.raw.index('python3 scripts/retain_mac_evidence.py'))

if __name__=='__main__':unittest.main()
