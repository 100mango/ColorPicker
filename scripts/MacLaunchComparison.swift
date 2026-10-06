// Standalone diagnostic only. Not a product target; no XCTest or AX access.
import AppKit
import CryptoKit
import Darwin
import Security

private let arguments = ["--ui-test-reset", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
private let bundleID = "com.mango.touchColor"
private func now() -> Double { ProcessInfo.processInfo.systemUptime }
private func epoch() -> Double { Date().timeIntervalSince1970 }
private enum Invalid: Error { case contract }
private func require(_ value: Bool) throws { if !value { throw Invalid.contract } }
private func bytes(_ url: URL, limit: Int) throws -> Data {
    let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    try require(values.isRegularFile == true && values.isSymbolicLink == false)
    guard let size = values.fileSize else { throw Invalid.contract }
    try require(size > 0 && size <= limit)
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    let data = try handle.read(upToCount: limit + 1) ?? Data()
    try require(data.count == size)
    return data
}
private func hash(_ url: URL) throws -> String {
    SHA256.hash(data: try bytes(url, limit: 16 * 1024 * 1024)).map { String(format: "%02x", $0) }.joined()
}
private func caller() throws -> [String: Any] {
    var code: SecCode?
    try require(SecCodeCopySelf(SecCSFlags(), &code) == errSecSuccess)
    guard let code else { throw Invalid.contract }
    var staticCode: SecStaticCode?
    try require(SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode) == errSecSuccess)
    guard let staticCode else { throw Invalid.contract }
    let validity = SecCodeCheckValidity(code, SecCSFlags(), nil)
    try require(validity == errSecSuccess || validity == errSecCSUnsigned)
    var information: CFDictionary?
    try require(SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation | kSecCSRequirementInformation), &information) == errSecSuccess)
    guard let info = information as? [String: Any] else { throw Invalid.contract }
    let dictionary = info[kSecCodeInfoEntitlementsDict as String]
    let blob = info[kSecCodeInfoEntitlements as String]
    let state: String
    if dictionary == nil && blob == nil {
        // Requested signing information succeeded and neither representation
        // exists. This is distinct from an API error or an unreadable blob.
        try require(validity == errSecSuccess || info[kSecCodeInfoIdentifier as String] == nil)
        state = "no-embedded-entitlements"
    } else {
        guard validity == errSecSuccess, let entitlements = dictionary as? [String: Any],
              let data = blob as? Data, !data.isEmpty else { throw Invalid.contract }
        if let sandbox = entitlements["com.apple.security.app-sandbox"] {
            try require(CFGetTypeID(sandbox as CFTypeRef) == CFBooleanGetTypeID() && (sandbox as? Bool) == false)
        }
        state = "readable-dictionary"
    }
    return ["inspection": "validated-Security-signing-information", "entitlementsState": state,
            "sandboxEnabled": false, "inheritedSandbox": "not-independently-measured",
            "executableSHA256": try hash(URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath())]
}
private func atomic(_ value: [String: Any], to path: URL) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    try require(data.count <= 16384)
    // Foundation atomic replacement plus file fsync; directory fsync is explicit.
    try data.write(to: path, options: [.atomic])
    let fd = open(path.path, O_RDONLY | O_NOFOLLOW)
    try require(fd >= 0)
    defer { close(fd) }
    try require(fsync(fd) == 0)
    let parent = open(path.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY)
    try require(parent >= 0)
    defer { close(parent) }
    try require(fsync(parent) == 0)
}
private func json(_ url: URL) throws -> [String: Any] {
    guard let result = try JSONSerialization.jsonObject(with: bytes(url, limit: 16384)) as? [String: Any] else { throw Invalid.contract }
    return result
}

// All mutable state and every app operation stays on the main queue. The public
// completion arrives on a concurrent queue and only enqueues an immutable result.
private final class Comparison {
    private let request: [String: Any]
    private let output: URL
    private let latch: URL
    private let deadline: Double
    private let began = now()
    private var stage = "preflight"
    private var receipt: [String: Any]
    private var owned: NSRunningApplication?
    private var ownedPID: pid_t?
    private var signals: [DispatchSourceSignal] = []
    private var callbackDeadline = 0.0
    private var observationDeadline = 0.0
    private var observationScheduled = 0.0
    private var terminationDeadline = 0.0

