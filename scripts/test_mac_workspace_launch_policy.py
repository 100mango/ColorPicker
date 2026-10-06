"""Source contract for an explicit launch policy, not native restoration proof."""
from pathlib import Path
import hashlib
import unittest
ROOT=Path(__file__).resolve().parents[1]
HELPER='/// Explicit primary-workspace launch intent; keep normal restoration and multiple windows.\nprivate extension Scene {\n    func workspaceDefaultLaunchPolicy() -> some Scene {\n        var scene = SceneBuilder.buildLimitedAvailability(self)\n        if #available(macOS 15.0, *) {\n            scene = SceneBuilder.buildLimitedAvailability(self.defaultLaunchBehavior(.presented))\n        }\n        return SceneBuilder.buildOptional(scene)\n    }\n}\n\n'
# Checkpoint-only successor; original projections are pinned in test_mac_scene_checkpoints.
BASE_HASH='85f4909d283a6b1c7b6a84a72ed2bf9bb6c8ad92ff3be3b747371780338ea3b7'

class WorkspaceLaunchPolicy(unittest.TestCase):
    def setUp(self):self.source=(ROOT/'TouchColorMac/TouchColorMacApp.swift').read_text()
    def test_existing_scene_content_identity_title_and_observation_bytes_preserved(self):
        restored=self.source.replace('        .workspaceDefaultLaunchPolicy()\n','',1).replace(HELPER,'',1)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),BASE_HASH)
        self.assertEqual(self.source.count('WindowGroup("TouchColor")'),1)
        self.assertEqual(self.source.count('Settings { PrivacyView() }'),1)
        self.assertLess(self.source.index('.workspaceDefaultLaunchPolicy()'),self.source.index('Settings { PrivacyView() }'))
    def test_private_availability_guard_retains_older_system_behavior(self):
        self.assertIn('private extension Scene',HELPER)
        self.assertIn('func workspaceDefaultLaunchPolicy() -> some Scene',HELPER)
        self.assertNotIn('@SceneBuilder', HELPER)
        self.assertIn('if #available(macOS 15.0, *)',HELPER)
        self.assertIn('var scene = SceneBuilder.buildLimitedAvailability(self)', HELPER)
        self.assertIn('scene = SceneBuilder.buildLimitedAvailability(self.defaultLaunchBehavior(.presented))', HELPER)
        self.assertEqual(HELPER.count('return '), 1)
        self.assertIn('return SceneBuilder.buildOptional(scene)', HELPER)
        self.assertNotIn('#unavailable', HELPER)
        self.assertNotIn('_LimitedAvailabilitySceneMarker', HELPER)
        self.assertNotIn('else', HELPER)
        self.assertLess(HELPER.index('var scene = '), HELPER.index('if #available'))
        self.assertLess(HELPER.index('if #available'), HELPER.index('return SceneBuilder.buildOptional'))
        self.assertNotIn('#if DEBUG',HELPER)
    def test_no_forced_activation_retry_or_restoration_mutation(self):
        for forbidden in ['NSApp','openWindow','activate(','.restorationBehavior','UserDefaults','Timer','DispatchQueue','while ','for ','removePersistentDomain','id:']:
            self.assertNotIn(forbidden,HELPER)
        self.assertEqual(self.source.count('.workspaceDefaultLaunchPolicy()'),1)
    def test_original_macos13_deployment_is_retained(self):
        generator=(ROOT/'scripts/generate_mac_project.py').read_text()
        self.assertIn("MACOSX_DEPLOYMENT_TARGET='13.0'",generator)
        self.assertNotIn("MACOSX_DEPLOYMENT_TARGET='15.0'",generator)
    def test_original_cold_locale_and_relaunch_controls_remain(self):
        ui=(ROOT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        self.assertIn('app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]',ui)
        self.assertIn('app.launchArguments += ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]',ui)
        self.assertIn('func testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail()',ui)
        self.assertIn('func testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail()',ui)
        self.assertIn('app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]',ui)
        self.assertIn('lifecycleRelaunchReceipt()',ui)

if __name__=='__main__':unittest.main()
