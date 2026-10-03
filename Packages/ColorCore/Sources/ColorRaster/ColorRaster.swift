import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import ColorDomain

public enum RasterError: LocalizedError {
    case unreadable, tooLarge, cancelled, exportFailed
    public var errorDescription: String? {
        switch self {
        case .unreadable: return NSLocalizedString("This image could not be opened. Choose a readable image file.", comment: "Image operation error")
        case .tooLarge: return NSLocalizedString("This image exceeds the 100-megapixel or 128 MB safety limit. The original was not changed or reduced.", comment: "Image operation error")
        case .cancelled: return NSLocalizedString("Import cancelled.", comment: "Image operation error")
        case .exportFailed: return NSLocalizedString("The image could not be exported. The original was not changed.", comment: "Image operation error")
        }
    }
    public static func fileReadError(_ error: Error) -> Error {
        guard let bounded = error as? BoundedFileReadError else { return error }
        switch bounded {
        case .tooLarge: return RasterError.tooLarge
        case .cancelled: return RasterError.cancelled
        case .changedDuringRead: return RasterError.unreadable
        }
    }
}

/// Full-size orientation-normalized source, never a reduced display-preview sampling source.
/// The original encoded bytes stay available for a lossless original-file export if needed.
// CGImage and Data are immutable snapshots; every sample/encode allocates a private context.
// No mutable bitmap pointer or ImageIO source escapes decode.
public struct ColorRaster: @unchecked Sendable {
    public static let maximumEncodedBytes = 128 * 1024 * 1024
    public static let maximumPixels = 100_000_000
    public let image: CGImage
    public let sourceData: Data
    public let sourceOrientation: UInt32
    public var width: Int { image.width }
    public var height: Int { image.height }

    public static func read(url: URL, cancelled: () -> Bool = { false }) throws -> ColorRaster {
        do { return try decode(BoundedFileReader.read(url, maximumBytes: maximumEncodedBytes, cancelled: cancelled), cancelled: cancelled) }
        catch { throw RasterError.fileReadError(error) }
    }

    public static func decode(_ data: Data, cancelled: () -> Bool = { false }) throws -> ColorRaster {
        guard data.count <= maximumEncodedBytes else { throw RasterError.tooLarge }
        if cancelled() { throw RasterError.cancelled }
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              width > 0, height > 0 else { throw RasterError.unreadable }
        guard width <= maximumPixels / height else { throw RasterError.tooLarge }
        let orientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
        guard (1...8).contains(orientation) else { throw RasterError.unreadable }
        // ImageIO applies all eight EXIF transforms. This ceiling is the ORIGINAL largest
        // dimension, not a display size. Check dimensions below; no silent downsampling.
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(width, height),
            kCGImageSourceShouldCacheImmediately: true
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { throw RasterError.unreadable }
        if cancelled() { throw RasterError.cancelled }
        let rotated = orientation >= 5
        guard image.width == (rotated ? height : width), image.height == (rotated ? width : height) else { throw RasterError.unreadable }
        return ColorRaster(image: image, sourceData: data, sourceOrientation: orientation)
    }

    /// Explicit sRGB conversion, no interpolation, premultiplied alpha composited over white.
    /// CGImage cropping uses top-left raster coordinates, independent of AppKit's view system.
    public func sample(at point: NormalizedPoint) -> RGBColor? { RasterPixelSampler.sample(image: image, at: point) }

    /// PNG preserves full oriented pixel dimensions and alpha; reopening uses the same policy.
    public func pngData() throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { throw RasterError.exportFailed }
        CGImageDestinationAddImage(destination, image, [kCGImagePropertyOrientation: 1] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw RasterError.exportFailed }
        return data as Data
    }
}

/// Shared exact sRGB/white-composite pixel policy for source and explicitly reduced previews.
public enum RasterPixelSampler {
    public static func sample(image: CGImage, at point: NormalizedPoint) -> RGBColor? {
        guard let pixel = point.pixel(width: image.width, height: image.height),
              let crop = image.cropping(to: CGRect(x: pixel.x, y: pixel.y, width: 1, height: 1)),
              let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        var bytes: [UInt8] = [255, 255, 255, 255]
        return bytes.withUnsafeMutableBytes { storage in
            guard let context = CGContext(data: storage.baseAddress, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
                                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return nil }
            context.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: 1, height: 1))
            context.interpolationQuality = .none
            context.draw(crop, in: CGRect(x: 0, y: 0, width: 1, height: 1))
            return RGBColor(red: storage[0], green: storage[1], blue: storage[2])
        }
    }

}
