import XCTest

final class WatchWorkflowTests: XCTestCase {
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        // The first cold Watch UI session can spend two minutes waiting for the
        // system app to become idle. Keep that startup bounded and distinct from
        // the normal functional cases, which retain the 120-second allowance.
        executionTimeAllowance = name.contains("Chinese") ? 240 : 120
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
    @MainActor private func audit(_ state: String) throws {
        if #available(watchOS 27.0, *) {
            print("WATCH_ACCESSIBILITY_AUDIT_BEGIN: \(state)")
            try app.performAccessibilityAudit(for: .all) { issue in
                print("WATCH_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                print("WATCH_ACCESSIBILITY_ELEMENT: \(String((issue.element?.debugDescription ?? "none").prefix(5000)))")
                return false
            }
            print("WATCH_ACCESSIBILITY_AUDIT_PASS: \(state)")
        } else { throw XCTSkip("Native audit qualification targets the installed watchOS 27 runtime") }
    }

    @MainActor func testOfficialAccessibilitySavedListSendAndCancel() throws {
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15))
        app.buttons["watch.editor"].tap(); app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        for _ in 0..<5 where !app.buttons["watch.save"].isHittable { app.swipeUp() }
        app.buttons["watch.save"].tap(); app.buttons["BackButton"].tap()
        for _ in 0..<5 where !app.buttons["watch.color.0"].isHittable { app.swipeUp() }
        XCTAssertTrue(app.buttons["watch.color.0"].isHittable)
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"))
        try audit("saved palette list")
        let saved = XCTAttachment(screenshot: app.screenshot())
        saved.name = "Native Watch device-sized saved palette"; saved.lifetime = .keepAlways; add(saved)
        for _ in 0..<5 where !app.buttons["watch.editor"].isHittable { app.swipeDown() }
        app.buttons["watch.editor"].tap()
        for _ in 0..<5 where !app.buttons["watch.send"].isHittable { app.swipeUp() }
        app.buttons["watch.send"].tap()
        XCTAssertTrue(app.buttons["Send"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label == '#fe0000'")).firstMatch.exists)
        try audit("explicit Send confirmation")
        let confirmation = XCTAttachment(screenshot: app.screenshot())
        confirmation.name = "Native Watch device-sized Send and Cancel"; confirmation.lifetime = .keepAlways; add(confirmation)
        app.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(app.buttons["watch.send"].waitForExistence(timeout: 5))
        app.buttons["BackButton"].tap()
        for _ in 0..<5 where !app.buttons["watch.transfer.open"].isHittable { app.swipeUp() }
        app.buttons["watch.transfer.open"].tap()
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        try audit("cancelled Send leaves no transfer")
    }
    @MainActor func testOfficialAccessibilityHomeAndColorEditor() throws {
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15))
        try audit("empty palette")
        app.buttons["watch.editor"].tap()
        XCTAssertTrue(app.staticTexts["watch.hex"].waitForExistence(timeout: 5))
        try audit("RGB editor")
        for _ in 0..<3 where !app.buttons["watch.save"].isHittable { app.swipeUp() }
        app.buttons["watch.save"].tap()
        try audit("editor actions and transfer status")
    }

    func testExplicitOfflineTransferRequestSurvivesRelaunchUntilUserCancels() {
        // Deliberately queue two different non-default values and inspect each actual
        // persisted payload through the production transfer review after relaunch.
        for (decrements, expected) in [(1, "#fe0000"), (2, "#fd0000")] {
            for _ in 0..<4 where !app.buttons["watch.editor"].isHittable { app.swipeDown() }
            app.buttons["watch.editor"].tap()
            for _ in 0..<decrements { app.buttons["watch.component.down"].tap() }
            XCTAssertEqual(app.staticTexts["watch.hex"].label, expected)
            for _ in 0..<5 where !app.buttons["watch.send"].isHittable { app.swipeUp() }
            app.buttons["watch.send"].tap()
            let title = app.staticTexts["Send this color to iPhone for review?"]
            XCTAssertTrue(title.waitForExistence(timeout: 5), app.debugDescription)
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label == %@", expected)).firstMatch.exists)
            let confirm = app.buttons["Send"].firstMatch
            XCTAssertTrue(confirm.waitForExistence(timeout: 5), app.debugDescription); confirm.tap()
            app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
            for _ in 0..<5 where !app.buttons["watch.transfer.open"].isHittable { app.swipeUp() }
            app.buttons["watch.transfer.open"].tap()
            let count = app.staticTexts["watch.transfer.count"]
            XCTAssertTrue(count.waitForExistence(timeout: 5)); XCTAssertEqual(count.label, "1 selected colors")
            let queued = app.staticTexts["watch.transfer.color.0"]
            XCTAssertEqual(queued.label, expected)
            for _ in 0..<3 where !queued.isHittable { app.swipeUp() }
            XCTAssertTrue(queued.isHittable, app.debugDescription)
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch actual queued payload after relaunch " + expected; shot.lifetime = .keepAlways; add(shot)
            for _ in 0..<5 where !app.buttons["watch.transfer.cancel"].isHittable { app.swipeUp() }
            app.buttons["watch.transfer.cancel"].tap()
            XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
            XCTAssertTrue(app.staticTexts["watch.transfer.status"].label.contains("Transfer cancelled"))
            app.terminate(); app.launch() // Reload default editor values before the second selection.
        }
    }

    func testRealDigitalCrownChangesRGBComponent() {
        app.buttons["watch.editor"].tap()
        let hex = app.staticTexts["watch.hex"]
        XCTAssertTrue(hex.waitForExistence(timeout: 5)); XCTAssertEqual(hex.label, "#ff0000")
        app.buttons["watch.component.down"].tap(); XCTAssertEqual(hex.label, "#fe0000")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label != %@", "#fe0000"), object: hex)
        XCTAssertEqual(XCTWaiter.wait(for: [changed], timeout: 5), .completed, app.debugDescription)
        XCTAssertTrue(hex.label.hasSuffix("0000"), "The Crown should modify only the selected red channel")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch real Digital Crown RGB adjustment"; shot.lifetime = .keepAlways; add(shot)
    }

    func testEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder() {
        func reach(_ button: XCUIElement) {
            for _ in 0..<6 where !button.isHittable { app.swipeUp() }
            XCTAssertTrue(button.isHittable, app.debugDescription); button.tap()
        }
        func back() { app.buttons["BackButton"].tap() }
        app.buttons["watch.editor"].tap(); app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        reach(app.buttons["watch.save"]); app.buttons["watch.save"].tap(); back()
        reach(app.buttons["watch.color.1"])
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        reach(app.buttons["watch.edit.copy"])
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fd0000")
        reach(app.buttons["watch.save"]); back(); back()
        for _ in 0..<4 { app.swipeDown() }
        reach(app.buttons["watch.color.0"]); reach(app.buttons["watch.delete.0"])
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["watch.count"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["watch.count"].label, "2")
        for _ in 0..<6 where !app.buttons["watch.color.1"].exists { app.swipeUp() }
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"), app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.1"].label.contains("#fd0000"), app.debugDescription)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch edit copy and delete preserve palette order"; image.lifetime = .keepAlways; add(image)
    }

}
