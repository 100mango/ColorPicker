import Foundation

/// Explicit selected-palette message, never a replica of the phone's whole store.
/// A recipient reviews the complete message before appending; order/duplicates are meaningful.
public struct PaletteTransfer: Equatable, Sendable {
    public static let maximumColors = 64
    public static let maximumBytes = 8 * 1024
    public let id: UUID
    public let colors: [RGBColor]
    public init(id: UUID = UUID(), colors: [RGBColor]) throws {
        guard (1...Self.maximumColors).contains(colors.count) else { throw PaletteTransferError.invalid }
        self.id = id; self.colors = colors
    }
    private struct Payload: Codable { let version: Int; let id: UUID; let colors: [String] }
    public func encoded() throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(Payload(version: 1, id: id, colors: colors.map(\.hex)))
        guard data.count <= Self.maximumBytes else { throw PaletteTransferError.invalid }
        return data
    }
    public static func decode(_ data: Data) throws -> Self {
        guard data.count <= maximumBytes,
              let payload = try? JSONDecoder().decode(Payload.self, from: data), payload.version == 1 else { throw PaletteTransferError.invalid }
        let colors = payload.colors.compactMap(RGBColor.init(hex:))
        guard colors.count == payload.colors.count else { throw PaletteTransferError.invalid }
        return try Self(id: payload.id, colors: colors)
    }
}
public enum PaletteTransferError: Error { case invalid }
