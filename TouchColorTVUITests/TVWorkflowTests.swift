import XCTest
import UIKit
import CoreImage

final class TVWorkflowTests: XCTestCase {
    private var failClosedInterruption: NSObjectProtocol?
    private var app: XCUIApplication!
    private let remote = XCUIRemote.shared
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Keep intended dialog actions explicit. Never fall through to XCTest's
        // default handler for an otherwise-unhandled system interruption.
        failClosedInterruption = addUIInterruptionMonitor(withDescription: "Abort every unhandled system interruption") { _ in
            // No UI query or XCTest failure recorder may throw before the abort.
            print("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=tv")
            fatalError("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT platform=tv; unexpected interruption; no alert action taken")
        }
        continueAfterFailure = false
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.tv-ui.\(UUID())"
        if name.contains("Chinese") { app.launchEnvironment["TOUCHCOLOR_TEST_TRAIT_PROOF"] = "1" }
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", name.contains("Chinese") ? "(zh-Hans)" : "(en)"]; app.launch()
    }
    override func tearDownWithError() throws {
        defer {
            if let monitor = failClosedInterruption { removeUIInterruptionMonitor(monitor) }
            failClosedInterruption = nil
        }
        if (testRun?.totalFailureCount ?? 0) > 0 { capture("Native TV failure"); print("TV_FAILURE_AX: \(app.debugDescription)") }
        app.terminate()
        try super.tearDownWithError()
    }
    private func capture(_ name: String) {
        guard let data = app.screenshot().image.jpegData(compressionQuality: 0.45), data.count <= 3_000_000 else { return }
        let shot = XCTAttachment(data: data, uniformTypeIdentifier: "public.jpeg"); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    /// Real remote events use the visible focus geometry; no direct test-only action dispatch.
    private func select(_ element: XCUIElement, in application: XCUIApplication? = nil) {
        let root = application ?? app!
        XCTAssertTrue(element.waitForExistence(timeout: 15), app.debugDescription)
        var attempted: [String: Set<String>] = [:]
        for _ in 0..<60 {
            if element.hasFocus { remote.press(.select); return }
            let button = root.buttons.matching(NSPredicate(format: "hasFocus == true")).firstMatch
            let focused = button.exists ? button : root.descendants(matching: .any).matching(NSPredicate(format: "hasFocus == true")).firstMatch
            if focused.exists {
                let target = element.frame, current = focused.frame
                // System permission alerts expose nested buttons with the same title/frame.
                // Their focused inner button represents the exact same visible choice.
                if focused.label == element.label && abs(target.midX-current.midX) < 1 && abs(target.midY-current.midY) < 1 && abs(target.width-current.width) < 1 && abs(target.height-current.height) < 1 {
                    remote.press(.select); return
                }
                if focused.elementType == .cell, !element.identifier.isEmpty, current.contains(target) {
                    // A native List focuses its row. Select it only when every
                    // exposed button is the same single action (SwiftUI may expose
                    // that button twice). Never treat a multi-action cell as one button.
                    let children = focused.buttons.allElementsBoundByIndex
                    if !children.isEmpty, children.count <= 4, children.allSatisfy({ child in
                        let frame = child.frame
                        return child.identifier == element.identifier && child.label == element.label &&
                            abs(frame.midX-target.midX) < 1 && abs(frame.midY-target.midY) < 1 &&
                            abs(frame.width-target.width) < 1 && abs(frame.height-target.height) < 1
                    }) {
                        remote.press(.select); return
                    }
                }
                // Duplicate saved colors have identical labels but distinct row positions.
                let state = "\(focused.elementType.rawValue)|\(focused.identifier)|\(focused.label)|\(current.integral)"
                let vertical: String = target.midY >= current.midY ? "down" : "up"
                let horizontal: String = target.midX >= current.midX ? "right" : "left"
                let preferred = target.minY >= current.maxY || target.maxY <= current.minY ? [vertical,horizontal] : [horizontal,vertical]
                let directions = preferred + [horizontal == "right" ? "left" : "right", vertical == "down" ? "up" : "down"]
                // The TV focus engine follows focus beams, not straight-line distance.
                // If the preferred direction does not reach a new item, explore another
                // real remote direction from that state instead of repeating a dead end.
                let tried = attempted[state, default: []]
                let direction = directions.first(where: { !tried.contains($0) }) ?? directions[0]
                if tried.count == 4 { attempted[state] = [] }
                attempted[state, default: []].insert(direction)
                switch direction {
                case "up": remote.press(.up)
                case "down": remote.press(.down)
                case "left": remote.press(.left)
                default: remote.press(.right)
                }
            } else { remote.press(.down) }
        }
        XCTFail("Remote could not focus \(element.identifier) [\(element.label)]: \(root.debugDescription)")
    }
    private func hex(_ expected: String) {
        let element = app.staticTexts["tv.sample.hex"]
        XCTAssertTrue(element.waitForExistence(timeout: 15), app.debugDescription)
        let match = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", expected), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [match], timeout: 10), .completed, app.debugDescription)
    }
    private func assertDisplayedPaletteCode(_ expected: String) throws {
        XCTAssertEqual(app.staticTexts["tv.export.hex"].label, expected)
        // Decode the actual displayed QR pixels, including scaling and the sheet surface.
        let rendered = try XCTUnwrap(app.screenshot().image.cgImage)
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: CIContext(), options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let payloads = detector.features(in: CIImage(cgImage: rendered)).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(payloads.count, 1)
        let payload = try XCTUnwrap(payloads.first)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: Data(payload.utf8)) as? [String], [expected])
        print("TV_DISPLAYED_QR_VERIFIED: \(expected)")
    }
    func testActualPhotosRemoteSamplingZoomPaletteCodeAndPersistence() throws {
        select(app.buttons["tv.photos"])
        let system = XCUIApplication(bundleIdentifier: "com.apple.PineBoard")
        let allow = system.buttons["Allow All Photos"].firstMatch
        if allow.waitForExistence(timeout: 8) {
            let namesApp = system.staticTexts.matching(NSPredicate(format: "label CONTAINS 'TouchColor'")).firstMatch
            XCTAssertTrue(namesApp.exists, system.debugDescription)
            print("TV_PHOTOS_PERMISSION_AX: \(system.debugDescription)")
            select(allow, in: system)
        }
        select(app.buttons["tv.photo.0"]); hex("#ff00ff")
        select(app.buttons["tv.sample.save"]); select(app.buttons["tv.sample.save"])
        select(app.buttons["tv.sample.up"]); hex("#00ff00")
        select(app.buttons["tv.zoom.in"])
        XCTAssertEqual(app.staticTexts["tv.zoom.value"].label, "2.0×")
        capture("Native TV real photo sampled with remote and visible zoom")
        select(app.buttons["tv.sample.export"])
        XCTAssertTrue(app.otherElements["tv.export.code"].exists || app.images["tv.export.code"].exists, app.debugDescription)
        try assertDisplayedPaletteCode("#00ff00")
        capture("Native TV selected color JSON palette code decoded from actual UI pixels")
        remote.press(.menu)
        XCTAssertTrue(app.buttons["tv.photos"].waitForExistence(timeout: 5))
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["tv.palette.count"].waitForExistence(timeout: 10)); XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "2")
        select(app.buttons["tv.palette.0"])
        try assertDisplayedPaletteCode("#ff00ff")
        select(app.buttons["tv.palette.delete"])
        XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "1")
        app.terminate(); app.launch()
        XCTAssertTrue(app.staticTexts["tv.palette.count"].waitForExistence(timeout: 10)); XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "1")
        XCTAssertTrue(app.buttons["tv.palette.0"].label.contains("#ff00ff"))
    }
    @MainActor func testChineseRemoteColorEditor() throws {
        let editor = app.buttons["tv.editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10)); XCTAssertEqual(editor.label, "创建颜色")
        select(editor)
        let hex = app.staticTexts["tv.editor.hex"]
        let baseline = try traitMetric(hex, largest: false)
        let baselineFrame = hex.frame, viewport = app.frame
        select(app.buttons["tv.red.down"])
        XCTAssertEqual(app.staticTexts["tv.editor.hex"].label, "#fe0000")
        XCTAssertEqual(app.buttons["tv.editor.save"].label, "保存颜色")
        select(app.buttons["tv.editor.save"]); capture("Native TV Chinese remote color editor")
        remote.press(.menu)
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(zh-Hans)"]
        app.launchEnvironment["TOUCHCOLOR_TEST_LARGEST_TRAIT"] = "1"; app.launch()
        XCTAssertEqual(app.frame, viewport)
        let rootTrait = app.staticTexts["tv.palette.count"].value as? String
        print("TV_PUBLIC_TRAIT_ROOT: \(rootTrait ?? "missing")")
        select(app.buttons["tv.editor"])
        print("TV_PUBLIC_TRAIT_SHEET: \(String(describing: hex.value))")
        XCTAssertEqual(rootTrait, "largest=true", "The root must receive the requested public trait before its sheet is qualified")
        let largest = try traitMetric(hex, largest: true)
        XCTAssertGreaterThan(largest, baseline)
        XCTAssertGreaterThan(hex.frame.height, baselineFrame.height)
        XCTAssertTrue(viewport.contains(hex.frame)); XCTAssertGreaterThan(hex.frame.width / hex.frame.height, 2.5)
        select(app.buttons["tv.red.down"]); XCTAssertEqual(hex.label, "#fe0000")
        XCTAssertEqual(app.staticTexts["tv.editor.rgb"].label, "R 254   G 0   B 0")
        XCTAssertTrue(viewport.contains(app.staticTexts["tv.editor.rgb"].frame))
        XCTAssertTrue(viewport.contains(app.buttons["tv.editor.save"].frame))
        try audit("largest public trait Chinese RGB editor; system propagation unverified")
        select(app.buttons["tv.editor.save"])
        capture("Native TV largest public trait Chinese editor")
        remote.press(.menu); XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "2")
        print("TV_PUBLIC_TRAIT_PROOF: accessibility5; baselineMetric=\(baseline); largestMetric=\(largest); viewport=\(viewport); systemPropagation=unverified")
    }
    private func traitMetric(_ element: XCUIElement, largest: Bool) throws -> Double {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let proof = try XCTUnwrap(element.value as? String)
        XCTAssertTrue(proof.hasPrefix("largest=\(largest);metric="), proof)
        return try XCTUnwrap(Double(proof.components(separatedBy: "metric=").last ?? ""))
    }
    func testRemoteColorEditorAndMenuReturn() {
        select(app.buttons["tv.editor"])
        select(app.buttons["tv.red.down"])
        XCTAssertEqual(app.staticTexts["tv.editor.hex"].label, "#fe0000")
        select(app.buttons["tv.editor.save"]); remote.press(.menu)
        XCTAssertTrue(app.buttons["tv.photos"].waitForExistence(timeout: 5)); XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "1")
    }
    @MainActor private func audit(_ state: String) throws {
        if #available(tvOS 27.0, *) {
            print("TV_ACCESSIBILITY_AUDIT_BEGIN: \(state)")
            try app.performAccessibilityAudit(for: .all) { issue in
                print("TV_ACCESSIBILITY_ISSUE: \(state): \(issue.compactDescription)")
                return false
            }
            print("TV_ACCESSIBILITY_AUDIT_PASS: \(state)")
        } else { throw XCTSkip("Native audit qualification targets the installed tvOS 27 runtime") }
    }
    @MainActor func testOfficialAccessibilityEmptyAndRemoteEditor() throws {
        XCTAssertTrue(app.buttons["tv.editor"].waitForExistence(timeout: 15))
        try audit("empty workspace")
        select(app.buttons["tv.editor"])
        XCTAssertTrue(app.staticTexts["tv.editor.hex"].waitForExistence(timeout: 5))
        try audit("remote RGB editor")
    }

    @MainActor func testRealPhotosDenialAndResetKeepPaletteAndEditorUsable() throws {
        app.terminate(); app.resetAuthorizationStatus(for: .photos); app.launch()
        select(app.buttons["tv.photos"])
        let system = XCUIApplication(bundleIdentifier: "com.apple.PineBoard")
        let deny = system.buttons["Don’t Allow"].firstMatch
        XCTAssertTrue(deny.waitForExistence(timeout: 10), system.debugDescription)
        XCTAssertTrue(system.staticTexts.matching(NSPredicate(format: "label CONTAINS 'TouchColor'")).firstMatch.exists)
        select(deny, in: system)
        let status = app.staticTexts["tv.photos.status"]
        XCTAssertTrue(status.waitForExistence(timeout: 10)); XCTAssertTrue(status.label.contains("Photo access is unavailable"))
        try audit("photo permission denied")
        capture("Native TV Photos denial retains local palette")
        remote.press(.menu)
        XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "0")
        select(app.buttons["tv.editor"]); select(app.buttons["tv.editor.save"]); remote.press(.menu)
        XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "1")
        app.terminate(); app.resetAuthorizationStatus(for: .photos)
        app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["tv.palette.count"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "1")
    }

}
