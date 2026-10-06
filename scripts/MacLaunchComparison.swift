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
    private var terminationDeadline = 0.0

    init(_ request: [String: Any], _ output: URL, _ latch: URL, _ requestHash: String) throws {
        self.request = request; self.output = output; self.latch = latch
        guard let deadline = request["deadlineMonotonic"] as? Double else { throw Invalid.contract }
        self.deadline = deadline
        try require(deadline > began && deadline <= began + 92)
        receipt = ["schema": 1, "route": "NSWorkspace", "source": request["source"] ?? NSNull(),
            "requestSHA256": requestHash, "status": "unavailable",
            "started": epoch(), "controllerStartedMonotonic": began, "deadlineMonotonic": deadline,
            "launchRequests": 0, "terminateRequests": 0, "preexistingCount": NSNull(),
            "caller": NSNull(), "identity": NSNull(), "callback": NSNull(), "terminated": NSNull(),
            "cleanupConfirmed": false, "reason": "not-started"]
    }
    private func persist() throws { try atomic(receipt, to: output) }
    private func fail(_ reason: String) {
        guard stage != "stopped" else { return }
        stage = "stopped"
        // Latch first, then local persistence only. No app reads/operations here.
        let fence: [String: Any] = ["schema": 1, "source": request["source"] ?? NSNull(), "reason": reason, "route": "NSWorkspace"]
        do { try atomic(fence, to: latch) } catch { _exit(75) }
        receipt["reason"] = reason; receipt["status"] = "unavailable"
        receipt["finished"] = epoch(); receipt["finishedMonotonic"] = now()
        try? persist()
        exit(74)
    }
    private func live(_ expected: String, until: Double) -> Bool {
        guard stage == expected else { return false }
        guard now() < min(until, deadline), !FileManager.default.fileExists(atPath: latch.path) else {
            fail("deadline-or-uncertainty-fence"); return false
        }
        return true
    }
    private func verify(_ app: NSRunningApplication, expected: String, until: Double) throws -> pid_t {
        guard let product = request["product"] as? [String: String],
              let path = product["applicationPath"], let executable = product["executable"] else { throw Invalid.contract }
        // Each potentially delayed public property read has an original-phase
        // pre/post fence; a late return cannot lead into the next app query.
        guard live(expected, until: until) else { throw Invalid.contract }
        let pid = app.processIdentifier
        guard live(expected, until: until) else { throw Invalid.contract }
        let identifier = app.bundleIdentifier
        guard live(expected, until: until) else { throw Invalid.contract }
        let bundleURL = app.bundleURL
        guard live(expected, until: until) else { throw Invalid.contract }
        let executableURL = app.executableURL
        guard live(expected, until: until) else { throw Invalid.contract }
        let terminated = app.isTerminated
        guard live(expected, until: until) else { throw Invalid.contract }
        guard let url = bundleURL, let actualExecutable = executableURL else { throw Invalid.contract }
        try require(pid > 0 && identifier == bundleID && !terminated)
        try require(url.path == path && url.resolvingSymlinksInPath().path == path)
        try require(actualExecutable.path == executable && actualExecutable.resolvingSymlinksInPath().path == executable)
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
            receipt["callback"] = epoch(); receipt["callbackMonotonic"] = now()
            guard live("callback", until: callbackDeadline) else { return }
            observationDeadline = min(now() + 12, deadline - 20)
            receipt["observationDeadlineMonotonic"] = observationDeadline
            stage = "observing"
            try persist()
            guard live("observing", until: observationDeadline) else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0, observationDeadline - now() - 0.5)) { [weak self] in self?.terminateOwned() }
        } catch { fail("callback-identity-unavailable") }
    }
    private func terminateOwned() {
        // No app/window observation is added during the passive interval.
        guard stage == "observing" else { return }
        guard now() < deadline - 0.05, !FileManager.default.fileExists(atPath: latch.path) else { fail("observation-late"); return }
        guard now() < observationDeadline, let app = owned else { fail("observation-late"); return }
        do {
            let pid = try verify(app, expected: "observing", until: observationDeadline)
            try require(pid == ownedPID)
            guard now() < observationDeadline, !FileManager.default.fileExists(atPath: latch.path) else { fail("termination-late"); return }
            terminationDeadline = min(now() + 20, deadline)
            receipt["terminateRequests"] = 1
            receipt["terminationRequested"] = epoch(); receipt["terminationRequestedMonotonic"] = now()
            receipt["terminationDeadlineMonotonic"] = terminationDeadline
            try persist()
            guard now() < observationDeadline && now() < terminationDeadline else { fail("termination-late"); return }
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
            stage = "stopped"
            receipt["terminated"] = epoch(); receipt["terminatedMonotonic"] = now()
            receipt["cleanupConfirmed"] = true; receipt["status"] = "completed"
            receipt["reason"] = "process-launch-only-not-window-readiness"
            receipt["finished"] = epoch(); receipt["finishedMonotonic"] = now()
            do {
                try persist()
                guard now() < terminationDeadline && now() < deadline else {
                    stage = "persist-late"; fail("completion-persistence-late"); return
                }
                exit(0)
            } catch { stage = "persist-failed"; fail("completion-persistence-unavailable") }
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
