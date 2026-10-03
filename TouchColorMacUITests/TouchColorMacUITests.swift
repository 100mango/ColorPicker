import XCTest
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import CryptoKit
import AVFoundation

@MainActor final class TouchColorMacUITests: XCTestCase {
    private var app: XCUIApplication!
    private var fixture: URL!
    private var suite = ""
    private var expectedUID: Int?
    private var expectsSandbox = false
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
        // Resolve the actual adjacent Debug product, never another registered build with this bundle ID.
        var products = Bundle(for: Self.self).bundleURL
        for _ in 0..<4 { products.deleteLastPathComponent() }
        let applicationURL = products.appendingPathComponent("TouchColor.app")
        let metadata = try XCTUnwrap(Bundle(url: applicationURL)?.infoDictionary)
        XCTAssertEqual(metadata["CFBundleIdentifier"] as? String, "com.mango.touchColor")
        XCTAssertEqual(products.lastPathComponent, "Debug")
        XCTAssertTrue(FileManager.default.fileExists(atPath: applicationURL.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib").path))
        print("NATIVE_UI_EXACT_APP: \(applicationURL.path)")
        app = XCUIApplication(url: applicationURL)
        app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = suite
        expectsSandbox = applicationURL.path.contains("/mac-sandbox/")
        if name.contains("SandboxBoundary") {
            var derivedData = products
            for _ in 0..<3 { derivedData.deleteLastPathComponent() }
            let record = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(contentsOf: derivedData.appendingPathComponent("probe-info.json"))) as? [String: Any])
            XCTAssertEqual(record["readControl"] as? Bool, true); XCTAssertEqual(record["writeControl"] as? Bool, true)
            expectedUID = record["uid"] as? Int
            app.launchEnvironment["TOUCHCOLOR_SANDBOX_PROBE_FILE"] = try XCTUnwrap(record["file"] as? String)
        }
        app.launchArguments = ["--ui-test-reset"]; app.launch()
        let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.mango.touchColor").filter { !$0.isTerminated }
        XCTAssertEqual(running.count, 1)
        let actual = try XCTUnwrap(running.first)
        XCTAssertEqual(actual.bundleURL?.resolvingSymlinksInPath(), applicationURL.resolvingSymlinksInPath())
        let executable = try XCTUnwrap(actual.executableURL)
        let digest = SHA256.hash(data: try Data(contentsOf: executable)).map { String(format: "%02x", $0) }.joined()
        let debugDylib = applicationURL.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib")
        let logicDigest = SHA256.hash(data: try Data(contentsOf: debugDylib)).map { String(format: "%02x", $0) }.joined()
        print("NATIVE_UI_LOGIC_SHA256: \(logicDigest)")
        XCTAssertTrue(app.menuBars.menuBarItems["TouchColor"].waitForExistence(timeout: 5), app.debugDescription)
        print("NATIVE_UI_RUNNING_APP path=\(actual.bundleURL?.path ?? "") executable=\(executable.path) sha256=\(digest)")
    }
    override func tearDownWithError() throws {
        if let app {
            if (testRun?.totalFailureCount ?? 0) > 0 && app.state != .notRunning {
                let failure = XCTAttachment(screenshot: app.screenshot())
                failure.name = "Native Mac UI failure state"; failure.lifetime = .keepAlways; add(failure)
                print("NATIVE_UI_FAILURE_AX: \(app.debugDescription)")
            }
            app.terminate()
        }
        if let fixture { try? FileManager.default.removeItem(at: fixture) }
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
        let changedPaletteURL = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-changed-palette-\(UUID()).json")
        defer {
            for url in [paletteURL, imageURL, changedPaletteURL] where FileManager.default.fileExists(atPath: url.path) {
                try? FileManager.default.removeItem(at: url)
            }
        }
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
        XCTAssertTrue(app.buttons["palette.export"].isHittable, app.debugDescription)
        app.buttons["palette.export"].click(); saveFile(paletteURL)
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard let size = try? paletteURL.resourceValues(forKeys: [.fileSizeKey]).fileSize else { return false }
            return size > 0
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 8), .completed, app.debugDescription)
        let stored = try JSONDecoder().decode([String].self, from: Data(contentsOf: paletteURL))
        XCTAssertEqual(stored, ["#ff00ff", "#ff00ff"])
        openFile(paletteURL)
        let count = app.staticTexts["palette.count"]
        expectation(for: NSPredicate(format: "value == '4' OR label == '4'"), evaluatedWith: count)
        waitForExpectations(timeout: 5)
        app.menuButtons["palette.actions.1"].click()
        app.menuItems["palette.delete.1"].click()
        XCTAssertEqual(count.value as? String ?? count.label, "3")
        app.buttons["image.export"].click(); saveFile(imageURL)
        expectation(for: NSPredicate { _,_ in FileManager.default.fileExists(atPath: imageURL.path) }, evaluatedWith: nil)
        waitForExpectations(timeout: 8)
        openFile(imageURL); assertHex("#ff00ff")
        let canvas = app.images["image.canvas"]
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click(); assertHex("#ff0000")
        app.buttons["sample.center"].click(); app.buttons["sample.above"].click(); assertHex("#00ff00")
        app.buttons["sample.save"].click()
        app.buttons["palette.export"].click(); saveFile(changedPaletteURL)
        let changedReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard let size = try? changedPaletteURL.resourceValues(forKeys: [.fileSizeKey]).fileSize else { return false }
            return size > 0
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [changedReady], timeout: 8), .completed)
        XCTAssertEqual(try JSONDecoder().decode([String].self, from: Data(contentsOf: changedPaletteURL)), ["#ff00ff", "#ff00ff", "#ff00ff", "#00ff00"])
    }
    func testSimplifiedChineseNativeSamplingFlowAndScreenshot() {
        app.terminate()
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launch()
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try! Data(contentsOf: fixture), forType: .png)
        XCTAssertTrue(app.buttons["image.paste"].waitForExistence(timeout: 10), app.debugDescription)
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
        XCTAssertTrue(app.buttons["image.paste"].waitForExistence(timeout: 10), app.debugDescription)
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
    func testActualNoCameraRouteDismissesWithoutRequestingPermission() throws {
        let types: [AVCaptureDevice.DeviceType]
        if #available(macOS 14, *) { types = [.builtInWideAngleCamera, .external, .continuityCamera] }
        else { types = [.builtInWideAngleCamera, .externalUnknown] }
        let devices = AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
        try XCTSkipIf(!devices.isEmpty, "No-device route requires a runner without camera hardware; no physical capture is requested by this test.")
        let permission = AVCaptureDevice.authorizationStatus(for: .video)
        for _ in 0..<2 {
            app.buttons["camera.open"].click()
            let status = app.staticTexts["camera.status"]
            XCTAssertTrue(status.waitForExistence(timeout: 5), app.debugDescription)
            XCTAssertTrue((status.value as? String ?? status.label).contains("No camera is available"))
            XCTAssertFalse(app.buttons["camera.start"].isEnabled)
            XCTAssertFalse(app.buttons["camera.freeze"].isEnabled)
            XCTAssertFalse(app.buttons["camera.save"].isEnabled)
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.name = "Native Mac actual no-camera status"; shot.lifetime = .keepAlways; add(shot)
            app.buttons["camera.close"].click()
            XCTAssertTrue(app.buttons["image.paste"].waitForExistence(timeout: 5))
        }
        XCTAssertEqual(AVCaptureDevice.authorizationStatus(for: .video), permission)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try Data(contentsOf: fixture), forType: .png)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
    }

    @MainActor private func audit(_ state: String) throws {
        if #available(macOS 27.0, *) {
            print("MAC_ACCESSIBILITY_AUDIT_BEGIN: \(state)")
            try app.performAccessibilityAudit(for: .all) { issue in
                print("MAC_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                print("MAC_ACCESSIBILITY_ISSUE_ELEMENT: \(String((issue.element?.debugDescription ?? "none").prefix(12_000)))")
                fflush(stdout)
                let details = "State: \(state)\nIssue: \(issue.compactDescription)\nElement: \(issue.element?.debugDescription ?? "none")\nHierarchy: \(self.app.debugDescription)"
                let attachment = XCTAttachment(string: String(details.prefix(64_000)))
                attachment.name = "Native Mac accessibility issue"
                attachment.lifetime = .keepAlways; self.add(attachment)
                return false
            }
            print("MAC_ACCESSIBILITY_AUDIT_PASS: \(state)")
        } else { throw XCTSkip("Native audit qualification targets the installed macOS 27 runtime") }
    }
    @MainActor func testOfficialAccessibilityEmptyAndPopulatedCanvas() throws {
        XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 10))
        try audit("empty workspace")
        openFile(fixture); assertHex("#ff00ff")
        app.buttons["sample.save"].click()
        try audit("full image and palette")
    }
    @MainActor func testOfficialAccessibilityCameraAndPrivacy() throws {
        app.buttons["camera.open"].click()
        XCTAssertTrue(app.buttons["camera.close"].waitForExistence(timeout: 10), app.debugDescription)
        try audit("camera availability")
        app.buttons["camera.close"].click()
        app.buttons["privacy.open"].click()
        XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 10))
        try audit("offline privacy")
    }

    @MainActor func testOfficialAccessibilityCorruptImportRetainsPreviousSource() throws {
        openFile(fixture); assertHex("#ff00ff")
        let bad = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-corrupt-\(UUID()).png")
        try Data("deliberately invalid synthetic PNG".utf8).write(to: bad)
        defer { try? FileManager.default.removeItem(at: bad) }
        openFile(bad)
        XCTAssertTrue(app.buttons["OK"].waitForExistence(timeout: 10), app.debugDescription)
        try audit("corrupt import error")
        app.buttons["OK"].click(); assertHex("#ff00ff")
    }

    func testSandboxBoundaryMatchesExactAppConfiguration() throws {
        let proof = app.staticTexts["debug.sandbox.proof"]
        XCTAssertTrue(proof.waitForExistence(timeout: 10), app.debugDescription)
        let text = proof.value as? String ?? proof.label
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        XCTAssertEqual(json["uid"] as? Int, try XCTUnwrap(expectedUID))
        XCTAssertEqual(json["unselectedReadDenied"] as? Bool, expectsSandbox)
        XCTAssertEqual(json["unselectedWriteDenied"] as? Bool, expectsSandbox)
        XCTAssertEqual(json["homeHasExpectedContainerPath"] as? Bool, expectsSandbox)
        XCTAssertEqual(json["applicationSupportIsInHome"] as? Bool, true)
        XCTAssertEqual(json["containerRoundTrip"] as? Bool, true)
        if expectsSandbox {
            XCTAssertEqual(json["readErrorDomain"] as? String, NSCocoaErrorDomain)
            XCTAssertEqual(json["readErrorCode"] as? Int, NSFileReadNoPermissionError)
            XCTAssertEqual(json["writeErrorDomain"] as? String, NSCocoaErrorDomain)
            XCTAssertEqual(json["writeErrorCode"] as? Int, NSFileWriteNoPermissionError)
        }
        print("NATIVE_SANDBOX_PROCESS_PROOF: \(text)")
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = "Native Mac actual sandbox process proof"; attachment.lifetime = .keepAlways; add(attachment)
    }

}
