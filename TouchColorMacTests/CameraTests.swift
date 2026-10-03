import XCTest
import AVFoundation
import AppKit
import ColorDomain
import ColorRaster
@testable import TouchColorMac

private final class FakeCameraDriver: CameraDriving {
    let session = AVCaptureSession()
    var onInterruption: ((UInt64) -> Void)?
    var available = [CameraDevice(id: "synthetic", name: "Synthetic test camera")]
    var permission = AVAuthorizationStatus.authorized
    var permissionReply: ((Bool) -> Void)?
    var starts: [(UInt64, (CameraEvent) -> Void)] = []
    var freezeReplies: [(Result<Data, Error>) -> Void] = []
    var stopCount = 0
    func devices() -> [CameraDevice] { available }
    func authorization() -> AVAuthorizationStatus { permission }
    func requestAccess(_ completion: @escaping (Bool) -> Void) { permissionReply = completion }
    func start(deviceID: String, token: UInt64, epoch: CaptureEpoch, receive: @escaping (CameraEvent) -> Void) { starts.append((token, receive)) }
    func stop() { stopCount += 1 }
    func freeze(token: UInt64, epoch: CaptureEpoch, completion: @escaping (Result<Data, Error>) -> Void) { freezeReplies.append(completion) }
}

@MainActor final class CameraTests: XCTestCase {
    private func settle() async { try? await Task.sleep(nanoseconds: 30_000_000) }
    func testPermissionCancelDeniedNoDeviceAndRepeatedStart() async {
        let driver = FakeCameraDriver(); driver.permission = .notDetermined
        let model = CameraModel(driver: driver, applicationIsActive: { true })
        model.start(); model.start()
        XCTAssertTrue(model.preparing); XCTAssertNotNil(driver.permissionReply)
        model.stop(); driver.permissionReply?(true); await settle()
        XCTAssertTrue(driver.starts.isEmpty); XCTAssertFalse(model.running)
        driver.permission = .denied; model.start()
        XCTAssertFalse(model.preparing); XCTAssertTrue(driver.starts.isEmpty)
        driver.available = []; model.refreshDevices(); model.start()
        XCTAssertTrue(model.devices.isEmpty); XCTAssertTrue(driver.starts.isEmpty)
        driver.available = [CameraDevice(id: "new", name: "New camera")]; driver.permission = .authorized
        model.start(); model.start()
        XCTAssertEqual(driver.starts.count, 1)
        driver.starts[0].1(.running); await settle()
        XCTAssertTrue(model.running); XCTAssertFalse(model.preparing)
        model.stop()
    }
    func testOldFramesFailuresAndFreezeCannotEscapeStopRestartOrInterruption() async {
        let driver = FakeCameraDriver(); let model = CameraModel(driver: driver)
        model.start(); let old = driver.starts[0].1
        old(.running); old(.sample(ColorDomain.RGBColor(hex: "#123456")!, width: 3, height: 2)); await settle()
        XCTAssertEqual(model.color?.hex, "#123456")
        var delivered = 0
        model.freeze { _ in delivered += 1 }; model.freeze { _ in delivered += 1 }
        XCTAssertEqual(driver.freezeReplies.count, 1)
        model.stop(); XCTAssertNil(model.color)
        model.start(); let fresh = driver.starts[1].1
        old(.sample(ColorDomain.RGBColor(hex: "#ff0000")!, width: 9, height: 9)); old(.failed("stale failure"))
        driver.freezeReplies[0](.success(RasterFixture.data()))
        fresh(.running); fresh(.sample(ColorDomain.RGBColor(hex: "#abcdef")!, width: 3, height: 2)); await settle()
        XCTAssertTrue(model.running); XCTAssertEqual(model.color?.hex, "#abcdef"); XCTAssertEqual(delivered, 0)
        driver.onInterruption?(driver.starts[1].0); await settle()
        fresh(.sample(ColorDomain.RGBColor(hex: "#ff0000")!, width: 3, height: 2)); await settle()
        XCTAssertFalse(model.running); XCTAssertNil(model.color)
        model.start(); driver.available = []; model.connectionChanged()
        XCTAssertFalse(model.preparing); XCTAssertTrue(model.devices.isEmpty)
    }
    func testCurrentFreezeDeliversOnceAndClearsCaptureSelection() async {
        let driver = FakeCameraDriver(); let model = CameraModel(driver: driver)
        model.start(); let send = driver.starts[0].1
        send(.running); send(.sample(ColorDomain.RGBColor(hex: "#ff00ff")!, width: 3, height: 2)); await settle()
        var result: Data?
        model.freeze { result = $0 }
        let bytes = RasterFixture.data()
        driver.freezeReplies[0](.success(bytes)); await settle()
        XCTAssertEqual(result, bytes); XCTAssertFalse(model.running); XCTAssertNil(model.color)
        driver.freezeReplies[0](.success(Data())); await settle()
        XCTAssertEqual(result, bytes)
    }
    func testSyntheticBGRAUsesActualPaddedStrideAndFullFramePNG() throws {
        var buffer: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, 3, 3, kCVPixelFormatType_32BGRA,
            [kCVPixelBufferBytesPerRowAlignmentKey: 32, kCVPixelBufferCGImageCompatibilityKey: true] as CFDictionary, &buffer), kCVReturnSuccess)
        let pixels = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(pixels, [])
        let stride = CVPixelBufferGetBytesPerRow(pixels)
        XCTAssertGreaterThan(stride, 12)
        let base = try XCTUnwrap(CVPixelBufferGetBaseAddress(pixels)).assumingMemoryBound(to: UInt8.self)
        for y in 0..<3 { for x in 0..<3 {
            let offset = y * stride + x * 4
            base[offset] = 0; base[offset + 1] = 0; base[offset + 2] = 255; base[offset + 3] = 255
        } }
        let center = stride + 4
        base[center] = 20; base[center + 1] = 80; base[center + 2] = 200
        CVPixelBufferUnlockBaseAddress(pixels, [])
        XCTAssertEqual(CameraPixels.center(pixels)?.hex, "#c85014")
        let decoded = try ColorRaster.decode(CameraPixels.png(pixels))
        XCTAssertEqual(decoded.width, 3); XCTAssertEqual(decoded.height, 3)
        XCTAssertEqual(decoded.sample(at: .center)?.hex, "#c85014")
        XCTAssertEqual(decoded.sample(at: NormalizedPoint(x: 0.1, y: 0.1)!)?.hex, "#ff0000")
        var unsupported: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, 2, 2, kCVPixelFormatType_32ARGB, nil, &unsupported), kCVReturnSuccess)
        XCTAssertNil(CameraPixels.center(try XCTUnwrap(unsupported)))
    }
    func testBackgroundNotificationStopsRealModelWithoutHardware() async {
        let driver = FakeCameraDriver(); let model = CameraModel(driver: driver)
        model.start(); driver.starts[0].1(.running); await settle()
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: nil)
        await settle()
        XCTAssertFalse(model.running); XCTAssertGreaterThan(driver.stopCount, 0)
    }
    func testInitialPermissionDeactivationWaitsForActiveAppOrGivesExplicitRetry() async {
        let driver = FakeCameraDriver(); driver.permission = .notDetermined
        var active = false
        let model = CameraModel(driver: driver, applicationIsActive: { active })
        model.start()
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: nil)
        await settle()
        XCTAssertTrue(model.preparing); XCTAssertTrue(driver.starts.isEmpty)
        driver.permissionReply?(true); await settle()
        XCTAssertFalse(model.preparing); XCTAssertTrue(driver.starts.isEmpty)
        XCTAssertTrue(model.status.contains("permission granted"))
        driver.permission = .authorized; active = true; model.start()
        XCTAssertEqual(driver.starts.count, 1)
        model.stop()
        driver.permission = .notDetermined; model.start()
        model.applicationResignedActive(); active = true
        driver.permissionReply?(true); await settle()
        XCTAssertEqual(driver.starts.count, 2)
        model.stop()
    }
    func testDelayedOldSessionInterruptionCannotStopRestartedCapture() async {
        let driver = FakeCameraDriver(); let model = CameraModel(driver: driver)
        model.start(); let old = driver.starts[0].0
        model.stop(); model.start(); let current = driver.starts[1]
        current.1(.running); current.1(.sample(ColorDomain.RGBColor(hex: "#abcdef")!, width: 3, height: 2)); await settle()
        driver.onInterruption?(old); await settle()
        XCTAssertTrue(model.running); XCTAssertEqual(model.color?.hex, "#abcdef")
        driver.onInterruption?(current.0); await settle()
        XCTAssertFalse(model.running); XCTAssertNil(model.color)
    }

}
