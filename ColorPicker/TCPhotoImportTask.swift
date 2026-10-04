import Foundation
import UIKit
import UniformTypeIdentifiers
import ColorDomain
import ColorRaster

/// The provider's borrowed file is consumed before its completion handler returns.
/// Decoding is serial; cancellation invalidates even a result queued for main delivery.
@objc(TCPhotoImportTask)
final class TCPhotoImportTask: NSObject, @unchecked Sendable {
    typealias Completion = @Sendable (UIImage?, NSError?) -> Void
    private static let startQueue = DispatchQueue(label: "com.mango.touchColor.photo-provider", qos: .userInitiated)
    private static let decodeQueue = DispatchQueue(label: "com.mango.touchColor.photo-decode", qos: .userInitiated)
    private let lock = NSLock()
    private var cancelled = false
    private var finished = false
    private var providerCallbackClaimed = false
    private var decoding = false
    private var providerProgress: Progress?
    private var coordinator: NSFileCoordinator?
    private var ownedURL: URL?
    private var completion: Completion?

    private init(completion: @escaping Completion) {
        self.completion = completion
        super.init()
    }

    @objc(loadProvider:completion:)
    static func load(provider: NSItemProvider, completion: @escaping Completion) -> TCPhotoImportTask {
        let task = TCPhotoImportTask(completion: completion)
        startQueue.async { [weak task] in task?.start(provider) }
        return task
    }

    @objc var isCancelled: Bool {
        lock.lock(); defer { lock.unlock() }
        return cancelled
    }

    @objc func cancel() {
        lock.lock()
        cancelled = true
        let progress = providerProgress
        let coordination = coordinator
        let disposable = decoding ? nil : ownedURL
        if !decoding { ownedURL = nil }
        lock.unlock()
        progress?.cancel()
        coordination?.cancel()
        if let disposable { try? FileManager.default.removeItem(at: disposable) }
        finish(image: nil, error: nil)
    }

    private func start(_ provider: NSItemProvider) {
        guard !isCancelled else { return }
        guard let identifier = provider.registeredTypeIdentifiers.first(where: {
            UTType($0)?.conforms(to: .image) == true
        }) else { finish(image: nil, error: Self.failure(RasterError.unreadable)); return }
        let progress = provider.loadFileRepresentation(forTypeIdentifier: identifier) { [weak self] url, error in
            guard let self, self.claimProviderCallback() else { return }
            guard error == nil, let url, url.isFileURL else {
                if let error = error as NSError?, error.domain == NSCocoaErrorDomain && error.code == NSUserCancelledError {
                    self.finish(image: nil, error: nil)
                } else { self.finish(image: nil, error: Self.failure(RasterError.unreadable)) }
                return
            }
            do {
                let snapshot = try self.copyProviderFile(url)
                guard self.takeOwnership(of: snapshot) else { return }
                Self.decodeQueue.async { [self] in self.decodeOwnedFile() }
            } catch {
                self.finish(image: nil, error: Self.failure(error))
            }
        }
        lock.lock()
        let shouldCancel = cancelled || finished
        if !shouldCancel { providerProgress = progress }
        lock.unlock()
        if shouldCancel { progress.cancel() }
    }

    private func claimProviderCallback() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !cancelled, !finished, !providerCallbackClaimed else { return false }
        providerCallbackClaimed = true
        return true
    }

    private func copyProviderFile(_ url: URL) throws -> URL {
        if isCancelled { throw RasterError.cancelled }
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let coordination = NSFileCoordinator(filePresenter: nil)
        lock.lock(); coordinator = coordination; let shouldCancel = cancelled; lock.unlock()
        if shouldCancel { coordination.cancel(); throw RasterError.cancelled }
        defer { lock.lock(); coordinator = nil; lock.unlock() }
        var coordinationError: NSError?
        var readError: Error?
        var snapshot: URL?
        var handedOff = false
        defer { if !handedOff, let snapshot { try? FileManager.default.removeItem(at: snapshot) } }
        coordination.coordinate(readingItemAt: url, options: .withoutChanges, error: &coordinationError) { readable in
            do {
                snapshot = try BoundedFileReader.copyToTemporaryFile(readable,
                    maximumBytes: ColorRaster.maximumEncodedBytes, cancelled: { self.isCancelled })
            } catch { readError = error }
        }
        if isCancelled { throw RasterError.cancelled }
        if let readError { throw readError }
        if let coordinationError { throw coordinationError }
        guard let snapshot else { throw RasterError.unreadable }
        handedOff = true
        return snapshot
    }

    private func takeOwnership(of url: URL) -> Bool {
        lock.lock()
        let accepted = !cancelled && !finished
        if accepted { ownedURL = url }
        lock.unlock()
        if !accepted { try? FileManager.default.removeItem(at: url) }
        return accepted
    }

    private func decodeOwnedFile() {
        lock.lock()
        guard !cancelled, !finished, let url = ownedURL else { lock.unlock(); return }
        decoding = true
        lock.unlock()
        var result: UIImage?
        var failure: NSError?
        do {
            let raster = try ColorRaster.read(url: url, cancelled: { self.isCancelled })
            if isCancelled { throw RasterError.cancelled }
            // ColorRaster applies EXIF orientation at the ORIGINAL dimensions and
            // asserts those dimensions. No display-preview raster is used here.
            result = UIImage(cgImage: raster.image, scale: 1, orientation: .up)
        } catch { failure = Self.failure(error) }
        lock.lock(); ownedURL = nil; decoding = false; lock.unlock()
        try? FileManager.default.removeItem(at: url)
        finish(image: result, error: failure)
    }

    private func finish(image: UIImage?, error: NSError?) {
        lock.lock()
        guard !finished else { lock.unlock(); return }
        finished = true
        let callback = completion
        completion = nil
        providerProgress = nil
        lock.unlock()
        DispatchQueue.main.async { [self] in
            if isCancelled { callback?(nil, nil) }
            else { callback?(image, error) }
        }
    }

    private static func failure(_ error: Error) -> NSError? {
        if let error = error as? RasterError {
            if case .cancelled = error { return nil }
            return error as NSError
        }
        if let error = error as? BoundedFileReadError {
            if case .cancelled = error { return nil }
            if case .tooLarge = error { return RasterError.tooLarge as NSError }
        }
        return RasterError.unreadable as NSError
    }

    deinit {
        providerProgress?.cancel()
        coordinator?.cancel()
        if let ownedURL { try? FileManager.default.removeItem(at: ownedURL) }
    }
}