    init(_ request: [String: Any], _ output: URL, _ latch: URL, _ requestHash: String) throws {
        self.request = request; self.output = output; self.latch = latch
        guard let deadline = request["deadlineMonotonic"] as? Double else { throw Invalid.contract }
        self.deadline = deadline
        try require(deadline > began && deadline <= began + 92)
        receipt = ["schema": 2, "route": "NSWorkspace", "source": request["source"] ?? NSNull(),
            "requestSHA256": requestHash, "status": "unavailable",
            "started": epoch(), "controllerStartedMonotonic": began, "deadlineMonotonic": deadline,
            "launchRequests": 0, "terminateRequests": 0, "preexistingCount": NSNull(),
            "caller": NSNull(), "identity": NSNull(), "callback": NSNull(), "terminated": NSNull(),
            "cleanupConfirmed": false, "reason": "not-started", "operationUncertain": false,
            "requested": NSNull(), "requestedMonotonic": NSNull(), "callbackDeadlineMonotonic": NSNull(),
            "callbackMonotonic": NSNull(), "observationDeadlineMonotonic": NSNull(),
            "observationScheduledMonotonic": NSNull(), "observationEnteredMonotonic": NSNull(),
            "observationLatenessSeconds": NSNull(), "observationComplete": NSNull(),
            "cleanupStartedMonotonic": NSNull(), "terminationRequested": NSNull(),
            "terminationRequestedMonotonic": NSNull(), "terminationDeadlineMonotonic": NSNull(),
            "terminatedMonotonic": NSNull(), "finished": NSNull(), "finishedMonotonic": NSNull()]
    }
    private func persist() throws { try atomic(receipt, to: output) }
    private func fail(_ reason: String) {
        guard stage != "stopped" else { return }
        stage = "stopped"
        // Latch first, then local persistence only. No app reads/operations here.
        let fence: [String: Any] = ["schema": 1, "source": request["source"] ?? NSNull(), "reason": reason, "route": "NSWorkspace"]
        receipt["reason"] = reason; receipt["status"] = "unavailable"
        receipt["operationUncertain"] = true
        if receipt["terminateRequests"] as? Int == 0 {
            receipt["cleanupConfirmed"] = false
        } else {
            receipt["cleanupConfirmed"] = NSNull()
        }
        receipt["finished"] = epoch(); receipt["finishedMonotonic"] = now()
        var fenced = false
        do { try atomic(fence, to: latch); fenced = true } catch { }
        do { try persist() } catch {
            // Atomic replacement may have succeeded before fsync failed. Do
            // not leave an earlier terminal success as the available receipt.
            _ = unlink(output.path)
            let parent = open(output.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY)
            if parent >= 0 { _ = fsync(parent); close(parent) }
            _exit(75)
        }
        exit(fenced ? 74 : 75)
    }
    private func live(_ expected: String, until: Double) -> Bool {
        guard stage == expected else { return false }
        guard now() < min(until, deadline), !FileManager.default.fileExists(atPath: latch.path) else {
            fail("deadline-or-uncertainty-fence"); return false
        }
        return true
    }
    private func verify(_ app: NSRunningApplication, expected: String, until: Double, expectedPID: pid_t? = nil) throws -> pid_t {
        guard let product = request["product"] as? [String: String],
              let path = product["applicationPath"], let executable = product["executable"] else { throw Invalid.contract }
        // Each potentially delayed public property read has phase-specific
        // pre/post fences. Reject each identity field before any next app read.
        guard live(expected, until: until) else { throw Invalid.contract }
        let pid = app.processIdentifier
        guard live(expected, until: until) else { throw Invalid.contract }
        try require(pid > 0)
        if let expectedPID { try require(pid == expectedPID) }
        guard live(expected, until: until) else { throw Invalid.contract }
        let identifier = app.bundleIdentifier
        guard live(expected, until: until) else { throw Invalid.contract }
        try require(identifier == bundleID)
        guard live(expected, until: until) else { throw Invalid.contract }
        let bundleURL = app.bundleURL
        guard live(expected, until: until) else { throw Invalid.contract }
        guard let url = bundleURL else { throw Invalid.contract }
        try require(url.path == path && url.resolvingSymlinksInPath().path == path)
        guard live(expected, until: until) else { throw Invalid.contract }
        let executableURL = app.executableURL
        guard live(expected, until: until) else { throw Invalid.contract }
        guard let actualExecutable = executableURL else { throw Invalid.contract }
        try require(actualExecutable.path == executable && actualExecutable.resolvingSymlinksInPath().path == executable)
        guard live(expected, until: until) else { throw Invalid.contract }
        let terminated = app.isTerminated
        guard live(expected, until: until) else { throw Invalid.contract }
        try require(!terminated)
        try verifyProduct()
        guard live(expected, until: until) else { throw Invalid.contract }
        return pid
    }
    private func verifyProduct() throws {
        guard let product = request["product"] as? [String: String], let path = product["applicationPath"],
              let executable = product["executable"] else { throw Invalid.contract }
        let url = URL(fileURLWithPath: path)
        try require(url.resolvingSymlinksInPath().path == path && path.hasSuffix("/Build/Products/Debug/TouchColor.app"))
        try require(Bundle(url: url)?.bundleIdentifier == bundleID && executable == path + "/Contents/MacOS/TouchColor")
        try require(try hash(URL(fileURLWithPath: executable)) == product["executableSHA256"])
        try require(try hash(url.appendingPathComponent("Contents/MacOS/TouchColor.debug.dylib")) == product["logicSHA256"])
    }
    func start() {
        do {
            try require(Thread.isMainThread && !FileManager.default.fileExists(atPath: latch.path))
            try require(Set(request.keys) == Set(["schema", "source", "product", "token", "suite", "args", "deadlineMonotonic"]))
            try require(request["schema"] as? Int == 1 && request["args"] as? [String] == arguments)
            guard let token = request["token"] as? String, let suite = request["suite"] as? String else { throw Invalid.contract }
            try require(UUID(uuidString: token)?.uuidString == token && suite.hasPrefix("TouchColor.mac-ui."))
            let suiteToken = String(suite.dropFirst("TouchColor.mac-ui.".count))
            try require(UUID(uuidString: suiteToken)?.uuidString == suiteToken && token != suiteToken)
            receipt["caller"] = try caller()
            try verifyProduct()
            try persist()
            for number in [SIGTERM, SIGINT] {
                signal(number, SIG_IGN)
                let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
                source.setEventHandler { [weak self] in self?.fail("controller-interrupted") }
                source.resume(); signals.append(source)
            }
            guard live("preflight", until: deadline - 32) else { return }
            let existing = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            guard live("preflight", until: deadline - 32) else { return }
            receipt["preexistingCount"] = existing.count
            try require(existing.isEmpty)
            try verifyProduct()
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.arguments = arguments
            configuration.environment = ["TOUCHCOLOR_TEST_DEFAULTS": suite, "TOUCHCOLOR_MAC_LIFECYCLE": token]
            configuration.allowsRunningApplicationSubstitution = false
            configuration.promptsUserIfNeeded = false
            // Ordinary documented defaults are checked, never an activation workaround.
            try require(configuration.activates && !configuration.hides && !configuration.createsNewApplicationInstance)
            callbackDeadline = min(began + 60, deadline - 32)
            receipt["launchRequests"] = 1
            receipt["requested"] = epoch(); receipt["requestedMonotonic"] = now()
            receipt["callbackDeadlineMonotonic"] = callbackDeadline
            try persist()
            guard live("preflight", until: callbackDeadline) else { return }
            stage = "callback"
            let url = URL(fileURLWithPath: (request["product"] as! [String: String])["applicationPath"]!)
            NSWorkspace.shared.openApplication(at: url, configuration: configuration) { app, error in
                DispatchQueue.main.async { [weak self] in self?.completed(app, error) }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0, callbackDeadline - now())) { [weak self] in
                guard let self, self.stage == "callback" else { return }
                self.fail("callback-missing-or-late")
            }
        } catch { fail("preflight-unavailable") }
    }
    private func completed(_ app: NSRunningApplication?, _ error: Error?) {
        // A late callback is never inspected for identity or cleanup.
        guard live("callback", until: callbackDeadline) else { return }
        guard error == nil, let app else { fail("callback-error-or-missing-app"); return }
        do {
            let pid = try verify(app, expected: "callback", until: callbackDeadline)
            guard live("callback", until: callbackDeadline) else { return }
            let running = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            guard live("callback", until: callbackDeadline) else { return }
            try require(running.count == 1)
            let registeredPID = running[0].processIdentifier
            guard live("callback", until: callbackDeadline) else { return }
            try require(registeredPID == pid)
            owned = app; ownedPID = pid
            var identity = request["product"] as! [String: String]
            identity["bundle"] = bundleID
            receipt["identity"] = ["product": identity, "pid": Int(pid), "token": request["token"]!, "suite": request["suite"]!, "args": arguments]
            let callback = now()
            receipt["callback"] = epoch(); receipt["callbackMonotonic"] = callback
            guard live("callback", until: callbackDeadline) else { return }
            observationDeadline = callback + 12
            observationScheduled = callback + 10.5
            receipt["observationDeadlineMonotonic"] = observationDeadline
            receipt["observationScheduledMonotonic"] = observationScheduled
            stage = "observing"
            try persist()
            guard live("observing", until: observationDeadline) else { return }
            let observationDelay = max(0, observationScheduled - now())
            DispatchQueue.main.asyncAfter(deadline: .now() + observationDelay) { [weak self] in self?.terminateOwned() }
        } catch { fail("callback-identity-unavailable") }
    }
    private func terminateOwned() {
        // No app/window observation is added during the passive interval.
        guard stage == "observing" else { return }
        let entered = now()
        receipt["observationEnteredMonotonic"] = entered
        receipt["observationLatenessSeconds"] = max(0, entered - observationScheduled)
        receipt["observationComplete"] = entered < observationDeadline
        // Only this passive timer may cross the observation ceiling. Its miss
        // is permanent, but is not an unknown in-flight app call. The one owned
        // cleanup has a separate 20-second reserve inside the original ceiling.
        guard live("observing", until: deadline) else { return }
        guard let app = owned, let expectedPID = ownedPID, expectedPID > 0,
              receipt["identity"] is [String: Any] else { fail("cleanup-identity-missing"); return }
        terminationDeadline = min(entered + 20, deadline)
        receipt["cleanupStartedMonotonic"] = entered
        receipt["terminationDeadlineMonotonic"] = terminationDeadline
        receipt["status"] = "incomplete"
        receipt["reason"] = entered < observationDeadline ? "cleanup-pending" : "observation-scheduling-miss"
        stage = "cleaning-up"
        do {
            try persist()
            guard live("cleaning-up", until: terminationDeadline) else { return }
            _ = try verify(app, expected: "cleaning-up", until: terminationDeadline, expectedPID: expectedPID)
            guard live("cleaning-up", until: terminationDeadline) else { return }
            receipt["terminateRequests"] = 1
            receipt["terminationRequested"] = epoch(); receipt["terminationRequestedMonotonic"] = now()
            try persist()
            guard live("cleaning-up", until: terminationDeadline) else { return }
            stage = "terminating"
            let accepted = app.terminate()
            guard live("terminating", until: terminationDeadline) else { return }
            guard accepted else { fail("termination-not-accepted"); return }
            pollTermination()
        } catch { fail("termination-identity-unavailable") }
    }
    private func pollTermination() {
        guard live("terminating", until: terminationDeadline), let app = owned else { return }
        let terminated = app.isTerminated
        guard live("terminating", until: terminationDeadline) else { return }
        if terminated {
            stage = "finalizing"
            receipt["terminated"] = epoch(); receipt["terminatedMonotonic"] = now()
            receipt["cleanupConfirmed"] = true
            let complete = receipt["observationComplete"] as? Bool == true && receipt["operationUncertain"] as? Bool == false
            receipt["status"] = complete ? "completed" : "incomplete"
            receipt["reason"] = complete ? "process-launch-only-not-window-readiness" : "observation-scheduling-miss"
            receipt["finished"] = epoch(); receipt["finishedMonotonic"] = now()
            do {
                try persist()
                guard now() < terminationDeadline && now() < deadline && !FileManager.default.fileExists(atPath: latch.path) else {
                    fail("completion-persistence-late-or-fenced"); return
                }
                stage = "stopped"
                exit(0)
            } catch { fail("completion-persistence-unavailable") }
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in self?.pollTermination() }
        }
    }
}

do {
    if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "inspect-caller" {
        let data = try JSONSerialization.data(withJSONObject: caller(), options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        exit(0)
    }
    try require(CommandLine.arguments.count == 5 && CommandLine.arguments[1] == "launch-once")
    let request = try json(URL(fileURLWithPath: CommandLine.arguments[2]))
    let controller = try Comparison(request, URL(fileURLWithPath: CommandLine.arguments[3]), URL(fileURLWithPath: CommandLine.arguments[4]), try hash(URL(fileURLWithPath: CommandLine.arguments[2])))
    controller.start()
    withExtendedLifetime(controller) { RunLoop.main.run() }
    exit(74)
} catch { exit(74) }
