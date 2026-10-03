import AppKit
import AVFoundation
import CoreImage
import ImageIO
import UniformTypeIdentifiers
import ColorDomain

struct CameraDevice: Identifiable, Equatable { let id: String; let name: String }
enum CameraEvent { case running, sample(ColorDomain.RGBColor, width: Int, height: Int), failed(String) }

/// Injectable boundary keeps deterministic lifecycle tests separate from actual hardware.
protocol CameraDriving: AnyObject {
    var session: AVCaptureSession { get }
    var onInterruption: (() -> Void)? { get set }
    func devices() -> [CameraDevice]
    func authorization() -> AVAuthorizationStatus
    func requestAccess(_ completion: @escaping (Bool) -> Void)
    func start(deviceID: String, token: UInt64, epoch: CaptureEpoch, receive: @escaping (CameraEvent) -> Void)
    func stop()
    func freeze(token: UInt64, epoch: CaptureEpoch, completion: @escaping (Result<Data, Error>) -> Void)
}

/// Pixel-buffer sampling uses the real row stride, not a tightly-packed assumption.
/// AVFoundation's BGRA video output is opaque; alpha is ignored as in the legacy camera.
enum CameraPixels {
    static func center(_ buffer: CVPixelBuffer) -> ColorDomain.RGBColor? {
        guard CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA,
              !CVPixelBufferIsPlanar(buffer) else { return nil }
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        guard width > 0, height > 0, width <= Int.max / 4, stride >= width * 4,
              CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let pixel = base.advanced(by: (height / 2) * stride + (width / 2) * 4).assumingMemoryBound(to: UInt8.self)
        return ColorDomain.RGBColor(red: pixel[2], green: pixel[1], blue: pixel[0])
    }
    static func png(_ buffer: CVPixelBuffer) throws -> Data {
        guard CVPixelBufferGetWidth(buffer) > 0, CVPixelBufferGetHeight(buffer) > 0,
              Double(CVPixelBufferGetWidth(buffer)) * Double(CVPixelBufferGetHeight(buffer)) <= 100_000_000 else {
            throw CocoaError(.fileReadTooLarge)
        }
        let space = CGColorSpace(name: CGColorSpace.sRGB)!
        let context = CIContext(options: [.workingColorSpace: space, .outputColorSpace: space])
        let image = CIImage(cvPixelBuffer: buffer, options: [.colorSpace: space])
        guard let cgImage = context.createCGImage(image, from: image.extent, format: .RGBA8, colorSpace: space) else { throw CocoaError(.fileReadCorruptFile) }
        let data = NSMutableData()
        guard let output = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { throw CocoaError(.fileWriteUnknown) }
        CGImageDestinationAddImage(output, cgImage, nil)
        guard CGImageDestinationFinalize(output) else { throw CocoaError(.fileWriteUnknown) }
        return data as Data
    }
}

/// All capture/session and full-frame conversion work is serialized off the main actor.
/// Each output has an immutable epoch, so callbacks from an old output cannot be relabeled.
final class AVColorCameraDriver: CameraDriving {
    let session = AVCaptureSession()
    var onInterruption: (() -> Void)?
    private let queue = DispatchQueue(label: "TouchColor.camera", qos: .userInitiated)
    private var receiver: ColorFrameReceiver?
    private var observers: [NSObjectProtocol] = []

