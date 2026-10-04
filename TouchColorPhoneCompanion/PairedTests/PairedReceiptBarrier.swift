import XCTest
import Foundation

/// Coordinates test lifetimes only. This never writes either app's container,
/// palette, WatchConnectivity messages, pending requests, or receipts.
func pairedObservation(_ element: XCUIElement) throws -> [String: String] {
    let text = try XCTUnwrap(element.value as? String)
    let data = try XCTUnwrap(text.data(using: .utf8))
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])
}

/// Read-only app accessibility observations. Diagnostics never constitute a receipt.
final class PairedReadinessObserver {
    let role: String
    private var lastRecord = ""
    private var emitted = 0
    private var overflowReported = false
    private(set) var latest: [String: String]?
    init(role: String) { self.role = role }
    @discardableResult func observe(_ element: XCUIElement, phase: String, nested: Bool = true) -> [String: String]? {
        guard element.exists, let raw = element.value as? String, raw.utf8.count <= 4096,
              let data = raw.data(using: .utf8),
              let outer = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return nil }
        let value: [String: String]
        if nested {
            guard let text = outer["connection"], let data = text.data(using: .utf8),
                  let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return nil }
            value = decoded
        } else { value = outer }
        guard value["schema"] == "1", value["role"] == role, value["source"] == "public-WCSession",
              let runID = ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_RUN_ID"] else { return nil }
        latest = value
        var record = value; record["runID"] = runID; record["phase"] = phase
        guard let encoded = try? JSONSerialization.data(withJSONObject: record, options: .sortedKeys),
              encoded.count <= 2048 else { return nil }
        let text = String(decoding: encoded, as: UTF8.self)
        if text != lastRecord {
            lastRecord = text
            if emitted < 64 {
                emitted += 1
                print("TOUCHCOLOR_PAIRED_READINESS " + text); fflush(stdout)
            } else if !overflowReported {
                overflowReported = true
                let identity = ["role": role, "runID": runID]
                if let data = try? JSONSerialization.data(withJSONObject: identity, options: .sortedKeys) {
                    print("TOUCHCOLOR_PAIRED_READINESS_OVERFLOW " + String(decoding: data, as: UTF8.self)); fflush(stdout)
                }
            }
        }
        return value
    }
    static func watchIsForegroundReady(_ value: [String: String]?) -> Bool {
        guard let value else { return false }
        return value["role"] == "watch" && value["supported"] == "true" && value["sessionPresent"] == "true"
            && value["activationState"] == "2" && value["activationCallbackState"] == "2"
            && value["activationErrorDomain"] == "" && value["activationErrorCode"] == ""
            && value["companionInstalled"] == "true" && value["reachable"] == "true"
    }
}

func waitForPairedReceiptBarrier(role: String, observation: [String: String]) throws {
    let requestID = try XCTUnwrap(observation["requestID"].flatMap(UUID.init(uuidString:)))
    XCTAssertEqual(observation["requestProtocol"], "touchColorPaletteV1")
    XCTAssertEqual(observation["receiptProtocol"], "touchColorReceiptV1")
    XCTAssertEqual(observation["version"], "1")
    XCTAssertEqual(observation["receiveChannel"], "sendMessage")
    XCTAssertEqual(observation["outcome"], "accepted")
    let environment = ProcessInfo.processInfo.environment
    let runID = try XCTUnwrap(environment["TOUCHCOLOR_PAIRED_RUN_ID"].flatMap(UUID.init(uuidString:)))
    let root = FileManager.default.temporaryDirectory
    let request = root.appendingPathComponent("TouchColor-paired-\(runID.uuidString).json")
    let acknowledgement = request.appendingPathExtension("ack")
    // Keep DEBUG connection metadata out of the existing <=1024-byte receipt
    // barrier. The same exact protocol/UUID/fingerprint/outcome checks still apply.
    let receiptKeys = Set(["requestID", "requestProtocol", "receiptProtocol", "version", "fingerprint", "outcome", "receiveChannel"])
    var value = observation.filter { receiptKeys.contains($0.key) }
    value["runID"] = runID.uuidString; value["role"] = role
    try JSONSerialization.data(withJSONObject: value).write(to: request, options: .atomic)
    print("TOUCHCOLOR_PAIRED_BARRIER " + String(decoding: try JSONSerialization.data(withJSONObject: value, options: .sortedKeys), as: UTF8.self)); fflush(stdout)
    let complete = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
        guard let data = try? Data(contentsOf: acknowledgement), data.count <= 1024,
              let received = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return false }
        return received["runID"] == runID.uuidString && received["requestID"] == requestID.uuidString && received["phase"] == "both-observed-receipt"
            && ["fingerprint", "requestProtocol", "receiptProtocol", "version"].allSatisfy { received[$0] == observation[$0] }
    }, object: nil)
    // Phone may accept before the Watch's remaining 60-second retry window.
    // Reserve the two bounded 15-second host container lookups as well. The
    // enclosing XCTest allowance stays 240 seconds and the CI job stays 45 minutes.
    let timeout: TimeInterval = role == "phone" ? 90 : 60
    XCTAssertEqual(XCTWaiter.wait(for: [complete], timeout: timeout), .completed, "Both real UI processes must confirm the same acceptance before either relaunches")
    try? FileManager.default.removeItem(at: request)
    try? FileManager.default.removeItem(at: acknowledgement)
}
