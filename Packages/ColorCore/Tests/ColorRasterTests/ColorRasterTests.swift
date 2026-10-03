import XCTest
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import ColorDomain
import ColorRaster

// Synthetic asymmetric source. These helpers are test-target-only, never app resources.
enum RasterFixture {
    static let bytes: [UInt8] = [255,0,0,255, 0,255,0,255, 0,0,255,255,
                                 255,255,0,255, 255,0,255,255, 0,255,255,255]
    static func image(bytes: [UInt8] = RasterFixture.bytes, width: Int = 3, height: Int = 2, colorSpace: CGColorSpace? = nil) -> CGImage {
        let space = colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
        let provider = CGDataProvider(data: Data(bytes) as CFData)!
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
                       space: space, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
    }
    static func alphaData() -> Data {
        var bytes = [UInt8]()
        for _ in 0..<20 { for x in 0..<40 { bytes += x < 20 ? [0, 0, 0, 0] : [0, 0, 128, 128] } }
        return data(image: image(bytes: bytes, width: 40, height: 20))
    }
    static func data(orientation: Int = 1, image: CGImage = RasterFixture.image()) -> Data {
        let data = NSMutableData()
        let destination = CGImageDestinationCreateWithData(data, UTType.tiff.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(destination, image, [kCGImagePropertyOrientation: orientation] as CFDictionary)
        precondition(CGImageDestinationFinalize(destination))
        return data as Data
    }
}

final class ColorRasterTests: XCTestCase {
    func testAllEightOrientationsMatchFrozenUIKitOracleAndExportReopen() throws {
        // Frozen actual UIKit tests: up, upMirrored, down, downMirrored,
        // leftMirrored, right, rightMirrored, left, translated to EXIF 1...8.
        let corners = [
            ["#ff0000", "#0000ff", "#ffff00", "#00ffff"],
            ["#0000ff", "#ff0000", "#00ffff", "#ffff00"],
            ["#00ffff", "#ffff00", "#0000ff", "#ff0000"],
            ["#ffff00", "#00ffff", "#ff0000", "#0000ff"],
            ["#ff0000", "#ffff00", "#0000ff", "#00ffff"],
            ["#ffff00", "#ff0000", "#00ffff", "#0000ff"],
            ["#00ffff", "#0000ff", "#ffff00", "#ff0000"],
            ["#0000ff", "#00ffff", "#ff0000", "#ffff00"]
        ]
        let points = [(0.1,0.1),(0.9,0.1),(0.1,0.9),(0.9,0.9)]
        for orientation in 1...8 {
            let original = RasterFixture.data(orientation: orientation)
            let raster = try ColorRaster.decode(original)
            XCTAssertEqual(raster.sourceData, original)
            XCTAssertEqual(raster.width, orientation >= 5 ? 2 : 3)
            XCTAssertEqual(raster.height, orientation >= 5 ? 3 : 2)
            let reopened = try ColorRaster.decode(raster.pngData())
            for (index, point) in points.enumerated() {
                let location = NormalizedPoint(x: point.0, y: point.1)!
                XCTAssertEqual(raster.sample(at: location)?.hex, corners[orientation - 1][index], "EXIF \(orientation), corner \(index)")
                XCTAssertEqual(reopened.sample(at: location), raster.sample(at: location))
            }
        }
    }
    func testAlphaIsCompositedOnWhiteAndP3IsConvertedToSRGB() throws {
        let image = RasterFixture.image(bytes: [0,0,0,0, 128,0,0,128], width: 2, height: 1)
        let raster = try ColorRaster.decode(RasterFixture.data(image: image))
        XCTAssertEqual(raster.sample(at: NormalizedPoint(x: 0, y: 0)!)?.hex, "#ffffff")
        let half = try XCTUnwrap(raster.sample(at: NormalizedPoint(x: 1, y: 1)!))
        XCTAssertEqual(half.red, 255); XCTAssertEqual(Double(half.green), 127, accuracy: 1); XCTAssertEqual(Double(half.blue), 127, accuracy: 1)
        let p3 = RasterFixture.image(bytes: [255,0,0,255], width: 1, height: 1, colorSpace: CGColorSpace(name: CGColorSpace.displayP3)!)
        let converted = try ColorRaster.decode(RasterFixture.data(image: p3))
        XCTAssertEqual(converted.sample(at: .center)?.hex, "#ff0000")
    }
    func testPNGReopenPreservesAlphaSeparatelyFromWhiteDisplayMatte() throws {
        let raster = try ColorRaster.decode(RasterFixture.alphaData())
        let reopened = try ColorRaster.decode(raster.pngData())
        func alpha(_ image: CGImage, x: Int) throws -> UInt8 {
            let crop = try XCTUnwrap(image.cropping(to: CGRect(x: x, y: 2, width: 1, height: 1)))
            var bytes = [UInt8](repeating: 0, count: 4)
            return try bytes.withUnsafeMutableBytes { storage in
                let context = try XCTUnwrap(CGContext(data: storage.baseAddress, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
                context.interpolationQuality = .none; context.draw(crop, in: CGRect(x: 0, y: 0, width: 1, height: 1))
                return storage[3]
            }
        }
        for image in [raster.image, reopened.image] {
            XCTAssertEqual(try alpha(image, x: 2), 0)
            XCTAssertEqual(Double(try alpha(image, x: 30)), 128, accuracy: 1)
        }
        XCTAssertEqual(reopened.width, 40); XCTAssertEqual(reopened.height, 20)
    }
    func testFullSourceDimensionsEdgesCorruptAndCancel() throws {
        let width = 2049
        var bytes = [UInt8](repeating: 255, count: width * 3 * 4)
        bytes.replaceSubrange((bytes.count - 4)..<bytes.count, with: [7,19,231,255])
        let data = RasterFixture.data(image: RasterFixture.image(bytes: bytes, width: width, height: 3))
        let raster = try ColorRaster.decode(data)
        XCTAssertEqual(raster.width, width); XCTAssertEqual(raster.height, 3)
        XCTAssertEqual(raster.sample(at: NormalizedPoint(x: 1, y: 1)!)?.hex, "#0713e7")
        XCTAssertThrowsError(try ColorRaster.decode(Data("broken".utf8)))
        XCTAssertThrowsError(try ColorRaster.decode(data, cancelled: { true }))
        XCTAssertThrowsError(try ColorRaster.read(url: URL(fileURLWithPath: "/missing/TouchColor-test-file.png")))
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-\(UUID()).png")
        defer { try? FileManager.default.removeItem(at: url) }
        try raster.pngData().write(to: url, options: .atomic)
        XCTAssertEqual(try ColorRaster.read(url: url).sample(at: NormalizedPoint(x: 1, y: 1)!)?.hex, "#0713e7")
    }
}

final class PreviewRasterTests: XCTestCase {
    func testBoundedPreviewMatchesSourceForSmallFixturesAndAllOrientations() throws {
        for orientation in 1...8 {
            let data = RasterFixture.data(orientation: orientation)
            let source = try ColorRaster.decode(data), preview = try PreviewRaster.decode(data)
            XCTAssertFalse(preview.isReduced)
            XCTAssertEqual(preview.width, source.width); XCTAssertEqual(preview.height, source.height)
            for point in [NormalizedPoint(x: 0, y: 0)!, .center, NormalizedPoint(x: 1, y: 1)!] {
                XCTAssertEqual(preview.sample(at: point), source.sample(at: point))
            }
        }
        XCTAssertThrowsError(try PreviewRaster.decode(Data("corrupt".utf8)))
        XCTAssertThrowsError(try PreviewRaster.decode(RasterFixture.data(), cancelled: { true }))
    }
    func testLargeWatchPreviewIsExplicitlyReducedAndReopensAtBoundedDimensions() throws {
        let width = 1024, height = 768
        let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.setFillColor(CGColor(srgbRed: 1, green: 0, blue: 0, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let preview = try PreviewRaster.decode(RasterFixture.data(image: context.makeImage()!))
        XCTAssertTrue(preview.isReduced); XCTAssertEqual(preview.width, 512); XCTAssertEqual(preview.height, 384)
        XCTAssertEqual(preview.originalWidth, width); XCTAssertEqual(preview.originalHeight, height)
        XCTAssertEqual(preview.sample(at: .center)?.hex, "#ff0000")
        let cached = try PreviewRaster.decode(preview.pngData())
        XCTAssertEqual(cached.width, 512); XCTAssertEqual(cached.sample(at: .center)?.hex, "#ff0000")
    }
    func testProgressiveFileBytesCapacityAndCancellation() throws {
        let bytes = RasterFixture.alphaData()
        let file = try BoundedImageFile(maximumBytes: bytes.count)
        try file.append(bytes.prefix(7)); try file.append(bytes.dropFirst(7))
        let url = try file.finish()
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertEqual(try Data(contentsOf: url), bytes)
        XCTAssertEqual(try ColorRaster.read(url: url).sample(at: NormalizedPoint(x: 0.1, y: 0.1)!)?.hex, "#ffffff")
        XCTAssertThrowsError(try file.append(Data([0])))
        let limited = try BoundedImageFile(maximumBytes: 8)
        try limited.append(Data(repeating: 1, count: 7))
        XCTAssertThrowsError(try limited.append(Data([2, 3])))
        XCTAssertEqual(try Data(contentsOf: limited.url), Data(repeating: 1, count: 7))
        limited.cancel(); XCTAssertFalse(FileManager.default.fileExists(atPath: limited.url.path))
        XCTAssertThrowsError(try limited.finish())
    }

}
