import XCTest
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import CryptoKit
import AVFoundation
import ApplicationServices

@MainActor final class TouchColorMacUITests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    private var fixture: URL!
    private var suite = ""
    private var expectedUID: Int?
    private var expectsSandbox = false
    private var lifecycleToken: String?
    private var lifecycleStarted = 0.0
    private let lifecycleCases = ["testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail",
        "testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail",
        "testNativeFileSamplingZoomPalettePersistenceAndPrivacy", "testSimplifiedChineseNativeSamplingFlowAndScreenshot"]
    private var actionDiagnosticKeys = Set<String>()
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
        actionDiagnosticKeys.removeAll()
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
        app.launchArguments = ["--ui-test-reset"]
        // Each contact locale uses this one exact-product setup launch.
        if name.contains("testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail") {
            app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        } else if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {
            app.launchArguments += ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        }
        lifecycleToken = lifecycleCases.contains(where: { name == "-[TouchColorMacUITests \($0)]" }) ? UUID().uuidString : nil
        if let lifecycleToken { app.launchEnvironment["TOUCHCOLOR_MAC_LIFECYCLE"] = lifecycleToken }
        lifecycleStarted = Date().timeIntervalSince1970
        app.launch()
        let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.mango.touchColor").filter { !$0.isTerminated }
        XCTAssertEqual(running.count, 1)
        let actual = try XCTUnwrap(running.first)
        XCTAssertEqual(actual.bundleURL?.resolvingSymlinksInPath(), applicationURL.resolvingSymlinksInPath())
        let executable = try XCTUnwrap(actual.executableURL)
        let digest = SHA256.hash(data: try Data(contentsOf: executable)).map { String(format: "%02x", $0) }.joined()
        let debugDylib = applicationURL.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib")
        let logicDigest = SHA256.hash(data: try Data(contentsOf: debugDylib)).map { String(format: "%02x", $0) }.joined()
        print("NATIVE_UI_LOGIC_SHA256: \(logicDigest)")
        lifecycleReceipt(actual: actual, applicationURL: applicationURL, executable: executable,
                         digest: digest, logicDigest: logicDigest, ordinal: 1)
        XCTAssertTrue(app.menuBars.menuBarItems["TouchColor"].waitForExistence(timeout: 5), app.debugDescription)
        print("NATIVE_UI_RUNNING_APP path=\(actual.bundleURL?.path ?? "") executable=\(executable.path) sha256=\(digest)")
    }
    // Receipt only: no AX query, wait, activation or launch is added.
    private func lifecycleReceipt(actual: NSRunningApplication, applicationURL: URL, executable: URL,
                                  digest: String, logicDigest: String, ordinal: Int) {
        guard let token = lifecycleToken else { return }
        let row: [String: Any] = ["v": 1, "token": token, "pid": actual.processIdentifier,
            "test": name, "ordinal": ordinal, "started": lifecycleStarted, "captured": Date().timeIntervalSince1970,
            "args": app.launchArguments, "sandbox": expectsSandbox,
            "bundle": actual.bundleIdentifier ?? "", "applicationPath": actual.bundleURL?.path ?? "",
            "expectedPath": applicationURL.path, "executable": executable.path,
            "executableSHA256": digest, "logicSHA256": logicDigest,
            "xctestPID": NSNull(), "xctestPIDReason": "No public PID query; correlate retained failure hierarchy independently"]
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]), data.count <= 4096,
              let text = String(data: data, encoding: .utf8) else { return }
        let attachment = XCTAttachment(string: text)
        attachment.name = "Native Mac accessibility issue lifecycle identity \(token) \(ordinal)"
        attachment.lifetime = .keepAlways; add(attachment)
    }
    private func lifecycleRelaunchReceipt() {
        guard lifecycleToken != nil else { return }
        // This is the already-existing Chinese relaunch. Observe its new PID and exact product once.
        let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.mango.touchColor").filter { !$0.isTerminated }
        guard running.count == 1, let actual = running.first, let url = actual.bundleURL,
              let executable = actual.executableURL else { return }
        var products = Bundle(for: Self.self).bundleURL
        for _ in 0..<4 { products.deleteLastPathComponent() }
        let expected = products.appendingPathComponent("TouchColor.app")
        guard url.resolvingSymlinksInPath() == expected.resolvingSymlinksInPath() else { return }
        let logic = expected.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib")
        func boundedDigest(_ path: URL) -> String? {
            guard let properties = try? path.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]),
                  properties.isRegularFile == true, properties.isSymbolicLink == false,
                  let size = properties.fileSize, size > 0, size <= 16 * 1024 * 1024,
                  let handle = try? FileHandle(forReadingFrom: path) else { return nil }
            defer { try? handle.close() }
            guard let data = try? handle.read(upToCount: 16 * 1024 * 1024 + 1), data.count == size else { return nil }
            return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        }
        guard let digest = boundedDigest(executable), let logicDigest = boundedDigest(logic) else { return }
        lifecycleReceipt(actual: actual, applicationURL: expected, executable: executable,
                         digest: digest, logicDigest: logicDigest, ordinal: 2)
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
    private func assertSelectedColorSwatch(label: String, hex: String, rgb: String) {
        let swatches = app.images.matching(identifier: "sample.swatch")
        let swatch = swatches.element
        XCTAssertTrue(swatch.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(swatches.count, 1)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "sample.swatch").count, 1)
        XCTAssertEqual(swatch.elementType, .image)
        XCTAssertEqual(swatch.label, label)
        let expected = "\(hex), \(rgb)"
        let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", expected), object: swatch)
        XCTAssertEqual(XCTWaiter.wait(for: [updated], timeout: 5), .completed, swatch.debugDescription)
        XCTAssertEqual(swatch.value as? String, expected)
        XCTAssertEqual(swatch.frame.width, 38, accuracy: 0.5)
        XCTAssertEqual(swatch.frame.height, 38, accuracy: 0.5)
        let visibleRGB = app.staticTexts["sample.rgb"]
        XCTAssertEqual(visibleRGB.value as? String ?? visibleRGB.label, rgb)
    }
    func testNativeFileSamplingZoomPalettePersistenceAndPrivacy() {
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sample.swatch").element.exists)
        openFile(fixture)
        assertHex("#ff00ff")
        assertSelectedColorSwatch(label: "Selected color", hex: "#ff00ff", rgb: "R 255   G 0   B 255")
        let canvas = app.images["image.canvas"]
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.1)).click()
        assertHex("#ff0000")
        assertSelectedColorSwatch(label: "Selected color", hex: "#ff0000", rgb: "R 255   G 0   B 0")
        app.typeKey(.rightArrow, modifierFlags: []); assertHex("#00ff00")
        assertSelectedColorSwatch(label: "Selected color", hex: "#00ff00", rgb: "R 0   G 255   B 0")
        app.typeKey(.leftArrow, modifierFlags: []); assertHex("#ff0000")
        assertSelectedColorSwatch(label: "Selected color", hex: "#ff0000", rgb: "R 255   G 0   B 0")
        app.buttons["sample.save"].click(); app.buttons["sample.save"].click()
        XCTAssertEqual(app.staticTexts["palette.count"].value as? String ?? app.staticTexts["palette.count"].label, "2")
        app.buttons["sample.copy"].click()
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "#ff0000")
        let unzoomedFrame = canvas.frame
        app.buttons["sample.zoom.in"].click()
        XCTAssertGreaterThan(canvas.frame.width, unzoomedFrame.width * 1.5)
        XCTAssertTrue(app.staticTexts["sample.zoom.value"].exists)
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        assertSelectedColorSwatch(label: "Selected color", hex: "#ff00ff", rgb: "R 255   G 0   B 255")
        let window = app.windows.firstMatch
        let edge = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1)).withOffset(CGVector(dx: -2, dy: -2))
        edge.click(forDuration: 0.2, thenDragTo: edge.withOffset(CGVector(dx: -120, dy: -60)))
        app.buttons["sample.center"].click(); assertHex("#ff00ff")
        assertSelectedColorSwatch(label: "Selected color", hex: "#ff00ff", rgb: "R 255   G 0   B 255")
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
        lifecycleStarted = Date().timeIntervalSince1970
        app.launch()
        lifecycleRelaunchReceipt()
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try! Data(contentsOf: fixture), forType: .png)
        XCTAssertTrue(app.buttons["image.paste"].waitForExistence(timeout: 10), app.debugDescription)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
        assertSelectedColorSwatch(label: "所选颜色", hex: "#ff00ff", rgb: "R 255   G 0   B 255")
        app.buttons["sample.save"].click()
        XCTAssertTrue(app.staticTexts["调色板"].exists)
        XCTAssertEqual(app.buttons["sample.save"].label, "保存颜色")
        XCTAssertTrue(app.windows.firstMatch.frame.contains(app.buttons["sample.above"].frame), app.debugDescription)
        XCTAssertTrue(app.buttons["sample.above"].isHittable, app.debugDescription)
        app.buttons["sample.above"].click(); assertHex("#00ff00")
        assertSelectedColorSwatch(label: "所选颜色", hex: "#00ff00", rgb: "R 0   G 255   B 0")
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
            let unavailable = app.staticTexts["camera.no-device"]
            XCTAssertTrue(unavailable.exists, app.debugDescription)
            XCTAssertEqual(unavailable.elementType, .staticText)
            XCTAssertEqual(unavailable.value as? String ?? unavailable.label, "No camera")
            XCTAssertFalse(app.popUpButtons["camera.device"].exists, app.debugDescription)
            XCTAssertFalse(app.buttons["camera.start"].isEnabled)
            XCTAssertFalse(app.buttons["camera.freeze"].isEnabled)
            XCTAssertFalse(app.buttons["camera.save"].isEnabled)
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.name = "Native Mac actual no-camera status"; shot.lifetime = .keepAlways; add(shot)
            app.buttons["camera.close"].click()
            XCTAssertTrue(app.buttons["image.paste"].waitForExistence(timeout: 5))
            XCTAssertEqual(AVCaptureDevice.authorizationStatus(for: .video), permission)
        }
        XCTAssertEqual(AVCaptureDevice.authorizationStatus(for: .video), permission)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(try Data(contentsOf: fixture), forType: .png)
        app.buttons["image.paste"].click(); assertHex("#ff00ff")
    }

    func testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail() {
        assertPrivacyContact(label: "Contact the developer about privacy")
    }

    func testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail() {
        assertPrivacyContact(label: "联系开发者咨询隐私问题")
    }

    private func assertPrivacyContact(label: String) {
        XCTAssertTrue(app.buttons["privacy.open"].waitForExistence(timeout: 10), app.debugDescription)
        app.buttons["privacy.open"].click()
        XCTAssertTrue(app.buttons["privacy.close"].waitForExistence(timeout: 5), app.debugDescription)
        let contacts = app.links.matching(identifier: "privacy.contact")
        XCTAssertEqual(contacts.count, 1, app.debugDescription)
        let contact = contacts.element(boundBy: 0)
        XCTAssertEqual(contact.elementType, .link)
        XCTAssertEqual(contact.label, label)
        XCTAssertTrue(contact.isEnabled, app.debugDescription)
        XCTAssertTrue(contact.isHittable, app.debugDescription)
        // Inspect semantics only. Activating mailto is outside this test.
        app.buttons["privacy.close"].click()
        XCTAssertTrue(app.buttons["image.open.empty"].waitForExistence(timeout: 5), app.debugDescription)
    }

    @MainActor private func audit(_ state: String) throws {
        if #available(macOS 27.0, *) {
            print("MAC_ACCESSIBILITY_AUDIT_BEGIN: \(state)")
            let auditID = UUID().uuidString
            // Retain native pixels immediately before this audit, without a UI
            // action between capture and audit. These are sequential observations.
            let requestedStates = ["empty workspace", "full image and palette", "camera availability", "offline privacy", "corrupt import error"]
            if !expectsSandbox && requestedStates.contains(state) {
                do {
                    let png = app.screenshot().pngRepresentation
                    let capturedAt = (Date().timeIntervalSince1970 * 1000).rounded(.down) / 1000
                    let imageName = "Native Mac audit state " + auditID
                    let image = XCTAttachment(data: png, uniformTypeIdentifier: UTType.png.identifier)
                    image.name = imageName; image.lifetime = .keepAlways; add(image)
                    let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.mango.touchColor").filter { !$0.isTerminated }
                    guard running.count == 1, let actual = running.first,
                          let executable = actual.executableURL, let bundleURL = actual.bundleURL else {
                        throw NSError(domain: "NativeMacAuditEvidence", code: 1,
                                      userInfo: [NSLocalizedDescriptionKey: "Exact running app is unavailable"])
                    }
                    let logic = bundleURL.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib")
                    func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
                    let proof: [String: Any] = ["schema": 1, "auditID": auditID, "state": state,
                        "testName": name, "capturePhase": "immediately before audit", "sequential": true,
                        "sandbox": false, "imageName": imageName, "pngSHA256": digest(png), "pngBytes": png.count,
                        "capturedAt": capturedAt,
                        "appExecutableSHA256": digest(try Data(contentsOf: executable)),
                        "appLogicSHA256": digest(try Data(contentsOf: logic))]
                    let data = try JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys])
                    let attachment = XCTAttachment(string: String(decoding: data, as: UTF8.self))
                    attachment.name = "Native Mac accessibility issue screenshot proof " + auditID
                    attachment.lifetime = .keepAlways; add(attachment)
                } catch {
                    // Evidence failure must not prevent the unchanged audit.
                    // The post-upload completeness gate will fail this row.
                    let failure = XCTAttachment(string: "Audit-ID: \(auditID)\nState: \(state)\nCapture error: \(String(String(reflecting: error).prefix(2000)))")
                    failure.name = "Native Mac accessibility issue screenshot unavailable " + auditID
                    failure.lifetime = .keepAlways; add(failure)
                }
            }
            var issueCount = 0
            let failuresBefore = testRun?.totalFailureCount ?? 0
            defer {
                let recorded = (testRun?.totalFailureCount ?? failuresBefore) - failuresBefore
                print("MAC_ACCESSIBILITY_AUDIT_END: \(state); issues=\(issueCount); recordedFailures=\(recorded)")
                let summary = XCTAttachment(string: "Audit-ID: \(auditID)\nState: \(state)\nIssues: \(issueCount)\nRecorded failures: \(recorded)")
                summary.name = "Native Mac accessibility issue audit summary " + auditID
                summary.lifetime = .keepAlways; add(summary)
            }
            try app.performAccessibilityAudit(for: .all) { issue in
                issueCount += 1
                print("MAC_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                print("MAC_ACCESSIBILITY_ISSUE_TYPE: \(issue.auditType.rawValue)")
                if let element = issue.element {
                    print("MAC_ACCESSIBILITY_ISSUE_ATTRIBUTES: role=\(element.elementType.rawValue) identifier=\(element.identifier) label=\(element.label) value=\(String(describing: element.value)) frame=\(element.frame) isEnabled=\(element.isEnabled)")
                    self.recordAuditOwnership(element)
                    self.recordAuditActions(element, state: state, auditID: auditID)
                }
                print("MAC_ACCESSIBILITY_ISSUE_ELEMENT: \(String((issue.element?.debugDescription ?? "none").prefix(12_000)))")
                fflush(stdout)
                let details = "State: \(state)\nAudit-ID: \(auditID)\nAudit type: \(issue.auditType.rawValue)\nIssue: \(issue.compactDescription)\nElement: \(issue.element?.debugDescription ?? "none")\nHierarchy: \(self.app.debugDescription)"
                let retainedDetails = String(details.prefix(64_000)) + (details.count > 64_000 ? "\n[Producer truncated diagnostic after 64000 characters]" : "")
                let attachment = XCTAttachment(string: retainedDetails)
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
    private func recordAuditActions(_ element: XCUIElement, state: String, auditID: String) {
        // Read only the application's existing public AX action names. Never
        // request trust, execute an action, or alter an accessibility attribute.
        guard state == "full image and palette" || state == "offline privacy" else { return }
        do {
            let target = try element.snapshot()
            let expectedRole: String
            if state == "full image and palette", target.identifier == "palette.actions.0", target.elementType == .menuButton {
                expectedRole = kAXMenuButtonRole as String
            } else if state == "offline privacy",
                      (target.identifier == "mailto:100mango@gmail.com" || target.identifier == "privacy.contact"), target.elementType == .link {
                expectedRole = NSAccessibility.Role.link.rawValue
            } else { return }
            let frame = target.frame
            guard !frame.isNull, !frame.isInfinite, frame.width > 0, frame.height > 0,
                  [frame.minX, frame.minY, frame.width, frame.height].allSatisfy({ $0.isFinite }) else { return }
            let key = state + "|" + target.identifier + "|" + String(describing: frame)
            guard !actionDiagnosticKeys.contains(key), actionDiagnosticKeys.count < 4 else { return }
            actionDiagnosticKeys.insert(key)
            var record: [String: Any] = ["schema": 1, "auditID": auditID, "state": state, "testName": name,
                "sandbox": expectsSandbox, "sequentialObservations": true,
                "targetIdentifier": target.identifier, "targetRole": expectedRole,
                "targetFrame": String(describing: frame), "status": "unavailable", "matches": []]
            func emit() {
                guard let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) else { return }
                let text: String
                if data.count <= 8192 { text = String(decoding: data, as: UTF8.self) }
                else { text = "Audit-ID: \(auditID)\nState: \(state)\nAX action diagnostic unavailable: output exceeded 8192 bytes" }
                print("MAC_ACCESSIBILITY_ACTION_NAMES: \(text)")
                let attachment = XCTAttachment(string: text)
                attachment.name = "Native Mac accessibility issue action names " + auditID
                attachment.lifetime = .keepAlways; add(attachment)
            }
            defer { emit() }
            guard AXIsProcessTrusted() else { record["reason"] = "AX client is not trusted; no prompt requested"; return }
            var products = Bundle(for: Self.self).bundleURL
            for _ in 0..<4 { products.deleteLastPathComponent() }
            let expectedURL = products.appendingPathComponent("TouchColor.app").resolvingSymlinksInPath()
            let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.mango.touchColor").filter { !$0.isTerminated }
            guard running.count == 1, let actual = running.first,
                  actual.bundleURL?.resolvingSymlinksInPath() == expectedURL else {
                record["reason"] = "Exact single owned app is unavailable"; return
            }
            let pid = actual.processIdentifier
            record["pid"] = pid; record["applicationPath"] = expectedURL.path
            let start = ProcessInfo.processInfo.systemUptime
            var calls = 0, visited: [AXUIElement] = [], matches: [[String: Any]] = [], incomplete = false
            enum Stop: Error { case bound, timeoutUnavailable, foreignPID }
            func admit(_ node: AXUIElement) throws {
                guard calls <= 510, ProcessInfo.processInfo.systemUptime - start < 2 else { throw Stop.bound }
                // Apple documents this timeout as object-specific. Set it on
                // every inspected object; do not change the process-global one.
                guard AXUIElementSetMessagingTimeout(node, 0.15) == .success else { throw Stop.timeoutUnavailable }
                calls += 2 // One timeout setup plus one admitted AX read.
            }
            func owned(_ node: AXUIElement) throws {
                try admit(node)
                var owner: pid_t = 0
                guard AXUIElementGetPid(node, &owner) == .success, owner == pid else { throw Stop.foreignPID }
            }
            func value(_ node: AXUIElement, _ attribute: String) throws -> CFTypeRef? {
                try admit(node)
                var result: CFTypeRef?
                let code = AXUIElementCopyAttributeValue(node, attribute as CFString, &result)
                if code == .attributeUnsupported || code == .noValue { return nil }
                guard code == .success else { incomplete = true; return nil }
                return result
            }
            func children(_ node: AXUIElement, _ attribute: String, limit: Int) throws -> [AXUIElement] {
                try admit(node)
                var count: CFIndex = 0
                let countCode = AXUIElementGetAttributeValueCount(node, attribute as CFString, &count)
                if countCode == .attributeUnsupported || countCode == .noValue { return [] }
                guard countCode == .success, count >= 0 else { incomplete = true; return [] }
                if count > limit { incomplete = true }
                guard count > 0 else { return [] }
                try admit(node)
                var result: CFArray?
                let code = AXUIElementCopyAttributeValues(node, attribute as CFString, 0, min(count, limit), &result)
                guard code == .success, let values = result as? [AXUIElement], values.count == min(count, limit) else {
                    incomplete = true; return []
                }
                return values
            }
            func geometry(_ node: AXUIElement) throws -> CGRect? {
                guard let position = try value(node, kAXPositionAttribute), let size = try value(node, kAXSizeAttribute),
                      CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { incomplete = true; return nil }
                let p = unsafeBitCast(position, to: AXValue.self), s = unsafeBitCast(size, to: AXValue.self)
                var point = CGPoint.zero, extent = CGSize.zero
                guard AXValueGetType(p) == .cgPoint, AXValueGetType(s) == .cgSize,
                      AXValueGetValue(p, .cgPoint, &point), AXValueGetValue(s, .cgSize, &extent),
                      [point.x, point.y, extent.width, extent.height].allSatisfy({ $0.isFinite }), extent.width > 0, extent.height > 0 else { incomplete = true; return nil }
                return CGRect(origin: point, size: extent)
            }
            do {
                let root = AXUIElementCreateApplication(pid)
                try owned(root)
                var pending = try children(root, kAXWindowsAttribute, limit: 4).map { ($0, 0) }
                // Restrict traversal to the exact app's windows, excluding its
                // root Touch Bar and menu bar. No other PID is inspected.
                while !pending.isEmpty {
                    guard visited.count < 128 else { throw Stop.bound }
                    let (node, depth) = pending.removeFirst()
                    if visited.contains(where: { CFEqual($0, node) }) { continue }
                    visited.append(node); try owned(node)
                    let identifier = try value(node, kAXIdentifierAttribute) as? String
                    let role = try value(node, kAXRoleAttribute) as? String
                    if identifier == target.identifier, role == expectedRole, let bounds = try geometry(node),
                       abs(bounds.minX - frame.minX) <= 0.5, abs(bounds.minY - frame.minY) <= 0.5,
                       abs(bounds.width - frame.width) <= 0.5, abs(bounds.height - frame.height) <= 0.5 {
                        try admit(node)
                        var names: CFArray?
                        let code = AXUIElementCopyActionNames(node, &names)
                        let actions = names as? [String]
                        matches.append(["identifier": identifier ?? "", "role": role ?? "", "frame": String(describing: bounds),
                            "actionReadCode": code.rawValue, "actions": Array((actions ?? []).prefix(16)).map { String($0.prefix(128)) },
                            "actionsComplete": code == .success && actions != nil && actions!.count <= 16 && actions!.allSatisfy { $0.count <= 128 }])
                        if matches.count >= 4 { incomplete = true; break }
                    }
                    if depth < 16 { pending += try children(node, kAXChildrenAttribute, limit: 16).map { ($0, depth + 1) } }
                    else { incomplete = true }
                }
                record["status"] = !incomplete && matches.count == 1 && (matches[0]["actionsComplete"] as? Bool) == true
                    ? "exact_node_action_names_observed" : "partial_or_ambiguous"
            } catch { incomplete = true; record["reason"] = String(describing: error); record["status"] = "partial_or_unavailable" }
            record["matches"] = matches; record["visitedNodes"] = visited.count; record["AXCalls"] = calls
            record["elapsedSeconds"] = ProcessInfo.processInfo.systemUptime - start
            record["traversalIncomplete"] = incomplete
            record["scope"] = "owned app windows; maximum128nodes/16depth/512calls;2s admission deadline;0.15s per AX call"
        } catch { print("MAC_ACCESSIBILITY_ACTION_NAMES_UNAVAILABLE: \(String(String(reflecting: error).prefix(1000)))") }
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
        // NSAlert also mirrors OK into the application Touch Bar. Select the
        // observed window-owned alert sheet, never the ambiguous global button.
        let alert = app.windows.sheets.matching(NSPredicate(format: "label == %@", "alert")).element
        XCTAssertTrue(alert.waitForExistence(timeout: 10), app.debugDescription)
        let title = alert.staticTexts.matching(NSPredicate(format: "value == %@ OR label == %@",
                                                           "Could Not Complete", "Could Not Complete")).element
        XCTAssertTrue(title.exists, alert.debugDescription)
        let dismiss = alert.buttons["action-button-1"]
        XCTAssertTrue(dismiss.exists, alert.debugDescription)
        XCTAssertEqual(dismiss.label, "OK")
        XCTAssertFalse(app.staticTexts["palette.count"].exists)
        XCTAssertFalse(app.buttons["sample.save"].exists)
        let corruptAuditError = retainAuditFailure("corrupt import error")
        XCTAssertTrue(title.exists, alert.debugDescription)
        XCTAssertEqual(dismiss.label, "OK")
        dismiss.click()
        XCTAssertTrue(alert.waitForNonExistence(timeout: 5), app.debugDescription)
        assertHex("#ff00ff")
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
