import SwiftUI
import UIKit
import Photos
import ColorRaster

@MainActor final class TVPhotoLibrary: ObservableObject {
    @Published private(set) var assets: [PHAsset] = []
    @Published private(set) var status = ""
    @Published private(set) var authorized = false
    @Published private(set) var hasMore = false
    @Published private(set) var hasPrevious = false
    private var page = 0
    private var activeRequest: PHAssetResourceDataRequestID?
    private var activeFile: BoundedImageFile?
    func open() {
        let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        if current == .notDetermined {
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { [weak self] _ in Task { @MainActor in self?.reload() } }
        } else { reload() }
    }
    func more() { page += 1; reload() }
    func previous() { page = max(0, page - 1); reload() }
    func cancel(_ session: ImageSession) {
        if let activeRequest { PHAssetResourceManager.default().cancelDataRequest(activeRequest) }
        activeRequest = nil; activeFile?.cancel(); activeFile = nil; session.cancelImport()
    }
    func reload() {
        let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        authorized = current == .authorized || current == .limited
        guard authorized else { assets = []; status = NSLocalizedString("Photo access is unavailable. You can enable it in Settings, or create a color without a photo.", comment: "TV photos status"); return }
        let options = PHFetchOptions(); options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]; options.fetchLimit = (page + 1) * 128 + 1
        let result = PHAsset.fetchAssets(with: .image, options: options)
        hasPrevious = page > 0; hasMore = result.count > (page + 1) * 128
        let start = min(page * 128, result.count), end = min(result.count, (page + 1) * 128)
        assets = (start..<end).map { result.object(at: $0) }
        status = assets.isEmpty ? NSLocalizedString("No photos are available in this TV library.", comment: "TV photos status") : ""
    }
    func load(_ asset: PHAsset, into session: ImageSession) {
        cancel(session)
        let token = session.beginImport(), cancelled = session.cancellationCheck(for: token)
        let resources = PHAssetResource.assetResources(for: asset)
        // fullSizePhoto is the current edited photo; photo is the original fallback.
        guard let resource = resources.first(where: { $0.type == .fullSizePhoto }) ?? resources.first(where: { $0.type == .photo }) else {
            session.report(RasterError.unreadable, token: token); return
        }
        do {
            let file = try BoundedImageFile(); activeFile = file
            let options = PHAssetResourceRequestOptions(); options.isNetworkAccessAllowed = true
            activeRequest = PHAssetResourceManager.default().requestData(for: resource, options: options) { [weak self] chunk in
                do {
                    guard !cancelled() else { file.cancel(); return }
                    try file.append(chunk)
                } catch {
                    file.cancel(error: error)
                    Task { @MainActor in
                        guard session.isCurrent(token) else { return }
                        if let request = self?.activeRequest { PHAssetResourceManager.default().cancelDataRequest(request) }
                        self?.activeRequest = nil; self?.activeFile = nil
                        session.report(error, token: token)
                    }
                }
            } completionHandler: { [weak self] error in
                if let error { file.cancel(error: error) }
                let result = Result { () throws -> URL in
                    guard !cancelled() else { throw RasterError.cancelled }
                    return try file.finish()
                }
                if case .failure = result { file.cancel() }
                Task { @MainActor in
                    guard session.isCurrent(token) else {
                        if case .success(let url) = result { try? FileManager.default.removeItem(at: url) }; return
                    }
                    self?.activeRequest = nil; self?.activeFile = nil
                    switch result {
                    case .success(let url): session.loadOwnedFile(url, name: NSLocalizedString("Selected photo", comment: "Source name"), token: token)
                    case .failure(let error): session.report(error, token: token)
                    }
                }
            }
        } catch { session.report(error, token: token) }
    }

}
struct TVPhotoThumb: View {
    let asset: PHAsset
    @State private var image: UIImage?
    @State private var request = PHInvalidImageRequestID
    var body: some View {
        Group { if let image { Image(uiImage: image).resizable().scaledToFit() } else { Image(systemName: "photo").font(.largeTitle) } }
            .frame(width: 220, height: 150)
            .onAppear {
                let options = PHImageRequestOptions(); options.deliveryMode = .fastFormat; options.isNetworkAccessAllowed = false
                request = PHImageManager.default().requestImage(for: asset, targetSize: CGSize(width: 220, height: 150), contentMode: .aspectFit, options: options) { image, _ in
                    Task { @MainActor in self.image = image }
                }
            }
            .onDisappear { PHImageManager.default().cancelImageRequest(request) }
    }
}
struct TVPhotoBrowser: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var library: TVPhotoLibrary
    @ObservedObject var session: ImageSession
    var body: some View {
        VStack {
            HStack { Text("Photos").font(.title); Spacer(); Button("Done") { dismiss() }.accessibilityIdentifier("tv.photos.close") }
            if !library.status.isEmpty { Text(library.status).accessibilityIdentifier("tv.photos.status") }
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 250))], spacing: 24) {
                    ForEach(Array(library.assets.enumerated()), id: \.element.localIdentifier) { index, asset in
                        Button { library.load(asset, into: session); dismiss() } label: { TVPhotoThumb(asset: asset) }
                            .accessibilityLabel(Text("Photo \(index + 1)")).accessibilityIdentifier("tv.photo.\(index)")
                    }
                }.focusSection()
                HStack {
                    if library.hasPrevious { Button("Previous Photos") { library.previous() } }
                    if library.hasMore { Button("More Photos") { library.more() } }
                }
            }.focusSection()
            Button("Retry") { library.open() }
        }.padding(40).frame(width: 1200, height: 760).onAppear { library.open() }.onExitCommand { dismiss() }
    }
}
