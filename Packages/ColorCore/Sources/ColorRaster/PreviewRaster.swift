import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import ColorDomain

/// Watch-only policy: a labeled, bounded preview, separate from full-fidelity ColorRaster.
/// Original encoded data is not retained in watch memory or written to its palette defaults.
public struct PreviewRaster: @unchecked Sendable {
    public static let maximumDimension = 512
    public static let maximumEncodedBytes = 32 * 1024 * 1024
    public static let maximumSourcePixels = 16_000_000
    public let image: CGImage
    public let originalWidth: Int
    public let originalHeight: Int
    public var width: Int { image.width }
    public var height: Int { image.height }
    public var isReduced: Bool { width != originalWidth || height != originalHeight }
    public static func read(url: URL, cancelled: () -> Bool = { false }) throws -> Self {
        do { return try decode(BoundedFileReader.read(url, maximumBytes: maximumEncodedBytes, cancelled: cancelled), cancelled: cancelled) }
        catch { throw RasterError.fileReadError(error) }
    }
    public static func decode(_ data: Data, cancelled: () -> Bool = { false }) throws -> Self {
        guard data.count <= maximumEncodedBytes else { throw RasterError.tooLarge }
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary) else { throw RasterError.unreadable }
        return try decode(source, cancelled: cancelled)
    }
    private static func decode(_ source: CGImageSource, cancelled: () -> Bool) throws -> Self {
        if cancelled() { throw RasterError.cancelled }
        guard let p = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = (p[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let h = (p[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue, w > 0, h > 0 else { throw RasterError.unreadable }
        guard w <= maximumSourcePixels / h else { throw RasterError.tooLarge }
        let orientation = (p[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        guard (1...8).contains(orientation) else { throw RasterError.unreadable }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true, kCGImageSourceThumbnailMaxPixelSize: maximumDimension,
            kCGImageSourceShouldCacheImmediately: true]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
              image.width <= maximumDimension, image.height <= maximumDimension else { throw RasterError.unreadable }
        if cancelled() { throw RasterError.cancelled }
        return Self(image: image, originalWidth: orientation >= 5 ? h : w, originalHeight: orientation >= 5 ? w : h)
    }
    public func sample(at point: NormalizedPoint) -> RGBColor? { RasterPixelSampler.sample(image: image, at: point) }
    public func pngData() throws -> Data {
        let data = NSMutableData()
        guard let output = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { throw RasterError.exportFailed }
        CGImageDestinationAddImage(output, image, nil)
        guard CGImageDestinationFinalize(output), data.length <= 2 * 1024 * 1024 else { throw RasterError.exportFailed }
        return data as Data
    }
}
