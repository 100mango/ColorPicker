import AppKit
import ColorDomain
import ColorRaster
import ColorPaletteLegacy

/// A window owns its source, selection and pending import. Only the palette is shared locally.
@MainActor final class ImageSession: ObservableObject {
    @Published private(set) var raster: ColorRaster?
    @Published private(set) var selectedPoint: NormalizedPoint = .center
    @Published private(set) var selectedColor: RGBColor?
    @Published private(set) var sourceName = ""
    @Published private(set) var busy = false
    @Published var zoom = 1.0
    @Published var errorMessage: String?
    @Published var notice: String?
    private var generation = ImportGeneration()
    // Bounded work: one decode at a time; replaced pending operations are cancelled.
    private let work: OperationQueue = {
        let queue = OperationQueue(); queue.name = "TouchColor.image-import"
        queue.maxConcurrentOperationCount = 1; queue.qualityOfService = .userInitiated
        return queue
    }()

    @discardableResult func beginImport() -> UInt64 {
        work.cancelAllOperations()
        busy = true; errorMessage = nil; notice = nil
        return generation.advance()
    }
    func isCurrent(_ token: UInt64) -> Bool { generation.accepts(token) }
    func cancelImport() {
        generation.advance(); work.cancelAllOperations(); busy = false
        notice = "Import cancelled. Your current image is unchanged."
    }
    func report(_ error: Error, token: UInt64) {
        guard isCurrent(token) else { return }
        busy = false
        if case RasterError.cancelled = error { return }
        errorMessage = error.localizedDescription
    }
    func load(data: Data, name: String, token: UInt64) {
        enqueue(name: name, token: token) { cancelled in try ColorRaster.decode(data, cancelled: cancelled) }
    }
    func load(url: URL, token: UInt64) {
        enqueue(name: url.lastPathComponent, token: token) { cancelled in
            let granted = url.startAccessingSecurityScopedResource()
            defer { if granted { url.stopAccessingSecurityScopedResource() } }
            return try ColorRaster.read(url: url, cancelled: cancelled)
        }
    }
    private func enqueue(name: String, token: UInt64,
                         decode: @escaping (@escaping () -> Bool) throws -> ColorRaster) {
        guard isCurrent(token) else { return }
        let operation = BlockOperation()
        operation.addExecutionBlock { [weak self, weak operation] in
            guard let operation, !operation.isCancelled else { return }
            let result = Result { try decode { operation.isCancelled } }
            guard !operation.isCancelled else { return }
            Task { @MainActor [weak self] in
                guard let self, self.isCurrent(token) else { return }
                self.busy = false
                switch result {
                case .success(let raster):
                    self.raster = raster; self.sourceName = name; self.zoom = 1
                    self.select(.center)
                case .failure(let error): self.report(error, token: token)
                }
            }
        }
        work.addOperation(operation)
    }
    func select(_ point: NormalizedPoint) {
        guard let color = raster?.sample(at: point) else { return }
        selectedPoint = point; selectedColor = color
    }
    func move(dx: Int, dy: Int) {
        guard let raster, let pixel = selectedPoint.pixel(width: raster.width, height: raster.height) else { return }
        let x = min(raster.width - 1, max(0, pixel.x + dx))
        let y = min(raster.height - 1, max(0, pixel.y + dy))
        select(NormalizedPoint(x: (Double(x) + 0.5) / Double(raster.width), y: (Double(y) + 0.5) / Double(raster.height))!)
    }
    func changeZoom(_ value: Double) { zoom = ColorZoom.clamped(value) }
    func finishPaletteImport(_ data: Data, token: UInt64, library: PaletteLibrary) {
        guard isCurrent(token) else { return }
        do {
            let colors = try PaletteFile.decode(data)
            library.append(colors); busy = false
            notice = "Imported \(colors.count) colors. Existing colors and duplicates were kept."
        } catch { report(error, token: token) }
    }
    func exportPNG(to url: URL) {
        guard let raster else { return }
        // Export owns an immutable source snapshot; subsequent imports cannot change its output.
        work.addOperation { [weak self] in
            do {
                let data = try raster.pngData()
                try data.write(to: url, options: .atomic)
                Task { @MainActor [weak self] in self?.notice = "Exported full-size PNG: \(url.lastPathComponent)" }
            } catch {
                Task { @MainActor [weak self] in self?.errorMessage = error.localizedDescription }
            }
        }
    }
}
