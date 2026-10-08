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
    var onInterruption: ((UInt64) -> Void)? { get set }
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
    private(set) var session = AVCaptureSession()
    var onInterruption: ((UInt64) -> Void)?
    private let queue = DispatchQueue(label: "TouchColor.camera", qos: .userInitiated)
    private var receiver: ColorFrameReceiver?
    private var activeSession: AVCaptureSession?
    private var observers: [NSObjectProtocol] = []

    deinit { observers.forEach(NotificationCenter.default.removeObserver) }
    private func observe(_ capture: AVCaptureSession, token: UInt64) {
        observers.forEach(NotificationCenter.default.removeObserver); observers.removeAll()
        for name in [AVCaptureSession.runtimeErrorNotification, AVCaptureSession.wasInterruptedNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: capture, queue: .main) { [weak self] _ in
                // Capture the originating session's epoch now; never look up a newer epoch
                // when a notification queued before stop/restart finally reaches the UI.
                self?.onInterruption?(token)
            })
        }
    }
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
        let capture = AVCaptureSession()
        session = capture // Called by the main-actor model; preview switches on the next publication.
        queue.async {
            guard epoch.accepts(token) else { return }
            if let previous = self.activeSession, previous.isRunning { previous.stopRunning() }
            self.activeSession = capture
            self.observe(capture, token: token)
            self.receiver = nil
            guard let device = Self.availableDevices().first(where: { $0.uniqueID == deviceID }) else {
                receive(.failed(NSLocalizedString("The selected camera is no longer available.", comment: "Camera error"))); return
            }
            capture.beginConfiguration()
            for input in capture.inputs { capture.removeInput(input) }
            for output in capture.outputs { capture.removeOutput(output) }
            do {
                let input = try AVCaptureDeviceInput(device: device)
                let output = AVCaptureVideoDataOutput()
                output.alwaysDiscardsLateVideoFrames = true
                output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
                guard capture.canAddInput(input), capture.canAddOutput(output) else { throw CocoaError(.featureUnsupported) }
                capture.addInput(input); capture.addOutput(output)
                if capture.canSetSessionPreset(.high) { capture.sessionPreset = .high }
                // macOS exposes device color-space selection; the automatic wide-color
                // session property is iOS-only. Select sRGB explicitly under the device lock.
                try device.lockForConfiguration()
                guard device.activeFormat.supportedColorSpaces.contains(.sRGB) else {
                    device.unlockForConfiguration(); throw CocoaError(.featureUnsupported)
                }
                device.activeColorSpace = .sRGB
                device.unlockForConfiguration()
                let receiver = ColorFrameReceiver(token: token, epoch: epoch, receive: receive)
                self.receiver = receiver
                output.setSampleBufferDelegate(receiver, queue: self.queue)
                capture.commitConfiguration()
                guard epoch.accepts(token) else { return }
                capture.startRunning()
                guard epoch.accepts(token) else { capture.stopRunning(); return }
                if capture.isRunning { receive(.running) }
                else { receive(.failed(NSLocalizedString("The camera could not start. Try another camera or import an image.", comment: "Camera error"))) }
            } catch {
                capture.commitConfiguration()
                receive(.failed(error.localizedDescription))
            }
        }
    }
    func stop() {
        queue.async {
            self.receiver = nil
            self.observers.forEach(NotificationCenter.default.removeObserver); self.observers.removeAll()
            guard let capture = self.activeSession else { return }
            if capture.isRunning { capture.stopRunning() }
            capture.beginConfiguration()
            for output in capture.outputs { capture.removeOutput(output) }
            for input in capture.inputs { capture.removeInput(input) }
            capture.commitConfiguration()
            self.activeSession = nil
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
