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

final class PaletteInboxTests: XCTestCase {
    func testPersistedInboxStorageIdentifiersRemainByteIdentical() {
        XCTAssertEqual(PaletteInbox.pendingStorageIdentifier, "colorInboxPendingV1")
        XCTAssertEqual(PaletteInbox.acceptedReceiptStorageIdentifier, "colorInboxAcceptedV1")
        XCTAssertEqual(PaletteInbox.rejectedReceiptStorageIdentifier, "colorInboxRejectedV1")
    }
    func testExplicitAcceptanceAtomicDomainPreservesLegacyBackupOrderAndDuplicateReceipt() throws {
        let suite = "TouchColor.inbox.\(UUID())"
        let isolated = UserDefaults(suiteName: suite)!
        defer { isolated.removePersistentDomain(forName: suite) }
        isolated.setPersistentDomain(["colorArray": ["#FF0000", "bad", "#ff0000"], "unrelated": "keep"], forName: suite)
        let inbox = PaletteInbox(defaults: isolated, domain: suite)
        let message = try PaletteTransfer(colors: [RGBColor(hex: "#abcdef")!, RGBColor(hex: "#abcdef")!])
        let data = try message.encoded()
        XCTAssertNil(try inbox.receive(data)); XCTAssertNil(try inbox.receive(data))
        XCTAssertEqual(try inbox.pending().count, 1)
        XCTAssertEqual(isolated.stringArray(forKey: "colorArray"), ["#FF0000", "bad", "#ff0000"])
        let receipt = try inbox.accept(message.id)
        XCTAssertEqual(receipt.outcome, .accepted)
        XCTAssertEqual(isolated.stringArray(forKey: "colorArray"), ["#ff0000", "#ff0000", "#abcdef", "#abcdef"])
        XCTAssertEqual(isolated.stringArray(forKey: "colorArrayRecoveryBackup"), ["#FF0000", "bad", "#ff0000"])
        XCTAssertEqual(isolated.string(forKey: "unrelated"), "keep")
        let reopened = PaletteInbox(defaults: isolated, domain: suite)
        XCTAssertEqual(try reopened.receive(data), receipt); XCTAssertEqual(try reopened.accept(message.id), receipt)
        XCTAssertEqual(isolated.stringArray(forKey: "colorArray")?.count, 4)
        XCTAssertTrue(try reopened.pending().isEmpty)
    }
    func testPartialMalformedConflictingAndRejectedTransfersCannotChangePhonePalette() throws {
        let suite = "TouchColor.inbox.\(UUID())"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(["#123456"], forKey: "colorArray")
        let inbox = PaletteInbox(defaults: defaults, domain: suite)
        let message = try PaletteTransfer(colors: [RGBColor(hex: "#ff0000")!]), data = try message.encoded()
        _ = try inbox.receive(data)
        XCTAssertThrowsError(try inbox.receive(data.prefix(data.count / 2)))
        let conflict = try PaletteTransfer(id: message.id, colors: [RGBColor(hex: "#00ff00")!])
        XCTAssertThrowsError(try inbox.receive(conflict.encoded()))
        XCTAssertEqual(try inbox.pending(), [message])
        let receipt = try inbox.reject(message.id)
        XCTAssertEqual(receipt.outcome, .rejected)
        XCTAssertEqual(defaults.stringArray(forKey: "colorArray"), ["#123456"])
        XCTAssertTrue(try inbox.pending().isEmpty)
        XCTAssertEqual(try PaletteTransferReceipt.decode(receipt.encoded()), receipt)
        XCTAssertThrowsError(try PaletteTransferReceipt.decode(Data(repeating: 0, count: 1025)))
    }
    func testRejectedReceiptSurvivesRetryRelaunchAndConflictingIdentifier() throws {
        let suite = "TouchColor.inbox-rejected.\(UUID())"
        let isolated = UserDefaults(suiteName: suite)!
        defer { isolated.removePersistentDomain(forName: suite) }
        isolated.set(["#123456"], forKey: "colorArray")
        let inbox = PaletteInbox(defaults: isolated, domain: suite)
        let message = try PaletteTransfer(colors: [RGBColor(hex: "#ff0000")!]), data = try message.encoded()
        _ = try inbox.receive(data)
        let receipt = try inbox.reject(message.id)
        let reopened = PaletteInbox(defaults: isolated, domain: suite)
        XCTAssertEqual(try reopened.receive(data), receipt)
        XCTAssertEqual(try reopened.reject(message.id), receipt)
        XCTAssertEqual(try reopened.accept(message.id), receipt)
        XCTAssertTrue(try reopened.pending().isEmpty)
        XCTAssertEqual(isolated.stringArray(forKey: "colorArray"), ["#123456"])
        let conflict = try PaletteTransfer(id: message.id, colors: [RGBColor(hex: "#abcdef")!])
        XCTAssertThrowsError(try reopened.receive(conflict.encoded()))
    }

    func testConflictingSavedOutcomesNeverChangeThePaletteOrInbox() throws {
        let suite = "TouchColor.inbox-conflict.\(UUID())", defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let request = try PaletteTransfer(colors: [RGBColor(hex: "#abcdef")!])
        let outcomes = [request.id.uuidString: try PaletteFingerprint.of(request)]
        let original: [String: Any] = [LegacyPalette.key: ["#ff0000"], PaletteInbox.acceptedReceiptStorageIdentifier: outcomes, PaletteInbox.rejectedReceiptStorageIdentifier: outcomes]
        defaults.setPersistentDomain(original, forName: suite)
        let inbox = PaletteInbox(defaults: defaults, domain: suite)
        XCTAssertThrowsError(try inbox.receive(request.encoded()))
        XCTAssertThrowsError(try inbox.accept(request.id)); XCTAssertThrowsError(try inbox.reject(request.id))
        XCTAssertEqual(defaults.persistentDomain(forName: suite) as NSDictionary?, original as NSDictionary)
    }

}

final class PaletteSelectionTests: XCTestCase {
    func testCompleteFileSelectionPreservesOrderDuplicatesAndRejectsInvalidInput() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("palette-review-\(UUID()).json")
        defer { try? FileManager.default.removeItem(at: url) }
        try Data("[\"#ABCDEF\",\"#123456\",\"#abcdef\"]".utf8).write(to: url)
        let selected = try PaletteSelection.read(url)
        XCTAssertEqual(selected.colors.map(\.hex), ["#abcdef", "#123456", "#abcdef"])
        try Data("[\"#123456\",\"invalid\"]".utf8).write(to: url)
        XCTAssertThrowsError(try PaletteSelection.read(url))
        XCTAssertEqual(selected.colors.map(\.hex), ["#abcdef", "#123456", "#abcdef"])
        XCTAssertThrowsError(try PaletteSelection.read(url, cancelled: { true }))
        let file = try FileHandle(forWritingTo: url)
        try file.truncate(atOffset: UInt64(PaletteSelection.maximumBytes + 1)); try file.close()
        XCTAssertThrowsError(try PaletteSelection.read(url))
    }
}
