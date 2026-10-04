import SwiftUI
import PhotosUI
import ColorDomain

struct ColorWindow: View {
    @ObservedObject var library: PaletteLibrary
    @StateObject private var session: ImageSession
    @State private var photo: PhotosPickerItem?
    @State private var showingPrivacy = false
    @State private var showingCamera = false
    @State private var targeted = false
    private var ownsModalPresentation: Bool { showingPrivacy || showingCamera || session.errorMessage != nil }

    @MainActor init(library: PaletteLibrary, session: ImageSession? = nil) {
        self.library = library
        _session = StateObject(wrappedValue: session ?? ImageSession())
    }

    var body: some View {
        NavigationSplitView {
            PaletteSidebar(library: library, session: session)
                // A sheet dims and blocks the workspace. Its inactive content must
                // also leave VoiceOver navigation until the sheet is dismissed.
                .accessibilityHidden(ownsModalPresentation)
                .background(NativePaneAccessibility(label: NSLocalizedString("Saved color palette", comment: "Palette pane accessibility"), identifier: "workspace.palette"))
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 300)
        } detail: {
            VStack(spacing: 0) {
                if session.raster != nil {
                    GeometryReader { viewport in
                        ImageCanvas(session: session)
                            .frame(width: viewport.size.width, height: viewport.size.height)
                            .clipped()
                            .overlay(alignment: .topLeading) {
                                Text(session.sourceName).lineLimit(1).help(session.sourceName).padding(8).background(.regularMaterial).padding(8).allowsHitTesting(false)
                            }
                    }
                    .frame(minHeight: 160, maxHeight: .infinity)
                } else {
                    VStack(spacing: 18) {
                        Image(systemName: "eyedropper.halffull").font(.system(size: 50)).foregroundStyle(.secondary).accessibilityHidden(true)
                        Text("Choose an image to sample colors").font(.title2).lineLimit(2)
                        Text("Open a file, choose a photo, drop an image here, or paste an image.")
                            .foregroundStyle(.primary).multilineTextAlignment(.center).lineLimit(3)
                        Button("Open Image…") { MacImportExport.open(session: session, library: library) }
                            .accessibilityIdentifier("image.open.empty")
                    }.frame(minWidth: 320, maxWidth: .infinity, maxHeight: .infinity).padding(30)
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
                }.font(.caption).lineLimit(2).padding(8).background(.bar).fixedSize(horizontal: false, vertical: true)
            }
            .frame(minWidth: 420, maxWidth: .infinity, maxHeight: .infinity)
            .overlay { if targeted { RoundedRectangle(cornerRadius: 8).stroke(.blue, lineWidth: 3).allowsHitTesting(false) } }
            .onDrop(of: [.fileURL, .image], isTargeted: $targeted) { MacImportExport.drop($0, session: session, library: library) }
            .accessibilityHidden(ownsModalPresentation)
            .background(NativePaneAccessibility(label: NSLocalizedString("Image color sampler", comment: "Sampler pane accessibility"), identifier: "workspace.sampler"))
        }
        .navigationSplitViewStyle(.balanced)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("TouchColor workspace")
        .toolbar {
            Button { MacImportExport.open(session: session, library: library) } label: { Label("Open", systemImage: "folder") }
                .accessibilityIdentifier("image.open")
            PhotosPicker(selection: $photo, matching: .images, preferredItemEncoding: .current) { Label("Photos", systemImage: "photo") }
                .accessibilityIdentifier("image.photos")
            Button { MacImportExport.paste(session: session, library: library) } label: { Label("Paste Image", systemImage: "doc.on.clipboard") }
                .accessibilityIdentifier("image.paste")
            Button { MacImportExport.exportImage(session: session) } label: { Label("Export PNG", systemImage: "square.and.arrow.up") }
                .disabled(session.raster == nil || session.exporting).accessibilityIdentifier("image.export")
            Button { showingCamera = true } label: { Label("Camera", systemImage: "camera") }
                .accessibilityIdentifier("camera.open")
            Button { showingPrivacy = true } label: { Label("Privacy", systemImage: "hand.raised") }
                .accessibilityIdentifier("privacy.open")
        }
        .focusedSceneValue(\.colorSession, session)
        .focusedSceneValue(\.colorLibrary, library)
        .alert("Could Not Complete", isPresented: Binding(get: { session.errorMessage != nil }, set: { if !$0, session.errorMessage != nil { session.errorMessage = nil } })) {
            Button("OK", role: .cancel) { session.errorMessage = nil }
        } message: { Text(session.errorMessage ?? "") }
        .sheet(isPresented: $showingPrivacy) { PrivacyView() }
        .sheet(isPresented: $showingCamera) {
            CameraSheet(library: library) { data in
                session.load(data: data, name: NSLocalizedString("Camera video frame", comment: "Source name"), token: session.beginImport())
            }
        }
        .task(id: photo) { await importPhoto() }
        .onDisappear { session.cancelImport() }
    }
    private func importPhoto() async {
        guard let photo else { return }
        // Clear only this selection so choosing the same photo again retries after failure/cancel.
        defer { if self.photo == photo { self.photo = nil } }
        let token = session.beginImport()
        do {
            guard let file = try await photo.loadTransferable(type: NativePhotoFile.self) else { throw CocoaError(.fileReadUnknown) }
            guard !Task.isCancelled, session.isCurrent(token) else { try? FileManager.default.removeItem(at: file.url); return }
            session.loadOwnedFile(file.url, name: NSLocalizedString("Selected photo", comment: "Imported photo name"), token: token)
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
                } else { Text("No color selected").foregroundStyle(.primary) }
                Spacer()
                Button("Copy") { if let color = session.selectedColor { library.copy(color) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.copy")
                Button("Save Color") { if let color = session.selectedColor { library.append([color]) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.save")
            }
            HStack {
                Button("−") { session.changeZoom(session.zoom / 2) }.accessibilityLabel("Zoom out").accessibilityIdentifier("sample.zoom.out")
                NativeZoomSlider(value: Binding(get: { session.zoom }, set: { session.changeZoom($0) }))
                    .frame(maxWidth: .infinity).frame(height: 24)
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
