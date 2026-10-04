import re
import unittest
from pathlib import Path
from vision_suites import CASES, needs_photo_seed


class VisionSuiteTests(unittest.TestCase):
    def test_only_real_photo_import_has_a_library_seed_prerequisite(self):
        self.assertEqual([case for case in CASES if needs_photo_seed('vision', case)], ['photos'])
        self.assertEqual(CASES['photos'][0], 'testRealPhotosImport')
        self.assertTrue(needs_photo_seed('tv'))
        self.assertFalse(needs_photo_seed('watch'))
        with self.assertRaises(ValueError): needs_photo_seed('vision', 'unknown')

    def test_every_real_ui_case_runs_exactly_once_across_fresh_vms(self):
        source = (Path(__file__).resolve().parents[1] / 'TouchColorVisionUITests/VisionWorkflowTests.swift').read_text()
        actual = re.findall(r'func (test\w+)\(', source)
        selected = [method for method, _ in CASES.values()]
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(set(selected), set(actual))

    def test_exact_workflow_rows_preserve_the_whole_run_budget(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/apple-platforms.yml').read_text()
        rows = re.findall(r'- platform: vision\s+lane: vision-([a-z-]+)\s+vision_case: ([a-z-]+)\s+minutes: (\d+)\s+evidence_bytes: (\d+)', workflow)
        self.assertEqual(len(rows), len(CASES))
        self.assertEqual({case for _, case, _, _ in rows}, set(CASES))
        for lane, case, minutes, budget in rows:
            self.assertEqual(lane, case)
            self.assertEqual(int(minutes), 25)
            self.assertEqual(int(budget), CASES[case][1])
        self.assertEqual(sum(budget for _, budget in CASES.values()), 8_000_000)
        self.assertEqual(sum(map(int, re.findall(r'evidence_bytes: (\d+)', workflow))), 20_000_000)
        self.assertIn('max-parallel: 2', workflow)
        self.assertIn('retention-days: 1', workflow)
        self.assertNotIn('TOUCHCOLOR_VISION_SUITE', workflow)


if __name__ == '__main__':
    unittest.main()
