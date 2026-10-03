import XCTest
import ColorDomain
import ColorPaletteLegacy

final class ColorPaletteTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!
    override func setUp() { suite = "TouchColor.palette-tests.\(UUID())"; defaults = UserDefaults(suiteName: suite)! }
    override func tearDown() { defaults.removePersistentDomain(forName: suite) }
    func testOriginalKeyDuplicatesOrderAndReopenWithoutMigration() throws {
        let original = ["#112233", "#abcdef", "#112233"]
        defaults.set(original, forKey: "colorArray")
        let store = LegacyPalette(defaults: defaults)
        XCTAssertEqual(store.colors.map(\.hex), original)
        store.append([RGBColor(hex: "#FF0000")!])
        XCTAssertEqual(defaults.array(forKey: "colorArray") as? [String], original + ["#ff0000"])
        XCTAssertNil(defaults.object(forKey: "colorArrayRecoveryBackup"))
        XCTAssertFalse(store.remove(at: -1)); XCTAssertFalse(store.remove(at: 4))
        XCTAssertTrue(store.remove(at: 1))
        let reopened = LegacyPalette(defaults: UserDefaults(suiteName: suite)!)
        XCTAssertEqual(reopened.colors.map(\.hex), ["#112233", "#112233", "#ff0000"])
        XCTAssertEqual(try PaletteFile.decode(PaletteFile.encode(reopened.colors)), reopened.colors)
    }
    func testMalformedDefaultsRemainUntouchedUntilBackupBeforeFirstWrite() {
        let raw: [Any] = ["#FF0000", 27, "broken", "#123456", "#FF0000"]
        defaults.set(raw, forKey: "colorArray")
        let store = LegacyPalette(defaults: defaults)
        XCTAssertEqual(store.colors.map(\.hex), ["#ff0000", "#123456", "#ff0000"])
        XCTAssertEqual(defaults.array(forKey: "colorArray")! as NSArray, raw as NSArray)
        XCTAssertNil(defaults.object(forKey: "colorArrayRecoveryBackup"))
        store.append([RGBColor(hex: "#abcdef")!])
        XCTAssertEqual(defaults.array(forKey: "colorArrayRecoveryBackup")! as NSArray, raw as NSArray)
        store.remove(at: 0)
        XCTAssertEqual(defaults.array(forKey: "colorArrayRecoveryBackup")! as NSArray, raw as NSArray)
    }
    func testWrongTopLevelAndInvalidImportNeverDeleteData() throws {
        defaults.set("original wrong-type payload", forKey: "colorArray")
        let store = LegacyPalette(defaults: defaults)
        store.append([RGBColor(hex: "#010203")!])
        XCTAssertEqual(defaults.string(forKey: "colorArrayRecoveryBackup"), "original wrong-type payload")
        for json in ["[\"#123456\",\"bad\"]", "[123]", "{}", "not json"] {
            XCTAssertThrowsError(try PaletteFile.decode(Data(json.utf8)))
            XCTAssertEqual(store.colors.map(\.hex), ["#010203"])
        }
        XCTAssertEqual(try PaletteFile.decode(Data("[]".utf8)), [])
    }
}
