import Foundation

/// Validates only PNG framing; ImageIO remains the image/metadata decoder.
/// PNG permits split IDAT and ancillary chunks, but requires complete lengths,
/// CRCs and a terminal zero-length IEND. ImageIO alone accepts missing IEND.
/// Format reference: https://www.w3.org/TR/png-3/#5DataRep
enum PNGFraming {
    private static let signature: [UInt8] = [137, 80, 78, 71, 13, 10, 26, 10]
    private static let crcTable: [UInt32] = {
        var table = [UInt32](repeating: 0, count: 256)
        for index in table.indices {
            var value = UInt32(index)
            for _ in 0..<8 { value = (value & 1) == 1 ? 0xedb88320 ^ (value >> 1) : value >> 1 }
            table[index] = value
        }
        return table
    }()

    /// Call after the platform's encoded-byte cap. The original Data is borrowed,
    /// never copied, and cancellation is checked within each64KiB of a large chunk.
    static func validateIfPNG(_ data: Data, cancelled: () -> Bool) throws {
        guard data.starts(with: signature) else { return }
        try data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            func word(_ offset: Int) -> UInt32 {
                (UInt32(bytes[offset]) << 24) | (UInt32(bytes[offset + 1]) << 16)
                    | (UInt32(bytes[offset + 2]) << 8) | UInt32(bytes[offset + 3])
            }
            var offset = 8, sawData = false, endedData = false
            while offset < bytes.count {
                if cancelled() { throw RasterError.cancelled }
                let remaining = bytes.count - offset
                guard remaining >= 12 else { throw RasterError.unreadable }
                let lengthWord = word(offset)
                // Check in UInt64 before conversion/addition, including arm64_32.
                guard lengthWord <= 0x7fffffff, UInt64(lengthWord) + 12 <= UInt64(remaining) else { throw RasterError.unreadable }
                let length = Int(lengthWord), type = word(offset + 4)
                let payloadEnd = offset + 8 + length, end = payloadEnd + 4
                if offset == 8 {
                    guard type == 0x49484452, length == 13 else { throw RasterError.unreadable } // IHDR
                } else if type == 0x49484452 { throw RasterError.unreadable }
                if type == 0x49444154 { // IDAT chunks must be consecutive.
                    guard !endedData else { throw RasterError.unreadable }
                    sawData = true
                } else if sawData { endedData = true }
                var crc = UInt32.max
                var nextCancellationCheck = offset + 4
                for index in (offset + 4)..<payloadEnd {
                    if index == nextCancellationCheck {
                        if cancelled() { throw RasterError.cancelled }
                        nextCancellationCheck += 64 * 1024
                    }
                    crc = crcTable[Int((crc ^ UInt32(bytes[index])) & 0xff)] ^ (crc >> 8)
                }
                guard (crc ^ UInt32.max) == word(payloadEnd) else { throw RasterError.unreadable }
                if type == 0x49454e44 { // IEND
                    guard length == 0, sawData, end == bytes.count else { throw RasterError.unreadable }
                    return
                }
                offset = end
            }
            throw RasterError.unreadable
        }
    }
}
