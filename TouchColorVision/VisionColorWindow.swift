import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import ColorDomain
import ColorPaletteLegacy

struct VisionColorWindow: View {
    @ObservedObject var library: PaletteLibrary
    @StateObject private var session = ImageSession()
    @State private var photo: PhotosPickerItem?
    @State private var importing = false
    @State private var privacy = false
    @State private var exporting = false
    @State private var preparingExport = false
    @State private var exportType = UTType.json
    @State private var exportDocument: ColorExportDocument?
    @State private var lastExport: URL?
    var body: some View {
        NavigationSplitView {
            List {
                HStack { Text("Palette"); Spacer(); Text("\(library.colors.count)").accessibilityIdentifier("palette.count") }
                ForEach(Array(library.colors.enumerated()), id: \.offset) { index, color in
                    HStack {
                        Color(red: Double(color.red)/255, green: Double(color.green)/255, blue: Double(color.blue)/255)
                            .frame(width: 36, height: 36).accessibilityHidden(true)
                        VStack(alignment: .leading) {
                            Text(color.hex).monospaced()
                            Text(color.rgbDescription).font(.caption.monospacedDigit())
                        }
                        Spacer()
                        Menu {
                            Button("Copy") { library.copy(color) }.accessibilityIdentifier("palette.copy.\(index)")
                            Button("Delete", role: .destructive) { library.remove(at: index) }
                                .accessibilityIdentifier("palette.delete.\(index)")
                        } label: { Image(systemName: "ellipsis.circle") }
                            .accessibilityLabel(Text("Actions for color \(index + 1)"))
                            .accessibilityIdentifier("palette.actions.\(index)")
                    }
                }
                Button("Export Palette…") { preparePaletteExport() }.disabled(library.colors.isEmpty)
                    .accessibilityIdentifier("palette.export")
            }.navigationTitle("Palette").navigationSplitViewColumnWidth(min: 240, ideal: 260, max: 320)
        } detail: {
            VStack(spacing: 12) {
                if session.raster != nil {
                    VisionCanvas(session: session).frame(minHeight: 220)
                        .overlay(alignment: .topLeading) { Text(session.sourceName).font(.caption).lineLimit(1).padding(12).allowsHitTesting(false) }
                } else {
                    VStack(spacing: 20) {
                        Image(systemName: "eyedropper.halffull").font(.system(size: 56))
                        Text("Choose an image to sample colors").font(.title2)
                        Text("Open a file, choose a photo, drop an image here, or paste an image.")
                            .multilineTextAlignment(.center).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(24)
                }
                VisionSamplingControls(session: session, library: library)
                HStack {
                    if session.busy {
                        ProgressView(); Text("Opening full-resolution image…")
                        Button("Cancel") { session.cancelImport(); photo = nil }.accessibilityIdentifier("image.cancel")
                    } else if preparingExport { ProgressView(); Text("Exporting full-resolution image…") }
                    else { Text(session.notice ?? NSLocalizedString("sRGB · transparent pixels on white · local palette", comment: "Sampling policy")) }
                    Spacer()
                    if let lastExport { Button("Reopen Export") { VisionImport.file(lastExport, session: session, library: library) }.accessibilityIdentifier("export.reopen") }
                }.font(.caption).lineLimit(2)
            }.padding(16)
                .onDrop(of: [.image], isTargeted: nil) { VisionImport.providers($0, session: session) }
                .navigationTitle("TouchColor")
                .toolbar {
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        Button { importing = true } label: { Label("Open", systemImage: "folder") }.accessibilityIdentifier("image.open")
                        PhotosPicker(selection: $photo, matching: .images, preferredItemEncoding: .current) { Label("Photos", systemImage: "photo") }
                            .accessibilityIdentifier("image.photos")
                        PasteButton(supportedContentTypes: [.image]) { _ = VisionImport.providers($0, session: session) }
                            .accessibilityIdentifier("image.paste")
                        Button { prepareImageExport() } label: { Label("Export PNG", systemImage: "square.and.arrow.up") }
                            .disabled(session.raster == nil || preparingExport).accessibilityIdentifier("image.export")
                        Button { privacy = true } label: { Label("Privacy", systemImage: "hand.raised") }.accessibilityIdentifier("privacy.open")
                    }
                }
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.image, .json]) { result in
            switch result {
            case .success(let url): VisionImport.file(url, session: session, library: library)
            case .failure(let error):
                if (error as NSError).code != NSUserCancelledError { session.errorMessage = error.localizedDescription }
            }
        }
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: exportType,
                      defaultFilename: exportType == .png ? "TouchColor Image" : "TouchColor Palette") { result in
            switch result {
            case .success(let url): lastExport = url; session.notice = NSLocalizedString("Export completed.", comment: "Export status")
            case .failure(let error):
                if (error as NSError).code != NSUserCancelledError { session.errorMessage = error.localizedDescription }
            }
            exportDocument = nil
        }
        .alert("Could Not Complete", isPresented: Binding(get: { session.errorMessage != nil }, set: { if !$0, session.errorMessage != nil { session.errorMessage = nil } })) {
            Button("OK", role: .cancel) { session.errorMessage = nil }
        } message: { Text(session.errorMessage ?? "") }
        .sheet(isPresented: $privacy) { PrivacyView() }
        .task(id: photo) {
            guard let selected = photo else { return }
            defer { if photo == selected { photo = nil } }
            let token = session.beginImport()
            do {
                guard let file = try await selected.loadTransferable(type: NativePhotoFile.self) else { throw CocoaError(.fileReadUnknown) }
                guard !Task.isCancelled, session.isCurrent(token) else { try? FileManager.default.removeItem(at: file.url); return }
                session.loadOwnedFile(file.url, name: NSLocalizedString("Selected photo", comment: "Source name"), token: token)
            } catch { if !Task.isCancelled { session.report(error, token: token) } }
        }
        .onDisappear { session.cancelImport() }
    }
    private func preparePaletteExport() {
        do { exportDocument = ColorExportDocument(data: try PaletteFile.encode(library.colors)); exportType = .json; exporting = true }
        catch { session.errorMessage = error.localizedDescription }
    }
    private func prepareImageExport() {
        guard let raster = session.raster, !preparingExport else { return }
        preparingExport = true
        Task {
            let result = await Task.detached(priority: .userInitiated) { Result { try raster.pngData() } }.value
            preparingExport = false
            switch result {
            case .success(let data): exportDocument = ColorExportDocument(data: data); exportType = .png; exporting = true
            case .failure(let error): session.errorMessage = error.localizedDescription
            }
        }
    }
}

