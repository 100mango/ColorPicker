"""Synthetic Mac metadata regressions; never a native build or archive result."""
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
import verify_mac_release_settings as gate


class MacReleaseSettingsTests(unittest.TestCase):
    def fixture(self):
        owner = tempfile.TemporaryDirectory(); self.addCleanup(owner.cleanup)
        root = Path(owner.name).resolve()
        settings = {'CONFIGURATION': 'Release', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.mango.touchColor',
                    'PRODUCT_NAME': 'TouchColor', 'MACOSX_DEPLOYMENT_TARGET': '13.0',
                    'TOUCHCOLOR_ENABLE_SANDBOX': 'YES', 'ENABLE_APP_SANDBOX': 'YES',
                    'CODE_SIGNING_ALLOWED': 'NO', 'MARKETING_VERSION': '2.0.1',
                    'CURRENT_PROJECT_VERSION': '20002', 'FULL_PRODUCT_NAME': 'TouchColor.app',
                    'SRCROOT': str(root), 'TARGET_BUILD_DIR': str(root / 'build'),
                    'CODE_SIGN_ENTITLEMENTS': 'TouchColorMac/TouchColorMac.entitlements'}
        entitlement = root / settings['CODE_SIGN_ENTITLEMENTS']; entitlement.parent.mkdir()
        entitlement.write_bytes(plistlib.dumps(gate.EXPECTED_SANDBOX))
        app = root / 'build/TouchColor.app'; (app / 'Contents').mkdir(parents=True)
        info = {'CFBundleIdentifier': 'com.mango.touchColor', 'CFBundlePackageType': 'APPL',
                'CFBundleExecutable': 'TouchColor', 'CFBundleShortVersionString': '2.0.1', 'CFBundleVersion': '20002'}
        metadata = app / 'Contents/Info.plist'; metadata.write_bytes(plistlib.dumps(info))
        path = root / 'settings.json'
        def save(): path.write_text(json.dumps([{'target': 'TouchColorMac', 'buildSettings': settings}]))
        save()
        return root, settings, info, path, metadata, entitlement, save

    def test_actual_settings_and_app_metadata_agree(self):
        _, _, _, path, _, _, _ = self.fixture()
        report = gate.verify(path)
        self.assertEqual((report['version'], report['build']), ('2.0.1', '20002'))
        self.assertTrue(report['unsigned_release_settings'])

    def test_old_split_missing_or_numeric_versions_reject_in_settings_and_app(self):
        for settings_key, info_key, wrong in [('MARKETING_VERSION', 'CFBundleShortVersionString', '2.0'),
                                             ('CURRENT_PROJECT_VERSION', 'CFBundleVersion', '20001'),
                                             ('CURRENT_PROJECT_VERSION', 'CFBundleVersion', 20002),
                                             ('MARKETING_VERSION', 'CFBundleShortVersionString', None)]:
            for side in ('settings', 'app', 'both'):
                with self.subTest(side=side, key=settings_key, wrong=wrong):
                    _, settings, info, path, metadata, _, save = self.fixture()
                    if side in ('settings', 'both'): settings[settings_key] = wrong
                    if side in ('app', 'both'):
                        if wrong is None: info.pop(info_key)
                        else: info[info_key] = wrong
                    save(); metadata.write_bytes(plistlib.dumps(info))
                    with self.assertRaises(ValueError): gate.verify(path)

    def test_every_existing_identity_sandbox_and_unsigned_setting_remains_required(self):
        for key in ['CONFIGURATION', 'PRODUCT_BUNDLE_IDENTIFIER', 'PRODUCT_NAME', 'MACOSX_DEPLOYMENT_TARGET',
                    'TOUCHCOLOR_ENABLE_SANDBOX', 'ENABLE_APP_SANDBOX', 'CODE_SIGNING_ALLOWED', 'CODE_SIGN_ENTITLEMENTS']:
            with self.subTest(key=key):
                _, settings, _, path, _, _, save = self.fixture(); settings[key] = 'wrong'; save()
                with self.assertRaises(ValueError): gate.verify(path)

    def test_entitlement_extra_missing_wrong_type_and_changed_value_reject(self):
        for update in ('extra', 'missing', 'type', 'value'):
            with self.subTest(update=update):
                _, _, _, path, _, entitlement, _ = self.fixture(); values = dict(gate.EXPECTED_SANDBOX)
                if update == 'extra': values['com.apple.security.network.client'] = True
                elif update == 'missing': values.pop('com.apple.security.device.camera')
                elif update == 'type': values['com.apple.security.app-sandbox'] = 1
                else: values['com.apple.security.app-sandbox'] = False
                entitlement.write_bytes(plistlib.dumps(values))
                with self.assertRaises(ValueError): gate.verify(path)

    def test_missing_or_aliased_product_metadata_cannot_use_another_app(self):
        for mutation in ('missing', 'linked', 'wrong-product', 'relative-build', 'oversized'):
            with self.subTest(mutation=mutation):
                root, settings, _, path, metadata, _, save = self.fixture()
                if mutation == 'missing': metadata.unlink()
                elif mutation == 'linked':
                    other = root / 'other.plist'; other.write_bytes(metadata.read_bytes()); metadata.unlink(); metadata.symlink_to(other)
                elif mutation == 'wrong-product': settings['FULL_PRODUCT_NAME'] = '../Other.app'; save()
                elif mutation == 'relative-build': settings['TARGET_BUILD_DIR'] = 'relative'; save()
                else: metadata.write_bytes(b'x' * (1024 * 1024 + 1))
                with self.assertRaises(ValueError): gate.verify(path)

    def test_settings_queries_use_the_same_derived_data_as_the_actual_mac_build(self):
        root = Path(__file__).resolve().parents[1]
        for name in ['apple-platforms.yml', 'mac-watch-repair.yml']:
            with self.subTest(workflow=name):
                text = (root / '.github/workflows' / name).read_text().replace('\\\n', '')
                commands = [line.strip() for line in text.splitlines() if line.strip().startswith('xcodebuild ')]
                builds = [line for line in commands if '-scheme TouchColorMac ' in line and '-configuration Release ' in line
                          and 'ARCHS=arm64' in line and line.endswith('CODE_SIGNING_ALLOWED=NO build')]
                queries = [line for line in commands if '-showBuildSettings -json > build/mac-release-settings.json' in line]
                self.assertEqual(len(builds), 1)
                self.assertEqual(len(queries), 1)
                for line in builds + queries:
                    self.assertIn('-derivedDataPath build/mac-arm64', line)
                    self.assertIn('-scheme TouchColorMac -configuration Release', line)
                    self.assertIn('CODE_SIGNING_ALLOWED=NO', line)

    def test_duplicate_missing_or_malformed_target_records_reject(self):
        for mutation in ('duplicate', 'missing', 'malformed'):
            _, _, _, path, _, _, _ = self.fixture(); records = json.loads(path.read_text())
            if mutation == 'duplicate': records.append(records[0])
            elif mutation == 'missing': records.clear()
            else: records[0]['buildSettings'] = []
            path.write_text(json.dumps(records))
            with self.assertRaises(ValueError): gate.verify(path)


if __name__ == '__main__':
    unittest.main()
