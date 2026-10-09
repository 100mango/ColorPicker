"""Portable admission negatives only; no Apple build/runtime or corrected-source pass claim."""
import contextlib
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import platform_qualification as q

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('.github/workflows/apple-platforms.yml', 'scripts/retain_mac_evidence.py', 'scripts/test_retain_mac_evidence.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            text = (ROOT / name).read_text()
            if name == 'scripts/retain_mac_evidence.py':
                text = text.replace(q.MAC_IDENTITY, '')
            if name == 'scripts/test_retain_mac_evidence.py':
                for old, new in q.MAC_IDENTITY_TEST_EDITS:
                    text = text.replace(new, old)
            path.write_text(text)
        (self.root / 'Product.swift').write_text('corrected product\n')
        self.run_git('init', '-q', '-b', 'touchcolor-platform-qualification')
        self.run_git('add', '-A')
        self.run_git('commit', '-qm', 'synthetic corrected product fixture')
        self.product = self.run_git('rev-parse', 'HEAD')
        self.product_tree = self.run_git('rev-parse', 'HEAD^{tree}')
        for name in q.OVERLAY_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, path)
        self.config = {'schema': 1, 'READY': True, 'corrected_product_sha': self.product,
                       'corrected_product_tree': self.product_tree, 'selected_lane': 'tv'}
        (self.root / q.CONFIG).write_text(json.dumps(self.config))
        with cwd(self.root):
            path = self.root / q.WORKFLOW
            path.write_text(q.render_selection(path.read_text(), self.config))
        self.run_git('add', '-A')
        self.run_git('commit', '-qm', 'synthetic control overlay fixture')
        self.env = {
            'GITHUB_REPOSITORY': q.REPOSITORY, 'GITHUB_REF': q.REF, 'GITHUB_WORKFLOW_REF': q.WORKFLOW_REF,
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_JOB': 'native-platform',
        }
        self.rebind_control()
        self.sync_row_env()

    def run_git(self, *args):
        return subprocess.check_output(['git', '-c', 'user.name=Portable fixture', '-c',
                                       'user.email=fixture@localhost', *args], cwd=self.root, text=True).strip()

    def rebind_control(self):
        control = self.run_git('rev-parse', 'HEAD')
        self.env.update(GITHUB_SHA=control, GITHUB_WORKFLOW_SHA=control)

    @contextlib.contextmanager
    def enabled_fixture(self):
        with cwd(self.root):
            yield

    def sync_row_env(self):
        try:
            with cwd(self.root):
                row = q.select(self.config['selected_lane'])
        except ValueError:
            return
        self.env.update(TOUCHCOLOR_JOB_PLATFORM=row['platform'], TOUCHCOLOR_JOB_LANE=row.get('lane', row['platform']),
                        TOUCHCOLOR_JOB_MINUTES=str(row['minutes']), TOUCHCOLOR_EVIDENCE_LIMIT=str(row['evidence_bytes']),
                        TOUCHCOLOR_VISION_CASE=row.get('vision_case', ''), TOUCHCOLOR_WATCH_PROFILE=row.get('watch_profile', ''),
                        TOUCHCOLOR_TEXT_PHASE=row.get('text_phase', ''))

    def render_fixture(self):
        with cwd(self.root):
            path = self.root / q.WORKFLOW
            try:
                rendered = q.render_selection(path.read_text(), self.config)
            except ValueError:
                return
            path.write_text(rendered)

    def configure(self, **changes):
        self.config.update(changes)
        (self.root / q.CONFIG).write_text(json.dumps(self.config))
        self.render_fixture()
        self.run_git('add', '-A'); self.run_git('commit', '--amend', '--no-edit', '-q'); self.rebind_control()
        self.sync_row_env()

    def test_delivered_guard_is_closed_before_any_source_execution(self):
        config = json.loads((ROOT / q.CONFIG).read_text())
        self.assertIs(config['READY'], False)
        self.assertEqual(config['corrected_product_sha'], 'UNBOUND')
        self.assertEqual(config['corrected_product_tree'], 'UNBOUND')
        with cwd(ROOT), patch.object(q, 'git', side_effect=AssertionError('must not read source')):
            with self.assertRaisesRegex(ValueError, 'closed'):
                q.admit(self.env)

    def test_exact_bindings_allow_exactly_one_existing_row(self):
        with self.enabled_fixture():
            for lane in q.LANES:
                if lane in ('ios', 'paired'):
                    continue
                self.configure(selected_lane=lane)
                result = q.admit(self.env)
                self.assertEqual(result['row'].get('lane', result['row']['platform']), lane)
                self.assertEqual(result['corrected_product_sha'], self.product)
                self.assertEqual(result['native_execution'], 'not established by admission')

    def test_wrong_identity_event_and_missing_bindings_fail(self):
        mutations = {
            'GITHUB_REPOSITORY': 'other/ColorPicker', 'GITHUB_REF': 'refs/heads/codex/platform-integration',
            'GITHUB_WORKFLOW_REF': q.REPOSITORY + '/.github/workflows/apple-platforms.yml@' + q.REF,
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_JOB': 'admit',
            'GITHUB_SHA': 'e' * 40, 'GITHUB_WORKFLOW_SHA': 'f' * 40,
        }
        with self.enabled_fixture():
            for key, value in mutations.items():
                for candidate in (value, ''):
                    with self.subTest(key=key, value=candidate), self.assertRaises(ValueError):
                        q.admit({**self.env, key: candidate})

    def test_no_default_wildcard_multilane_or_legacy_selection(self):
        with self.enabled_fixture():
            for lane in ('', 'unselected', 'all', 'tv,mac', 'vision', 'watch', 'ios', 'paired', None):
                self.configure(selected_lane=lane)
                with self.subTest(lane=lane), self.assertRaises(ValueError):
                    q.admit(self.env)

    def test_malformed_or_unbound_product_bindings_fail(self):
        with self.enabled_fixture():
            for key in ('corrected_product_sha', 'corrected_product_tree'):
                for value in ('UNBOUND', 'main', 'a' * 39, 'A' * 40, 'a' * 40 + '\n', '; echo unsafe'):
                    self.configure(**{key: value})
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        q.admit(self.env)
                self.configure(corrected_product_sha=self.product, corrected_product_tree=self.product_tree)

    def test_wrong_product_tree_or_absent_root_fails(self):
        with self.enabled_fixture():
            self.configure(corrected_product_tree='a' * 40)
            with self.assertRaisesRegex(ValueError, 'tree mismatch'):
                q.admit(self.env)
            self.configure(corrected_product_tree=self.product_tree, corrected_product_sha='b' * 40)
            with self.assertRaisesRegex(ValueError, 'root absent'):
                q.admit(self.env)

    def test_ready_requires_exact_boolean_and_schema_is_closed(self):
        with self.enabled_fixture():
            for value in (False, 'true', 1, None):
                self.configure(READY=value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    q.admit(self.env)
            self.configure(READY=True, control_sha='self-referential control input is forbidden')
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                q.admit(self.env)

    def test_source_edits_cannot_hide_in_control_commit(self):
        (self.root / 'Product.swift').write_text('unexpected source resurrection\n')
        self.run_git('add', '-A'); self.run_git('commit', '--amend', '--no-edit', '-q'); self.rebind_control()
        with self.enabled_fixture(), self.assertRaisesRegex(ValueError, 'transition changed product'):
            q.admit(self.env)

    def test_historical_mac_assertion_changes_rejected(self):
        path = self.root / 'scripts/retain_mac_evidence.py'
        path.write_text(path.read_text().replace("'complete': False", "'complete': True"))
        self.run_git('add', '-A'); self.run_git('commit', '--amend', '--no-edit', '-q'); self.rebind_control()
        with self.enabled_fixture(), self.assertRaisesRegex(ValueError, 'Historical Mac evidence code'):
            q.admit(self.env)

    def test_two_parents_cannot_pass_control_only_guard(self):
        tree = self.run_git('rev-parse', 'HEAD^{tree}')
        other = self.run_git('commit-tree', self.product_tree, '-m', 'unrelated parent fixture')
        merge = self.run_git('commit-tree', tree, '-p', self.product, '-p', other, '-m', 'merge fixture')
        self.run_git('reset', '--hard', '-q', merge); self.rebind_control()
        with self.enabled_fixture(), self.assertRaisesRegex(ValueError, 'sole parent'):
            q.admit(self.env)

    def test_sequential_lane_controls_pass_without_rewriting_product(self):
        self.config['selected_lane'] = 'mac'
        (self.root / q.CONFIG).write_text(json.dumps(self.config))
        self.render_fixture()
        self.run_git('add', '-A'); self.run_git('commit', '-qm', 'next explicit lane'); self.rebind_control(); self.sync_row_env()
        with self.enabled_fixture():
            receipt = q.admit(self.env)
            self.assertEqual(receipt['control_commits'], 2)
            self.assertEqual(receipt['row']['platform'], 'mac')

    def test_temporarily_changed_product_cannot_be_hidden_by_revert(self):
        (self.root / 'Product.swift').write_text('temporary changed product')
        self.run_git('add', '-A'); self.run_git('commit', '-qm', 'unapproved product edit')
        (self.root / 'Product.swift').write_text('corrected product\n')
        self.run_git('add', '-A'); self.run_git('commit', '-qm', 'revert product edit'); self.rebind_control()
        with self.enabled_fixture(), self.assertRaisesRegex(ValueError, 'transition changed product'):
            q.admit(self.env)

    def test_control_chain_bound_is_enforced(self):
        self.config['selected_lane'] = 'mac'
        (self.root / q.CONFIG).write_text(json.dumps(self.config))
        self.render_fixture()
        self.run_git('add', '-A'); self.run_git('commit', '-qm', 'next explicit lane'); self.rebind_control(); self.sync_row_env()
        with self.enabled_fixture(), patch.object(q, 'MAX_CONTROL_COMMITS', 1), self.assertRaisesRegex(ValueError, 'root absent'):
            q.admit(self.env)

    def test_dirty_and_untracked_files_rejected(self):
        with self.enabled_fixture():
            path = self.root / 'unexpected.txt'; path.write_text('extra')
            with self.assertRaisesRegex(ValueError, 'Dirty'):
                q.admit(self.env)
            path.unlink()
            path = self.root / 'Product.swift'; path.write_text('dirty product')
            with self.assertRaisesRegex(ValueError, 'Dirty'):
                q.admit(self.env)

    def test_native_job_cannot_change_row_budget_or_case(self):
        with self.enabled_fixture():
            row = q.select('vision-photos')
            self.configure(selected_lane='vision-photos')
            env = {**self.env, 'GITHUB_JOB': 'native-platform',
                   'TOUCHCOLOR_JOB_PLATFORM': 'vision', 'TOUCHCOLOR_JOB_LANE': 'vision-photos',
                   'TOUCHCOLOR_JOB_MINUTES': str(row['minutes']), 'TOUCHCOLOR_EVIDENCE_LIMIT': str(row['evidence_bytes']),
                   'TOUCHCOLOR_VISION_CASE': 'photos', 'TOUCHCOLOR_TEXT_PHASE': 'normal'}
            q.admit(env)
            for key in ('TOUCHCOLOR_JOB_PLATFORM', 'TOUCHCOLOR_JOB_LANE', 'TOUCHCOLOR_JOB_MINUTES',
                        'TOUCHCOLOR_EVIDENCE_LIMIT', 'TOUCHCOLOR_VISION_CASE', 'TOUCHCOLOR_TEXT_PHASE', 'TOUCHCOLOR_WATCH_PROFILE'):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'admitted row'):
                    q.admit({**env, key: 'unexpected'})

    def test_old_native_inventory_is_preserved(self):
        with cwd(self.root):
            rows = q.rows()
        self.assertEqual(len(rows), 19)
        self.assertEqual(sum(row['platform'] == 'vision' for row in rows), 11)
        self.assertEqual(sum(row['platform'] == 'watch' for row in rows), 4)

    def test_workflow_is_exact_push_closed_serial_and_unsigned(self):
        text = (ROOT / q.WORKFLOW).read_text()
        self.assertIn('  push:', text)
        self.assertIn('branches: [touchcolor-platform-qualification]', text)
        self.assertIn('paths: [.github/platform-qualification.json]', text)
        self.assertIn('fetch-depth: 64', text)
        self.assertEqual(text.count('runs-on: xcode-27'), 1)
        self.assertNotIn('  admit:', text)
        self.assertNotIn('needs:', text)
        self.assertNotIn('ubuntu-latest', text)
        for trigger in ('  workflow_dispatch:', '  pull_request:', '  schedule:', '  workflow_call:'):
            self.assertNotIn(trigger, text)
        self.assertIn('if: ${{ false }}', text)
        self.assertIn('max-parallel: 1', text)
        self.assertIn('          - platform: unselected', text)
        self.assertEqual(text.count('          - platform:'), 1)
        self.assertNotIn('fromJSON', text)
        self.assertNotIn('bash scripts/test_mac_sandbox.sh', text)
        self.assertNotIn('python3 scripts/test_paired_watch.py', text)
        self.assertNotIn('GITHUB_SHA=', text)
        self.assertNotIn('GITHUB_REF=', text)
        self.assertIn('run: test "$MAC_EVIDENCE_COMPLETE" = true', text)
        for platform in ('vision', 'watch', 'tv'):
            self.assertIn('python3 scripts/test_extra_platforms.py ' + platform, text)

    def test_baked_selector_mismatch_fails_before_native_work(self):
        path = self.root / q.WORKFLOW
        path.write_text(path.read_text().replace('          - platform: tv', '          - platform: mac'))
        self.run_git('add', '-A'); self.run_git('commit', '--amend', '--no-edit', '-q'); self.rebind_control()
        with self.enabled_fixture(), self.assertRaisesRegex(ValueError, 'Baked native selection'):
            q.admit(self.env)

    def test_local_generator_bakes_each_original_row_without_changing_other_steps(self):
        workflow = (ROOT / q.WORKFLOW).read_text()
        before, tail = workflow.split(q.SELECTION_START)
        _, after = tail.split(q.SELECTION_END)
        with cwd(ROOT):
            for lane in q.LANES:
                if lane in ('ios', 'paired'):
                    continue
                config = {**self.config, 'selected_lane': lane}
                rendered = q.render_selection(workflow, config)
                self.assertTrue(rendered.startswith(before + q.SELECTION_START))
                self.assertTrue(rendered.endswith(q.SELECTION_END + after))
                self.assertEqual(rendered.count('          - platform:'), 1)
                self.assertEqual(q.render_selection(rendered, config), rendered)
                row = q.select(lane)
                self.assertIn('minutes: ' + str(row['minutes']), rendered)
                self.assertIn('evidence_bytes: ' + str(row['evidence_bytes']), rendered)
            closed = q.render_selection(workflow, {**self.config, 'READY': False})
            self.assertEqual(closed, workflow)
            for lane in ('ios', 'paired', 'all', 'unselected'):
                with self.assertRaises(ValueError):
                    q.render_selection(workflow, {**self.config, 'selected_lane': lane})

    def test_new_mac_identity_is_exact_push_only_and_full_gate_stays_incomplete(self):
        import retain_mac_evidence as keep
        from test_retain_mac_evidence import Fixture, SOURCE
        identity = {'GITHUB_REPOSITORY': q.REPOSITORY, 'GITHUB_REF': q.REF,
                    'GITHUB_WORKFLOW_REF': q.WORKFLOW_REF, 'GITHUB_EVENT_NAME': 'push'}
        self.assertEqual(keep.workflow_identity(identity)['workflow_file'], q.WORKFLOW)
        with self.assertRaises(ValueError):
            keep.workflow_identity({**identity, 'GITHUB_EVENT_NAME': 'workflow_dispatch'})
        source = {**copy.deepcopy(SOURCE), **keep.workflow_identity(identity)}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITHUB_SHA': ''}):
            root = Path(folder); Fixture(root)
            deferred = ('mac-sandbox-summary.json', 'mac-sandbox-entitlements.json', 'mac-sandbox-post-entitlements.json')
            for name in deferred:
                (root / name).unlink()
            result = keep.retain(root, source)
            self.assertIs(result['complete'], False)
            self.assertEqual(result['missingMandatory'], sorted(deferred))
            self.assertIs(keep.validate_selection(root)['complete'], False)
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                keep.validate_selection(root, require_complete=True)


if __name__ == '__main__':
    unittest.main()
