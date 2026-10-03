import Foundation
import CoreTransferable
import UniformTypeIdentifiers
import ColorRaster

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
        if cancelled() { throw RasterError.cancelled }
        let size = try source.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= maximumBytes else { throw RasterError.tooLarge }
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-import-\(UUID()).image")
        guard FileManager.default.createFile(atPath: destination.path, contents: nil) else { throw RasterError.unreadable }
        var completed = false
        defer { if !completed { try? FileManager.default.removeItem(at: destination) } }
        let input = try FileHandle(forReadingFrom: source)
        defer { try? input.close() }
        let output = try FileHandle(forWritingTo: destination)
        defer { try? output.close() }
        var count = 0
        while true {
            if cancelled() { throw RasterError.cancelled }
            guard let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty else { break }
            guard count <= maximumBytes - chunk.count else { throw RasterError.tooLarge }
            try output.write(contentsOf: chunk); count += chunk.count
        }
        if cancelled() { throw RasterError.cancelled }
        completed = true
        return destination
    }
}
