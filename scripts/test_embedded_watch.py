import plistlib
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
if __name__=='__main__':unittest.main()
