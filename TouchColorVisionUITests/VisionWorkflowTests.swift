import XCTest
import UIKit
import UniformTypeIdentifiers

final class VisionWorkflowTests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=vision")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=vision; unexpected interruption; no alert action taken")
        }
        continueAfterFailure = false
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.vision-ui.\(UUID())"
        let chinese = name.contains("Chinese")
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", chinese ? "(zh-Hans)" : "(en)", "-AppleLocale", chinese ? "zh_CN" : "en_US"]; app.launch()
    }
    override func tearDownWithError() throws {
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
        if (testRun?.totalFailureCount ?? 0) > 0 { capture("Native Vision failure"); print("VISION_FAILURE_AX: \(app.debugDescription)") }
        app.terminate()
        try super.tearDownWithError()
    }
    private func capture(_ name: String) {
        // A failed visual checkpoint remains an XCTest failure, while later functional
        // assertions still execute so a simulator capture problem cannot hide app defects.
        let previousFailureBehavior = continueAfterFailure
        continueAfterFailure = true
        defer { continueAfterFailure = previousFailureBehavior }
        // The spatial XCTest screenshot API can crop or stall. Hold this real UI state
        // while the CI host uses documented simctl screenshot, with a bounded acknowledgement.
        let id = UUID().uuidString
        let root = FileManager.default.temporaryDirectory
        let request = root.appendingPathComponent("TouchColor-capture-\(id).json")
        let acknowledgement = root.appendingPathComponent("TouchColor-capture-\(id).ack")
        defer { try? FileManager.default.removeItem(at: request); try? FileManager.default.removeItem(at: acknowledgement) }
        do { try JSONSerialization.data(withJSONObject: ["id": id, "name": name]).write(to: request) }
        catch { XCTFail("Could not request simulator checkpoint: \(error)"); return }
        print("TOUCHCOLOR_CAPTURE_REQUEST \(id)"); fflush(stdout)
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in FileManager.default.fileExists(atPath: acknowledgement.path) }, object: nil)
        guard XCTWaiter.wait(for: [ready], timeout: 85) == .completed else { XCTFail("Simulator checkpoint acknowledgement timed out"); return }
        let result = (try? Data(contentsOf: acknowledgement)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        XCTAssertEqual(result?["success"] as? Bool, true, "Simulator checkpoint failed: \(String(describing: result))")
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
        let picker = app.navigationBars["Photos"]
        XCTAssertTrue(picker.waitForExistence(timeout: 30), app.debugDescription)
        let scroll = app.scrollViews["photosView_content_scroll_view"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 30), app.debugDescription)
        // The exact system grid-image identifier is unique in the observed picker.
        // Avoid a second nested remote-subtree query after checking its scroll view.
        let image = app.images["PXGGridLayout-Info"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 45), app.debugDescription)
        image.tap()
        hex("#ff00ff")
    }
    private func paste() {
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = true
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 200), format: format).image { context in
            let colors: [UIColor] = [.red, .green, .blue, .yellow, .magenta, .cyan]
            for index in 0..<6 {
                context.cgContext.setFillColor(colors[index].cgColor)
                context.cgContext.fill(CGRect(x: (index % 3) * 100, y: (index / 3) * 100, width: 100, height: 100))
            }
        }
        UIPasteboard.general.setData(image.pngData()!, forPasteboardType: UTType.png.identifier)
        let paste = app.buttons["image.paste"]
        XCTAssertTrue(paste.waitForExistence(timeout: 20), app.debugDescription)
        paste.tap(); hex("#ff00ff")
    }
    func testRealPhotosImport() { photo(); capture("Native Vision actual system Photos import") }
    func testRealPastePrecisionZoomPaletteAndRelaunch() {
        paste()
        app.buttons["sample.save"].tap(); app.buttons["sample.save"].tap()
        app.buttons["sample.above"].tap(); hex("#00ff00")
        app.buttons["sample.zoom.in"].tap()
        XCTAssertTrue(app.staticTexts["sample.zoom.value"].exists)
        app.buttons["sample.center"].tap(); hex("#ff00ff")
        capture("Native Vision pasted image with precision sampling and zoom")
        app.buttons["privacy.open"].tap(); XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 5)); app.buttons["privacy.close"].tap()
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        let count = app.staticTexts["palette.count"]
        XCTAssertTrue(count.waitForExistence(timeout: 15)); XCTAssertEqual(count.label, "2")
        capture("Native Vision ordered palette after relaunch")
    }
    func testNativeExportSaveAndReopenActualPNG() {
        executionTimeAllowance = 300
        paste(); app.buttons["image.export"].tap()
        XCTAssertTrue(app.navigationBars["DOCSidebarView"].waitForExistence(timeout: 45), app.debugDescription)
        let save = app.buttons["DOCPicker.actionButton"]
        XCTAssertTrue(save.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(save.label, "Save")
        XCTAssertTrue(app.textFields["DOCPicker.filenameTextField"].exists)
        print("VISION_EXPORT_PANEL_READY: actual Save and filename controls verified")
        save.tap()
        XCTAssertTrue(app.buttons["export.reopen"].waitForExistence(timeout: 12), app.debugDescription)
        app.buttons["export.reopen"].tap(); hex("#ff00ff")
        app.buttons["sample.above"].tap(); hex("#00ff00")
        capture("Native Vision actual exported PNG reopened")
    }
    func testNativePaletteExportReopensActualChangedSelectionAndDuplicates() {
        // This complete route includes three saves, system Files export/reopen,
        // three separate native menus and artifact readback; it exceeded 180 seconds
        // while still progressing through the genuine Save controls on 7c8148a.
        executionTimeAllowance = 360
        paste(); app.buttons["sample.save"].tap(); app.buttons["sample.save"].tap()
        app.buttons["sample.above"].tap(); hex("#00ff00"); app.buttons["sample.save"].tap()
        app.buttons["palette.export"].tap()
        XCTAssertTrue(app.navigationBars["DOCSidebarView"].waitForExistence(timeout: 45), app.debugDescription)
        let save = app.buttons["DOCPicker.actionButton"]
        XCTAssertTrue(save.waitForExistence(timeout: 15)); XCTAssertEqual(save.label, "Save"); save.tap()
        XCTAssertTrue(app.buttons["export.reopen"].waitForExistence(timeout: 15), app.debugDescription)
        app.buttons["export.reopen"].tap()
        let count = app.staticTexts["palette.count"]
        let appended = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == '6' OR value == '6'"), object: count)
        XCTAssertEqual(XCTWaiter.wait(for: [appended], timeout: 15), .completed, app.debugDescription)
        // Read back every appended entry through its distinct production Copy action.
        // Query the observed native Button directly, without an all-descendants scan.
        var reopened: [String] = []
        for index in 3..<6 {
            app.buttons["palette.actions.\(index)"].tap()
            let copy = app.buttons["palette.copy.\(index)"]
            XCTAssertTrue(copy.waitForExistence(timeout: 5), app.debugDescription); copy.tap()
            reopened.append(UIPasteboard.general.string ?? "")
        }
        XCTAssertEqual(reopened, ["#ff00ff", "#ff00ff", "#00ff00"])
        print("VISION_JSON_REOPEN_VERIFIED: actual Copy values magenta, magenta, green")
        capture("Native Vision changed-color JSON export reopened with duplicates")
    }
    func testRealFilesPickerSelectsExportedPNG() {
        executionTimeAllowance = 360
        paste(); app.buttons["image.export"].tap()
        let filename = "TouchSelect-" + String(UUID().uuidString.prefix(6))
        let field = app.textFields["DOCPicker.filenameTextField"]
        XCTAssertTrue(field.waitForExistence(timeout: 45), app.debugDescription)
        field.tap()
        if let value = field.value as? String, !value.isEmpty {
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
        field.typeText(filename)
        let save = app.buttons["DOCPicker.actionButton"]
        XCTAssertTrue(save.waitForExistence(timeout: 10)); XCTAssertEqual(save.label, "Save"); save.tap()
        XCTAssertTrue(app.buttons["export.reopen"].waitForExistence(timeout: 15), app.debugDescription)
        // Leave a different selection before opening the genuine system picker.
        // A cancelled or ineffective selection must not satisfy the import oracle.
        app.buttons["sample.above"].tap(); hex("#00ff00")
        app.buttons["image.open"].tap()
        let picker = app.navigationBars["DOCSidebarView"]
        XCTAssertTrue(picker.waitForExistence(timeout: 45), app.debugDescription)
        let savedFile = app.cells.matching(NSPredicate(format: "label CONTAINS %@", filename)).firstMatch
        XCTAssertTrue(savedFile.waitForExistence(timeout: 30), app.debugDescription)
        savedFile.tap()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: picker)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 20), .completed, app.debugDescription)
        hex("#ff00ff")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", filename)).firstMatch.waitForExistence(timeout: 10), app.debugDescription)
        app.buttons["sample.above"].tap(); hex("#00ff00")
        print("VISION_FILES_SELECTION_VERIFIED: actual saved PNG selected in system Files and sampled")
        capture("Native Vision actual Files picker selected exported PNG")
    }
    func testChinesePasteAndPrecisionControls() {
        paste(); app.buttons["sample.above"].tap(); hex("#00ff00")
        XCTAssertEqual(app.buttons["sample.save"].label, "保存颜色")
        app.buttons["sample.save"].tap()
        capture("Native Vision Chinese pasted image and precision controls")
    }
    func testNativeFileAndPhotosCancelRepeatedly() {
        XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 20))
        for key in ["image.open", "image.photos"] {
            app.buttons[key].tap()
            let bar = app.navigationBars[key == "image.open" ? "DOCSidebarView" : "Photos"]
            XCTAssertTrue(bar.waitForExistence(timeout: 45), app.debugDescription)
            let cancel = bar.buttons["Cancel"]
            XCTAssertTrue(cancel.waitForExistence(timeout: 10), app.debugDescription); cancel.tap()
            let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: bar)
            XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 20), .completed, app.debugDescription)
            XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 5))
        }
        XCTAssertEqual(app.staticTexts["palette.count"].label, "0")
    }
    @MainActor private func audit(_ state: String) throws {
        if #available(visionOS 27.0, *) {
            print("VISION_ACCESSIBILITY_AUDIT_BEGIN: \(state)")
            try app.performAccessibilityAudit(for: .all) { issue in
                print("VISION_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                return false
            }
            print("VISION_ACCESSIBILITY_AUDIT_PASS: \(state)")
        } else { throw XCTSkip("Native audit qualification targets the installed visionOS 27 runtime") }
    }
    @MainActor func testOfficialAccessibilityEmptyAndPastedCanvas() throws {
        XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 20))
        try audit("empty workspace")
        paste(); app.buttons["sample.save"].tap()
        try audit("pasted image and palette")
    }

    @MainActor func testOfficialAccessibilityCorruptPasteRetainsPreviousSource() throws {
        paste()
        UIPasteboard.general.setData(Data("deliberately invalid synthetic PNG".utf8), forPasteboardType: UTType.png.identifier)
        app.buttons["image.paste"].tap()
        XCTAssertTrue(app.buttons["OK"].waitForExistence(timeout: 15), app.debugDescription)
        try audit("corrupt pasted image error")
        app.buttons["OK"].tap(); hex("#ff00ff")
    }

}
