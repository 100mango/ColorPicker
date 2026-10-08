import subprocess
import tempfile
from pathlib import Path
import unittest
from native_resources import result_sizes, snapshot, require_responsive


class ResourceTests(unittest.TestCase):
    def test_sizes_cover_only_owned_results_without_following_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = root/'vision-ui.xcresult'; result.mkdir()
            (result/'data').write_bytes(b'12345')
            elsewhere = root/'other'; elsewhere.mkdir(); (elsewhere/'payload').write_bytes(b'x'*100)
            (result/'external').symlink_to(elsewhere, target_is_directory=True)
            value = result_sizes(root)
            self.assertEqual(value['bytes_observed'], 5)
            self.assertFalse(value['partial'])
            self.assertEqual(value['bundles'], ['vision-ui.xcresult'])
            self.assertTrue(result_sizes(root, maximum_entries=1)['partial'])
            self.assertTrue(result_sizes(root, maximum_seconds=0)['partial'])

    def test_responsiveness_requires_both_successful_bounded_probes(self):
        healthy={'memory_swap':{'exit':0},'pages':{'exit':0}}
        self.assertTrue(require_responsive(healthy))
        for value in ({}, {'memory_swap':{'exit':0},'pages':{'error':'TimeoutExpired'}},
                      {'memory_swap':{'exit':1},'pages':{'exit':0}},
                      {**healthy,'cleanup_unconfirmed':True}):
            with self.assertRaises(RuntimeError): require_responsive(value)

    def test_snapshot_is_small_and_does_not_enumerate_processes(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            self.assertEqual(kwargs['timeout'], 3)
            return subprocess.CompletedProcess(command, 0, stdout='x'*4000, stderr='')
        with tempfile.TemporaryDirectory() as folder:
            value = snapshot('before UI', Path(folder), run)
        self.assertEqual(commands, [['sysctl', 'hw.memsize', 'vm.swapusage'], ['vm_stat']])
        self.assertEqual(len(value['pages']['text']), 1600)
        self.assertIn('wall_time', value); self.assertIn('monotonic_seconds', value)
        self.assertGreater(value['disk']['available_bytes'], 0)

    def test_unconfirmed_exit_stops_optional_command_family(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            error = subprocess.TimeoutExpired(command, 3); error.cleanup_confirmed = False
            raise error
        with tempfile.TemporaryDirectory() as folder:
            value = snapshot('after failed UI', Path(folder), run)
        self.assertTrue(value['cleanup_unconfirmed'])
        self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
