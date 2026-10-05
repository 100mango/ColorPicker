"""Portable synthetic-only tests. Never invokes sample or captures any stack."""
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import sample_capability_probe as probe


class CapabilityProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Canonicalizing trusted test fixtures is explicit; production rejects
        # aliases and never silently resolves a tool or caller-supplied path.
        self.directory = Path(self.temporary.name).resolve()
        self.python = str(Path(sys.executable).resolve())
        # Cloud test runtimes are immutable mounts owned by nobody rather than
        # root. This explicit test-only owner set does not relax the Mac CLI.
        owner_patch = patch.object(probe, 'TOOL_OWNERS',
            frozenset((0, os.getuid(), os.stat(self.python).st_uid)))
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def run_python(self, source, **kwargs):
        return probe.run_bounded([self.python, '-I', '-S', '-c', source],
                                 self.directory, interpreter=self.python, **kwargs)

    def test_normal_both_streams_limits_and_cleanup(self):
        result = self.run_python(
            "import os,resource; "
            "assert resource.getrlimit(resource.RLIMIT_FSIZE)==(4096,4096); "
            "assert resource.getrlimit(resource.RLIMIT_CORE)==(0,0); "
            "os.write(1,b'public-help\\n'); os.write(2,b'also-stderr\\n')",
            file_cap=4096)
        self.assertEqual(result.output, b'public-help\nalso-stderr\n')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.limit_ready)
        self.assertTrue(result.cleanup_confirmed)
        self.assertFalse(result.truncated or result.timed_out)

    def test_file_producer_is_kernel_bounded_before_parent_reads(self):
        result = self.run_python(
            "import os,signal; signal.signal(signal.SIGXFSZ,signal.SIG_DFL); "
            "fd=os.open('owned.bin',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); "
            "os.write(fd,b'x'*1000000)", file_cap=4096)
        self.assertTrue(result.limit_ready)
        self.assertTrue(result.cleanup_confirmed)
        self.assertLessEqual((self.directory / 'owned.bin').stat().st_size, 4096)
        # A first write may be shortened without a signal. A second over-limit
        # write proves the boundary cannot subsequently be extended.
        other = self.run_python(
            "import os,signal; signal.signal(signal.SIGXFSZ,signal.SIG_DFL); "
            "fd=os.open('owned2.bin',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); "
            "os.write(fd,b'x'*4096); os.write(fd,b'y')", file_cap=4096)
        self.assertEqual(other.returncode, -signal_number('SIGXFSZ'))
        self.assertEqual((self.directory / 'owned2.bin').stat().st_size, 4096)
        self.assertTrue(other.cleanup_confirmed)

    def test_continuous_pipe_overflow_is_bounded_and_stopped(self):
        start = time.monotonic()
        result = self.run_python("import os\nwhile True: os.write(1,b'x'*8192)",
                                 pipe_cap=4096)
        self.assertEqual(len(result.output), 4096)
        self.assertTrue(result.truncated)
        self.assertTrue(result.cleanup_confirmed)
        self.assertLess(time.monotonic() - start, 2)
        report = json.loads(probe.capability_report(result))
        self.assertIsNone(report['help']['sha256'])
        self.assertFalse(report['help']['complete'])

    def test_exact_pipe_cap_is_conservatively_incomplete(self):
        result = self.run_python("import os; os.write(1,b'x'*2048)", pipe_cap=2048)
        self.assertEqual(len(result.output), 2048)
        self.assertTrue(result.truncated)
        self.assertTrue(result.cleanup_confirmed)

    def test_timeout_stops_owned_term_ignoring_process(self):
        result = self.run_python(
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "time.sleep(30)", timeout=0.2)
        self.assertTrue(result.timed_out)
        self.assertTrue(result.cleanup_confirmed)
        self.assertEqual(result.returncode, -signal_number('SIGKILL'))

    def test_group_cleanup_reaps_cooperative_owned_descendant(self):
        result = self.run_python(
            "import subprocess,sys,signal,time\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            "def stop(*ignored):\n"
            " child.wait(timeout=0.4)\n"
            " raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM,stop)\n"
            "time.sleep(30)\n", timeout=0.25)
        self.assertTrue(result.timed_out)
        self.assertTrue(result.cleanup_confirmed)

    def test_cleanup_uncertainty_fail_closed(self):
        result = probe.Result(b'usage: sample pid duration interval\n', 0,
                              True, False, False, False)
        report = json.loads(probe.capability_report(result))
        self.assertEqual(report['reason'], 'help_incomplete_or_cleanup_unconfirmed')
        self.assertIsNone(report['help']['sha256'])
        self.assertFalse(report['captureAttempted'])

    def test_no_group_signals_after_reap(self):
        class FakeProcess:
            pid = 9999999
            returncode = None
            def wait(self, timeout):
                self.returncode = 0
        fake = FakeProcess()
        signals = []
        def killpg(pid, sig):
            if sig:
                self.assertIsNone(fake.returncode)
                signals.append(sig)
            else:
                raise ProcessLookupError()
        with patch.object(probe.os, 'getpgid', return_value=fake.pid), \
                patch.object(probe.os, 'killpg', side_effect=killpg):
            self.assertTrue(probe._stop_owned_unreaped_group(fake))
        self.assertEqual(signals, [signal_number('SIGTERM'), signal_number('SIGKILL')])
        self.assertFalse(probe._stop_owned_unreaped_group(fake))

    def test_producer_identity_mismatch_prevents_exec(self):
        original = probe.identity
        def mismatched(info):
            values = original(info)
            values[1] += 1
            return values
        with patch.object(probe, 'identity', side_effect=mismatched):
            result = self.run_python("import os; os.write(1,b'MUST_NOT_EXECUTE')")
        self.assertEqual(result.output, b'')
        self.assertFalse(result.limit_ready)
        self.assertEqual(result.returncode, 125)
        self.assertTrue(result.cleanup_confirmed)

    def test_post_capture_identity_ambiguity_is_unavailable(self):
        result = probe.Result(b'Usage: sample pid', 1, True, False, False, True, False)
        report = json.loads(probe.capability_report(result))
        self.assertFalse(report['help']['complete'])
        self.assertIsNone(report['help']['sha256'])
        self.assertFalse(report['help']['identityConfirmed'])
        self.assertFalse(report['captureAttempted'])

    def test_invalid_bounds_are_rejected_under_optimization(self):
        for kwargs in ({'timeout': True}, {'timeout': math.nan}, {'timeout': math.inf},
                       {'timeout': 0}, {'timeout': 6}, {'pipe_cap': True},
                       {'pipe_cap': 32769}, {'file_cap': 65537}, {'file_cap': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_python('pass', **kwargs)

    def test_symlink_file_and_symlink_ancestor_are_rejected(self):
        file = self.directory / 'regular'
        file.write_bytes(b'public')
        alias = self.directory / 'alias'
        alias.symlink_to(file)
        ancestor = self.directory / 'linked'
        ancestor.symlink_to(self.directory, target_is_directory=True)
        for candidate in (alias, ancestor / 'regular'):
            with self.subTest(path=candidate), self.assertRaises(probe.Unavailable):
                probe.checked_file(candidate, owner=os.getuid())

    def test_hardlink_special_file_relative_and_dotdot_rejected(self):
        file = self.directory / 'regular'
        file.write_bytes(b'public')
        os.link(file, self.directory / 'hardlink')
        os.mkfifo(self.directory / 'fifo')
        for candidate in (file, self.directory / 'fifo', Path('relative'),
                          str(self.directory) + '/../wrong',
                          str(self.directory) + '/./regular'):
            with self.subTest(path=candidate), self.assertRaises(probe.Unavailable):
                probe.checked_file(candidate, owner=os.getuid())

    def test_non_private_and_symlink_work_directories_rejected(self):
        public = self.directory / 'public'
        public.mkdir(mode=0o755)
        alias = self.directory / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        for candidate in (public, alias):
            with self.assertRaises(probe.Unavailable):
                probe.checked_directory(candidate)

    def test_trusted_launcher_rejects_writable_file_and_ancestor(self):
        # Keep ancestors in the already trusted checkout; /tmp is intentionally
        # ineligible for trusted code because its ancestor is world-writable.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            parent = Path(temporary).resolve()
            launcher = parent / 'owned_launcher.py'
            launcher.write_text('pass\n')
            launcher.chmod(0o600)
            fd = probe.checked_file(launcher, owner=os.getuid(), trusted_code=True)
            os.close(fd)  # Non-executable trusted source is valid.
            launcher.chmod(0o666)
            with self.assertRaises(probe.Unavailable):
                probe.checked_file(launcher, owner=os.getuid(), trusted_code=True)
            launcher.chmod(0o600)
            parent.chmod(0o777)
            try:
                with self.assertRaises(probe.Unavailable):
                    probe.checked_file(launcher, owner=os.getuid(), trusted_code=True)
            finally:
                parent.chmod(0o700)

    def test_executable_alias_never_launches(self):
        alias = self.directory / 'python'
        alias.symlink_to(self.python)
        with patch.object(probe.subprocess, 'Popen') as launch:
            with self.assertRaises(probe.Unavailable):
                probe.run_bounded([str(alias), '-c', 'pass'], self.directory,
                                  interpreter=self.python)
            launch.assert_not_called()

    def test_help_response_cannot_enable_capture_or_claim_parser(self):
        output = b'Usage: sample <pid> [duration [interval]]\nOptions:\n -file <filename>\n'
        result = probe.Result(output, 1, True, False, False, True)
        encoded = probe.capability_report(result)
        report = json.loads(encoded)
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue(report['help']['usageResponseObserved'])
        self.assertEqual(report['help']['sha256'], hashlib.sha256(output).hexdigest())
        self.assertFalse(report['captureAttempted'])
        self.assertFalse(report['targetCreated'])
        self.assertEqual(report['stackExtraction'], 'not_implemented')
        self.assertEqual(report['watchCause'], 'not_assessed')
        self.assertEqual(report['help']['text'], output.decode('utf-8'))
        self.assertTrue(report['help']['textComplete'])
        self.assertEqual(report['help']['retainedTextBytes'], len(output))
        self.assertNotIn('raw_help', report['omissions'])
        self.assertLessEqual(len(encoded), probe.REPORT_CAP)
        self.assertLessEqual(probe.FILE_CAP + probe.PIPE_CAP + probe.REPORT_CAP,
                             probe.TOTAL_RETAINED_CAP)

    def help_report(self, output, **changes):
        fields = dict(output=output, returncode=1, limit_ready=True,
                      timed_out=False, truncated=False, cleanup_confirmed=True)
        fields.update(changes)
        return json.loads(probe.capability_report(probe.Result(**fields)))

    def test_complete_utf8_help_is_retained_exactly(self):
        text = 'Usage: sample <pid> [duration]\r\nOptions: durée\r\n'
        report = self.help_report(text.encode('utf-8'))
        self.assertEqual(report['help']['text'], text)
        self.assertEqual(report['help']['textStatus'], 'retained_complete')
        self.assertEqual(report['help']['retainedTextBytes'], len(text.encode('utf-8')))
        self.assertFalse(report['captureAttempted'])

    def test_invalid_utf8_and_unknown_control_text_are_wholly_omitted(self):
        for body, status in ((b'Usage: sample pid\n\xff', 'omitted_invalid_utf8'),
                             (b'Usage: sample pid\n\x1b[31m', 'omitted_unsupported_controls'),
                             (b'Usage: sample pid\rhidden', 'omitted_unsupported_controls'),
                             ('Usage: sample pid\n\u202e'.encode('utf-8'), 'omitted_unsupported_controls')):
            report = self.help_report(body)
            self.assertEqual(report['help']['textStatus'], status)
            self.assertNotIn('text', report['help'])
            self.assertFalse(report['help']['textComplete'])
            self.assertEqual(report['help']['retainedTextBytes'], 0)
            self.assertIn('raw_help', report['omissions'])

    def test_oversized_help_retains_no_prefix(self):
        body = b'Usage: sample pid\n' + b'x' * probe.HELP_TEXT_CAP
        report = self.help_report(body)
        self.assertEqual(report['help']['textStatus'], 'omitted_oversized')
        self.assertNotIn('text', report['help'])
        self.assertTrue(report['help']['complete'])
        self.assertEqual(report['help']['sha256'], hashlib.sha256(body).hexdigest())
        self.assertFalse(report['help']['textComplete'])

    def test_exact_help_text_cap_is_complete_if_source_is_complete(self):
        prefix = b'Usage: sample pid\n'
        body = prefix + b'x' * (probe.HELP_TEXT_CAP - len(prefix))
        report = self.help_report(body)
        self.assertEqual(report['help']['text'].encode('utf-8'), body)
        self.assertTrue(report['help']['textComplete'])
        self.assertEqual(report['help']['retainedTextBytes'], probe.HELP_TEXT_CAP)

    def test_json_expansion_omits_whole_help_instead_of_trimming(self):
        body = ('Usage: sample pid\n' + '\u0100' * 5900).encode('utf-8')
        self.assertLess(len(body), probe.HELP_TEXT_CAP)
        report = self.help_report(body)
        self.assertEqual(report['help']['textStatus'], 'omitted_report_bound')
        self.assertNotIn('text', report['help'])
        self.assertFalse(report['help']['textComplete'])
        self.assertLessEqual(len(json.dumps(report, indent=2).encode('ascii')), probe.REPORT_CAP)

    def test_unknown_prefix_is_not_promoted_by_later_usage_line(self):
        report = self.help_report(b'PRIVATE SENTINEL\nUsage: sample pid\n')
        self.assertEqual(report['help']['textStatus'], 'omitted_unknown_response')
        self.assertNotIn('PRIVATE SENTINEL', json.dumps(report))
        self.assertNotIn('text', report['help'])

    def test_incomplete_or_signalled_help_never_retains_text(self):
        for changes in ({'truncated': True}, {'timed_out': True},
                        {'cleanup_confirmed': False}, {'identity_confirmed': False},
                        {'limit_ready': False}, {'returncode': -15}):
            with self.subTest(changes=changes):
                report = self.help_report(b'Usage: sample pid\n', **changes)
                self.assertEqual(report['help']['textStatus'], 'omitted_incomplete')
                self.assertNotIn('text', report['help'])
                self.assertIsNone(report['help']['sha256'])
                self.assertFalse(report['help']['textComplete'])

    def test_unknown_help_or_missing_limit_ack_is_unavailable(self):
        for result in (probe.Result(b'unknown format', 0, True, False, False, True),
                       probe.Result(b'Usage: sample pid', 0, False, False, False, True)):
            report = json.loads(probe.capability_report(result))
            self.assertEqual(report['status'], 'unavailable')
            self.assertFalse(report['captureAttempted'])
        report = json.loads(probe.capability_report(
            probe.Result(b'unknown', 0, True, False, False, True)))
        self.assertEqual(report['reason'], 'installed_help_unrecognized')

    def test_non_darwin_never_invokes_any_producer(self):
        with patch.object(probe.sys, 'platform', 'linux'), \
                patch.object(probe, 'run_bounded') as launch:
            report = json.loads(probe.inspect_installed_help(self.directory))
            self.assertEqual(report['reason'], 'darwin_required')
            launch.assert_not_called()

    def test_targetless_help_command_has_no_guessed_flags(self):
        result = probe.Result(b'Usage: sample pid', 1, True, False, False, True)
        with patch.object(probe.sys, 'platform', 'darwin'), \
                patch.object(probe, 'checked_file', return_value=1234), \
                patch.object(probe.os, 'close'), \
                patch.object(probe, 'run_bounded', return_value=result) as launch:
            report = json.loads(probe.inspect_installed_help(self.directory))
            launch.assert_called_once_with(['/usr/bin/sample'], self.directory)
            self.assertFalse(report['captureAttempted'])


def signal_number(name):
    import signal
    return getattr(signal, name)


if __name__ == '__main__':
    unittest.main()
