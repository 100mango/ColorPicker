import Foundation

/// Capture callbacks can arrive after stop/restart. Invalidate synchronously, including
/// before dispatching a slow session stop, and validate again at UI delivery.
public final class CaptureEpoch: @unchecked Sendable {
    private let lock = NSLock()
    private var value: UInt64 = 0
    private var active = false
    public init() {}
    @discardableResult public func begin() -> UInt64 {
        lock.lock(); defer { lock.unlock() }
        value &+= 1; active = true; return value
    }
    public func invalidate() {
        lock.lock(); defer { lock.unlock() }
        value &+= 1; active = false
    }
    public func currentToken() -> UInt64? {
        lock.lock(); defer { lock.unlock() }
        return active ? value : nil
    }
    public func accepts(_ token: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return active && value == token
    }
}
