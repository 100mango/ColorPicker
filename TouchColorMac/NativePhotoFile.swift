import Foundation
import CoreTransferable
import UniformTypeIdentifiers
import ColorRaster
import ColorDomain

/// File transfer avoids materializing an arbitrary provider item in app memory before
/// checking its size. The original bytes, alpha and EXIF orientation are copied unchanged.
struct NativePhotoFile: Transferable {
    let url: URL
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            NativePhotoFile(url: try copyBounded(received.file, cancelled: { Task.isCancelled }))
        }
    }
    static func copyBounded(_ source: URL, maximumBytes: Int = ColorRaster.maximumEncodedBytes,
                            cancelled: () -> Bool = { false }) throws -> URL {
        do { return try BoundedFileReader.copyToTemporaryFile(source, maximumBytes: maximumBytes, cancelled: cancelled) }
        catch { throw RasterError.fileReadError(error) }
    }
}
