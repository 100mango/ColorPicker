import AppKit
import AVFoundation
import ColorDomain

@MainActor final class CameraModel: ObservableObject {
    @Published private(set) var devices: [CameraDevice] = []
    @Published private(set) var status = NSLocalizedString("Choose Start Camera when you are ready.", comment: "Camera status")
    @Published private(set) var running = false
    @Published private(set) var preparing = false
    @Published private(set) var freezing = false
    @Published private(set) var color: ColorDomain.RGBColor?
    @Published private(set) var dimensions = ""
    @Published var selectedDeviceID = ""
    let driver: CameraDriving
    private let epoch = CaptureEpoch()
    private var token: UInt64?
    private var observers: [NSObjectProtocol] = []
    var session: AVCaptureSession { driver.session }

    init(driver: CameraDriving = AVColorCameraDriver()) {
        self.driver = driver
        refreshDevices()
        let gate = epoch
        driver.onInterruption = { [weak self] in
            guard let interrupted = gate.currentToken() else { return }
            Task { @MainActor in
                guard gate.accepts(interrupted) else { return }
                self?.stop(message: NSLocalizedString("Camera interrupted. Choose Start Camera to retry.", comment: "Camera status"))
            }
        }
        for name in [AVCaptureDevice.wasConnectedNotification, AVCaptureDevice.wasDisconnectedNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.connectionChanged() }
            })
        }
        observers.append(NotificationCenter.default.addObserver(forName: NSApplication.didResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.stop(message: NSLocalizedString("Camera paused while TouchColor is inactive. Choose Start Camera to resume.", comment: "Camera status")) }
        })
    }
    deinit { epoch.invalidate(); driver.stop(); observers.forEach(NotificationCenter.default.removeObserver) }
    func refreshDevices() {
        devices = driver.devices()
        if !devices.contains(where: { $0.id == selectedDeviceID }) { selectedDeviceID = devices.first?.id ?? "" }
        if devices.isEmpty { status = NSLocalizedString("No camera is available. Connect a camera, or import an image instead.", comment: "Camera status") }
    }
    func connectionChanged() {
        stop(message: NSLocalizedString("Camera connection changed. Choose a camera and start again.", comment: "Camera status"))
        refreshDevices()
    }
    func start() {
        // Repeated Start never overlaps permission requests or sessions.
        guard !preparing, !running else { return }
        refreshDevices()
        guard devices.contains(where: { $0.id == selectedDeviceID }) else { return }
        let current = epoch.begin(); token = current
        color = nil; dimensions = ""; preparing = true; freezing = false
        status = NSLocalizedString("Preparing camera…", comment: "Camera status")
        switch driver.authorization() {
        case .authorized: beginCapture(current)
        case .notDetermined:
            driver.requestAccess { [weak self] granted in
                Task { @MainActor in
                    guard let self, self.epoch.accepts(current) else { return }
                    if granted { self.beginCapture(current) }
                    else { self.stop(message: NSLocalizedString("Camera access was denied. You can enable it in System Settings > Privacy & Security > Camera, or import an image.", comment: "Camera status")) }
                }
            }
        default:
            stop(message: NSLocalizedString("Camera access is unavailable. Check System Settings > Privacy & Security > Camera, or import an image.", comment: "Camera status"))
        }
    }
    private func beginCapture(_ current: UInt64) {
        guard epoch.accepts(current) else { return }
        driver.start(deviceID: selectedDeviceID, token: current, epoch: epoch) { [weak self] event in
            Task { @MainActor in
                guard let self, self.epoch.accepts(current) else { return }
                switch event {
                case .running:
                    self.preparing = false; self.running = true
                    self.status = NSLocalizedString("Live center pixel · sRGB video", comment: "Camera status")
                case .sample(let color, let width, let height):
                    self.color = color; self.dimensions = "\(width) × \(height)"
                case .failed(let message): self.stop(message: message)
                }
            }
        }
    }
    func stop(message: String = NSLocalizedString("Camera stopped", comment: "Camera status")) {
        epoch.invalidate(); token = nil
        preparing = false; running = false; freezing = false; color = nil; dimensions = ""
        status = message
        driver.stop()
    }
    func freeze(_ completion: @escaping (Data) -> Void) {
        guard running, color != nil, !freezing, let current = token, epoch.accepts(current) else { return }
        freezing = true
        driver.freeze(token: current, epoch: epoch) { [weak self] result in
            Task { @MainActor in
                guard let self, self.epoch.accepts(current) else { return }
                self.freezing = false
                switch result {
                case .success(let data): self.stop(); completion(data)
                case .failure(let error): self.status = error.localizedDescription
                }
            }
        }
    }
}
