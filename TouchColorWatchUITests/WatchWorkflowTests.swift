import XCTest

final class WatchWorkflowTests: XCTestCase {
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.watch-ui.\(UUID())"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", name.contains("Chinese") ? "(zh-Hans)" : "(en)"]
        app.launch()
    }
    override func tearDownWithError() throws {
        if (testRun?.totalFailureCount ?? 0) > 0 {
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch failure"; shot.lifetime = .keepAlways; add(shot)
            print("WATCH_FAILURE_AX: \(app.debugDescription)")
        }
        app.terminate()
    }
    func testNativeRGBEditSaveDuplicateAndOfflineRelaunch() {
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15), app.debugDescription)
        app.buttons["watch.editor"].tap()
        let hex = app.staticTexts["watch.hex"]
        XCTAssertTrue(hex.waitForExistence(timeout: 5)); XCTAssertEqual(hex.label, "#ff0000")
        app.buttons["watch.component.down"].tap(); XCTAssertEqual(hex.label, "#fe0000")
        for _ in 0..<3 where !app.buttons["watch.save"].isHittable { app.swipeUp() }
        app.buttons["watch.save"].tap(); app.buttons["watch.save"].tap()
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        let count = app.staticTexts["watch.count"]
        XCTAssertTrue(count.waitForExistence(timeout: 8)); XCTAssertEqual(count.label, "2")
        for _ in 0..<5 where !app.buttons["watch.color.1"].exists { app.swipeUp() }
        XCTAssertTrue(app.buttons["watch.color.0"].exists, app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.1"].exists, app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"), app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.1"].label.contains("#fe0000"), app.debugDescription)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch persisted ordered palette"; shot.lifetime = .keepAlways; add(shot)
    }
    func testChineseColorEditorSave() {
        let editor = app.buttons["watch.editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10)); XCTAssertEqual(editor.label, "创建颜色")
        editor.tap(); app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        for _ in 0..<3 where !app.buttons["watch.save"].isHittable { app.swipeUp() }
        XCTAssertEqual(app.buttons["watch.save"].label, "保存颜色")
        app.buttons["watch.save"].tap()
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch Chinese color editor"; shot.lifetime = .keepAlways; add(shot)
    }
    func testRealPhotoPickerSimulatorUnavailableAndCloseKeepsPalette() {
        app.buttons["watch.photo"].tap()
        XCTAssertTrue(app.buttons["watch.photos.choose"].waitForExistence(timeout: 5))
        app.buttons["watch.photos.choose"].tap()
        print("WATCH_PHOTOS_PICKER_AX: \(app.debugDescription)")
        let unavailable = app.staticTexts["Unable to Load Photos in Simulator"]
        XCTAssertTrue(unavailable.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.staticTexts["You need to use an Apple Watch."].exists)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch real PhotosPicker simulator limitation"; shot.lifetime = .keepAlways; add(shot)
        let close = app.buttons["Close"].firstMatch
        XCTAssertTrue(close.exists); close.tap()
        XCTAssertTrue(app.buttons["watch.photos.choose"].waitForExistence(timeout: 5))
    }
}
