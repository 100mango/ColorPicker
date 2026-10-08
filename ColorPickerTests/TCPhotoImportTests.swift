import XCTest
import UIKit
import ImageIO
import UniformTypeIdentifiers
import ColorRaster
@testable import TouchColor

private final class PhotoImportResult: @unchecked Sendable {
    struct Snapshot {
        var image: UIImage?
        var error: NSError?
        var count = 0
        var allOnMain = true
    }
    private let lock = NSLock()
    private var value = Snapshot()
    func record(_ image: UIImage?, _ error: NSError?) {
        lock.lock(); defer { lock.unlock() }
        value.image = image; value.error = error; value.count += 1
        value.allOnMain = value.allOnMain && Thread.isMainThread
    }
    var snapshot: Snapshot { lock.lock(); defer { lock.unlock() }; return value }
}

private final class ControlledPhotoProvider: NSItemProvider, @unchecked Sendable {
    let requested = XCTestExpectation(description: "Provider admitted the file request")
    let progress = Progress(totalUnitCount: 1)
    private let identifier: String
    private let returnGate: DispatchSemaphore?
    private let lock = NSLock()
    private var callback: (@Sendable (URL?, Error?) -> Void)?
    init(identifier: String = UTType.png.identifier, returnGate: DispatchSemaphore? = nil) {
        self.identifier = identifier; self.returnGate = returnGate; super.init()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var registeredTypeIdentifiers: [String] { [identifier] }
    override func loadFileRepresentation(forTypeIdentifier typeIdentifier: String,
        completionHandler: @escaping @Sendable (URL?, Error?) -> Void) -> Progress {
        lock.lock(); callback = completionHandler; lock.unlock()
        requested.fulfill()
        returnGate?.wait()
        return progress
    }
    func deliver(_ url: URL?, error: Error? = nil, returned: @escaping @Sendable () -> Void = {}) {
        lock.lock(); let completion = callback; lock.unlock()
        DispatchQueue.global(qos: .userInitiated).async { completion?(url, error); returned() }
    }
}

final class TCPhotoImportTests: XCTestCase {
    private func fixtureImage(space: CGColorSpace = CGColorSpace(name: CGColorSpace.sRGB)!, alpha: Bool = false) -> CGImage {
        let bytes: [UInt8] = alpha
            ? [0,0,0,0, 128,0,0,128, 128,64,32,255]
            : [255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255, 255,0,255,255, 0,255,255,255]
        return CGImage(width: 3, height: alpha ? 1 : 2, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: 12, space: space,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
            provider: CGDataProvider(data: Data(bytes) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
    }
    private func encoded(_ image: CGImage, type: UTType = .tiff, orientation: Int = 1) throws -> Data {
        let data = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, [kCGImagePropertyOrientation: orientation] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return data as Data
    }
    private func withFile<T>(_ data: Data, body: (URL) throws -> T) throws -> T {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-import-test-\(UUID()).image")
        try data.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        return try body(url)
    }
    private func importFile(_ url: URL?, type: UTType = .tiff, error: Error? = nil) -> PhotoImportResult.Snapshot {
        let provider = ControlledPhotoProvider(identifier: type.identifier)
        let result = PhotoImportResult()
        let completed = expectation(description: "Import completion")
        let task = TCPhotoImportTask.load(provider: provider) { image, error in
            result.record(image, error); completed.fulfill()
        }
        wait(for: [provider.requested], timeout: 5)
        provider.deliver(url, error: error)
        wait(for: [completed], timeout: 10)
        withExtendedLifetime(task) {}
        XCTAssertEqual(result.snapshot.count, 1)
        XCTAssertTrue(result.snapshot.allOnMain)
        return result.snapshot
    }
    func testFileImportPreservesFullSizeAllEightOrientationsAndSampling() throws {
        let cg = fixtureImage()
        let orientations: [UIImage.Orientation] = [.up, .upMirrored, .down, .downMirrored, .leftMirrored, .right, .rightMirrored, .left]
        for (index, orientation) in orientations.enumerated() {
            try withFile(encoded(cg, orientation: index + 1)) { url in
                let result = importFile(url)
                XCTAssertNil(result.error)
                let image = try XCTUnwrap(result.image)
                XCTAssertEqual(image.cgImage?.width, index >= 4 ? 2 : 3)
                XCTAssertEqual(image.cgImage?.height, index >= 4 ? 3 : 2)
                for scale in [1.0, 2.0, 3.0] {
                    let original = UIImage(cgImage: cg, scale: scale, orientation: orientation)
                    for point in [CGPoint(x: 0.1,y: 0.1), CGPoint(x: 0.9,y: 0.1), CGPoint(x: 0.1,y: 0.9), CGPoint(x: 0.9,y: 0.9)] {
                        XCTAssertEqual(TCSampleImage(image, point), TCSampleImage(original, point), "EXIF \(index + 1), scale \(scale)")
                    }
                }
            }
        }
    }
    func testImportedAlphaAndWideGamutKeepTheUIKitSRGBWhiteMattePolicy() throws {
        for space in [CGColorSpace(name: CGColorSpace.sRGB)!, CGColorSpace(name: CGColorSpace.displayP3)!] {
            let cg = fixtureImage(space: space, alpha: true)
            try withFile(encoded(cg)) { url in
                let result = importFile(url)
                let image = try XCTUnwrap(result.image)
                XCTAssertNil(result.error)
                let original = UIImage(cgImage: cg)
                for x in [0.1, 0.5, 0.9] {
                    XCTAssertEqual(TCSampleImage(image, CGPoint(x: x, y: 0.5)), TCSampleImage(original, CGPoint(x: x, y: 0.5)))
                }
                XCTAssertEqual(TCSampleImage(image, CGPoint(x: 0.1, y: 0.5)), "#ffffff")
            }
        }
    }
    func testOversizedEncodedFileIsRejectedBeforeMaterialization() throws {
        try withFile(Data()) { url in
            let file = try FileHandle(forWritingTo: url)
            try file.truncate(atOffset: UInt64(ColorRaster.maximumEncodedBytes) + 1)
            try file.close()
            let result = importFile(url)
            XCTAssertNil(result.image)
            XCTAssertEqual(result.error?.localizedDescription, RasterError.tooLarge.localizedDescription)
        }
    }
    func testOversizedOriginalDimensionsAreRejectedBeforeMaterialization() throws {
        let resource = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "photo-over-100mp", withExtension: "b64"))
        let encodedText = try String(contentsOf: resource, encoding: .utf8)
        let data = try XCTUnwrap(Data(base64Encoded: encodedText.trimmingCharacters(in: .whitespacesAndNewlines)))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual((properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue, 10_001)
        XCTAssertEqual((properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue, 10_000)
        try withFile(data) { url in
            let result = importFile(url, type: .png)
            XCTAssertNil(result.image)
            XCTAssertEqual(result.error?.localizedDescription, RasterError.tooLarge.localizedDescription)
        }
    }
    func testTruncatedImageWithOriginalDimensionsIsRejected() throws {
        let complete = try encoded(fixtureImage(), type: .png)
        let truncated = Data(complete.dropLast(12)) // Remove the final PNG IEND chunk, retaining source dimensions.
        let source = try XCTUnwrap(CGImageSourceCreateWithData(truncated as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual((properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue, 3)
        XCTAssertEqual((properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue, 2)
        try withFile(truncated) { url in
            let result = importFile(url, type: .png)
            XCTAssertNil(result.image); XCTAssertNotNil(result.error)
        }
    }
    func testProviderFailureAndNonFileURLPreserveNoImageResult() {
        let failed = importFile(nil, error: NSError(domain: "TouchColor.ProviderFixture", code: 1))
        XCTAssertNil(failed.image); XCTAssertNotNil(failed.error)
        let remote = importFile(URL(string: "https://example.invalid/photo.png"))
        XCTAssertNil(remote.image); XCTAssertNotNil(remote.error)
    }
    func testCancellationBeforeLateProviderResponseCompletesExactlyOnce() throws {
        try withFile(encoded(fixtureImage())) { url in
            let gate = DispatchSemaphore(value: 0)
            defer { gate.signal() } // Release the provider even if an assertion aborts the test.
            let provider = ControlledPhotoProvider(identifier: UTType.tiff.identifier, returnGate: gate)
            let result = PhotoImportResult()
            let completed = expectation(description: "Cancel completion")
            let task = TCPhotoImportTask.load(provider: provider) { image, error in result.record(image,error); completed.fulfill() }
            wait(for: [provider.requested], timeout: 5)
            task.cancel()
            wait(for: [completed], timeout: 5)
            let returned = expectation(description: "Late provider callback returned")
            provider.deliver(url) { returned.fulfill() }
            wait(for: [returned], timeout: 5)
            // requested and the late callback do not join provider Progress registration.
            // Hold that return path explicitly, then observe its actual cancellation.
            XCTAssertFalse(provider.progress.isCancelled)
            gate.signal()
            let cancelled = XCTNSPredicateExpectation(predicate: NSPredicate { _,_ in provider.progress.isCancelled }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [cancelled], timeout: 5), .completed)
            XCTAssertTrue(provider.progress.isCancelled)
            XCTAssertEqual(result.snapshot.count, 1)
            XCTAssertTrue(result.snapshot.allOnMain)
            XCTAssertNil(result.snapshot.image); XCTAssertNil(result.snapshot.error)
        }
    }
    func testCancelBeforeProgressRegistrationStillCancelsProviderWork() {
        let gate = DispatchSemaphore(value: 0)
        let provider = ControlledPhotoProvider(returnGate: gate)
        let completed = expectation(description: "Cancel while provider has not returned progress")
        let task = TCPhotoImportTask.load(provider: provider) { image,error in XCTAssertNil(image); XCTAssertNil(error); completed.fulfill() }
        wait(for: [provider.requested], timeout: 5)
        task.cancel(); gate.signal()
        wait(for: [completed], timeout: 5)
        let cancelled = XCTNSPredicateExpectation(predicate: NSPredicate { _,_ in provider.progress.isCancelled }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [cancelled], timeout: 5), .completed)
    }
}
