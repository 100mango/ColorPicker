import SwiftUI
import AppKit
#if DEBUG
import CoreFoundation
import OSLog
#endif

@main struct TouchColorMacApp: App {
    @StateObject private var library: PaletteLibrary
    init() {
        #if DEBUG
        MacPassiveLifecycle.startIfEnabled()
        #endif
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
        #if DEBUG
        let _ = MacPassiveLifecycle.shared?.checkpoint(.sceneBody)
        #endif
        WindowGroup("TouchColor") {
            #if DEBUG
            let _ = MacPassiveLifecycle.shared?.checkpoint(.windowContentEntered)
            let content = ColorWindow(library: library)
                .background(NativeWindowMinimumSize())
                .overlay(alignment: .topLeading) {
                    if let proof = SandboxRuntimeProof.json {
                        Text(proof).font(.caption2).lineLimit(4).accessibilityIdentifier("debug.sandbox.proof")
                    }
                }
            let _ = MacPassiveLifecycle.shared?.checkpoint(.windowContentReturned)
            content
            #else
            ColorWindow(library: library)
                .background(NativeWindowMinimumSize())
            #endif
        }
        .defaultSize(width: 960, height: 640)
        .commands { ColorCommands() }
        .workspaceDefaultLaunchPolicy()
        Settings { PrivacyView() }
    }
}

/// Explicit primary-workspace launch intent; keep normal restoration and multiple windows.
private extension Scene {
    func workspaceDefaultLaunchPolicy() -> some Scene {
        var scene = SceneBuilder.buildLimitedAvailability(self)
        if #available(macOS 15.0, *) {
            scene = SceneBuilder.buildLimitedAvailability(self.defaultLaunchBehavior(.presented))
        }
        return SceneBuilder.buildOptional(scene)
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
    func makeNSView(context: Context) -> MinimumSizeView {
        #if DEBUG
        let view = MinimumSizeView()
        MacPassiveLifecycle.shared?.markerCreated()
        return view
        #else
        MinimumSizeView()
        #endif
    }
    func updateNSView(_ view: MinimumSizeView, context: Context) {}
}
final class MinimumSizeView: NSView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        #if DEBUG
        MacPassiveLifecycle.shared?.markerMapped(window)
        #endif
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

#if DEBUG
/// Passive, synthetic test correlation only. No activation, scene creation or restoration writes.
@MainActor final class MacPassiveLifecycle {
    enum SceneCheckpoint: String {
        case sceneBody, windowContentEntered, windowContentReturned, colorWindowBody
    }
    static var shared: MacPassiveLifecycle?
    private let token: String
    private let launch = UUID().uuidString
    private let started = ProcessInfo.processInfo.systemUptime
    private let logger = Logger(subsystem: "com.mango.touchColor.MacLifecycle", category: "passive")
    private var observers: [NSObjectProtocol] = []
    private var sequence = 0
    private var bytes = 0
    private var omitted = 0
    private var stopped = false
    private var checkpoints: Set<SceneCheckpoint> = []
    private final class WindowIdentity {
        weak var window: NSWindow?
        let identifier: Int
        init(_ window: NSWindow, _ identifier: Int) { self.window = window; self.identifier = identifier }
    }
    private var identities: [WindowIdentity] = []
    private weak var workspace: NSWindow?

