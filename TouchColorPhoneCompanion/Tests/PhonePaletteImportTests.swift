import XCTest
import UIKit
import UniformTypeIdentifiers
import ColorPaletteLegacy
@testable import TouchColor

/// Integrated UIKit review lifecycle and unsupported-companion behavior.
@MainActor final class PhonePaletteImportTests: XCTestCase {
    func testActualCloseBarActionDismissesFullScreenErrorAndRejectsLateResult() async throws {
        let suite = "TouchColor.close-action.\(UUID())", defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let original = ["#123456", "#123456"]
        defaults.set(original, forKey: "colorArray")
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive })
        let oldKeyWindow = scene.windows.first { $0.isKeyWindow }
        let owner = UIViewController(), window = UIWindow(windowScene: scene)
        window.rootViewController = owner; window.makeKeyAndVisible()
        defer { window.isHidden = true; window.rootViewController = nil; oldKeyWindow?.makeKey() }
        let content = PhonePaletteImportController(defaults: defaults)
        let navigation = UINavigationController(rootViewController: content); navigation.modalPresentationStyle = .fullScreen
        let presented = expectation(description: "Actual full-screen UIKit import host appeared")
        owner.present(navigation, animated: false) { presented.fulfill() }
        await fulfillment(of: [presented], timeout: 3)
        XCTAssertTrue(window.isKeyWindow)
        XCTAssertTrue(window.windowScene === scene)
        XCTAssertTrue(owner.presentedViewController === navigation)
        XCTAssertTrue(navigation.presentingViewController === owner)
        XCTAssertTrue(navigation.topViewController === content)
        XCTAssertTrue(content.view.window === window)
        let token = content.begin()
        content.apply(.failure(PaletteFileError.invalid), name: "invalid.json", token: token)
        XCTAssertNil(content.selection)
        let close = try XCTUnwrap(content.navigationItem.leftBarButtonItem)
        let action = try XCTUnwrap(close.action)
        XCTAssertEqual(close.accessibilityIdentifier, "palette.import.close")
        XCTAssertTrue(close.target === content)
        XCTAssertNil(content.presentedViewController, "This baseline exercises Close without a presented child")
        XCTAssertTrue(UIApplication.shared.sendAction(action, to: close.target, from: close, for: nil))
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in owner.presentedViewController == nil }, object: nil)
        await fulfillment(of: [dismissed], timeout: 3)
        XCTAssertNil(owner.presentedViewController)
        let late = try PaletteSelection(data: Data("[\"#abcdef\"]".utf8))
        content.apply(.success(late), name: "late.json", token: token)
        XCTAssertNil(content.selection, "Dismissal invalidates a previously issued import generation")
        XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), original)
    }
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
