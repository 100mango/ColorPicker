"""Portable source contracts; AppKit/SwiftUI behavior still requires native tests."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTACT_LABEL = "Contact the developer about privacy"


class MacAccessibilitySemanticsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = (ROOT / "TouchColorMac/CameraSheet.swift").read_text()
        cls.privacy = (ROOT / "TouchColorMac/PrivacyView.swift").read_text()
        cls.hosted = (ROOT / "TouchColorMacTests/CameraTests.swift").read_text()
        cls.ui = (ROOT / "TouchColorMacUITests/TouchColorMacUITests.swift").read_text()

    def test_workflow_runs_semantics_contracts_in_normal_and_optimized_prerequisites(self):
        workflow = (ROOT / ".github/workflows/apple-platforms.yml").read_text()
        prerequisite = workflow.split('      - name: Fail closed on setup regression failures', 1)[1].split(
            '      - name: Execute shared package tests', 1)[0]
        commands = [line.strip().split() for line in prerequisite.splitlines()
                    if line.strip().startswith(('python3 -m unittest ', 'python3 -O -m unittest '))]
        self.assertEqual(len(commands), 2)
        self.assertEqual(sum('-O' in command for command in commands), 1)
        for command in commands:
            self.assertEqual(command.count('test_mac_accessibility_semantics'), 1)

    def test_empty_camera_picker_keeps_existing_busy_guards_and_device_binding(self):
        picker = self.camera.split('Picker("Camera", selection: $camera.selectedDeviceID)', 1)[1].split(
            '.accessibilityIdentifier("camera.device")', 1)[0]
        self.assertIn('if camera.devices.isEmpty { Text("No camera").tag("") }', picker)
        self.assertIn('ForEach(camera.devices) { device in Text(device.name).tag(device.id) }', picker)
        self.assertIn('.disabled(camera.devices.isEmpty || camera.preparing || camera.running)', picker)

    def test_hosted_no_device_regression_observes_permission_requests_directly(self):
        test = self.hosted.split('func testNoDeviceNeverRequestsPermissionOrStartsCapture()', 1)[1].split(
            'func testAvailableSelectionSurvivesRefreshWithoutRequestingPermission()', 1)[0]
        for required in ('driver.available = []', 'driver.permission = .notDetermined',
                         'model.start(); model.start()', 'XCTAssertEqual(driver.permissionRequestCount, 0)',
                         'XCTAssertNil(driver.permissionReply)', 'XCTAssertTrue(driver.starts.isEmpty)',
                         'XCTAssertFalse(model.preparing)', 'XCTAssertFalse(model.running)'):
            self.assertIn(required, test)
        self.assertIn('permissionRequestCount += 1; permissionReply = completion', self.hosted)

    def test_hosted_available_selection_regression_preserves_selected_id(self):
        test = self.hosted.split('func testAvailableSelectionSurvivesRefreshWithoutRequestingPermission()', 1)[1].split(
            'func testPermissionCancelDeniedNoDeviceAndRepeatedStart()', 1)[0]
        self.assertIn('model.selectedDeviceID = second.id', test)
        self.assertIn('driver.available = [second, first]; model.refreshDevices()', test)
        self.assertIn('XCTAssertEqual(model.selectedDeviceID, second.id)', test)
        self.assertIn('XCTAssertEqual(driver.permissionRequestCount, 0)', test)

    def test_actual_empty_device_ui_checks_native_popup_on_repeated_presentations(self):
        test = self.ui.split('func testActualNoCameraRouteDismissesWithoutRequestingPermission()', 1)[1].split(
            'func testExplicitPrivacyContactHasLocalizedLinkSemanticsWithoutOpeningMail()', 1)[0]
        for required in ('for _ in 0..<2', 'let picker = app.popUpButtons["camera.device"]',
                         'XCTAssertTrue(picker.exists', 'XCTAssertFalse(picker.isEnabled',
                         'XCTAssertEqual(picker.value as? String, "No camera")',
                         'XCTAssertEqual(AVCaptureDevice.authorizationStatus(for: .video), permission)'):
            self.assertIn(required, test)
        self.assertNotIn('picker.click()', test)

    def test_contact_keeps_native_link_visible_address_and_exact_mailto(self):
        self.assertIn('Link("100mango@gmail.com", destination: URL(string: "mailto:100mango@gmail.com")!)\n'
                      '                        .accessibilityLabel("' + CONTACT_LABEL + '")\n'
                      '                        .accessibilityIdentifier("privacy.contact")', self.privacy)
        self.assertEqual(self.privacy.count('.accessibilityIdentifier("privacy.contact")'), 1)
        self.assertIn('Link("Published privacy policy", destination: URL(string: "https://100mango.github.io/app-privacy/")!)', self.privacy)
        self.assertNotIn('.onTapGesture', self.privacy)

    def test_approved_bilingual_policy_text_is_unchanged(self):
        # Fingerprints of the two approved Text statements in source tree a7bd322.
        statements = [line.strip() for line in self.privacy.splitlines()
                      if line.strip().startswith('Text("Celluloid')]
        self.assertEqual([hashlib.sha256(line.encode()).hexdigest() for line in statements], [
            '7297a918bc728a3870ece616c831952ef06d67787be8e3049f01cdc6150e7310',
            'e5f6f88f0908c01aabf80cee6892710ffd57deab41000ad2b04ca315143b9a3a'])

    def test_contact_accessibility_label_has_both_language_resources(self):
        for language, expected in [('en', CONTACT_LABEL), ('zh-Hans', '联系开发者咨询隐私问题')]:
            source = (ROOT / 'TouchColorMac' / (language + '.lproj') / 'Localizable.strings').read_text()
            entries = re.findall(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', source, re.M)
            self.assertEqual(len(entries), len(dict(entries)), language)
            self.assertEqual(dict(entries).get(CONTACT_LABEL), expected)

    def test_contact_ui_regression_checks_both_locales_without_dispatching_mail(self):
        test = self.ui.split('func testExplicitPrivacyContactHasLocalizedLinkSemanticsWithoutOpeningMail()', 1)[1].split(
            '@MainActor private func audit(', 1)[0]
        for required in ('("en", "en_US", "' + CONTACT_LABEL + '")',
                         '("zh-Hans", "zh_CN", "联系开发者咨询隐私问题")',
                         'app.links.matching(identifier: "privacy.contact")',
                         'XCTAssertEqual(contacts.count, 1', 'XCTAssertEqual(contact.elementType, .link)',
                         'XCTAssertEqual(contact.label, label)', 'XCTAssertTrue(contact.isEnabled',
                         'XCTAssertTrue(contact.isHittable'):
            self.assertIn(required, test)
        self.assertNotIn('contact.click()', test)
        self.assertNotIn('contact.tap()', test)


if __name__ == '__main__':
    unittest.main()
