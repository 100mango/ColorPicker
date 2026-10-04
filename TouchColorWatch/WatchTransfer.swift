import Foundation
import Combine
import WatchConnectivity
import ColorDomain
import ColorPaletteLegacy

/// A small adapter seam for verifying cancellation of persisted platform queues.
@MainActor protocol WatchQueuedPaletteRequest: AnyObject {
    var userInfo: [String: Any] { get }
    func cancel()
}
extension WCSessionUserInfoTransfer: WatchQueuedPaletteRequest {}

private struct WatchCancellationState: Codable {
    static let maximumIDs = 4096
    static let maximumBytes = 256 * 1024
    var version = 1
    var requestIDs: [UUID] = []
    var lastCancelledID: UUID?
    static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.version == 1, value.requestIDs.count <= maximumIDs,
              Set(value.requestIDs).count == value.requestIDs.count,
              value.lastCancelledID.map({ value.requestIDs.contains($0) }) ?? true else { throw PaletteTransferError.invalid }
        return value
    }
}
private enum WatchTransferStorageError: LocalizedError {
    case cancellationHistoryFull
    case pendingChanged
    var errorDescription: String? {
        switch self {
        case .cancellationHistoryFull:
            return NSLocalizedString("The cancellation history is full. The pending transfer was kept.", comment: "Watch transfer error")
        case .pendingChanged:
            return NSLocalizedString("The pending transfer file needs recovery before another transfer.", comment: "Watch transfer error")
        }
    }
}

/// Only an explicit Send creates a queued message. Pending payload survives relaunch;
/// retry keeps its UUID so the phone inbox can reject duplicate delivery.
@MainActor final class WatchTransfer: NSObject, ObservableObject, WCSessionDelegate {
    @Published private(set) var status = NSLocalizedString("Select Send to iPhone to request a transfer.", comment: "Watch transfer status")
    @Published private(set) var sending = false
    @Published private(set) var pending: PaletteTransfer?
    @Published private(set) var lastReceipt: PaletteTransferReceipt?
#if DEBUG
    private(set) var pairedReceiptChannel: String?
    @Published private(set) var pairedReadinessValue = ""
    private var pairedActivationErrorDomain = ""
    private var pairedActivationErrorCode = ""
    private var pairedActivationCallbackState = ""
    private var pairedSelectedTransport = "none"
    private var pairedReadinessSequence = 0
    // Observations only: never activate, send, retry, or override a production guard.
    private func recordPairedReadiness(_ event: String, transport: String? = nil) {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else { return }
        if let transport { pairedSelectedTransport = transport }
        pairedReadinessSequence = min(pairedReadinessSequence + 1, 1_000_000)
        let active = session?.activationState == .activated
        let value: [String: String] = [
            "schema": "1", "role": "watch", "source": "public-WCSession", "event": event,
            "sequence": String(pairedReadinessSequence), "supported": WCSession.isSupported() ? "true" : "false",
            "sessionPresent": session == nil ? "false" : "true",
            "activationState": session.map { String($0.activationState.rawValue) } ?? "absent",
            "activationCallbackState": pairedActivationCallbackState,
            "activationErrorDomain": pairedActivationErrorDomain, "activationErrorCode": pairedActivationErrorCode,
            // Most WCSession properties are undefined until successful activation.
            "companionInstalled": active ? (session!.isCompanionAppInstalled ? "true" : "false") : "unknown",
            "reachable": active ? (session!.isReachable ? "true" : "false") : "unknown",
            "selectedTransport": pairedSelectedTransport
        ]
        pairedReadinessValue = (try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys))
            .map { String(decoding: $0, as: UTF8.self) } ?? ""
    }
    var pairedReceiptValue: String {
        var value = ["connection": pairedReadinessValue]
        if let receipt = lastReceipt {
            value.merge(["requestID": receipt.requestID.uuidString, "requestProtocol": "touchColorPaletteV1", "receiptProtocol": "touchColorReceiptV1", "version": String(receipt.version), "fingerprint": receipt.fingerprint, "outcome": receipt.outcome.rawValue, "receiveChannel": pairedReceiptChannel ?? "persisted"]) { _, new in new }
        }
        return (try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys)).map { String(decoding: $0, as: UTF8.self) } ?? ""
    }
