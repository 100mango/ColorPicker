import SwiftUI
import AVFoundation

struct CameraSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var camera = CameraModel()
    @ObservedObject var library: PaletteLibrary
    let onFrame: (Data) -> Void
    var body: some View {
        VStack(spacing: 14) {
            Text("Camera").font(.title2.bold())
            CameraPreview(session: camera.session)
                .frame(width: 520, height: 280).background(.black)
                .overlay { Image(systemName: "plus").font(.title).foregroundStyle(.white).shadow(color: .black, radius: 2).accessibilityHidden(true) }
                .accessibilityLabel("Live camera preview, sampling the center pixel")
            Picker("Camera", selection: $camera.selectedDeviceID) {
                if camera.devices.isEmpty { Text("No camera").tag("") }
                ForEach(camera.devices) { device in Text(device.name).tag(device.id) }
            }.disabled(camera.preparing || camera.running).accessibilityIdentifier("camera.device")
            Text(camera.status).multilineTextAlignment(.center).lineLimit(4).frame(maxWidth: .infinity)
                .accessibilityIdentifier("camera.status")
            HStack {
                if let color = camera.color {
                    Text(color.hex).monospaced().accessibilityIdentifier("camera.hex")
                    Text(color.rgbDescription).monospacedDigit()
                    Text(camera.dimensions).font(.caption)
                } else { Text("No color selected").foregroundStyle(.secondary) }
            }.frame(height: 22)
            HStack {
                Button("Start Camera") { camera.start() }
                    .disabled(camera.running || camera.preparing || camera.devices.isEmpty).accessibilityIdentifier("camera.start")
                Button("Stop Camera") { camera.stop() }
                    .disabled(!camera.running && !camera.preparing).accessibilityIdentifier("camera.stop")
                Button("Copy") { if let color = camera.color { library.copy(color) } }
                    .disabled(camera.color == nil).accessibilityIdentifier("camera.copy")
                Button("Save Color") { if let color = camera.color { library.append([color]) } }
                    .disabled(camera.color == nil).accessibilityIdentifier("camera.save")
                Button("Freeze Frame") { camera.freeze { data in onFrame(data); dismiss() } }
                    .disabled(!camera.running || camera.color == nil || camera.freezing).accessibilityIdentifier("camera.freeze")
            }
            HStack {
                Text("Freeze keeps the full video frame, not a still-photo capture.").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Done") { camera.stop(); dismiss() }.keyboardShortcut(.cancelAction).accessibilityIdentifier("camera.close")
            }
        }.padding(20).frame(width: 560)
            .onDisappear { camera.stop() }
    }
}
private struct CameraPreview: NSViewRepresentable {
    let session: AVCaptureSession
    func makeNSView(context: Context) -> Preview { Preview(session: session) }
    func updateNSView(_ view: Preview, context: Context) { view.setSession(session) }
    final class Preview: NSView {
        private let preview: AVCaptureVideoPreviewLayer
        init(session: AVCaptureSession) {
            preview = AVCaptureVideoPreviewLayer(session: session)
            super.init(frame: .zero)
            wantsLayer = true; preview.videoGravity = .resizeAspect
            setAccessibilityElement(true)
            setAccessibilityRole(.image)
            setAccessibilityLabel(NSLocalizedString("Live camera preview, sampling the center pixel", comment: "Camera accessibility"))
            layer?.addSublayer(preview)
        }
        func setSession(_ session: AVCaptureSession) {
            if preview.session !== session { preview.session = session }
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
        override func layout() { super.layout(); preview.frame = bounds }
    }
}
