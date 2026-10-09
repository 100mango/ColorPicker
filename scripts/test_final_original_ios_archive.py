import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('final_archive', Path(__file__).with_name('final_original_ios_archive.py'))
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class FinalOriginalArchiveTests(unittest.TestCase):
    def config(self):
        value = json.loads((gate.CONTROL_ROOT / gate.CONFIG).read_text())
        value['enabled'] = True
        return value

    def env(self):
        return {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': gate.BRANCH,
            'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + gate.WORKFLOW + '@' + gate.BRANCH,
            'GITHUB_JOB': 'archive', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'push',
            'DEVELOPER_DIR': '/Applications/Xcode_27.app/Contents/Developer',
            'GITHUB_SHA': 'c' * 40, 'GITHUB_WORKFLOW_SHA': 'c' * 40, 'GITHUB_RUN_ID': '123'}

    def answers(self):
        return {('control', 'rev-parse', 'HEAD'): 'c' * 40,
            ('control', 'rev-list', '--parents', '-n', '1', 'HEAD'): 'c' * 40 + ' ' + gate.SOURCE,
            ('control', 'rev-parse', gate.SOURCE + '^{tree}'): gate.TREE,
            ('control', 'diff', '--name-status', gate.SOURCE, 'HEAD', '--'): '\n'.join(gate.CONTROL_CHANGES),
            ('control', 'status', '--porcelain', '--untracked-files=all'): '',
            ('product', 'status', '--porcelain', '--untracked-files=all'): '',
            ('product', 'rev-parse', 'HEAD'): gate.SOURCE,
            ('product', 'rev-parse', 'HEAD^{tree}'): gate.TREE}

    def test_closed_template_rejects_before_git_or_native_command(self):
        value = self.config(); value['enabled'] = False
        calls = []
        with self.assertRaisesRegex(ValueError, 'archive-control-closed'):
            gate.admit_sources(value, self.env(), lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_closed_bootstrap_never_imports_product_code_or_launches_git(self):
        from unittest.mock import patch
        value = self.config(); value['enabled'] = False
        with patch.object(gate, 'read_control', return_value=(value, 'a' * 64)), \
                patch.object(gate.subprocess, 'run') as run, \
                patch.object(gate.importlib, 'import_module') as load:
            with self.assertRaisesRegex(ValueError, 'archive-control-closed'):
                gate.checked_api(self.env(), deadline=gate.time.monotonic() + 60)
            run.assert_not_called(); load.assert_not_called()

    def test_exact_current_product_and_control_scope_are_admitted(self):
        answers = self.answers()
        binding = gate.admit_sources(self.config(), self.env(), lambda *args: answers[args])
        self.assertEqual(binding['product_sha'], gate.SOURCE)
        self.assertEqual(binding['product_tree'], gate.TREE)
        self.assertNotEqual(binding['control_sha'], binding['product_sha'])

    def test_old_source_changed_product_merge_parent_or_extra_control_is_rejected(self):
        for key, value in self.answers().items():
            bad = self.answers()
            bad[key] = value + '\nA\tunexpected' if 'diff' in key else 'unexpected'
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.admit_sources(self.config(), self.env(), lambda *args: bad[args])

    def test_foreign_source_or_forged_native_release_qualification_is_rejected(self):
        mutations = [lambda x: x['source'].update(commit='a' * 40),
            lambda x: x['source'].update(version='2.0', build='20001'),
            lambda x: x.update(execution_scope='release'),
            lambda x: x['native_gate'].update(status='accepted'),
            lambda x: x['native_gate'].update(source_commit='a' * 40),
            lambda x: x['native_gate'].update(run_id='123'),
            lambda x: x['native_gate'].update(artifacts={'se3': {}})]
        for mutation in mutations:
            value = self.config(); mutation(value)
            with self.subTest(value=value), self.assertRaises(ValueError): gate.validate_control(value)

    def test_pending_ui_does_not_block_unsigned_diagnostic_or_create_release_approval(self):
        value = self.config()
        self.assertEqual(gate.validate_control(value)['native_gate']['status'], 'pending')
        import ast
        tree = ast.parse(Path(gate.__file__).read_text())
        for key in ('release_qualified', 'native_ui_qualified', 'signing_qualified', 'store_qualified'):
            matches = [v for node in ast.walk(tree) if isinstance(node, ast.Dict)
                       for k, v in zip(node.keys, node.values)
                       if isinstance(k, ast.Constant) and k.value == key]
            self.assertTrue(matches, key)
            self.assertTrue(all(isinstance(v, ast.Constant) and v.value is False for v in matches), key)

    def test_wrong_job_ref_event_attempt_or_workflow_never_reads_source(self):
        for key in self.env():
            env = self.env(); env[key] = 'wrong'; calls = []
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.admit_sources(self.config(), env, lambda *args: calls.append(args))
            self.assertEqual(calls, [])

    def test_duplicate_config_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate-control-key'):
            gate.strict_json('{"enabled":false,"enabled":true}')

    def assert_workflow_bytes(self, raw, enabled):
        closed = '    if: ${{ false }}\n'
        active = "    if: ${{ github.repository == '100mango/ColorPicker' && github.ref == 'refs/heads/ios-original-archive' }}\n"
        selected = active if enabled else closed
        self.assertEqual(raw.count(selected), 1)
        canonical = raw.replace(selected, closed, 1)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), 'c56fc6c8de858353fd721293e33243d0b55c567008ad3d959668650e7d1474c6')

    def test_exact_control_workflow_bytes_reject_unreviewed_changes(self):
        raw = (gate.CONTROL_ROOT / gate.WORKFLOW).read_text()
        value, _ = gate.read_control()
        self.assert_workflow_bytes(raw, value['enabled'])
        for old, new in [('  contents: read', '  contents: write'),
                         ('    timeout-minutes: 20', '    timeout-minutes: 21'),
                         ('  push:', '  pull_request:'),
                         ('  cancel-in-progress: false', '  cancel-in-progress: true'),
                         (gate.SOURCE, 'a' * 40),
                         ('          path: product', '          path: other')]:
            with self.subTest(new=new), self.assertRaises(AssertionError):
                self.assert_workflow_bytes(raw.replace(old, new, 1), value['enabled'])

    def test_fixed_workflow_keeps_original_single_job_and_budget(self):
        raw = (gate.CONTROL_ROOT / gate.WORKFLOW).read_text()
        value, _ = gate.read_control()
        expected_if = ('    if: ${{ false }}\n' if not value['enabled'] else
            "    if: ${{ github.repository == '100mango/ColorPicker' && github.ref == 'refs/heads/ios-original-archive' }}\n")
        self.assertEqual(raw.count(expected_if), 1)
        self.assertEqual(raw.count('    runs-on: xcode-27\n'), 1)
        self.assertEqual(raw.count('    timeout-minutes: 20\n'), 1)
        self.assertEqual(raw.count('        timeout-minutes: 16\n'), 1)
        self.assertEqual(raw.count('          ref: ' + gate.SOURCE + '\n'), 1)
        for exact in ['          path: control\n', '          path: product\n',
                      '          python3 -S control/scripts/test_final_original_ios_archive.py\n',
                      '          python3 -O -S control/scripts/test_final_original_ios_archive.py\n',
                      '          path: product/build/archive-proof/report.json\n']:
            self.assertEqual(raw.count(exact), 1)
        self.assertNotIn('secrets.', raw)
        self.assertNotIn('workflow_run:', raw)
        self.assertNotIn('matrix:', raw)

    def test_existing_actual_package_archive_checks_and_unsigned_command_are_reused(self):
        source = Path(gate.__file__).read_text()
        for token in ['api.ARCHIVE_COMMAND', 'api.verify_archive(', 'api.retain_report(',
                      'api.upload_gate(', 'api.PHASE_END', "'binary_handoff': False",
                      "'signing_qualified': False", "'store_qualified': False",
                      "'scripts/verify_original_design_source.py'"]:
            self.assertIn(token, source)
        self.assertNotIn('pip install', source)
        self.assertNotIn('import yaml', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
