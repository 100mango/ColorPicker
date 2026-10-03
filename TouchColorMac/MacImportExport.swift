import AppKit
import UniformTypeIdentifiers
import ColorPaletteLegacy
import ColorRaster

@MainActor enum MacImportExport {
    static func open(session: ImageSession, library: PaletteLibrary) {
        let token = session.beginImport()
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image, .json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = NSLocalizedString("Open an image to sample, or a JSON palette to append.", comment: "File operation")
        guard panel.runModal() == .OK, let url = panel.url else {
            if session.isCurrent(token) { session.cancelImport() }
            return
        }
        importURL(url, session: session, library: library, token: token)
    }
    static func importURL(_ url: URL, session: ImageSession, library: PaletteLibrary, token: UInt64? = nil) {
        let current = token ?? session.beginImport()
        if url.pathExtension.lowercased() == "json" {
            session.loadPalette(url, token: current, library: library)
        } else { session.load(url: url, token: current) }
    }
    static func paste(session: ImageSession, library: PaletteLibrary) {
        let token = session.beginImport()
        if let urls = NSPasteboard.general.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL], let url = urls.first {
            importURL(url, session: session, library: library, token: token); return
        }
        for type in [NSPasteboard.PasteboardType.png, .tiff] {
            if let data = NSPasteboard.general.data(forType: type) {
                session.load(data: data, name: NSLocalizedString("Pasted image", comment: "File operation"), token: token); return
            }
        }
        session.cancelImport()
        session.errorMessage = NSLocalizedString("The clipboard does not contain an image or an image file.", comment: "File operation")
    }
    static func drop(_ providers: [NSItemProvider], session: ImageSession, library: PaletteLibrary) -> Bool {
        guard let provider = providers.first else { return false }
        let token = session.beginImport()
        if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, error in
                let url = (item as? URL) ?? (item as? Data).flatMap { URL(dataRepresentation: $0, relativeTo: nil) }
                Task { @MainActor in
                    guard session.isCurrent(token) else { return }
                    if let url, url.isFileURL { importURL(url, session: session, library: library, token: token) }
                    else { session.report(error ?? CocoaError(.fileReadUnknown), token: token) }
                }
            }
            return true
        }
        if let type = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .image) == true }) {
            let cancelled = session.cancellationCheck(for: token)
            provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
                let result = Result { () throws -> URL in
                    guard let url else { throw error ?? RasterError.unreadable }
                    return try NativePhotoFile.copyBounded(url, cancelled: cancelled)
                }
                Task { @MainActor in
                    switch result {
                    case .success(let file): session.loadOwnedFile(file, name: NSLocalizedString("Dropped image", comment: "File operation"), token: token)
                    case .failure(let error): session.report(error, token: token)
                    }
                }
            }
            return true
        }
        session.report(CocoaError(.fileReadUnsupportedScheme), token: token)
        return false
    }
    static func exportPalette(library: PaletteLibrary, session: ImageSession) {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = NSLocalizedString("TouchColor Palette.json", comment: "File operation")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try PaletteFile.encode(library.colors).write(to: url, options: .atomic)
            session.notice = String(format: NSLocalizedString("Exported %ld colors.", comment: "Palette export"), library.colors.count)
        } catch { session.errorMessage = error.localizedDescription }
    }
    static func exportImage(session: ImageSession) {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.png]
        panel.nameFieldStringValue = NSLocalizedString("TouchColor Image.png", comment: "File operation")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        session.exportPNG(to: url)
    }
}
