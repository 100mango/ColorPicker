import XCTest
import AppKit
import ColorDomain
import ColorRaster
@testable import TouchColorMac

@MainActor final class ImageSessionTests: XCTestCase {
    private func waitForImport(_ session: ImageSession) async throws {
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertFalse(session.busy)
    }
    func testRealDataImportNumericSelectionAndWindowIsolation() async throws {
        let first = ImageSession(); let second = ImageSession()
        first.load(data: RasterFixture.data(), name: "asymmetric.tiff", token: first.beginImport())
        try await waitForImport(first)
        XCTAssertEqual(first.selectedColor?.hex, "#ff00ff")
        first.select(NormalizedPoint(x: 0.1, y: 0.1)!)
        XCTAssertEqual(first.selectedColor?.hex, "#ff0000")
        first.move(dx: 1, dy: 0)
        XCTAssertEqual(first.selectedColor?.hex, "#00ff00")
        first.changeZoom(150); XCTAssertEqual(first.zoom, 100)
        XCTAssertNil(second.raster); XCTAssertNil(second.selectedColor)
        let scroll = ColorScrollView(frame: NSRect(x: 0, y: 0, width: 600, height: 500))
        scroll.session = first; scroll.documentView = PixelCanvas()
        scroll.updateCanvasSize()
        let selected = first.selectedPoint
        scroll.setFrameSize(NSSize(width: 900, height: 300)); scroll.updateCanvasSize()
        XCTAssertEqual(first.selectedPoint, selected)
        XCTAssertEqual(first.raster?.sample(at: selected), first.selectedColor)
    }
    func testReplacingCancellingAndFailingImportCannotOverwriteValidSource() async throws {
        let session = ImageSession()
        let stale = session.beginImport()
        let newest = session.beginImport()
        session.load(data: RasterFixture.data(orientation: 3), name: "old.tiff", token: stale)
        session.load(data: RasterFixture.data(), name: "new.tiff", token: newest)
        try await waitForImport(session)
        XCTAssertEqual(session.sourceName, "new.tiff")
        let cancelled = session.beginImport(); session.cancelImport()
        session.load(data: RasterFixture.data(orientation: 3), name: "cancelled.tiff", token: cancelled)
        XCTAssertEqual(session.sourceName, "new.tiff")
        session.load(data: Data("broken".utf8), name: "broken", token: session.beginImport())
        try await waitForImport(session)
        XCTAssertNotNil(session.errorMessage); XCTAssertEqual(session.sourceName, "new.tiff")
        session.load(url: URL(fileURLWithPath: "/missing/no-image.png"), token: session.beginImport())
        try await waitForImport(session)
        XCTAssertNotNil(session.errorMessage); XCTAssertEqual(session.sourceName, "new.tiff")
    }
    func testRealPasteAndPaletteImportKeepOrderAndDuplicates() async throws {
        let suite = "TouchColor.mac-tests.\(UUID())"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let library = PaletteLibrary(defaults: defaults); let session = ImageSession()
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(RasterFixture.data(), forType: .tiff)
        MacImportExport.paste(session: session, library: library)
        try await waitForImport(session)
        XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
        let palette = Data("[\"#FF0000\",\"#123456\",\"#FF0000\"]".utf8)
        session.finishPaletteImport(palette, token: session.beginImport(), library: library)
        XCTAssertEqual(library.colors.map(\.hex), ["#ff0000", "#123456", "#ff0000"])
        library.copy(library.colors[1])
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "#123456")
        library.remove(at: 1)
        XCTAssertEqual(PaletteLibrary(defaults: defaults).colors.map(\.hex), ["#ff0000", "#ff0000"])
    }
}
