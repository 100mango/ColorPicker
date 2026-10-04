import SwiftUI
import PhotosUI
import ColorDomain
import ColorRaster
#if DEBUG
import OSLog
#endif

struct WatchHome: View {
    @ObservedObject var palette: WatchPalette
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        NavigationStack {
            List {
                NavigationLink("Create Color") { WatchColorEditor(palette: palette, transfer: transfer) }.accessibilityIdentifier("watch.editor")
                NavigationLink("Sample Photo Preview") { WatchPhotoView(palette: palette) }.accessibilityIdentifier("watch.photo")
                Section("Palette") {
                    Text("\(palette.colors.count)").accessibilityIdentifier("watch.count")
                    ForEach(Array(palette.colors.enumerated()), id: \.offset) { index, color in
                        NavigationLink {
                            WatchSavedColor(color: color, index: index, palette: palette, transfer: transfer)
                        } label: {
                            HStack {
                                Color(red: Double(color.red)/255, green: Double(color.green)/255, blue: Double(color.blue)/255).frame(width: 22, height: 22)
                                Text(color.hex).monospaced()
                            }
                        }.accessibilityIdentifier("watch.color.\(index)")
                    }
                }
                NavigationLink("Transfer Status") { WatchTransferView(transfer: transfer) }.accessibilityIdentifier("watch.transfer.open")
                NavigationLink("Privacy") { WatchPrivacy() }
            }.navigationTitle("TouchColor")
        }
    }
}
struct WatchSwatch: View {
    #if DEBUG
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .headline) private var measuredHeadlineSize: CGFloat = 17
    #endif
    let color: RGBColor
    @ViewBuilder private var hexadecimal: some View {
        let text = Text(color.hex).font(.headline.monospaced()).accessibilityIdentifier("watch.hex")
        #if DEBUG
        if ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_TRAIT_PROOF"] == "1" {
            text.accessibilityValue("largest=\(dynamicTypeSize == .accessibility5);metric=\(measuredHeadlineSize)")
        } else { text }
        #else
        text
        #endif
    }
    var body: some View {
        VStack(spacing: 6) {
            Color(red: Double(color.red)/255, green: Double(color.green)/255, blue: Double(color.blue)/255).frame(height: 52).clipShape(RoundedRectangle(cornerRadius: 10)).accessibilityHidden(true)
            hexadecimal
            Text(color.rgbDescription).font(.caption2.monospacedDigit()).accessibilityIdentifier("watch.rgb")
        }
    }
}
struct WatchColorEditor: View {
    @ObservedObject var palette: WatchPalette
    @ObservedObject var transfer: WatchTransfer
    @State private var channel = 0
    @State private var sendSelection: RGBColor?
    @State private var editorIsVisible = false
    @State private var editorID = UUID()
    @FocusState private var crownFocused: Bool
    private var component: Binding<Double> {
        Binding(get: { channel == 0 ? palette.red : channel == 1 ? palette.green : palette.blue },
                set: { value in
                    // A retained navigation destination must not keep writing its
                    // Crown binding after another editor becomes visible.
                    guard editorIsVisible else {
                        #if DEBUG
                        WatchEditorDiagnostics.writeback(editorID, changed: false, visible: false)
                        #endif
                        return
                    }
                    #if DEBUG
                    let before = channel == 0 ? palette.red : channel == 1 ? palette.green : palette.blue
                    #endif
                    palette.setComponent(value, channel: channel)
                    #if DEBUG
                    let after = channel == 0 ? palette.red : channel == 1 ? palette.green : palette.blue
                    WatchEditorDiagnostics.writeback(editorID, changed: before != after, visible: true)
                    #endif
                })
    }
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                WatchSwatch(color: palette.selected)
                Picker("Component", selection: $channel) { Text("R").tag(0); Text("G").tag(1); Text("B").tag(2) }.pickerStyle(.navigationLink)
                HStack {
                    Button("−") { component.wrappedValue = max(0, component.wrappedValue - 1); crownFocused = true }.accessibilityIdentifier("watch.component.down")
                    Text("\(Int(component.wrappedValue.rounded()))").monospacedDigit()
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .focusable(true).focused($crownFocused)
                        .digitalCrownRotation(component, from: 0, through: 255, by: 1, sensitivity: .medium, isContinuous: false, isHapticFeedbackEnabled: true)
                        .onTapGesture { crownFocused = true }
                        .accessibilityLabel("Component")
                        .accessibilityValue("\(Int(component.wrappedValue.rounded()))")
                        .accessibilityIdentifier("watch.component.value")
                        .accessibilityAdjustableAction { direction in
                            if direction == .increment { component.wrappedValue = min(255, component.wrappedValue + 1) }
                            else if direction == .decrement { component.wrappedValue = max(0, component.wrappedValue - 1) }
                        }
                    Button("+") { component.wrappedValue = min(255, component.wrappedValue + 1); crownFocused = true }.accessibilityIdentifier("watch.component.up")
                }
                Text("Turn the Digital Crown to adjust the selected RGB component.").font(.caption2)
                Button("Save Color") { palette.save() }.accessibilityIdentifier("watch.save")
                Button("Send to iPhone") { sendSelection = palette.selected }.accessibilityIdentifier("watch.send")
                Text(transfer.status).font(.caption2).accessibilityIdentifier("watch.transfer.status")
            }.padding(.horizontal, 8)
        }
        .onAppear {
            editorIsVisible = true; crownFocused = true
            #if DEBUG
            WatchEditorDiagnostics.appeared(editorID)
            #endif
        }
        .onDisappear {
            editorIsVisible = false; crownFocused = false
            #if DEBUG
            WatchEditorDiagnostics.disappeared(editorID)
            #endif
        }
        .onChange(of: channel) { _ in if editorIsVisible { crownFocused = true } }
        .onChange(of: crownFocused) { focused in
            #if DEBUG
            WatchEditorDiagnostics.focus(editorID, focused: focused, visible: editorIsVisible)
            #endif
        }
        .navigationTitle("Create Color")
        .confirmationDialog("Send this color to iPhone for review?",
            isPresented: Binding(get: { sendSelection != nil }, set: { if !$0 { sendSelection = nil } }),
            titleVisibility: .visible, presenting: sendSelection) { color in
            Button("Send") { transfer.request([color]) }.accessibilityIdentifier("watch.send.confirm")
            Button("Cancel", role: .cancel) {}
        } message: { color in Text(color.hex) }
    }
}
#if DEBUG
/// Bounded local lifecycle diagnostics for the actual nested-navigation/Crown
/// regression. No values, photos or palette contents are logged.
@MainActor private enum WatchEditorDiagnostics {
    private static var visibleEditors = Set<UUID>()
    private static var events = 0
    private static let logger = Logger(subsystem: "com.mango.touchColor.WatchDiagnostics", category: "editor")
    private static func emit(_ kind: String, _ id: UUID, focused: Bool = false, visible: Bool) {
        guard events < 80 else { return }; events += 1
        logger.notice("WATCH_EDITOR \(kind, privacy: .public) id=\(id.uuidString, privacy: .public) visible=\(visible) focused=\(focused) active=\(visibleEditors.count)")
    }
    static func appeared(_ id: UUID) { visibleEditors.insert(id); emit("appear", id, visible: true) }
    static func disappeared(_ id: UUID) { visibleEditors.remove(id); emit("disappear", id, visible: false) }
    static func focus(_ id: UUID, focused: Bool, visible: Bool) { emit("focus", id, focused: focused, visible: visible) }
    static func writeback(_ id: UUID, changed: Bool, visible: Bool) { emit(changed ? "component changed" : "component unchanged", id, visible: visible) }
}
#endif
struct WatchTransferView: View {
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
#if DEBUG
                if ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" {
                    // Read-only correlation of the actual received receipt; no transport injection.
                    Text(transfer.status).accessibilityIdentifier("watch.transfer.status")
                        .accessibilityValue(transfer.pairedReceiptValue)
                } else {
                    Text(transfer.status).accessibilityIdentifier("watch.transfer.status")
                }
