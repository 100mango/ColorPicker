import UIKit
import WatchConnectivity
import ColorDomain
import ColorPaletteLegacy

extension Notification.Name { static let touchColorWatchInboxChanged = Notification.Name("TouchColorWatchInboxChanged") }

/// Explicit companion inbox. No received message changes the phone palette by itself.
/// Call activate from the iPhone app lifecycle and presentInbox from a visible user action.
@objc(TCWatchPaletteInbox)
@MainActor final class PhonePaletteInbox: NSObject, WCSessionDelegate {
    private static let instance = PhonePaletteInbox(defaults: .standard, domain: "com.mango.touchColor")
    @objc class func sharedInbox() -> PhonePaletteInbox { instance }
    private let inbox: PaletteInbox
    private nonisolated let receiptRoutes = PaletteReceiptRoutes()
    private var connectivity: WCSession?
    private(set) var status: String?
#if DEBUG
    // Read-only evidence of actual delegate ingress and explicit local acceptance.
    private var pairedRequests: [UUID: [String: String]] = [:]
    private var pairedReceipt: [String: String]?
    private var pairedReadinessValue = ""
    private var pairedActivationErrorDomain = ""
    private var pairedActivationErrorCode = ""
    private var pairedActivationCallbackState = ""
    private var pairedSelectedTransport = "none"
    private var pairedReadinessSequence = 0
    private func recordPairedReadiness(_ event: String, transport: String? = nil) {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" else { return }
        if let transport { pairedSelectedTransport = transport }
        pairedReadinessSequence = min(pairedReadinessSequence + 1, 1_000_000)
        let active = connectivity?.activationState == .activated
        let value: [String: String] = [
            "schema": "1", "role": "phone", "source": "public-WCSession", "event": event,
            "sequence": String(pairedReadinessSequence), "supported": WCSession.isSupported() ? "true" : "false",
            "sessionPresent": connectivity == nil ? "false" : "true",
            "activationState": connectivity.map { String($0.activationState.rawValue) } ?? "absent",
            "activationCallbackState": pairedActivationCallbackState,
            "activationErrorDomain": pairedActivationErrorDomain, "activationErrorCode": pairedActivationErrorCode,
            "paired": active ? (connectivity!.isPaired ? "true" : "false") : "unknown",
            "watchInstalled": active ? (connectivity!.isWatchAppInstalled ? "true" : "false") : "unknown",
            "reachable": active ? (connectivity!.isReachable ? "true" : "false") : "unknown",
            "selectedTransport": pairedSelectedTransport
        ]
        pairedReadinessValue = (try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys))
            .map { String(decoding: $0, as: UTF8.self) } ?? ""
        NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
    }
    private let pairedDefaults: UserDefaults
    private let pairedDomain: String
    func pairedRequestValue(_ id: UUID) -> String? { pairedJSON(pairedRequests[id]) }
    var pairedStatusValue: String? {
        if let pairedReceipt { return pairedJSON(pairedReceipt) }
        let pending = try? inbox.pending()
        let active = connectivity?.activationState == .activated && receiptRoutes.currentEpoch() != nil
        let values = pairedDefaults.persistentDomain(forName: pairedDomain) ?? [:]
        let raw = values[PaletteInbox.acceptedReceiptStorageIdentifier]
        guard let accepted = raw == nil ? [:] : raw as? [String: String], accepted.count <= PaletteInbox.maximumReceipts,
              accepted.allSatisfy({ UUID(uuidString: $0.key)?.uuidString == $0.key && $0.value.count == 64 && $0.value.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) }) else {
            return pairedJSON(["phase": "not-ready", "acceptedReceiptCount": "unreadable"])
        }
        var value = ["phase": active && status == nil && pending?.isEmpty == true ? "ready-empty" : "not-ready", "activated": active ? "true" : "false", "pendingCount": pending.map { String($0.count) } ?? "unreadable", "acceptedReceiptCount": String(accepted.count)]
        if accepted.count == 1, let receipt = accepted.first {
            value.merge(["requestID": receipt.key, "fingerprint": receipt.value, "requestProtocol": "touchColorPaletteV1", "receiptProtocol": "touchColorReceiptV1", "version": "1", "outcome": "accepted", "receiveChannel": "persisted"]) { _, new in new }
        }
        return pairedJSON(value)
    }
    private func pairedJSON(_ value: [String: String]?) -> String? {
        guard ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1", var value else { return nil }
        value["connection"] = pairedReadinessValue
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys) else { return nil }
        return String(decoding: data, as: UTF8.self)
    }
