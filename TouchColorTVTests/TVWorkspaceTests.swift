import XCTest
import UIKit
import CoreImage
import ColorDomain
import ColorPaletteLegacy
import ColorRaster
@testable import TouchColorTV

@MainActor final class TVWorkspaceTests: XCTestCase {
    func testTVByteQuotaRefusesNewSaveWithoutDroppingExistingDuplicates() {
        let suite = "TouchColor.tv-unit.\(UUID())"
        let isolated = UserDefaults(suiteName: suite)!
        defer { isolated.removePersistentDomain(forName: suite) }
        isolated.set(["#FF0000", "bad", "#ff0000"], forKey: "colorArray")
        let library = PaletteLibrary(defaults: isolated, domain: suite)
        library.append([RGBColor(hex: "#123456")!])
        XCTAssertEqual(library.colors.map(\.hex), ["#ff0000", "#ff0000", "#123456"])
        XCTAssertEqual(isolated.stringArray(forKey: "colorArrayRecoveryBackup"), ["#FF0000", "bad", "#ff0000"])
        let before = isolated.stringArray(forKey: "colorArray")
        isolated.set(Data(repeating: 0, count: PaletteLibrary.maximumBytes), forKey: "synthetic-other-app-data")
        library.append([RGBColor(hex: "#abcdef")!])
        XCTAssertNotNil(library.error); XCTAssertEqual(isolated.stringArray(forKey: "colorArray"), before)
        XCTAssertEqual(PaletteLibrary(defaults: isolated, domain: suite).colors.map(\.hex), before)
    }
    func testActualPaletteCodePixelsDecodeExactOrderedJSONAndRejectCapacityOverflow() throws {
        let colors = ["#123456", "#ff0000", "#123456"].map { RGBColor(hex: $0)! }
        let cg = try TVPaletteCode.image(colors)
        let scaled = CIImage(cgImage: cg).transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: CIContext(), options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let features = detector.features(in: scaled).compactMap { $0 as? CIQRCodeFeature }
        XCTAssertEqual(features.count, 1)
        let text = try XCTUnwrap(features.first?.messageString)
        XCTAssertEqual(try PaletteFile.decode(Data(text.utf8)), colors)
        XCTAssertThrowsError(try TVPaletteCode.image(Array(repeating: colors[0], count: 9)))
        XCTAssertThrowsError(try TVPaletteCode.image([]))
    }
    func testSourceSamplingAndPNGRemainFullSizeOnTV() async throws {
        let session = ImageSession()
        session.load(data: RasterFixture.data(), name: "tv-asymmetric", token: session.beginImport())
        for _ in 0..<100 where session.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(session.selectedColor?.hex, "#ff00ff")
        session.move(dx: 0, dy: -1); XCTAssertEqual(session.selectedColor?.hex, "#00ff00")
        session.changeZoom(2); let point = session.selectedPoint
        XCTAssertEqual(session.raster?.sample(at: point)?.hex, "#00ff00")
        let data = try XCTUnwrap(session.raster).pngData(), reopened = try ColorRaster.decode(data)
        XCTAssertEqual(reopened.width, 3); XCTAssertEqual(reopened.height, 2)
        XCTAssertEqual(reopened.sample(at: point)?.hex, "#00ff00")
    }
}
