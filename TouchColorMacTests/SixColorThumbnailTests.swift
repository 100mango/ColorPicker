import XCTest
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

final class SixColorThumbnailTests: XCTestCase {
    private func image(origins: [(Int, Int)], corrupt: Bool = false) throws -> Data {
        let width = 420, height = 300, side = 30
        var bytes = [UInt8](repeating: 245, count: width * height * 4)
        let colors: [[UInt8]] = [[255,0,0], [0,255,0], [0,0,255], [255,255,0], [255,0,255], [0,255,255]]
        for (left, top) in origins {
            for y in 0..<(2 * side) { for x in 0..<(3 * side) {
                let color = corrupt && y >= side ? [UInt8](repeating: 150, count: 3) : colors[(y / side) * 3 + x / side]
                let offset = ((top + y) * width + left + x) * 4
                for channel in 0..<3 { bytes[offset + channel] = color[channel] }
                bytes[offset + 3] = 255
            } }
        }
        let image = try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: CGDataProvider(data: Data(bytes) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let data = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil); XCTAssertTrue(CGImageDestinationFinalize(destination))
        return data as Data
    }
    func testFindsOnlyCompleteAsymmetricVisibleFixtureAtItsActualPosition() throws {
        let positions = try SixColorThumbnail.locate(in: image(origins: [(57, 91)]))
        XCTAssertEqual(positions.count, 1)
        let point = try XCTUnwrap(positions.first)
        XCTAssertEqual(point.x, 102.0 / 420, accuracy: 0.005)
        XCTAssertEqual(point.y, 121.0 / 300, accuracy: 0.005)
        XCTAssertTrue(try SixColorThumbnail.locate(in: image(origins: [(57, 91)], corrupt: true)).isEmpty)
        XCTAssertTrue(try SixColorThumbnail.locate(in: image(origins: [])).isEmpty)
        XCTAssertEqual(try SixColorThumbnail.locate(in: image(origins: [(20, 40), (200, 180)])).count, 2,
                       "Ambiguous duplicate thumbnails must not collapse to a single click target")
    }
}
