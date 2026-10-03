import XCTest
import UIKit
import UniformTypeIdentifiers

final class VisionWorkflowTests: XCTestCase {
    private var app: XCUIApplication!
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.vision-ui.\(UUID())"
        let chinese = name.contains("Chinese")
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", chinese ? "(zh-Hans)" : "(en)", "-AppleLocale", chinese ? "zh_CN" : "en_US"]; app.launch()
    }
    override func tearDownWithError() throws {
        if (testRun?.totalFailureCount ?? 0) > 0 { capture("Native Vision failure"); print("VISION_FAILURE_AX: \(app.debugDescription)") }
        app.terminate()
    }
    private func capture(_ name: String) {
        // The per-app vision capture cropped the magnified scene to logical window bounds.
        // Retain the actual simulator display so the whole native window can be inspected.
        guard let bytes = XCUIScreen.main.screenshot().image.jpegData(compressionQuality: 0.5), bytes.count <= 3_000_000 else { return }
        let shot = XCTAttachment(data: bytes, uniformTypeIdentifier: "public.jpeg"); shot.name = name; shot.lifetime = .keepAlways; add(shot)
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
        paste(); app.buttons["image.export"].tap()
        let save = app.buttons["Save"].firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 10), app.debugDescription)
        print("VISION_EXPORT_PANEL_AX: \(app.debugDescription)")
        save.tap()
        XCTAssertTrue(app.buttons["export.reopen"].waitForExistence(timeout: 12), app.debugDescription)
        app.buttons["export.reopen"].tap(); hex("#ff00ff")
        app.buttons["sample.above"].tap(); hex("#00ff00")
        capture("Native Vision actual exported PNG reopened")
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
            let cancel = app.buttons["Cancel"].firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 10), app.debugDescription); cancel.tap()
            XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 5))
        }
        XCTAssertEqual(app.staticTexts["palette.count"].label, "0")
    }
}
