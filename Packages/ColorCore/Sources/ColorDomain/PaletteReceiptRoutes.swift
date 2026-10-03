import Foundation

/// Ephemeral routing authority for a single active companion session. Persisted inbox
/// items deliberately carry no delivery authority across activation or app relaunch.
public final class PaletteReceiptRoutes: @unchecked Sendable {
    private let lock = NSRecursiveLock()
    private var epoch: UInt64 = 0
    private var active = false
    private var routes: [UUID: UInt64] = [:]
    private let maximumRoutes: Int
    public init(maximumRoutes: Int = 16) { self.maximumRoutes = max(1, maximumRoutes) }
    @discardableResult public func activate() -> UInt64 {
        lock.lock(); defer { lock.unlock() }
        epoch &+= 1; active = true; routes.removeAll(); return epoch
    }
    public func invalidate() {
        lock.lock(); defer { lock.unlock() }
        epoch &+= 1; active = false; routes.removeAll()
    }
    public func currentEpoch() -> UInt64? {
        lock.lock(); defer { lock.unlock() }; return active ? epoch : nil
    }
    public func isCurrent(_ admittedEpoch: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }; return active && epoch == admittedEpoch
    }
    /// Call only after the complete message was validated and durably admitted by the inbox.
    @discardableResult public func admit(_ requestID: UUID, epoch admittedEpoch: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard active, epoch == admittedEpoch,
              routes[requestID] != nil || routes.count < maximumRoutes else { return false }
        routes[requestID] = admittedEpoch; return true
    }
    /// Serialize the short transport-enqueue operation with synchronous invalidation.
    /// A failed/lost send requires another same-UUID request to establish a fresh route.
    @discardableResult public func deliver(_ requestID: UUID, enqueue: () -> Void) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard active, routes.removeValue(forKey: requestID) == epoch else { return false }
        enqueue(); return true
    }
}
