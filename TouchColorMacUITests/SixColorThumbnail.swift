import CoreGraphics
import Foundation
import ImageIO

/// Test-only pixel oracle for the single, generated Photos-library fixture.
/// Returns normalized centers only when all six colored blocks are visible.
enum SixColorThumbnail {
    static func locate(in png: Data) throws -> [CGPoint] {
        guard png.count <= 5_000_000,
              let source = CGImageSourceCreateWithData(png as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              image.width > 0, image.height > 0,
              image.width <= 4_000_000 / image.height else { return [] }
        let width = image.width, height = image.height
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        let rendered = rgba.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard rendered else { return [] }
        func red(_ index: Int) -> Bool {
            rgba[index * 4] >= 220 && rgba[index * 4 + 1] <= 35 && rgba[index * 4 + 2] <= 35
        }
        let colors = [[255,0,0], [0,255,0], [0,0,255], [255,255,0], [255,0,255], [0,255,255]]
        var visited = [Bool](repeating: false, count: width * height)
        var result: [CGPoint] = []
        for start in visited.indices where !visited[start] && red(start) {
            var queue = [start], cursor = 0
            visited[start] = true
            var left = start % width, right = left, top = start / width, bottom = top
            while cursor < queue.count {
                let point = queue[cursor]; cursor += 1
                let x = point % width, y = point / width
                left = min(left, x); right = max(right, x); top = min(top, y); bottom = max(bottom, y)
                for next in [x > 0 ? point - 1 : -1, x + 1 < width ? point + 1 : -1,
                             y > 0 ? point - width : -1, y + 1 < height ? point + width : -1] {
                    if next >= 0 && !visited[next] && red(next) { visited[next] = true; queue.append(next) }
                }
            }
            let cellWidth = right - left + 1, cellHeight = bottom - top + 1
            guard cellWidth >= 12, cellHeight >= 12, cellWidth <= 200, cellHeight <= 200,
                  abs(cellWidth - cellHeight) <= max(3, cellWidth / 8),
                  left + 3 * cellWidth <= width, top + 2 * cellHeight <= height else { continue }
            var matches = true
            for row in 0..<2 { for column in 0..<3 {
                let expected = colors[row * 3 + column]
                // Multiple interior points reject a coincidental red icon or a
                // partially loaded/gray thumbnail before any coordinate is used.
                for fy in [0.35, 0.5, 0.65] { for fx in [0.35, 0.5, 0.65] {
                    let x = left + Int((Double(column) + fx) * Double(cellWidth))
                    let y = top + Int((Double(row) + fy) * Double(cellHeight))
                    let offset = (y * width + x) * 4
                    if (0..<3).contains(where: { abs(Int(rgba[offset + $0]) - expected[$0]) > 25 }) { matches = false }
                } }
            } }
            if matches {
                result.append(CGPoint(x: (Double(left) + 1.5 * Double(cellWidth)) / Double(width),
                                      y: (Double(top) + Double(cellHeight)) / Double(height)))
            }
        }
        return result
    }
}
