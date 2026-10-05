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
        cls.window = (ROOT / "TouchColorMac/ColorWindow.swift").read_text()
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

    def test_selected_color_swatch_keeps_pixels_and_exposes_only_image_semantics(self):
        swatch = self.window.split('                if let color = session.selectedColor {', 1)[1].split(
            '                    VStack(alignment: .leading)', 1)[0]
        self.assertEqual(swatch.strip(), '\n'.join([
            'Color(red: Double(color.red) / 255, green: Double(color.green) / 255, blue: Double(color.blue) / 255)',
            '                        .frame(width: 38, height: 38).border(.gray.opacity(0.6))',
            '                        .accessibilityElement(children: .ignore)',
            '                        .accessibilityAddTraits(.isImage)',
            '                        .accessibilityLabel("Selected color")',
            '                        .accessibilityValue(Text(verbatim: "\\(color.hex), \\(color.rgbDescription)"))',
            '                        .accessibilityIdentifier("sample.swatch")']))
        self.assertEqual(self.window.count('.accessibilityIdentifier("sample.swatch")'), 1)
        for forbidden in ('.accessibilityHidden', '.accessibilityAction', 'Button(', '.onTapGesture', '.isButton'):
            self.assertNotIn(forbidden, swatch)

    def test_selected_color_label_is_localized_and_numeric_value_is_live_verbatim(self):
        for language, expected in [('en', 'Selected color'), ('zh-Hans', '所选颜色')]:
            source = (ROOT / 'TouchColorMac' / (language + '.lproj') / 'Localizable.strings').read_text()
            entries = re.findall(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', source, re.M)
            self.assertEqual(len(entries), len(dict(entries)), language)
            self.assertEqual(dict(entries).get('Selected color'), expected)
        self.assertIn('Text(color.hex).font(.title2.monospaced()).accessibilityIdentifier("sample.hex")', self.window)
        self.assertIn('Text(color.rgbDescription).font(.callout.monospacedDigit()).accessibilityIdentifier("sample.rgb")', self.window)
        self.assertIn('if let color = session.selectedColor {', self.window)
        self.assertIn('.accessibilityValue(Text(verbatim: "\\(color.hex), \\(color.rgbDescription)"))', self.window)

    def test_selected_color_checks_reuse_existing_sampling_cases_without_new_launches(self):
        setup = self.ui.split('override func setUpWithError()', 1)[1].split('override func tearDownWithError()', 1)[0]
        self.assertEqual(setup.count('app.launch()'), 1)
        self.assertNotIn('testSelectedColorSwatch', self.ui)
        self.assertNotIn('sample.swatch', setup)
        self.assertIn('app = XCUIApplication(url: applicationURL)', setup)
        english = self.ui.split('func testNativeFileSamplingZoomPalettePersistenceAndPrivacy()', 1)[1].split(
            'private func makePhotosFixture(', 1)[0]
        chinese = self.ui.split('func testSimplifiedChineseNativeSamplingFlowAndScreenshot()', 1)[1].split(
            'func testPasteImageAndOpenCancelRetainSource()', 1)[0]
        for case in (english, chinese):
            self.assertEqual(case.count('app.launch()'), 1)
            self.assertEqual(case.count('app.terminate()'), 1)
        self.assertIn('app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]', chinese)

    def test_selected_color_ui_requires_unique_image_exact_label_value_and_size(self):
        check = self.ui.split('private func assertSelectedColorSwatch(label: String, hex: String, rgb: String)', 1)[1].split(
            'func testNativeFileSamplingZoomPalettePersistenceAndPrivacy()', 1)[0]
        for required in ('app.images.matching(identifier: "sample.swatch")',
                         'swatch.waitForExistence(timeout: 5)', 'XCTAssertEqual(swatches.count, 1)',
                         'XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "sample.swatch").count, 1)',
                         'XCTAssertEqual(swatch.elementType, .image)', 'XCTAssertEqual(swatch.label, label)',
                         'let expected = "\\(hex), \\(rgb)"', 'NSPredicate(format: "value == %@", expected)',
                         'XCTWaiter.wait(for: [updated], timeout: 5)', 'XCTAssertEqual(swatch.value as? String, expected)',
                         'XCTAssertEqual(swatch.frame.width, 38, accuracy: 0.5)',
                         'XCTAssertEqual(swatch.frame.height, 38, accuracy: 0.5)',
                         'app.staticTexts["sample.rgb"]', 'XCTAssertEqual(visibleRGB.value as? String ?? visibleRGB.label, rgb)'):
            self.assertIn(required, check)
        self.assertNotIn('swatch.click()', check)
        self.assertNotIn('swatch.tap()', check)

    def test_selected_color_ui_follows_existing_pointer_keyboard_and_chinese_changes(self):
        english = self.ui.split('func testNativeFileSamplingZoomPalettePersistenceAndPrivacy()', 1)[1].split(
            'private func makePhotosFixture(', 1)[0]
        chinese = self.ui.split('func testSimplifiedChineseNativeSamplingFlowAndScreenshot()', 1)[1].split(
            'func testPasteImageAndOpenCancelRetainSource()', 1)[0]
        self.assertIn('XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sample.swatch").element.exists)', english)
        pattern = r'assertSelectedColorSwatch\(label: "([^"]+)", hex: "([^"]+)", rgb: "([^"]+)"\)'
        self.assertEqual(re.findall(pattern, english), [
            ('Selected color', '#ff00ff', 'R 255   G 0   B 255'), ('Selected color', '#ff0000', 'R 255   G 0   B 0'),
            ('Selected color', '#00ff00', 'R 0   G 255   B 0'), ('Selected color', '#ff0000', 'R 255   G 0   B 0'),
            ('Selected color', '#ff00ff', 'R 255   G 0   B 255'), ('Selected color', '#ff00ff', 'R 255   G 0   B 255')])
        self.assertEqual(re.findall(pattern, chinese), [
            ('所选颜色', '#ff00ff', 'R 255   G 0   B 255'), ('所选颜色', '#00ff00', 'R 0   G 255   B 0')])
        for required in ('openFile(fixture)', 'app.images["image.canvas"]',
                         'canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click()',
                         'app.typeKey(.rightArrow, modifierFlags: [])', 'app.typeKey(.leftArrow, modifierFlags: [])',
                         'app.buttons["sample.copy"].click()', 'app.buttons["sample.save"].click()',
                         'app.buttons["sample.center"].click()'):
            self.assertIn(required, english)
        self.assertIn('app.buttons["image.paste"].click(); assertHex("#ff00ff")', chinese)
        self.assertIn('app.buttons["sample.above"].click(); assertHex("#00ff00")', chinese)
        for case in (english, chinese):
            for forbidden in ('swatch.click()', 'swatch.tap()', 'XCTSkip', 'selectedColor ='):
                self.assertNotIn(forbidden, case)

    def test_empty_camera_is_static_status_and_nonempty_picker_keeps_busy_guards_and_binding(self):
        selection = self.camera.split('            if camera.devices.isEmpty {', 1)[1].split(
            '            Text(camera.status)', 1)[0]
        empty, available = selection.split('            } else {', 1)
        self.assertIn('Text("No camera").accessibilityIdentifier("camera.no-device")', empty)
        for forbidden in ('Picker(', 'Button(', '.tag(', '.onTapGesture', '.accessibilityAction'):
            self.assertNotIn(forbidden, empty)
        self.assertIn('Picker("Camera", selection: $camera.selectedDeviceID)', available)
        self.assertIn('ForEach(camera.devices) { device in Text(device.name).tag(device.id) }', available)
        self.assertIn('.disabled(camera.preparing || camera.running).accessibilityIdentifier("camera.device")', available)
        self.assertNotIn('Text("No camera")', available)
        self.assertEqual(self.camera.count('Picker('), 1)

    def test_empty_camera_status_is_localized_and_keeps_start_and_dismiss_guards(self):
        for language, expected in [('en', 'No camera'), ('zh-Hans', '无可用相机')]:
            source = (ROOT / 'TouchColorMac' / (language + '.lproj') / 'Localizable.strings').read_text()
            entries = re.findall(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', source, re.M)
            self.assertEqual(len(entries), len(dict(entries)), language)
            self.assertEqual(dict(entries).get('No camera'), expected)
        self.assertIn('Button("Start Camera") { camera.start() }', self.camera)
        self.assertIn('.disabled(camera.running || camera.preparing || camera.devices.isEmpty).accessibilityIdentifier("camera.start")', self.camera)
        self.assertIn('Button("Done") { camera.stop(); dismiss() }', self.camera)
        self.assertIn('.onDisappear { camera.stop() }', self.camera)

    def test_hosted_no_device_regression_observes_permission_requests_directly(self):
        test = self.hosted.split('func testNoDeviceNeverRequestsPermissionOrStartsCapture()', 1)[1].split(
            'func testAvailableSelectionSurvivesRefreshWithoutRequestingPermission()', 1)[0]
        for required in ('driver.available = []', 'driver.permission = .notDetermined',
                         'model.start(); model.start()', 'XCTAssertEqual(driver.permissionRequestCount, 0)',
                         'XCTAssertNil(driver.permissionReply)', 'XCTAssertTrue(driver.starts.isEmpty)',
                         'XCTAssertFalse(model.preparing)', 'XCTAssertFalse(model.running)',
                         'NSLocalizedString("No camera is available. Connect a camera, or import an image instead."'):
            self.assertIn(required, test)
        self.assertEqual(test.count('XCTAssertEqual(model.status, unavailable)'), 2)
        self.assertEqual(test.count('XCTAssertTrue(model.devices.isEmpty); XCTAssertEqual(model.selectedDeviceID, "")'), 2)
        self.assertIn('permissionRequestCount += 1; permissionReply = completion', self.hosted)

    def test_hosted_available_selection_regression_preserves_selected_id(self):
        test = self.hosted.split('func testAvailableSelectionSurvivesRefreshWithoutRequestingPermission()', 1)[1].split(
            'func testPermissionCancelDeniedNoDeviceAndRepeatedStart()', 1)[0]
        self.assertIn('model.selectedDeviceID = second.id', test)
        self.assertIn('driver.available = [second, first]; model.refreshDevices()', test)
        self.assertIn('XCTAssertEqual(model.selectedDeviceID, second.id)', test)
        self.assertIn('XCTAssertEqual(driver.permissionRequestCount, 0)', test)
        self.assertIn('driver.available = []; model.refreshDevices()', test)
        self.assertIn('XCTAssertTrue(model.devices.isEmpty); XCTAssertEqual(model.selectedDeviceID, "")', test)
        self.assertIn('driver.available = [first, second]; model.refreshDevices()', test)
        self.assertIn('XCTAssertEqual(model.devices.map(\\.id), [first.id, second.id])', test)

    def test_actual_empty_device_ui_checks_static_status_on_repeated_presentations(self):
        test = self.ui.split('func testActualNoCameraRouteDismissesWithoutRequestingPermission()', 1)[1].split(
            'func testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail()', 1)[0]
        for required in ('for _ in 0..<2', 'let unavailable = app.staticTexts["camera.no-device"]',
                         'XCTAssertTrue(unavailable.exists',
                         'XCTAssertEqual(unavailable.elementType, .staticText)',
                         'XCTAssertEqual(unavailable.value as? String ?? unavailable.label, "No camera")',
                         'XCTAssertFalse(app.popUpButtons["camera.device"].exists',
                         'XCTAssertFalse(app.buttons["camera.start"].isEnabled)',
                         'XCTAssertFalse(app.buttons["camera.freeze"].isEnabled)',
                         'XCTAssertFalse(app.buttons["camera.save"].isEnabled)',
                         'app.buttons["camera.close"].click()',
                         'XCTAssertEqual(AVCaptureDevice.authorizationStatus(for: .video), permission)',
                         'app.buttons["image.paste"].click(); assertHex("#ff00ff")'):
            self.assertIn(required, test)
        self.assertNotIn('unavailable.click()', test)
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

    def test_contact_locales_are_independent_cases_selected_before_single_exact_product_launch(self):
        setup = self.ui.split('override func setUpWithError()', 1)[1].split('override func tearDownWithError()', 1)[0]
        cases = [('English', 'en', 'en_US', CONTACT_LABEL),
                 ('SimplifiedChinese', 'zh-Hans', 'zh_CN', '联系开发者咨询隐私问题')]
        self.assertEqual(setup.count('app.launch()'), 1)
        self.assertIn('app = XCUIApplication(url: applicationURL)', setup)
        self.assertIn('app.launchArguments = ["--ui-test-reset"]', setup)
        self.assertIn('XCTAssertEqual(actual.bundleURL?.resolvingSymlinksInPath(), applicationURL.resolvingSymlinksInPath())', setup)
        self.assertIn('NATIVE_UI_LOGIC_SHA256:', setup)
        for suffix, language, locale, label in cases:
            name = 'testExplicitPrivacyContactHas' + suffix + 'LinkSemanticsWithoutOpeningMail'
            dispatch = 'name.contains("' + name + '")'
            arguments = 'app.launchArguments += ["-AppleLanguages", "(' + language + ')", "-AppleLocale", "' + locale + '"]'
            self.assertIn(dispatch, setup)
            branch = setup.split(dispatch + ' {', 1)[1].split('}', 1)[0]
            self.assertIn(arguments, branch)
            self.assertLess(setup.index(arguments), setup.index('app.launch()'))
            case = self.ui.split('func ' + name + '()', 1)[1].split('\n    }', 1)[0]
            self.assertIn('assertPrivacyContact(label: "' + label + '")', case)
            self.assertNotIn('app.launch', case)
            self.assertNotIn('app.terminate', case)
        methods = re.findall(r'func (testExplicitPrivacyContact\w+)\(', self.ui)
        self.assertEqual(len(methods), 2)

    def test_contact_ui_regression_keeps_semantics_and_timeouts_without_relaunch_or_mail(self):
        test = self.ui.split('private func assertPrivacyContact(label: String)', 1)[1].split(
            '@MainActor private func audit(', 1)[0]
        for required in ('app.buttons["privacy.open"].waitForExistence(timeout: 10)',
                         'app.buttons["privacy.close"].waitForExistence(timeout: 5)',
                         'app.links.matching(identifier: "privacy.contact")',
                         'XCTAssertEqual(contacts.count, 1', 'XCTAssertEqual(contact.elementType, .link)',
                         'XCTAssertEqual(contact.label, label)', 'XCTAssertTrue(contact.isEnabled',
                         'XCTAssertTrue(contact.isHittable', 'app.buttons["privacy.close"].click()',
                         'app.buttons["image.open.empty"].waitForExistence(timeout: 5)'):
            self.assertIn(required, test)
        for forbidden in ('contact.click()', 'contact.tap()', 'app.launch', 'app.terminate', 'for '):
            self.assertNotIn(forbidden, test)


if __name__ == '__main__':
    unittest.main()
