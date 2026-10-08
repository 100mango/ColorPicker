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
                NavigationLink("Privacy") { WatchPrivacy() }.accessibilityIdentifier("watch.privacy")
            }.navigationTitle("TouchColor")
            .onAppear {
                #if DEBUG
                WatchEditorDiagnostics.probeBaseline()
                #endif
            }
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
                        // Keep Crown eligibility stable across navigation appearance.
                        // Hidden writes are guarded and disappearance releases focus.
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
#if DEBUG
                if ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" {
                    PairedWatchReadButton(transfer: transfer)
                    Button("Send to iPhone") { sendSelection = palette.selected }.accessibilityIdentifier("watch.send")
                        .accessibilityValue(transfer.pairedReadinessValue)
                } else {
                    Button("Send to iPhone") { sendSelection = palette.selected }.accessibilityIdentifier("watch.send")
                }
#else
                Button("Send to iPhone") { sendSelection = palette.selected }.accessibilityIdentifier("watch.send")
#endif
                Text(transfer.status).font(.caption2).accessibilityIdentifier("watch.transfer.status")
            }.padding(.horizontal, 8)
        }
        .onAppear {
            editorIsVisible = true
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
    // Diagnostic only: two finite tasks, no observed state or UI writes.
    private static let probeCase = "__WatchWorkflowTests_testTouchCopyEntryTouchAndCrownRemainResponsive_"
    private static let probeNonce: String? = {
        let environment = ProcessInfo.processInfo.environment
        guard environment["TOUCHCOLOR_TEST_MAINACTOR_PROBE"] == "1",
              let value = environment["TOUCHCOLOR_TEST_MAINACTOR_NONCE"], value.utf8.count == 36
        else { return nil }
        return UUID(uuidString: value)?.uuidString
    }()
    private static var probeBirth: Double?
    private static var baselineStarted = false
    private static var copyStarted: Double?
    private static var copyExited = false
    private static var probeCount = 0
    private static func probeEmit(_ event: String, sequence: Int, started: Double) {
        guard testCase == probeCase, let nonce = probeNonce, let birth = probeBirth,
              probeCount < 14 else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now >= started, now - started <= 14, now >= birth, now - birth <= 134 else { return }
        probeCount += 1
        let elapsed = Int((now - started) * 1000)
        logger.notice("WATCH_MAIN_ACTOR event=\(event, privacy: .public) case=\(probeCase, privacy: .public) nonce=\(nonce, privacy: .public) seq=\(sequence) elapsed_ms=\(elapsed)")
    }
    private static func probePulses(_ event: String, count: Int, started: Double, window: Double) {
        Task { @MainActor in
            for sequence in 1...count {
                do { try await Task.sleep(nanoseconds: 2_000_000_000) }
                catch { return }
                // Late scheduling must not restart the window or produce a burst.
                guard !Task.isCancelled,
                      ProcessInfo.processInfo.systemUptime - started <= window else { return }
                probeEmit(event, sequence: sequence, started: started)
            }
        }
    }
    static func probeBaseline() {
        guard testCase == probeCase, probeNonce != nil, !baselineStarted else { return }
        baselineStarted = true
        let started = ProcessInfo.processInfo.systemUptime
        probeBirth = started
        probeEmit("baseline", sequence: 0, started: started)
        probePulses("baseline", count: 5, started: started, window: 12)
    }
    static func probeCopyEnter() {
        guard testCase == probeCase, probeNonce != nil, let birth = probeBirth,
              ProcessInfo.processInfo.systemUptime - birth <= 120, copyStarted == nil else { return }
        let started = ProcessInfo.processInfo.systemUptime
        copyStarted = started
        probeEmit("copy_enter", sequence: 0, started: started)
        probePulses("copy_beat", count: 6, started: started, window: 14)
    }
    static func probeCopyExit() {
        guard let started = copyStarted, !copyExited else { return }
        copyExited = true
        probeEmit("copy_exit", sequence: 0, started: started)
    }

    private static var visibleEditors = Set<UUID>()
    // Repeated focus changes must not consume the appearance/disappearance
    // allowance. Inactive callbacks have their own allowance as well.
    private static let limits = ["lifecycle": 32, "focusVisible": 16, "focusHidden": 16,
                                 "writeVisible": 16, "writeHidden": 16]
    private static var seen: [String: Int] = [:]
    // Reserve half of each existing focus bucket for the second editor. The
    // first editor's repeated focus events cannot consume the copy's evidence.
    // Two identities at most; no reset or additional process-wide allowance.
    private static var focusEditors: [UUID] = []
    private static var focusSeen: [String: Int] = [:]
    private static var emitted: [String: Int] = [:]
    private static let testCase = String((ProcessInfo.processInfo.environment["TOUCHCOLOR_TEST_CASE"] ?? "unscoped")
        .map { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == ".") ? $0 : "_" }.prefix(120))
    private static let logger = Logger(subsystem: "com.mango.touchColor.WatchDiagnostics", category: "editor")
    private static func emit(_ kind: String, _ id: UUID, bucket: String, focused: Bool? = nil, visible: Bool) {
        seen[bucket, default: 0] += 1
        if bucket == "focusVisible" || bucket == "focusHidden" {
            guard let ordinal = focusEditors.firstIndex(of: id) else { return }
            let key = "\(ordinal).\(bucket)"
            focusSeen[key, default: 0] += 1
            guard focusSeen[key, default: 0] <= 8 else { return }
        } else {
            guard seen[bucket, default: 0] <= limits[bucket, default: 0] else { return }
        }
        guard emitted[bucket, default: 0] < limits[bucket, default: 0] else { return }
        emitted[bucket, default: 0] += 1
        let dropped = seen.reduce(0) { $0 + max(0, $1.value - emitted[$1.key, default: 0]) }
        // Only onChange(of: crownFocused) supplies a measured focus value.
        let focus = focused.map { " focused=\($0)" } ?? ""
        logger.notice("WATCH_EDITOR \(kind, privacy: .public) case=\(testCase, privacy: .public) id=\(id.uuidString, privacy: .public) visible=\(visible)\(focus, privacy: .public) active=\(visibleEditors.count) dropped=\(dropped)")
    }
    static func appeared(_ id: UUID) {
        if focusEditors.count < 2 && !focusEditors.contains(id) { focusEditors.append(id) }
        visibleEditors.insert(id); emit("appear", id, bucket: "lifecycle", visible: true)
    }
    static func disappeared(_ id: UUID) { visibleEditors.remove(id); emit("disappear", id, bucket: "lifecycle", visible: false) }
    static func focus(_ id: UUID, focused: Bool, visible: Bool) { emit("focus", id, bucket: visible ? "focusVisible" : "focusHidden", focused: focused, visible: visible) }
    static func writeback(_ id: UUID, changed: Bool, visible: Bool) { emit(changed ? "component_changed" : "component_unchanged", id, bucket: visible ? "writeVisible" : "writeHidden", visible: visible) }
}
#endif
#if DEBUG
private struct PairedWatchReadButton: View {
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        Button { transfer.samplePairedReadiness() } label: { Image(systemName: "arrow.clockwise") }
            .accessibilityLabel(Text(verbatim: "Refresh connection state"))
            .accessibilityIdentifier("watch.connection.refresh")
            .accessibilityValue(transfer.pairedReadinessValue)
    }
}
#endif
struct WatchTransferView: View {
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
#if DEBUG
                if ProcessInfo.processInfo.environment["TOUCHCOLOR_PAIRED_E2E"] == "1" {
                    PairedWatchReadButton(transfer: transfer)
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
    @State private var editingCopy = false
    let color: RGBColor
    let index: Int
    @ObservedObject var palette: WatchPalette
    @ObservedObject var transfer: WatchTransfer
    var body: some View {
        ScrollView {
            VStack {
                WatchSwatch(color: color)
                Button("Edit a Copy") {
                    // Prepare the shared working color in the user action,
                    // before requesting navigation, rather than on appearance.
                    #if DEBUG
                    WatchEditorDiagnostics.probeCopyEnter()
                    #endif
                    palette.select(color)
                    editingCopy = true
                    #if DEBUG
                    WatchEditorDiagnostics.probeCopyExit()
                    #endif
                }.accessibilityIdentifier("watch.edit.copy")
                Button("Delete", role: .destructive) { palette.remove(at: index); dismiss() }.accessibilityIdentifier("watch.delete.\(index)")
            }
        }
        .navigationDestination(isPresented: $editingCopy) {
            WatchColorEditor(palette: palette, transfer: transfer)
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
