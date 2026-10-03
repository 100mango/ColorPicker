import Foundation
import CryptoKit
import ColorDomain

public enum PaletteInboxError: Error { case corruptStore, full, conflictingID, missing }
public enum PaletteFingerprint {
    public static func of(_ transfer: PaletteTransfer) throws -> String {
        SHA256.hash(data: try transfer.encoded()).map { String(format: "%02x", $0) }.joined()
    }
}

/// Phone-only inbox semantics. Receive stages complete immutable messages. Explicit
/// acceptance writes colors, recovery backup, receipt and inbox in one persistent-domain
/// replacement, preserving every unrelated preference and the legacy palette contract.
/// The app serializes this adapter with its existing palette UI on the main actor.
public final class PaletteInbox {
    public static let pendingKey = "colorInboxPendingV1"
    public static let receiptsKey = "colorInboxAcceptedV1"
    public static let maximumPending = 16
    public static let maximumReceipts = 4096
    private let defaults: UserDefaults
    private let domain: String
    private let lock = NSRecursiveLock()
    public init(defaults: UserDefaults, domain: String) { self.defaults = defaults; self.domain = domain }
    private func entries(_ values: [String: Any]) throws -> [PaletteTransfer] {
        guard let raw = values[Self.pendingKey] else { return [] }
        guard let data = raw as? [Data], data.count <= Self.maximumPending else { throw PaletteInboxError.corruptStore }
        let result = try data.map(PaletteTransfer.decode)
        guard Set(result.map(\.id)).count == result.count else { throw PaletteInboxError.corruptStore }
        return result
    }
    private func receipts(_ values: [String: Any]) throws -> [String: String] {
        guard let raw = values[Self.receiptsKey] else { return [:] }
        guard let result = raw as? [String: String], result.count <= Self.maximumReceipts,
              result.allSatisfy({ UUID(uuidString: $0.key)?.uuidString == $0.key && $0.value.utf8.count == 64 && $0.value.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) }) else { throw PaletteInboxError.corruptStore }
        return result
    }
    public func pending() throws -> [PaletteTransfer] {
        lock.lock(); defer { lock.unlock() }
        return try entries(defaults.persistentDomain(forName: domain) ?? [:])
    }
    /// An accepted duplicate returns its prior receipt. Pending duplicates are retained once.
    public func receive(_ data: Data) throws -> PaletteTransferReceipt? {
        let message = try PaletteTransfer.decode(data), digest = try PaletteFingerprint.of(message)
        lock.lock(); defer { lock.unlock() }
        var values = defaults.persistentDomain(forName: domain) ?? [:]
        var pending = try entries(values)
        let accepted = try receipts(values)
        if let existing = accepted[message.id.uuidString] {
            guard existing == digest else { throw PaletteInboxError.conflictingID }
            return PaletteTransferReceipt(requestID: message.id, fingerprint: digest, outcome: .accepted)
        }
        if let existing = pending.first(where: { $0.id == message.id }) {
            guard existing == message else { throw PaletteInboxError.conflictingID }
            return nil
        }
        guard pending.count < Self.maximumPending, accepted.count < Self.maximumReceipts else { throw PaletteInboxError.full }
        pending.append(message)
        values[Self.pendingKey] = try pending.map { try $0.encoded() }
        defaults.setPersistentDomain(values, forName: domain)
        return nil
    }
    public func accept(_ id: UUID) throws -> PaletteTransferReceipt {
        lock.lock(); defer { lock.unlock() }
        var values = defaults.persistentDomain(forName: domain) ?? [:]
        var pending = try entries(values), accepted = try receipts(values)
        if let digest = accepted[id.uuidString] { return PaletteTransferReceipt(requestID: id, fingerprint: digest, outcome: .accepted) }
        guard let index = pending.firstIndex(where: { $0.id == id }) else { throw PaletteInboxError.missing }
        guard accepted.count < Self.maximumReceipts else { throw PaletteInboxError.full }
        let message = pending.remove(at: index), digest = try PaletteFingerprint.of(message)
        let original = values[LegacyPalette.key]
        let colors = (original as? [Any] ?? []).compactMap { ($0 as? String).flatMap(RGBColor.init(hex:)) }
        if let original, !(original as? NSObject ?? NSObject()).isEqual(colors.map(\.hex)), values[LegacyPalette.recoveryKey] == nil {
            values[LegacyPalette.recoveryKey] = original
        }
        values[LegacyPalette.key] = (colors + message.colors).map(\.hex)
        accepted[id.uuidString] = digest
        values[Self.receiptsKey] = accepted
        values[Self.pendingKey] = try pending.map { try $0.encoded() }
        defaults.setPersistentDomain(values, forName: domain)
        return PaletteTransferReceipt(requestID: id, fingerprint: digest, outcome: .accepted)
    }
    public func reject(_ id: UUID) throws -> PaletteTransferReceipt {
        lock.lock(); defer { lock.unlock() }
        var values = defaults.persistentDomain(forName: domain) ?? [:]
        var pending = try entries(values)
        guard let index = pending.firstIndex(where: { $0.id == id }) else { throw PaletteInboxError.missing }
        let message = pending.remove(at: index)
        values[Self.pendingKey] = try pending.map { try $0.encoded() }
        defaults.setPersistentDomain(values, forName: domain)
        return PaletteTransferReceipt(requestID: id, fingerprint: try PaletteFingerprint.of(message), outcome: .rejected)
    }
}
