import contextlib
import hashlib
import io
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from vision_capture_format import verify_generated


class CaptureFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'derived'
        self.products = self.root/'Build/Products'
        (self.products/'Debug-xrsimulator/TouchColor.app').mkdir(parents=True)
        self.file = self.products/'TouchColorVision.xctestrun'
        self.target = dict(TestBundlePath='__TESTHOST__/PlugIns/TouchColorVisionUITests.xctest',
                           IsUITestBundle=True, PreferredScreenCaptureFormat='screenshots',
                           UITargetAppPath='__TESTROOT__/Debug-xrsimulator/TouchColor.app')
        self.write()
        self.budget = patch('vision_capture_format.enabled_budget', return_value=None)
        self.budget.start(); self.addCleanup(self.budget.stop)

    def write(self, value=None):
        self.file.write_bytes(plistlib.dumps(value if value is not None else
            {'TestConfigurations': [{'TestTargets': [self.target]}]}))

    def verify(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return verify_generated(self.root, **kwargs)

    def test_current_and_legacy_target_containers_are_read_only(self):
        for value in ({'TestConfigurations': [{'TestTargets': [self.target]}]},
                      {'TouchColorVisionUITests': self.target}):
            self.write(value); before = self.file.read_bytes()
            result = self.verify()
            self.assertEqual(result['preferred_capture_format'], 'screenshots')
            self.assertEqual(result['sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(before, self.file.read_bytes())
            self.assertIn('runtime media/resource behavior still requires verification', result['scope'])

    def test_missing_or_other_format_rejects_with_small_probe(self):
        for value in (None, 'screenRecording', 'bogus', True, ['screenshots']):
            if value is None: self.target.pop('PreferredScreenCaptureFormat', None)
            else: self.target['PreferredScreenCaptureFormat'] = value
            self.write(); out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(ValueError): verify_generated(self.root)
            self.assertIn('VISION_CAPTURE_CONFIGURATION_PROBE', out.getvalue())
            self.assertNotIn('UITargetAppPath', out.getvalue())
            self.assertLess(len(out.getvalue()), 400)

    def test_preserves_default_and_failure_attachment_lifetimes(self):
        for value in (None, 'deleteOnSuccess', 'keepAlways'):
            if value is None: self.target.pop('SystemAttachmentLifetime', None)
            else: self.target['SystemAttachmentLifetime'] = value
            self.write(); self.assertEqual(self.verify()['system_attachment_lifetime'], value)
        for value in ('keepNever', 'unknown'):
            self.target['SystemAttachmentLifetime'] = value; self.write()
            with self.assertRaises(ValueError): self.verify()

    def test_missing_duplicate_non_ui_or_wrong_app_fails(self):
        cases = [{'TestTargets': []}, {'TestTargets': [self.target, self.target]},
                 {'TestTargets': [dict(self.target, IsUITestBundle=False)]},
                 {'TestTargets': [dict(self.target, UITargetAppPath='/tmp/another.app')]},
                 {'TestTargets': [dict(self.target, TestBundlePath='Wrong.xctest')]}]
        for value in cases:
            self.write(value)
            with self.assertRaises(ValueError): self.verify()

    def test_symlink_hardlink_oversize_and_extra_configuration_reject(self):
        self.file.rename(self.products/'actual')
        self.file.symlink_to('actual')
        with self.assertRaises(ValueError): self.verify()
        self.file.unlink(); self.file.write_bytes((self.products/'actual').read_bytes())
        os.link(self.file, self.products/'hardlink')
        with self.assertRaises(ValueError): self.verify()
        (self.products/'hardlink').unlink()
        self.file.write_bytes(b'x'*2_000_001)
        with self.assertRaises(ValueError): self.verify()
        self.write(); (self.products/'second.xctestrun').write_bytes(self.file.read_bytes())
        with self.assertRaises(ValueError): self.verify()

    def test_structure_entries_and_late_final_check_are_bounded(self):
        self.write({'many': [0]*4097, 'target': self.target})
        with self.assertRaises(ValueError): self.verify()
        self.write()
        count = [0]
        def clock():
            count[0] += 1
            return 1000 if count[0] > 4 else 0
        with self.assertRaisesRegex(ValueError, 'finite bound'): self.verify(clock=clock)
        for i in range(129): (self.products/str(i)).touch()
        with self.assertRaisesRegex(ValueError, 'Too many'): self.verify()

    def test_budget_admission_precedes_any_read(self):
        with patch('vision_capture_format.enabled_budget') as budget, patch.object(Path, 'iterdir') as read:
            budget.return_value.admit.side_effect = RuntimeError('exhausted')
            with self.assertRaises(RuntimeError): self.verify()
            read.assert_not_called()
            budget.return_value.admit.assert_called_once_with('Vision generated capture-format readback', 5, minimum=5, cleanup=0)

    def test_source_setting_and_both_preboot_readbacks_preserve_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        scheme = root/'TouchColorVision.xcodeproj/xcshareddata/xcschemes/TouchColorVision.xcscheme'
        action = ET.parse(scheme).getroot().find('TestAction')
        self.assertEqual(action.attrib['preferredScreenCaptureFormat'], 'screenshots')
        self.assertNotIn('systemAttachmentLifetime', action.attrib)
        self.assertNotIn('userAttachmentLifetime', action.attrib)
        generator = (root/'scripts/generate_vision_project.py').read_text()
        self.assertIn("preferredScreenCaptureFormat='screenshots'", generator)
        driver = (root/'scripts/test_extra_platforms.py').read_text()
        self.assertLess(driver.index("report['capture_configuration']=verify_capture_format('build/vision-tests')"),
                        driver.index("runner_info=Path('build/vision-tests"))
        workflow = (root/'.github/workflows/apple-platforms.yml').read_text()
        self.assertEqual(workflow.count('python3 scripts/vision_capture_format.py build/vision-tests'), 1)
        self.assertEqual(workflow.count('test_vision_capture_format'), 2)
        self.assertIn("capture_simulator_checkpoint", driver)
        for other in ('TouchColorWatch', 'TouchColorTV', 'TouchColorMac'):
            for other_scheme in (root/(other+'.xcodeproj')).glob('xcshareddata/xcschemes/*.xcscheme'):
                self.assertNotIn('preferredScreenCaptureFormat', other_scheme.read_text())


if __name__ == '__main__': unittest.main()
