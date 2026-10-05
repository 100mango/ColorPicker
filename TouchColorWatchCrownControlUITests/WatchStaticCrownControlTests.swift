#if DEBUG
import XCTest

/// Independent control; neither a product Home test nor an RGB input test.
final class WatchStaticCrownControlTests: XCTestCase {
    private static let caseID = "WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations"
    private static let maxNodes = 256
    private static let maxRows = 12
    private static let maxFrameBytes = 1536
    private static let maxSummaryBytes = 2048
    private static let maxStructuredBytes = 16 * 1024
    private var app: XCUIApplication!
    private var interruption: NSObjectProtocol?
    private var crownSnapshots = 0, touchSnapshots = 0, crownCalls = 0, touchCalls = 0
    private var structuredBytes = 0, emittedFrames = 0, omittedFrames = 0, omittedRows = 0
    private var omittedSubtreeRoots = 0, snapshotErrors = 0
    private var crownStatus = "not_started", touchStatus = "not_attempted", failureReason = "none"

    private enum ControlError: String, Error {
        case startup, productStillRunning, topPrecondition, targetPrecondition, geometry, snapshot, budget, liveGeometry
    }
    private enum Movement { case stationary, downward, unclassified }
    private struct Frame {
        let viewport: CGRect
        let list: CGRect
        let navigation: CGRect
        let rows: [Int: CGRect]
        let complete: Bool
    }

    override func setUpWithError() throws {
        try super.setUpWithError()
        continueAfterFailure = false
        executionTimeAllowance = 120
        interruption = addUIInterruptionMonitor(withDescription: "Abort unhandled static-control interruption") { _ in
            // Never query/tap an alert or return false into XCTest's default handlers.
            print("WATCH_STATIC_CROWN_ABORT {\"crownStatus\":\"inconclusive\",\"touchStatus\":\"aborted\",\"reason\":\"unexpected_interruption\"}")
            fatalError("WATCH_STATIC_CROWN_FAIL_CLOSED; no alert action taken")
        }
        app = XCUIApplication(bundleIdentifier: "com.mango.touchColor.watchCrownControl")
    }

    override func tearDownWithError() throws {
        app?.terminate()
        if let interruption { removeUIInterruptionMonitor(interruption) }
        interruption = nil
        try super.tearDownWithError()
    }

    private func valid(_ r: CGRect) -> Bool {
        [r.origin.x, r.origin.y, r.size.width, r.size.height, r.maxX, r.maxY].allSatisfy { $0.isFinite }
            && r.width > 0 && r.height > 0
    }
    private func rect(_ r: CGRect) -> TCStaticRect {
        TCStaticRect(x: Double(r.origin.x), y: Double(r.origin.y), width: Double(r.width), height: Double(r.height))
    }
    private func array(_ r: CGRect) -> [Double] {
        // Invalid geometry is recorded as an empty array and cannot qualify a pass/gesture.
        guard valid(r) else { return [] }
        return [Double(r.origin.x), Double(r.origin.y), Double(r.width), Double(r.height)]
    }
    private func same(_ a: CGRect, _ b: CGRect) -> Bool {
        valid(a) && valid(b) && abs(a.minX-b.minX) <= 0.5 && abs(a.minY-b.minY) <= 0.5
            && abs(a.width-b.width) <= 0.5 && abs(a.height-b.height) <= 0.5
    }
    private func movement(_ before: Frame, _ after: Frame) -> Movement {
        guard before.complete, after.complete, same(before.viewport, after.viewport), same(before.list, after.list),
              same(before.navigation, after.navigation) else {
            return .unclassified
        }
        let shared = Set(before.rows.keys).intersection(after.rows.keys)
        for id in shared {
            guard let a = before.rows[id], let b = after.rows[id],
                  a.intersects(before.viewport) || b.intersects(after.viewport) else { continue }
            if abs(a.minX-b.minX) <= 0.5 && abs(a.width-b.width) <= 0.5 && abs(a.height-b.height) <= 0.5
                && b.minY < a.minY - 1 { return .downward }
        }
        if Set(before.rows.keys) == Set(after.rows.keys), same(before.navigation, after.navigation),
           shared.allSatisfy({ same(before.rows[$0]!, after.rows[$0]!) }) { return .stationary }
        return .unclassified
    }

