import XCTest
import UIKit
import Darwin

/// Reserved for the separately coordinated real paired-simulator foreground run.
/// No received message or receipt is injected by this test.
@MainActor final class PhonePairedTransferTests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private let app = XCUIApplication()
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=paired-phone")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=paired-phone; unexpected interruption; no alert action taken")
        }
    }
    override func tearDown() {
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
        if (testRun?.failureCount ?? 0) > 0 {
            if let data=XCUIScreen.main.screenshot().image.jpegData(compressionQuality:0.55), data.count<=500*1024 {
                let image=XCTAttachment(data:data,uniformTypeIdentifier:"public.jpeg")
                image.name="touchcolor-paired-phone-failure";image.lifetime = .keepAlways;add(image)
            }
            print("TOUCHCOLOR_PAIRED_PHONE_FAILURE_HIERARCHY\n"+app.debugDescription);fflush(stdout)
        }
        app.terminate()
        super.tearDown()
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
    private func open(_ identifier: String) {
        let button = app.buttons[identifier], scroll = app.scrollViews["sourceControls"]
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        for _ in 0..<5 where !button.isHittable {
            if button.frame.minY < scroll.frame.minY { scroll.swipeDown() } else { scroll.swipeUp() }
        }
        XCTAssertTrue(button.isHittable); button.tap()
    }
    private func assertClosed(_ button: XCUIElement) {
        if #available(iOS 18.0, *) { XCTAssertTrue(button.waitForNonExistence(timeout: 5)) }
        else {
            let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: button)
            XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed)
        }
    }
    private func assertHistory(_ colors: [String]) {
        let cells = app.tables["colorHistory"].cells
        XCTAssertTrue(cells.firstMatch.waitForExistence(timeout: 5))
        XCTAssertEqual(cells.count, colors.count)
        for (index, color) in colors.enumerated() {
            XCTAssertTrue(cells.element(boundBy: index).label.contains(color))
        }
    }

    private func healthyInbox(receipts: Int) throws -> [String: String] {
        let emptyStatus = app.cells["watch.inbox.status"]
        let healthy = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard emptyStatus.exists, let text = emptyStatus.value as? String, let data = text.data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return false }
            return value["phase"] == "ready-empty" && value["activated"] == "true" && value["pendingCount"] == "0" && value["acceptedReceiptCount"] == String(receipts)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [healthy], timeout: 5), .completed, "Inbox must be activated, readable and empty")
        XCTAssertTrue(emptyStatus.staticTexts.firstMatch.label.hasPrefix("No pending Watch colors."))
        return try pairedObservation(emptyStatus)
    }

    func testIncomingForegroundTransferReviewAcceptAndRelaunch() throws {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else {
            throw XCTSkip("Requires the explicitly coordinated paired phone/Watch simulator run")
        }
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        app.launchEnvironment["TOUCHCOLOR_PAIRED_E2E"] = "1"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        // Establish existing duplicates through the actual visible import review.
        UIPasteboard.general.string = "[\"#112233\",\"#112233\"]"
        open("palette.import.open")
        let paste = element("palette.import.paste")
        XCTAssertTrue(paste.waitForExistence(timeout: 5)); paste.tap()
        XCTAssertTrue(element("palette.import.color.1").waitForExistence(timeout: 10))
        let accept = app.buttons["palette.import.accept"], importClose = app.buttons["palette.import.close"]
        XCTAssertTrue(accept.isEnabled); accept.tap(); assertClosed(importClose)
        assertHistory(["#112233", "#112233"])

        open("watch.inbox.open")
        XCTAssertTrue(app.tables["watch.inbox"].waitForExistence(timeout: 5))
        _ = try healthyInbox(receipts: 0)
        print("TOUCHCOLOR_PAIRED_PHONE_READY"); fflush(stdout)
        let incoming = app.cells.matching(NSPredicate(format: "identifier BEGINSWITH 'watch.inbox.'")).containing(.staticText, identifier:"#fe0000").firstMatch
        XCTAssertTrue(incoming.waitForExistence(timeout: 120), app.debugDescription)
        XCTAssertTrue(incoming.staticTexts["1 selected colors"].exists)
        let requestIdentifier = incoming.identifier
        let requestID = try XCTUnwrap(UUID(uuidString: String(requestIdentifier.dropFirst("watch.inbox.".count))))
        let received = try pairedObservation(incoming)
        XCTAssertEqual(received["requestID"], requestID.uuidString)
        XCTAssertEqual(received["receiveChannel"], "sendMessage")
        incoming.tap()
        let review = app.alerts["Add these colors?"]
        XCTAssertTrue(review.waitForExistence(timeout: 5))
        review.buttons["Cancel"].tap()
        assertClosed(review)
        XCTAssertTrue(app.cells[requestIdentifier].exists, "Cancel must retain the actual request")
        print("TOUCHCOLOR_PAIRED_PHONE_REVIEW_CANCELLED \(requestID.uuidString)"); fflush(stdout)

        // Merely receiving/reviewing the message may not append to the palette.
        let inboxClose = app.buttons["watch.inbox.close"]
        inboxClose.tap(); assertClosed(inboxClose); assertHistory(["#112233", "#112233"])
        open("watch.inbox.open")
        let retained = app.cells[requestIdentifier]
        XCTAssertTrue(retained.waitForExistence(timeout: 5)); retained.tap()
        let confirmation = app.alerts["Add these colors?"]
        XCTAssertTrue(confirmation.waitForExistence(timeout: 5))
        confirmation.buttons["Add Colors"].tap()
        if #available(iOS 18.0, *) { XCTAssertTrue(retained.waitForNonExistence(timeout: 5)) }
        else { XCTAssertFalse(retained.exists) }
        XCTAssertTrue(app.cells["watch.inbox.status"].exists)
        let receipt = try pairedObservation(app.cells["watch.inbox.status"])
        for key in ["requestID", "requestProtocol", "version", "fingerprint", "receiveChannel"] { XCTAssertEqual(receipt[key], received[key]) }
        inboxClose.tap(); assertClosed(inboxClose)
        assertHistory(["#112233", "#112233", "#fe0000"])

        try waitForPairedReceiptBarrier(role: "phone", observation: receipt)
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]; app.launch()
        assertHistory(["#112233", "#112233", "#fe0000"])
        open("watch.inbox.open")
        XCTAssertTrue(app.cells["watch.inbox.status"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.cells[requestIdentifier].exists)
        let restored = try healthyInbox(receipts: 1)
        XCTAssertEqual(restored["phase"], "ready-empty")
        XCTAssertEqual(restored["activated"], "true")
        XCTAssertEqual(restored["pendingCount"], "0")
        XCTAssertEqual(restored["acceptedReceiptCount"], "1")
        XCTAssertTrue(app.cells["watch.inbox.status"].staticTexts.firstMatch.label.hasPrefix("No pending Watch colors."))
        for key in ["requestID", "fingerprint", "requestProtocol", "receiptProtocol", "version", "outcome"] { XCTAssertEqual(restored[key], receipt[key]) }
        XCTAssertEqual(restored["receiveChannel"], "persisted")
        print("TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED"); fflush(stdout)
    }
}
