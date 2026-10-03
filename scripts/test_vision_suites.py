import re
import unittest
from pathlib import Path
from vision_suites import SUITES


class VisionSuiteTests(unittest.TestCase):
    def test_every_real_ui_case_runs_exactly_once_across_fresh_vms(self):
        source = (Path(__file__).resolve().parents[1] / 'TouchColorVisionUITests/VisionWorkflowTests.swift').read_text()
        actual = re.findall(r'func (test\w+)\(', source)
        selected = [method for cases in SUITES.values() for method in cases]
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(set(selected), set(actual))


if __name__ == '__main__':
    unittest.main()
