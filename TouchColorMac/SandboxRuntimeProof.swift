#if DEBUG
import Foundation
import Darwin

/// Fixed results from the real application process, using only its UI test's fresh
/// synthetic fixture. No external bytes or arbitrary file contents are reported.
struct SandboxRuntimeProof {
    static let json: String? = {
        guard let path = ProcessInfo.processInfo.environment["TOUCHCOLOR_SANDBOX_PROBE_FILE"] else { return nil }
        let home = NSHomeDirectory()
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        var result: [String: Any] = ["uid": Int(geteuid()),
            "homeHasExpectedContainerPath": home.contains("/Containers/com.mango.touchColor/Data"),
            "applicationSupportIsInHome": support.path.hasPrefix(home + "/")]
        let file = URL(fileURLWithPath: path)
        do { _ = try Data(contentsOf: file); result["unselectedReadDenied"] = false }
        catch { result["unselectedReadDenied"] = true; result["readErrorDomain"] = (error as NSError).domain; result["readErrorCode"] = (error as NSError).code }
        do { try Data("TouchColor synthetic app write probe".utf8).write(to: file); result["unselectedWriteDenied"] = false }
        catch { result["unselectedWriteDenied"] = true; result["writeErrorDomain"] = (error as NSError).domain; result["writeErrorCode"] = (error as NSError).code }
        let local = support.appendingPathComponent("TouchColor-sandbox-proof-\(UUID()).txt")
        defer { try? FileManager.default.removeItem(at: local) }
        do {
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            let bytes = Data("TouchColor synthetic container roundtrip".utf8)
            try bytes.write(to: local); result["containerRoundTrip"] = try Data(contentsOf: local) == bytes
        } catch { result["containerRoundTrip"] = false; result["containerErrorCode"] = (error as NSError).code }
        guard let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]) else { return nil }
        return String(data: data, encoding: .utf8)
    }()
}
#endif
