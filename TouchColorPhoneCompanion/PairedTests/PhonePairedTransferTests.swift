import XCTest
import UIKit
import Darwin

/// Reserved for the separately coordinated real paired-simulator foreground run.
/// No received message or receipt is injected by this test.
@MainActor final class PhonePairedTransferTests: XCTestCase {
    private let app = XCUIApplication()
    override func tearDown() {
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

    func testIncomingForegroundTransferReviewAcceptAndRelaunch() throws {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else {
            throw XCTSkip("Requires the explicitly coordinated paired phone/Watch simulator run")
        }
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
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
        print("TOUCHCOLOR_PAIRED_PHONE_READY"); fflush(stdout)
        let incoming = app.cells.matching(NSPredicate(format: "identifier BEGINSWITH 'watch.inbox.'")).containing(.staticText, identifier:"#fe0000").firstMatch
        XCTAssertTrue(incoming.waitForExistence(timeout: 120), app.debugDescription)
        XCTAssertTrue(incoming.staticTexts["1 selected colors"].exists)
        let requestIdentifier = incoming.identifier

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
        inboxClose.tap(); assertClosed(inboxClose)
        assertHistory(["#112233", "#112233", "#fe0000"])

        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]; app.launch()
        assertHistory(["#112233", "#112233", "#fe0000"])
        open("watch.inbox.open")
        XCTAssertTrue(app.cells["watch.inbox.status"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.cells[requestIdentifier].exists)
        print("TOUCHCOLOR_PAIRED_PHONE_RELAUNCH_VERIFIED"); fflush(stdout)
    }
}
