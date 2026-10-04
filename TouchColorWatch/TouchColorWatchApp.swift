import SwiftUI

@main struct TouchColorWatchApp: App {
    @StateObject private var palette: WatchPalette
    @StateObject private var transfer: WatchTransfer
    init() {
        var defaults = UserDefaults.standard
        var transferDirectory: URL?
        #if DEBUG
        if let suite = ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_DEFAULTS"] {
            defaults = UserDefaults(suiteName: suite)!
            let component = "suite-" + suite.map { $0.isLetter || $0.isNumber || $0 == "." || $0 == "-" ? String($0) : "_" }.joined()
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-UITransfers").appendingPathComponent(component)
            if ProcessInfo.processInfo.arguments.contains("--ui-test-reset"), FileManager.default.fileExists(atPath: directory.path) { try? FileManager.default.removeItem(at: directory) }
            transferDirectory = directory
            if ProcessInfo.processInfo.arguments.contains("--ui-test-reset") { defaults.removePersistentDomain(forName: suite) }
        }
        #endif
        _palette = StateObject(wrappedValue: WatchPalette(defaults: defaults))
        _transfer = StateObject(wrappedValue: WatchTransfer(directory: transferDirectory))
    }
    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_LARGEST_TRAIT"] == "1" {
                WatchHome(palette: palette, transfer: transfer).dynamicTypeSize(.accessibility5)
            } else { WatchHome(palette: palette, transfer: transfer) }
            #else
            WatchHome(palette: palette, transfer: transfer)
            #endif
        }
    }
}
