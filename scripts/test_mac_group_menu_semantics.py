"""Exact group/menu inverse delta against the admitted bridge; native behavior remains to verify."""
from pathlib import Path
import hashlib
import unittest
ROOT=Path(__file__).resolve().parents[1]
# Inverse-baseline UI hash remains admitted bridge 8c4034; PrivacyView additionally pins the root-admitted explicit type spellings.
# Camera/palette remain exact collector baseline; all original group/menu assertions are retained.
CHANGES = {'TouchColorMac/CameraSheet.swift': ('aedefc2617434530e882b26c9c369e4d2a5fc53ca68123008ebdac46d4e741af',
                                     [('        }.padding(20).frame(width: 560)\n'
                                       '            .onDisappear { camera.stop() }\n',
                                       '        }.padding(20).frame(width: 560)\n'
                                       '            .accessibilityElement(children: .contain)\n'
                                       '            .accessibilityLabel("Camera")\n'
                                       '            .accessibilityIdentifier("camera.content")\n'
                                       '            .onDisappear { camera.stop() }\n')]),
 'TouchColorMac/PrivacyView.swift': ('6d43689e9cd6fe21605aa77905b9386d08012b7d472918494753316c3bfea427',
                                     [('        }.padding(24).frame(width: 600, height: 540)\n    }\n',
                                       '        }.padding(24).frame(width: 600, height: 540)\n'
                                       '            .accessibilityElement(children: .contain)\n'
                                       '            .accessibilityLabel("Privacy Policy / 应用隐私政策")\n'
                                       '            .accessibilityIdentifier("privacy.content")\n'
                                       '    }\n')]),
 'TouchColorMac/PaletteSidebar.swift': ('0ad3b0cab70a6c2e9ac7b91cca6a94729447f669ac69fe54e0fcab96cde27b38',
                                        [('                        } label: { Label("Actions for color \\(index + 1)", '
                                          'systemImage: "ellipsis.circle").labelStyle(.iconOnly) }\n'
                                          '                            .menuStyle(.borderlessButton).frame(width: 24)\n'
                                          '                            .accessibilityLabel("Actions for color \\(index '
                                          '+ 1)")\n',
                                          '                        } label: { Label("Actions for color \\(index + 1)", '
                                          'systemImage: "ellipsis.circle").labelStyle(.iconOnly) }\n'
                                          '                            .menuStyle(.button).buttonStyle(.bordered)\n'
                                          '                            .accessibilityLabel("Actions for color \\(index '
                                          '+ 1)")\n')]),
 'TouchColorMacUITests/TouchColorMacUITests.swift': ('e7b3f7c2fbfdb4b6fcca3d2e863375fe9673f7278beb76b23197673a521e1267',
                                                     [('        '
                                                       'XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: '
                                                       '5))\n'
                                                       '        assertSelectablePrivacyParagraphs()\n'
                                                       '        app.buttons["privacy.close"].click()\n',
                                                       '        '
                                                       'XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: '
                                                       '5))\n'
                                                       '        let privacyContent = app.groups.matching(identifier: '
                                                       '"privacy.content")\n'
                                                       '        XCTAssertEqual(privacyContent.count, 1)\n'
                                                       '        XCTAssertEqual(privacyContent.element.label, "Privacy '
                                                       'Policy / 应用隐私政策")\n'
                                                       '        '
                                                       'XCTAssertTrue(privacyContent.element.buttons["privacy.close"].exists)\n'
                                                       '        '
                                                       'XCTAssertTrue(privacyContent.element.links["privacy.contact"].exists)\n'
                                                       '        assertSelectablePrivacyParagraphs()\n'
                                                       '        app.buttons["privacy.close"].click()\n'),
                                                      ('        waitForExpectations(timeout: 5)\n'
                                                       '        app.menuButtons["palette.actions.1"].click()\n'
                                                       '        app.menuItems["palette.delete.1"].click()\n',
                                                       '        waitForExpectations(timeout: 5)\n'
                                                       '        let actions = app.menuButtons["palette.actions.1"]\n'
                                                       '        XCTAssertTrue(actions.isEnabled); '
                                                       'XCTAssertTrue(actions.isHittable)\n'
                                                       '        NSPasteboard.general.clearContents()\n'
                                                       '        '
                                                       'XCTAssertTrue(NSPasteboard.general.setString("TouchColor '
                                                       'palette Copy regression sentinel", forType: .string))\n'
                                                       '        actions.click()\n'
                                                       '        let copy = app.menuItems["Copy Color"]\n'
                                                       '        XCTAssertTrue(copy.exists); '
                                                       'XCTAssertTrue(copy.isEnabled)\n'
                                                       '        copy.click()\n'
                                                       '        XCTAssertEqual(NSPasteboard.general.string(forType: '
                                                       '.string), "#ff00ff")\n'
                                                       '        XCTAssertEqual(app.staticTexts["palette.count"].value '
                                                       'as? String ?? app.staticTexts["palette.count"].label, "4")\n'
                                                       '        actions.click()\n'
                                                       '        app.menuItems["palette.delete.1"].click()\n'),
                                                      ('            XCTAssertTrue(status.waitForExistence(timeout: 5), '
                                                       'app.debugDescription)\n'
                                                       '            XCTAssertTrue((status.value as? String ?? '
                                                       'status.label).contains("No camera is available"))\n',
                                                       '            XCTAssertTrue(status.waitForExistence(timeout: 5), '
                                                       'app.debugDescription)\n'
                                                       '            let cameraContent = '
                                                       'app.groups.matching(identifier: "camera.content")\n'
                                                       '            XCTAssertEqual(cameraContent.count, 1)\n'
                                                       '            XCTAssertEqual(cameraContent.element.label, '
                                                       '"Camera")\n'
                                                       '            '
                                                       'XCTAssertTrue(cameraContent.element.buttons["camera.close"].exists)\n'
                                                       '            '
                                                       'XCTAssertTrue(cameraContent.element.buttons["camera.start"].exists)\n'
                                                       '            '
                                                       'XCTAssertTrue(cameraContent.element.staticTexts["camera.no-device"].exists)\n'
                                                       '            XCTAssertTrue((status.value as? String ?? '
                                                       'status.label).contains("No camera is available"))\n')])}

