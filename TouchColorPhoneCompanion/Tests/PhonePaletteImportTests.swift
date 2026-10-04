import XCTest
import UIKit
import UniformTypeIdentifiers
import ColorPaletteLegacy
@testable import TouchColor

/// Integrated UIKit review lifecycle and unsupported-companion behavior.
@MainActor final class PhonePaletteImportTests: XCTestCase {
    func testUnsupportedCompanionExplainsIndependentPaletteImport() throws {
        let suite = "TouchColor.inbox-unavailable.\(UUID())", defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let inbox = PhonePaletteInbox(defaults: defaults, domain: suite)
        guard !inbox.isSupported else { throw XCTSkip("Requires a device without WatchConnectivity support, such as iPad") }
        inbox.activate()
        XCTAssertEqual(inbox.status, NSLocalizedString("Watch transfer is unavailable on this device. You can import a palette using Files or Paste.", comment: "Unsupported companion"))
        XCTAssertTrue(try inbox.pending().isEmpty)
        XCTAssertNil(defaults.object(forKey: "colorArray"))
    }
    func testCancelledFileSelectionAndUnsupportedPasteRejectLatePriorRead() throws {
        let suite = "TouchColor.palette-review.\(UUID())", defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(["#123456", "#123456"], forKey: "colorArray")
        let controller = PhonePaletteImportController(defaults: defaults); controller.loadViewIfNeeded()
        let retained = try PaletteSelection(data: Data("[\"#abcdef\",\"#abcdef\"]".utf8))
        let first = controller.begin(); controller.apply(.success(retained), name: "first.json", token: first)
        let slow = controller.begin()
        controller.documentPickerWasCancelled(UIDocumentPickerViewController(forOpeningContentTypes: [.json]))
        let cancellation = controller.status
        let replacement = try PaletteSelection(data: Data("[\"#ff0000\"]".utf8))
        controller.apply(.success(replacement), name: "late.json", token: slow)
        XCTAssertEqual(controller.selection, retained); XCTAssertEqual(controller.status, cancellation)
        let anotherSlowRead = controller.begin()
        controller.paste(itemProviders: [])
        let pasteError = controller.status
        controller.apply(.success(replacement), name: "another-late.json", token: anotherSlowRead)
        XCTAssertEqual(controller.selection, retained); XCTAssertEqual(controller.status, pasteError)
        XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), ["#123456", "#123456"])
    }
}
