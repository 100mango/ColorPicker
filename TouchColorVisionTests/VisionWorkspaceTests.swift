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
        let providerURL = FileManager.default.temporaryDirectory.appendingPathComponent("provider-\(UUID()).png")
        try source.pngData().write(to: providerURL)
        defer { try? FileManager.default.removeItem(at: providerURL) }
        let provider = NSItemProvider()
        provider.registerFileRepresentation(forTypeIdentifier: "public.png", fileOptions: [], visibility: .all) { completion in
            completion(providerURL, false, nil); return nil
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
    func testRenderedVisionCanvasUsesTheSameWhiteAlphaPolicyAsSampling() async throws {
        let session = ImageSession()
        session.load(data: RasterFixture.alphaData(), name: "alpha.tiff", token: session.beginImport())
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        session.select(NormalizedPoint(x: 0.95, y: 0.95)!)
        let canvas = VisionPixelCanvas(frame: CGRect(x: 0, y: 0, width: 400, height: 200))
        canvas.session = session; canvas.image = try XCTUnwrap(session.raster).image
        canvas.setNeedsDisplay(); canvas.layer.displayIfNeeded()
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = true
        let image = UIGraphicsImageRenderer(size: canvas.bounds.size, format: format).image { canvas.layer.render(in: $0.cgContext) }
        let cg = try XCTUnwrap(image.cgImage)
        XCTAssertEqual(RasterPixelSampler.sample(image: cg, at: NormalizedPoint(x: 0.125, y: 0.25)!)?.hex, "#ffffff")
        let blue = try XCTUnwrap(RasterPixelSampler.sample(image: cg, at: NormalizedPoint(x: 0.625, y: 0.25)!))
        XCTAssertEqual(Double(blue.red), 127, accuracy: 1); XCTAssertEqual(Double(blue.green), 127, accuracy: 1); XCTAssertEqual(blue.blue, 255)
    }

    func testBoundedProviderFilePreservesAlphaOrientationsAndRejectsOversizeBeforeRead() async throws {
        let source = FileManager.default.temporaryDirectory.appendingPathComponent("provider-source-\(UUID()).tiff")
        defer { try? FileManager.default.removeItem(at: source) }
        for bytes in (1...8).map({ RasterFixture.data(orientation: $0) }) + [RasterFixture.alphaData()] {
            try bytes.write(to: source)
            let copy = try NativePhotoFile.copyBounded(source)
            defer { try? FileManager.default.removeItem(at: copy) }
            XCTAssertEqual(try Data(contentsOf: copy), bytes)
            let original = try ColorRaster.decode(bytes), copied = try ColorRaster.read(url: copy)
            XCTAssertEqual(original.sourceOrientation, copied.sourceOrientation)
            XCTAssertEqual(original.width, copied.width); XCTAssertEqual(original.height, copied.height)
            for point in [NormalizedPoint.center, NormalizedPoint(x: 0.1, y: 0.1)!, NormalizedPoint(x: 0.75, y: 0.25)!] {
                XCTAssertEqual(original.sample(at: point), copied.sample(at: point))
            }
        }
        XCTAssertThrowsError(try NativePhotoFile.copyBounded(source, cancelled: { true }))
        let file = try FileHandle(forWritingTo: source)
        try file.truncate(atOffset: UInt64(ColorRaster.maximumEncodedBytes + 1)); try file.close()
        XCTAssertThrowsError(try NativePhotoFile.copyBounded(source)) { error in
            guard case RasterError.tooLarge = error else { return XCTFail("Unexpected error: \(error)") }
        }
        let session = ImageSession(); try await load(session)
        let provider = NSItemProvider()
        provider.registerFileRepresentation(forTypeIdentifier: "public.tiff", fileOptions: [], visibility: .all) { completion in
            completion(source, true, nil); return nil
        }
        XCTAssertTrue(VisionImport.providers([provider], session: session))
        for _ in 0..<150 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertFalse(session.busy); XCTAssertNotNil(session.errorMessage)
        XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
    }

}
