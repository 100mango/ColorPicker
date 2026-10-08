"""Synthetic products/processes only. No simulator, Xcode, or CI execution."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import paired_product_diagnostics as diagnostics


class ProductDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # The runner's TMPDIR may itself be an OS/CI symlink. Canonicalize only
        # this trusted synthetic fixture; production rejection stays unchanged.
        self.root = Path(self.temporary.name).resolve()
        self.products = {}
        for role, identifier in diagnostics.PRODUCT_ROLES.items():
            app = self.root / role / 'TouchColor.app'
            app.mkdir(parents=True)
            info = {'CFBundleIdentifier': identifier, 'CFBundleExecutable': 'TouchColor',
                    'CFBundleVersion': '20001', 'CFBundleSupportedPlatforms': ['WatchSimulator'],
                    'WKApplication': True, 'WKRunsIndependentlyOfCompanionApp': False,
                    'UIDeviceFamily': [4], 'unrelatedPrivateData': 'never-retain-this'}
            (app / 'Info.plist').write_bytes(plistlib.dumps(info))
            (app / 'TouchColor').write_bytes(b'code-' + role.encode())
            (app / 'TouchColor.debug.dylib').write_bytes(b'debug-' + role.encode())
            self.products[role] = app

    def collect(self, **kwargs):
        return diagnostics.collect_product_identities(self.products, [self.root], **kwargs)

    def update_plist(self, role='builtPhone', **fields):
        path = self.products[role] / 'Info.plist'
        info = plistlib.loads(path.read_bytes())
        info.update(fields)
        path.write_bytes(plistlib.dumps(info))

    def test_six_roles_preserve_false_absence_and_exact_hashes(self):
        result = self.collect()
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(set(result['products']), set(diagnostics.PRODUCT_ROLES))
        for role, item in result['products'].items():
            self.assertIs(item['info']['values']['WKRunsIndependentlyOfCompanionApp'], False)
            self.assertIn('WKWatchOnly', item['info']['absent'])
            self.assertEqual(item['executable']['file'], 'TouchColor')
            self.assertEqual(item['debugDylib']['file'], 'TouchColor.debug.dylib')
            self.assertEqual(item['executable']['sha256'],
                             hashlib.sha256(b'code-' + role.encode()).hexdigest())
        encoded = json.dumps(result)
        self.assertNotIn('never-retain-this', encoded)
        self.assertNotIn(str(self.root), encoded)
        # All synthetic builds differ; no equality verdict or defect is inferred.
        self.assertEqual(len({item['executable']['sha256']
                              for item in result['products'].values()}), 6)
        self.assertEqual(result['hashInterpretation'], 'observations_only_no_defect_inference')

    def test_absent_optional_dylib_is_complete(self):
        (self.products['builtPhone'] / 'TouchColor.debug.dylib').unlink()
        result = self.collect()
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['products']['builtPhone']['debugDylib'], {'status': 'absent'})

    def test_unlisted_data_files_and_nested_directories_are_not_read(self):
        app = self.products['builtPhone']
        (app / 'private.sqlite').write_bytes(b'PRIVATE SENTINEL')
        (app / 'Documents').mkdir()
        (app / 'Documents' / 'credentials').write_bytes(b'PRIVATE SENTINEL')
        opened = []
        original = os.open
        def observe(path, *args, **kwargs):
            opened.append(str(path))
            return original(path, *args, **kwargs)
        with patch.object(diagnostics.os, 'open', side_effect=observe):
            result = self.collect()
        self.assertEqual(result['status'], 'observed')
        self.assertNotIn('private.sqlite', opened)
        self.assertNotIn('Documents', opened)
        self.assertNotIn('PRIVATE SENTINEL', json.dumps(result))

    def test_outside_scope_unknown_roles_and_relative_paths_fail_closed(self):
        result = diagnostics.collect_product_identities(
            {'builtPhone': self.products['builtPhone'], 'other': '/etc'},
            [self.products['installedPhone']])
        self.assertTrue(result['unexpectedRolesIgnored'])
        self.assertEqual(result['products']['builtPhone']['reason'], 'outside_source_roots')
        self.products['builtPhone'] = Path('TouchColor.app')
        self.assertEqual(self.collect()['products']['builtPhone']['reason'], 'unsafe_path')

    def test_symlinked_app_ancestor_and_regular_file_are_rejected(self):
        app = self.products['builtPhone']
        executable = app / 'TouchColor'
        executable.unlink()
        executable.symlink_to('/etc/passwd')
        self.assertEqual(self.collect()['products']['builtPhone']['status'], 'incomplete')
        link = self.root / 'alias'
        link.symlink_to(app.parent, target_is_directory=True)
        self.products['builtPhone'] = link / 'TouchColor.app'
        self.assertEqual(self.collect()['products']['builtPhone']['status'], 'incomplete')

    def test_non_regular_file_and_hardlink_are_rejected(self):
        executable = self.products['builtPhone'] / 'TouchColor'
        executable.unlink()
        os.mkfifo(executable)
        self.assertEqual(self.collect()['products']['builtPhone']['reason'], 'not_regular_file')
        executable.unlink()
        os.link(self.products['installedPhone'] / 'TouchColor', executable)
        self.assertEqual(self.collect()['products']['builtPhone']['reason'], 'hardlinked_file')

    def test_foreign_owner_and_root_are_rejected(self):
        self.assertEqual(self.collect(owner_uid=os.getuid() + 1)['products']['builtPhone']['reason'],
                         'foreign_owner')
        self.assertEqual(diagnostics.collect_product_identities(self.products, ['/'])['status'],
                         'incomplete')

    def test_identity_or_executable_mismatch_never_hashes_arbitrary_file(self):
        self.update_plist(CFBundleIdentifier='wrong')
        result = self.collect()['products']['builtPhone']
        self.assertEqual(result['reason'], 'unexpected_bundle_identifier')
        self.assertNotIn('executable', result)
        self.update_plist(CFBundleIdentifier=diagnostics.PHONE_ID, CFBundleExecutable='../secret')
        result = self.collect()['products']['builtPhone']
        self.assertEqual(result['reason'], 'unexpected_executable')
        self.assertNotIn('executable', result)

    def test_bad_plist_and_invalid_whitelisted_fields_are_incomplete(self):
        self.update_plist(WKApplication={'unexpected': 'never-retain-this'})
        result = self.collect()['products']['builtPhone']
        self.assertEqual(result['info']['invalid'], ['WKApplication'])
        self.assertNotIn('WKApplication', result['info']['values'])
        self.assertEqual(result['status'], 'incomplete')
        (self.products['builtPhone'] / 'Info.plist').write_bytes(b'<?xml version="1.0"?><plist>')
        self.assertEqual(self.collect()['products']['builtPhone']['status'], 'incomplete')

    def test_size_entry_and_total_hash_limits(self):
        for limits, reason in [
                (replace(diagnostics.Limits(), plist_bytes=10), 'file_size_limit'),
                (replace(diagnostics.Limits(), binary_bytes=2), 'file_size_limit'),
                (replace(diagnostics.Limits(), app_entries=2), 'app_entry_limit'),
                (replace(diagnostics.Limits(), total_hash_bytes=2), 'total_hash_limit')]:
            with self.subTest(reason=reason):
                self.assertEqual(self.collect(limits=limits)['products']['builtPhone']['reason'], reason)
        self.assertEqual(self.collect(limits=replace(diagnostics.Limits(), binary_bytes=10**9))['reason'],
                         'invalid_arguments')

    def test_file_changed_during_read_has_no_digest(self):
        original = os.read
        target = self.products['builtPhone'] / 'TouchColor'
        def mutate(descriptor, size):
            data = original(descriptor, size)
            if data == b'code-builtPhone':
                target.write_bytes(b'changed')
            return data
        with patch.object(diagnostics.os, 'read', side_effect=mutate):
            result = self.collect()['products']['builtPhone']
        self.assertEqual(result['reason'], 'file_changed_during_read')
        self.assertNotIn('executable', result)

    def test_filesystem_deadline_prevents_more_reads_and_marks_all_roles_incomplete(self):
        with patch.object(diagnostics.time, 'monotonic', side_effect=[0] + [11] * 20), \
                patch.object(diagnostics.os, 'open', side_effect=AssertionError('read after deadline')):
            result = self.collect()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['hashBytesRead'], 0)
        self.assertTrue(all(item['reason'] == 'filesystem_time_limit'
                            for item in result['products'].values()))

    def test_filesystem_deadline_is_checked_between_hash_chunks(self):
        original = os.read
        clock = [0]
        def read_then_expire(descriptor, size):
            data = original(descriptor, size)
            if data == b'code-builtPhone':
                clock[0] = 11
            return data
        with patch.object(diagnostics.os, 'read', side_effect=read_then_expire), \
                patch.object(diagnostics.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.collect()
        self.assertEqual(result['products']['builtPhone']['reason'], 'filesystem_time_limit')
        self.assertNotIn('executable', result['products']['builtPhone'])
        self.assertEqual(result['products']['embeddedWatch']['reason'], 'filesystem_time_limit')


class RegistrationTests(unittest.TestCase):
    device = '12345678-1234-1234-1234-123456789ABC'
    help = b'Usage: simctl [options] <subcommand>\nSubcommands:\n    appinfo             Get app information.\n'
    usage = b"Get an installed app's information.\nUsage: simctl appinfo <device> <app bundle identifier>\n"

    def executor(self, bodies, **overrides):
        calls = []
        def execute(command, **kwargs):
            calls.append((command, kwargs))
            body = bodies[len(calls) - 1]
            return diagnostics.CommandResult(0, body, True, **overrides)
        return execute, calls

    def collect(self, execute=None, **kwargs):
        return diagnostics.collect_registration_receipt(self.device, diagnostics.PHONE_ID, execute, **kwargs)

    def test_without_executor_no_capability_is_claimed(self):
        self.assertEqual(self.collect()['reason'], 'runtime_capability_not_verified')
        self.assertFalse(self.collect()['capability']['usageVerified'])

    def test_runtime_help_precedes_exact_scoped_command_and_only_filtered_output_survives(self):
        for body in (plistlib.dumps({'CFBundleIdentifier': diagnostics.PHONE_ID,
                                    'ApplicationType': 'User', 'DataContainer': 'SECRET'}),
                     json.dumps({'CFBundleIdentifier': diagnostics.PHONE_ID,
                                 'EnvironmentVariables': {'SECRET': 'SECRET'}}).encode()):
            execute, calls = self.executor([self.help, self.usage, body])
            result = self.collect(execute)
            self.assertEqual(result['status'], 'observed')
            self.assertEqual([item[0] for item in calls], [
                ['xcrun', 'simctl', 'help'], ['xcrun', 'simctl', 'help', 'appinfo'],
                ['xcrun', 'simctl', 'appinfo', self.device, diagnostics.PHONE_ID]])
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertNotIn('Get app information.', json.dumps(result))
            self.assertEqual(result['capability']['verifiedUsage'],
                             'Usage: simctl appinfo <device> <app bundle identifier>')
            self.assertEqual(result['capability']['topLevelHelpSHA256'],
                             hashlib.sha256(self.help).hexdigest())
            self.assertEqual(result['capability']['appinfoHelpSHA256'],
                             hashlib.sha256(self.usage).hexdigest())
            self.assertTrue(all(item[1] == {'timeout': 10.0, 'max_output_bytes': 65_536}
                                for item in calls))

    def test_explicit_ten_second_limit_is_valid_and_larger_limits_execute_nothing(self):
        execute, calls = self.executor([
            self.help, self.usage,
            json.dumps({'CFBundleIdentifier': diagnostics.PHONE_ID}).encode()])
        result = self.collect(execute, limits=diagnostics.Limits(command_timeout=10))
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(item[1]['timeout'] == 10 for item in calls))
        for timeout in (10.001, 11, float('inf')):
            execute, calls = self.executor([])
            result = self.collect(execute, limits=diagnostics.Limits(command_timeout=timeout))
            self.assertEqual(result['reason'], 'invalid_owned_target_or_limits')
            self.assertEqual(calls, [])

    def test_no_guessed_flags_grammar_or_inventory_fallback(self):
        for help_text, usage in [(b'Use appinfo for information', self.usage),
                                 (b'    listapps     Print apps\n', self.usage),
                                 (self.help, b'Usage: simctl appinfo [--json] <device> <bundle-id>\n'),
                                 (self.help, self.usage + self.usage)]:
            execute, calls = self.executor([help_text, usage])
            result = self.collect(execute)
            self.assertEqual(result['status'], 'unavailable')
            self.assertLessEqual(len(calls), 2)
            self.assertTrue(all('listapps' not in item[0] for item in calls))

    def test_missing_wrong_or_unsupported_appinfo_identity_is_unavailable(self):
        for body in (b'{ CFBundleIdentifier = com.mango.touchColor; }',
                     b'{"CFBundleIdentifier":"other", "private":"SECRET"}', b'[]',
                     b'WARNING SECRET\n{"CFBundleIdentifier":"com.mango.touchColor"}',
                     b'{"CFBundleIdentifier":"com.mango.touchColor"}\nWARNING SECRET'):
            execute, calls = self.executor([self.help, self.usage, body])
            result = self.collect(execute)
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('SECRET', json.dumps(result))

    def test_help_on_stderr_is_verified_without_retaining_raw_output(self):
        calls = []
        bodies = [self.help, self.usage, json.dumps({'CFBundleIdentifier': diagnostics.PHONE_ID}).encode()]
        def synthetic_executor(command, timeout, max_output_bytes):
            index = len(calls)
            calls.append(command)
            script = 'import os; os.write(%d, %r)' % (2 if index < 2 else 1, bodies[index])
            return diagnostics.run_inspection([sys.executable, '-c', script], timeout, max_output_bytes)
        result = self.collect(synthetic_executor)
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(len(calls), 3)
        self.assertNotIn('Get app information.', json.dumps(result))
        self.assertEqual(result['capability']['appinfoHelpSHA256'], hashlib.sha256(self.usage).hexdigest())

    def test_unverified_target_executes_nothing(self):
        execute, calls = self.executor([])
        result = diagnostics.collect_registration_receipt('booted', diagnostics.PHONE_ID, execute)
        self.assertEqual(result['reason'], 'invalid_owned_target_or_limits')
        self.assertEqual(calls, [])

    def test_size_truncation_timeout_cleanup_and_exception_stop_discovery(self):
        for command_result, reason in [
                (diagnostics.CommandResult(0, b'x' * 65_537, True), 'help_output_limit'),
                (diagnostics.CommandResult(0, self.help, True, True), 'help_output_limit'),
                (diagnostics.CommandResult(0, self.help, False), 'help_cleanup_unconfirmed'),
                (diagnostics.CommandResult(0, self.help, True, False, True), 'help_timeout'),
                (diagnostics.CommandResult(1, b'SECRET', True), 'help_failed')]:
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                return command_result
            result = self.collect(execute)
            self.assertEqual(result['reason'], reason)
            self.assertEqual(len(calls), 1)
            self.assertNotIn('SECRET', json.dumps(result))
        def fails(*args, **kwargs):
            raise OSError('SECRET')
        self.assertEqual(self.collect(fails)['reason'], 'help_executor_failed')
        def unclean_failure(*args, **kwargs):
            error = OSError('SECRET')
            error.cleanup_confirmed = False
            raise error
        self.assertTrue(self.collect(unclean_failure)['cleanupUnconfirmed'])


class BoundedInspectionTests(unittest.TestCase):
    def run_python(self, script, timeout=2, cap=128):
        return diagnostics.run_inspection([sys.executable, '-c', script], timeout, cap)

    def test_success_combines_both_streams_in_one_bounded_pipe(self):
        result = self.run_python("import os; os.write(1,b'receipt\\n'); os.write(2,b'warning\\n')")
        self.assertEqual(result.stdout, b'receipt\nwarning\n')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.cleanup_confirmed)
        self.assertFalse(result.output_truncated)
        self.assertFalse(result.timed_out)

    def test_output_cap_applies_to_both_streams_together(self):
        result = self.run_python("import os; os.write(1,b'123456'); os.write(2,b'abcdef')", cap=10)
        self.assertEqual(result.stdout, b'123456abcd')
        self.assertTrue(result.output_truncated)
        self.assertTrue(result.cleanup_confirmed)

    def test_timeout_and_output_overflow_clean_owned_process(self):
        result = self.run_python('import time; time.sleep(30)', timeout=0.05)
        self.assertTrue(result.timed_out)
        self.assertTrue(result.cleanup_confirmed)
        result = self.run_python("import os;\nwhile True: os.write(1,b'x'*4096)", cap=13)
        self.assertEqual(result.stdout, b'x' * 13)
        self.assertTrue(result.output_truncated)
        self.assertTrue(result.cleanup_confirmed)

    def test_no_unbounded_communicate(self):
        with patch.object(subprocess.Popen, 'communicate', side_effect=AssertionError('unbounded')):
            self.assertEqual(self.run_python("print('ok')").stdout, b'ok\n')

    def test_exception_preserves_cleanup_failure_evidence(self):
        original = diagnostics.stop_group
        def unconfirmed(process):
            original(process, grace=0.1)
            return False
        with patch.object(diagnostics.os, 'set_blocking', side_effect=OSError('synthetic pipe failure')), \
                patch.object(diagnostics, 'stop_group', side_effect=unconfirmed):
            with self.assertRaises(OSError) as caught:
                self.run_python('import time; time.sleep(30)')
        self.assertFalse(caught.exception.cleanup_confirmed)

    def test_unconfirmed_descendant_cleanup_is_not_reported_as_success(self):
        # The process has already exited; a separate group-liveness result still
        # vetoes success. Exercise the real orphan-cleanup implementation below.
        original = diagnostics.stop_group
        def unconfirmed(process):
            original(process, grace=0.1)
            return False
        with patch.object(diagnostics, 'stop_group', side_effect=unconfirmed):
            result = self.run_python("print('parent exited')")
        self.assertFalse(result.cleanup_confirmed)

    def test_parent_exit_does_not_skip_orphan_cleanup(self):
        original = diagnostics.stop_group
        seen = []
        def bounded_cleanup(process):
            seen.append(process.pid)
            return original(process, grace=0.1)
        script = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])"
        with patch.object(diagnostics, 'stop_group', side_effect=bounded_cleanup):
            result = self.run_python(script, timeout=0.1)
        self.assertTrue(result.timed_out)
        self.assertEqual(len(seen), 1)
        # A zombie descendant can outlive its killed process on Linux. Its
        # existence must remain unconfirmed rather than becoming a false pass.
        from bounded_process import group_exists
        self.assertEqual(result.cleanup_confirmed, not group_exists(seen[0]))


if __name__ == '__main__':
    unittest.main()
