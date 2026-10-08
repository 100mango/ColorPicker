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

public struct PaletteTransferReceipt: Codable, Equatable, Sendable {
    public enum Outcome: String, Codable, Sendable { case accepted, rejected }
    public let version: Int
    public let requestID: UUID
    public let fingerprint: String
    public let outcome: Outcome
    public init(requestID: UUID, fingerprint: String, outcome: Outcome) {
        version = 1; self.requestID = requestID; self.fingerprint = fingerprint; self.outcome = outcome
    }
    public func encoded() throws -> Data { try JSONEncoder().encode(self) }
    public static func decode(_ data: Data) throws -> Self {
        guard data.count <= 1024, let result = try? JSONDecoder().decode(Self.self, from: data), result.version == 1,
              result.fingerprint.utf8.count == 64,
              result.fingerprint.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { throw PaletteTransferError.invalid }
        return result
    }
}
