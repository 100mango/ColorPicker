import XCTest
import UIKit
import UniformTypeIdentifiers
import ColorPaletteLegacy
@testable import TouchColor

/// Observe UIKit's real owner appearance once; never synthesize lifecycle calls.
@MainActor private final class PhonePaletteImportTestOwner: UIViewController {
    var onFirstAppearance: (() -> Void)?
    var onNextAppearance: (() -> Void)?
    private(set) var hasAppeared = false
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        let next = onNextAppearance; onNextAppearance = nil; next?()
        guard !hasAppeared else { return }
        hasAppeared = true
        let completion = onFirstAppearance
        onFirstAppearance = nil
        completion?()
    }
}

/// Integrated UIKit review lifecycle and unsupported-companion behavior.
@MainActor final class PhonePaletteImportTests: XCTestCase {
    func testActualCloseBarActionDismissesFullScreenErrorAndRejectsLateResult() async throws {
        let suite = "TouchColor.close-action.\(UUID())", defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let original = ["#123456", "#123456"]
        defaults.set(original, forKey: "colorArray")
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive })
        let oldKeyWindow = scene.windows.first { $0.isKeyWindow }
        let owner = PhonePaletteImportTestOwner(), window = UIWindow(windowScene: scene)
        let ownerAppeared = expectation(description: "Actual UIKit test owner appeared")
        var ownerEvent: TimeInterval?
        var ownerState = false
        let ownerAction = ProcessInfo.processInfo.systemUptime
        owner.onFirstAppearance = {
            ownerState = owner.viewIfLoaded?.window === window
            ownerEvent = ProcessInfo.processInfo.systemUptime
            NSLog("HOSTED_UI_GATE phase=owner event=appearance action=%.6f observed=%.6f state=%d", ownerAction, ownerEvent!, ownerState ? 1 : 0)
            if ownerState { ownerAppeared.fulfill() }
        }
        window.rootViewController = owner; window.makeKeyAndVisible()
        let ownerReturned = ProcessInfo.processInfo.systemUptime
        defer { window.isHidden = true; window.rootViewController = nil; oldKeyWindow?.makeKey() }
        // makeKeyAndVisible begins appearance asynchronously. Present only after
        // UIKit has delivered its actual owner callback, with the original import
        // presentation and dismissal gates still independently capped at 3 seconds.
        let ownerWait = ProcessInfo.processInfo.systemUptime
        await fulfillment(of: [ownerAppeared], timeout: 3)
        owner.onFirstAppearance = nil
        let ownerAttached = owner.viewIfLoaded?.window === window
        let ownerWaitReturned = ProcessInfo.processInfo.systemUptime
        NSLog("HOSTED_UI_GATE phase=owner action=%.6f returned=%.6f wait=%.6f waitReturned=%.6f observed=%.6f state=%d", ownerAction, ownerReturned, ownerWait, ownerWaitReturned, ownerEvent ?? -1, ownerAttached ? 1 : 0)
        XCTAssertTrue(owner.viewIfLoaded?.window === window)
        let ownerTimely = ownerEvent.map { $0 >= ownerAction && $0 < ownerWait + 3 } ?? false
        guard ownerTimely, ownerState, owner.hasAppeared, ownerAttached else {
            XCTFail("Owner appearance readiness was not proved within the original waiter boundary")
            NSLog("HOSTED_UI_GATE phase=owner dependent=unexecuted readiness=unproved"); return
        }
        let content = PhonePaletteImportController(defaults: defaults)
        let navigation = UINavigationController(rootViewController: content); navigation.modalPresentationStyle = .fullScreen
        let presented = expectation(description: "Actual full-screen UIKit import host appeared")
        var presentationEvent: TimeInterval?
        var presentationState = false
        var presentationClosed = false
        let presentationAction = ProcessInfo.processInfo.systemUptime
        owner.present(navigation, animated: false) {
            guard !presentationClosed else { return }
            presentationState = owner.presentedViewController === navigation && navigation.presentingViewController === owner && content.viewIfLoaded?.window === window
            presentationEvent = ProcessInfo.processInfo.systemUptime
            NSLog("HOSTED_UI_GATE phase=presentation event=completion action=%.6f observed=%.6f state=%d", presentationAction, presentationEvent!, presentationState ? 1 : 0)
            if presentationState { presented.fulfill() }
        }
        let presentationReturned = ProcessInfo.processInfo.systemUptime
        let presentationWait = ProcessInfo.processInfo.systemUptime
        await fulfillment(of: [presented], timeout: 3)
        presentationClosed = true
        let presentationAttached = owner.presentedViewController === navigation && navigation.presentingViewController === owner && content.viewIfLoaded?.window === window
        let presentationWaitReturned = ProcessInfo.processInfo.systemUptime
        NSLog("HOSTED_UI_GATE phase=presentation action=%.6f returned=%.6f wait=%.6f waitReturned=%.6f observed=%.6f state=%d", presentationAction, presentationReturned, presentationWait, presentationWaitReturned, presentationEvent ?? -1, presentationAttached ? 1 : 0)
        XCTAssertTrue(window.isKeyWindow)
        XCTAssertTrue(window.windowScene === scene)
        XCTAssertTrue(owner.presentedViewController === navigation)
        XCTAssertTrue(navigation.presentingViewController === owner)
        XCTAssertTrue(navigation.topViewController === content)
        XCTAssertTrue(content.view.window === window)
        let presentationTimely = presentationEvent.map { $0 >= presentationAction && $0 < presentationWait + 3 } ?? false
        guard presentationTimely, presentationState, presentationAttached else {
            XCTFail("Presentation readiness was not proved within the original waiter boundary")
            NSLog("HOSTED_UI_GATE phase=presentation dependent=unexecuted readiness=unproved"); return
        }
        let token = content.begin()
        content.apply(.failure(PaletteFileError.invalid), name: "invalid.json", token: token)
        XCTAssertNil(content.selection)
        let close = try XCTUnwrap(content.navigationItem.leftBarButtonItem)
        let action = try XCTUnwrap(close.action)
        XCTAssertEqual(close.accessibilityIdentifier, "palette.import.close")
        XCTAssertTrue(close.target === content)
        XCTAssertNil(content.presentedViewController, "This baseline exercises Close without a presented child")
        let dismissed = expectation(description: "Actual owner reappeared with full-screen presentation absent")
        var dismissalEvent: TimeInterval?
        var dismissalState = false
        let dismissalAction = ProcessInfo.processInfo.systemUptime
        owner.onNextAppearance = { [weak owner] in
            guard let owner else { return }
            dismissalState = owner.presentedViewController == nil && owner.viewIfLoaded?.window === window
            dismissalEvent = ProcessInfo.processInfo.systemUptime
            NSLog("HOSTED_UI_GATE phase=dismissal event=owner-reappeared action=%.6f observed=%.6f state=%d", dismissalAction, dismissalEvent!, dismissalState ? 1 : 0)
            if dismissalState { dismissed.fulfill() }
        }
        defer { owner.onNextAppearance = nil }
        XCTAssertTrue(UIApplication.shared.sendAction(action, to: close.target, from: close, for: nil))
        let dismissalReturned = ProcessInfo.processInfo.systemUptime
        // Preserve the original waiter-relative3s gate. Action-to-state latency
        // is recorded separately; no new action-start responsiveness SLA.
        let dismissalWait = ProcessInfo.processInfo.systemUptime
        await fulfillment(of: [dismissed], timeout: 3)
        owner.onNextAppearance = nil
        let dismissalAbsent = owner.presentedViewController == nil
        let dismissalWaitReturned = ProcessInfo.processInfo.systemUptime
        NSLog("HOSTED_UI_GATE phase=dismissal action=%.6f returned=%.6f wait=%.6f waitReturned=%.6f observed=%.6f state=%d", dismissalAction, dismissalReturned, dismissalWait, dismissalWaitReturned, dismissalEvent ?? -1, dismissalAbsent ? 1 : 0)
        XCTAssertNil(owner.presentedViewController)
        let dismissalTimely = dismissalEvent.map { $0 >= dismissalAction && $0 < dismissalWait + 3 } ?? false
        guard dismissalTimely, dismissalState, dismissalAbsent else {
            XCTFail("Dismissal readiness was not proved within the original waiter boundary")
            NSLog("HOSTED_UI_GATE phase=dismissal late-result-check=unexecuted readiness=unproved"); return
        }
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