private struct VisionSamplingControls: View {
    @ObservedObject var session: ImageSession
    @ObservedObject var library: PaletteLibrary
    var body: some View {
        VStack(spacing: 12) {
            HStack {
                if let color = session.selectedColor {
                    Color(red: Double(color.red)/255, green: Double(color.green)/255, blue: Double(color.blue)/255)
                        .frame(width: 44, height: 44).accessibilityHidden(true)
                    VStack(alignment: .leading) {
                        Text(color.hex).font(.title2.monospaced()).accessibilityIdentifier("sample.hex")
                        Text(color.rgbDescription).monospacedDigit().accessibilityIdentifier("sample.rgb")
                    }
                } else { Text("No color selected") }
                Spacer()
                Button("Copy") { if let color = session.selectedColor { library.copy(color) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.copy")
                Button("Save Color") { if let color = session.selectedColor { library.append([color]) } }
                    .disabled(session.selectedColor == nil).accessibilityIdentifier("sample.save")
            }
            HStack {
                Button("−") { session.changeZoom(session.zoom / 2) }.accessibilityLabel("Zoom out").accessibilityIdentifier("sample.zoom.out")
                Slider(value: Binding(get: { session.zoom }, set: { session.changeZoom($0) }), in: ColorZoom.range).accessibilityLabel("Image zoom")
                Button("+") { session.changeZoom(session.zoom * 2) }.accessibilityLabel("Zoom in").accessibilityIdentifier("sample.zoom.in")
                Text(String(format: "%.1f×", session.zoom)).monospacedDigit().accessibilityIdentifier("sample.zoom.value")
                Button("Center") { session.select(.center) }.accessibilityIdentifier("sample.center")
            }.disabled(session.raster == nil)
            if let raster = session.raster, let pixel = session.selectedPoint.pixel(width: raster.width, height: raster.height) {
                HStack {
                    Text("\(raster.width) × \(raster.height) pixels · x \(pixel.x), y \(pixel.y)").font(.caption.monospacedDigit())
                    Spacer()
                    Button("←") { session.move(dx: -1, dy: 0) }.accessibilityLabel("Previous pixel").accessibilityIdentifier("sample.previous")
                    Button("↑") { session.move(dx: 0, dy: -1) }.accessibilityLabel("Pixel above").accessibilityIdentifier("sample.above")
                    Button("↓") { session.move(dx: 0, dy: 1) }.accessibilityLabel("Pixel below").accessibilityIdentifier("sample.below")
                    Button("→") { session.move(dx: 1, dy: 0) }.accessibilityLabel("Next pixel").accessibilityIdentifier("sample.next")
                }
            }
        }.buttonStyle(.bordered).fixedSize(horizontal: false, vertical: true)
    }
}
