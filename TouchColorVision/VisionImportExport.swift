import SwiftUI
import UniformTypeIdentifiers
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
            session.loadPalette(url, token: token, library: library)
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
                return try NativePhotoFile.copyBounded(url, cancelled: cancelled)
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
