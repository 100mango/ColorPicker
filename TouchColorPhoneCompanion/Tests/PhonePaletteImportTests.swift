import XCTest
import UIKit
import UniformTypeIdentifiers
import ColorPaletteLegacy
@testable import TouchColor

/// Prepared for the integrated phone test target; not yet registered or executed.
@MainActor final class PhonePaletteImportTests: XCTestCase {
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