class GroupMenuSemantics(unittest.TestCase):
    def test_all_other_product_and_test_bytes_match_admitted_bridge_baseline(self):
        for path,(expected,edits) in CHANGES.items():
            source=(ROOT/path).read_text()
            for old,new in edits:
                self.assertEqual(source.count(new),1,path)
                source=source.replace(new,old,1)
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),expected,path)
    def test_named_groups_contain_children_without_hiding_or_combining(self):
        for path,label,identifier in [('CameraSheet.swift','Camera','camera.content'),('PrivacyView.swift','Privacy Policy / 应用隐私政策','privacy.content')]:
            text=(ROOT/'TouchColorMac'/path).read_text()
            self.assertIn('.accessibilityElement(children: .contain)',text)
            self.assertIn('.accessibilityLabel("'+label+'")',text)
            self.assertIn('.accessibilityIdentifier("'+identifier+'")',text)
            self.assertNotIn('children: .ignore',text);self.assertNotIn('children: .combine',text)
    def test_standard_menu_keeps_real_actions_and_localized_name(self):
        text=(ROOT/'TouchColorMac/PaletteSidebar.swift').read_text()
        self.assertIn('.menuStyle(.button).buttonStyle(.bordered)',text)
        self.assertNotIn('.menuStyle(.borderlessButton)',text)
        self.assertIn('Button("Copy Color") { library.copy(color) }',text)
        self.assertIn('Button("Delete Color", role: .destructive) { library.remove(at: index) }',text)
        self.assertIn(r'.accessibilityLabel("Actions for color \(index + 1)")',text)
        self.assertNotIn('.accessibilityAction',text)
    def test_existing_ui_cases_verify_containment_and_copy_without_count_change(self):
        ui=(ROOT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        for identifier,label in [('camera.content','Camera'),('privacy.content','Privacy Policy / 应用隐私政策')]:
            self.assertIn('app.groups.matching(identifier: "'+identifier+'")',ui)
            self.assertIn('.element.label, "'+label+'")',ui)
        for item in ['cameraContent.element.buttons["camera.close"].exists','cameraContent.element.buttons["camera.start"].exists',
            'cameraContent.element.staticTexts["camera.no-device"].exists','privacyContent.element.buttons["privacy.close"].exists',
            'privacyContent.element.links["privacy.contact"].exists','XCTAssertTrue(copy.exists); XCTAssertTrue(copy.isEnabled)',
            'XCTAssertEqual(NSPasteboard.general.string(forType: .string), "#ff00ff")']:
            self.assertIn(item,ui)
        section=ui.split('let actions = app.menuButtons["palette.actions.1"]',1)[1].split('app.buttons["image.export"]',1)[0]
        self.assertIn('"4")',section);self.assertIn('"3")',section)
        self.assertLess(section.index('copy.click()'),section.index('palette.delete.1'))
        self.assertLess(section.index('NSPasteboard.general.clearContents()'), section.index('actions.click()'))
        self.assertLess(section.index('NSPasteboard.general.setString("TouchColor palette Copy regression sentinel", forType: .string)'), section.index('actions.click()'))
        self.assertIn('XCTAssertTrue(NSPasteboard.general.setString("TouchColor palette Copy regression sentinel", forType: .string))', section)
    def test_policy_selectability_and_explicit_contact_route_are_preserved(self):
        policy=(ROOT/'TouchColorMac/PrivacyView.swift').read_text()
        self.assertIn('.textSelection(.enabled)',policy)
        self.assertEqual(policy.count('100mango@gmail.com'),4)
        self.assertIn('.accessibilityIdentifier("privacy.contact")',policy)
        # Root-admitted bridge supersedes the old blanket NSTextView prohibition.
        # Its precise selectable/plain-text contract replaces that single assertion.
        for required in ['struct SelectablePrivacyText: NSViewRepresentable', 'isEditable = false',
                         'isSelectable = true', 'isRichText = false', 'isAutomaticLinkDetectionEnabled = false',
                         'isAutomaticDataDetectionEnabled = false', 'enabledTextCheckingTypes = 0',
                         'container.widthTracksTextView = true',
                         'let storage = NSTextStorage(attributedString: liveStorage)']:
            self.assertIn(required, policy)
        self.assertNotIn('children: .ignore', policy)
        self.assertNotIn('children: .combine', policy)

if __name__=='__main__':unittest.main()
