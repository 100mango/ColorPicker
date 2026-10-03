import SwiftUI
import UniformTypeIdentifiers
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
        provider.loadDataRepresentation(forTypeIdentifier: type) { data, error in
            Task { @MainActor in
                guard session.isCurrent(token) else { return }
                if let data { session.load(data: data, name: NSLocalizedString("Pasted image", comment: "Source name"), token: token) }
                else { session.report(error ?? CocoaError(.fileReadUnknown), token: token) }
            }
        }
        return true
    }
}
