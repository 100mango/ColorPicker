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
    func receive(_ data: Data) {
        do {
            if let receipt = try inbox.receive(data) { acknowledge(receipt) }
            status = nil
        } catch {
            status = NSLocalizedString("The Watch transfer could not be added to the inbox. Existing colors and pending transfers were kept.", comment: "Companion inbox error")
        }
        NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self)
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
        guard let session = connectivity, session.activationState == .activated, session.isWatchAppInstalled,
              let data = try? receipt.encoded() else { return }
        // The system queues this bounded acknowledgement. If delivery is lost, the
        // watch retries its same UUID and receive returns the saved receipt without reapplying.
        let message: [String: Any] = ["touchColorReceiptV1": data, "receiptID": receipt.requestID.uuidString]
        if session.isReachable {
            session.sendMessage(message, replyHandler: nil) { _ in
                // The same saved receipt is returned when the watch explicitly retries.
            }
        } else if !session.outstandingUserInfoTransfers.contains(where: { ($0.userInfo["receiptID"] as? String) == receipt.requestID.uuidString }) {
            session.transferUserInfo(message)
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
        if let error { Task { @MainActor in self.status = error.localizedDescription; NotificationCenter.default.post(name: .touchColorWatchInboxChanged, object: self) } }
    }
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) { session.activate() }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        guard let data = message["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), message["requestID"] as? String == request.id.uuidString else {
            replyHandler(["received": false]); return
        }
        Task { @MainActor in
            self.receive(data)
            replyHandler(["received": self.status == nil, "requestID": request.id.uuidString])
        }
    }
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        guard let data = userInfo["touchColorPaletteV1"] as? Data, data.count <= PaletteTransfer.maximumBytes,
              let request = try? PaletteTransfer.decode(data), userInfo["requestID"] as? String == request.id.uuidString else { return }
        Task { @MainActor in self.receive(data) }
    }
}
