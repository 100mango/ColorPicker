import SwiftUI
import AppKit

@main struct TouchColorMacApp: App {
    @StateObject private var library: PaletteLibrary
    init() {
        var defaults = UserDefaults.standard
        #if DEBUG
        if let suite = ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_DEFAULTS"] {
            defaults = UserDefaults(suiteName: suite)!
            if ProcessInfo.processInfo.arguments.contains("--ui-test-reset") { defaults.removePersistentDomain(forName: suite) }
        }
        #endif
        _library = StateObject(wrappedValue: PaletteLibrary(defaults: defaults))
    }
    var body: some Scene {
        WindowGroup("TouchColor") {
            ColorWindow(library: library)
                .background(NativeWindowMinimumSize())
                #if DEBUG
                .overlay(alignment: .topLeading) {
                    if let proof = SandboxRuntimeProof.json {
                        Text(proof).font(.caption2).lineLimit(4).accessibilityIdentifier("debug.sandbox.proof")
                    }
                }
                #endif
        }
        .defaultSize(width: 960, height: 640)
        .commands { ColorCommands() }
        Settings { PrivacyView() }
    }
}

struct SessionFocusKey: FocusedValueKey { typealias Value = ImageSession }
struct LibraryFocusKey: FocusedValueKey { typealias Value = PaletteLibrary }
extension FocusedValues {
    var colorSession: ImageSession? {
        get { self[SessionFocusKey.self] }
        set { self[SessionFocusKey.self] = newValue }
    }
    var colorLibrary: PaletteLibrary? {
        get { self[LibraryFocusKey.self] }
        set { self[LibraryFocusKey.self] = newValue }
    }
}

struct ColorCommands: Commands {
    @FocusedValue(\.colorSession) private var session
    @FocusedValue(\.colorLibrary) private var library
    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("Open Image or Palette…") { if let session, let library { MacImportExport.open(session: session, library: library) } }
                .keyboardShortcut("o")
            Button("Export Palette…") { if let session, let library { MacImportExport.exportPalette(library: library, session: session) } }
                .keyboardShortcut("e")
            Button("Export Image as PNG…") { if let session { MacImportExport.exportImage(session: session) } }
                .disabled(session?.raster == nil || session?.exporting == true)
        }
        CommandGroup(after: .pasteboard) {
            Button("Paste Image") { if let session, let library { MacImportExport.paste(session: session, library: library) } }
                .keyboardShortcut("v", modifiers: [.command, .shift])
        }
        CommandMenu("Sample") {
            Button("Save Color") { if let library, let color = session?.selectedColor { library.append([color]) } }
                .keyboardShortcut("s").disabled(session?.selectedColor == nil)
            Button("Sample Image Center") { session?.select(.center) }.keyboardShortcut("0")
            Button("Zoom In") { if let session { session.changeZoom(session.zoom * 2) } }.keyboardShortcut("+")
            Button("Zoom Out") { if let session { session.changeZoom(session.zoom / 2) } }.keyboardShortcut("-")
            Button("Actual Fit (1×)") { session?.changeZoom(1) }.keyboardShortcut("1")
        }
    }
}

/// Keep the minimum on the actual NSWindow. A SwiftUI flexible root frame feeds its
/// ideal height back into NavigationSplitView when an AppKit canvas is inserted.
struct NativeWindowMinimumSize: NSViewRepresentable {
    func makeNSView(context: Context) -> MinimumSizeView { MinimumSizeView() }
    func updateNSView(_ view: MinimumSizeView, context: Context) {}
}
final class MinimumSizeView: NSView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        #if DEBUG
        if NativeModalAuditProbe.enabled, let original = window {
            DispatchQueue.main.async { NativeModalAuditProbe.shared.start(replacing: original) }
            return
        }
        #endif
        window?.contentMinSize = NSSize(width: 740, height: 520)
        window?.contentView?.setAccessibilityLabel(NSLocalizedString("TouchColor workspace", comment: "Window accessibility"))
        window?.contentView?.setAccessibilityIdentifier("workspace.content")
    }
}

/// NavigationSplitView creates a separate accessible hosting group for each pane.
/// Label the outermost existing group inside this marker's split pane, without
/// changing its role, children, or the window's own accessibility container.
struct NativePaneAccessibility: NSViewRepresentable {
    let label: String
    let identifier: String
    func makeNSView(context: Context) -> PaneAccessibilityView {
        let view = PaneAccessibilityView()
        view.setAccessibilityElement(false)
        return view
    }
    func updateNSView(_ view: PaneAccessibilityView, context: Context) {
        view.paneLabel = label; view.paneIdentifier = identifier
        view.labelPane()
        DispatchQueue.main.async { [weak view] in view?.labelPane() }
    }
}

final class PaneAccessibilityView: NSView {
    var paneLabel = ""
    var paneIdentifier = ""
    private(set) weak var labeledPane: NSView?

    override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); labelPane() }
    override func viewDidMoveToSuperview() { super.viewDidMoveToSuperview(); labelPane() }
    override func layout() { super.layout(); labelPane() }

    func labelPane() {
        guard window != nil, !paneLabel.isEmpty else { return }
        var ancestor = superview
        var candidate: NSView?
        for _ in 0..<32 {
            guard let view = ancestor else { return }
            if view is NSSplitView {
                guard let candidate else { return }
                // AppKit's glass/sidebar wrappers may add extra view levels;
                // identify the boundary by public role and split containment.
                if candidate.accessibilityLabel() != paneLabel { candidate.setAccessibilityLabel(paneLabel) }
                if candidate.accessibilityIdentifier() != paneIdentifier { candidate.setAccessibilityIdentifier(paneIdentifier) }
                labeledPane = candidate
                return
            }
            if view.isAccessibilityElement(), view.accessibilityRole() == .group { candidate = view }
            ancestor = view.superview
        }
    }
}
