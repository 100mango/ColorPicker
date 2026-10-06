"""Portable completion evidence identity and budget adversaries; no app evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import uikit_completion as completion
import uikit_managed_device as managed


class CompletionEvidenceTests(unittest.TestCase):
    SCRIPT = Path(__file__).with_name('export_audit_failures.py').resolve()
    GROUPS = {
        'iphone-compact': ('iPhoneCompact', 2),
        'iphone-large': ('iPhoneLarge', 2),
        'ipad-mini-palette': ('iPadMini', 1),
        'ipad-mini-canvas': ('iPadMini', 1),
        'ipad-large-palette': ('iPadLarge', 2),
        'ipad-large-canvas': ('iPadLarge', 2),
    }

    def setUp(self):
        previous = Path.cwd()
        folder = tempfile.TemporaryDirectory(prefix='Completion evidence ')
        os.chdir(folder.name)
        self.addCleanup(folder.cleanup)
        self.addCleanup(os.chdir, previous)
        environment = patch.dict(os.environ, {
            'GITHUB_REPOSITORY': managed.REPOSITORY, 'GITHUB_REF': completion.REF,
            'GITHUB_WORKFLOW_REF': completion.WORKFLOW, 'GITHUB_ACTIONS': 'true',
            'GITHUB_JOB': 'completion', 'RUNNER_OS': 'macOS',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': 'a' * 40,
            'GITHUB_WORKFLOW_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123',
            'GITHUB_RUN_ATTEMPT': '1', 'TC_TEST_FAMILY': 'iPadMini',
            'TC_COMPLETION_GROUP': 'ipad-mini-palette',
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def load(self):
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return runpy.run_path(str(self.SCRIPT))

    def bundle(self, suite='TouchColorUITests'):
        if not hasattr(self, 'binding_reader'):
            binding = patch.object(managed, 'read_binding',
                                   side_effect=lambda family: {'context': managed.require_job(family)})
            self.binding_reader = binding.start()
            self.addCleanup(binding.stop)
        result = Path('build', os.environ['TC_TEST_FAMILY'] + '-' + suite + '.xcresult')
        result.mkdir(parents=True, exist_ok=True)
        (result / 'Info.plist').write_text('synthetic test fixture only')
        return result

    def exporter(self, names, *, size=20, failures=False, action=None):
        def run(command, **kwargs):
            self.assertEqual(command[:4], ['xcrun', 'xcresulttool', 'export', 'attachments'])
            destination = Path(command[command.index('--output-path') + 1])
            attachments = []
            for index, name in enumerate(names):
                filename = str(index) + '.jpg'
                (destination / filename).write_bytes(b'\xff\xd8' + b'x' * (size - 4) + b'\xff\xd9')
                method = {'photo': 'SampledPhoto', 'saved': 'SavedPalette',
                          'live': 'LiveCameraUnavailable'}.get(name.rsplit('-', 1)[-1], 'Other')
                attachments.append({'exportedFileName': filename, 'suggestedHumanReadableName': name,
                    'testIdentifier': 'TouchColorAccessibilityUITests/testAccessibility' + method,
                    'isAssociatedWithFailure': failures})
            (destination / 'manifest.json').write_text(json.dumps(attachments))
            if action is not None:
                action()
            return subprocess.CompletedProcess(command, 0, '', '')
        return run

    def test_six_groups_share_exactly_ten_slots_and_reserve_six_hosts_of_output(self):
        for identity, (family, allocation) in self.GROUPS.items():
            with self.subTest(group=identity), patch.dict(os.environ, {
                    'TC_COMPLETION_GROUP': identity, 'TC_TEST_FAMILY': family}):
                module = self.load()
                budget = json.loads(self.output.getvalue().splitlines()[0].split(':', 1)[1])
                self.assertEqual(module['limit'], allocation)
                self.assertEqual(module['COMPLETION_EVIDENCE_GROUPS'], self.GROUPS)
                self.assertEqual(budget['allocations'], {key: value[1] for key, value in self.GROUPS.items()})
                self.assertEqual(sum(budget['allocations'].values()), 10)
                self.assertEqual(budget['maximum_image_bytes'], 500 * 1024)
                self.assertEqual(budget['completion_group'], identity)
                self.assertEqual(budget['diagnostic_groups'], 6)
                image_bytes = 10 * (4 * ((500 * 1024 + 2) // 3) + 16 * 1024)
                per_host = 2 * (4 * 1024 + 512) + 24 * 1024 + 32 * 1024 + 4 * 1024
                self.assertEqual(module['RESERVED_LOG_BYTES'], image_bytes + 6 * per_host + 16 * 36 * 1024)
                self.assertEqual(module['RESERVED_LOG_BYTES'], 8_004_280)
                self.assertEqual(module['COMPLETION_SUITE_INVOCATIONS'], 16)
                self.assertEqual(sum(bool(group[suite]) for group in completion.GROUPS.values()
                                     for suite in ('bootstrap', 'functional', 'audits')), 16)
                self.assertEqual(budget['maximum_selected_result_bytes'], 36 * 1024)
                self.assertLessEqual(module['RESERVED_LOG_BYTES'], 20_000_000)
                self.assertEqual(module['MAX_RUN_LOG_BYTES'], 20_000_000)
                self.assertEqual(module['ORIGINAL_RESERVED_LOG_BYTES'], 7_256_760)
                self.assertLessEqual(len(self.output.getvalue().encode()) + 128 * len(self.output.getvalue().splitlines()),
                                     budget['maximum_group_summary_bytes'])

    def test_wrong_group_family_workflow_or_source_fails_before_export(self):
        bad_values = [('TC_COMPLETION_GROUP', 'ipad-mini'), ('TC_COMPLETION_GROUP', ''),
                      ('TC_TEST_FAMILY', 'iPadLarge'), ('TC_TEST_FAMILY', 'Unknown'),
                      ('GITHUB_REF', managed.REF), ('GITHUB_WORKFLOW_REF', managed.WORKFLOW),
                      ('GITHUB_JOB', 'compatibility'), ('GITHUB_SHA', 'b' * 40),
                      ('GITHUB_WORKFLOW_SHA', 'b' * 40), ('GITHUB_SHA', 'not-a-sha')]
        for key, value in bad_values:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}), \
                    patch('subprocess.run') as run:
                with self.assertRaises(ValueError):
                    self.load()
                run.assert_not_called()
                self.assertNotIn('EVIDENCE_BUDGET:', self.output.getvalue())
        del os.environ['TC_COMPLETION_GROUP']
        with self.assertRaises(ValueError):
            self.load()
        with patch.dict(os.environ, {'GITHUB_REF': managed.REF}), self.assertRaises(ValueError):
            self.load()

    def test_job_context_must_match_selected_group_family_and_source(self):
        context = managed.require_job('iPadMini')
        for key, value in [('completion_group', 'ipad-mini-canvas'), ('family', 'iPadLarge'),
                           ('sha', 'b' * 40), ('sha', '')]:
            with self.subTest(key=key, value=value), \
                    patch.object(managed, 'require_job', return_value={**context, key: value}), \
                    patch('subprocess.run') as run:
                with self.assertRaises(ValueError):
                    self.load()
                run.assert_not_called()

    def test_route_cannot_inflate_or_replace_closed_image_allocation(self):
        original = completion.GROUPS['ipad-mini-palette']
        for change in ({'images': 2}, {'images': True}, {'images': -1},
                       {'id': 'ipad-mini-canvas'}, {'id': 'unknown'}, {'family': 'iPadLarge'}):
            with self.subTest(change=change), patch.object(completion, 'completion_group',
                    return_value={**original, **change}):
                with self.assertRaises(ValueError):
                    self.load()

    def test_original_path_keeps_four_host_budget_and_does_not_require_completion_job(self):
        with patch.dict(os.environ, {'TC_TEST_FAMILY': 'iPadLarge'}, clear=True), \
                patch.object(managed, 'require_job', side_effect=AssertionError('Original route changed')):
            module = self.load()
        budget = json.loads(self.output.getvalue().splitlines()[0].split(':', 1)[1])
        self.assertEqual(module['limit'], 4)
        self.assertEqual(module['RESERVED_LOG_BYTES'], 7_256_760)
        self.assertEqual(budget['allocations'], {'iPadMini': 2, 'iPadLarge': 4, 'iPhoneCompact': 2, 'iPhoneLarge': 2})
        self.assertNotIn('completion_group', budget)

    def test_existing_result_rejects_stale_group_or_source_binding_before_export(self):
        stored = managed.require_job('iPadMini')
        self.bundle()
        os.environ['TC_COMPLETION_GROUP'] = 'ipad-mini-canvas'
        current = managed.require_job('iPadMini')
        for context in (stored, {**current, 'sha': 'b' * 40, 'workflow_sha': 'b' * 40}):
            with self.subTest(context=context), patch.object(managed, 'read_binding',
                    return_value={'context': context}) as binding, patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'result ownership differs'):
                    self.load()
                binding.assert_called_once_with('iPadMini')
                run.assert_not_called()
                self.assertNotIn('SCREENSHOT_META:', self.output.getvalue())
        with patch.object(managed, 'read_binding', side_effect=ValueError('Foreign source/workflow/run/attempt/family binding')), \
                patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'Foreign source'):
                self.load()
            run.assert_not_called()

    def test_no_result_after_failed_configuration_does_not_require_device_binding(self):
        with patch.object(managed, 'read_binding', side_effect=AssertionError('No result exists')) as binding, \
                patch('subprocess.run') as run:
            self.load()
        binding.assert_not_called()
        run.assert_not_called()
        self.assertIn('"count": 0', self.output.getvalue())

    def test_each_completion_group_stops_at_its_image_allocation(self):
        for identity, (family, allocation) in self.GROUPS.items():
            with self.subTest(group=identity), patch.dict(os.environ, {
                    'TC_COMPLETION_GROUP': identity, 'TC_TEST_FAMILY': family}):
                result = self.bundle()
                prefix = 'touchcolor-ipad-functional-failure-' if family.startswith('iPad') else 'touchcolor-phone-functional-failure-'
                with patch('subprocess.run', side_effect=self.exporter([prefix + '1', prefix + '2'])) as run:
                    self.load()
                metadata = [json.loads(line.split(':', 1)[1]) for line in self.output.getvalue().splitlines()
                            if line.startswith('SCREENSHOT_META:')]
                self.assertEqual(len(metadata), allocation)
                self.assertEqual([item['name'] for item in metadata], [family + '-' + prefix + str(i + 1) for i in range(allocation)])
                self.assertTrue(all(item['completion_group'] == identity and item['tested_commit'] == 'a' * 40 for item in metadata))
                self.assertEqual(run.call_args.args[0][5], str(result))

    def test_group_or_source_change_during_export_emits_no_image(self):
        self.bundle()
        for change in ({'TC_COMPLETION_GROUP': 'ipad-mini-canvas'},
                       {'GITHUB_SHA': 'b' * 40, 'GITHUB_WORKFLOW_SHA': 'b' * 40}):
            with self.subTest(change=change), patch.dict(os.environ, dict(os.environ)):
                with patch('subprocess.run', side_effect=self.exporter(
                        ['touchcolor-ipad-functional-failure-1'], action=lambda: os.environ.update(change))):
                    with self.assertRaisesRegex(ValueError, 'changed during export'):
                        self.load()
                self.assertNotIn('SCREENSHOT_META:', self.output.getvalue())

    def test_completion_source_image_keeps_the_existing_500_kib_boundary(self):
        self.bundle()
        for size in (500 * 1024, 500 * 1024 + 1):
            with self.subTest(size=size), patch('subprocess.run', side_effect=self.exporter(
                    ['touchcolor-ipad-functional-failure-1'], size=size)):
                if size > 500 * 1024:
                    with self.assertRaisesRegex(ValueError, 'image size cap'):
                        self.load()
                    self.assertNotIn('SCREENSHOT_META:', self.output.getvalue())
                else:
                    module = self.load()
                    chunks = [line.split(':', 1)[1] for line in self.output.getvalue().splitlines()
                              if line.startswith('SCREENSHOT_CHUNK:')]
                    self.assertEqual(sum(map(len, chunks)), 4 * ((size + 2) // 3))
                    self.assertLessEqual(len(self.output.getvalue().encode()), module['IMAGE_SLOT_LOG_BYTES'])

    def test_completion_keeps_audit_priority_and_required_failure_frames(self):
        os.environ.update(TC_COMPLETION_GROUP='ipad-large-canvas', TC_TEST_FAMILY='iPadLarge')
        self.bundle('AccessibilityAudits')
        self.bundle()
        names = ['touchcolor-audit-failure-policy-local-body', 'touchcolor-audit-failure-photo',
                 'touchcolor-audit-failure-saved', 'touchcolor-audit-failure-live',
                 'touchcolor-ipad-functional-failure-1']
        with patch('subprocess.run', side_effect=self.exporter(names, failures=True)) as run:
            with self.assertRaisesRegex(ValueError, 'Requested audit-state pixels were omitted'):
                self.load()
        metadata = [json.loads(line.split(':', 1)[1]) for line in self.output.getvalue().splitlines()
                    if line.startswith('SCREENSHOT_META:')]
        self.assertEqual([item['name'] for item in metadata],
                         ['iPadLarge-' + name for name in names[:2]])
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('EVIDENCE_IMAGES:', self.output.getvalue())

    def test_completion_issue_tags_remain_inside_the_description_byte_budget(self):
        os.environ['TC_COMPLETION_GROUP'] = 'ipad-mini-canvas'
        self.bundle('AccessibilityAudits')
        def export(command, **kwargs):
            destination = Path(command[command.index('--output-path') + 1])
            attachments = []
            for index in range(12):
                filename = str(index) + '.txt'
                (destination / filename).write_text('x' * 9000)
                attachments.append({'exportedFileName': filename,
                    'suggestedHumanReadableName': 'Complete Issue Description.txt',
                    'testIdentifier': 'TouchColorAccessibilityUITests/testAccessibilityNativePolicyBodyAndActions',
                    'isAssociatedWithFailure': True})
            (destination / 'manifest.json').write_text(json.dumps(attachments))
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch('subprocess.run', side_effect=export):
            self.load()
        lines = [line for line in self.output.getvalue().splitlines()
                 if line.startswith('AUDIT_ISSUE_DESCRIPTION')]
        self.assertLessEqual(sum(len(line.encode()) + 1 + 128 for line in lines), 24 * 1024)
        descriptions = [json.loads(line.split(':', 1)[1]) for line in lines
                        if line.startswith('AUDIT_ISSUE_DESCRIPTION:')]
        self.assertGreater(len(descriptions), 0)
        self.assertTrue(all(item['completion_group'] == 'ipad-mini-canvas' and item['tested_commit'] == 'a' * 40
                            for item in descriptions))


if __name__ == '__main__': unittest.main()
