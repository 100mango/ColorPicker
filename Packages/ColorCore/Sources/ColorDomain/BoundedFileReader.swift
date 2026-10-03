import Foundation

public enum BoundedFileReadError: Error, Equatable {
    case tooLarge, cancelled, changedDuringRead
}

/// Reads an immutable snapshot with an actual byte ceiling, never a mapped file.
/// Platform adapters own security-scoped access and provider coordination.
public enum BoundedFileReader {
    public static let chunkBytes = 64 * 1024

    public static func read(_ url: URL, maximumBytes: Int,
                            cancelled: () -> Bool = { false }) throws -> Data {
        var result = Data()
        try forEachChunk(url, maximumBytes: maximumBytes, cancelled: cancelled) { result.append($0) }
        return result
    }

    /// A failed/cancelled read never hands off a complete snapshot. Streaming
    /// destinations must discard their partial output when this method throws.
    public static func forEachChunk(_ url: URL, maximumBytes: Int,
                                    cancelled: () -> Bool = { false },
                                    consume: (Data) throws -> Void) throws {
        if cancelled() { throw BoundedFileReadError.cancelled }
        var initialURL = url
        initialURL.removeAllCachedResourceValues()
        let before = try initialURL.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        try drain(maximumBytes: maximumBytes, expectedBytes: before.fileSize,
                  cancelled: cancelled, read: { try file.read(upToCount: $0) }, consume: consume)
        var freshURL = url
        freshURL.removeAllCachedResourceValues()
        let after = try freshURL.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
        guard before.fileSize == after.fileSize,
              before.contentModificationDate == after.contentModificationDate else {
            throw BoundedFileReadError.changedDuringRead
        }
        if cancelled() { throw BoundedFileReadError.cancelled }
    }

    public static func copyToTemporaryFile(_ source: URL, maximumBytes: Int,
                                            cancelled: () -> Bool = { false }) throws -> URL {
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent("TouchColor-bounded-\(UUID()).data")
        guard FileManager.default.createFile(atPath: destination.path, contents: nil) else { throw CocoaError(.fileWriteUnknown) }
        var complete = false
        defer { if !complete { try? FileManager.default.removeItem(at: destination) } }
        let output = try FileHandle(forWritingTo: destination)
        defer { try? output.close() }
        try forEachChunk(source, maximumBytes: maximumBytes, cancelled: cancelled) { try output.write(contentsOf: $0) }
        try output.close()
        complete = true
        return destination
    }

    // An injectable stream boundary makes growth, truncation, read errors and
    // cancellation deterministic without changing production file access.
    static func drain(maximumBytes: Int, expectedBytes: Int?, cancelled: () -> Bool,
                      read: (Int) throws -> Data?, consume: (Data) throws -> Void) throws {
        guard maximumBytes > 0 else { throw BoundedFileReadError.tooLarge }
        if let expectedBytes, expectedBytes < 0 || expectedBytes > maximumBytes { throw BoundedFileReadError.tooLarge }
        var count = 0
        while true {
            if cancelled() { throw BoundedFileReadError.cancelled }
            // One byte beyond the remaining allowance detects growth at the cap
            // without allocating an unbounded chunk or silently returning a prefix.
            let remaining = maximumBytes - count
            let requested = remaining >= chunkBytes ? chunkBytes : remaining + 1
            guard let bytes = try read(requested), !bytes.isEmpty else { break }
            if cancelled() { throw BoundedFileReadError.cancelled }
            guard bytes.count <= requested, bytes.count <= maximumBytes - count else { throw BoundedFileReadError.tooLarge }
            count += bytes.count
            try consume(bytes)
        }
        if cancelled() { throw BoundedFileReadError.cancelled }
        if let expectedBytes, count != expectedBytes { throw BoundedFileReadError.changedDuringRead }
    }
}
