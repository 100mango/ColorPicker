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
    private var activeRequest = PHInvalidImageRequestID
    func open() {
        let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        if current == .notDetermined {
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { [weak self] _ in Task { @MainActor in self?.reload() } }
        } else { reload() }
    }
    func more() { page += 1; reload() }
    func previous() { page = max(0, page - 1); reload() }
    func cancel(_ session: ImageSession) { PHImageManager.default().cancelImageRequest(activeRequest); session.cancelImport() }
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
        PHImageManager.default().cancelImageRequest(activeRequest)
        let token = session.beginImport()
        let options = PHImageRequestOptions(); options.deliveryMode = .highQualityFormat; options.version = .current; options.isNetworkAccessAllowed = true
        activeRequest = PHImageManager.default().requestImageDataAndOrientation(for: asset, options: options) { data, _, _, info in
            Task { @MainActor in
                guard session.isCurrent(token) else { return }
                if let data { session.load(data: data, name: NSLocalizedString("Selected photo", comment: "Source name"), token: token) }
                else { session.report((info?[PHImageErrorKey] as? Error) ?? CocoaError(.fileReadUnknown), token: token) }
            }
        }
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
                }
                HStack {
                    if library.hasPrevious { Button("Previous Photos") { library.previous() } }
                    if library.hasMore { Button("More Photos") { library.more() } }
                }
            }
            Button("Retry") { library.open() }
        }.padding(40).frame(width: 1200, height: 760).onAppear { library.open() }.onExitCommand { dismiss() }
    }
}
