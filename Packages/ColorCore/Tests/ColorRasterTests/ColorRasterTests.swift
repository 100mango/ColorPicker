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

private enum PNGTestChunks {
    static func split(_ data: Data) -> [(String, Data)] {
        let bytes = Array(data); var offset = 8; var result: [(String, Data)] = []
        while offset < bytes.count {
            let length = Int(UInt32(bytes[offset]) << 24 | UInt32(bytes[offset + 1]) << 16
                | UInt32(bytes[offset + 2]) << 8 | UInt32(bytes[offset + 3]))
            let type = String(bytes: bytes[(offset + 4)..<(offset + 8)], encoding: .ascii)!
            result.append((type, Data(bytes[(offset + 8)..<(offset + 8 + length)])))
            offset += length + 12
        }
        return result
    }
    static func join(_ chunks: [(String, Data)]) -> Data {
        var result = Data([137, 80, 78, 71, 13, 10, 26, 10])
        func appendWord(_ value: UInt32) {
            result.append(contentsOf: [UInt8((value >> 24) & 255), UInt8((value >> 16) & 255), UInt8((value >> 8) & 255), UInt8(value & 255)])
        }
        for (type, payload) in chunks {
            appendWord(UInt32(payload.count))
            let body = Data(type.utf8) + payload
            result.append(body)
            // Independent bit-at-a-time fixture CRC; production uses a lookup table.
            var crc = UInt32.max
            for byte in body {
                crc ^= UInt32(byte)
                for _ in 0..<8 { crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xedb88320 : crc >> 1 }
            }
            appendWord(crc ^ UInt32.max)
        }
        return result
    }
}

