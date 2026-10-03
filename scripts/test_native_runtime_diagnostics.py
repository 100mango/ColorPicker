import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from native_runtime_diagnostics import crash_summary, process_rows, recent_crashes, snapshot


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_only_named_processes_without_arguments_or_paths(self):
        result = process_rows(' PID PPID STAT RSS COMM\n 11 1 S 100 /synthetic/TouchColor\n 12 1 S 200 /synthetic/Unrelated\n 13 1 R 300 /system/SurfBoard\n')
        self.assertEqual([row['name'] for row in result], ['TouchColor', 'SurfBoard'])
        self.assertNotIn('/synthetic', json.dumps(result))

    def test_crash_parser_keeps_only_selected_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'TouchColor-synthetic.ips'
            path.write_text('{}\n' + json.dumps({'procName': 'TouchColor', 'pid': 12,
                'exception': {'type': 'EXC_CRASH', 'signal': 'SIGABRT', 'private': 'omit'},
                'termination': {'namespace': 'SIGNAL', 'code': 6},
                'environment': {'synthetic_private': 'omit'}, 'threads': ['omit']}))
            result = crash_summary(path)
            self.assertEqual(result['exception'], {'type': 'EXC_CRASH', 'signal': 'SIGABRT'})
            self.assertNotIn('omit', json.dumps(result))
            self.assertEqual(len(recent_crashes([Path(root)], time.time() - 5)), 1)
            self.assertEqual(recent_crashes([Path(root)], time.time() + 5), [])

    def test_oversize_and_symlink_reports_are_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'TouchColor-large.ips'
            path.write_bytes(b'x' * 512_001)
            (Path(root) / 'TouchColor-link.ips').symlink_to(path)
            result = recent_crashes([Path(root)], 0)
            self.assertEqual(len(result), 1)
            self.assertIn('omitted', result[0])

    def test_unconfirmed_diagnostic_timeout_stops_further_commands(self):
        commands = []
        def command_runner(command, **kwargs):
            commands.append(command)
            error = subprocess.TimeoutExpired(command, 3)
            error.cleanup_confirmed = False
            raise error
        result = snapshot('synthetic', None, time.time(), command_runner)
        self.assertTrue(result['cleanup_unconfirmed'])
        self.assertEqual(len(commands), 1)


if __name__ == '__main__': unittest.main()