    init() {
        for name in [AVCaptureSession.runtimeErrorNotification, AVCaptureSession.wasInterruptedNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: session, queue: .main) { [weak self] _ in self?.onInterruption?() })
        }
    }
    deinit { observers.forEach(NotificationCenter.default.removeObserver) }
    private static func availableDevices() -> [AVCaptureDevice] {
        let types: [AVCaptureDevice.DeviceType]
        if #available(macOS 14, *) { types = [.builtInWideAngleCamera, .external, .continuityCamera] }
        else { types = [.builtInWideAngleCamera, .externalUnknown] }
        return AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
    }
    func devices() -> [CameraDevice] { Self.availableDevices().map { CameraDevice(id: $0.uniqueID, name: $0.localizedName) } }
    func authorization() -> AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .video) }
    func requestAccess(_ completion: @escaping (Bool) -> Void) { AVCaptureDevice.requestAccess(for: .video, completionHandler: completion) }
    func start(deviceID: String, token: UInt64, epoch: CaptureEpoch, receive: @escaping (CameraEvent) -> Void) {
        queue.async {
            guard epoch.accepts(token) else { return }
            if self.session.isRunning { self.session.stopRunning() }
            self.receiver = nil
            guard let device = Self.availableDevices().first(where: { $0.uniqueID == deviceID }) else {
                receive(.failed(NSLocalizedString("The selected camera is no longer available.", comment: "Camera error"))); return
            }
            self.session.beginConfiguration()
            for input in self.session.inputs { self.session.removeInput(input) }
            for output in self.session.outputs { self.session.removeOutput(output) }
            do {
                let input = try AVCaptureDeviceInput(device: device)
                let output = AVCaptureVideoDataOutput()
                output.alwaysDiscardsLateVideoFrames = true
                output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
                guard self.session.canAddInput(input), self.session.canAddOutput(output) else { throw CocoaError(.featureUnsupported) }
                self.session.addInput(input); self.session.addOutput(output)
                if self.session.canSetSessionPreset(.high) { self.session.sessionPreset = .high }
                self.session.automaticallyConfiguresCaptureDeviceForWideColor = false
                try device.lockForConfiguration()
                guard device.activeFormat.supportedColorSpaces.contains(.sRGB) else {
                    device.unlockForConfiguration(); throw CocoaError(.featureUnsupported)
                }
                device.activeColorSpace = .sRGB
                device.unlockForConfiguration()
                let receiver = ColorFrameReceiver(token: token, epoch: epoch, receive: receive)
                self.receiver = receiver
                output.setSampleBufferDelegate(receiver, queue: self.queue)
                self.session.commitConfiguration()
                guard epoch.accepts(token) else { return }
                self.session.startRunning()
                guard epoch.accepts(token) else { self.session.stopRunning(); return }
                if self.session.isRunning { receive(.running) }
                else { receive(.failed(NSLocalizedString("The camera could not start. Try another camera or import an image.", comment: "Camera error"))) }
            } catch {
                self.session.commitConfiguration()
                receive(.failed(error.localizedDescription))
            }
        }
    }
    func stop() {
        queue.async {
            self.receiver = nil
            if self.session.isRunning { self.session.stopRunning() }
            // Release inputs as well as stopping, so a dismissed sheet relinquishes the device.
            self.session.beginConfiguration()
            for output in self.session.outputs { self.session.removeOutput(output) }
            for input in self.session.inputs { self.session.removeInput(input) }
            self.session.commitConfiguration()
        }
    }
    func freeze(token: UInt64, epoch: CaptureEpoch, completion: @escaping (Result<Data, Error>) -> Void) {
        queue.async {
            guard epoch.accepts(token), let receiver = self.receiver, receiver.token == token,
                  let frame = receiver.latest else { completion(.failure(CocoaError(.fileReadUnknown))); return }
            let result = Result { try CameraPixels.png(frame) }
            guard epoch.accepts(token) else { return }
            completion(result)
        }
    }
}

private final class ColorFrameReceiver: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let token: UInt64
    let epoch: CaptureEpoch
    let receive: (CameraEvent) -> Void
    var latest: CVPixelBuffer?
    private var lastTime = -Double.infinity
    init(token: UInt64, epoch: CaptureEpoch, receive: @escaping (CameraEvent) -> Void) {
        self.token = token; self.epoch = epoch; self.receive = receive
    }
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard epoch.accepts(token) else { return }
        let time = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
        guard time.isFinite, time < lastTime || time - lastTime >= 0.1,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer), let color = CameraPixels.center(buffer) else { return }
        lastTime = time; latest = buffer // At most one retained full-size frame, no unbounded frame queue.
        receive(.sample(color, width: CVPixelBufferGetWidth(buffer), height: CVPixelBufferGetHeight(buffer)))
    }
}
