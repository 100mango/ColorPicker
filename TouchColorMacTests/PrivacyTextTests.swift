import XCTest
import AppKit
@testable import TouchColorMac

@MainActor final class PrivacyTextTests: XCTestCase {
    private let paragraphs = [PrivacyPolicyCopy.simplifiedChinese, PrivacyPolicyCopy.english]
    private func paragraph(_ text: String) -> SelectablePrivacyText.ParagraphTextView {
        SelectablePrivacyText.ParagraphTextView(text: text, identifier: "privacy.text.test", label: "Privacy policy test")
    }
    private func assertNoInlineLinks(_ view: NSTextView) throws {
        let storage = try XCTUnwrap(view.textStorage)
        storage.enumerateAttribute(.link, in: NSRange(location: 0, length: storage.length)) { value, _, _ in
            XCTAssertNil(value, "The explicit contact Link must be the only email action")
        }
    }
    func testApprovedBilingualStringsAndReadOnlySelectablePlainTextFlags() throws {
        XCTAssertEqual(paragraphs, ["Celluloid、QRCatcher 和 TouchColor 在设备本地处理照片、相机画面、二维码或颜色数据，开发者不收集或上传这些数据。用户主动分享、打开链接，以及系统 iCloud 同步等行为由相应服务处理。如有隐私问题，请联系 100mango@gmail.com。本地数据可通过相应应用或系统删除，权限可在系统设置中撤回。", "Celluloid, QRCatcher, and TouchColor process photos, camera images, QR codes, or color data locally on your device. The developer does not collect or upload this data. Actions you choose to take, such as sharing or opening links, and system services such as iCloud sync are handled by the respective services. For privacy questions, contact 100mango@gmail.com. Local data can be deleted through the relevant app or system, and permissions can be revoked in system settings."])
        for text in paragraphs {
            let view = paragraph(text)
            XCTAssertEqual(view.string, text)
            XCTAssertFalse(view.isEditable); XCTAssertTrue(view.isSelectable)
            XCTAssertFalse(view.isRichText)
            XCTAssertFalse(view.isAutomaticLinkDetectionEnabled)
            XCTAssertFalse(view.isAutomaticDataDetectionEnabled)
            XCTAssertEqual(view.enabledTextCheckingTypes, 0)
            XCTAssertFalse(view.drawsBackground)
            XCTAssertEqual(view.font, NSFont.preferredFont(forTextStyle: .body))
            XCTAssertEqual(view.textColor, NSColor.labelColor)
            XCTAssertEqual(view.textContainerInset, .zero)
            XCTAssertEqual(view.textContainer?.lineFragmentPadding, 0)
            XCTAssertEqual(view.accessibilityIdentifier(), "privacy.text.test")
            XCTAssertEqual(view.accessibilityLabel(), "Privacy policy test")
            try assertNoInlineLinks(view)
        }
    }
    func testUnchangedUpdatesPreserveSelectionAndChangedTextStaysPlain() throws {
        let view = paragraph(paragraphs[0])
        let selection = NSRange(location: 10, length: 12)
        view.setSelectedRange(selection)
        for _ in 0..<3 {
            view.update(text: paragraphs[0], identifier: "privacy.text.test", label: "Updated paragraph label")
            XCTAssertEqual(view.selectedRange(), selection)
            XCTAssertEqual(view.string, paragraphs[0])
            try assertNoInlineLinks(view)
        }
        view.update(text: paragraphs[1], identifier: "privacy.text.test", label: "English paragraph")
        XCTAssertEqual(view.string, paragraphs[1])
        XCTAssertEqual(view.accessibilityLabel(), "English paragraph")
        try assertNoInlineLinks(view)
    }
    func testActualLayoutWrapsCompleteParagraphsAtRepresentativeWidths() throws {
        for text in paragraphs {
            let view = paragraph(text)
            let manager = try XCTUnwrap(view.layoutManager)
            let container = try XCTUnwrap(view.textContainer)
            let selection = NSRange(location: 10, length: 12)
            view.setSelectedRange(selection)
            var heights: [CGFloat: CGFloat] = [:]
            let probes: [(CGFloat, CGFloat, CGFloat)] = [(280, 552, 280), (552, 280, 552),
                                                         (280, 552, 552), (552, 280, 552), (280, 552, 280)]
            for (firstWidth, secondWidth, committedWidth) in probes {
                let before = container.size
                let first = try XCTUnwrap(view.measuredSize(width: firstWidth))
                let second = try XCTUnwrap(view.measuredSize(width: secondWidth))
                XCTAssertEqual(container.size, before, "Speculative probes cannot mutate the live container")
                XCTAssertEqual(view.selectedRange(), selection)
                XCTAssertEqual(view.string, text)
                let committed = committedWidth == firstWidth ? first : second
                // Includes choosing the earlier proposal and committing an unchanged frame size.
                view.setFrameSize(committed)
                manager.ensureLayout(for: container)
                XCTAssertEqual(committed.width, committedWidth)
                XCTAssertTrue(committed.height.isFinite); XCTAssertGreaterThan(committed.height, 0)
                XCTAssertEqual(container.size.width, view.bounds.width)
                XCTAssertEqual(container.size.width, committedWidth)
                XCTAssertLessThanOrEqual(manager.usedRect(for: container).maxX, view.bounds.width + 0.5)
                XCTAssertLessThanOrEqual(manager.usedRect(for: container).maxY, view.bounds.height)
                let laidOut = manager.glyphRange(for: container)
                XCTAssertEqual(laidOut.location, 0)
                XCTAssertEqual(laidOut.length, manager.numberOfGlyphs)
                XCTAssertEqual(manager.characterRange(forGlyphRange: laidOut, actualGlyphRange: nil).length, (text as NSString).length)
                XCTAssertEqual(view.selectedRange(), selection)
                XCTAssertEqual(view.string, text)
                heights[committedWidth] = committed.height
            }
            XCTAssertGreaterThanOrEqual(try XCTUnwrap(heights[280]), try XCTUnwrap(heights[552]))
            let before = container.size
            for width in [CGFloat.zero, -1, .infinity, -.infinity, .nan] {
                XCTAssertNil(view.measuredSize(width: width))
                XCTAssertEqual(container.size, before)
                XCTAssertEqual(view.selectedRange(), selection)
            }
        }
    }
    func testNormalAppKitSelectionAndCopyKeepCompleteBilingualText() {
        for text in paragraphs {
            let view = paragraph(text)
            NSPasteboard.general.clearContents()
            XCTAssertTrue(NSPasteboard.general.setString("TouchColor privacy Copy regression sentinel", forType: .string))
            view.selectAll(nil)
            XCTAssertEqual(view.selectedRange(), NSRange(location: 0, length: (text as NSString).length))
            view.copy(nil)
            XCTAssertEqual(NSPasteboard.general.string(forType: .string), text)
            XCTAssertEqual(view.string, text)
            XCTAssertFalse(view.isEditable)
        }
    }
    func testParagraphAccessibilityLabelsAreLocalizedWithoutChangingApprovedCopy() throws {
        let cases = [("en", "Privacy policy in Simplified Chinese", "Privacy policy in English"),
                     ("zh-Hans", "简体中文隐私政策", "英文隐私政策")]
        for (language, chineseLabel, englishLabel) in cases {
            let directory = try XCTUnwrap(Bundle.main.path(forResource: language, ofType: "lproj"))
            let bundle = try XCTUnwrap(Bundle(path: directory))
            XCTAssertEqual(NSLocalizedString("Privacy policy in Simplified Chinese", bundle: bundle, comment: ""), chineseLabel)
            XCTAssertEqual(NSLocalizedString("Privacy policy in English", bundle: bundle, comment: ""), englishLabel)
            for text in paragraphs { XCTAssertEqual(NSLocalizedString(text, bundle: bundle, comment: ""), text) }
        }
        try assertOnlyOwnedSheetContentIsRelabeled()
    }
    private func assertOnlyOwnedSheetContentIsRelabeled() throws {
        let parent = NSWindow(contentRect: NSRect(x: 120, y: 120, width: 400, height: 260),
                              styleMask: [.titled], backing: .buffered, defer: false)
        let main = NSView(frame: .zero)
        parent.contentView = main
        main.setAccessibilityLabel("Existing main content")
        main.setAccessibilityIdentifier("fixture.main")
        let mainMarker = OwnedSheetContentAccessibility.Marker(label: "Must not label main", identifier: "fixture.invalid-main")
        main.addSubview(mainMarker); mainMarker.labelOwnedSheet()
        XCTAssertNil(parent.sheetParent)
        XCTAssertEqual(main.accessibilityLabel(), "Existing main content")
        XCTAssertEqual(main.accessibilityIdentifier(), "fixture.main")

        let sheet = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 180),
                             styleMask: [.titled], backing: .buffered, defer: false)
        let content = NSView(frame: .zero)
        sheet.contentView = content
        content.setAccessibilityElement(true); content.setAccessibilityRole(.group)
        let receiver = SheetActionReceiver()
        let button = NSButton(title: "Real fixture action", target: receiver, action: #selector(SheetActionReceiver.pressed(_:)))
        button.frame = NSRect(x: 12, y: 12, width: 160, height: 30)
        content.addSubview(button)
        content.setAccessibilityChildren([button])
        let marker = OwnedSheetContentAccessibility.Marker(label: "Owned sheet content", identifier: "fixture.sheet")
        content.addSubview(marker)
        parent.orderFront(nil)
        parent.beginSheet(sheet, completionHandler: nil)
        defer {
            parent.endSheet(sheet); sheet.orderOut(nil); parent.orderOut(nil)
            sheet.contentView = nil; parent.contentView = nil
        }
        XCTAssertTrue(sheet.sheetParent === parent)
        XCTAssertTrue(marker.isDescendant(of: content))
        content.setAccessibilityLabel("Before owned label")
        content.setAccessibilityIdentifier("fixture.before")
        let role = content.accessibilityRole(), element = content.isAccessibilityElement()
        let frame = content.frame, bounds = content.bounds, focus = sheet.firstResponder
        let children = try XCTUnwrap(content.accessibilityChildren() as? [NSView]).map(ObjectIdentifier.init)
        let subviews = content.subviews.map(ObjectIdentifier.init)
        let buttonFrame = button.frame, action = button.action, enabled = button.isEnabled
        marker.labelOwnedSheet(); marker.labelOwnedSheet()
        XCTAssertEqual(content.accessibilityLabel(), "Owned sheet content")
        XCTAssertEqual(content.accessibilityIdentifier(), "fixture.sheet")
        XCTAssertEqual(content.accessibilityRole(), role); XCTAssertEqual(content.isAccessibilityElement(), element)
        XCTAssertEqual(content.frame, frame); XCTAssertEqual(content.bounds, bounds)
        XCTAssertTrue(sheet.firstResponder === focus)
        XCTAssertEqual(try XCTUnwrap(content.accessibilityChildren() as? [NSView]).map(ObjectIdentifier.init), children)
        XCTAssertEqual(content.subviews.map(ObjectIdentifier.init), subviews)
        XCTAssertEqual(button.frame, buttonFrame); XCTAssertEqual(button.action, action)
        XCTAssertEqual(button.isEnabled, enabled); XCTAssertTrue(button.target === receiver)
        button.performClick(nil); XCTAssertEqual(receiver.count, 1)
        marker.labelOwnedSheet()
        button.performClick(nil); XCTAssertEqual(receiver.count, 2)
        let chrome = try XCTUnwrap(content.superview)
        let outside = OwnedSheetContentAccessibility.Marker(label: "Must not label outside", identifier: "fixture.invalid-outside")
        chrome.addSubview(outside)
        XCTAssertTrue(outside.window === sheet); XCTAssertFalse(outside.isDescendant(of: content))
        outside.labelOwnedSheet()
        XCTAssertEqual(content.accessibilityLabel(), "Owned sheet content")
        XCTAssertEqual(content.accessibilityIdentifier(), "fixture.sheet")
        outside.removeFromSuperview()
    }
}

@MainActor private final class SheetActionReceiver: NSObject {
    var count = 0
    @objc func pressed(_ sender: NSButton) { count += 1 }
}