    @MainActor private func capture(_ phase: String, touch: Bool = false) throws -> Frame {
        if touch {
            guard touchSnapshots < 2 else { throw ControlError.budget }
            touchSnapshots += 1
        } else {
            guard crownSnapshots < 6 else { throw ControlError.budget }
            crownSnapshots += 1
        }
        let started = ProcessInfo.processInfo.systemUptime
        let root: any XCUIElementSnapshot
        do { root = try app.snapshot() }
        catch { snapshotErrors += 1; throw ControlError.snapshot }
        // The public snapshot itself is OS-owned. Bounds cover traversal, retained
        // nodes/rows and serialized observations, not undocumented OS allocation.
        var pending: [(any XCUIElementSnapshot, Bool)] = [(root, false)]
        var visited = 0, pruned = 0, rowDrops = 0, duplicateRows = 0, invalidRows = 0
        var listCount = 0, navigationCount = 0, backButtons = 0, omittedIdentityCharacters = 0
        var listIdentifier = "", navigationIdentifier = "", navigationTitle = ""
        var listIdentityMatches = false, navigationIdentityMatches = false
        var list = CGRect.zero, navigation = CGRect.zero
        var rows: [Int: CGRect] = [:]
        while visited < Self.maxNodes, let (element, inList) = pending.popLast() {
            visited += 1
            let isList = element.elementType == .collectionView
            if isList {
                listCount += 1
                if listCount == 1 {
                    list = element.frame
                    listIdentityMatches = element.identifier == "static.list"
                    listIdentifier = String(element.identifier.prefix(64))
                    omittedIdentityCharacters += max(0, element.identifier.count - 64)
                }
            }
            if element.elementType == .button && element.identifier == "BackButton" { backButtons += 1 }
            if element.elementType == .navigationBar {
                navigationCount += 1
                if navigationCount == 1 {
                    navigation = element.frame
                    navigationIdentityMatches = element.identifier == "Crown Control" || element.label == "Crown Control"
                    navigationIdentifier = String(element.identifier.prefix(64))
                    navigationTitle = String(element.label.prefix(64))
                    omittedIdentityCharacters += max(0, element.identifier.count - 64) + max(0, element.label.count - 64)
                }
            }
            if inList && element.elementType == .button && element.identifier.hasPrefix("static.row.") {
                let suffix = element.identifier.dropFirst("static.row.".count)
                if let index = Int(suffix), (0..<12).contains(index), element.identifier == "static.row.\(index)" {
                    if rows[index] != nil { duplicateRows += 1 }
                    else if rows.count >= Self.maxRows { rowDrops += 1 }
                    else if !valid(element.frame) { invalidRows += 1 }
                    else { rows[index] = element.frame }
                } else { invalidRows += 1 }
            }
            let children = element.children
            let available = max(0, Self.maxNodes - visited - pending.count)
            let retained = min(children.count, available)
            pruned += children.count - retained
            for child in children.prefix(retained).reversed() { pending.append((child, inList || isList)) }
        }
        pruned += pending.count
        omittedSubtreeRoots += pruned
        let complete = pruned == 0 && rowDrops == 0 && duplicateRows == 0 && invalidRows == 0
            && listCount == 1 && navigationCount == 1 && listIdentityMatches && navigationIdentityMatches
            && backButtons == 0 && omittedIdentityCharacters == 0 && valid(root.frame) && valid(list)
            && valid(navigation) && !rows.isEmpty
        let frame = Frame(viewport: root.frame, list: list, navigation: navigation, rows: rows, complete: complete)
        var printedRows: [[String: Any]] = rows.keys.sorted().map { ["id": $0, "frame": array(rows[$0]!)] }
        var payload: [String: Any] = ["case": Self.caseID, "phase": phase,
            "runnerPID": ProcessInfo.processInfo.processIdentifier, "uptime": started,
            "snapshotMilliseconds": Int((ProcessInfo.processInfo.systemUptime-started)*1000),
            "viewport": array(root.frame), "list": array(list), "navigation": array(navigation),
            "listCount": listCount, "navigationCount": navigationCount, "nodesVisited": visited,
            "listIdentifier": listIdentifier, "navigationIdentifier": navigationIdentifier, "navigationTitle": navigationTitle,
            "backButtons": backButtons, "omittedIdentityCharacters": omittedIdentityCharacters,
            "geometryComplete": complete, "omittedSubtreeRoots": pruned,
            "omittedDescendantsUnknown": pruned > 0, "duplicateRows": duplicateRows, "invalidRows": invalidRows]
        var byteDrops = 0
        var data = Data()
        while true {
            payload["rows"] = printedRows
            payload["omittedRows"] = rowDrops + byteDrops
            let candidate = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            if candidate.count <= Self.maxFrameBytes { data = candidate; break }
            guard !printedRows.isEmpty else { omittedFrames += 1; throw ControlError.budget }
            printedRows.removeLast(); byteDrops += 1
            payload["geometryComplete"] = false
        }
        omittedRows += rowDrops + byteDrops
        guard structuredBytes + data.count <= Self.maxStructuredBytes - Self.maxSummaryBytes else {
            omittedFrames += 1; throw ControlError.budget
        }
        structuredBytes += data.count; emittedFrames += 1
        print("WATCH_STATIC_CROWN_FRAME " + String(decoding: data, as: UTF8.self)); fflush(stdout)
        return Frame(viewport: frame.viewport, list: frame.list, navigation: frame.navigation,
                     rows: frame.rows, complete: frame.complete && byteDrops == 0)
    }

