import signal
import select
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from bounded_process import run_captured, stop_group


class BoundedProcessTests(unittest.TestCase):
    def test_normal_output_and_exit(self):
        result = run_captured([sys.executable, '-c', 'print("synthetic")'], 5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'synthetic')

    def test_unreapable_child_never_uses_an_unbounded_wait(self):
        class Stuck:
            pid = 987654
            waits = []
            def poll(self): return None
            def wait(self, timeout):
                self.waits.append(timeout)
                raise subprocess.TimeoutExpired('synthetic', timeout)
        child = Stuck()
        events = []
        with patch('bounded_process.os.killpg') as kill:
            self.assertFalse(stop_group(child, grace=0.1, checkpoint=events.append))
        self.assertEqual(child.waits, [0.1, 0.1])
        self.assertEqual([call.args[1] for call in kill.call_args_list], [signal.SIGTERM, signal.SIGKILL])
        self.assertIn('exit unconfirmed', events[-1])

    def test_real_timeout_is_failed_and_child_exit_is_confirmed(self):
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_captured([sys.executable, '-c', 'import time; time.sleep(30)'], 0.1)
        self.assertTrue(raised.exception.cleanup_confirmed)
        self.assertLess(time.monotonic() - start, 3)

    def test_real_term_ignoring_child_reaches_bounded_kill(self):
        child = subprocess.Popen([sys.executable, '-u', '-c',
            'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready"); time.sleep(30)'],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'Synthetic child did not become ready')
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            events = []
            self.assertTrue(stop_group(child, grace=0.1, checkpoint=events.append))
            self.assertEqual(child.returncode, -signal.SIGKILL)
            self.assertIn('sending SIGKILL', events)
        finally:
            stop_group(child, grace=0.1)
            child.stdout.close()


if __name__ == '__main__':
    unittest.main()