#endif
    private let file: URL
    private let receiptFile: URL
    private let cancellationFile: URL
    private var cancellations = WatchCancellationState()
    private var storageNeedsRecovery = false
    private var activeTransfer: WCSessionUserInfoTransfer?
    private var session: WCSession?
    private let queuedRequestsOverride: (() -> [WatchQueuedPaletteRequest])?
    init(directory: URL? = nil, activate: Bool = true,
         queuedRequests: (() -> [WatchQueuedPaletteRequest])? = nil) {
        let folder = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        file = folder.appendingPathComponent("pending-color-transfer.json")
        receiptFile = folder.appendingPathComponent("last-color-transfer-receipt.json")
        cancellationFile = folder.appendingPathComponent("cancelled-color-transfers.json")
        queuedRequestsOverride = queuedRequests
        super.init()
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: cancellationFile.path) {
                cancellations = try WatchCancellationState.decode(BoundedFileReader.read(cancellationFile, maximumBytes: WatchCancellationState.maximumBytes))
            }
            if FileManager.default.fileExists(atPath: file.path) {
                pending = try PaletteTransfer.decode(BoundedFileReader.read(file, maximumBytes: PaletteTransfer.maximumBytes))
                status = NSLocalizedString("A transfer is pending. Open TouchColor on iPhone, then choose Retry.", comment: "Watch transfer status")
            }
            if let pending, cancellations.requestIDs.contains(pending.id) {
                // Recover a crash after the cancellation was persisted but before
                // its pending payload could be removed. Never resend this UUID.
                try FileManager.default.removeItem(at: file)
                self.pending = nil
            }
            if FileManager.default.fileExists(atPath: receiptFile.path) {
                let receipt = try PaletteTransferReceipt.decode(BoundedFileReader.read(receiptFile, maximumBytes: 1024))
                lastReceipt = receipt
                if pending == nil && cancellations.lastCancelledID == nil {
                    status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
                }
                if let pending, !cancellations.requestIDs.contains(pending.id), receipt.requestID == pending.id, receipt.fingerprint == (try PaletteFingerprint.of(pending)) {
                    try clearLastCancellationStatus()
                    if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
                    self.pending = nil
                    status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
                }
            }
            if pending == nil && cancellations.lastCancelledID != nil { status = cancelledStatus }
        } catch { storageNeedsRecovery = true; status = NSLocalizedString("The pending transfer could not be read. Its file was kept.", comment: "Watch transfer error") }
        if activate && WCSession.isSupported() { session = .default; session?.delegate = self; session?.activate() }
#if DEBUG
        recordPairedReadiness(session == nil ? "initialized" : "activate-called")
