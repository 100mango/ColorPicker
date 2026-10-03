import XCTest
import UIKit
import SwiftUI
import ColorDomain
import ColorRaster
import ColorPaletteLegacy
@testable import TouchColorVision

@MainActor final class VisionWorkspaceTests: XCTestCase {
    private func load(_ session: ImageSession, orientation: Int = 1) async throws {
        session.load(data: RasterFixture.data(orientation: orientation), name: "asymmetric.tiff", token: session.beginImport())
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertFalse(session.busy)
    }
    func testNativeCanvasPixelCoordinatesMagnificationAndResizePreserveSelection() async throws {
        let session = ImageSession(); try await load(session)
        let scroll = VisionColorScrollView(frame: CGRect(x: 0, y: 0, width: 600, height: 450))
        scroll.session = session; scroll.refresh(); scroll.layoutIfNeeded()
        XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
        scroll.choose(CGPoint(x: scroll.canvas.bounds.width * 0.1, y: scroll.canvas.bounds.height * 0.1))
        XCTAssertEqual(session.selectedColor?.hex, "#ff0000")
        session.move(dx: 1, dy: 0); XCTAssertEqual(session.selectedColor?.hex, "#00ff00")
        let selected = session.selectedPoint
        let width = scroll.canvas.convert(scroll.canvas.bounds, to: scroll).width
        session.changeZoom(4); scroll.refresh()
        XCTAssertEqual(scroll.canvas.convert(scroll.canvas.bounds, to: scroll).width, width * 4, accuracy: 0.01)
        for size in [CGSize(width: 500, height: 300), CGSize(width: 700, height: 400)] {
            scroll.frame.size = size; scroll.layoutIfNeeded(); scroll.refresh()
            XCTAssertEqual(session.selectedPoint, selected); XCTAssertEqual(session.selectedColor?.hex, "#00ff00")
            XCTAssertEqual(scroll.zoomScale, 4, accuracy: 0.001)
            let marker = CGPoint(x: selected.x * scroll.canvas.bounds.width, y: selected.y * scroll.canvas.bounds.height)
            let recovered = scroll.canvas.convert(scroll.canvas.convert(marker, to: scroll), from: scroll)
            XCTAssertEqual(recovered.x / scroll.canvas.bounds.width, selected.x, accuracy: 0.00001)
            XCTAssertEqual(recovered.y / scroll.canvas.bounds.height, selected.y, accuracy: 0.00001)
        }
        scroll.choose(CGPoint(x: -1, y: -1)); XCTAssertEqual(session.selectedPoint, selected)
        scroll.choose(CGPoint(x: scroll.canvas.bounds.width, y: 0)); XCTAssertEqual(session.selectedPoint, selected)
    }
    func testPaletteExportAndNativeFileImportPreserveDuplicateOrdering() async throws {
        let suite = "TouchColor.vision-unit.\(UUID())"
        let isolated = UserDefaults(suiteName: suite)!
        defer { isolated.removePersistentDomain(forName: suite) }
        let library = PaletteLibrary(defaults: isolated), session = ImageSession()
        let colors = ["#ff0000", "#abcdef", "#ff0000"].map { ColorDomain.RGBColor(hex: $0)! }
        library.append(colors)
        let document = ColorExportDocument(data: try PaletteFile.encode(library.colors))
        XCTAssertEqual(try PaletteFile.decode(document.data), colors)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("palette-\(UUID()).json")
        defer { try? FileManager.default.removeItem(at: url) }
        try document.data.write(to: url)
        VisionImport.file(url, session: session, library: library)
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(library.colors, colors + colors)
        library.remove(at: 1)
        XCTAssertEqual(PaletteLibrary(defaults: isolated).colors.map(\.hex), ["#ff0000", "#ff0000", "#ff0000", "#abcdef", "#ff0000"])
    }
    func testRealProviderImportCancelMissingFileAndFullSizePNGReopen() async throws {
        let session = ImageSession(); try await load(session)
        let source = try XCTUnwrap(session.raster)
        let provider = NSItemProvider()
        provider.registerDataRepresentation(forTypeIdentifier: "public.png", visibility: .all) { completion in
            completion(try? source.pngData(), nil); return nil
        }
        XCTAssertTrue(VisionImport.providers([provider], session: session))
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
        let document = ColorExportDocument(data: try XCTUnwrap(session.raster).pngData())
        let reopened = try ColorRaster.decode(document.data)
        XCTAssertEqual(reopened.width, 3); XCTAssertEqual(reopened.height, 2)
        XCTAssertEqual(reopened.sample(at: NormalizedPoint(x: 0.1, y: 0.1)!)?.hex, "#ff0000")
        let old = session.beginImport(); session.cancelImport()
        session.load(data: RasterFixture.data(orientation: 3), name: "cancelled", token: old)
        XCTAssertNotEqual(session.sourceName, "cancelled")
        session.load(url: URL(fileURLWithPath: "/missing/image.png"), token: session.beginImport())
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertNotNil(session.errorMessage); XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
    }
}
