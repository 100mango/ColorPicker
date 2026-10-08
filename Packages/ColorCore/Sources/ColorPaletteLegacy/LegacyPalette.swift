import Foundation
import ColorDomain

/// Adapter for the existing on-device defaults contract. No sync, sorting, deduplication or cap.
public final class LegacyPalette {
    public static let key = "colorArray"
    public static let recoveryKey = "colorArrayRecoveryBackup"
    private let defaults: UserDefaults
    private let lock = NSRecursiveLock()

    public init(defaults: UserDefaults) { self.defaults = defaults }

    public var colors: [RGBColor] {
        lock.lock(); defer { lock.unlock() }
        return (defaults.object(forKey: Self.key) as? [Any] ?? []).compactMap {
            ($0 as? String).flatMap(RGBColor.init(hex:))
        }
    }

    public func append(_ additions: [RGBColor]) {
        guard !additions.isEmpty else { return }
        lock.lock(); defer { lock.unlock() }
        write(colors + additions)
    }

    @discardableResult public func remove(at index: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }
        var values = colors
        guard values.indices.contains(index) else { return false }
        values.remove(at: index)
        write(values)
        return true
    }

    private func write(_ values: [RGBColor]) {
        let original = defaults.object(forKey: Self.key)
        let normalized = colors.map(\.hex)
        // Uppercase and malformed originals are backed up once, before any repair write.
        if let original, !(original as? NSObject ?? NSObject()).isEqual(normalized),
           defaults.object(forKey: Self.recoveryKey) == nil {
            defaults.set(original, forKey: Self.recoveryKey)
        }
        defaults.set(values.map(\.hex), forKey: Self.key)
    }
}

public enum PaletteFileError: LocalizedError {
    case invalid
    public var errorDescription: String? {
        NSLocalizedString("The palette must contain only #rrggbb colors. Nothing was imported.", comment: "Palette import error")
    }
}

public enum PaletteFile {
    public static let maximumFileBytes = 16 * 1024 * 1024
    public static func read(_ url: URL, cancelled: @escaping () -> Bool = { false }) throws -> [RGBColor] {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        var result: Result<[RGBColor], Error>?
        var coordinationError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [], error: &coordinationError) { readable in
            result = Result {
                do { return try decode(BoundedFileReader.read(readable, maximumBytes: maximumFileBytes, cancelled: cancelled)) }
                catch BoundedFileReadError.cancelled { throw PaletteSelectionError.cancelled }
                catch is BoundedFileReadError { throw PaletteFileError.invalid }
            }
        }
        if let coordinationError { throw coordinationError }
        guard let result else { throw PaletteFileError.invalid }
        return try result.get()
    }
    public static func encode(_ colors: [RGBColor]) throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        return try encoder.encode(colors.map(\.hex))
    }
    public static func decode(_ data: Data) throws -> [RGBColor] {
        // All-or-nothing import: malformed files never silently discard entries.
        guard let strings = try? JSONDecoder().decode([String].self, from: data) else { throw PaletteFileError.invalid }
        let colors = strings.compactMap(RGBColor.init(hex:))
        guard colors.count == strings.count else { throw PaletteFileError.invalid }
        return colors
    }
}