    @MainActor private func validateTop(_ frame: Frame) throws {
        var content = TCStaticRect()
        guard frame.complete, TCStaticContent(rect(frame.viewport), rect(frame.list), rect(frame.navigation), &content) != 0,
              let first = frame.rows[0], TCStaticContains(content, rect(first)) != 0,
              first.minY - CGFloat(content.y) <= 12,
              app.buttons["static.row.0"].isHittable, !app.buttons["BackButton"].exists else {
            throw ControlError.topPrecondition
        }
        let target = app.buttons["static.row.11"]
        guard !(target.exists && target.isHittable),
              frame.rows[11].map({ !$0.intersects(frame.viewport) }) ?? true else {
            throw ControlError.targetPrecondition
        }
    }

    @MainActor private func touchControl(after finalCrown: Frame) throws {
        touchStatus = "checking_geometry"
        let before = try capture("touch.before", touch: true)
        guard movement(finalCrown, before) == .stationary else {
            touchStatus = "not_attempted_geometry_changed"; return
        }
        var plan = TCStaticDrag()
        guard before.complete, TCStaticPlan(rect(before.viewport), rect(before.list), rect(before.navigation), &plan) != 0 else {
            touchStatus = "not_attempted_invalid_geometry"; return
        }
        let lists = app.collectionViews, bars = app.navigationBars
        guard app.state == .runningForeground, lists.count == 1, bars.count == 1 else { throw ControlError.liveGeometry }
        let list = lists.element(boundBy: 0), bar = bars.element(boundBy: 0)
        guard list.identifier == "static.list", (bar.identifier == "Crown Control" || bar.label == "Crown Control"), list.isHittable,
              app.frame == before.viewport, list.frame == before.list, bar.frame == before.navigation,
              !app.buttons["BackButton"].exists else { throw ControlError.liveGeometry }
        let origin = list.coordinate(withNormalizedOffset: .zero)
        let start = origin.withOffset(CGVector(dx: CGFloat(plan.start.x)-before.list.minX, dy: CGFloat(plan.start.y)-before.list.minY))
        let end = origin.withOffset(CGVector(dx: CGFloat(plan.end.x)-before.list.minX, dy: CGFloat(plan.end.y)-before.list.minY))
        // Recheck the live public geometry immediately before the sole native gesture.
        guard start.screenPoint == CGPoint(x: CGFloat(plan.start.x), y: CGFloat(plan.start.y)),
              end.screenPoint == CGPoint(x: CGFloat(plan.end.x), y: CGFloat(plan.end.y)),
              app.state == .runningForeground, app.frame == before.viewport,
              lists.count == 1, bars.count == 1, list.frame == before.list, bar.frame == before.navigation,
              list.isHittable else { throw ControlError.liveGeometry }
        touchCalls += 1
        start.press(forDuration: 0.01, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)
        let after = try capture("touch.after", touch: true)
        switch movement(before, after) {
        case .downward: touchStatus = "moved_downward"
        case .stationary: touchStatus = "stationary"
        case .unclassified: touchStatus = "inconclusive_geometry_changed"
        }
    }