#endif
    }
    func request(_ colors: [RGBColor]) {
        guard !storageNeedsRecovery else { status = NSLocalizedString("The pending transfer file needs recovery before another transfer.", comment: "Watch transfer error"); return }
        guard pending == nil else { status = NSLocalizedString("Finish or cancel the pending transfer first.", comment: "Watch transfer status"); return }
        // Never replace a malformed pending file whose contents may need recovery.
        guard !FileManager.default.fileExists(atPath: file.path) else { status = NSLocalizedString("The pending transfer file needs recovery before another transfer.", comment: "Watch transfer error"); return }
        do {
            let request = try PaletteTransfer(colors: colors)
            try request.encoded().write(to: file, options: .atomic)
            pending = request; retry()
        } catch { status = NSLocalizedString("The transfer could not be saved. Your palette is unchanged.", comment: "Watch transfer error") }
    }
    func retry() {
#if DEBUG
        recordPairedReadiness("retry")
#endif
        guard !storageNeedsRecovery, let pending, !sending, !cancellations.requestIDs.contains(pending.id) else { return }
        guard let session, session.activationState == .activated, session.isCompanionAppInstalled else {
            status = NSLocalizedString("Waiting for TouchColor on the paired iPhone. Choose Retry when it is available.", comment: "Watch transfer status"); return
        }
        if session.isReachable, let data = try? pending.encoded() {
            sending = true
            let id = pending.id
#if DEBUG
            recordPairedReadiness("sendMessage", transport: "sendMessage")
#endif
            session.sendMessage(["touchColorPaletteV1": data, "requestID": id.uuidString], replyHandler: { [weak self] reply in
                Task { @MainActor in
                    guard let self, self.isActiveRequest(id) else { return }
                    self.sending = false
                    self.status = reply["received"] as? Bool == true
                        ? NSLocalizedString("Received on iPhone. Open Watch Inbox there to review.", comment: "Foreground transfer status")
                        : NSLocalizedString("The phone could not stage this transfer. The request was kept for retry.", comment: "Foreground transfer status")
                }
            }, errorHandler: { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.isActiveRequest(id) else { return }
                    self.sending = false
                    self.status = NSLocalizedString("Transfer not delivered yet. Keep both apps open and choose Retry.", comment: "Foreground transfer status")
                }
            })
            status = NSLocalizedString("Sending selected colors to iPhone…", comment: "Foreground transfer status")
            return
        }
        if let existing = session.outstandingUserInfoTransfers.first(where: { ($0.userInfo["requestID"] as? String) == pending.id.uuidString }) {
            activeTransfer = existing
        } else if let data = try? pending.encoded() {
#if DEBUG
            recordPairedReadiness("transferUserInfo", transport: "transferUserInfo")
#endif
            activeTransfer = session.transferUserInfo(["touchColorPaletteV1": data, "requestID": pending.id.uuidString])
        }
        status = NSLocalizedString("Queued for iPhone. This has not changed the phone palette.", comment: "Watch transfer status")
    }
    func cancel() {
        sending = false
        guard !storageNeedsRecovery, let pending else { return }
        do {
            try compactSettledCancellationsIfNeeded()
            var next = cancellations
            if !next.requestIDs.contains(pending.id) {
                guard next.requestIDs.count < WatchCancellationState.maximumIDs else { throw WatchTransferStorageError.cancellationHistoryFull }
                next.requestIDs.append(pending.id)
            }
            next.lastCancelledID = pending.id
            // Tombstone first; a late receipt or crash cannot resurrect a removed request.
            try persistCancellations(next)
            cancelQueuedRequests(for: pending.id)
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
            self.pending = nil; status = cancelledStatus
        } catch { status = error.localizedDescription }
    }
    private var cancelledStatus: String {
        NSLocalizedString("Transfer cancelled. If it already arrived, review it on iPhone.", comment: "Watch transfer status")
    }
    private func persistCancellations(_ value: WatchCancellationState) throws {
        let data = try JSONEncoder().encode(value)
        guard data.count <= WatchCancellationState.maximumBytes else { throw WatchTransferStorageError.cancellationHistoryFull }
        try data.write(to: cancellationFile, options: .atomic)
        cancellations = value
    }
    private func clearLastCancellationStatus() throws {
        guard cancellations.lastCancelledID != nil else { return }
        var next = cancellations; next.lastCancelledID = nil
        try persistCancellations(next)
    }
    private func compactSettledCancellationsIfNeeded() throws {
        guard cancellations.requestIDs.count >= WatchCancellationState.maximumIDs else { return }
        let queued: [WatchQueuedPaletteRequest]
        if let queuedRequestsOverride {
            // Tests supply the complete synthetic platform queue explicitly.
            queued = queuedRequestsOverride()
        } else if let session, session.activationState == .activated {
            queued = session.outstandingUserInfoTransfers.map { $0 as WatchQueuedPaletteRequest }
        } else {
            // Before activation, absence of a local handle proves nothing about
            // the platform's durable queue. Keep every unresolved tombstone.
            return
        }
        var protected = Set<UUID>()
        if let pending { protected.insert(pending.id) }
        if let latest = cancellations.lastCancelledID { protected.insert(latest) }
        if FileManager.default.fileExists(atPath: file.path) {
            guard let current = pending,
                  let persisted = try? PaletteTransfer.decode(BoundedFileReader.read(file, maximumBytes: PaletteTransfer.maximumBytes)),
                  persisted == current else { throw WatchTransferStorageError.pendingChanged }
            protected.insert(persisted.id)
        }
        var outstanding = queued
        if let activeTransfer { outstanding.append(activeTransfer) }
        for request in outstanding {
            // Even a malformed matching queue entry is unresolved. Cancellation
            // itself still requires the complete validated owned protocol.
            if let text = request.userInfo["requestID"] as? String, let id = UUID(uuidString: text) { protected.insert(id) }
        }
        let retained = cancellations.requestIDs.filter { protected.contains($0) }
        guard retained.count < cancellations.requestIDs.count else { return }
        var next = cancellations; next.requestIDs = retained
        // A late foreground reply/receipt cannot create a pending request: all
        // handlers require its UUID to equal the current durable request first.
        // Keep the latest cancellation so relaunch still reports the right outcome.
        try persistCancellations(next)
    }
    private func isActiveRequest(_ id: UUID) -> Bool {
        !storageNeedsRecovery && pending?.id == id && !cancellations.requestIDs.contains(id)
    }
    private func cancelQueuedRequests(for id: UUID) { cancelQueuedRequests(for: Set([id])) }
    private func cancelQueuedRequests(for ids: Set<UUID>, receipt: PaletteTransferReceipt? = nil) {
        guard !ids.isEmpty || receipt != nil else { return }
        func matches(_ userInfo: [String: Any]) -> Bool {
            guard let text = userInfo["requestID"] as? String, let id = UUID(uuidString: text),
                  ids.contains(id) || receipt?.requestID == id,
                  let data = userInfo["touchColorPaletteV1"] as? Data,
                  let payload = try? PaletteTransfer.decode(data), payload.id == id else { return false }
            if ids.contains(id) { return true }
            // A saved acceptance/decline authorizes recovery only for the exact
            // payload that produced that receipt, never a conflicting same UUID.
            guard let receipt, let fingerprint = try? PaletteFingerprint.of(payload) else { return false }
            return fingerprint == receipt.fingerprint
        }
        var requests: [WatchQueuedPaletteRequest] = queuedRequestsOverride?()
            ?? (session?.outstandingUserInfoTransfers.map { $0 as WatchQueuedPaletteRequest } ?? [])
        if let activeTransfer { requests.append(activeTransfer) }
        var cancelled = Set<ObjectIdentifier>()
        for request in requests {
            guard matches(request.userInfo) else { continue }
            if cancelled.insert(ObjectIdentifier(request)).inserted { request.cancel() }
        }
        if let activeTransfer, matches(activeTransfer.userInfo) { self.activeTransfer = nil }
    }
    func reconcileCancelledRequests() {
        guard !storageNeedsRecovery else { return }
        cancelQueuedRequests(for: Set(cancellations.requestIDs))
    }
    func reconcileSavedOutcomes() {
        guard !storageNeedsRecovery else { return }
        // Covers a crash after a saved receipt removed its local pending file,
        // but before the external queue observed cancellation. Never resend.
        cancelQueuedRequests(for: Set(cancellations.requestIDs), receipt: lastReceipt)
    }
    func receiveReceipt(_ data: Data, channel: String = "direct") {
        do {
            let receipt = try PaletteTransferReceipt.decode(data)
            guard !storageNeedsRecovery, let pending, !cancellations.requestIDs.contains(receipt.requestID),
                  receipt.requestID == pending.id, receipt.fingerprint == (try PaletteFingerprint.of(pending)) else { return }
            // Persist the acknowledgement before clearing its request; a relaunch reconciles
            // either ordering without resending or applying an old acknowledgement to a new request.
            try receipt.encoded().write(to: receiptFile, options: .atomic)
            try clearLastCancellationStatus()
#if DEBUG
            pairedReceiptChannel = channel
#endif
            lastReceipt = receipt
            cancelQueuedRequests(for: Set<UUID>(), receipt: receipt)
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
            self.pending = nil; sending = false
            status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
        } catch { status = NSLocalizedString("The transfer acknowledgement could not be saved. The request was kept for retry.", comment: "Transfer receipt") }
    }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String : Any]) {
        guard let data = message["touchColorReceiptV1"] as? Data else { return }
        Task { @MainActor in self.receiveReceipt(data, channel: "sendMessage") }
    }
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String : Any] = [:]) {
        guard let data = userInfo["touchColorReceiptV1"] as? Data else { return }
        Task { @MainActor in self.receiveReceipt(data, channel: "transferUserInfo") }
    }
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in
#if DEBUG
            self.pairedActivationCallbackState = String(activationState.rawValue)
            self.pairedActivationErrorDomain = error.map { String(($0 as NSError).domain.prefix(128)) } ?? ""
            self.pairedActivationErrorCode = error.map { String(($0 as NSError).code) } ?? ""
            self.recordPairedReadiness("activation-completed")
