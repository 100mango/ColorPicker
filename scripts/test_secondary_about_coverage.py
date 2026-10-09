"""Test-only native About coverage contracts; these do not claim Apple execution."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = {p: f'TouchColor{p}UITests/' + ('TouchColorMacUITests.swift' if p == 'Mac' else p + 'WorkflowTests.swift')
         for p in ('Mac', 'TV', 'Watch', 'Vision')}
def source(platform): return (ROOT / FILES[platform]).read_text()
def method(text, name):
    found = re.search(r'^    [^\n]*func ' + re.escape(name) + r'\([^\n]*\{', text, re.M)
    if not found: raise ValueError('Missing method ' + name)
    tail = re.search(r'^    }$', text[found.end():], re.M)
    if not tail: raise ValueError('Missing method boundary ' + name)
    return text[found.start():found.end() + tail.end()]


class SecondaryAboutCoverageTests(unittest.TestCase):
    def test_mac_uses_real_settings_keyboard_escape_and_no_workspace_routes(self):
        body = method(source('Mac'), 'assertSecondaryMacSettingsAndEscape')
        self.assertEqual(body.count('app.typeKey(",", modifierFlags: [.command])'), 2)
        self.assertEqual(body.count('app.typeKey(.escape, modifierFlags: [])'), 3)
        self.assertIn('workspace.waitForNonExistence(timeout: 5)', body)
        self.assertIn('if locale == "en"', body)
        self.assertIn('XCTAssertEqual(settings.count, 1)', body)
        self.assertIn('XCTAssertFalse(settings.element.buttons["about.close"].exists)', body)
        self.assertIn('captureSecondaryMac("Privacy " + locale + " settings")', body)
        for bad in ('activate(', 'perform(', 'openSettings(', 'launch()', 'terminate()'):
            self.assertNotIn(bad, body)

    def test_mac_modal_menu_never_directly_dispatches_disabled_action(self):
        text = source('Mac'); helper = method(text, 'assertAboutMenuDisabledWhileModalOwnsPresentation')
        self.assertIn('XCTAssertFalse(about.isEnabled', helper)
        self.assertNotIn('about.click()', helper)
        self.assertIn('app.typeKey(.escape, modifierFlags: [])', helper)
        for name, modal_close in [('testOfficialAccessibilityCameraAndPrivacy', 'app.buttons["camera.close"].click()'),
                                 ('testOfficialAccessibilityCorruptImportRetainsPreviousSource', 'dismiss.click()')]:
            body = method(text, name)
            self.assertLess(body.index('assertAboutMenuDisabledWhileModalOwnsPresentation()'), body.index(modal_close))
            self.assertIn('must not reveal a queued About sheet', body)
            self.assertIn('finishRetainedAudits', body)

    def test_mac_about_and_privacy_owners_keep_disabled_menu_and_underlying_sheet(self):
        text = source('Mac')
        helper = method(text, 'assertAboutMenuDisabledWhileModalOwnsPresentation')
        self.assertIn('expectedAboutVisible: Bool = false, expectedPrivacyVisible: Bool = false', helper)
        self.assertIn('XCTAssertEqual(app.buttons["about.close"].exists, expectedAboutVisible)', helper)
        self.assertIn('XCTAssertEqual(app.buttons["privacy.close"].exists, expectedPrivacyVisible)', helper)
        body = method(text, 'assertSecondaryMacSettingsAndEscape')
        self.assertIn('assertAboutMenuDisabledWhileModalOwnsPresentation(expectedAboutVisible: true)', body)
        self.assertIn('assertAboutMenuDisabledWhileModalOwnsPresentation(expectedPrivacyVisible: true)', body)
        self.assertLess(body.index('expectedPrivacyVisible: true'), body.index('app.typeKey(.escape, modifierFlags: [])'))

    def test_watch_chinese_helper_keeps_fallback_editor_metrics_before_about(self):
        text = source('Watch'); helper = method(text, 'performChineseColorEditorSave')
        self.assertIn('app.buttons["watch.save"].tap()', helper)
        self.assertIn('Native Watch Chinese color editor', helper)
        self.assertNotIn('BackButton', helper); self.assertNotIn('Secondary', helper)
        ordinary = method(text, 'testChineseColorEditorSave')
        self.assertLess(ordinary.index('performChineseColorEditorSave()'), ordinary.index('BackButton'))
        fallback = method(text, 'testPublicLargestTraitChineseColorEditorSave')
        self.assertIn('performChineseColorEditorSave()', fallback)
        self.assertNotIn('testChineseColorEditorSave()', fallback)
        self.assertLess(fallback.index('performChineseColorEditorSave()'), fallback.index('let largest = try metric(true)'))
        self.assertLess(fallback.index('XCTAssertGreaterThan(largest, baseline)'), fallback.index('try assertSecondaryWatchPrivacyFromHome'))
        self.assertIn('systemPropagation=unverified', fallback)

    def test_mac_normal_captures_and_original_audit_states_stay_distinct(self):
        text = source('Mac'); capture = method(text, 'captureSecondaryMac')
        self.assertIn('guard !expectsSandbox else { return }', capture)
        self.assertIn('XCTAttachment(screenshot: app.screenshot())', capture)
        self.assertIn('.keepAlways', capture)
        contact = method(text, 'assertPrivacyContact')
        self.assertIn('captureSecondaryMac("About " + locale + " app-menu")', contact)
        self.assertIn('try audit("secondary About " + locale + " app-menu")', contact)
        self.assertIn('try assertSecondaryMacSettingsAndEscape(locale: locale, contactLabel: label)', contact)
        audit = method(text, 'audit')
        self.assertIn('let requestedStates = ["empty workspace", "full image and palette", "camera availability", "offline privacy", "corrupt import error"]', audit)
        self.assertNotIn('secondary About', audit)

    def test_tv_real_remote_routes_and_cold_primary_focus_remain(self):
        text = source('TV'); body = method(text, 'testRemoteColorEditorAndMenuReturn')
        self.assertIn('self.app.buttons["tv.photos"].hasFocus || self.app.buttons["tv.editor"].hasFocus', body)
        self.assertIn('XCTWaiter.wait(for: [primaryFocus], timeout: 5)', body)
        self.assertIn('context: "empty"', body); self.assertIn('context: "populated"', body)
        route = method(text, 'assertSecondaryPrivacyAndRemoteReturn')
        self.assertEqual(route.count('remote.press(.menu)'), 2)
        self.assertIn('select(app.buttons["privacy.close"])', route)
        self.assertIn('select(app.buttons["about.close"])', route)
        self.assertNotIn('.tap()', route)
        chinese = method(text, 'testChineseRemoteColorEditor')
        self.assertIn('context: "zh-normal"', chinese)
        self.assertIn('context: "zh-public-largest"', chinese)
        self.assertIn('systemPropagation=unverified', chinese)

    def test_swift_audit_calls_are_in_main_actor_methods(self):
        cases = [('TV', 'assertSecondaryPrivacyAndRemoteReturn'), ('TV', 'testRemoteColorEditorAndMenuReturn'),
                 ('Vision', 'assertSecondaryVisionPrivacy'), ('Vision', 'testChinesePasteAndPrecisionControls'),
                 ('Watch', 'recordSecondaryWatchAboutAudit'), ('Watch', 'assertSecondaryWatchPrivacyFromHome'),
                 ('Watch', 'testChineseColorEditorSave')]
        for platform, name in cases:
            with self.subTest(platform=platform, method=name):
                self.assertIn('@MainActor', method(source(platform), name).split('\n', 1)[0])
                self.assertIn('throws {', method(source(platform), name).split('\n', 1)[0])

    def test_audit_receipts_follow_actual_audit_and_unchanged_failure_count(self):
        cases = [('TV', 'assertSecondaryPrivacyAndRemoteReturn'), ('Vision', 'assertSecondaryVisionPrivacy'),
                 ('Watch', 'recordSecondaryWatchAboutAudit')]
        for platform, name in cases:
            with self.subTest(platform=platform):
                body = method(source(platform), name)
                audit = body.index('try audit("secondary About " + context)')
                condition = body.index('if (testRun?.totalFailureCount ?? 0) == failures')
                receipt = body.index('"outcome": "passed"')
                self.assertLess(body.index('let failures = testRun?.totalFailureCount ?? 0'), audit)
                self.assertLess(audit, condition); self.assertLess(condition, receipt)
                self.assertIn('"schema": 1', body); self.assertIn('"testName": name', body)
                self.assertIn('"imageName": "Native ' + platform + ' secondary About " + context', body)
                self.assertIn('XCTAssertLessThanOrEqual(data.count, 8192)', body)
                self.assertIn('receipt.lifetime = .keepAlways', body)
                self.assertNotIn('catch', body)
                self.assertNotIn('try?', body)

    def test_vision_extends_existing_chinese_and_audit_rows_without_new_launches(self):
        text = source('Vision')
        for name, context in [('testChinesePasteAndPrecisionControls', 'zh'),
                              ('testOfficialAccessibilityEmptyAndPastedCanvas', 'audit')]:
            body = method(text, name)
            self.assertIn('try assertSecondaryVisionPrivacy(context: "' + context, body)
            self.assertNotIn('app.launch', body)
        route = method(text, 'assertSecondaryVisionPrivacy')
        self.assertIn('chinese ? "关于" : "About"', route)
        self.assertIn('chinese ? "隐私" : "Privacy"', route)
        self.assertIn('app.frame.contains(heading.frame)', route)
        self.assertIn('capture("Native Vision secondary Privacy " + context)', route)
        self.assertNotIn('setenv(', route)

    def test_watch_cold_home_crown_bound_and_two_back_cycles_are_preserved(self):
        text = source('Watch'); cold = method(text, 'testHomeListDigitalCrownFromColdLaunch')
        self.assertIn('XCTAssertFalse(target.exists && target.isHittable', cold)
        self.assertIn('for attempt in 0..<12', cold)
        self.assertIn('rotateDigitalCrown(delta: -0.1)', cold)
        self.assertIn('for iteration in 0..<2', cold)
        self.assertIn('if iteration == 0 { captureSecondaryWatch("Privacy cold") }', cold)
        self.assertNotIn('swipe', cold)
        self.assertIn('try recordSecondaryWatchAboutAudit("cold")', cold)
        for name, context in [('testChineseColorEditorSave', 'zh'),
                              ('testOfficialAccessibilityHomeAndColorEditor', 'audit'),
                              ('testPublicLargestTraitChineseColorEditorSave', 'zh-public-largest')]:
            body = method(text, name)
            self.assertIn('try assertSecondaryWatchPrivacyFromHome(context: "' + context, body)
            self.assertIn('assertSecondaryWatchSavedCount("1")', body)

    def test_new_about_flows_never_launch_links_change_permissions_or_add_skips(self):
        helpers = [('Mac', 'assertSecondaryMacSettingsAndEscape'), ('Mac', 'captureSecondaryMac'),
                   ('TV', 'assertSecondaryPrivacyAndRemoteReturn'), ('Vision', 'assertSecondaryVisionPrivacy'),
                   ('Watch', 'assertSecondaryWatchPrivacyFromHome')]
        for platform, name in helpers:
            body = method(source(platform), name)
            for forbidden in ('XCTSkip', 'XCTExpectFailure', 'executionTimeAllowance', 'resetAuthorizationStatus',
                              'privacy.contact"].click()', 'privacy.contact"].tap()', 'openURL', 'UIApplication.shared'):
                self.assertNotIn(forbidden, body)


if __name__ == '__main__': unittest.main()
