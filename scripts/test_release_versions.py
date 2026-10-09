"""Exact release version wiring and negative fixtures; no native claims."""
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import verify_original_ios_package as package
import test_original_ios_package as package_fixture
import test_embedded_watch as watch_fixture
import verify_embedded_watch as watch_gate

ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_all_five_app_targets_resolve_both_configurations_to_exact_pair(self):
        for name in ['TouchColor', 'TouchColorMac', 'TouchColorTV', 'TouchColorVision', 'TouchColorWatch']:
            with self.subTest(target=name):
                project = package.generated_project((ROOT / (name + '.xcodeproj/project.pbxproj')).read_bytes())
                objects = project['objects']
                targets = [x for x in objects.values() if x.get('isa') == 'PBXNativeTarget' and x.get('name') == name]
                self.assertEqual(len(targets), 1)
                configs = [objects[x] for x in objects[targets[0]['buildConfigurationList']]['buildConfigurations']]
                self.assertEqual({c['name'] for c in configs}, {'Debug', 'Release'})
                for config in configs:
                    self.assertEqual(config['buildSettings']['MARKETING_VERSION'], '2.0.1')
                    self.assertEqual(config['buildSettings']['CURRENT_PROJECT_VERSION'], '20002')

    def test_source_variable_plist_and_independent_test_fixtures_are_preserved(self):
        app = plistlib.loads((ROOT / 'ColorPicker/TouchColor-Info.plist').read_bytes())
        self.assertEqual(app['CFBundleShortVersionString'], '$(MARKETING_VERSION)')
        self.assertEqual(app['CFBundleVersion'], '$(CURRENT_PROJECT_VERSION)')
        for name in ['ColorPickerTests/TouchColorTests-Info.plist', 'TestFixtures/PaletteFixtures/Info.plist']:
            value = plistlib.loads((ROOT / name).read_bytes())
            self.assertEqual((value['CFBundleShortVersionString'], value['CFBundleVersion']), ('1.0', '1'))

    def test_original_package_rejects_old_split_missing_or_numeric_versions(self):
        for key, wrong in [('CFBundleShortVersionString', '2.0'), ('CFBundleVersion', '20001'),
                           ('CFBundleVersion', 20002), ('CFBundleVersion', None), ('CFBundleShortVersionString', None)]:
            with self.subTest(key=key, wrong=wrong):
                owner = package_fixture.PackageTests(); self.addCleanup(owner.doCleanups); f = owner.fixture()
                if wrong is None: f.metadata.pop(key)
                else: f.metadata[key] = wrong
                f.write_info()
                with self.assertRaisesRegex(ValueError, 'App metadata mismatch'): f.verify()

    def test_phone_watch_versions_reject_old_and_partial_updates(self):
        for role in ['phone', 'watch', 'both']:
            for key, wrong in [('CFBundleShortVersionString', '2.0'), ('CFBundleVersion', '20001'), ('CFBundleVersion', 20002), ('CFBundleVersion', None)]:
                with self.subTest(role=role, key=key, wrong=wrong), tempfile.TemporaryDirectory() as temp:
                    owner = watch_fixture.EmbeddedWatchTests(); phone, watch = owner.create(Path(temp))
                    for target in ([phone, watch] if role == 'both' else [phone if role == 'phone' else watch]):
                        info = plistlib.loads((target / 'Info.plist').read_bytes())
                        if wrong is None: info.pop(key)
                        else: info[key] = wrong
                        (target / 'Info.plist').write_bytes(plistlib.dumps(info))
                    with patch('verify_embedded_watch.check_output', return_value='production'), self.assertRaisesRegex(ValueError, 'version mismatch'):
                        watch_gate.verify(phone)

    def test_native_runner_version_predicates_keep_exact_pair(self):
        for name in ['test_extra_platforms.py', 'test_paired_watch.py']:
            text = (ROOT / 'scripts' / name).read_text()
            self.assertIn("'CFBundleShortVersionString'", text)
            self.assertIn("=='2.0.1'", text)
            self.assertIn("'CFBundleVersion'", text)
            self.assertIn("=='20002'", text)
            self.assertNotIn("=='20001'", text)


if __name__ == '__main__':
    unittest.main()
