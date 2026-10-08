import SwiftUI

@main struct TouchColorVisionApp: App {
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
        WindowGroup("TouchColor") { VisionColorWindow(library: library) }
            .defaultSize(width: 1000, height: 700)
    }
}
