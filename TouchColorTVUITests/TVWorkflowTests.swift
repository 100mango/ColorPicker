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
        for _ in 0..<24 {
            if element.hasFocus { remote.press(.select); return }
            let focused = root.descendants(matching: .any).matching(NSPredicate(format: "hasFocus == true")).firstMatch
            if focused.exists {
                let dx = element.frame.midX - focused.frame.midX, dy = element.frame.midY - focused.frame.midY
                if abs(dx) > abs(dy) { remote.press(dx >= 0 ? .right : .left) }
                else { remote.press(dy >= 0 ? .down : .up) }
            } else { remote.press(.right) }
        }
        XCTFail("Remote could not focus \(element.identifier): \(app.debugDescription)")
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
}
