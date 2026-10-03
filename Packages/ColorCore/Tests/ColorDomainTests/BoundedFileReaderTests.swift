import XCTest
import Foundation
@testable import ColorDomain

final class BoundedFileReaderTests: XCTestCase {
    func testActualFileSnapshotAndExactCapPreserveEveryByte() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("bounded-reader-\(UUID())")
        defer { try? FileManager.default.removeItem(at: url) }
        let original = Data((0..<(BoundedFileReader.chunkBytes + 19)).map { UInt8($0 % 251) })
        try original.write(to: url)
        XCTAssertEqual(try BoundedFileReader.read(url, maximumBytes: original.count), original)
        XCTAssertThrowsError(try BoundedFileReader.read(url, maximumBytes: original.count - 1)) {
            XCTAssertEqual($0 as? BoundedFileReadError, .tooLarge)
        }
    }

    func testGrowingStreamCannotReturnOrConsumeAnOversizePrefixAsSuccess() throws {
        var reads = 0, accepted = Data()
        XCTAssertThrowsError(try BoundedFileReader.drain(maximumBytes: 5, expectedBytes: 3,
            cancelled: { false }, read: { _ in reads += 1; return Data(repeating: 1, count: 3) },
            consume: { accepted.append($0) })) { XCTAssertEqual($0 as? BoundedFileReadError, .tooLarge) }
        XCTAssertEqual(reads, 2); XCTAssertEqual(accepted.count, 3)
        var chunks = [Data([1, 2]), Data([3]), Data()]
        XCTAssertThrowsError(try BoundedFileReader.drain(maximumBytes: 8, expectedBytes: 2,
            cancelled: { false }, read: { _ in chunks.removeFirst() }, consume: { _ in })) {
            XCTAssertEqual($0 as? BoundedFileReadError, .changedDuringRead)
        }
    }

    func testTruncationAndReadFailureNeverReturnASnapshot() {
        var chunks = [Data([1, 2]), Data()]
        XCTAssertThrowsError(try BoundedFileReader.drain(maximumBytes: 8, expectedBytes: 4,
            cancelled: { false }, read: { _ in chunks.removeFirst() }, consume: { _ in })) {
            XCTAssertEqual($0 as? BoundedFileReadError, .changedDuringRead)
        }
        enum Failure: Error { case read }
        var reads = 0
        XCTAssertThrowsError(try BoundedFileReader.drain(maximumBytes: 8, expectedBytes: nil,
            cancelled: { false }, read: { _ in reads += 1; if reads == 2 { throw Failure.read }; return Data([1]) },
            consume: { _ in })) { XCTAssertTrue($0 is Failure) }
    }

    func testCancellationStopsBeforeOpeningAndBeforeAnotherChunk() throws {
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        XCTAssertThrowsError(try BoundedFileReader.read(missing, maximumBytes: 8, cancelled: { true })) {
            XCTAssertEqual($0 as? BoundedFileReadError, .cancelled)
        }
        var reads = 0
        XCTAssertThrowsError(try BoundedFileReader.drain(maximumBytes: 8, expectedBytes: nil,
            cancelled: { reads == 1 }, read: { _ in reads += 1; return Data([1]) }, consume: { _ in XCTFail("Cancelled bytes must not be consumed") })) {
            XCTAssertEqual($0 as? BoundedFileReadError, .cancelled)
        }
        XCTAssertEqual(reads, 1)
        XCTAssertThrowsError(try BoundedFileReader.read(missing, maximumBytes: 8))
    }

    func testRealFileTruncatedDuringStreamingIsRejected() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("bounded-truncate-\(UUID())")
        defer { try? FileManager.default.removeItem(at: url) }
        try Data(repeating: 1, count: BoundedFileReader.chunkBytes * 2).write(to: url)
        var consumed = 0
        XCTAssertThrowsError(try BoundedFileReader.forEachChunk(url, maximumBytes: BoundedFileReader.chunkBytes * 3) { bytes in
            consumed += bytes.count
            let writer = try FileHandle(forWritingTo: url); defer { try? writer.close() }
            try writer.truncate(atOffset: UInt64(BoundedFileReader.chunkBytes))
        }) { XCTAssertEqual($0 as? BoundedFileReadError, .changedDuringRead) }
        XCTAssertEqual(consumed, BoundedFileReader.chunkBytes)
    }

    func testFreshMetadataRejectsSameSizeMutationAndIgnoresAnOlderURLCache() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("bounded-metadata-\(UUID())")
        defer { try? FileManager.default.removeItem(at: url) }
        let data = Data(repeating: 7, count: BoundedFileReader.chunkBytes * 2)
        try data.write(to: url)
        _ = try url.resourceValues(forKeys: [.contentModificationDateKey])
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 1000)], ofItemAtPath: url.path)
        XCTAssertEqual(try BoundedFileReader.read(url, maximumBytes: data.count), data,
                       "A previously cached URL must not create a false changed-file result")
        var changed = false
        XCTAssertThrowsError(try BoundedFileReader.forEachChunk(url, maximumBytes: data.count) { _ in
            if !changed {
                changed = true
                let writer = try FileHandle(forWritingTo: url)
                try writer.seek(toOffset: UInt64(BoundedFileReader.chunkBytes))
                try writer.write(contentsOf: Data(repeating: 8, count: BoundedFileReader.chunkBytes))
                try writer.close()
                try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 2000)], ofItemAtPath: url.path)
            }
        }) { XCTAssertEqual($0 as? BoundedFileReadError, .changedDuringRead) }
    }

    func testCopiedProviderBytesAreExactAndGrowingFileIsRejected() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("bounded-copy-\(UUID())")
        defer { try? FileManager.default.removeItem(at: url) }
        let bytes = Data(repeating: 9, count: BoundedFileReader.chunkBytes * 2)
        try bytes.write(to: url)
        let copy = try BoundedFileReader.copyToTemporaryFile(url, maximumBytes: bytes.count)
        defer { try? FileManager.default.removeItem(at: copy) }
        XCTAssertEqual(try BoundedFileReader.read(copy, maximumBytes: bytes.count), bytes)
        var grew = false
        XCTAssertThrowsError(try BoundedFileReader.forEachChunk(url, maximumBytes: bytes.count) { _ in
            if !grew {
                grew = true
                let writer = try FileHandle(forWritingTo: url); defer { try? writer.close() }
                _ = try writer.seekToEnd(); try writer.write(contentsOf: Data([1]))
            }
        }) { XCTAssertEqual($0 as? BoundedFileReadError, .tooLarge) }
    }
}