    static func startIfEnabled() {
        let environment = ProcessInfo.processInfo.environment
        guard shared == nil,
              let token = environment["TOUCHCOLOR_MAC_LIFECYCLE"], UUID(uuidString: token)?.uuidString == token,
              let suite = environment["TOUCHCOLOR_TEST_DEFAULTS"], suite.hasPrefix("TouchColor.mac-ui."),
              UUID(uuidString: String(suite.dropFirst("TouchColor.mac-ui.".count))) != nil,
              ProcessInfo.processInfo.arguments.contains("--ui-test-reset") else { return }
        let value = MacPassiveLifecycle(token: token); shared = value; value.start()
    }
    private init(token: String) { self.token = token }
    private func start() {
        let appEvents: [(Notification.Name, String)] = [
            (NSApplication.willFinishLaunchingNotification, "willFinishLaunching"),
            (NSApplication.didFinishRestoringWindowsNotification, "didFinishRestoringWindows"),
            (NSApplication.didFinishLaunchingNotification, "didFinishLaunching"),
            (NSApplication.didBecomeActiveNotification, "didBecomeActive"),
            (NSApplication.didResignActiveNotification, "didResignActive"),
            (NSApplication.didHideNotification, "didHide"), (NSApplication.didUnhideNotification, "didUnhide")]
        let windowEvents: [(Notification.Name, String)] = [
            (NSWindow.didBecomeKeyNotification, "windowKey"), (NSWindow.didResignKeyNotification, "windowResignKey"),
            (NSWindow.didMiniaturizeNotification, "windowMiniaturized"), (NSWindow.didDeminiaturizeNotification, "windowDeminiaturized"),
            (NSWindow.didChangeOcclusionStateNotification, "windowOcclusion"), (NSWindow.willCloseNotification, "windowWillClose")]
        for (name, event) in appEvents {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                MainActor.assumeIsolated {
                    guard let own = NSApp, let observed = note.object as? NSApplication, observed === own else { return }
                    if event == "didFinishLaunching" {
                        let scalar: String
                        if let raw = note.userInfo?[NSApplication.launchIsDefaultUserInfoKey] {
                            if let flag = raw as? NSNumber, CFGetTypeID(flag) == CFBooleanGetTypeID() {
                                scalar = flag.boolValue ? "reportedTrue" : "reportedFalse"
                            } else { scalar = "unexpectedType" }
                        } else { scalar = "missing" }
                        self?.record(event, launchIsDefault: scalar)
                    } else { self?.record(event) }
                }
            })
        }
        for (name, event) in windowEvents {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                MainActor.assumeIsolated {
                    guard let window = note.object as? NSWindow, NSApp?.windows.contains(where: { $0 === window }) == true else { return }
                    self?.record(event)
                }
            })
        }
        record("appInit", header: true)
        for seconds in [1.0, 5.0, 10.0] {
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
                guard let self else { return }
                if seconds == 10 { self.finish() } else { self.record("census") }
            }
        }
    }
    // First evaluation only, through the existing token-gated instance and bounds.
    // A late or omitted checkpoint stays omitted; it is never retried.
    func checkpoint(_ value: SceneCheckpoint) {
        guard !stopped, checkpoints.insert(value).inserted else { return }
        record(value.rawValue, sampleApp: false)
    }
    func markerCreated() { record("markerCreated") }
    func markerMapped(_ window: NSWindow?) {
        workspace = window
        record(window == nil ? "markerDetached" : "markerMapped")
    }
    private func identity(_ window: NSWindow?) -> Any {
        guard let window else { return NSNull() }
        if let value = identities.first(where: { $0.window === window }) { return value.identifier }
        guard identities.count < 16 else { return NSNull() }
        let value = identities.count + 1; identities.append(WindowIdentity(window, value)); return value
    }
    private func census() -> [String: Any] {
        guard let app = NSApp else { return ["present": false] }
        let windows = app.windows
        return ["present": true, "running": app.isRunning, "active": app.isActive, "hidden": app.isHidden,
                "policy": app.activationPolicy().rawValue, "count": windows.count, "omitted": max(0, windows.count - 4),
                "key": identity(app.keyWindow), "main": identity(app.mainWindow),
                "windows": windows.prefix(4).map { window -> [String: Any] in
                    let frame = window.frame
                    return ["id": identity(window), "number": window.windowNumber,
                            "frame": [frame.minX, frame.minY, frame.width, frame.height],
                            "visible": window.isVisible, "miniaturized": window.isMiniaturized,
                            "key": window.isKeyWindow, "main": window.isMainWindow,
                            "occlusion": window.occlusionState.rawValue, "restorable": window.isRestorable,
                            "restorationClass": window.restorationClass != nil,
                            "autosaveName": !window.frameAutosaveName.isEmpty,
                            "sheet": window.attachedSheet != nil, "workspace": window === workspace]
                }]
    }
    private func record(_ event: String, header: Bool = false, final: Bool = false, launchIsDefault: String? = nil, sampleApp: Bool = true) {
        guard !stopped else { return }
        let elapsed = ProcessInfo.processInfo.systemUptime - started
        // Delayed callbacks never extend observation. The final record reports omission honestly.
        if elapsed > 10 && !final { omitted += 1; return }
        guard final || sequence < 23 else { omitted += 1; return }
        var row: [String: Any] = ["v": 1, "token": token, "launch": launch,
            "pid": ProcessInfo.processInfo.processIdentifier, "epoch": Date().timeIntervalSince1970,
            "elapsed": elapsed, "sequence": sequence + 1, "event": event,
            "omittedRecords": omitted, "late": elapsed > 10]
        if event == "didFinishLaunching", let launchIsDefault { row["launchIsDefault"] = launchIsDefault }
        if elapsed <= 10 && sampleApp { row["app"] = census() }
        if header {
            let info = ProcessInfo.processInfo; let arguments = info.arguments
            let language = arguments.firstIndex(of: "-AppleLanguages").flatMap { $0 + 1 < arguments.count ? arguments[$0 + 1] : nil }
            let locale = arguments.firstIndex(of: "-AppleLocale").flatMap { $0 + 1 < arguments.count ? arguments[$0 + 1] : nil }
            row["product"] = ["bundle": Bundle.main.bundleIdentifier ?? "", "path": Bundle.main.bundleURL.path,
                "executable": Bundle.main.executableURL?.path ?? "", "reset": true,
                "language": ["(en)", "(zh-Hans)"].contains(language ?? "") ? (language ?? "") as Any : NSNull(),
                "locale": ["en_US", "zh_CN"].contains(locale ?? "") ? (locale ?? "") as Any : NSNull(),
                "suitePresent": true, "modalPresent": info.environment["TOUCHCOLOR_NATIVE_MODAL_PROBE"] != nil,
                "sandboxProbePresent": info.environment["TOUCHCOLOR_SANDBOX_PROBE_FILE"] != nil]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]),
              data.count + 22 <= 4096, bytes + data.count + 22 <= (final ? 12288 : 8192),
              let text = String(data: data, encoding: .utf8) else { omitted += 1; return }
        sequence += 1; bytes += data.count + 22
        logger.log("MAC_PASSIVE_LIFECYCLE \(text, privacy: .public)")
    }
    private func finish() {
        guard !stopped else { return }
        record("final", final: true); stopped = true
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers.removeAll()
    }
}
#endif
