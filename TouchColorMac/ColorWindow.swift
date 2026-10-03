import SwiftUI
import PhotosUI
import ColorDomain

struct ColorWindow: View {
    @ObservedObject var library: PaletteLibrary
    @StateObject private var session = ImageSession()
    @State private var photo: PhotosPickerItem?
    @State private var showingPrivacy = false
    @State private var targeted = false

    var body: some View {
        NavigationSplitView {
            PaletteSidebar(library: library, session: session)
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 300)
        } detail: {
            VStack(spacing: 0) {
                if session.raster != nil {
                    ImageCanvas(session: session)
                        .frame(minHeight: 160, maxHeight: .infinity)
                        .layoutPriority(-1)
                        .overlay(alignment: .topLeading) {
                            Text(session.sourceName).padding(8).background(.regularMaterial).padding(8).allowsHitTesting(false)
                        }
                } else {
                    VStack(spacing: 18) {
                        Image(systemName: "eyedropper.halffull").font(.system(size: 50)).foregroundStyle(.secondary)
                        Text("Choose an image to sample colors").font(.title2)
                        Text("Open a file, choose a photo, drop an image here, or paste an image.")
                            .foregroundStyle(.secondary).multilineTextAlignment(.center)
                        Button("Open Image…") { MacImportExport.open(session: session, library: library) }
                            .accessibilityIdentifier("image.open.empty")
                    }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(30)
                }
                Divider()
                SamplingControls(session: session, library: library).fixedSize(horizontal: false, vertical: true)
                Divider()
                HStack {
                    if session.busy {
                        ProgressView().controlSize(.small)
                        Text("Opening full-resolution image…")
                        Button("Cancel") { session.cancelImport(); photo = nil }.accessibilityIdentifier("image.cancel")
                    } else if session.exporting {
                        ProgressView().controlSize(.small)
                        Text("Exporting full-resolution image…")
                    } else { Text(session.notice ?? NSLocalizedString("sRGB · transparent pixels on white · local palette", comment: "Sampling policy")) }
                    Spacer()
                }.font(.caption).padding(8).background(.bar).fixedSize(horizontal: false, vertical: true)
            }
            .overlay { if targeted { RoundedRectangle(cornerRadius: 8).stroke(.blue, lineWidth: 3).allowsHitTesting(false) } }
            .onDrop(of: [.fileURL, .image], isTargeted: $targeted) { MacImportExport.drop($0, session: session, library: library) }
        }
        .navigationSplitViewStyle(.balanced)
        .toolbar {
            Button { MacImportExport.open(session: session, library: library) } label: { Label("Open", systemImage: "folder") }
                .accessibilityIdentifier("image.open")
            PhotosPicker(selection: $photo, matching: .images, preferredItemEncoding: .current) { Label("Photos", systemImage: "photo") }
                .accessibilityIdentifier("image.photos")
            Button { MacImportExport.paste(session: session, library: library) } label: { Label("Paste Image", systemImage: "doc.on.clipboard") }
                .accessibilityIdentifier("image.paste")
            Button { MacImportExport.exportImage(session: session) } label: { Label("Export PNG", systemImage: "square.and.arrow.up") }
                .disabled(session.raster == nil || session.exporting).accessibilityIdentifier("image.export")
            Button { showingPrivacy = true } label: { Label("Privacy", systemImage: "hand.raised") }
                .accessibilityIdentifier("privacy.open")
        }
        .focusedSceneValue(\.colorSession, session)
        .focusedSceneValue(\.colorLibrary, library)
        .alert("Could Not Complete", isPresented: Binding(get: { session.errorMessage != nil }, set: { if !$0 { session.errorMessage = nil } })) {
            Button("OK", role: .cancel) { session.errorMessage = nil }
        } message: { Text(session.errorMessage ?? "") }
        .sheet(isPresented: $showingPrivacy) { PrivacyView() }
        .task(id: photo) { await importPhoto() }
        .onDisappear { session.cancelImport() }
    }
    private func importPhoto() async {
        guard let photo else { return }
        // Clear only this selection so choosing the same photo again retries after failure/cancel.
        defer { if self.photo == photo { self.photo = nil } }
        let token = session.beginImport()
        do {
            guard let data = try await photo.loadTransferable(type: Data.self) else { throw CocoaError(.fileReadUnknown) }
            guard !Task.isCancelled, session.isCurrent(token) else { return }
            session.load(data: data, name: NSLocalizedString("Selected photo", comment: "Imported photo name"), token: token)
        } catch { if !Task.isCancelled { session.report(error, token: token) } }
    }
}

private struct SamplingControls: View {
    @ObservedObject var session: ImageSession
    @ObservedObject var library: PaletteLibrary
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                if let color = session.selectedColor {
                    Color(red: Double(color.red) / 255, green: Double(color.green) / 255, blue: Double(color.blue) / 255)
                        .frame(width: 38, height: 38).border(.gray.opacity(0.6)).accessibilityHidden(true)
                    VStack(alignment: .leading) {
                        Text(color.hex).font(.title2.monospaced()).accessibilityIdentifier("sample.hex")
                        Text(color.rgbDescription).font(.callout.monospacedDigit()).accessibilityIdentifier("sample.rgb")
                    }
                } else { Text("No color selected").foregroundStyle(.secondary) }
                Spacer()
                Button("Copy") { if let color = session.selectedColor { library.copy(color) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.copy")
                Button("Save Color") { if let color = session.selectedColor { library.append([color]) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.save")
            }
            HStack {
                Button("−") { session.changeZoom(session.zoom / 2) }.accessibilityLabel("Zoom out").accessibilityIdentifier("sample.zoom.out")
                Slider(value: Binding(get: { session.zoom }, set: { session.changeZoom($0) }), in: ColorZoom.range)
                    .accessibilityLabel("Image zoom").accessibilityIdentifier("sample.zoom")
                Button("+") { session.changeZoom(session.zoom * 2) }.accessibilityLabel("Zoom in").accessibilityIdentifier("sample.zoom.in")
                Text(String(format: "%.1f×", session.zoom)).monospacedDigit().frame(width: 55).accessibilityIdentifier("sample.zoom.value")
                Button("Center") { session.select(.center) }.accessibilityIdentifier("sample.center")
            }.disabled(session.raster == nil)
            if let raster = session.raster, let pixel = session.selectedPoint.pixel(width: raster.width, height: raster.height) {
                HStack {
                    Text("\(raster.width) × \(raster.height) pixels · x \(pixel.x), y \(pixel.y)")
                        .font(.caption.monospacedDigit()).accessibilityIdentifier("sample.pixel")
                    Spacer()
                    Button("←") { session.move(dx: -1, dy: 0) }.accessibilityLabel("Previous pixel").accessibilityIdentifier("sample.previous")
                    Button("↑") { session.move(dx: 0, dy: -1) }.accessibilityLabel("Pixel above").accessibilityIdentifier("sample.above")
                    Button("↓") { session.move(dx: 0, dy: 1) }.accessibilityLabel("Pixel below").accessibilityIdentifier("sample.below")
                    Button("→") { session.move(dx: 1, dy: 0) }.accessibilityLabel("Next pixel").accessibilityIdentifier("sample.next")
                }
            }
        }.padding(16)
    }
}
