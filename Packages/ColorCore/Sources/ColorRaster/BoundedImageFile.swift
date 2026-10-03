import Foundation

/// Progressive PhotoKit/provider bytes go straight to a temporary file. No complete
/// encoded image is accumulated in memory. Ownership transfers only on successful finish.
public final class BoundedImageFile: @unchecked Sendable {
    public let url: URL
    private let maximumBytes: Int
    private let lock = NSLock()
    private var output: FileHandle?
    private var count = 0
    private var handedOff = false
    private var failure: Error?
    public init(maximumBytes: Int = ColorRaster.maximumEncodedBytes, directory: URL = FileManager.default.temporaryDirectory) throws {
        guard maximumBytes > 0 else { throw RasterError.tooLarge }
        self.maximumBytes = maximumBytes
        url = directory.appendingPathComponent("TouchColor-stream-\(UUID()).image")
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else { throw RasterError.unreadable }
        do { output = try FileHandle(forWritingTo: url) }
        catch { try? FileManager.default.removeItem(at: url); throw error }
    }
    public func append(_ data: Data) throws {
        lock.lock(); defer { lock.unlock() }
        if let failure { throw failure }
        guard let output, !handedOff else { throw RasterError.cancelled }
        guard data.count <= maximumBytes, count <= maximumBytes - data.count else { throw RasterError.tooLarge }
        try output.write(contentsOf: data); count += data.count
    }
    public func finish() throws -> URL {
        lock.lock(); defer { lock.unlock() }
        if let failure { throw failure }
        guard let output, !handedOff else { throw RasterError.cancelled }
        try output.close(); self.output = nil; handedOff = true
        return url
    }
    public func cancel(error: Error = RasterError.cancelled) {
        lock.lock(); defer { lock.unlock() }
        guard !handedOff else { return }
        if failure == nil { failure = error }
        try? output?.close(); output = nil
        try? FileManager.default.removeItem(at: url)
    }
    deinit { cancel() }
}
