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
    init(defaults: UserDefaults, domain: String) { inbox = PaletteInbox(defaults: defaults, domain: domain); super.init() }
    @objc var isSupported: Bool { WCSession.isSupported() }
    @objc func activate() {
        guard isSupported else {
            status = NSLocalizedString("Watch transfer is unavailable on this device. You can import a palette using Files or Paste.", comment: "Unsupported companion")
            NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
            return
        }
        let session = WCSession.default; connectivity = session; session.delegate = self; session.activate()
    }
    func pending() throws -> [PaletteTransfer] { try inbox.pending() }
    @discardableResult private func receive(_ data: Data, epoch: UInt64) -> Bool {
        guard receiptRoutes.isCurrent(epoch) else { return false }
        do {
            let request = try PaletteTransfer.decode(data)
            let receipt = try inbox.receive(data)
            // The actual delegate callback captured this epoch before crossing to MainActor.
            // A queued callback from a previous counterpart cannot grant a new delivery route.
            guard receiptRoutes.admit(request.id, epoch: epoch) else { return false }
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
                session.sendMessage(message, replyHandler: nil) { _ in
                    // The Watch retains its UUID and explicitly retries after a lost receipt.
                }
            } else if !session.outstandingUserInfoTransfers.contains(where: { ($0.userInfo["receiptID"] as? String) == receipt.requestID.uuidString }) {
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
        navigation.modalPresentationStyle = .pageSheet
        controller.present(navigation, animated: true) { navigation.presentationController?.delegate = content }
    }
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
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
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) { invalidateDelivery(session) }
    nonisolated func sessionDidDeactivate(_ session: WCSession) { invalidateDelivery(session); session.activate() }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        guard let epoch = receiptRoutes.currentEpoch(), session.activationState == .activated,
              let data = message["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), message["requestID"] as? String == request.id.uuidString else {
            replyHandler(["received": false]); return
        }
        Task { @MainActor in
            let received = self.receive(data, epoch: epoch)
            replyHandler(["received": received, "requestID": request.id.uuidString])
        }
    }
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        guard let epoch = receiptRoutes.currentEpoch(), session.activationState == .activated,
              let data = userInfo["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), userInfo["requestID"] as? String == request.id.uuidString else { return }
        Task { @MainActor in self.receive(data, epoch: epoch) }
    }
}
