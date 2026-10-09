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
    def assert_historical_workflow(self, raw):
        # Reverse only the four reviewed full-line naming edits. Exact counts
        # reject omitted, duplicated, mixed-old/new, or broadened route guards.
        naming_edits = (
            ('    branches: [mac-watch-repair]\n',
             '    branches: [codex/mac-watch-repair]\n', 1),
            ('  group: touchcolor-platforms-refs/heads/platform-integration\n',
             '  group: touchcolor-platforms-refs/heads/codex/platform-integration\n', 1),
            ('          test "$GITHUB_REF" = refs/heads/mac-watch-repair\n',
             '          test "$GITHUB_REF" = refs/heads/codex/mac-watch-repair\n', 2),
            ('          test "$GITHUB_WORKFLOW_REF" = 100mango/ColorPicker/.github/workflows/mac-watch-repair.yml@refs/heads/mac-watch-repair\n',
             '          test "$GITHUB_WORKFLOW_REF" = 100mango/ColorPicker/.github/workflows/mac-watch-repair.yml@refs/heads/codex/mac-watch-repair\n', 2),
        )
        projected = raw
        for renamed, historical, count in naming_edits:
            self.assertEqual(projected.count(renamed), count)
            self.assertNotIn(historical, projected)
            projected = projected.replace(renamed, historical, count)
        marker='    runs-on: xcode-27\n'
        # Preserve the historical hash after reversing only the reviewed query-path fix.
        original_query = "-destination 'generic/platform=macOS' ARCHS=arm64 CODE_SIGNING_ALLOWED=NO -showBuildSettings"
        reviewed_query = "-destination 'generic/platform=macOS' -derivedDataPath build/mac-arm64 ARCHS=arm64 CODE_SIGNING_ALLOWED=NO -showBuildSettings"
        self.assertEqual(projected.count(reviewed_query), 1)
        projected = projected.replace(reviewed_query, original_query, 1)
        position=projected.index(marker,projected.index('  native-platform:'))
        restored=projected[:position]+REMOVED+projected[position:]
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),ORIGINAL_SHA)
    def test_only_two_fixed_watch_rows_and_reviewed_naming_edits(self):
        self.assert_historical_workflow(self.raw)
    def test_historical_fingerprint_rejects_unrelated_workflow_changes(self):
        for original, changed in (
            ('contents: read', 'contents: write'),
            ('cancel-in-progress: false', 'cancel-in-progress: true'),
            ('evidence_bytes: 3000000', 'evidence_bytes: 3000001'),
            ('max-parallel: 2', 'max-parallel: 3'),
        ):
            self.assertIn(original, self.raw)
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                self.assert_historical_workflow(self.raw.replace(original, changed, 1))
    def test_naming_projection_rejects_missing_extra_and_historical_guards(self):
        guard = '          test "$GITHUB_REF" = refs/heads/mac-watch-repair\n'
        for changed in ('', guard + guard, guard.replace('heads/', 'heads/codex/')):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                self.assert_historical_workflow(self.raw.replace(guard, changed, 1))
    def test_exact_one_mac_row_and_original_caps(self):
        job=self.workflow['jobs']['native-platform']
        self.assertEqual(job['strategy']['matrix']['include'],[dict(platform='mac',minutes='40',evidence_bytes='3000000')])
        self.assertEqual(job['strategy']['max-parallel'],'2')
        self.assertEqual(job['runs-on'],'xcode-27')
        self.assertEqual(job['needs'],'native-prerequisites')
    def test_exact_push_only_branch_and_existing_group(self):
        self.assertEqual(self.workflow['on'],{'push':{'branches':['mac-watch-repair']}})
        self.assertEqual(self.workflow['concurrency'],{'group':'touchcolor-platforms-refs/heads/platform-integration','cancel-in-progress':'false'})
        self.assertEqual(self.workflow['permissions'],{'contents':'read'})
    def test_existing_two_jobs_and_no_manual_selector(self):
        self.assertEqual(list(self.workflow['jobs']),['native-prerequisites','native-platform'])
        self.assertNotIn('workflow_dispatch',self.workflow['on'])
        self.assertNotIn('inputs.',self.raw)
    def test_collector_remains_existing_mac_tail_once(self):
        self.assertEqual(self.raw.count('python3 scripts/mac_passive_lifecycle.py'),1)
        self.assertLess(self.raw.index('python3 scripts/mac_passive_lifecycle.py'),self.raw.index('python3 scripts/retain_mac_evidence.py'))

if __name__=='__main__':unittest.main()