#endif
    init(defaults: UserDefaults, domain: String) {
        inbox = PaletteInbox(defaults: defaults, domain: domain)
#if DEBUG
        pairedDefaults = defaults; pairedDomain = domain
#endif
        super.init()
    }
    @objc var isSupported: Bool { WCSession.isSupported() }
    @objc func activate() {
        guard isSupported else {
#if DEBUG
            recordPairedReadiness("unsupported")
#endif
            status = NSLocalizedString("Watch transfer is unavailable on this device. You can import a palette using Files or Paste.", comment: "Unsupported companion")
            NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
            return
        }
        let session = WCSession.default; connectivity = session; session.delegate = self; session.activate()
#if DEBUG
        recordPairedReadiness("activate-called")
#endif
    }
    func pending() throws -> [PaletteTransfer] { try inbox.pending() }
    @discardableResult private func receive(_ data: Data, epoch: UInt64, channel: String) -> Bool {
        guard receiptRoutes.isCurrent(epoch) else { return false }
        do {
            let request = try PaletteTransfer.decode(data)
            let receipt = try inbox.receive(data)
            // The actual delegate callback captured this epoch before crossing to MainActor.
            // A queued callback from a previous counterpart cannot grant a new delivery route.
            guard receiptRoutes.admit(request.id, epoch: epoch) else { return false }
#if DEBUG
            if ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" {
                pairedRequests[request.id] = ["requestID": request.id.uuidString, "requestProtocol": "touchColorPaletteV1", "version": "1", "fingerprint": try PaletteFingerprint.of(request), "receiveChannel": channel]
            }
#endif
            if let receipt { acknowledge(receipt) }
            status = nil
        } catch {
            status = NSLocalizedString("The Watch transfer could not be added to the inbox. Existing colors and pending transfers were kept.", comment: "Companion inbox error")
        }
        NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
        return status == nil
    }
    func accept(_ id: UUID) throws {
        let receipt = try inbox.accept(id)
#if DEBUG
        if var value = pairedRequests[id] {
            value["receiptProtocol"] = "touchColorReceiptV1"; value["fingerprint"] = receipt.fingerprint
            value["outcome"] = receipt.outcome.rawValue; value["version"] = String(receipt.version)
            pairedReceipt = value
        }
#endif
        acknowledge(receipt)
        NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
    }
    func reject(_ id: UUID) throws {
        let receipt = try inbox.reject(id)
        acknowledge(receipt)
        NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
    }
    private func acknowledge(_ receipt: PaletteTransferReceipt) {
        guard let session = connectivity, let data = try? receipt.encoded() else { return }
        receiptRoutes.deliver(receipt.requestID) {
            guard session.activationState == .activated, session.isWatchAppInstalled else { return }
            let message: [String: Any] = ["touchColorReceiptV1": data, "receiptID": receipt.requestID.uuidString]
            if session.isReachable {
#if DEBUG
                recordPairedReadiness("sendMessage", transport: "sendMessage")
#endif
                session.sendMessage(message, replyHandler: nil) { _ in
                    // The Watch retains its UUID and explicitly retries after a lost receipt.
                }
            } else if !session.outstandingUserInfoTransfers.contains(where: { ($0.userInfo["receiptID"] as? String) == receipt.requestID.uuidString }) {
#if DEBUG
                recordPairedReadiness("transferUserInfo", transport: "transferUserInfo")
#endif
                session.transferUserInfo(message)
            }
        }
    }
    private nonisolated func invalidateDelivery(_ session: WCSession) {
        // Revoke before scheduling UI work, and cancel only this protocol's queued receipts.
        receiptRoutes.invalidate()
        for transfer in session.outstandingUserInfoTransfers where transfer.userInfo["touchColorReceiptV1"] is Data {
            transfer.cancel()
        }
    }
    @objc func presentInbox(from controller: UIViewController, completion: @escaping () -> Void) {
        let content = PhonePaletteInboxController(inbox: self)
        content.onDismiss = completion
        let navigation = UINavigationController(rootViewController: content)
        navigation.modalPresentationStyle = .fullScreen
        controller.present(navigation, animated: true) { navigation.presentationController?.delegate = content }
    }
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
#if DEBUG
        Task { @MainActor in
            self.pairedActivationCallbackState = String(activationState.rawValue)
            self.pairedActivationErrorDomain = error.map { String(($0 as NSError).domain.prefix(128)) } ?? ""
            self.pairedActivationErrorCode = error.map { String(($0 as NSError).code) } ?? ""
            self.recordPairedReadiness("activation-completed")
        }
#endif
        guard activationState == .activated, session.activationState == .activated, error == nil else {
            invalidateDelivery(session)
            if let error { Task { @MainActor in
                guard self.receiptRoutes.currentEpoch() == nil else { return }
                self.status = error.localizedDescription
                NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
            } }
            return
        }
        let epoch = receiptRoutes.activate()
        Task { @MainActor in
            guard self.receiptRoutes.isCurrent(epoch) else { return }
            self.status = nil
            NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
        }
    }
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {
        invalidateDelivery(session)
#if DEBUG
        Task { @MainActor in self.recordPairedReadiness("inactive") }
#endif
    }
    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        invalidateDelivery(session); session.activate()
#if DEBUG
        Task { @MainActor in self.recordPairedReadiness("deactivated") }
#endif
    }
#if DEBUG
    nonisolated func sessionWatchStateDidChange(_ session: WCSession) {
        Task { @MainActor in self.recordPairedReadiness("watch-state-changed") }
    }
    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.recordPairedReadiness("reachability-changed") }
    }
#endif
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        guard let epoch = receiptRoutes.currentEpoch(), session.activationState == .activated,
              let data = message["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), message["requestID"] as? String == request.id.uuidString else {
            replyHandler(["received": false]); return
        }
        Task { @MainActor in
            let received = self.receive(data, epoch: epoch, channel: "sendMessage")
            replyHandler(["received": received, "requestID": request.id.uuidString])
        }
    }
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        guard let epoch = receiptRoutes.currentEpoch(), session.activationState == .activated,
              let data = userInfo["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), userInfo["requestID"] as? String == request.id.uuidString else { return }
        Task { @MainActor in self.receive(data, epoch: epoch, channel: "transferUserInfo") }
    }
}
