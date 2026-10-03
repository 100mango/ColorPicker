import XCTest

final class VisionWorkflowTests: XCTestCase {
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.vision-ui.\(UUID())"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]; app.launch()
    }
    override func tearDownWithError() throws {
        if (testRun?.totalFailureCount ?? 0) > 0 { capture("Native Vision failure"); print("VISION_FAILURE_AX: \(app.debugDescription)") }
        app.terminate()
    }
    private func capture(_ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    private func hex(_ expected: String) {
        let value = app.staticTexts["sample.hex"]
        XCTAssertTrue(value.waitForExistence(timeout: 15), app.debugDescription)
        let check = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@ OR value == %@", expected, expected), object: value)
        XCTAssertEqual(XCTWaiter.wait(for: [check], timeout: 10), .completed, app.debugDescription)
    }
    private func photo() {
        XCTAssertTrue(app.buttons["image.photos"].waitForExistence(timeout: 20), app.debugDescription)
        app.buttons["image.photos"].tap()
        let image = app.images.matching(NSPredicate(format: "identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'")).firstMatch
        if image.waitForExistence(timeout: 6) { image.tap() }
        else {
            let item = app.collectionViews.cells.firstMatch
            XCTAssertTrue(item.waitForExistence(timeout: 15), app.debugDescription); item.tap()
        }
        hex("#ff00ff")
    }
    func testRealPhotosPrecisionZoomPaletteAndRelaunch() {
        photo()
        app.buttons["sample.save"].tap(); app.buttons["sample.save"].tap()
        app.buttons["sample.above"].tap(); hex("#00ff00")
        app.buttons["sample.zoom.in"].tap()
        XCTAssertTrue(app.staticTexts["sample.zoom.value"].exists)
        app.buttons["sample.center"].tap(); hex("#ff00ff")
        capture("Native Vision imported photo with precision sampling and zoom")
        app.buttons["privacy.open"].tap(); XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 5)); app.buttons["privacy.close"].tap()
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        let count = app.staticTexts["palette.count"]
        XCTAssertTrue(count.waitForExistence(timeout: 15)); XCTAssertEqual(count.label, "2")
        capture("Native Vision ordered palette after relaunch")
    }
    func testNativeExportSaveAndReopenActualPNG() {
        photo(); app.buttons["image.export"].tap()
        let save = app.buttons["Save"].firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 10), app.debugDescription)
        print("VISION_EXPORT_PANEL_AX: \(app.debugDescription)")
        save.tap()
        XCTAssertTrue(app.buttons["export.reopen"].waitForExistence(timeout: 12), app.debugDescription)
        app.buttons["export.reopen"].tap(); hex("#ff00ff")
        app.buttons["sample.above"].tap(); hex("#00ff00")
        capture("Native Vision actual exported PNG reopened")
    }
    func testNativeFileAndPhotosCancelRepeatedly() {
        XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 20))
        for key in ["image.open", "image.photos"] {
            app.buttons[key].tap()
            let cancel = app.buttons["Cancel"].firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 10), app.debugDescription); cancel.tap()
            XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 5))
        }
        XCTAssertEqual(app.staticTexts["palette.count"].label, "0")
    }
}