#else
                Text(transfer.status).accessibilityIdentifier("watch.transfer.status")
#endif
                if let pending = transfer.pending {
                    Text("\(pending.colors.count) selected colors").font(.caption).accessibilityIdentifier("watch.transfer.count")
                    ForEach(Array(pending.colors.enumerated()), id: \.offset) { index, color in
                        Text(color.hex).font(.caption.monospaced()).accessibilityIdentifier("watch.transfer.color.\(index)")
                    }
                    Button("Retry") { transfer.retry() }.disabled(transfer.sending).accessibilityIdentifier("watch.transfer.retry")
                    Button("Cancel Transfer", role: .destructive) { transfer.cancel() }.accessibilityIdentifier("watch.transfer.cancel")
                }
            }
        }.navigationTitle("Transfer Status")
    }
}
struct WatchPhotoView: View {
    @ObservedObject var palette: WatchPalette
    @StateObject private var model = WatchPhotoModel()
    @State private var selection: PhotosPickerItem?
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                PhotosPicker(selection: $selection, matching: .images, preferredItemEncoding: .current) { Label("Choose Photo", systemImage: "photo") }
                    .accessibilityIdentifier("watch.photos.choose")
                if let preview = model.preview {
                    WatchPreviewCanvas(preview: preview, point: model.point, zoom: model.zoom)
                        .frame(height: 120).accessibilityIdentifier("watch.preview")
                    Text("Preview color · up to 512 pixels").font(.caption2)
                    if let color = model.color {
                        Text(color.hex).monospaced().accessibilityIdentifier("watch.preview.hex")
                        Text(color.rgbDescription).font(.caption2.monospacedDigit())
                        Button("Save Color") { palette.select(color); palette.save() }.accessibilityIdentifier("watch.preview.save")
                    }
                    HStack {
                        Button("←") { model.move(dx: -1, dy: 0) }.accessibilityIdentifier("watch.preview.left")
                        Button("→") { model.move(dx: 1, dy: 0) }.accessibilityIdentifier("watch.preview.right")
                    }
                    HStack {
                        Button("↑") { model.move(dx: 0, dy: -1) }.accessibilityIdentifier("watch.preview.up")
                        Button("↓") { model.move(dx: 0, dy: 1) }.accessibilityIdentifier("watch.preview.down")
                    }
                    Button("Center") { model.select(.center) }
                    Slider(value: $model.zoom, in: 1...10).accessibilityLabel("Preview zoom")
                    Text(String(format: "%.1f×", model.zoom)).font(.caption)
                }
                if model.busy { ProgressView(); Button("Cancel") { model.cancel(); selection = nil } }
                if let error = model.error { Text(error).font(.caption2) }
            }
        }.navigationTitle("Photo Preview")
        .task(id: selection) {
            guard let selected = selection else { return }
            defer { if selection == selected { selection = nil } }
            let token = model.begin()
            do {
                guard let file = try await selected.loadTransferable(type: WatchPhotoFile.self) else { throw CocoaError(.fileReadUnknown) }
                guard !Task.isCancelled, model.accepts(token) else { try? FileManager.default.removeItem(at: file.url); return }
                model.load(file, token: token)
            } catch {
                if model.accepts(token) { model.cancel(); model.error = NSLocalizedString("The photo could not be opened. Try another photo.", comment: "Watch photo error") }
            }
        }
        .onDisappear { model.cancel() }
    }
}
struct WatchPrivacy: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Celluloid、QRCatcher 和 TouchColor 在设备本地处理照片、相机画面、二维码或颜色数据，开发者不收集或上传这些数据。用户主动分享、打开链接，以及系统 iCloud 同步等行为由相应服务处理。如有隐私问题，请联系 100mango@gmail.com。本地数据可通过相应应用或系统删除，权限可在系统设置中撤回。")
                Text("Celluloid, QRCatcher, and TouchColor process photos, camera images, QR codes, or color data locally on your device. The developer does not collect or upload this data. Actions you choose to take, such as sharing or opening links, and system services such as iCloud sync are handled by the respective services. For privacy questions, contact 100mango@gmail.com. Local data can be deleted through the relevant app or system, and permissions can be revoked in system settings.")
                Text("https://100mango.github.io/app-privacy/").font(.caption2)
            }
        }.navigationTitle("Privacy")
    }
}

