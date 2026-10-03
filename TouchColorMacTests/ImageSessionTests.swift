import XCTest
import AppKit
import SwiftUI
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
    func testActualSwiftUIWindowKeepsImportedCanvasInsideCompactContentBounds() async throws {
        let suite = "TouchColor.window-layout.\(UUID())"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let session = ImageSession()
        let host = NSHostingView(rootView: ColorWindow(library: PaletteLibrary(defaults: defaults), session: session).background(NativeWindowMinimumSize()))
        let previous = NSApp.keyWindow
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 588), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.contentView = host
        window.makeKeyAndOrderFront(nil)
        defer { window.orderOut(nil); window.contentView = nil; previous?.makeKeyAndOrderFront(nil) }
        session.load(data: RasterFixture.data(), name: "layout.tiff", token: session.beginImport())
        try await waitForImport(session)
        for size in [NSSize(width: 960, height: 588), NSSize(width: 800, height: 530)] {
            window.setContentSize(size)
            host.layoutSubtreeIfNeeded()
            try await Task.sleep(nanoseconds: 100_000_000)
            host.layoutSubtreeIfNeeded()
            func find(_ view: NSView) -> ColorScrollView? {
                if let scroll = view as? ColorScrollView { return scroll }
                for child in view.subviews { if let found = find(child) { return found } }
                return nil
            }
            let scroll = try XCTUnwrap(find(host))
            let viewport = scroll.convert(scroll.bounds, to: host)
            print("MAC_WINDOW_LAYOUT requested=\(size) window=\(window.frame) layout=\(window.contentLayoutRect) host=\(host.frame) bounds=\(host.bounds) viewport=\(viewport)")
            XCTAssertEqual(host.bounds.width, size.width, accuracy: 1)
            XCTAssertEqual(host.bounds.height, size.height, accuracy: 1)
            XCTAssertTrue(host.bounds.insetBy(dx: -1, dy: -1).contains(viewport), "viewport \(viewport), host \(host.bounds)")
            XCTAssertGreaterThan(viewport.height, 100)
            // Leave room for the actual three-row sampler and status, rather than growing the window content.
            XCTAssertLessThan(viewport.height, host.bounds.height - 100)
        }
    }
    func testNativeScrollMagnificationPanResizeAndMarkerUseOneCoordinateSpace() async throws {
        let session = ImageSession()
        session.load(data: RasterFixture.data(), name: "geometry.tiff", token: session.beginImport())
        try await waitForImport(session)
        let scroll = ColorScrollView(frame: NSRect(x: 0, y: 0, width: 600, height: 450))
        scroll.allowsMagnification = true; scroll.minMagnification = 1; scroll.maxMagnification = 100
        let canvas = PixelCanvas(); canvas.session = session
        scroll.session = session; scroll.documentView = canvas; scroll.updateCanvasSize()
        let baseWidth = canvas.convert(canvas.bounds, to: scroll).width
        scroll.setMagnification(4, centeredAt: NSPoint(x: canvas.bounds.midX, y: canvas.bounds.midY))
        scroll.updateCanvasSize()
        XCTAssertEqual(scroll.magnification, 4, accuracy: 0.001)
        XCTAssertEqual(canvas.convert(canvas.bounds, to: scroll).width, baseWidth * 4, accuracy: 0.01)
        scroll.contentView.scroll(to: NSPoint(x: 25, y: 30)); scroll.reflectScrolledClipView(scroll.contentView)
        session.select(NormalizedPoint(x: 0.9, y: 0.9)!)
        for size in [NSSize(width: 600, height: 450), NSSize(width: 400, height: 300)] {
            scroll.setFrameSize(size); scroll.updateCanvasSize()
            let marker = NSPoint(x: session.selectedPoint.x * canvas.bounds.width, y: session.selectedPoint.y * canvas.bounds.height)
            let visible = canvas.convert(marker, to: scroll)
            let recovered = canvas.convert(visible, from: scroll)
            XCTAssertEqual(recovered.x / canvas.bounds.width, session.selectedPoint.x, accuracy: 0.000001)
            XCTAssertEqual(recovered.y / canvas.bounds.height, session.selectedPoint.y, accuracy: 0.000001)
            XCTAssertEqual(session.selectedColor?.hex, "#00ffff")
            XCTAssertEqual(scroll.magnification, 4, accuracy: 0.001)
        }
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
    func testPNGExportSnapshotSurvivesNewImportAndReopensActualPixels() async throws {
        let session = ImageSession()
        session.load(data: RasterFixture.data(), name: "original.tiff", token: session.beginImport())
        try await waitForImport(session)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-export-\(UUID()).png")
        defer { try? FileManager.default.removeItem(at: url) }
        session.exportPNG(to: url)
        session.load(data: RasterFixture.data(orientation: 3), name: "replacement.tiff", token: session.beginImport())
        for _ in 0..<100 where session.exporting { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertFalse(session.exporting)
        let reopened = try ColorRaster.read(url: url)
        XCTAssertEqual(reopened.width, 3); XCTAssertEqual(reopened.height, 2)
        XCTAssertEqual(reopened.sample(at: NormalizedPoint(x: 0.1, y: 0.1)!)?.hex, "#ff0000")
        try await waitForImport(session)
        XCTAssertEqual(session.sourceName, "replacement.tiff")
        XCTAssertEqual(session.raster?.sample(at: NormalizedPoint(x: 0.1, y: 0.1)!)?.hex, "#00ffff")
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
