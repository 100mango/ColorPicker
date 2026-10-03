import XCTest
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

@MainActor final class TouchColorMacUITests: XCTestCase {
    private var app: XCUIApplication!
    private var fixture: URL!
    private var suite = ""
    override func setUpWithError() throws {
        continueAfterFailure = false
        suite = "TouchColor.mac-ui.\(UUID())"
        fixture = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-fixture-\(UUID()).png")
        let bytes: [UInt8] = [255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255, 255,0,255,255, 0,255,255,255]
        let image = CGImage(width: 3, height: 2, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 12,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                            provider: CGDataProvider(data: Data(bytes) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
        let destination = CGImageDestinationCreateWithURL(fixture as CFURL, UTType.png.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(destination, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = suite
        app.launchArguments = ["--ui-test-reset"]; app.launch()
    }
    override func tearDownWithError() throws {
        if testRun?.hasSucceeded == false {
            let failure = XCTAttachment(screenshot: app.screenshot())
            failure.name = "Native Mac UI failure state"; failure.lifetime = .keepAlways; add(failure)
            print("NATIVE_UI_FAILURE_AX: \(app.debugDescription)")
        }
        app.terminate(); try? FileManager.default.removeItem(at: fixture)
        UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite)
    }
    private func openFile(_ url: URL) {
        app.buttons["image.open"].click()
        app.typeKey("g", modifierFlags: [.command, .shift])
        let field = app.textFields["PathTextField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5), app.debugDescription)
        field.typeKey("a", modifierFlags: [.command])
        field.typeText(url.path)
        app.typeKey(.return, modifierFlags: [])
        let open = app.dialogs["open-panel"].buttons["OKButton"]
        XCTAssertTrue(open.waitForExistence(timeout: 5), app.debugDescription)
        open.click()
    }
    private func assertHex(_ expected: String) {
        let value = app.staticTexts["sample.hex"]
        XCTAssertTrue(value.waitForExistence(timeout: 8))
        let expectedValue = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@ OR label == %@", expected, expected), object: value)
        let outcome = XCTWaiter.wait(for: [expectedValue], timeout: 8)
        XCTAssertEqual(outcome, .completed, "Expected \(expected), actual value \(String(describing: value.value)), label \(value.label). \(app.debugDescription)")
    }
    func testNativeFileSamplingZoomPalettePersistenceAndPrivacy() {
        openFile(fixture)
        assertHex("#ff00ff")
        let canvas = app.images["image.canvas"]
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click()
        assertHex("#ff0000")
        app.typeKey(.rightArrow, modifierFlags: []); assertHex("#00ff00")
        app.typeKey(.leftArrow, modifierFlags: []); assertHex("#ff0000")
        app.buttons["sample.save"].click(); app.buttons["sample.save"].click()
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
        app.buttons["sample.copy"].click()
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "#ff0000")
        let unzoomedFrame = canvas.frame
        app.buttons["sample.zoom.in"].click()
        XCTAssertGreaterThan(canvas.frame.width, unzoomedFrame.width * 1.5)
        XCTAssertTrue(app.staticTexts["sample.zoom.value"].exists)
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        let window = app.windows.firstMatch
        let edge = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1)).withOffset(CGVector(dx: -2, dy: -2))
        edge.click(forDuration: 0.2, thenDragTo: edge.withOffset(CGVector(dx: -120, dy: -60)))
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Mac sampled source and ordered palette"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["privacy.open"].click()
        XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 5))
        app.buttons["privacy.close"].click()
        app.terminate(); app.launchArguments = []; app.launch()
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 8))
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
    }
    private func saveFile(_ url: URL) {
        XCTAssertTrue(app.dialogs.buttons["OKButton"].firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        print("NATIVE_SAVE_PANEL_AX: \(app.debugDescription)")
        // Use the actual native Save As field; choose its parent directory separately.
        let name = app.dialogs.textFields["saveAsNameTextField"].firstMatch
        XCTAssertTrue(name.waitForExistence(timeout: 5), app.debugDescription)
        name.typeKey("a", modifierFlags: [.command])
        name.typeText(url.lastPathComponent)
        app.typeKey("g", modifierFlags: [.command, .shift])
        let field = app.textFields["PathTextField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5), app.debugDescription)
        field.typeKey("a", modifierFlags: [.command])
        field.typeText(url.deletingLastPathComponent().path)
        app.typeKey(.return, modifierFlags: [])
        let save = app.dialogs.buttons["OKButton"].firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 5), app.debugDescription)
        save.click()
    }
    func testNativePaletteAndImageExportReopenAndDelete() throws {
        openFile(fixture); assertHex("#ff00ff")
        app.buttons["sample.save"].click(); app.buttons["sample.save"].click()
        let paletteURL = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-palette-\(UUID()).json")
        let imageURL = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-image-\(UUID()).png")
        defer { try? FileManager.default.removeItem(at: paletteURL); try? FileManager.default.removeItem(at: imageURL) }
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
        XCTAssertTrue(app.buttons["palette.export"].isHittable, app.debugDescription)
        app.buttons["palette.export"].click(); saveFile(paletteURL)
        let stored = try JSONDecoder().decode([String].self, from: Data(contentsOf: paletteURL))
        XCTAssertEqual(stored, ["#ff00ff", "#ff00ff"])
        openFile(paletteURL)
        let count = app.staticTexts["palette.count"]
        expectation(for: NSPredicate(format: "value == '4' OR label == '4'"), evaluatedWith: count)
        waitForExpectations(timeout: 5)
        app.descendants(matching: .any).matching(identifier: "palette.actions.1").firstMatch.click()
        app.menuItems["palette.delete.1"].click()
        XCTAssertEqual(count.value as? String ?? count.label, "3")
        app.buttons["image.export"].click(); saveFile(imageURL)
        expectation(for: NSPredicate { _,_ in FileManager.default.fileExists(atPath: imageURL.path) }, evaluatedWith: nil)
        waitForExpectations(timeout: 8)
        openFile(imageURL); assertHex("#ff00ff")
        let canvas = app.images["image.canvas"]
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click(); assertHex("#ff0000")
    }
    func testSimplifiedChineseNativeSamplingFlowAndScreenshot() {
        app.terminate()
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launch()
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try! Data(contentsOf: fixture), forType: .png)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
        app.buttons["sample.save"].click()
        XCTAssertTrue(app.staticTexts["调色板"].exists)
        XCTAssertEqual(app.buttons["sample.save"].label, "保存颜色")
        XCTAssertTrue(app.windows.firstMatch.frame.contains(app.buttons["sample.above"].frame), app.debugDescription)
        XCTAssertTrue(app.buttons["sample.above"].isHittable, app.debugDescription)
        app.buttons["sample.above"].click(); assertHex("#00ff00")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "Native Mac Simplified Chinese sampling and palette"
        shot.lifetime = .keepAlways; add(shot)
    }
    func testPasteImageAndOpenCancelRetainSource() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try! Data(contentsOf: fixture), forType: .png)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
        app.buttons["image.open"].click()
        app.dialogs["open-panel"].buttons["CancelButton"].click()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.dialogs["open-panel"])
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 5), .completed, app.debugDescription)
        assertHex("#ff00ff")
        XCTAssertTrue(app.windows.firstMatch.frame.contains(app.buttons["sample.above"].frame), app.debugDescription)
        XCTAssertTrue(app.buttons["sample.above"].isHittable, app.debugDescription)
        app.buttons["sample.above"].click(); assertHex("#00ff00")
        app.buttons["sample.previous"].click(); assertHex("#ff0000")
    }
}