private struct WatchSavedColor: View {
    @Environment(\.dismiss) private var dismiss
    let color: RGBColor
    let index: Int
    @ObservedObject var palette: WatchPalette
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        ScrollView {
            VStack {
                WatchSwatch(color: color)
                NavigationLink("Edit a Copy") {
                    WatchColorEditor(palette: palette, transfer: transfer).onAppear { palette.select(color) }
                }.accessibilityIdentifier("watch.edit.copy")
                Button("Delete", role: .destructive) { palette.remove(at: index); dismiss() }.accessibilityIdentifier("watch.delete.\(index)")
            }
        }
    }
}

struct WatchPreviewCanvas: View {
    let preview: PreviewRaster
    let point: NormalizedPoint
    let zoom: Double
    var body: some View {
        GeometryReader { geometry in
            let ratio = min(geometry.size.width / CGFloat(preview.width), geometry.size.height / CGFloat(preview.height))
            let size = CGSize(width: CGFloat(preview.width) * ratio, height: CGFloat(preview.height) * ratio)
            Image(decorative: preview.image, scale: 1).resizable().interpolation(.none)
                .frame(width: size.width, height: size.height)
                .background(Color.white)
                .overlay {
                    Circle().stroke(.white, lineWidth: 2 / zoom).background(Circle().stroke(.black, lineWidth: 4 / zoom))
                        .frame(width: 10 / zoom, height: 10 / zoom)
                        .position(x: point.x * size.width, y: point.y * size.height)
                }
                .scaleEffect(zoom, anchor: UnitPoint(x: point.x, y: point.y))
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
        }.clipped()
    }
}
