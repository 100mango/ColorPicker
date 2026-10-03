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
        app.terminate(); try? FileManager.default.removeItem(at: fixture)
        UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite)
    }
    private func openFile(_ url: URL) {
        app.buttons["image.open"].click()
        app.typeKey("g", modifierFlags: [.command, .shift])
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.typeText(url.path)
        app.typeKey(.return, modifierFlags: [])
        app.typeKey(.return, modifierFlags: [])
    }
    private func assertHex(_ expected: String) {
        let value = app.staticTexts["sample.hex"]
        XCTAssertTrue(value.waitForExistence(timeout: 8))
        expectation(for: NSPredicate(format: "value == %@ OR label == %@", expected, expected), evaluatedWith: value)
        waitForExpectations(timeout: 8)
    }
    func testNativeFileSamplingZoomPalettePersistenceAndPrivacy() {
        openFile(fixture)
        assertHex("#ff00ff")
        let canvas = app.images["image.canvas"]
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click()
        assertHex("#ff0000")
        app.buttons["sample.save"].click(); app.buttons["sample.save"].click()
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
        app.buttons["sample.copy"].click()
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "#ff0000")
        app.buttons["Zoom in"].click()
        XCTAssertTrue(app.staticTexts["sample.zoom.value"].exists)
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Native Mac sampled source and ordered palette"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["privacy.open"].click()
        XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 5))
        app.buttons["privacy.close"].click()
        app.terminate(); app.launchArguments = []; app.launch()
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 8))
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
    }
    func testPasteImageAndOpenCancelRetainSource() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try! Data(contentsOf: fixture), forType: .png)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
        app.buttons["image.open"].click()
        app.typeKey(.escape, modifierFlags: [])
        assertHex("#ff00ff")
        app.buttons["Pixel above"].click(); assertHex("#00ff00")
        app.buttons["Previous pixel"].click(); assertHex("#ff0000")
    }
}
