import XCTest

final class WatchWorkflowTests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=watch")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=watch; unexpected interruption; no alert action taken")
        }
        continueAfterFailure = false
        // The first cold Watch UI session can spend two minutes waiting for the
        // system app to become idle. Keep that startup bounded and distinct from
        // the normal functional cases, which retain the 120-second allowance.
        executionTimeAllowance = name.contains("Chinese") ? 240 : 120
        app = XCUIApplication()
        app.launchEnvironment["TOUCHCOLOR_TEST_CASE"] = name
        app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.watch-ui.\(UUID())"
        if name.contains("PublicLargestTrait") { app.launchEnvironment["TOUCHCOLOR_TEST_TRAIT_PROOF"] = "1" }
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", name.contains("Chinese") ? "(zh-Hans)" : "(en)"]
        if name.contains("TouchCopyEntryTouchAndCrownRemainResponsive") {
            // Foundation's argument domain supplies synthetic input to the
            // existing LegacyPalette colorArray key, including isolated suites.
            // This case does not claim to test Save or persisted palette writes.
            app.launchArguments += ["-colorArray", "(\"#fe0000\", \"#fe0000\")"]
        } else if name.contains("TouchCopyEntryReentryDoesNotPersist") {
            app.launchArguments += ["-colorArray", "(\"#fe0000\", \"#fe0000\")"]
        }
        app.launch()
    }
    override func tearDownWithError() throws {
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
        if (testRun?.totalFailureCount ?? 0) > 0 {
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch failure"; shot.lifetime = .keepAlways; add(shot)
            print("WATCH_FAILURE_AX: \(app.debugDescription)")
        }
        app.terminate()
        try super.tearDownWithError()
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
    @MainActor func testPublicLargestTraitChineseColorEditorSave() throws {
        // Invoked only by the host after this exact owned device returned the
        // literal unsupported system-size query with confirmed command cleanup.
        func metric(_ largest: Bool) throws -> Double {
            let hex = app.staticTexts["watch.hex"]
            XCTAssertTrue(hex.waitForExistence(timeout: 5))
            let proof = try XCTUnwrap(hex.value as? String)
            XCTAssertTrue(proof.hasPrefix("largest=\(largest);metric="), proof)
            return try XCTUnwrap(Double(proof.components(separatedBy: "metric=").last ?? ""))
        }
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15))
        app.buttons["watch.editor"].tap()
        let baseline = try metric(false), baselineFrame = app.staticTexts["watch.hex"].frame, viewport = app.frame
        app.terminate(); app.launchEnvironment["TOUCHCOLOR_TEST_LARGEST_TRAIT"] = "1"; app.launch()
        XCTAssertEqual(app.frame, viewport)
        testChineseColorEditorSave()
        // Saving scrolls the editor. Return to its measured numerical readout.
        for _ in 0..<5 where !app.staticTexts["watch.hex"].isHittable { app.swipeDown() }
        let largest = try metric(true), hex = app.staticTexts["watch.hex"]
        XCTAssertGreaterThan(largest, baseline); XCTAssertGreaterThan(hex.frame.height, baselineFrame.height)
        XCTAssertEqual(hex.label, "#fe0000"); XCTAssertGreaterThan(hex.frame.width / hex.frame.height, 2.5)
        XCTAssertEqual(app.staticTexts["watch.rgb"].label, "R 254   G 0   B 0")
        XCTAssertTrue(viewport.contains(app.staticTexts["watch.rgb"].frame))
        XCTAssertTrue(viewport.contains(hex.frame)); try audit("largest public trait Chinese editor")
        app.buttons["BackButton"].tap()
        for _ in 0..<5 where !app.buttons["watch.color.0"].isHittable { app.swipeUp() }
        XCTAssertTrue(app.buttons["watch.color.0"].isHittable)
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"))
        XCTAssertTrue(viewport.contains(app.buttons["watch.color.0"].frame))
        try audit("largest public trait saved palette")
        for _ in 0..<5 where !app.buttons["watch.editor"].isHittable { app.swipeDown() }
        app.buttons["watch.editor"].tap()
        for _ in 0..<5 where !app.buttons["watch.send"].isHittable { app.swipeUp() }
        app.buttons["watch.send"].tap()
        let close = app.buttons["AX_ActionContentControllerCancelButton"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 5)); XCTAssertTrue(close.isHittable)
        try audit("largest public trait Send and Cancel")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch largest public trait Send and Cancel"; shot.lifetime = .keepAlways; add(shot)
        close.tap(); XCTAssertTrue(app.buttons["watch.send"].waitForExistence(timeout: 5))
        app.buttons["BackButton"].tap()
        for _ in 0..<5 where !app.buttons["watch.transfer.open"].isHittable { app.swipeUp() }
        app.buttons["watch.transfer.open"].tap()
        XCTAssertFalse(app.staticTexts["watch.transfer.count"].exists)
        print("WATCH_PUBLIC_TRAIT_PROOF: accessibility5; baselineMetric=\(baseline); largestMetric=\(largest); viewport=\(viewport); systemPropagation=unverified")
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
        // watchOS renders the cancel-role action as the observed top-left Close
        // control, not as a table row titled Cancel (including the 40mm layout).
        let close = app.buttons["AX_ActionContentControllerCancelButton"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(close.label, "Close"); close.tap()
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

    @MainActor func testTouchCopyEntryTouchAndCrownRemainResponsive() throws {
        func revealComponentControls() {
            let down = app.buttons["watch.component.down"], up = app.buttons["watch.component.up"]
            // Real bounded touch scrolling within the current editor viewport.
            // The 40mm component row begins below the visible content; Crown
            // editing is tested after the same explicit +/- focus as the
            // previously passing RGB test, not as an unverified entry promise.
            for attempt in 0...6 {
                XCTAssertEqual(app.scrollViews.count, 1)
                XCTAssertEqual(app.navigationBars.count, 1)
                let navigation = app.navigationBars["Create Color"]
                XCTAssertTrue(navigation.exists)
                let scroll = app.scrollViews.element(boundBy: 0)
                let viewport = app.frame.intersection(scroll.frame)
                let top = max(viewport.minY, navigation.frame.maxY)
                let content = CGRect(x: viewport.minX, y: top, width: viewport.width, height: viewport.maxY - top)
                XCTAssertGreaterThan(content.width, 44); XCTAssertGreaterThan(content.height, 64)
                if down.exists && up.exists && down.isHittable && up.isHittable
                    && content.contains(down.frame) && content.contains(up.frame) { return }
                guard attempt < 6 else { XCTFail("RGB controls remained clipped after six touch drags"); return }
                let above = down.exists && down.frame.midY < content.midY
                let origin = scroll.coordinate(withNormalizedOffset: .zero)
                let startY = content.midY + (above ? -16 : 16)
                let endY = content.midY + (above ? 16 : -16)
                let start = origin.withOffset(CGVector(dx: content.midX - scroll.frame.minX, dy: startY - scroll.frame.minY))
                let end = origin.withOffset(CGVector(dx: content.midX - scroll.frame.minX, dy: endY - scroll.frame.minY))
                start.press(forDuration: 0.01, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)
            }
        }
        let count = app.staticTexts["watch.count"]
        XCTAssertTrue(count.waitForExistence(timeout: 10))
        XCTAssertEqual(count.label, "2", "The actual palette must load both synthetic argument-domain inputs")
        // Keep a real prior editor in the navigation history without claiming
        // synthetic palette inputs prove Save, deletion or persisted writes.
        app.buttons["watch.editor"].tap()
        let createHex = app.staticTexts["watch.hex"]
        XCTAssertTrue(createHex.waitForExistence(timeout: 5)); XCTAssertEqual(createHex.label, "#ff0000")
        revealComponentControls()
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(createHex.label, "#fe0000")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        let createChanged = createHex.label
        XCTAssertNotEqual(createChanged, "#fe0000", "Create Crown editing must respond after explicit component focus")
        XCTAssertEqual(createChanged.count, 7); XCTAssertTrue(createChanged.hasPrefix("#") && createChanged.hasSuffix("0000"))
        let createRed = try XCTUnwrap(Int(createChanged.dropFirst().prefix(2), radix: 16))
        XCTAssertTrue((0...253).contains(createRed))
        app.buttons["watch.component.up"].tap()
        XCTAssertEqual(createHex.label, String(format: "#%02x0000", createRed + 1))
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(createHex.label, createChanged)
        print("WATCH_CREATE_ENTRY_RESPONSE touchFocusedCrown=true buttons=true")
        app.buttons["BackButton"].tap()
        try reachSavedColorByTouch("watch.color.0")
        let hex = app.staticTexts["watch.hex"]
        XCTAssertEqual(hex.label, "#fe0000", "The fixture must be read through the real saved-color destination")
        let copy = app.buttons["watch.edit.copy"]
        XCTAssertTrue(copy.waitForExistence(timeout: 5)); XCTAssertTrue(copy.isHittable)
        copy.tap() // Ordinary XCTest quiescence must finish before any reveal or edit.
        XCTAssertTrue(hex.waitForExistence(timeout: 5)); XCTAssertEqual(hex.label, "#fe0000")
        revealComponentControls()
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(hex.label, "#fd0000")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        let changed = hex.label
        XCTAssertNotEqual(changed, "#fd0000", "Copy Crown editing must respond after explicit component focus")
        XCTAssertEqual(changed.count, 7); XCTAssertTrue(changed.hasPrefix("#") && changed.hasSuffix("0000"))
        let red = try XCTUnwrap(Int(changed.dropFirst().prefix(2), radix: 16))
        XCTAssertTrue((0...252).contains(red))
        app.buttons["watch.component.up"].tap()
        XCTAssertEqual(hex.label, String(format: "#%02x0000", red + 1))
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(hex.label, changed)
        print("WATCH_COPY_ENTRY_RESPONSE touchFocusedCrown=true buttons=true")
        app.buttons["BackButton"].tap()
        XCTAssertTrue(copy.waitForExistence(timeout: 5))
        XCTAssertEqual(hex.label, "#fe0000", "An unsaved copy must leave the original saved color unchanged")
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch Create and copy touch-focused Crown response"; image.lifetime = .keepAlways; add(image)
    }

    @MainActor func testTouchCopyEntryReentryDoesNotPersist() throws {
        let count = app.staticTexts["watch.count"]
        XCTAssertTrue(count.waitForExistence(timeout: 10)); XCTAssertEqual(count.label, "2")
        try reachSavedColorByTouch("watch.color.0")
        let hex = app.staticTexts["watch.hex"]
        XCTAssertEqual(hex.label, "#fe0000")
        for _ in 0..<2 {
            let copy = app.buttons["watch.edit.copy"]
            XCTAssertTrue(copy.waitForExistence(timeout: 5)); XCTAssertTrue(copy.isHittable)
            copy.tap() // Keep ordinary XCTest quiescence on each real entry.
            XCTAssertTrue(hex.waitForExistence(timeout: 5)); XCTAssertEqual(hex.label, "#fe0000")
            // The existing RGB test also lets XCTest reveal this real control.
            app.buttons["watch.component.down"].tap()
            XCTAssertEqual(hex.label, "#fd0000")
            app.buttons["BackButton"].tap()
            XCTAssertTrue(copy.waitForExistence(timeout: 5))
            XCTAssertEqual(hex.label, "#fe0000", "Returning must preserve the saved color")
        }
        app.buttons["BackButton"].tap()
        XCTAssertTrue(count.waitForExistence(timeout: 5)); XCTAssertEqual(count.label, "2")
        // The first launch only supplied argument-domain input. Relaunch the
        // same suite without either the input or reset: Copy must not persist it.
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(count.waitForExistence(timeout: 10)); XCTAssertEqual(count.label, "0")
    }

    func testRealDigitalCrownChangesRGBComponent() {
        app.buttons["watch.editor"].tap()
        let hex = app.staticTexts["watch.hex"]
        XCTAssertTrue(hex.waitForExistence(timeout: 5)); XCTAssertEqual(hex.label, "#ff0000")
        app.buttons["watch.component.down"].tap(); XCTAssertEqual(hex.label, "#fe0000")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        // The synchronous Crown event waits for animation. The prior predicate
        // wait timed out resolving remote snapshots even though its failure
        // hierarchy already read #fa0000. Assert the returned numerical state.
        let changed = hex.label
        XCTAssertNotEqual(changed, "#fe0000", app.debugDescription)
        XCTAssertTrue(changed.hasPrefix("#") && changed.hasSuffix("0000"), "The Crown should modify only the selected red channel")
        XCTAssertEqual(changed.count, 7)
        guard let red = Int(changed.dropFirst().prefix(2), radix: 16) else {
            XCTFail("The changed red channel must remain valid hexadecimal: \(changed)"); return
        }
        XCTAssertTrue((0...253).contains(red), "The negative Crown event must decrease the starting red value 254")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Watch real Digital Crown RGB adjustment"; shot.lifetime = .keepAlways; add(shot)
    }

    /// One real AX snapshot per observation; no coordinates, focus changes,
    /// scrolling, labels or color values are synthesized by this diagnostic.
    @MainActor private func logHomeListFrame(_ phase: String) throws {
        print("WATCH_LIST_SNAPSHOT_BEGIN case=\(name) phase=\(phase)"); fflush(stdout)
        let snapshotStarted = ProcessInfo.processInfo.systemUptime
        let root = try app.snapshot()
        let snapshotMilliseconds = Int((ProcessInfo.processInfo.systemUptime - snapshotStarted) * 1000)
        var pending: [any XCUIElementSnapshot] = [root]
        var rows: [[String: Any]] = []
        var visited = 0
        func rectangle(_ frame: CGRect) -> [Double] {
            [Double(frame.minX), Double(frame.minY), Double(frame.width), Double(frame.height)]
        }
        while let element = pending.popLast() {
            visited += 1
            guard visited <= 512 else { XCTFail("Home List diagnostic exceeded its snapshot bound"); return }
            let identifier = element.identifier
            if ["watch.editor", "watch.photo", "watch.count", "watch.transfer.open", "watch.privacy"].contains(identifier)
                || identifier.hasPrefix("watch.color.") {
                rows.append(["id": identifier, "frame": rectangle(element.frame)])
            }
            pending.append(contentsOf: element.children)
        }
        XCTAssertLessThanOrEqual(rows.count, 24)
        let data = try JSONSerialization.data(withJSONObject: ["case": name, "phase": phase,
            "viewport": rectangle(root.frame), "rows": rows, "snapshotMilliseconds": snapshotMilliseconds], options: [.sortedKeys])
        XCTAssertLessThanOrEqual(data.count, 4096)
        print("WATCH_LIST_FRAME " + String(decoding: data, as: UTF8.self)); fflush(stdout)
    }

    @MainActor func testHomeListDigitalCrownFromColdLaunch() throws {
        // Cold-home control: no editor destination has been opened. The same
        // Crown delta and bound must reach the real, initially offscreen row.
        XCTAssertTrue(app.buttons["watch.editor"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["BackButton"].exists, app.debugDescription)
        XCTAssertEqual(app.staticTexts["watch.count"].label, "0")
        let target = app.buttons["watch.privacy"]
        XCTAssertFalse(target.exists && target.isHittable, "The cold-home control must require actual scrolling")
        for attempt in 0..<12 {
            if target.exists && target.isHittable { break }
            try logHomeListFrame("cold.\(attempt).before")
            XCUIDevice.shared.rotateDigitalCrown(delta: -0.1)
            try logHomeListFrame("cold.\(attempt).after")
        }
        XCTAssertTrue(target.isHittable, app.debugDescription)
        target.tap()
        XCTAssertTrue(app.navigationBars["Privacy"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["BackButton"].exists)
    }

    /// A fresh bounded snapshot scopes each gesture to the actual home List.
    /// This helper is used only by the separately launched touch workflow.
    @MainActor private func reachSavedColorByTouch(_ identifier: String, tap: Bool = true) throws {
        func rect(_ value: CGRect) -> TCWatchListRect {
            TCWatchListRect(x: Double(value.origin.x), y: Double(value.origin.y), width: Double(value.size.width), height: Double(value.size.height))
        }
        guard identifier.hasPrefix("watch.color."),
              let targetIndex = Int32(identifier.dropFirst("watch.color.".count)), targetIndex >= 0,
              identifier == "watch.color.\(targetIndex)" else {
            XCTFail("Touch List navigation requires an exact saved-color identifier"); return
        }
        // A final observation after gesture 12 can succeed; gesture 13 is forbidden.
        for attempt in 0...12 {
            let root = try app.snapshot()
            var pending: [(any XCUIElementSnapshot, Bool)] = [(root, false)]
            var lists: [CGRect] = [], navigation: [CGRect] = [], rows: [TCWatchListRow] = []
            var targetFrame: CGRect?, seen = Set<String>(), visited = 0
            var anchors: [(id: String, type: XCUIElement.ElementType, frame: CGRect)] = []
            var semanticLeaves: [(id: String, type: XCUIElement.ElementType, frame: CGRect)] = []
            let semanticTypes: [XCUIElement.ElementType] = [.button, .staticText, .image, .slider, .switch, .link]
            while let (element, inList) = pending.popLast() {
                visited += 1
                guard visited <= 512 else { XCTFail("Touch List snapshot exceeded 512 nodes"); return }
                if element.children.isEmpty,
                   semanticTypes.contains(element.elementType) {
                    semanticLeaves.append((element.identifier, element.elementType, element.frame))
                }
                let isList = element.elementType == .collectionView
                if isList { lists.append(element.frame) }
                if element.elementType == .navigationBar {
                    guard element.identifier == "TouchColor" else { XCTFail("Touch List is not the home destination"); return }
                    navigation.append(element.frame)
                }
                guard element.identifier != "BackButton" else { XCTFail("Touch List still has a pushed destination"); return }
                if inList {
                    let id = element.identifier
                    var index: Int32?
                    if ["watch.editor", "watch.photo", "watch.count"].contains(id) { index = -1 }
                    else if ["watch.transfer.open", "watch.privacy"].contains(id) { index = Int32.max }
                    else if id.hasPrefix("watch.color.") {
                        guard let parsed = Int32(id.dropFirst("watch.color.".count)), parsed >= 0,
                              id == "watch.color.\(parsed)" else { XCTFail("Invalid observed color identity"); return }
                        index = parsed
                    }
                    if let index {
                        guard seen.insert(id).inserted, rows.count < 24 else { XCTFail("Ambiguous or oversized touch List snapshot"); return }
                        let expectedType: XCUIElement.ElementType = id == "watch.count" ? .staticText : .button
                        guard element.elementType == expectedType, element.children.isEmpty else {
                            XCTFail("Touch List identity is not a unique semantic leaf: \(id)"); return
                        }
                        anchors.append((id, expectedType, element.frame))
                        rows.append(TCWatchListRow(index: index, frame: rect(element.frame)))
                        if id == identifier { targetFrame = element.frame }
                    }
                }
                pending.append(contentsOf: element.children.map { ($0, inList || isList) })
            }
            XCTAssertEqual(lists.count, 1, "Require one actual home List")
            XCTAssertEqual(navigation.count, 1, "Require one current home navigation bar")
            let listFrame = try XCTUnwrap(lists.first), navigationFrame = try XCTUnwrap(navigation.first)
            var plan = TCWatchListDrag()
            let decision = rows.withUnsafeBufferPointer {
                TCWatchListPlan(rect(root.frame), rect(listFrame), rect(navigationFrame), targetIndex,
                    targetFrame == nil ? 0 : 1, rect(targetFrame ?? .zero), $0.baseAddress, $0.count, &plan)
            }
            let listQuery = app.collectionViews
            XCTAssertEqual(listQuery.count, 1)
            let list = listQuery.element(boundBy: 0)
            let targetQuery = list.descendants(matching: .any).matching(identifier: identifier)
            let button = app.buttons[identifier]
            func currentHome() -> Bool {
                listQuery.count == 1 && app.frame == root.frame && list.frame == listFrame
                    && app.navigationBars.count == 1 && app.navigationBars["TouchColor"].exists
                    && app.navigationBars["TouchColor"].frame == navigationFrame
                    && !app.buttons["BackButton"].exists && app.alerts.count == 0 && app.sheets.count == 0
            }
            func currentTarget() -> Bool {
                let matches = targetQuery.count
                guard let capturedTarget = targetFrame else { return matches == 0 }
                guard matches == 1 else { return false }
                let target = targetQuery.element
                return target.exists && target.identifier == identifier && target.elementType == .button
                    && target.frame == capturedTarget
            }
            // Bind the captured geometry back to live public elements immediately
            // before either tap or drag. No stale coordinates cross a navigation.
            XCTAssertEqual(app.frame, root.frame)
            XCTAssertEqual(list.frame, listFrame)
            XCTAssertEqual(app.navigationBars["TouchColor"].frame, navigationFrame)
            // Action-only partial target: do not weaken the later tap:false
            // full-row visual/order observation or any Crown expectation.
            if tap, decision == TCWatchListEarlier || decision == TCWatchListLater,
               let capturedTarget = targetFrame {
                var point = TCWatchListPoint()
                if TCWatchListPartialTapPoint(plan.content, rect(capturedTarget), &point) != 0 {
                    let covering = semanticLeaves.filter { TCWatchListPointTouches(rect($0.frame), point) != 0 }
                    guard covering.count == 1, covering[0].id == identifier,
                          covering[0].type == .button, covering[0].frame == capturedTarget else {
                        XCTFail("Partial touch target has an ambiguous or covered center"); return
                    }
                    let leaves = semanticLeaves.map { rect($0.frame) }
                    func partialTargetReady(_ actualPoint: TCWatchListPoint) -> Bool {
                        guard currentHome(), currentTarget() else { return false }
                        // currentTarget already checks the List match, existence,
                        // identifier, type and frame. Also reject a duplicate outside it.
                        let matches = app.buttons.matching(identifier: identifier).count
                        guard matches == 1, button.children(matching: .any).count == 0 else { return false }
                        let hittable = button.isHittable, liveFrame = button.frame
                        return leaves.withUnsafeBufferPointer {
                            TCWatchListPartialTapReady(plan.content, rect(capturedTarget), rect(liveFrame),
                                $0.baseAddress, $0.count, matches, 1, hittable ? 1 : 0, 1, actualPoint) != 0
                        }
                    }
                    guard partialTargetReady(point) else {
                        XCTFail("Partial touch target became hidden, stale or non-hittable"); return
                    }
                    let coordinate = button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
                    let screenPoint = coordinate.screenPoint
                    let actualPoint = TCWatchListPoint(x: Double(screenPoint.x), y: Double(screenPoint.y))
                    // Revalidate after coordinate resolution. Public hittability
                    // and known overlay checks are not pixel-level attestation.
                    guard partialTargetReady(actualPoint) else {
                        XCTFail("Partial touch target changed before its center tap"); return
                    }
                    print("WATCH_TOUCH_TARGET_TAP target=\(identifier) attempt=\(attempt) frame=\(capturedTarget) point=\(screenPoint)"); fflush(stdout)
                    coordinate.tap()
                    return
                }
            }
            if decision == TCWatchListReady {
                XCTAssertTrue(button.exists); XCTAssertTrue(button.isHittable)
                XCTAssertEqual(button.frame, try XCTUnwrap(targetFrame))
                XCTAssertTrue(TCWatchListContains(plan.content, rect(button.frame)) != 0)
                guard currentHome(), currentTarget() else {
                    XCTFail("Touch List target changed before tap"); return
                }
                if tap { button.tap() }
                return
            }
            guard decision == TCWatchListEarlier || decision == TCWatchListLater else {
                XCTFail("Touch List direction/geometry is ambiguous for \(identifier), attempt \(attempt)"); return
            }
            guard attempt < 12 else { XCTFail("Saved color remained unreachable after 12 bounded touch drags"); return }
            // Preserve the original plan whenever a reviewed leaf covers its
            // start. Only a genuine gap permits a separate midpoint-based path.
            // No live failure may switch to another candidate or reset the cap.
            var gesture = plan, usedGap: Int32 = 0
            var liveAnchorState = "not-queried", validationMilliseconds = 0
            func diagnostic(_ event: String, reason: String, anchor: String) {
                let details = anchors.map { "\($0.id)=\($0.frame)" }.joined(separator: ";")
                let diagnostic = "WATCH_TOUCH_ANCHOR_\(event) case=\(name) reason=\(reason) attempt=\(attempt) target=\(identifier) "
                    + "targetFrame=\(String(describing: targetFrame)) mode=\(usedGap == 1 ? "gap" : "original") anchor=\(anchor) "
                    + "viewport=\(root.frame) list=\(listFrame) navigation=\(navigationFrame) "
                    + "originalStart=(\(plan.start.x),\(plan.start.y)) originalEnd=(\(plan.end.x),\(plan.end.y)) "
                    + "start=(\(gesture.start.x),\(gesture.start.y)) end=(\(gesture.end.x),\(gesture.end.y)) "
                    + "validationMilliseconds=\(validationMilliseconds) live=\(liveAnchorState) rows=\(details)"
                print(String(diagnostic.prefix(4096))); fflush(stdout)
            }
            func failAnchor(_ reason: String) {
                diagnostic("REJECT", reason: reason, anchor: "not-admitted")
                XCTFail("Touch List anchor rejected: \(reason)")
            }
            let frames = anchors.map { rect($0.frame) }, leaves = semanticLeaves.map { rect($0.frame) }
            let anchorIndex = frames.withUnsafeBufferPointer { rowFrames in
                leaves.withUnsafeBufferPointer { semanticFrames in
                    TCWatchListSelectTouch(&plan, rowFrames.baseAddress, rowFrames.count,
                        semanticFrames.baseAddress, semanticFrames.count, &gesture, &usedGap)
                }
            }
            guard anchorIndex >= 0 else { failAnchor("blocked-or-no-unique-safe-start"); return }
            let captured = anchors[Int(anchorIndex)]
            let coveringLeaves = semanticLeaves.filter { TCWatchListPointTouches(rect($0.frame), gesture.start) != 0 }
            liveAnchorState = "semantic-covers=\(coveringLeaves.count)"
            guard coveringLeaves.count == 1, coveringLeaves[0].id == captured.id,
                  coveringLeaves[0].type == captured.type, coveringLeaves[0].frame == captured.frame else {
                failAnchor("overlapping-snapshot-leaf"); return
            }
            let anchorQuery = list.descendants(matching: .any).matching(identifier: captured.id)
            guard anchorQuery.count == 1 else { failAnchor("duplicate-or-missing-live-identity"); return }
            let anchor = anchorQuery.element
            func anchorReady() -> Bool {
                let started = ProcessInfo.processInfo.systemUptime
                defer { validationMilliseconds += Int((ProcessInfo.processInfo.systemUptime - started) * 1000) }
                liveAnchorState = "revalidating-home-and-target"
                guard currentHome(), currentTarget() else { return false }
                let matches = anchorQuery.count
                liveAnchorState = "matches=\(matches);revalidating-identity"
                guard matches == 1, anchor.exists, anchor.identifier == captured.id,
                      anchor.elementType == captured.type,
                      anchor.children(matching: .any).count == 0 else { return false }
                let hittable = anchor.isHittable, liveFrame = anchor.frame
                liveAnchorState = "id=\(captured.id);matches=\(matches);hittable=\(hittable);frame=\(liveFrame)"
                return TCWatchListTouchAnchorReady(&gesture, rect(captured.frame), rect(liveFrame),
                    matches, 1, hittable ? 1 : 0, 1) != 0
            }
            guard anchorReady() else { failAnchor("occluded-stale-or-wrong-home"); return }
            let origin = list.coordinate(withNormalizedOffset: .zero)
            let start = origin.withOffset(CGVector(dx: CGFloat(gesture.start.x) - listFrame.minX, dy: CGFloat(gesture.start.y) - listFrame.minY))
            let end = origin.withOffset(CGVector(dx: CGFloat(gesture.end.x) - listFrame.minX, dy: CGFloat(gesture.end.y) - listFrame.minY))
            XCTAssertEqual(start.screenPoint, CGPoint(x: CGFloat(gesture.start.x), y: CGFloat(gesture.start.y)))
            XCTAssertEqual(end.screenPoint, CGPoint(x: CGFloat(gesture.end.x), y: CGFloat(gesture.end.y)))
            XCTAssertEqual(list.frame, listFrame)
            // Revalidate after coordinate resolution, immediately before dispatch.
            // isHittable is public element-level evidence, not pixel hit-testing.
            guard anchorReady() else { failAnchor("anchor-changed-before-drag"); return }
            // Reuse captured fields and the final live result; no logging-only query.
            diagnostic("PLAN", reason: "admitted", anchor: "\(captured.id):\(captured.type):\(captured.frame)")
            // Public XCUIAutomation API, documented for watchOS. Exact Xcode 27
            // compilation and 40/49mm runtime behavior remain native proof gates.
            start.press(forDuration: 0.01, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)
        }
    }

    @MainActor func testEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder() throws {
        func reach(_ identifier: String) throws {
            let button = app.buttons[identifier]
            for attempt in 0..<12 {
                if button.exists && button.isHittable { break }
                var above = button.exists && button.frame.midY < app.frame.midY
                if !button.exists, let targetIndex = Int(identifier.replacingOccurrences(of: "watch.color.", with: "")) {
                    // Lists virtualize offscreen rows. A fast full-screen swipe can
                    // skip color 0 on the 40mm display; use the actual neighboring
                    // row identities to reverse direction instead of scrolling
                    // farther toward the end after every unsuccessful query.
                    let indices = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "watch.color."))
                        .allElementsBoundByIndex.compactMap { Int($0.identifier.dropFirst("watch.color.".count)) }
                    if let first = indices.min() { above = targetIndex < first }
                }
                if identifier.hasPrefix("watch.color.") {
                    // Apple's XCTest contract: positive scrolls UP, negative
                    // scrolls DOWN, independent of wrist orientation. The old
                    // reversed sign kept both actual sizes at the home header.
                    // Keep small bounded Crown movement and the exact target.
                    XCTAssertFalse(app.buttons["BackButton"].exists, app.debugDescription)
                    print("WATCH_LIST_CROWN: target=\(identifier) above=\(above)"); fflush(stdout)
                    try logHomeListFrame("return.\(identifier).\(attempt).before")
                    XCUIDevice.shared.rotateDigitalCrown(delta: above ? 0.1 : -0.1)
                    try logHomeListFrame("return.\(identifier).\(attempt).after")
                } else if above { app.swipeDown(velocity: .slow) } else { app.swipeUp(velocity: .slow) }
            }
            XCTAssertTrue(button.isHittable, app.debugDescription); button.tap()
        }
        func back() { app.buttons["BackButton"].tap() }
        app.buttons["watch.editor"].tap(); app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        try reach("watch.save"); app.buttons["watch.save"].tap(); back()
        try reach("watch.color.1")
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        try reach("watch.edit.copy")
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fd0000")
        try reach("watch.save"); back(); back()
        for _ in 0..<4 { app.swipeDown() }
        try reach("watch.color.0"); try reach("watch.delete.0")
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["watch.count"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["watch.count"].label, "2")
        for _ in 0..<6 where !app.buttons["watch.color.1"].exists { app.swipeUp() }
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"), app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.1"].label.contains("#fd0000"), app.debugDescription)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch edit copy and delete preserve palette order"; image.lifetime = .keepAlways; add(image)
    }

    @MainActor func testTouchEditSavedCopyDeleteOneDuplicateAndRelaunchKeepsOrder() throws {
        func reach(_ identifier: String) throws {
            if identifier.hasPrefix("watch.color.") {
                try reachSavedColorByTouch(identifier)
                return
            }
            // Preserve the existing successful editor/detail gesture path.
            let button = app.buttons[identifier]
            for _ in 0..<12 {
                if button.exists && button.isHittable { break }
                let above = button.exists && button.frame.midY < app.frame.midY
                if above { app.swipeDown(velocity: .slow) } else { app.swipeUp(velocity: .slow) }
            }
            XCTAssertTrue(button.isHittable, app.debugDescription); button.tap()
        }
        func back() { app.buttons["BackButton"].tap() }
        app.buttons["watch.editor"].tap(); app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        try reach("watch.save"); app.buttons["watch.save"].tap(); back()
        try reach("watch.color.1")
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fe0000")
        try reach("watch.edit.copy")
        app.buttons["watch.component.down"].tap()
        XCTAssertEqual(app.staticTexts["watch.hex"].label, "#fd0000")
        try reach("watch.save"); back(); back()
        try reach("watch.color.0"); try reach("watch.delete.0")
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["watch.count"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["watch.count"].label, "2")
        try reachSavedColorByTouch("watch.color.1", tap: false)
        XCTAssertTrue(app.buttons["watch.color.0"].label.contains("#fe0000"), app.debugDescription)
        XCTAssertTrue(app.buttons["watch.color.1"].label.contains("#fd0000"), app.debugDescription)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Watch touch edit copy and delete preserve palette order"; image.lifetime = .keepAlways; add(image)
    }

}
