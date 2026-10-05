"""Portable source contracts only; these are not Swift/native execution proof."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def release_projection(source):
    output, stack = [], []
    active = True
    for line in source.splitlines(keepends=True):
        directive = line.strip()
        if directive.startswith('#if '):
            is_debug = directive == '#if DEBUG'
            stack.append((active, is_debug))
            if is_debug: active = False
            elif active: output.append(line)
        elif directive == '#else' and stack:
            parent, is_debug = stack[-1]
            if is_debug: active = parent and not active
            elif active: output.append(line)
        elif directive == '#endif' and stack:
            parent, is_debug = stack.pop()
            if not is_debug and active: output.append(line)
            active = parent
        elif active:
            output.append(line)
    if stack: raise ValueError('Unbalanced Swift directives')
    return ''.join(output)


class WatchCrownPacketInvariantTests(unittest.TestCase):
    def test_watch_views_release_projection_is_frozen(self):
        projection = release_projection((ROOT/'TouchColorWatch/WatchViews.swift').read_text())
        self.assertEqual(hashlib.sha256(projection.encode()).hexdigest(), 'e9af1534757f85078775d01e7f368eb7ceebc6fb19cc7a54d65979700efd3622')
        self.assertEqual(release_projection((ROOT/'TouchColorWatch/WatchHomeDiagnostics.swift').read_text()), '')

    def test_product_app_and_existing_workflow_budget_are_frozen(self):
        expected = {
            'TouchColorWatch/TouchColorWatchApp.swift': '9cfbaeeab92b0573afaa40d5255e48551c6caa9f2bbf9068e7f05306c0013b32',
            '.github/workflows/apple-platforms.yml': '8c4e6fff2438d42838e718107a16db951629febd8a9cbe43e346c90e0f78e8e7',
            'scripts/generate_watch_project.py': '9d49206c796355267fb1389829f2c7dff4177e3ff1a6867c95b05f6bee147de9',
        }
        for path, sha in expected.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), sha, path)

    def test_distinct_twenty_five_minute_proposal_balances_without_borrowing(self):
        proposal = json.loads((ROOT/'review/watch-crown-control-budget-proposal.json').read_text())
        self.assertEqual(proposal['status'], 'proposal_only_not_admitted_not_run')
        self.assertEqual(proposal['profiles'], ['smallest'])
        self.assertEqual(proposal['runner_class'], 'existing_standard_VM_only')
        self.assertEqual(proposal['job_timeout_minutes'], 25)
        self.assertEqual(proposal['startup_margin_seconds'], 30)
        self.assertEqual(proposal['reserves_seconds'], dict(cleanup=130,evidence=180,validation=60,upload=60,overhead=20))
        work = 25*60 - proposal['startup_margin_seconds'] - sum(proposal['reserves_seconds'].values())
        self.assertEqual(work, proposal['maximum_work_seconds'])
        self.assertEqual(sum(proposal['sequential_work_plan_seconds'].values()), proposal['work_plan_seconds'])
        self.assertEqual(work-proposal['work_plan_seconds'], proposal['unallocated_work_seconds'])
        self.assertEqual(proposal['test_execution_allowance_seconds'], 120)
        self.assertEqual(proposal['test_launch_allowance_seconds'], 60)
        minimum = proposal['test_execution_allowance_seconds'] + proposal['test_launch_allowance_seconds']
        self.assertEqual(proposal['minimum_test_phase_seconds'], minimum)
        for name in ('actual_cold_test_including_install_launch', 'isolated_static_control_including_install_launch',
                     'unchanged_rgb_positive_control_including_launch'):
            self.assertGreaterEqual(proposal['sequential_work_plan_seconds'][name], minimum, name)
        self.assertEqual(proposal['home_observation_bytes']+proposal['static_control_observation_bytes'], 32768)
        self.assertEqual(proposal['evidence_cap_bytes'], 1200000)
        workflow = (ROOT/'review/watch-crown-control-workflow.yml.proposal').read_text()
        self.assertIn('timeout-minutes: 25', workflow)
        self.assertIn('TOUCHCOLOR_JOB_PLATFORM: watch-crown-control', workflow)
        self.assertIn('exit 1', workflow)
        self.assertLess(workflow.index('Stamp original absolute budget'), workflow.index('Exact source checkout'))
        # The preserved inactive proposal is historical. Runnable contract now
        # has an independently bounded identity and a dedicated push-only branch.
        from job_budget import EXPECTED_MINUTES, RESERVES, STARTUP_MARGIN
        self.assertEqual(EXPECTED_MINUTES['watch'],45)
        self.assertEqual(EXPECTED_MINUTES['watch-crown-control'],25)
        self.assertEqual(RESERVES,proposal['reserves_seconds'])
        self.assertEqual(STARTUP_MARGIN,proposal['startup_margin_seconds'])
        active=(ROOT/'.github/workflows/watch-crown-control.yml').read_text()
        self.assertIn('branches: [codex/watch-crown-diagnostic]',active)
        self.assertNotIn('workflow_dispatch:',active)


if __name__ == '__main__': unittest.main()
