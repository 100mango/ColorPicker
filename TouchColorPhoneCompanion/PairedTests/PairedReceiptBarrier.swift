import XCTest
import Foundation

/// Coordinates test lifetimes only. This never writes either app's container,
/// palette, WatchConnectivity messages, pending requests, or receipts.
func pairedObservation(_ element: XCUIElement) throws -> [String: String] {
    let text = try XCTUnwrap(element.value as? String)
    let data = try XCTUnwrap(text.data(using: .utf8))
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])
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
    var value = observation
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