final class ColorRasterTests: XCTestCase {
    func testPNGChunkBoundsCRCAndTerminalBoundaryRejectMalformedFiles() throws {
        let complete = try ColorRaster.decode(RasterFixture.data()).pngData()
        var badCRC = complete; badCRC[badCRC.count - 1] ^= 1
        var oversizedLength = complete
        oversizedLength.replaceSubrange(8..<12, with: [255, 255, 255, 255])
        let chunks = PNGTestChunks.split(complete)
        let nonemptyEnd = PNGTestChunks.join(Array(chunks.dropLast()) + [("IEND", Data([1]))])
        let afterEnd = complete + PNGTestChunks.join([("tEXt", Data("Note\0extra".utf8))]).dropFirst(8)
        let incomplete: [Data] = [Data(complete.prefix(10)), Data(complete.prefix(14)),
            Data(complete.prefix(22)), Data(complete.prefix(31)), Data(complete.dropLast()),
            Data(complete.dropLast(12)), badCRC, oversizedLength, nonemptyEnd, afterEnd]
        for (index, data) in incomplete.enumerated() {
            XCTAssertThrowsError(try ColorRaster.decode(data), "Malformed PNG variant \(index)")
            XCTAssertThrowsError(try PreviewRaster.decode(data), "Malformed PNG preview variant \(index)")
        }
    }
    func testValidPNGAncillaryAndMultipleIDATKeepOriginalBytesAndPixels() throws {
        let original = try ColorRaster.decode(RasterFixture.data()).pngData()
        var chunks: [(String, Data)] = []
        for (type, payload) in PNGTestChunks.split(original) {
            if type == "IDAT" {
                if !chunks.contains(where: { $0.0 == "IDAT" }) { chunks.append(("tEXt", Data("Comment\0synthetic metadata".utf8))) }
                let middle = payload.count / 2
                chunks.append((type, Data(payload.prefix(middle))))
                chunks.append((type, Data(payload.dropFirst(middle))))
            } else { chunks.append((type, payload)) }
        }
        let modified = PNGTestChunks.join(chunks)
        XCTAssertEqual(Array(modified.suffix(4)), [174, 66, 96, 130], "Standard IEND CRC")
        let baseline = try ColorRaster.decode(original), source = try ColorRaster.decode(modified)
        let preview = try PreviewRaster.decode(modified)
        XCTAssertEqual(source.sourceData, modified)
        XCTAssertEqual(source.width, 3); XCTAssertEqual(source.height, 2)
        for point in [NormalizedPoint(x: 0, y: 0)!, .center, NormalizedPoint(x: 1, y: 1)!] {
            XCTAssertEqual(source.sample(at: point), baseline.sample(at: point))
            XCTAssertEqual(preview.sample(at: point), baseline.sample(at: point))
        }
    }
    func testPNGCRCScanCancelsWithinOneLargeIDATWithoutDecoding() throws {
        var pixels = [UInt8](); pixels.reserveCapacity(256 * 256 * 4)
        var state: UInt32 = 0x12345678
        for _ in 0..<(256 * 256) {
            state ^= state << 13; state ^= state >> 17; state ^= state << 5
            pixels.append(contentsOf: [UInt8(state & 255), UInt8((state >> 8) & 255), UInt8((state >> 16) & 255), 255])
        }
        let complete = try ColorRaster.decode(RasterFixture.data(image: RasterFixture.image(bytes: pixels, width: 256, height: 256))).pngData()
        let chunks = PNGTestChunks.split(complete)
        var compressed = Data()
        for (type, payload) in chunks where type == "IDAT" { compressed.append(payload) }
        XCTAssertGreaterThan(compressed.count, 128 * 1024)
        let single = PNGTestChunks.join([try XCTUnwrap(chunks.first(where: { $0.0 == "IHDR" })), ("IDAT", compressed), ("IEND", Data())])
        var checks = 0
        XCTAssertThrowsError(try ColorRaster.decode(single, cancelled: { checks += 1; return checks == 6 })) {
            guard let error = $0 as? RasterError, case .cancelled = error else { return XCTFail("Expected cancellation inside CRC scan, got \($0)") }
        }
        XCTAssertEqual(checks, 6)
        checks = 0
        XCTAssertThrowsError(try PreviewRaster.decode(single, cancelled: { checks += 1; return checks == 6 })) {
            guard let error = $0 as? RasterError, case .cancelled = error else { return XCTFail("Expected preview cancellation inside CRC scan, got \($0)") }
        }
        XCTAssertEqual(checks, 6)
    }
    private func assertCompleteNonPNGRemainsReadable(_ type: UTType) throws {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil) else {
            throw XCTSkip("No synthetic \(type.identifier) encoder on this runtime")
        }
        var pixels = [UInt8]()
        for _ in 0..<(64 * 64) { pixels.append(contentsOf: [17, 34, 51, 255]) }
        let image = RasterFixture.image(bytes: pixels, width: 64, height: 64)
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 1] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw XCTSkip("Synthetic \(type.identifier) encoding is unavailable on this runtime") }
        let encoded = data as Data, raster = try ColorRaster.decode(encoded), preview = try PreviewRaster.decode(encoded)
        XCTAssertEqual(raster.sourceData, encoded); XCTAssertEqual(raster.width, 64); XCTAssertEqual(raster.height, 64)
        XCTAssertEqual(preview.sample(at: .center), raster.sample(at: .center))
    }
    func testCompleteJPEGStillUsesOriginalImageIOPath() throws { try assertCompleteNonPNGRemainsReadable(.jpeg) }
    func testCompleteHEIFStillUsesOriginalImageIOPath() throws { try assertCompleteNonPNGRemainsReadable(.heic) }
    func testDimensionBearingTruncatedPNGIsRejectedBySourceAndPreviewDecoders() throws {
        let complete = try ColorRaster.decode(RasterFixture.data()).pngData()
        let truncated = Data(complete.dropLast(12)) // Entire terminal PNG IEND chunk.
        let source = try XCTUnwrap(CGImageSourceCreateWithData(truncated as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual((properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue, 3)
        XCTAssertEqual((properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue, 2)
        print("TRUNCATED_PNG_IMAGEIO_STATUS: source=\(CGImageSourceGetStatus(source).rawValue) image=\(CGImageSourceGetStatusAtIndex(source, 0).rawValue)")
        XCTAssertEqual(try ColorRaster.decode(complete).sourceData, complete)
        XCTAssertEqual(try PreviewRaster.decode(complete).width, 3)
        XCTAssertThrowsError(try ColorRaster.decode(truncated))
        XCTAssertThrowsError(try PreviewRaster.decode(truncated))
    }
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
