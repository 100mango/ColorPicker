#if DEBUG
import AppKit

/// Opt-in diagnostic window, using standard AppKit chrome and modal APIs only.
/// It never changes product audit handling or hides an audit finding.
@MainActor final class NativeModalAuditProbe: NSObject {
    static let shared = NativeModalAuditProbe()
    static var enabled: Bool { ProcessInfo.processInfo.environment["TOUCHCOLOR_NATIVE_MODAL_PROBE"] == "1" }
    private var controlWindow: NSWindow?
    private var sheetWindow: NSWindow?
    private var alert: NSAlert?

    func start(replacing original: NSWindow) {
        guard controlWindow == nil else { return }
        let window = NSWindow(contentRect: NSRect(x: 160, y: 140, width: 640, height: 420),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "TouchColor"
        window.isReleasedWhenClosed = false
        window.toolbar = NSToolbar(identifier: "NativeModalProbeToolbar")
        window.toolbarStyle = .unified
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 640, height: 420))
        content.setAccessibilityLabel(NSLocalizedString("TouchColor workspace", comment: "Window accessibility"))
        let sheet = NSButton(title: "Open Standard Sheet", target: self, action: #selector(openSheet))
        sheet.bezelStyle = .rounded; sheet.frame = NSRect(x: 32, y: 300, width: 220, height: 32)
        sheet.setAccessibilityIdentifier("probe.standard.sheet")
        let alert = NSButton(title: "Open Standard Alert", target: self, action: #selector(openAlert))
        alert.bezelStyle = .rounded; alert.frame = NSRect(x: 32, y: 240, width: 220, height: 32)
        alert.setAccessibilityIdentifier("probe.standard.alert")
        content.addSubview(sheet); content.addSubview(alert); window.contentView = content
        controlWindow = window
        window.makeKeyAndOrderFront(nil)
        original.close()
    }
    @objc private func openSheet() {
        guard let window = controlWindow else { return }
        let sheet = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 360, height: 180),
                             styleMask: [.titled], backing: .buffered, defer: false)
        sheet.title = "Standard AppKit Sheet"; sheet.isReleasedWhenClosed = false
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 360, height: 180))
        let text = NSTextField(labelWithString: "Active standard sheet content")
        text.frame = NSRect(x: 24, y: 110, width: 312, height: 30); text.font = .systemFont(ofSize: 17)
        let done = NSButton(title: "Done", target: self, action: #selector(closeSheet))
        done.bezelStyle = .rounded; done.frame = NSRect(x: 220, y: 24, width: 110, height: 32)
        done.setAccessibilityIdentifier("probe.sheet.done")
        content.addSubview(text); content.addSubview(done); sheet.contentView = content
        sheetWindow = sheet; window.beginSheet(sheet)
    }
    @objc private func closeSheet() {
        guard let window = controlWindow, let sheet = sheetWindow else { return }
        window.endSheet(sheet); sheet.orderOut(nil); sheetWindow = nil
    }
    @objc private func openAlert() {
        guard let window = controlWindow else { return }
        let alert = NSAlert()
        alert.messageText = "Standard AppKit Alert"
        alert.informativeText = "Active standard alert content"
        alert.addButton(withTitle: "OK")
        self.alert = alert; alert.beginSheetModal(for: window)
    }
}
#endif
