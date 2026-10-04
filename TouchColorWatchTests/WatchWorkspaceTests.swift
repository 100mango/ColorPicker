import XCTest
import SwiftUI
import Foundation
import Combine
import ColorDomain
import ColorRaster
import ColorPaletteLegacy
@testable import TouchColorWatch

@MainActor final class WatchWorkspaceTests: XCTestCase {
    func testReceiptWithoutPendingFileRecoversOnlyItsExactQueuedPayloadAfterRelaunch() throws {
        final class Queued: WatchQueuedPaletteRequest {
            let userInfo: [String: Any]
            var cancellations = 0
            init(_ userInfo: [String: Any]) { self.userInfo = userInfo }
            func cancel() { cancellations += 1 }
        }
        let outcomes: [PaletteTransferReceipt.Outcome] = [.accepted, .rejected]
        for outcome in outcomes {
            for pendingMode in 0..<3 {
                let hasNewPending = pendingMode != 0
                let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-receipt-queue-\(UUID())")
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                defer { try? FileManager.default.removeItem(at: directory) }
                let completed = try PaletteTransfer(colors: [RGBColor(hex: "#123456")!])
                let receipt = PaletteTransferReceipt(requestID: completed.id, fingerprint: try PaletteFingerprint.of(completed), outcome: outcome)
                let receiptBytes = try receipt.encoded()
                let receiptFile = directory.appendingPathComponent("last-color-transfer-receipt.json")
                try receiptBytes.write(to: receiptFile)
                let matching = Queued(["requestID": completed.id.uuidString, "touchColorPaletteV1": try completed.encoded()])
                let conflict = try PaletteTransfer(id: completed.id, colors: [RGBColor(hex: "#abcdef")!])
                let conflicting = Queued(["requestID": completed.id.uuidString, "touchColorPaletteV1": try conflict.encoded()])
                let malformed = Queued(["requestID": completed.id.uuidString, "touchColorPaletteV1": Data([1])])
                let otherProtocol = Queued(["requestID": completed.id.uuidString, "unrelated": Data([1])])
                let next = try PaletteTransfer(id: pendingMode == 2 ? completed.id : UUID(), colors: [RGBColor(hex: "#778899")!])
                let nextBytes = try next.encoded()
                let newer = Queued(["requestID": next.id.uuidString, "touchColorPaletteV1": nextBytes])
                let pendingFile = directory.appendingPathComponent("pending-color-transfer.json")
                if hasNewPending { try nextBytes.write(to: pendingFile) }
                let model = WatchTransfer(directory: directory, activate: false,
                    queuedRequests: { [matching, matching, conflicting, malformed, otherProtocol, newer] })
                let status = model.status
                XCTAssertEqual(model.lastReceipt, receipt)
                XCTAssertEqual(model.pending, hasNewPending ? next : nil)
                model.reconcileSavedOutcomes()
                XCTAssertEqual(matching.cancellations, 1)
                XCTAssertEqual(conflicting.cancellations, 0); XCTAssertEqual(malformed.cancellations, 0)
                XCTAssertEqual(otherProtocol.cancellations, 0); XCTAssertEqual(newer.cancellations, 0)
                XCTAssertEqual(model.status, status)
                XCTAssertEqual(model.pending, hasNewPending ? next : nil)
                // The cancelled queue may report completion after this recovery.
                // A conflicting same-UUID payload must not change the new status.
                model.completeQueuedRequest(completed, error: nil)
                XCTAssertEqual(model.status, status)
                XCTAssertEqual(model.pending, hasNewPending ? next : nil)
                XCTAssertEqual(try Data(contentsOf: receiptFile), receiptBytes)
                if hasNewPending { XCTAssertEqual(try Data(contentsOf: pendingFile), nextBytes) }
                else { XCTAssertFalse(FileManager.default.fileExists(atPath: pendingFile.path)) }
            }
        }
    }
    func testCancelAfterRelaunchCancelsOnlyMatchingPersistedProtocolRequests() throws {
        final class Queued: WatchQueuedPaletteRequest {
            let userInfo: [String: Any]
            var cancellations = 0
            init(_ userInfo: [String: Any]) { self.userInfo = userInfo }
            func cancel() { cancellations += 1 }
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-queue-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let original = WatchTransfer(directory: directory, activate: false)
        original.request([RGBColor(hex: "#123456")!])
        let request = try XCTUnwrap(original.pending)
        let matching = Queued(["requestID": request.id.uuidString, "touchColorPaletteV1": try request.encoded()])
        let other = Queued(["requestID": UUID().uuidString, "touchColorPaletteV1": try request.encoded()])
        let otherProtocol = Queued(["requestID": request.id.uuidString, "unrelated": Data([1])])
        let malformed = Queued(["requestID": request.id.uuidString, "touchColorPaletteV1": Data([1])])
        let conflicting = Queued(["requestID": request.id.uuidString,
            "touchColorPaletteV1": try PaletteTransfer(colors: [RGBColor(hex: "#abcdef")!]).encoded()])
        let reopened = WatchTransfer(directory: directory, activate: false,
            queuedRequests: { [matching, matching, other, otherProtocol, malformed, conflicting] })
        XCTAssertEqual(reopened.pending, request)
        reopened.cancel()
        XCTAssertEqual(matching.cancellations, 1)
        XCTAssertEqual(other.cancellations, 0); XCTAssertEqual(otherProtocol.cancellations, 0)
        XCTAssertEqual(malformed.cancellations, 0); XCTAssertEqual(conflicting.cancellations, 0)
        XCTAssertNil(reopened.pending)
        XCTAssertNil(WatchTransfer(directory: directory, activate: false).pending)
        reopened.cancel(); XCTAssertEqual(matching.cancellations, 1)
        // Simulate a crash between the durable tombstone and payload removal.
        try request.encoded().write(to: directory.appendingPathComponent("pending-color-transfer.json"), options: .atomic)
        let queuedAfterRestart = Queued(matching.userInfo)
        let recovered = WatchTransfer(directory: directory, activate: false,
            queuedRequests: { [queuedAfterRestart, other, otherProtocol] })
        XCTAssertNil(recovered.pending)
        recovered.reconcileCancelledRequests()
        XCTAssertEqual(queuedAfterRestart.cancellations, 1)
        XCTAssertEqual(other.cancellations, 0); XCTAssertEqual(otherProtocol.cancellations, 0)
        let late = PaletteTransferReceipt(requestID: request.id, fingerprint: try PaletteFingerprint.of(request), outcome: .accepted)
        recovered.receiveReceipt(try late.encoded())
        XCTAssertNil(recovered.pending); XCTAssertNil(recovered.lastReceipt)
        recovered.request([RGBColor(hex: "#abcdef")!])
        let next = try XCTUnwrap(recovered.pending)
        recovered.receiveReceipt(try late.encoded()); XCTAssertEqual(recovered.pending, next)
    }
    func testCancelledStatusSurvivesOlderReceiptAndLaterAcceptanceStillWorks() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-receipt-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = WatchTransfer(directory: directory, activate: false)
        model.request([RGBColor(hex: "#112233")!])
        let first = try XCTUnwrap(model.pending)
        let firstReceipt = PaletteTransferReceipt(requestID: first.id, fingerprint: try PaletteFingerprint.of(first), outcome: .accepted)
        model.receiveReceipt(try firstReceipt.encoded())
        model.request([RGBColor(hex: "#445566")!]); model.cancel()
        let cancelled = WatchTransfer(directory: directory, activate: false)
        XCTAssertNil(cancelled.pending); XCTAssertEqual(cancelled.lastReceipt, firstReceipt)
        XCTAssertEqual(cancelled.status, NSLocalizedString("Transfer cancelled. If it already arrived, review it on iPhone.", comment: "Watch transfer status"))
        cancelled.request([RGBColor(hex: "#778899")!])
        let next = try XCTUnwrap(cancelled.pending)
        let receipt = PaletteTransferReceipt(requestID: next.id, fingerprint: try PaletteFingerprint.of(next), outcome: .accepted)
        cancelled.receiveReceipt(try receipt.encoded())
        let accepted = WatchTransfer(directory: directory, activate: false)
        XCTAssertNil(accepted.pending); XCTAssertEqual(accepted.lastReceipt, receipt)
        XCTAssertEqual(accepted.status, NSLocalizedString("Accepted on iPhone.", comment: "Transfer receipt"))
    }
    func testMalformedCancellationJournalIsRetainedAndBlocksNewAdmission() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-corrupt-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("cancelled-color-transfers.json"), bytes = Data("incomplete cancellation journal".utf8)
        try bytes.write(to: file)
        let model = WatchTransfer(directory: directory, activate: false)
        model.request([RGBColor(hex: "#123456")!])
        XCTAssertNil(model.pending); XCTAssertEqual(try Data(contentsOf: file), bytes)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("pending-color-transfer.json").path))
    }
    func testFullCancellationHistoryNeverDropsRecordsOrThePendingRequest() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-full-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let ids = (0..<4096).map { _ in UUID().uuidString }
        let bytes = try JSONSerialization.data(withJSONObject: ["version": 1, "requestIDs": ids])
        let journal = directory.appendingPathComponent("cancelled-color-transfers.json")
        try bytes.write(to: journal)
        // No activated queue snapshot: absence of a session must not authorize
        // forgetting durable platform transfers from a previous process.
        let model = WatchTransfer(directory: directory, activate: false)
        model.request([RGBColor(hex: "#123456")!])
        let pending = try XCTUnwrap(model.pending)
        model.cancel()
        XCTAssertEqual(model.pending, pending)
        XCTAssertEqual(try Data(contentsOf: journal), bytes)
        XCTAssertEqual(WatchTransfer(directory: directory, activate: false).pending, pending)
        XCTAssertEqual(model.status, NSLocalizedString("The cancellation history is full. The pending transfer was kept.", comment: "Watch transfer error"))
    }
    func testFullCancellationHistoryRecoversOnlyAfterSettledQueueConfirmation() throws {
        final class Queued: WatchQueuedPaletteRequest {
            let userInfo: [String: Any]
            var cancellations = 0
            init(_ id: UUID) { userInfo = ["requestID": id.uuidString] }
            func cancel() { cancellations += 1 }
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-settled-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let ids = (0..<4096).map { _ in UUID() }
        let journal = directory.appendingPathComponent("cancelled-color-transfers.json")
        let bytes = try JSONSerialization.data(withJSONObject: ["version": 1, "requestIDs": ids.map(\.uuidString), "lastCancelledID": ids.last!.uuidString])
        try bytes.write(to: journal)
        let outstanding = ids.map(Queued.init)
        var snapshot: [WatchQueuedPaletteRequest] = outstanding
        let model = WatchTransfer(directory: directory, activate: false, queuedRequests: { snapshot })
        model.request([RGBColor(hex: "#123456")!])
        let pending = try XCTUnwrap(model.pending)
        model.cancel()
        XCTAssertEqual(model.pending, pending); XCTAssertEqual(try Data(contentsOf: journal), bytes)
        XCTAssertTrue(outstanding.allSatisfy { $0.cancellations == 0 })
        // Every other request is now confirmed absent from the platform queue.
        // One unresolved entry and the last visible cancellation remain protected.
        snapshot = [outstanding[0]]
        model.cancel()
        XCTAssertNil(model.pending)
        let value = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: journal)) as? [String: Any])
        XCTAssertEqual(value["requestIDs"] as? [String], [ids[0].uuidString, ids.last!.uuidString, pending.id.uuidString])
        XCTAssertEqual(value["lastCancelledID"] as? String, pending.id.uuidString)
        let reopened = WatchTransfer(directory: directory, activate: false, queuedRequests: { snapshot })
        XCTAssertNil(reopened.pending)
        XCTAssertEqual(reopened.status, NSLocalizedString("Transfer cancelled. If it already arrived, review it on iPhone.", comment: "Watch transfer status"))
        let removed = try PaletteTransfer(id: ids[1], colors: [RGBColor(hex: "#abcdef")!])
        let late = PaletteTransferReceipt(requestID: removed.id, fingerprint: try PaletteFingerprint.of(removed), outcome: .accepted)
        reopened.receiveReceipt(try late.encoded())
        XCTAssertNil(reopened.pending); XCTAssertNil(reopened.lastReceipt)
        reopened.request([RGBColor(hex: "#778899")!])
        let next = try XCTUnwrap(reopened.pending)
        reopened.receiveReceipt(try late.encoded()); XCTAssertEqual(reopened.pending, next)
        XCTAssertEqual(outstanding[0].cancellations, 0)
    }
    func testCompactionCannotDiscardAnUnreadableOrReplacedPendingFile() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-cancel-unreadable-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let journal = directory.appendingPathComponent("cancelled-color-transfers.json")
        let bytes = try JSONSerialization.data(withJSONObject: ["version": 1, "requestIDs": (0..<4096).map { _ in UUID().uuidString }])
        try bytes.write(to: journal)
        let model = WatchTransfer(directory: directory, activate: false, queuedRequests: { [] })
        model.request([RGBColor(hex: "#123456")!])
        let pending = try XCTUnwrap(model.pending)
        let pendingFile = directory.appendingPathComponent("pending-color-transfer.json")
        let different = try PaletteTransfer(colors: [RGBColor(hex: "#abcdef")!]).encoded()
        for replacement in [Data("truncated pending request".utf8), different] {
            try replacement.write(to: pendingFile)
            model.cancel()
            XCTAssertEqual(model.pending, pending)
            XCTAssertEqual(try Data(contentsOf: pendingFile), replacement)
            XCTAssertEqual(try Data(contentsOf: journal), bytes)
        }
    }
    func testCrownComponentWritebacksIgnoreIdenticalNonfiniteAndUnselectedValues() {
        let suite = "TouchColor.watch-crown-writeback.\(UUID())"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let palette = WatchPalette(defaults: defaults)
        palette.select(RGBColor(hex: "#fe2238")!); palette.save(); palette.save()
        var red: [Double] = [], green: [Double] = [], blue: [Double] = []
        let tokens = [palette.$red.dropFirst().sink { red.append($0) },
                      palette.$green.dropFirst().sink { green.append($0) },
                      palette.$blue.dropFirst().sink { blue.append($0) }]
        withExtendedLifetime(tokens) {
            for _ in 0..<20 {
                palette.setComponent(254, channel: 0)
                palette.setComponent(34, channel: 1)
                palette.setComponent(56, channel: 2)
            }
            palette.setComponent(.nan, channel: 0); palette.setComponent(.infinity, channel: 1)
            palette.setComponent(123, channel: 3)
            XCTAssertTrue(red.isEmpty && green.isEmpty && blue.isEmpty)
            palette.setComponent(253, channel: 0); palette.setComponent(253, channel: 0)
            XCTAssertEqual(red, [253]); XCTAssertTrue(green.isEmpty && blue.isEmpty)
            XCTAssertEqual(palette.selected.hex, "#fd2238")
            XCTAssertEqual(palette.colors.map(\.hex), ["#fe2238", "#fe2238"])
            palette.setComponent(-1, channel: 1); palette.setComponent(256, channel: 2)
            XCTAssertEqual(green, [0]); XCTAssertEqual(blue, [255])
        }
    }
    func testRepeatedEditCopySelectionDoesNotRepublishOrMutateSavedHistory() {
        let suite = "TouchColor.watch-copy-unit.\(UUID())"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let palette = WatchPalette(defaults: defaults)
        let first = RGBColor(hex: "#fe0000")!, next = RGBColor(hex: "#0c2238")!
        palette.select(first); palette.save(); palette.save()
        var red: [Double] = [], green: [Double] = [], blue: [Double] = []
        let tokens = [palette.$red.dropFirst().sink { red.append($0) },
                      palette.$green.dropFirst().sink { green.append($0) },
                      palette.$blue.dropFirst().sink { blue.append($0) }]
        withExtendedLifetime(tokens) {
            for _ in 0..<5 { palette.select(first) }
            XCTAssertTrue(red.isEmpty && green.isEmpty && blue.isEmpty)
            palette.select(next); palette.select(next)
            XCTAssertEqual(red, [12]); XCTAssertEqual(green, [34]); XCTAssertEqual(blue, [56])
            XCTAssertEqual(palette.selected, next)
            XCTAssertEqual(palette.colors, [first, first])
        }
    }
    func testOfflineRGBEditingKeepsOrderedDuplicatesAndRecoveryBackup() {
        let suite = "TouchColor.watch-unit.\(UUID())"
        let isolated = UserDefaults(suiteName: suite)!
        defer { isolated.removePersistentDomain(forName: suite) }
        isolated.set(["#FF0000", "malformed", "#FF0000"], forKey: "colorArray")
        let palette = WatchPalette(defaults: isolated)
        XCTAssertEqual(palette.colors.map(\.hex), ["#ff0000", "#ff0000"])
        palette.red = 12; palette.green = 34; palette.blue = 56; palette.save()
        XCTAssertEqual(palette.selected.hex, "#0c2238")
        XCTAssertEqual(WatchPalette(defaults: isolated).colors.map(\.hex), ["#ff0000", "#ff0000", "#0c2238"])
        XCTAssertEqual(isolated.stringArray(forKey: "colorArrayRecoveryBackup"), ["#FF0000", "malformed", "#FF0000"])
        palette.remove(at: 1)
        XCTAssertEqual(WatchPalette(defaults: isolated).colors.map(\.hex), ["#ff0000", "#0c2238"])
    }
    func testExplicitTransferPersistsOfflineRejectsReplacementAndRequiresRetry() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-transfer-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let transfer = WatchTransfer(directory: directory, activate: false)
        XCTAssertNil(transfer.pending)
        let color = RGBColor(hex: "#123456")!
        transfer.request([color, color])
        let id = try XCTUnwrap(transfer.pending?.id)
        XCTAssertEqual(transfer.pending?.colors, [color, color])
        transfer.request([RGBColor(hex: "#abcdef")!])
        XCTAssertEqual(transfer.pending?.id, id)
        let reopened = WatchTransfer(directory: directory, activate: false)
        XCTAssertEqual(reopened.pending?.id, id); XCTAssertEqual(reopened.pending?.colors, [color, color])
        reopened.retry(); XCTAssertEqual(reopened.pending?.id, id)
        reopened.cancel(); XCTAssertNil(WatchTransfer(directory: directory, activate: false).pending)
    }
    func testMalformedPendingTransferIsPreservedBeforeAnyNewRequest() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-transfer-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("pending-color-transfer.json"), original = Data("corrupt pending request".utf8)
        try original.write(to: file)
        let transfer = WatchTransfer(directory: directory, activate: false)
        transfer.request([RGBColor(hex: "#ff0000")!])
        XCTAssertNil(transfer.pending); XCTAssertEqual(try Data(contentsOf: file), original)
    }
    func testRealPreviewFileSamplingAndCancellationKeepCurrentSelection() async throws {
        let model = WatchPhotoModel()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("watch-photo-\(UUID()).tiff")
        try RasterFixture.data().write(to: file)
        model.load(WatchPhotoFile(url: file), token: model.begin())
        for _ in 0..<100 where model.busy { try await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertFalse(model.busy); XCTAssertEqual(model.color?.hex, "#ff00ff")
        model.move(dx: 0, dy: -1); XCTAssertEqual(model.color?.hex, "#00ff00")
        let old = model.begin(); model.cancel()
        let stale = FileManager.default.temporaryDirectory.appendingPathComponent("watch-photo-stale-\(UUID()).tiff")
        try RasterFixture.data(orientation: 3).write(to: stale)
        model.load(WatchPhotoFile(url: stale), token: old)
        XCTAssertEqual(model.color?.hex, "#00ff00"); XCTAssertFalse(FileManager.default.fileExists(atPath: stale.path))
    }
    func testAcknowledgementsPersistAndIgnoreStaleOrDuplicateMessages() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-ack-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = WatchTransfer(directory: directory, activate: false)
        model.request([RGBColor(hex: "#123456")!])
        let first = try XCTUnwrap(model.pending)
        let receipt = PaletteTransferReceipt(requestID: first.id, fingerprint: try PaletteFingerprint.of(first), outcome: .accepted)
        model.receiveReceipt(try receipt.encoded())
        XCTAssertNil(model.pending); XCTAssertEqual(model.lastReceipt, receipt)
        let reopened = WatchTransfer(directory: directory, activate: false)
        XCTAssertNil(reopened.pending); XCTAssertEqual(reopened.lastReceipt, receipt)
        reopened.request([RGBColor(hex: "#abcdef")!])
        let next = reopened.pending
        reopened.receiveReceipt(try receipt.encoded())
        XCTAssertEqual(reopened.pending, next)
        reopened.receiveReceipt(Data("partial acknowledgement".utf8))
        XCTAssertEqual(reopened.pending, next)
    }

    func testRenderedPreviewWhiteMatteMatchesTransparentAndHalfAlphaSamples() throws {
        let content = WatchPreviewCanvas(preview: try PreviewRaster.decode(RasterFixture.alphaData()), point: .center, zoom: 1).frame(width: 400, height: 200).environment(\.colorScheme, .dark)
        let renderer = ImageRenderer(content: content); renderer.scale = 1
        let image = try XCTUnwrap(renderer.cgImage)
        XCTAssertEqual(RasterPixelSampler.sample(image: image, at: NormalizedPoint(x: 0.25, y: 0.25)!)?.hex, "#ffffff")
        let blue = try XCTUnwrap(RasterPixelSampler.sample(image: image, at: NormalizedPoint(x: 0.75, y: 0.25)!))
        XCTAssertEqual(Double(blue.red), 127, accuracy: 1); XCTAssertEqual(Double(blue.green), 127, accuracy: 1); XCTAssertEqual(blue.blue, 255)
    }

}
