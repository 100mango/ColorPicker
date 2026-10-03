import Foundation
import Combine
import PhotosUI
import UniformTypeIdentifiers
import ColorDomain
import ColorRaster

struct WatchPhotoFile: Transferable {
    let url: URL
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            let size = try received.file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size <= PreviewRaster.maximumEncodedBytes else { throw CocoaError(.fileReadTooLarge) }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-watch-import-\(UUID())")
            try FileManager.default.copyItem(at: received.file, to: url)
            return WatchPhotoFile(url: url)
        }
    }
}

@MainActor final class WatchPhotoModel: ObservableObject {
    @Published private(set) var preview: PreviewRaster?
    @Published private(set) var point = NormalizedPoint.center
    @Published private(set) var color: RGBColor?
    @Published private(set) var busy = false
    @Published var error: String?
    @Published var zoom = 1.0
    private var generation = ImportGeneration()
    private let queue: OperationQueue = {
        let q = OperationQueue(); q.name = "TouchColor.watch-preview"; q.maxConcurrentOperationCount = 1; return q
    }()
    @discardableResult func begin() -> UInt64 { queue.cancelAllOperations(); busy = true; error = nil; return generation.advance() }
    func cancel() { generation.advance(); queue.cancelAllOperations(); busy = false }
    func accepts(_ token: UInt64) -> Bool { generation.accepts(token) }
    func load(_ file: WatchPhotoFile, token: UInt64) {
        guard accepts(token) else { try? FileManager.default.removeItem(at: file.url); return }
        let work = BlockOperation()
        work.completionBlock = { try? FileManager.default.removeItem(at: file.url) }
        work.addExecutionBlock { [weak self, weak work] in
            guard let work, !work.isCancelled else { return }
            let result = Result { try PreviewRaster.read(url: file.url, cancelled: { work.isCancelled }) }
            Task { @MainActor [weak self] in
                guard let self, self.accepts(token), !work.isCancelled else { return }
                self.busy = false
                switch result {
                case .success(let preview): self.preview = preview; self.zoom = 1; self.select(.center)
                case .failure:
                    self.error = NSLocalizedString("The watch could not open this photo. Choose an image under 16 megapixels and 32 MB.", comment: "Watch photo error")
                }
            }
        }
        queue.addOperation(work)
    }
    func select(_ value: NormalizedPoint) { guard let color = preview?.sample(at: value) else { return }; point = value; self.color = color }
    func move(dx: Int, dy: Int) {
        guard let preview, let pixel = point.pixel(width: preview.width, height: preview.height) else { return }
        let x = min(preview.width - 1, max(0, pixel.x + dx)), y = min(preview.height - 1, max(0, pixel.y + dy))
        select(NormalizedPoint(x: (Double(x) + 0.5) / Double(preview.width), y: (Double(y) + 0.5) / Double(preview.height))!)
    }
}