#endif
            if let error { self.status = error.localizedDescription }
            if activationState == .activated, error == nil, !self.storageNeedsRecovery {
                self.reconcileSavedOutcomes()
            }
            // Activation does not silently send a retained request; Retry is explicit.
        }
    }
#if DEBUG
    nonisolated func sessionCompanionAppInstalledDidChange(_ session: WCSession) {
        Task { @MainActor in self.recordPairedReadiness("companion-installed-changed") }
    }
    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.recordPairedReadiness("reachability-changed") }
    }
#endif
    nonisolated func session(_ session: WCSession, didFinish userInfoTransfer: WCSessionUserInfoTransfer, error: Error?) {
        guard let data = userInfoTransfer.userInfo["touchColorPaletteV1"] as? Data,
              let request = try? PaletteTransfer.decode(data),
              userInfoTransfer.userInfo["requestID"] as? String == request.id.uuidString else { return }
        Task { @MainActor in self.completeQueuedRequest(request, error: error) }
    }
    func completeQueuedRequest(_ request: PaletteTransfer, error: Error?) {
        guard pending == request, isActiveRequest(request.id) else { return }
        activeTransfer = nil
        if let error { status = error.localizedDescription }
        else {
            status = NSLocalizedString("Delivered to iPhone for review. The phone palette changes only after acceptance.", comment: "Watch transfer status")
            // Keep the request available across relaunch until the user dismisses it.
        }
    }
}
