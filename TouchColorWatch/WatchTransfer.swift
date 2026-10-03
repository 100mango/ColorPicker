import Foundation
import Combine
import WatchConnectivity
import ColorDomain
import ColorPaletteLegacy

/// Only an explicit Send creates a queued message. Pending payload survives relaunch;
/// retry keeps its UUID so the phone inbox can reject duplicate delivery.
@MainActor final class WatchTransfer: NSObject, ObservableObject, WCSessionDelegate {
    @Published private(set) var status = NSLocalizedString("Select Send to iPhone to request a transfer.", comment: "Watch transfer status")
    @Published private(set) var sending = false
    @Published private(set) var pending: PaletteTransfer?
    @Published private(set) var lastReceipt: PaletteTransferReceipt?
    private let file: URL
    private let receiptFile: URL
    private var activeTransfer: WCSessionUserInfoTransfer?
    private var session: WCSession?
    init(directory: URL? = nil, activate: Bool = true) {
        let folder = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        file = folder.appendingPathComponent("pending-color-transfer.json")
        receiptFile = folder.appendingPathComponent("last-color-transfer-receipt.json")
        super.init()
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: file.path) {
                pending = try PaletteTransfer.decode(Data(contentsOf: file))
                status = NSLocalizedString("A transfer is pending. Open TouchColor on iPhone, then choose Retry.", comment: "Watch transfer status")
            }
            if FileManager.default.fileExists(atPath: receiptFile.path) {
                let receipt = try PaletteTransferReceipt.decode(Data(contentsOf: receiptFile))
                lastReceipt = receipt
                if pending == nil {
                    status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
                }
                if let pending, receipt.requestID == pending.id, receipt.fingerprint == (try PaletteFingerprint.of(pending)) {
                    if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
                    self.pending = nil
                    status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
                }
            }
        } catch { status = NSLocalizedString("The pending transfer could not be read. Its file was kept.", comment: "Watch transfer error") }
        if activate && WCSession.isSupported() { session = .default; session?.delegate = self; session?.activate() }
    }
    func request(_ colors: [RGBColor]) {
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
        guard let pending, !sending else { return }
        guard let session, session.activationState == .activated, session.isCompanionAppInstalled else {
            status = NSLocalizedString("Waiting for TouchColor on the paired iPhone. Choose Retry when it is available.", comment: "Watch transfer status"); return
        }
        if session.isReachable, let data = try? pending.encoded() {
            sending = true
            let id = pending.id
            session.sendMessage(["touchColorPaletteV1": data, "requestID": id.uuidString], replyHandler: { [weak self] reply in
                Task { @MainActor in
                    guard let self, self.pending?.id == id else { return }
                    self.sending = false
                    self.status = reply["received"] as? Bool == true
                        ? NSLocalizedString("Received on iPhone. Open Watch Inbox there to review.", comment: "Foreground transfer status")
                        : NSLocalizedString("The phone could not stage this transfer. The request was kept for retry.", comment: "Foreground transfer status")
                }
            }, errorHandler: { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.pending?.id == id else { return }
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
            activeTransfer = session.transferUserInfo(["touchColorPaletteV1": data, "requestID": pending.id.uuidString])
        }
        status = NSLocalizedString("Queued for iPhone. This has not changed the phone palette.", comment: "Watch transfer status")
    }
    func cancel() {
        activeTransfer?.cancel(); activeTransfer = nil; sending = false
        guard pending != nil else { return }
        do { if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }; pending = nil
            status = NSLocalizedString("Transfer cancelled. If it already arrived, review it on iPhone.", comment: "Watch transfer status")
        } catch { status = error.localizedDescription }
    }
    func receiveReceipt(_ data: Data) {
        do {
            let receipt = try PaletteTransferReceipt.decode(data)
            guard let pending, receipt.requestID == pending.id, receipt.fingerprint == (try PaletteFingerprint.of(pending)) else { return }
            // Persist the acknowledgement before clearing its request; a relaunch reconciles
            // either ordering without resending or applying an old acknowledgement to a new request.
            try receipt.encoded().write(to: receiptFile, options: .atomic)
            lastReceipt = receipt
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
            self.pending = nil; activeTransfer?.cancel(); activeTransfer = nil; sending = false
            status = receipt.outcome == .accepted ? NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt") : NSLocalizedString("Declined on iPhone. Your watch palette is unchanged.", comment: "Transfer receipt")
        } catch { status = NSLocalizedString("The transfer acknowledgement could not be saved. The request was kept for retry.", comment: "Transfer receipt") }
    }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String : Any]) {
        guard let data = message["touchColorReceiptV1"] as? Data else { return }
        Task { @MainActor in self.receiveReceipt(data) }
    }
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String : Any] = [:]) {
        guard let data = userInfo["touchColorReceiptV1"] as? Data else { return }
        Task { @MainActor in self.receiveReceipt(data) }
    }
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in
            if let error { self.status = error.localizedDescription }
            // Activation does not silently send a retained request; Retry is explicit.
        }
    }
    nonisolated func session(_ session: WCSession, didFinish userInfoTransfer: WCSessionUserInfoTransfer, error: Error?) {
        let id = userInfoTransfer.userInfo["requestID"] as? String
        Task { @MainActor in
            guard let pending = self.pending, pending.id.uuidString == id else { return }
            self.activeTransfer = nil
            if let error { self.status = error.localizedDescription }
            else {
                self.status = NSLocalizedString("Delivered to iPhone for review. The phone palette changes only after acceptance.", comment: "Watch transfer status")
                // Keep the request available across relaunch until the user dismisses it.
            }
        }
    }
}
