import XCTest
import Foundation

/// Register in the Watch UI-test target only with the coordinated phone integration.
/// Requires a real paired-simulator run; no request or receipt is injected by this test.
final class WatchPairedTransferTests: XCTestCase {
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else {
            throw XCTSkip("Requires the dedicated paired iPhone and Watch simulator lane")
        }
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.watch-paired.\(UUID())"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(en)"]
        app.launch()
    }
    override func tearDownWithError() throws {
        guard let app else { return }
        if (testRun?.totalFailureCount ?? 0) > 0 {
            print("WATCH_PAIRED_FAILURE_AX: \(app.debugDescription)")
            let image = XCTAttachment(screenshot: app.screenshot())
            image.name = "Native Watch paired transfer failure"; image.lifetime = .keepAlways; add(image)
        }
        app.terminate()
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
    func testForegroundSendAcceptReceiptAndBothLocalStatesAfterRelaunch() {
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15), app.debugDescription)
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
        for _ in 0..<3 {
            let accepted = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Accepted on iPhone."), object: status)
            if XCTWaiter.wait(for: [accepted], timeout: 20) == .completed { break }
            let retry = app.buttons["watch.transfer.retry"]
            if retry.exists && retry.isEnabled { reach(retry) }
        }
        XCTAssertEqual(status.label, "Accepted on iPhone.", app.debugDescription)
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        print("TOUCHCOLOR_PAIRED_WATCH_ACCEPTED"); fflush(stdout)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch actual foreground acceptance receipt"; image.lifetime = .keepAlways; add(image)
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["watch.count"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["watch.count"].label, "1")
        reach(app.buttons["watch.transfer.open"])
        XCTAssertEqual(app.staticTexts["watch.transfer.status"].label, "Accepted on iPhone.")
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        print("TOUCHCOLOR_PAIRED_WATCH_RELAUNCH_VERIFIED"); fflush(stdout)
    }
}
