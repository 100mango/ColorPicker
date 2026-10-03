import XCTest
import ColorDomain

final class ColorDomainTests: XCTestCase {
    func testLegacyHexAndRGBFormattingAcrossByteRange() {
        for red in stride(from: 0, through: 255, by: 17) {
            for green in stride(from: 0, through: 255, by: 17) {
                for blue in stride(from: 0, through: 255, by: 17) {
                    let legacy = String(format: "#%02x%02x%02x", red, green, blue)
                    let color = RGBColor(red: UInt8(red), green: UInt8(green), blue: UInt8(blue))
                    XCTAssertEqual(color.hex, legacy)
                    XCTAssertEqual(RGBColor(hex: legacy.uppercased()), color)
                    XCTAssertEqual(color.rgbDescription, "R \(red)   G \(green)   B \(blue)")
                }
            }
        }
        for bad in ["", "#fff", "#12345678", "#abcdef ", "abcdefg", "#gg0000", "#１２３４５６", "#12345\n"] {
            XCTAssertNil(RGBColor(hex: bad), bad)
        }
    }
    func testFiniteGeometryAndZoomMatchLegacyEdges() {
        XCTAssertEqual(NormalizedPoint.inside(x: 120, y: 90, originX: 20, originY: 40, width: 200, height: 100), .center)
        XCTAssertNil(NormalizedPoint.inside(x: 220, y: 140, originX: 20, originY: 40, width: 200, height: 100))
        XCTAssertNil(NormalizedPoint.inside(x: 0, y: 0, originX: 0, originY: 0, width: .infinity, height: 1))
        for invalid in [Double.nan, .infinity, -.infinity, -0.1, 1.01] { XCTAssertNil(NormalizedPoint(x: invalid, y: 0)) }
        let edge = NormalizedPoint(x: 1, y: 1)!.pixel(width: 3, height: 2)!
        XCTAssertEqual(edge.x, 2); XCTAssertEqual(edge.y, 1)
        let extreme = NormalizedPoint(x: 1, y: 1)!.pixel(width: Int.max, height: Int.max)!
        XCTAssertEqual(extreme.x, Int.max - 1); XCTAssertEqual(extreme.y, Int.max - 1)
        XCTAssertEqual(ColorZoom.clamped(0), 1); XCTAssertEqual(ColorZoom.clamped(101), 100)
        XCTAssertEqual(ColorZoom.clamped(.nan), 1); XCTAssertEqual(ColorZoom.clamped(50), 50)
    }
    func testGenerationRejectsOldImportAndCancellation() {
        var generation = ImportGeneration()
        let first = generation.advance(); let second = generation.advance()
        XCTAssertFalse(generation.accepts(first)); XCTAssertTrue(generation.accepts(second))
        generation.advance(); XCTAssertFalse(generation.accepts(second))
    }
}

final class CaptureEpochTests: XCTestCase {
    func testStopAndRestartRejectOldCaptureAndQueuedDeliveries() {
        let gate = CaptureEpoch()
        let first = gate.begin(); XCTAssertTrue(gate.accepts(first))
        gate.invalidate(); XCTAssertFalse(gate.accepts(first))
        let second = gate.begin(); XCTAssertTrue(gate.accepts(second)); XCTAssertFalse(gate.accepts(first))
        gate.invalidate(); gate.invalidate(); XCTAssertFalse(gate.accepts(second))
    }
}
