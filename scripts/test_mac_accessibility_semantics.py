"""Portable source contracts; AppKit/SwiftUI behavior still requires native tests."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTACT_LABEL = "Contact the developer about privacy"


def privacy_platform_source(mac: bool) -> str:
    """Project the shared file's closed, balanced macOS conditional blocks."""
    source = (ROOT / 'TouchColorMac/PrivacyView.swift').read_text()
    result, stack, active = [], [], True
    for line in source.splitlines(keepends=True):
        directive = line.strip()
        if directive == '#if os(macOS)':
            stack.append((active, False))
            active = active and mac
        elif directive == '#else':
            if not stack or stack[-1][1]: raise AssertionError('Unmatched or duplicate #else')
            parent, _ = stack[-1]
            stack[-1] = (parent, True)
            active = parent and not mac
        elif directive == '#endif':
            if not stack: raise AssertionError('Unmatched #endif')
            active, _ = stack.pop()
        elif directive.startswith('#'):
            raise AssertionError('Unexpected shared privacy compiler directive: ' + directive)
        elif active:
            result.append(line)
    if stack: raise AssertionError('Unclosed shared privacy compiler directive')
    return ''.join(result)


class MacAccessibilitySemanticsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = (ROOT / "TouchColorMac/ColorWindow.swift").read_text()
        cls.camera = (ROOT / "TouchColorMac/CameraSheet.swift").read_text()
        cls.privacy = privacy_platform_source(mac=True)
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
        # Reconstruct the approved source statements from unchanged paragraph literals.
        literals = re.findall(r'^    static let (?:simplifiedChinese|english) = (".*")$', self.privacy, re.M)
        statements = ['Text(' + literal + ')' for literal in literals]
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


class MacSelectablePrivacyTextContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.privacy = privacy_platform_source(mac=True)
        cls.native = (ROOT / 'TouchColorMacTests/PrivacyTextTests.swift').read_text()
        cls.ui = (ROOT / 'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()

    def test_only_two_approved_paragraphs_use_native_selectable_text_and_localized_keys(self):
        self.assertEqual(self.privacy.count('SelectablePrivacyText(text: NSLocalizedString(PrivacyPolicyCopy.'), 2)
        for member, identifier, label in [('simplifiedChinese', 'privacy.policy.zh-Hans', 'Privacy policy in Simplified Chinese'),
                                          ('english', 'privacy.policy.en', 'Privacy policy in English')]:
            self.assertIn('NSLocalizedString(PrivacyPolicyCopy.' + member + ', comment: "Approved offline privacy policy")', self.privacy)
            self.assertIn('identifier: "' + identifier + '", label: NSLocalizedString("' + label + '"', self.privacy)
        self.assertIn('.textSelection(.enabled)', self.privacy)
        self.assertNotIn('Text(verbatim:', self.privacy)
        self.assertEqual(self.privacy.count('.frame(maxWidth: .infinity, alignment: .leading)'), 2)

    def test_native_plain_text_disables_detectors_before_assigning_content(self):
        initial = self.privacy.split('init(text: String, identifier: String, label: String) {', 1)[1].split('required init?', 1)[0]
        for required in ['isEditable = false', 'isSelectable = true', 'isRichText = false',
                         'isAutomaticLinkDetectionEnabled = false', 'isAutomaticDataDetectionEnabled = false',
                         'enabledTextCheckingTypes = 0', 'drawsBackground = false', 'textContainerInset = .zero',
                         'container.lineFragmentPadding = 0', 'container.lineBreakMode = NSLineBreakMode.byWordWrapping',
                         'NSSize(width: CGFloat.zero, height: CGFloat.greatestFiniteMagnitude)',
                         'container.widthTracksTextView = true', 'container.heightTracksTextView = false',
                         'font = NSFont.preferredFont(forTextStyle: .body)', 'textColor = .labelColor']:
            self.assertIn(required, initial)
            self.assertLess(initial.index(required), initial.index('update(text: text'))
        self.assertIn('textStorage?.setAttributes([.font: NSFont.preferredFont(forTextStyle: .body),', self.privacy)
        self.assertIn('.foregroundColor: NSColor.labelColor]', self.privacy)
        for forbidden in ['.accessibilityHidden', 'children: .ignore', 'children: .combine', '.accessibilityAction',
                          'AXUIElement', 'makeFirstResponder', 'NSEvent', '.activate(', 'NSWorkspace']:
            self.assertNotIn(forbidden, self.privacy)

    def test_native_update_preserves_selected_range_when_string_does_not_change(self):
        update = self.privacy.split('func update(text: String, identifier: String, label: String) {', 1)[1].split('func measuredSize', 1)[0]
        self.assertEqual(update.count('string = text'), 1)
        self.assertLess(update.index('guard string != text else { return }'), update.index('string = text'))
        self.assertLess(update.index('guard string != text else { return }'), update.index('textStorage?.setAttributes'))
        self.assertNotIn('setSelectedRange', update)
        for required in ['for _ in 0..<3', 'XCTAssertEqual(view.selectedRange(), selection)',
                         'view.update(text: paragraphs[1]', 'try assertNoInlineLinks(view)']:
            self.assertIn(required, self.native)

    def test_sizing_uses_actual_wrapped_layout_for_finite_positive_proposed_width(self):
        self.assertIn('guard let width = proposal.width else { return nil }', self.privacy)
        self.assertIn('return nsView.measuredSize(width: width)', self.privacy)
        for required in ['guard width.isFinite, width > 0', 'let container = NSTextContainer(size: NSSize(width: width, height: CGFloat.greatestFiniteMagnitude))',
                         'manager.ensureLayout(for: container)', 'manager.usedRect(for: container).height',
                         'manager.defaultLineHeight(for: font)', 'guard height.isFinite, height > 0',
                         'return CGSize(width: width, height: height)']:
            self.assertIn(required, self.privacy)
        for required in ['let probes: [(CGFloat, CGFloat, CGFloat)] = [(280, 552, 280), (552, 280, 552),', 'manager.numberOfGlyphs',
                         'manager.characterRange(forGlyphRange: laidOut, actualGlyphRange: nil).length',
                         'XCTAssertGreaterThanOrEqual(try XCTUnwrap(heights[280]), try XCTUnwrap(heights[552]))', 'XCTAssertNil(view.measuredSize(width: width))']:
            self.assertIn(required, self.native)
        measurement = self.privacy.split('func measuredSize(width: CGFloat)', 1)[1]
        for required in ['let storage = NSTextStorage(attributedString: liveStorage)',
                         'container.lineFragmentPadding = liveContainer.lineFragmentPadding',
                         'container.lineBreakMode = liveContainer.lineBreakMode',
                         'storage.addLayoutManager(manager)', 'manager.addTextContainer(container)']:
            self.assertIn(required, measurement)
        for forbidden in ['liveContainer.size =', 'setFrameSize(', 'setBoundsSize(', 'string =', 'setSelectedRange(']:
            self.assertNotIn(forbidden, measurement)
        for required in ['XCTAssertEqual(container.size, before, "Speculative probes cannot mutate the live container")',
                         'let committed = committedWidth == firstWidth ? first : second',
                         'XCTAssertEqual(container.size.width, view.bounds.width)',
                         'XCTAssertLessThanOrEqual(manager.usedRect(for: container).maxY, view.bounds.height)',
                         'XCTAssertEqual(view.selectedRange(), selection)']:
            self.assertIn(required, self.native)

    def test_five_new_hosted_cases_are_in_project_and_no_native_ui_case_is_added(self):
        self.assertEqual(len(re.findall(r'func test\w+\(', self.native)), 5)
        project = (ROOT / 'TouchColorMac.xcodeproj/project.pbxproj').read_text()
        self.assertEqual(project.count('"path" = "TouchColorMacTests/PrivacyTextTests.swift";'), 1)
        self.assertIn("unitrefs=sources('TouchColorMacTests')", (ROOT / 'scripts/generate_mac_project.py').read_text())
        self.assertEqual(len(re.findall(r'func test\w+\(', self.ui)), 14)
        for forbidden in ['XCTSkip', 'app.launch(', 'performAccessibilityAudit', 'requestAccess']:
            self.assertNotIn(forbidden, self.native)

    def test_existing_privacy_flow_requires_complete_text_actual_copy_and_only_explicit_links(self):
        section = self.ui.split('private func assertSelectablePrivacyParagraphs()', 1)[1].split('private func makePhotosFixture', 1)[0]
        for required in ['app.textViews.matching(identifier: identifier)', 'XCTAssertEqual(texts.count, 1',
                         'XCTAssertEqual(paragraph.elementType, .textView)', 'XCTAssertEqual(paragraph.value as? String, expected)',
                         'XCTAssertEqual(app.links.count, 2', 'app.links.matching(identifier: "privacy.contact").count, 1',
                         'XCTAssertFalse(app.links.matching(identifier: "mailto:100mango@gmail.com").element.exists)',
                         'chinese.click()', 'chinese.typeKey("a", modifierFlags: [.command])',
                         'NSPasteboard.general.clearContents()', 'XCTAssertTrue(NSPasteboard.general.setString("TouchColor privacy Copy regression sentinel", forType: .string))',
                         'chinese.typeKey("c", modifierFlags: [.command])', 'NSPasteboard.general.string(forType: .string), paragraphs[0].2']:
            self.assertIn(required, section)
        self.assertLess(section.index('Copy regression sentinel'), section.index('chinese.typeKey("c"'))
        for forbidden in ['.links["privacy.contact"].click', 'app.launch', 'app.terminate']:
            self.assertNotIn(forbidden, section)
        self.assertEqual(self.ui.count('assertSelectablePrivacyParagraphs()'), 2)

    def test_paragraph_accessibility_labels_have_exact_bilingual_resources(self):
        expected = {'en': ['Privacy policy in Simplified Chinese', 'Privacy policy in English'],
                    'zh-Hans': ['简体中文隐私政策', '英文隐私政策']}
        for language, labels in expected.items():
            source = (ROOT / 'TouchColorMac' / (language + '.lproj') / 'Localizable.strings').read_text()
            entries = re.findall(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', source, re.M)
            self.assertEqual(len(entries), len(dict(entries)), language)
            for key, value in zip(expected['en'], labels): self.assertEqual(dict(entries).get(key), value)
        self.assertIn('NSLocalizedString(text, bundle: bundle, comment: ""), text', self.native)


class SharedPrivacyPlatformContracts(unittest.TestCase):
    def test_actual_project_source_membership_is_exactly_mac_and_vision(self):
        consumers = []
        shared_path = 'TouchColorMac/PrivacyView.swift'
        for project in sorted(ROOT.rglob('project.pbxproj')):
            raw = project.read_text()
            objects = dict(re.findall(r'^\t\t"([A-F0-9]{24})" = \{\n(.*?)^\t\t\};$', raw, re.M | re.S))
            def field(body, name):
                found = re.search(r'"' + name + r'" = (.*?);', body, re.S)
                return found.group(1) if found else ''
            refs = {key for key, body in objects.items() if field(body, 'isa') == '"PBXFileReference"'
                    and field(body, 'path') == json.dumps(shared_path)}
            if shared_path in raw: self.assertTrue(refs, 'Shared-file reference must use parsed project objects')
            if not refs: continue
            builds = {key for key, body in objects.items() if field(body, 'isa') == '"PBXBuildFile"'
                      and field(body, 'fileRef').strip('"') in refs}
            phases = {key: sum(item in builds for item in re.findall(r'"([A-F0-9]{24})"', field(body, 'files')))
                      for key, body in objects.items() if field(body, 'isa') == '"PBXSourcesBuildPhase"'}
            for _, body in objects.items():
                if field(body, 'isa') != '"PBXNativeTarget"': continue
                count = sum(phases.get(key, 0) for key in re.findall(r'"([A-F0-9]{24})"', field(body, 'buildPhases')))
                if count:
                    consumers.append((str(project.parent.relative_to(ROOT)), json.loads(field(body, 'name')), count))
        self.assertEqual(consumers, [('TouchColorMac.xcodeproj', 'TouchColorMac', 1),
                                     ('TouchColorVision.xcodeproj', 'TouchColorVision', 1)])
        vision = (ROOT / 'scripts/generate_vision_project.py').read_text()
        self.assertIn("'TouchColorMac/PrivacyView.swift'", vision)
        mac = (ROOT / 'scripts/generate_mac_project.py').read_text()
        self.assertIn("apprefs=sources('TouchColorMac')", mac)
        tv = (ROOT / 'TouchColorTV.xcodeproj/project.pbxproj').read_text()
        self.assertIn('"path" = "TouchColorTV/PrivacyView.swift";', tv)
        self.assertNotIn('"path" = "TouchColorMac/PrivacyView.swift";', tv)

    def test_mac_projection_pins_admitted_owned_sheet_marker_source(self):
        mac = privacy_platform_source(mac=True)
        self.assertEqual(hashlib.sha256(mac.encode()).hexdigest(), 'f55cad52bed4607831b219915bb08b6540dcf07eb089bd304c5570eb92d68ee1')
        for required in ['import AppKit', 'struct SelectablePrivacyText: NSViewRepresentable',
                         'isEditable = false', 'isSelectable = true', 'container.widthTracksTextView = true',
                         '.accessibilityElement(children: .contain)', '.accessibilityIdentifier("privacy.content")']:
            self.assertIn(required, mac)

    def test_non_mac_projection_is_exact_original_selectable_swiftui_policy(self):
        shared = privacy_platform_source(mac=False)
        self.assertEqual(hashlib.sha256(shared.encode()).hexdigest(), '08240fce405f34cad6a5ee2452934858ebc06dff01c3652d4439f61fa8ef915e')
        for forbidden in ['import AppKit', 'PrivacyPolicyCopy', 'SelectablePrivacyText', 'NSViewRepresentable',
                          'NSTextView', 'NSLayoutManager', 'privacy.content', '.accessibilityElement(children: .contain)']:
            self.assertNotIn(forbidden, shared)
        self.assertEqual(len([line for line in shared.splitlines() if line.strip().startswith('Text("Celluloid')]), 2)
        self.assertIn('.textSelection(.enabled)', shared)
        self.assertIn('Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)', shared)
        self.assertEqual(shared.count('Link('), 2)
        self.assertIn('.accessibilityIdentifier("privacy.contact")', shared)

    def test_all_mac_only_source_is_inside_closed_platform_guards(self):
        raw = (ROOT / 'TouchColorMac/PrivacyView.swift').read_text()
        self.assertEqual(raw.count('#if os(macOS)'), 4)
        self.assertEqual(raw.count('#else'), 1)
        self.assertEqual(raw.count('#endif'), 4)
        self.assertEqual(raw.count('import AppKit'), 1)
        self.assertNotIn('#if DEBUG', raw)
        self.assertNotIn('canImport(AppKit)', raw)
        # Both balanced projections must complete; unsupported directives fail closed.
        self.assertTrue(privacy_platform_source(mac=True))
        self.assertTrue(privacy_platform_source(mac=False))


class OwnedSheetDirectActionContracts(unittest.TestCase):
    def test_marker_uses_only_owned_content_view_label_and_identifier_setters(self):
        source = privacy_platform_source(mac=True)
        marker = source.split('struct OwnedSheetContentAccessibility: NSViewRepresentable', 1)[1]
        for required in ['guard let window, window.sheetParent != nil, let content = window.contentView',
                         'self !== content, isDescendant(of: content) else { return }', 'var presentationIdentifier: String',
                         'content.setAccessibilityLabel(label)', 'content.setAccessibilityIdentifier(presentationIdentifier)',
                         'viewDidMoveToWindow()', 'viewDidMoveToSuperview()', 'override func layout()']:
            self.assertIn(required, marker)
        for forbidden in ['setAccessibilityRole', 'setAccessibilityElement', 'setAccessibilityChildren',
                          'setAccessibilityEnabled', 'setAccessibilityHidden', 'accessibilityAction',
                          'AXUIElement', 'NSApp', 'Timer', 'DispatchQueue', 'makeFirstResponder', 'activate(',
                          'contentView =', 'setFrame', 'setBounds', 'beginSheet', 'orderFront', 'makeKey']:
            self.assertNotIn(forbidden, marker)
        camera = (ROOT / 'TouchColorMac/CameraSheet.swift').read_text()
        self.assertIn('identifier: "camera.presentation"', camera)
        self.assertIn('identifier: "privacy.presentation"', source)
        self.assertNotIn('OwnedSheetContentAccessibility', privacy_platform_source(mac=False))

    def test_existing_hosted_label_case_checks_real_sheet_and_main_window_preservation(self):
        native = (ROOT / 'TouchColorMacTests/PrivacyTextTests.swift').read_text()
        self.assertEqual(len(re.findall(r'func test\w+\(', native)), 5)
        self.assertIn('try assertOnlyOwnedSheetContentIsRelabeled()', native)
        for required in ['XCTAssertNil(parent.sheetParent)', 'parent.beginSheet(sheet, completionHandler: nil)',
                         'XCTAssertTrue(sheet.sheetParent === parent)', 'XCTAssertTrue(marker.isDescendant(of: content))',
                         'XCTAssertEqual(content.accessibilityRole(), role)', 'XCTAssertEqual(content.isAccessibilityElement(), element)',
                         'XCTAssertEqual(content.frame, frame)', 'XCTAssertEqual(content.bounds, bounds)',
                         'XCTAssertTrue(sheet.firstResponder === focus)', 'XCTAssertEqual(content.subviews.map(ObjectIdentifier.init), subviews)',
                         'XCTAssertEqual(button.action, action)', 'XCTAssertTrue(button.target === receiver)',
                         'XCTAssertEqual(receiver.count, 1)', 'XCTAssertEqual(receiver.count, 2)',
                         'XCTAssertFalse(outside.isDescendant(of: content))']:
            self.assertIn(required, native)

    def test_direct_palette_buttons_keep_model_actions_and_natural_control_dimensions(self):
        source = (ROOT / 'TouchColorMac/PaletteSidebar.swift').read_text()
        actions = source.split('VStack(spacing: 4)', 1)[1].split('}.padding(.vertical, 4)', 1)[0]
        for required in ['Button("Copy") { library.copy(color) }', 'Button("Delete", role: .destructive) { library.remove(at: index) }',
                         '.accessibilityLabel("Copy color', '.accessibilityLabel("Delete color',
                         'palette.copy.', 'palette.delete.', '.buttonStyle(.bordered)']:
            self.assertIn(required, actions)
        for forbidden in ['Menu {', '.frame(', '.font(', '.accessibilityAction', 'onTapGesture', 'Button {}']:
            self.assertNotIn(forbidden, actions)
        for language, values in [('en', ['Delete', 'Copy color %lld', 'Delete color %lld']),
                                 ('zh-Hans', ['删除', '复制第 %lld 个颜色', '删除第 %lld 个颜色'])]:
            resources = (ROOT / 'TouchColorMac' / (language + '.lproj') / 'Localizable.strings').read_text()
            for key, value in zip(['Delete', 'Copy color %lld', 'Delete color %lld'], values):
                self.assertIn('"' + key + '" = "' + value + '";', resources)

    def test_existing_ui_flows_check_bilingual_roles_reachability_and_real_copy_delete(self):
        ui = (ROOT / 'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        self.assertEqual(len(re.findall(r'func test\w+\(', ui)), 14)
        for required in ['copyLabel: "Copy color 2", deleteLabel: "Delete color 2"',
                         'copyLabel: "Copy color 4", deleteLabel: "Delete color 4"',
                         'copyLabel: "复制第 1 个颜色", deleteLabel: "删除第 1 个颜色"',
                         'XCTAssertEqual(button.elementType, .button)', 'XCTAssertEqual(button.label, label)',
                         'XCTAssertTrue(sidebar.frame.contains(button.frame)', 'XCTAssertTrue(button.isEnabled)',
                         'XCTAssertTrue(button.isHittable', 'TouchColor palette Copy regression sentinel',
                         'copy.click()', 'delete.click()', 'NSPasteboard.general.string(forType: .string), "#ff00ff"',
                         'assertOwnedSheetPresentation(identifier: "camera.presentation"',
                         'assertOwnedSheetPresentation(identifier: "privacy.presentation"']:
            self.assertIn(required, ui)
        self.assertNotIn('app.menuButtons["palette.actions.1"].click()', ui)
        self.assertNotIn('app.menuItems["palette.delete.1"].click()', ui)

    def test_did_finish_launch_emits_only_the_closed_scalar_in_the_debug_producer(self):
        app = (ROOT / 'TouchColorMac/TouchColorMacApp.swift').read_text()
        start = app.index('private final class MacPassiveLifecycle') if 'private final class MacPassiveLifecycle' in app else app.index('final class MacPassiveLifecycle')
        producer = app[start:]
        self.assertIn('note.userInfo?[NSApplication.launchIsDefaultUserInfoKey]', producer)
        self.assertEqual(producer.count('note.userInfo'), 1)
        self.assertIn('observed === own else { return }', producer)
        self.assertIn('if event == "didFinishLaunching"', producer)
        self.assertIn('CFGetTypeID(flag) == CFBooleanGetTypeID()', producer)
        for required in ['"missing"', '"reportedTrue"', '"reportedFalse"', '"unexpectedType"',
                         'if event == "didFinishLaunching", let launchIsDefault { row["launchIsDefault"] = launchIsDefault }']:
            self.assertIn(required, producer)
        self.assertNotIn('row["userInfo"]', producer)
        self.assertNotIn('String(describing: raw)', producer)


if __name__ == '__main__':
    unittest.main()
