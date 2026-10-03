import XCTest
import SwiftUI
import Foundation
import Combine
import ColorDomain
import ColorRaster
import ColorPaletteLegacy
@testable import TouchColorWatch

@MainActor final class WatchWorkspaceTests: XCTestCase {
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
