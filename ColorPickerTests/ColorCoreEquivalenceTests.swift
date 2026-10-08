import XCTest
import UIKit
import ImageIO
import UniformTypeIdentifiers
import ColorDomain
import ColorRaster
import ColorPaletteLegacy

/// Direct comparison with untouched legacy Objective-C interfaces, not just reimplemented formulas.
final class ColorCoreEquivalenceTests: XCTestCase {
    func testDomainMatchesLegacyNormalizationRGBAndFiniteGeometry() {
        for red in stride(from: 0, through: 255, by: 17) {
            for green in stride(from: 0, through: 255, by: 17) {
                for blue in stride(from: 0, through: 255, by: 17) {
                    let value = ColorDomain.RGBColor(red: UInt8(red), green: UInt8(green), blue: UInt8(blue))
                    XCTAssertEqual(value.hex, TCHexColor(UInt8(red), UInt8(green), UInt8(blue)))
                    XCTAssertEqual(value.hex, TCNormalizeHexColor(value.hex.uppercased()))
                    XCTAssertEqual(value.rgbDescription, TCRGBDescription(value.hex))
                }
            }
        }
        for input in ["", "#fff", "#GG0000", "#12345678", "#abcdef ", "abcdefg", "#AB09EF"] {
            XCTAssertEqual(ColorDomain.RGBColor(hex: input)?.hex, TCNormalizeHexColor(input))
        }
        let rect = CGRect(x: 20, y: 40, width: 200, height: 100)
        for point in [CGPoint(x: 120, y: 90), CGPoint(x: 20, y: 40), CGPoint(x: 220, y: 140), CGPoint(x: -1, y: 90)] {
            var legacy = CGPoint.zero
            let valid = TCNormalizedPoint(point, rect, &legacy)
            let portable = NormalizedPoint.inside(x: point.x, y: point.y, originX: rect.minX, originY: rect.minY, width: rect.width, height: rect.height)
            XCTAssertEqual(valid, portable != nil)
            if let portable { XCTAssertEqual(legacy.x, portable.x, accuracy: 0.000001); XCTAssertEqual(legacy.y, portable.y, accuracy: 0.000001) }
        }
    }
    func testSourcePixelsMatchUIKitAcrossAllOrientationsAndScales() throws {
        let bytes: [UInt8] = [255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255, 255,0,255,255, 0,255,255,255]
        let provider = CGDataProvider(data: Data(bytes) as CFData)!
        let cg = CGImage(width: 3, height: 2, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 12, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                         bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
                         provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
        let orientations: [UIImage.Orientation] = [.up, .upMirrored, .down, .downMirrored, .leftMirrored, .right, .rightMirrored, .left]
        for (index, orientation) in orientations.enumerated() {
            let data = NSMutableData()
            let destination = CGImageDestinationCreateWithData(data, UTType.tiff.identifier as CFString, 1, nil)!
            CGImageDestinationAddImage(destination, cg, [kCGImagePropertyOrientation: index + 1] as CFDictionary)
            XCTAssertTrue(CGImageDestinationFinalize(destination))
            let raster = try ColorRaster.decode(data as Data)
            for scale in [1.0, 2.0, 3.0] {
                let ui = UIImage(cgImage: cg, scale: scale, orientation: orientation)
                for (x,y) in [(0.1,0.1),(0.9,0.1),(0.1,0.9),(0.9,0.9),(1.0,1.0)] {
                    let portable = raster.sample(at: NormalizedPoint(x: x, y: y)!)?.hex
                    XCTAssertEqual(portable, TCSampleImage(ui, CGPoint(x: x, y: y)), "EXIF \(index + 1), scale \(scale), \(x),\(y)")
                }
            }
        }
    }
    @MainActor func testZoomedUIKitCoordinatesKeepNormalizedPointsAndRejectLetterbox() {
        let scroll = UIScrollView(frame: CGRect(x: 0, y: 0, width: 320, height: 480))
        let image = UIImageView(frame: CGRect(x: 20, y: 40, width: 200, height: 100))
        let delegate = ZoomOracleDelegate(image: image)
        scroll.addSubview(image); scroll.contentSize = CGSize(width: 240, height: 180)
        scroll.minimumZoomScale = 1; scroll.maximumZoomScale = 100; scroll.delegate = delegate
        let expected = NormalizedPoint(x: 0.3, y: 0.7)!
        for zoom in [1.0, 2.0, 20.0, 100.0] {
            scroll.setZoomScale(zoom, animated: false)
            scroll.contentOffset = CGPoint(x: 15 * zoom, y: 10 * zoom)
            scroll.layoutIfNeeded()
            let marker = CGPoint(x: expected.x * image.bounds.width, y: expected.y * image.bounds.height)
            let screenPoint = image.convert(marker, to: scroll)
            let recovered = image.convert(screenPoint, from: scroll)
            var legacy = CGPoint.zero
            XCTAssertTrue(TCNormalizedPoint(recovered, image.bounds, &legacy))
            let portable = NormalizedPoint.inside(x: recovered.x, y: recovered.y, originX: image.bounds.minX,
                                                 originY: image.bounds.minY, width: image.bounds.width, height: image.bounds.height)
            XCTAssertEqual(portable?.x ?? -1, expected.x, accuracy: 0.000001)
            XCTAssertEqual(portable?.y ?? -1, expected.y, accuracy: 0.000001)
            XCTAssertEqual(portable?.x ?? -1, legacy.x, accuracy: 0.000001)
            XCTAssertEqual(portable?.y ?? -1, legacy.y, accuracy: 0.000001)
            for outside in [CGPoint(x: -1, y: 50), CGPoint(x: 200, y: 100), CGPoint(x: 50, y: -1)] {
                XCTAssertFalse(TCNormalizedPoint(outside, image.bounds, nil))
                XCTAssertNil(NormalizedPoint.inside(x: outside.x, y: outside.y, originX: 0, originY: 0,
                                                    width: image.bounds.width, height: image.bounds.height))
            }
        }
        XCTAssertEqual(ColorZoom.clamped(scroll.zoomScale), 100)
    }
    func testTransparentPartialAlphaAndWideGamutMatchActualUIKitSRGBSampling() throws {
        for space in [CGColorSpace(name: CGColorSpace.sRGB)!, CGColorSpace(name: CGColorSpace.displayP3)!] {
            let bytes: [UInt8] = [0,0,0,0, 128,0,0,128, 128,64,32,255]
            let cg = CGImage(width: 3, height: 1, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 12, space: space,
                             bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
                             provider: CGDataProvider(data: Data(bytes) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
            let data = NSMutableData()
            let destination = CGImageDestinationCreateWithData(data, UTType.tiff.identifier as CFString, 1, nil)!
            CGImageDestinationAddImage(destination, cg, nil); XCTAssertTrue(CGImageDestinationFinalize(destination))
            let portable = try ColorRaster.decode(data as Data)
            for scale in [1.0, 2.0, 3.0] {
                let legacy = UIImage(cgImage: cg, scale: scale, orientation: .up)
                for x in [0.1, 0.5, 0.9, 1.0] {
                    XCTAssertEqual(portable.sample(at: NormalizedPoint(x: x, y: 0.5)!)?.hex,
                                   TCSampleImage(legacy, CGPoint(x: x, y: 0.5)))
                }
            }
            XCTAssertEqual(portable.sample(at: NormalizedPoint(x: 0.1, y: 0.5)!)?.hex, "#ffffff")
            if space.name == CGColorSpace.displayP3 { XCTAssertNotEqual(portable.sample(at: NormalizedPoint(x: 0.9, y: 0.5)!)?.hex, "#804020") }
        }
    }
    func testNewAdapterAndLegacyStoreProduceEquivalentBackupsOrderAndDuplicates() {
        let firstSuite = "TouchColor.compare.legacy.\(UUID())", secondSuite = "TouchColor.compare.portable.\(UUID())"
        let first = UserDefaults(suiteName: firstSuite)!, second = UserDefaults(suiteName: secondSuite)!
        defer { first.removePersistentDomain(forName: firstSuite); second.removePersistentDomain(forName: secondSuite) }
        let malformed: [Any] = ["#FF0000", 27, "bad", "#abcdef", "#FF0000"]
        first.set(malformed, forKey: "colorArray"); second.set(malformed, forKey: "colorArray")
        let legacy = TCColorStore(defaults: first); let portable = LegacyPalette(defaults: second)
        XCTAssertEqual(legacy.colors, portable.colors.map(\.hex))
        XCTAssertTrue(legacy.addColor("#00FF00")); portable.append([ColorDomain.RGBColor(hex: "#00FF00")!])
        XCTAssertTrue(legacy.removeColor(at: 1)); XCTAssertTrue(portable.remove(at: 1))
        XCTAssertEqual(legacy.colors, portable.colors.map(\.hex))
        XCTAssertEqual(first.array(forKey: "colorArrayRecoveryBackup")! as NSArray, second.array(forKey: "colorArrayRecoveryBackup")! as NSArray)
        XCTAssertEqual(first.array(forKey: "colorArray")! as NSArray, second.array(forKey: "colorArray")! as NSArray)
    }
}

@MainActor private final class ZoomOracleDelegate: NSObject, UIScrollViewDelegate {
    let image: UIImageView
    init(image: UIImageView) { self.image = image }
    func viewForZooming(in scrollView: UIScrollView) -> UIView? { image }
}
