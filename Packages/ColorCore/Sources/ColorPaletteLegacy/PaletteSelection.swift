import Foundation
import ColorDomain

public enum PaletteSelectionError: LocalizedError {
    case tooLarge, cancelled
    public var errorDescription: String? {
        switch self {
        case .tooLarge: return NSLocalizedString("Choose a JSON palette no larger than 1 MB. Existing colors were kept.", comment: "Palette selection limit")
        case .cancelled: return NSLocalizedString("Palette selection cancelled.", comment: "Palette selection status")
        }
    }
}

/// A complete, immutable review selection. Decoding never mutates any stored palette.
public struct PaletteSelection: Equatable {
    public static let maximumBytes = 1_048_576
    public let colors: [RGBColor]
    public init(data: Data) throws {
        guard data.count <= Self.maximumBytes else { throw PaletteSelectionError.tooLarge }
        colors = try PaletteFile.decode(data)
    }
    public static func read(_ url: URL, cancelled: @escaping () -> Bool = { false }) throws -> PaletteSelection {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        var coordinated: Result<PaletteSelection, Error>?
        var coordinationError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [], error: &coordinationError) { readable in
            coordinated = Result { try readCoordinated(readable, cancelled: cancelled) }
        }
        if let coordinationError { throw coordinationError }
        guard let coordinated else { throw PaletteFileError.invalid }
        return try coordinated.get()
    }
    private static func readCoordinated(_ url: URL, cancelled: () -> Bool) throws -> PaletteSelection {
        do { return try PaletteSelection(data: BoundedFileReader.read(url, maximumBytes: maximumBytes, cancelled: cancelled)) }
        catch BoundedFileReadError.tooLarge { throw PaletteSelectionError.tooLarge }
        catch BoundedFileReadError.cancelled { throw PaletteSelectionError.cancelled }
        catch BoundedFileReadError.changedDuringRead { throw PaletteFileError.invalid }
    }
}
