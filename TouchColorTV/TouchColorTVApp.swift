import SwiftUI

@main struct TouchColorTVApp: App {
    @StateObject private var library: PaletteLibrary
    init() {
        var defaults = UserDefaults.standard
        var domain = Bundle.main.bundleIdentifier ?? "com.mango.touchColor"
        #if DEBUG
        if let suite = ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_DEFAULTS"] {
            defaults = UserDefaults(suiteName: suite)!; domain = suite
            if ProcessInfo.processInfo.arguments.contains("--ui-test-reset") { defaults.removePersistentDomain(forName: suite) }
        }
        #endif
        _library = StateObject(wrappedValue: PaletteLibrary(defaults: defaults, domain: domain))
    }
    var body: some Scene { WindowGroup { TVColorWindow(library: library) } }
}
