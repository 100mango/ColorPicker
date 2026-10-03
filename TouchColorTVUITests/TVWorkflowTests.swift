import XCTest
import UIKit

final class TVWorkflowTests: XCTestCase {
    private var app: XCUIApplication!
    private let remote = XCUIRemote.shared
    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(); app.launchEnvironment["TOUCHCOLOR_TEST_DEFAULTS"] = "TouchColor.tv-ui.\(UUID())"
        app.launchArguments = ["--ui-test-reset", "-AppleLanguages", name.contains("Chinese") ? "(zh-Hans)" : "(en)"]; app.launch()
    }
    override func tearDownWithError() throws {
        if (testRun?.totalFailureCount ?? 0) > 0 { capture("Native TV failure"); print("TV_FAILURE_AX: \(app.debugDescription)") }
        app.terminate()
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
                let state = focused.identifier.isEmpty ? focused.label : focused.identifier
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
    func testActualPhotosRemoteSamplingZoomPaletteCodeAndPersistence() {
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
        capture("Native TV selected color JSON palette code")
        remote.press(.menu)
        XCTAssertTrue(app.buttons["tv.photos"].waitForExistence(timeout: 5))
        app.terminate(); app.launchArguments = ["-AppleLanguages", "(en)"]; app.launch()
        XCTAssertTrue(app.staticTexts["tv.palette.count"].waitForExistence(timeout: 10)); XCTAssertEqual(app.staticTexts["tv.palette.count"].label, "2")
    }
    func testChineseRemoteColorEditor() {
        let editor = app.buttons["tv.editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10)); XCTAssertEqual(editor.label, "创建颜色")
        select(editor); select(app.buttons["tv.red.down"])
        XCTAssertEqual(app.staticTexts["tv.editor.hex"].label, "#fe0000")
        XCTAssertEqual(app.buttons["tv.editor.save"].label, "保存颜色")
        select(app.buttons["tv.editor.save"]); capture("Native TV Chinese remote color editor")
        remote.press(.menu)
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
