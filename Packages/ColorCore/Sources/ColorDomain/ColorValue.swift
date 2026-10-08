import Foundation

/// Original TouchColor contract: exactly #rrggbb, ASCII, lowercase on output.
public struct RGBColor: Equatable, Hashable, Sendable {
    public let red: UInt8
    public let green: UInt8
    public let blue: UInt8

    public init(red: UInt8, green: UInt8, blue: UInt8) {
        self.red = red; self.green = green; self.blue = blue
    }

    public init?(hex: String) {
        let bytes = Array(hex.utf8)
        guard bytes.count == 7, bytes[0] == 35 else { return nil }
        var number: UInt32 = 0
        for byte in bytes.dropFirst() {
            let nibble: UInt8
            switch byte {
            case 48...57: nibble = byte - 48
            case 65...70: nibble = byte - 55
            case 97...102: nibble = byte - 87
            default: return nil
            }
            number = number * 16 + UInt32(nibble)
        }
        red = UInt8((number >> 16) & 255)
        green = UInt8((number >> 8) & 255)
        blue = UInt8(number & 255)
    }

    public var hex: String { String(format: "#%02x%02x%02x", Int(red), Int(green), Int(blue)) }
    public var rgbDescription: String { "R \(red)   G \(green)   B \(blue)" }
}

/// Top-left origin, independent of points/pixels/backing scale.
public struct NormalizedPoint: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public init?(x: Double, y: Double) {
        guard x.isFinite, y.isFinite, (0...1).contains(x), (0...1).contains(y) else { return nil }
        self.x = x; self.y = y
    }
    public static let center = NormalizedPoint(x: 0.5, y: 0.5)!

    /// Like CGRectContainsPoint, the right/bottom edges of a view rectangle are excluded.
    public static func inside(x: Double, y: Double, originX: Double, originY: Double,
                              width: Double, height: Double) -> NormalizedPoint? {
        guard [x, y, originX, originY, width, height].allSatisfy(\.isFinite),
              width > 0, height > 0,
              x >= originX, y >= originY, x - originX < width, y - originY < height else { return nil }
        return NormalizedPoint(x: (x - originX) / width, y: (y - originY) / height)
    }

    /// Direct sampling accepts the outer edge and clamps it to the final pixel, as iOS does.
    public func pixel(width: Int, height: Int) -> (x: Int, y: Int)? {
        guard width > 0, height > 0 else { return nil }
        // Check the inclusive far edge before Double→Int conversion: Double(Int.max)
        // rounds upward, so converting x == 1 directly would overflow on arbitrary domain input.
        return (x == 1 ? width - 1 : min(Int(floor(x * Double(width))), width - 1),
                y == 1 ? height - 1 : min(Int(floor(y * Double(height))), height - 1))
    }
}

public enum ColorZoom {
    public static let range = 1.0...100.0
    public static func clamped(_ value: Double) -> Double {
        guard value.isFinite else { return 1 }
        return min(range.upperBound, max(range.lowerBound, value))
    }
}

/// Value-only import generation. The UI owner serializes mutation on its main actor.
public struct ImportGeneration: Sendable {
    public private(set) var current: UInt64 = 0
    public init() {}
    @discardableResult public mutating func advance() -> UInt64 { current &+= 1; return current }
    public func accepts(_ value: UInt64) -> Bool { current == value }
}