    private func emitResult() throws {
        var payload: [String: Any] = ["case": Self.caseID, "crownStatus": crownStatus, "touchStatus": touchStatus,
            "crownCalls": crownCalls, "delta": -0.1, "crownSnapshots": crownSnapshots, "touchSnapshots": touchSnapshots,
            "touchCalls": touchCalls, "emittedFrames": emittedFrames, "failureReason": failureReason,
            "omittedFrames": omittedFrames, "omittedRows": omittedRows, "omittedSubtreeRoots": omittedSubtreeRoots,
            "omittedDescendantsUnknown": omittedSubtreeRoots > 0, "snapshotErrors": snapshotErrors,
            "maxStructuredBytes": Self.maxStructuredBytes, "frameBytes": structuredBytes,
            "touchCanSatisfyCrown": false, "productHomeAcceptance": "unchanged", "structuredBytes": 0]
        var data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        // Fixed point includes the final result JSON itself in the stated byte total.
        for _ in 0..<4 {
            payload["structuredBytes"] = structuredBytes + data.count
            data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        }
        guard data.count <= Self.maxSummaryBytes, structuredBytes + data.count <= Self.maxStructuredBytes else {
            throw ControlError.budget
        }
        structuredBytes += data.count
        print("WATCH_STATIC_CROWN_RESULT " + String(decoding: data, as: UTF8.self)); fflush(stdout)
    }

    @MainActor func testStaticListDigitalCrownThreeRotations() throws {
        do {
            // Read-only admission check: the real product must already be inactive.
            guard XCUIApplication(bundleIdentifier: "com.mango.touchColor.watchkitapp").state == .notRunning else {
                throw ControlError.productStillRunning
            }
            app.launchArguments = ["-AppleLanguages", "(en)"]
            app.launch()
            guard app.buttons["static.row.0"].waitForExistence(timeout: 15) else { throw ControlError.startup }
            var first: Frame?, last: Frame?
            var moved = false, stationary = true
            for attempt in 0..<3 {
                let before = try capture("crown.\(attempt).before")
                if attempt == 0 { try validateTop(before); first = before }
                guard before.complete else { throw ControlError.geometry }
                XCUIDevice.shared.rotateDigitalCrown(delta: -0.1)
                crownCalls += 1
                let after = try capture("crown.\(attempt).after")
                guard after.complete else { throw ControlError.geometry }
                switch movement(before, after) {
                case .downward: moved = true; stationary = false
                case .stationary: break
                case .unclassified: stationary = false
                }
                if let first, movement(first, after) == .downward { moved = true }
                if let last, movement(last, before) != .stationary { stationary = false }
                last = after
            }
            crownStatus = moved ? "moved_downward" : (stationary ? "stationary" : "inconclusive_geometry_changed")
            // Freeze the Crown result before the optional, separately labeled touch control.
            if crownStatus == "stationary", let last { try touchControl(after: last) }
        } catch {
            failureReason = (error as? ControlError)?.rawValue ?? "serialization"
            if crownStatus == "not_started" { crownStatus = "inconclusive" }
            if touchStatus == "checking_geometry" { touchStatus = "inconclusive" }
        }
        try emitResult()
        // A successful touch drag NEVER satisfies or rewrites this Crown assertion.
        XCTAssertEqual(crownCalls, 3, "The independent control requires exactly three Crown events")
        XCTAssertEqual(crownStatus, "moved_downward", "Static List Crown result failed; inspect the separate touch status")
        XCTAssertEqual(failureReason, "none", "Incomplete diagnostic observations cannot qualify this control")
    }
}
#else
#error("The isolated Crown UI control is DEBUG-only.")
#endif
