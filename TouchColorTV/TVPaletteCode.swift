import Foundation
import CoreImage
import CoreGraphics
import ColorDomain
import ColorPaletteLegacy

/// A small selected palette is exported visually for a phone to scan; no TV clipboard assumed.
enum TVPaletteCode {
    static func payload(_ colors: [RGBColor]) throws -> Data {
        guard (1...8).contains(colors.count) else { throw PaletteFileError.invalid }
        return try JSONEncoder().encode(colors.map(\.hex))
    }
    static func image(_ colors: [RGBColor]) throws -> CGImage {
        let data = try payload(colors)
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { throw PaletteFileError.invalid }
        filter.setValue(data, forKey: "inputMessage"); filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let image = filter.outputImage else { throw PaletteFileError.invalid }
        let extent = image.extent.insetBy(dx: -4, dy: -4)
        let white = CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: extent)
        let padded = image.composited(over: white)
        guard let cg = CIContext().createCGImage(padded, from: extent) else { throw PaletteFileError.invalid }
        return cg
    }
}
