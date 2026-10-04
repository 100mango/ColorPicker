import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import os
import sys
from unittest.mock import patch
import uikit_runtime_diagnostics as diagnostics

from uikit_runtime_diagnostics import collect, framed_record, owned_crashes, service_rows, validate_identity


class UIKitRuntimeDiagnosticsTests(unittest.TestCase):
    identity = {'family': 'iPadMini', 'udid': 'D2B249EB-2AC1-445A-BE5C-E80D6FBCCDF5',
                'runtime': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'started': 1.0}

    def root(self, home, identity=None):
        return Path(home) / 'Library/Developer/CoreSimulator/Devices' / (identity or self.identity)['udid'] / 'data/Library/Logs/CrashReporter'

    def write_report(self, root, name='DocumentManagerService-fixture.ips'):
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        path.write_text(json.dumps({'procName': 'DocumentManagerService', 'pid': 123,
            'captureTime': '2026-10-04T04:00:00Z', 'parentProc': '/private/personal/path',
            'exception': {'type': 'EXC_CRASH', 'signal': 'SIGABRT', 'codes': 'private details'},
            'termination': {'namespace': 'SIGNAL', 'code': 6, 'indicator': '/private/personal/path'},
            'threads': [{'secret': 'not emitted'}]}))
        return path

    def test_owned_identity_rejects_wrong_family_runtime_path_and_start(self):
        self.assertEqual(validate_identity(dict(self.identity), 'iPadMini'), self.identity)
        for key, value in [('family', 'other'), ('udid', '../other-device'), ('runtime', 'iOS-26-0'), ('started', True), ('started', float('nan'))]:
            invalid = dict(self.identity, **{key: value})
            with self.assertRaises((ValueError, AttributeError)):
                validate_identity(invalid, 'iPadMini')

    def test_only_named_apple_and_app_service_rows_are_emitted(self):
        rows = service_rows('PID Status Label\n12 0 com.apple.DocumentManager.fixture\n13 0 UIKitApplication:com.mango.touchColor[fixture]\n- 0 com.apple.fileproviderd\n14 0 com.apple.Notes\n15 0 com.example.com.apple.DocumentManager.secret\n')
        self.assertEqual([row['service'] for row in rows], ['com.apple.DocumentManager.fixture', 'com.mango.touchColor', 'com.apple.fileproviderd'])
        self.assertEqual(len(service_rows('1 0 com.apple.fileproviderd\n' * 100)), 48)

    def test_crash_selection_uses_only_owned_simulator_and_safe_fields(self):
        with tempfile.TemporaryDirectory() as home:
            root = self.root(home)
            self.write_report(root)
            self.write_report(Path(home) / 'Library/Logs/DiagnosticReports')
            self.write_report(self.root(home, dict(self.identity, udid='AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA')))
            self.write_report(root, 'UnrelatedApp-fixture.ips')
            result = owned_crashes(home, self.identity)
            self.assertEqual(len(result['reports']), 1)
            self.assertEqual(result['reports'][0]['exception'], {'type': 'EXC_CRASH', 'signal': 'SIGABRT'})
            encoded = json.dumps(result)
            self.assertNotIn('/private', encoded)
            self.assertNotIn('threads', encoded)
            self.assertNotIn('private details', encoded)

    def test_symlinked_owned_root_and_old_reports_are_not_read(self):
        with tempfile.TemporaryDirectory() as home:
            root = self.root(home)
            self.write_report(root)
            self.assertEqual(owned_crashes(home, dict(self.identity, started=time.time() + 1))['reports'], [])
            alias = root.with_name('ExternalReports'); alias.mkdir()
            self.write_report(alias)
            (root / 'DocumentPicker-link.ips').symlink_to(alias / 'DocumentManagerService-fixture.ips')
            self.assertEqual(len(owned_crashes(home, self.identity)['reports']), 1)
            for child in root.iterdir(): child.unlink()
            root.rmdir(); root.symlink_to(alias, target_is_directory=True)
            self.assertFalse(owned_crashes(home, self.identity)['owned_crash_root_present'])

    def test_command_is_bound_to_owned_simulator_and_error_text_is_not_emitted(self):
        calls = []
        def runner(command, **options):
            calls.append((command, options))
            return subprocess.CompletedProcess(command, 1, 'private output', '/personal/private/path')
        with tempfile.TemporaryDirectory() as home:
            result = collect(self.identity, home, runner)
        self.assertEqual(calls[0][0], ['xcrun', 'simctl', 'spawn', self.identity['udid'], 'launchctl', 'list'])
        self.assertEqual(calls[0][1]['timeout'], 3)
        self.assertEqual(result['service_query_exit'], 1)
        self.assertEqual(result['services'], [])
        self.assertNotIn('private', framed_record(result))

    def test_output_limit_includes_framing_and_omits_oversized_metadata(self):
        value = {'family': 'iPadMini', 'deviceId': self.identity['udid'], 'diagnostic': '界' * 100000}
        line = framed_record(value)
        self.assertLessEqual(len(line.encode('utf-8')) + 128, 32768)
        self.assertIn('metadata exceeded', line)
        self.assertNotIn('界', line)

    def test_host_client_cleanup_does_not_claim_simulator_exit(self):
        def timeout(command, **options):
            error = subprocess.TimeoutExpired(command, options['timeout'])
            error.cleanup_confirmed = True
            raise error
        with tempfile.TemporaryDirectory() as home:
            value = collect(self.identity, home, timeout)
        self.assertFalse(value['simulator_commands_completed'])
        self.assertTrue(value['host_client_cleanup_confirmed'])

    def test_pending_barrier_survives_unknown_exit_and_blocks_another_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd(); os.chdir(directory)
            try:
                Path('build').mkdir()
                Path('build/iPadMini-simulator.json').write_text(json.dumps(self.identity))
                marker = Path('build/iPadMini-runtime-command-uncertain')
                value = dict(family='iPadMini', deviceId=self.identity['udid'], simulator_commands_completed=False)
                with patch.object(sys, 'argv', ['diagnostic', 'iPadMini']), patch.object(diagnostics, 'collect', return_value=value), patch('builtins.print'):
                    with self.assertRaises(SystemExit): diagnostics.main()
                self.assertTrue(marker.is_file())
                original = marker.read_bytes()
                value['simulator_commands_completed'] = True
                with patch.object(sys, 'argv', ['diagnostic', 'iPadMini']), patch.object(diagnostics, 'collect', return_value=value) as mocked, patch('builtins.print'):
                    with self.assertRaises(SystemExit): diagnostics.main()
                    mocked.assert_not_called()
                self.assertEqual(marker.read_bytes(), original)
            finally:
                os.chdir(previous)

    def test_naturally_completed_first_inventory_clears_only_its_own_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd(); os.chdir(directory)
            try:
                Path('build').mkdir()
                Path('build/iPadMini-simulator.json').write_text(json.dumps(self.identity))
                marker = Path('build/iPadMini-runtime-command-uncertain')
                value = dict(family='iPadMini', deviceId=self.identity['udid'], simulator_commands_completed=True)
                with patch.object(sys, 'argv', ['diagnostic', 'iPadMini']), patch.object(diagnostics, 'collect', return_value=value), patch.dict(os.environ, {'GITHUB_OUTPUT': str(Path(directory)/'output')}), patch('builtins.print'):
                    diagnostics.main()
                self.assertFalse(marker.exists())
                self.assertEqual(Path('output').read_text(), 'simulator_safe=true\n')
            finally:
                os.chdir(previous)

    def test_simulator_driver_refuses_shutdown_before_any_command_when_exit_unknown(self):
        script = Path(__file__).with_name('test_simulators.sh').resolve()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'build').mkdir(); (root/'build/iPadMini-runtime-command-uncertain').write_text('unknown')
            tools=root/'tools'; tools.mkdir(); fake=tools/'xcrun'
            fake.write_text('#!/bin/sh\ntouch "'+str(root/'command-ran')+'"\n'); fake.chmod(0o755)
            result=subprocess.run(['bash',str(script),'iPadMini','shutdown'],cwd=root,
                env=dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH']),capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,3)
            self.assertFalse((root/'command-ran').exists())



if __name__ == '__main__':
    unittest.main()
