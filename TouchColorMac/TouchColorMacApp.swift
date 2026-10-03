import SwiftUI

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
                .frame(minWidth: 740, minHeight: 520)
        }
        .defaultSize(width: 1080, height: 740)
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
