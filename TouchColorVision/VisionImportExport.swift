import SwiftUI
import UniformTypeIdentifiers
import CoreTransferable
import ColorRaster
import ColorPaletteLegacy

struct ColorExportDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.png, .json] }
    let data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadCorruptFile) }
        self.data = data
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

@MainActor enum VisionImport {
    static func file(_ url: URL, session: ImageSession, library: PaletteLibrary) {
        let token = session.beginImport()
        if url.pathExtension.lowercased() == "json" {
            // Scoped access must remain alive for the complete asynchronous read.
            Task.detached(priority: .userInitiated) {
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                let result = Result { () throws -> Data in
                    guard (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) <= 16 * 1024 * 1024 else { throw PaletteFileError.invalid }
                    return try Data(contentsOf: url)
                }
                await MainActor.run {
                    switch result {
                    case .success(let data): session.finishPaletteImport(data, token: token, library: library)
                    case .failure(let error): session.report(error, token: token)
                    }
                }
            }
        } else { session.load(url: url, token: token) }
    }
    static func providers(_ providers: [NSItemProvider], session: ImageSession) -> Bool {
        guard let provider = providers.first,
              let type = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .image) == true }) else { return false }
        let token = session.beginImport()
        let cancelled = session.cancellationCheck(for: token)
        provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
            // The provider URL is valid only inside its callback. Copy in fixed-size
            // chunks before returning, then let the serial decoder own/remove the file.
            let result = Result { () throws -> URL in
                guard let url else { throw error ?? RasterError.unreadable }
                return try VisionPhotoFile.copyBounded(url, cancelled: cancelled)
            }
            Task { @MainActor in
                switch result {
                case .success(let file): session.loadOwnedFile(file, name: NSLocalizedString("Pasted image", comment: "Source name"), token: token)
                case .failure(let error): session.report(error, token: token)
                }
            }
        }
        return true
    }
}

/// File transfer avoids materializing an arbitrary provider item in app memory before
/// checking its size. The original bytes, alpha and EXIF orientation are copied unchanged.
struct VisionPhotoFile: Transferable {
    let url: URL
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            VisionPhotoFile(url: try copyBounded(received.file, cancelled: { Task.isCancelled }))
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
