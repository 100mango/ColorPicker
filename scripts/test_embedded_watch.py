import plistlib
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from verify_embedded_watch import verify

class EmbeddedWatchTests(unittest.TestCase):
    def create(self,root):
        phone=root/'TouchColor.app';watch=phone/'Watch/TouchColor.app'
        for app,identifier,minimum,platform in [(phone,'com.mango.touchColor','15.0','iPhoneOS'),(watch,'com.mango.touchColor.watchkitapp','9.0','WatchOS')]:
            app.mkdir(parents=True,exist_ok=True)
            info={'CFBundleIdentifier':identifier,'CFBundleExecutable':'TouchColor','CFBundleShortVersionString':'2.0','CFBundleVersion':'20001','MinimumOSVersion':minimum,'CFBundleSupportedPlatforms':[platform]}
            if app==watch: info.update(WKApplication=True,WKCompanionAppBundleIdentifier='com.mango.touchColor',WKRunsIndependentlyOfCompanionApp=True)
            (app/'Info.plist').write_bytes(plistlib.dumps(info))
            for name in ('TouchColor','Assets.car','PrivacyInfo.xcprivacy'): (app/name).write_bytes(b'synthetic')
        return phone,watch
    def test_actual_nested_identity_versions_and_no_test_leak(self):
        with tempfile.TemporaryDirectory() as root,patch('verify_embedded_watch.check_output',return_value='production'):
            phone,watch=self.create(Path(root));self.assertEqual(verify(phone)['watch']['MinimumOSVersion'],'9.0')
            info=plistlib.loads((watch/'Info.plist').read_bytes());info['CFBundleVersion']='1';(watch/'Info.plist').write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):verify(phone)
    def test_missing_embedding_or_debug_seam_fails(self):
        with tempfile.TemporaryDirectory() as root:
            phone,watch=self.create(Path(root))
            with patch('verify_embedded_watch.check_output',return_value='TOUCHCOLOR_PAIRED_E2E'):
                with self.assertRaises(ValueError):verify(phone)
            (watch/'Info.plist').unlink()
            with self.assertRaises(FileNotFoundError):verify(phone,release=False)
    def simulator_host(self,root):
        phone,watch=self.create(root)
        for app,platform in [(phone,'iPhoneSimulator'),(watch,'WatchSimulator')]:
            info=plistlib.loads((app/'Info.plist').read_bytes());info['CFBundleSupportedPlatforms']=[platform]
            (app/'Info.plist').write_bytes(plistlib.dumps(info))
        bundle=phone/'PlugIns/TouchColorTests.xctest';bundle.mkdir(parents=True)
        (bundle/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.mango.touchColor.TouchColorTests',
            'CFBundleExecutable':'TouchColorTests','CFBundlePackageType':'BNDL'}))
        (bundle/'TouchColorTests').write_bytes(b'synthetic test executable')
        return phone,watch,bundle
    def test_debug_test_host_requires_the_bundle_and_its_executable(self):
        with tempfile.TemporaryDirectory() as root:
            phone,watch,bundle=self.simulator_host(Path(root))
            (bundle/'TouchColorTests').unlink()
            with self.assertRaises(ValueError):verify(phone,'simulator',False,build_for_testing=True)
            shutil.rmtree(bundle)
            with self.assertRaises(ValueError):verify(phone,'simulator',False,build_for_testing=True)
    def test_only_explicit_debug_mode_allows_the_registered_hosted_test_bundle(self):
        with tempfile.TemporaryDirectory() as root,patch('verify_embedded_watch.check_output',return_value='production'):
            phone,watch,bundle=self.simulator_host(Path(root))
            self.assertEqual(verify(phone,'simulator',False,build_for_testing=True)['debug_test_host_bundles'],['PlugIns/TouchColorTests.xctest'])
            for release in (True,False):
                with self.assertRaises(ValueError):verify(phone,'simulator',release)
            with self.assertRaises(ValueError):verify(phone,'simulator',True,build_for_testing=True)
            with self.assertRaises(ValueError):verify(phone,'device',False,build_for_testing=True)
    def test_debug_mode_rejects_other_nested_tests_and_fixture_products(self):
        with tempfile.TemporaryDirectory() as root:
            phone,watch,bundle=self.simulator_host(Path(root))
            extra=watch/'PlugIns/Other.xctest';extra.mkdir(parents=True)
            with self.assertRaises(ValueError):verify(phone,'simulator',False,build_for_testing=True)
            extra.rmdir();fixture=phone/'PaletteFixtures.app';fixture.mkdir()
            with self.assertRaises(ValueError):verify(phone,'simulator',False,build_for_testing=True)
            fixture.rmdir();info=plistlib.loads((bundle/'Info.plist').read_bytes());info['CFBundleIdentifier']='unrelated'
            (bundle/'Info.plist').write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):verify(phone,'simulator',False,build_for_testing=True)
if __name__=='__main__':unittest.main()
