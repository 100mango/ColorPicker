import XCTest
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import CryptoKit
import AVFoundation

@MainActor final class TouchColorMacUITests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    private var fixture: URL!
    private var suite = ""
    private var expectedUID: Int?
    private var expectsSandbox = false
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=mac")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=mac; unexpected interruption; no alert action taken")
        }
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
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
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
        try super.tearDownWithError()
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
    private func makePhotosFixture(at url: URL) throws {
        let colors: [[UInt8]] = [[255,0,0,255], [0,255,0,255], [0,0,255,255],
                                 [255,255,0,255], [255,0,255,255], [0,255,255,255]]
        var bytes: [UInt8] = []
        bytes.reserveCapacity(300 * 200 * 4)
        for y in 0..<200 {
            for x in 0..<300 {
                let index = (y / 100) * 3 + x / 100
                bytes.append(contentsOf: colors[index])
            }
        }
        let image = try XCTUnwrap(CGImage(width: 300, height: 200, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: 1200, space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: CGDataProvider(data: Data(bytes) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
    }

    private func selectVerifiedPhotosThumbnail() throws {
        let picker = app.sheets.firstMatch
        XCTAssertTrue(picker.waitForExistence(timeout: 15), app.debugDescription)
        // The observed macOS Photos picker uses this native sheet. Never use
        // screenshot coordinates for another sheet or for a permission prompt.
        XCTAssertEqual(picker.frame.width, 780, accuracy: 2)
        XCTAssertEqual(picker.frame.height, 620, accuracy: 2)
        let deadline = Date().addingTimeInterval(35)
        repeat {
            let screenshot = picker.screenshot()
            let png = screenshot.pngRepresentation
            let source = try XCTUnwrap(CGImageSourceCreateWithData(png as CFData, nil))
            let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
            let width = try XCTUnwrap(properties[kCGImagePropertyPixelWidth] as? NSNumber).doubleValue
            let height = try XCTUnwrap(properties[kCGImagePropertyPixelHeight] as? NSNumber).doubleValue
            XCTAssertEqual(width / height, Double(picker.frame.width / picker.frame.height), accuracy: 0.005,
                           "The pixel coordinates must come from this cropped sheet, including Retina scale")
            let locations = try SixColorThumbnail.locate(in: png)
            if locations.count == 1, let point = locations.first {
                let attachment = XCTAttachment(screenshot: screenshot)
                attachment.name = "Native Mac verified asymmetric Photos thumbnail"
                attachment.lifetime = .keepAlways; add(attachment)
                print("NATIVE_PHOTOS_VERIFIED_THUMBNAIL: x=\(point.x) y=\(point.y)")
                picker.coordinate(withNormalizedOffset: CGVector(dx: point.x, dy: point.y)).click()
                return
            }
            XCTAssertLessThanOrEqual(locations.count, 1, "Only the one synthetic source may be selected")
            RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        } while Date() < deadline
        let attachment = XCTAttachment(screenshot: picker.screenshot())
        attachment.name = "Native Mac Photos thumbnail readiness failure"; attachment.lifetime = .keepAlways; add(attachment)
        XCTFail("No unique six-color source was visible in the current Photos sheet; no coordinate was clicked")
    }

    func testSystemPhotosImportSamplesActualImageInsideSandbox() throws {
        try XCTSkipUnless(expectsSandbox, "Qualify the populated system Photos route once in the minimal sandbox lane")
        let photosFixture = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-Photos-\(UUID()).png")
        try makePhotosFixture(at: photosFixture)
        defer { try? FileManager.default.removeItem(at: photosFixture) }
        let photos = XCUIApplication(bundleIdentifier: "com.apple.Photos")
        photos.launch()
        defer {
            if (testRun?.totalFailureCount ?? 0) > 0 {
                print("NATIVE_PHOTOS_FAILURE_AX: \(String(photos.debugDescription.prefix(18_000)))")
                let shot = XCTAttachment(screenshot: photos.screenshot())
                shot.name = "Native Mac system Photos failure state"; shot.lifetime = .keepAlways; add(shot)
            }
            photos.terminate()
        }
        // This disposable runner contains only synthetic images. Use Photos' own
        // normal library/import UI, without accounts, iCloud or database changes.
        if photos.buttons["Get Started"].waitForExistence(timeout: 5) { photos.buttons["Get Started"].click() }
        let file = photos.menuBarItems["File"]
        XCTAssertTrue(file.waitForExistence(timeout: 15), photos.debugDescription); file.click()
        let command = photos.menuItems["_NS:1096"]
        XCTAssertTrue(command.isEnabled, photos.debugDescription); command.click()
        photos.typeKey("g", modifierFlags: [.command, .shift])
        let path = photos.sheets.textFields.firstMatch
        XCTAssertTrue(path.waitForExistence(timeout: 5), photos.debugDescription)
        path.typeKey("a", modifierFlags: [.command]); path.typeText(photosFixture.path)
        photos.typeKey(.return, modifierFlags: [])
        let importButton = photos.sheets["open-panel"].buttons["OKButton"]
        XCTAssertTrue(importButton.waitForExistence(timeout: 5), photos.debugDescription); importButton.click()
        let review = photos.buttons["Review for Import"]
        if review.waitForExistence(timeout: 3) { review.click() }
        let importAll = photos.buttons["Import All New Photos"]
        if importAll.waitForExistence(timeout: 3) { importAll.click() }
        let imported = photos.collectionViews["photos_collection_view"].descendants(matching: .any).matching(identifier: "mediaKind_asset").firstMatch
        XCTAssertTrue(imported.waitForExistence(timeout: 25), photos.debugDescription)
        XCTAssertFalse(photos.sheets["open-panel"].exists)
        app.activate(); app.buttons["image.photos"].click()
        print("NATIVE_POPULATED_PHOTOS_PICKER_AX: \(String(app.debugDescription.prefix(32_000)))")
        for helper in NSWorkspace.shared.runningApplications.filter({ application in
            let identifier = (application.bundleIdentifier ?? "").lowercased()
            return identifier.contains("photos") || identifier.contains("photopicker")
        }).prefix(8) {
            print("NATIVE_PHOTOS_UI_OWNER: \(helper.bundleIdentifier ?? "unknown") pid=\(helper.processIdentifier)")
        }
        try selectVerifiedPhotosThumbnail()
        assertHex("#ff00ff")
        // The default normalized center resolves to y=100. One original pixel up
        // crosses the asymmetric fixture boundary into the green block.
        app.buttons["sample.above"].click(); assertHex("#00ff00")
        let dimensions = app.staticTexts["sample.pixel"]
        XCTAssertTrue((dimensions.value as? String ?? dimensions.label).contains("300 × 200"))
        app.buttons["sample.save"].click()
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "1")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "Native Mac actual Photos imported source and green pixel"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["image.photos"].click()
        let picker = app.sheets.firstMatch
        XCTAssertTrue(picker.waitForExistence(timeout: 10), app.debugDescription)
        app.typeKey(.escape, modifierFlags: [])
        if #available(macOS 15.0, *) {
            XCTAssertTrue(picker.waitForNonExistence(timeout: 10), app.debugDescription)
        } else {
            let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: picker)
            XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 10), .completed, app.debugDescription)
        }
        assertHex("#00ff00")
        app.terminate(); app.launchArguments = []; app.launch()
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "1")
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
            var issueCount = 0
            let failuresBefore = testRun?.totalFailureCount ?? 0
            defer {
                let recorded = (testRun?.totalFailureCount ?? failuresBefore) - failuresBefore
                print("MAC_ACCESSIBILITY_AUDIT_END: \(state); issues=\(issueCount); recordedFailures=\(recorded)")
            }
            try app.performAccessibilityAudit(for: .all) { issue in
                issueCount += 1
                print("MAC_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                print("MAC_ACCESSIBILITY_ISSUE_TYPE: \(issue.auditType.rawValue)")
                if let element = issue.element {
                    print("MAC_ACCESSIBILITY_ISSUE_ATTRIBUTES: role=\(element.elementType.rawValue) identifier=\(element.identifier) label=\(element.label) value=\(String(describing: element.value)) frame=\(element.frame) isEnabled=\(element.isEnabled)")
                    self.recordAuditOwnership(element)
                }
                print("MAC_ACCESSIBILITY_ISSUE_ELEMENT: \(String((issue.element?.debugDescription ?? "none").prefix(12_000)))")
                fflush(stdout)
                let details = "State: \(state)\nIssue: \(issue.compactDescription)\nElement: \(issue.element?.debugDescription ?? "none")\nHierarchy: \(self.app.debugDescription)"
                let attachment = XCTAttachment(string: String(details.prefix(64_000)))
                attachment.name = "Native Mac accessibility issue"
                attachment.lifetime = .keepAlways; self.add(attachment)
                return false
            }
            // Under continueAfterFailure the API may record XCTest issues and
            // return normally rather than throw. Returning does not imply a pass.
            if issueCount == 0 && (testRun?.totalFailureCount ?? 0) == failuresBefore {
                print("MAC_ACCESSIBILITY_AUDIT_PASS: \(state)")
            } else {
                print("MAC_ACCESSIBILITY_AUDIT_FAIL: \(state)")
            }
        } else { throw XCTSkip("Native audit qualification targets the installed macOS 27 runtime") }
    }
    private func recordAuditOwnership(_ element: XCUIElement) {
        do {
            let target = try element.snapshot()
            let root = try app.snapshot()
            func attributes(_ node: any XCUIElementSnapshot) -> [String: Any] {
                ["role": node.elementType.rawValue, "identifier": String(node.identifier.prefix(256)),
                 "label": String(node.label.prefix(256)), "value": String(String(describing: node.value).prefix(256)),
                 "frame": String(describing: node.frame), "isEnabled": node.isEnabled]
            }
            let owners = root.children.filter { $0.elementType == .window }.prefix(4).compactMap { window -> [String: Any]? in
                let matches = window.children.filter {
                    $0.elementType == target.elementType && $0.frame == target.frame &&
                    $0.identifier == target.identifier && $0.label == target.label &&
                    String(describing: $0.value) == String(describing: target.value)
                }
                guard !matches.isEmpty else { return nil }
                return ["directChildMatches": matches.count, "window": attributes(window),
                        "directSheets": window.children.filter { $0.elementType == .sheet }.prefix(4).map(attributes)]
            }
            // These are sequential snapshots. Exact role/geometry/identity
            // attributes must correlate uniquely before claiming ownership.
            let unique = owners.count == 1 && (owners.first?["directChildMatches"] as? Int) == 1
            let data = try JSONSerialization.data(withJSONObject: ["sequentialSnapshots": true,
                "uniqueDirectChildCorrelation": unique, "issueElement": attributes(target), "directWindowOwners": owners], options: [.sortedKeys])
            let text = String(decoding: data, as: UTF8.self)
            print("MAC_ACCESSIBILITY_OWNERSHIP: \(text)")
            let attachment = XCTAttachment(string: text)
            attachment.name = "Native Mac accessibility issue ownership"; attachment.lifetime = .keepAlways; add(attachment)
        } catch {
            print("MAC_ACCESSIBILITY_OWNERSHIP_UNAVAILABLE: \(error)")
        }
    }
    private func retainAuditFailure(_ state: String) -> Error? {
        // Keep every raw before/modal/after audit failure, then finish the
        // same-window comparison before rethrowing. Action assertions stay fail-fast.
        let previous = continueAfterFailure
        continueAfterFailure = true
        defer { continueAfterFailure = previous }
        do { try audit(state); return nil } catch {
            // More than one phase can throw an API error. Keep each payload now,
            // before the final aggregate rethrows its first retained error.
            let raw = String(reflecting: error)
            let native = error as NSError
            let details = "Phase: \(state)\nDomain: \(native.domain)\nCode: \(native.code)\nError: \(String(raw.prefix(4000)))"
                + (raw.count > 4000 ? "\n[Error payload truncated after 4000 characters]" : "")
            print("MAC_ACCESSIBILITY_PHASE_API_ERROR: \(details)"); fflush(stdout)
            let attachment = XCTAttachment(string: details)
            attachment.name = "Native Mac accessibility issue raw API error \(state)"
            attachment.lifetime = .keepAlways; add(attachment)
            return error
        }
    }
    private func finishRetainedAudits(_ errors: [Error?], route: String) throws {
        // Recorded audit issues remain failures in this XCTest case. Only those
        // audit calls continue after failure; all functional assertions stay
        // fail-fast. API errors are rethrown after the complete route is measured.
        print("MAC_FUNCTIONAL_AUDIT_ROUTE_COMPLETED: \(route); recorded XCTest failures=\(testRun?.totalFailureCount ?? 0)")
        if let error = errors.compactMap({ $0 }).first { throw error }
    }
    private func finishStandardModal(_ sheet: XCUIElement, action: XCUIElement, window: XCUIElement,
                                     originalFrame: CGRect, state: String, priorAuditErrors: [Error]) throws {
        XCTAssertTrue(action.exists && action.isEnabled && action.isHittable, app.debugDescription)
        XCTAssertTrue(sheet.frame.contains(action.frame), app.debugDescription)
        action.click()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: sheet)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 5), .completed, app.debugDescription)
        XCTAssertEqual(app.windows.count, 1); XCTAssertEqual(window.frame, originalFrame)
        XCTAssertTrue(window.buttons["probe.standard.sheet"].isHittable)
        let afterError = retainAuditFailure(state + " after dismissal")
        let errors = priorAuditErrors + [afterError].compactMap { $0 }
        print("NATIVE_STANDARD_MODAL_THREE_PHASES_MEASURED: \(state); retained API errors=\(errors.count); recorded XCTest failures=\(testRun?.totalFailureCount ?? 0)"); fflush(stdout)
        if let error = errors.first { throw error }
    }
    private func launchStandardModalProbe() {
        app.terminate()
        app.launchEnvironment["TOUCHCOLOR_NATIVE_MODAL_PROBE"] = "1"
        app.launch()
        XCTAssertTrue(app.buttons["probe.standard.sheet"].waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.buttons["probe.standard.alert"].exists)
    }
    @MainActor func testDiagnosticStandardAppKitSheetAudit() throws {
        launchStandardModalProbe()
        XCTAssertEqual(app.windows.count, 1)
        let window = app.windows.element(boundBy: 0); let originalFrame = window.frame
        let beforeError = retainAuditFailure("diagnostic standard AppKit sheet before presentation")
        XCTAssertTrue(app.buttons["probe.standard.sheet"].isEnabled && app.buttons["probe.standard.sheet"].isHittable)
        app.buttons["probe.standard.sheet"].click()
        let sheet = window.sheets.element(boundBy: 0)
        XCTAssertTrue(sheet.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(window.sheets.count, 1)
        XCTAssertTrue(sheet.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", "Active standard sheet content", "Active standard sheet content")).firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        let done = sheet.buttons["probe.sheet.done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(done.title, "Done")
        print("NATIVE_STANDARD_SHEET_AX: \(app.debugDescription)"); fflush(stdout)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Mac standard AppKit sheet diagnostic"; image.lifetime = .keepAlways; add(image)
        let modalError = retainAuditFailure("diagnostic standard AppKit sheet")
        try finishStandardModal(sheet, action: done, window: window, originalFrame: originalFrame,
                                state: "diagnostic standard AppKit sheet", priorAuditErrors: [beforeError, modalError].compactMap { $0 })
    }
    @MainActor func testDiagnosticStandardAppKitAlertAudit() throws {
        launchStandardModalProbe()
        XCTAssertEqual(app.windows.count, 1)
        let window = app.windows.element(boundBy: 0); let originalFrame = window.frame
        let beforeError = retainAuditFailure("diagnostic standard AppKit alert before presentation")
        XCTAssertTrue(app.buttons["probe.standard.alert"].isEnabled && app.buttons["probe.standard.alert"].isHittable)
        app.buttons["probe.standard.alert"].click()
        let sheet = window.sheets.element(boundBy: 0)
        XCTAssertTrue(sheet.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(window.sheets.count, 1)
        for value in ["Standard AppKit Alert", "Active standard alert content"] {
            XCTAssertTrue(sheet.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", value, value)).firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        }
        let done = sheet.buttons["action-button-1"]
        XCTAssertTrue(done.waitForExistence(timeout: 5)); XCTAssertEqual(done.title, "OK")
        print("NATIVE_STANDARD_ALERT_AX: \(app.debugDescription)"); fflush(stdout)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Native Mac standard AppKit alert diagnostic"; image.lifetime = .keepAlways; add(image)
        let modalError = retainAuditFailure("diagnostic standard AppKit alert")
        try finishStandardModal(sheet, action: done, window: window, originalFrame: originalFrame,
                                state: "diagnostic standard AppKit alert", priorAuditErrors: [beforeError, modalError].compactMap { $0 })
    }
    @MainActor private func nativeSliderValue(_ slider: XCUIElement) -> Double? {
        let value = slider.value
        if let number = value as? NSNumber { return number.doubleValue }
        if let text = value as? String { return Double(text) }
        return nil
    }
    @MainActor func testOfficialAccessibilityEmptyAndPopulatedCanvas() throws {
        XCTAssertTrue(app.buttons["image.open"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.groups["workspace.palette"].waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.groups["workspace.sampler"].exists, app.debugDescription)
        XCTAssertTrue(app.groups["workspace.palette"].staticTexts["palette.count"].exists)
        XCTAssertTrue(app.groups["workspace.sampler"].buttons["image.open.empty"].exists)
        let zoom = app.sliders["sample.zoom"]
        XCTAssertTrue(zoom.exists); XCTAssertEqual(zoom.label, "Image zoom")
        XCTAssertFalse(zoom.isEnabled)
        XCTAssertEqual(nativeSliderValue(zoom), 1)
        XCTAssertEqual(zoom.descendants(matching: .valueIndicator)
            .matching(NSPredicate(format: "label == '' AND (value == nil OR value == '')")).count, 0)
        let emptyAuditError = retainAuditFailure("empty workspace")
        openFile(fixture); assertHex("#ff00ff")
        app.buttons["sample.save"].click()
        let populatedAuditError = retainAuditFailure("full image and palette")
        // The standard AppKit control must retain real pointer/keyboard input,
        // an accessible numeric value and visible canvas magnification.
        let canvas = app.images["image.canvas"]
        let originalWidth = canvas.frame.width
        zoom.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.5)).click()
        XCTAssertGreaterThan(canvas.frame.width, originalWidth * 1.5)
        let zoomBeforeKeyboard = try XCTUnwrap(nativeSliderValue(zoom))
        app.typeKey("+", modifierFlags: .command)
        let keyboardZoom = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            (self.nativeSliderValue(zoom) ?? 0) > zoomBeforeKeyboard
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [keyboardZoom], timeout: 5), .completed,
                       "The native range value must follow the real Zoom In keyboard command")
        let magnified = XCTAttachment(screenshot: app.screenshot())
        magnified.name = "Native Mac native slider pointer and keyboard magnification"; magnified.lifetime = .keepAlways; add(magnified)
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        try finishRetainedAudits([emptyAuditError, populatedAuditError], route: "empty/populated canvas and native slider")
    }
    @MainActor func testOfficialAccessibilityCameraAndPrivacy() throws {
        app.buttons["camera.open"].click()
        XCTAssertTrue(app.buttons["camera.close"].waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertFalse(app.staticTexts["palette.count"].exists)
        XCTAssertFalse(app.buttons["sample.save"].exists)
        let cameraAuditError = retainAuditFailure("camera availability")
        app.buttons["camera.close"].click()
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["sample.save"].exists)
        app.buttons["privacy.open"].click()
        XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["palette.count"].exists)
        let privacyAuditError = retainAuditFailure("offline privacy")
        app.buttons["privacy.close"].click()
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["image.open.empty"].exists)
        try finishRetainedAudits([cameraAuditError, privacyAuditError], route: "camera and offline privacy return")
    }

    @MainActor func testOfficialAccessibilityCorruptImportRetainsPreviousSource() throws {
        openFile(fixture); assertHex("#ff00ff")
        let bad = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-corrupt-\(UUID()).png")
        try Data("deliberately invalid synthetic PNG".utf8).write(to: bad)
        defer { try? FileManager.default.removeItem(at: bad) }
        openFile(bad)
        XCTAssertTrue(app.buttons["OK"].waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertFalse(app.staticTexts["palette.count"].exists)
        XCTAssertFalse(app.buttons["sample.save"].exists)
        let corruptAuditError = retainAuditFailure("corrupt import error")
        app.buttons["OK"].click(); assertHex("#ff00ff")
        XCTAssertTrue(app.staticTexts["palette.count"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["sample.save"].exists)
        try finishRetainedAudits([corruptAuditError], route: "corrupt alert preserves previous source")
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
