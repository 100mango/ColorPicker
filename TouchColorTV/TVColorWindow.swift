import SwiftUI
import ColorDomain
import ColorRaster

struct TVColorWindow: View {
    @ObservedObject var library: PaletteLibrary
    @StateObject private var session = ImageSession()
    @StateObject private var photoLibrary = TVPhotoLibrary()
    @State private var photos = false
    @State private var privacy = false
    @State private var export = false
    @State private var manual = false
    @State private var selectedIndex: Int?
    @State private var selected = ColorDomain.RGBColor(red: 255, green: 0, blue: 0)
    var body: some View {
        NavigationStack {
            HStack(spacing: 32) {
                VStack(alignment: .leading) {
                    Text("Palette").font(.title2)
                    Text("\(library.colors.count)").accessibilityIdentifier("tv.palette.count")
                    List {
                        ForEach(Array(library.colors.enumerated()), id: \.offset) { index, color in
                            Button { selected = color; selectedIndex = index; export = true } label: { Text(color.hex).monospaced() }
                                .accessibilityIdentifier("tv.palette.\(index)")
                        }
                    }
                }.frame(width: 270)
                VStack(spacing: 18) {
                    HStack {
                        Button("Photos") { photos = true }.accessibilityIdentifier("tv.photos")
                        Button("Create Color") { manual = true }.accessibilityIdentifier("tv.editor")
                        Button("Privacy") { privacy = true }.accessibilityIdentifier("privacy.open")
                    }
                    if let raster = session.raster {
                        TVSamplingCanvas(raster: raster, point: session.selectedPoint, zoom: session.zoom).frame(minHeight: 250)
                        if let color = session.selectedColor {
                            HStack {
                                Text(color.hex).font(.title2.monospaced()).accessibilityIdentifier("tv.sample.hex")
                                Text(color.rgbDescription).monospacedDigit()
                                Button("Save Color") { library.append([color]) }.accessibilityIdentifier("tv.sample.save")
                                Button("Show Palette Code") { selected = color; selectedIndex = nil; export = true }.accessibilityIdentifier("tv.sample.export")
                            }
                        }
                        HStack {
                            Button("←") { session.move(dx: -1, dy: 0) }.accessibilityLabel("Previous pixel").accessibilityIdentifier("tv.sample.left")
                            Button("↑") { session.move(dx: 0, dy: -1) }.accessibilityLabel("Pixel above").accessibilityIdentifier("tv.sample.up")
                            Button("Center") { session.select(.center) }.accessibilityIdentifier("tv.sample.center")
                            Button("↓") { session.move(dx: 0, dy: 1) }.accessibilityLabel("Pixel below").accessibilityIdentifier("tv.sample.down")
                            Button("→") { session.move(dx: 1, dy: 0) }.accessibilityLabel("Next pixel").accessibilityIdentifier("tv.sample.right")
                        }
                        HStack {
                            Button("Zoom Out") { session.changeZoom(session.zoom / 2) }.accessibilityIdentifier("tv.zoom.out")
                            Text(String(format: "%.1f×", session.zoom)).monospacedDigit().accessibilityIdentifier("tv.zoom.value")
                            Button("Zoom In") { session.changeZoom(session.zoom * 2) }.accessibilityIdentifier("tv.zoom.in")
                            if let pixel = session.selectedPoint.pixel(width: raster.width, height: raster.height) { Text("x \(pixel.x), y \(pixel.y)").font(.caption) }
                        }
                    } else {
                        Spacer(); Text("Choose an image to sample colors").font(.title2); Spacer()
                    }
                    if session.busy { HStack { ProgressView(); Button("Cancel") { photoLibrary.cancel(session) } } }
                    Text("sRGB · transparent pixels on white · local palette").font(.caption)
                }
            }.padding(40).navigationTitle("TouchColor")
        }
        .sheet(isPresented: $photos) { TVPhotoBrowser(library: photoLibrary, session: session) }
        .sheet(isPresented: $privacy) { PrivacyView() }
        .sheet(isPresented: $export) { TVExportView(color: selected, index: selectedIndex, library: library) }
        .sheet(isPresented: $manual) { TVColorEditor(library: library) }
        .alert("Could Not Complete", isPresented: Binding(get: { session.errorMessage != nil || library.error != nil }, set: { if !$0 { session.errorMessage = nil; library.error = nil } })) {
            Button("OK", role: .cancel) { session.errorMessage = nil; library.error = nil }
        } message: { Text(session.errorMessage ?? library.error ?? "") }
        .onDisappear { photoLibrary.cancel(session) }
    }
}
struct TVSamplingCanvas: View {
    let raster: ColorRaster
    let point: NormalizedPoint
    let zoom: Double
    var body: some View {
        GeometryReader { viewport in
            let ratio = min(viewport.size.width / CGFloat(raster.width), viewport.size.height / CGFloat(raster.height))
            let width = CGFloat(raster.width) * ratio * zoom, height = CGFloat(raster.height) * ratio * zoom
            ZStack {
                Color.white
                Image(decorative: raster.image, scale: 1).resizable().interpolation(.none)
                    .frame(width: width, height: height)
                    .position(x: viewport.size.width / 2 + (0.5 - point.x) * width,
                              y: viewport.size.height / 2 + (0.5 - point.y) * height)
                Circle().stroke(.black, lineWidth: 4).overlay(Circle().stroke(.white, lineWidth: 2))
                    .frame(width: 18, height: 18).position(x: viewport.size.width / 2, y: viewport.size.height / 2)
            }.clipped()
        }.accessibilityLabel("Image canvas. Use the pixel controls to move the center marker.").accessibilityIdentifier("tv.canvas")
    }
}
struct TVExportView: View {
    @Environment(\.dismiss) private var dismiss
    let color: ColorDomain.RGBColor
    let index: Int?
    @ObservedObject var library: PaletteLibrary
    var body: some View {
        VStack(spacing: 28) {
            Text("Show Palette Code").font(.title)
            if let code = try? TVPaletteCode.image([color]) {
                Image(decorative: code, scale: 1).resizable().interpolation(.none).frame(width: 400, height: 400).background(.white)
                    .accessibilityLabel("QR code containing the selected palette as JSON").accessibilityIdentifier("tv.export.code")
            } else { Text("The selected color code could not be created.") }
            Text(color.hex).font(.title.monospaced())
            Text("Scan with your phone to copy the selected color.")
            if let index { Button("Delete", role: .destructive) { library.remove(at: index); dismiss() }.accessibilityIdentifier("tv.palette.delete") }
            Button("Done") { dismiss() }.accessibilityIdentifier("tv.export.close")
        }.padding(40).onExitCommand { dismiss() }
    }
}
struct TVColorEditor: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var library: PaletteLibrary
    @State private var red = 255
    @State private var green = 0
    @State private var blue = 0
    private var color: ColorDomain.RGBColor { ColorDomain.RGBColor(red: UInt8(red), green: UInt8(green), blue: UInt8(blue)) }
    var body: some View {
        VStack(spacing: 24) {
            Text(color.hex).font(.title.monospaced()).accessibilityIdentifier("tv.editor.hex")
            Text(color.rgbDescription).monospacedDigit()
            HStack {
                Button("R −") { red = max(0, red - 1) }.accessibilityIdentifier("tv.red.down")
                Button("R +") { red = min(255, red + 1) }
                Button("G −") { green = max(0, green - 1) }
                Button("G +") { green = min(255, green + 1) }
                Button("B −") { blue = max(0, blue - 1) }
                Button("B +") { blue = min(255, blue + 1) }
            }
            Button("Save Color") { library.append([color]) }.accessibilityIdentifier("tv.editor.save")
            Button("Done") { dismiss() }.accessibilityIdentifier("tv.editor.close")
        }.padding(40).onExitCommand { dismiss() }
    }
}
