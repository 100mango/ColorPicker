import XCTest
import Foundation

/// Register in the Watch UI-test target only with the coordinated phone integration.
/// Requires a real paired-simulator run; no request or receipt is injected by this test.
final class WatchPairedTransferTests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=paired-watch")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=paired-watch; unexpected interruption; no alert action taken")
        }
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else {
            throw XCTSkip("Requires the dedicated paired iPhone and Watch simulator lane")
        }
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.watch-paired.\(UUID())"
        app.launchEnvironment["TOUCHCOLOR_PAIRED_E2E"] = "1"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(en)"]
        app.launch()
    }
    override func tearDownWithError() throws {
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
        guard let app else { return }
        if (testRun?.totalFailureCount ?? 0) > 0 {
            print("WATCH_PAIRED_FAILURE_AX: \(app.debugDescription)")
            let image = XCTAttachment(screenshot: app.screenshot())
            image.name = "Native Watch paired transfer failure"; image.lifetime = .keepAlways; add(image)
        }
        app.terminate()
        try super.tearDownWithError()
    }
    private func reach(_ button: XCUIElement) {
        for _ in 0..<7 where !button.isHittable { app.swipeUp() }
        XCTAssertTrue(button.isHittable, app.debugDescription)
        button.tap()
    }
    private func openStatus() {
        let back = app.buttons["BackButton"]
        XCTAssertTrue(back.waitForExistence(timeout: 5), app.debugDescription); back.tap()
        reach(app.buttons["watch.transfer.open"])
    }
    func testForegroundSendAcceptReceiptAndBothLocalStatesAfterRelaunch() throws {
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(app.staticTexts["watch.count"].label, "0", "Fresh Watch palette must be empty before Send")
        app.buttons["watch.editor"].tap()
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        reach(app.buttons["watch.save"])
        reach(app.buttons["watch.send"])
        XCTAssertTrue(app.staticTexts["Send this color to iPhone for review?"].waitForExistence(timeout: 5))
        app.buttons["Send"].firstMatch.tap()
        print("TOUCHCOLOR_PAIRED_WATCH_REQUESTED"); fflush(stdout)
        openStatus()
        let status = app.staticTexts["watch.transfer.status"]
        XCTAssertTrue(status.waitForExistence(timeout: 5))
        // Foreground reachability can settle after activation. Each retry is an actual
        // visible user action and preserves the production request's original UUID.
        for attempt in 0..<3 {
            if attempt > 0 {
                let retry = app.buttons["watch.transfer.retry"]
                if retry.exists && retry.isEnabled { reach(retry) }
            }
            // Every Retry has a following observation; total receipt waits stay 60 seconds.
            let accepted = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Accepted on iPhone."), object: status)
            if XCTWaiter.wait(for: [accepted], timeout: 20) == .completed { break }
        }
        XCTAssertEqual(status.label, "Accepted on iPhone.", app.debugDescription)
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        let receipt = try pairedObservation(status)
        let requestID = try XCTUnwrap(receipt["requestID"].flatMap(UUID.init(uuidString:)))
        print("TOUCHCOLOR_PAIRED_WATCH_ACCEPTED \(requestID.uuidString)"); fflush(stdout)
        try waitForPairedReceiptBarrier(role: "watch", observation: receipt)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch actual foreground acceptance receipt"; image.lifetime = .keepAlways; add(image)
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["watch.count"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["watch.count"].label, "1")
        let saved = app.buttons["watch.color.0"]
        XCTAssertTrue(saved.waitForExistence(timeout: 5))
        XCTAssertTrue(saved.label.contains("#fe0000"), "The actual saved color must survive relaunch")
        reach(saved)
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        openStatus()
        XCTAssertEqual(app.staticTexts["watch.transfer.status"].label, "Accepted on iPhone.")
        let restored = try pairedObservation(app.staticTexts["watch.transfer.status"])
        for key in ["requestID", "fingerprint", "requestProtocol", "receiptProtocol", "version", "outcome"] { XCTAssertEqual(restored[key], receipt[key]) }
        XCTAssertEqual(restored["receiveChannel"], "persisted")
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        print("TOUCHCOLOR_PAIRED_WATCH_RELAUNCH_VERIFIED"); fflush(stdout)
    }
}
