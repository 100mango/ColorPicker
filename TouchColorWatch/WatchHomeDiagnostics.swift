#if DEBUG
import Foundation
import OSLog

/// Observes delivery to Home, not model values or all upstream publications.
/// This is plain, fixed-size logger storage; it never invalidates a SwiftUI view.
@MainActor enum WatchHomeDiagnostics {
    enum Event: Int { case appear, disappear, palette, transfer }
    private static let limits: [UInt32] = [4, 4, 8, 8]
    private static var counts: [UInt32] = [0, 0, 0, 0]
    private static var omitted: [UInt32] = [0, 0, 0, 0]
    private static var saturated = false
    private static let names = ["appear", "disappear", "palette", "transfer"]
    private static let testCase = String((ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_CASE"] ?? "unscoped")
        .map { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == ".") ? $0 : "_" }.prefix(120))
    private static let enabled = testCase == "__WatchWorkflowTests_testHomeListDigitalCrownFromColdLaunch_"
    private static let logger = Logger(subsystem: "com.mango.touchColor.WatchDiagnostics", category: "home")

    private static func increment(_ values: inout [UInt32], at index: Int) {
        if values[index] == UInt32.max { saturated = true }
        else { values[index] += 1 }
    }

    static func record(_ event: Event) {
        guard enabled else { return }
        let index = event.rawValue
        increment(&counts, at: index)
        if counts[index] > limits[index] { increment(&omitted, at: index) }
        // Each source retains its own first events plus its first-overflow
        // snapshot. Later lifecycle snapshots carry cumulative separate drops.
        // Maximum 5 + 5 + 9 + 9 = 28 records, each at most 512 UTF-8 bytes.
        guard counts[index] <= limits[index] + 1 else { return }
        let countText = counts.map(String.init).joined(separator: ",")
        let omittedText = omitted.map(String.init).joined(separator: ",")
        let uptime = min(UInt64.max / 2, UInt64(ProcessInfo.processInfo.systemUptime * 1000))
        let payload = "{\"case\":\"\(testCase)\",\"pid\":\(ProcessInfo.processInfo.processIdentifier),\"uptimeMilliseconds\":\(uptime),\"event\":\"\(names[index])\",\"counts\":[\(countText)],\"omitted\":[\(omittedText)],\"saturated\":\(saturated),\"terminal\":false}"
        guard payload.utf8.count <= 512 else { return }
        logger.notice("WATCH_HOME \(payload, privacy: .public)")
    }
}
#endif
