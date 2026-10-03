import SwiftUI

@main struct TouchColorWatchApp: App {
    @StateObject private var palette: WatchPalette
    @StateObject private var transfer = WatchTransfer()
    init() {
        var defaults = UserDefaults.standard
        #if DEBUG
        if let suite = ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_DEFAULTS"] {
            defaults = UserDefaults(suiteName: suite)!
            if ProcessInfo.processInfo.arguments.contains("--ui-test-reset") { defaults.removePersistentDomain(forName: suite) }
        }
        #endif
        _palette = StateObject(wrappedValue: WatchPalette(defaults: defaults))
    }
    var body: some Scene { WindowGroup { WatchHome(palette: palette, transfer: transfer) } }
}
