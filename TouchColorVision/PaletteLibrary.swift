import UIKit
import Combine
import ColorDomain
import ColorPaletteLegacy

@MainActor final class PaletteLibrary: ObservableObject {
    private let store: LegacyPalette
    @Published private(set) var colors: [ColorDomain.RGBColor]
    init(defaults: UserDefaults = .standard) {
        store = LegacyPalette(defaults: defaults); colors = store.colors
    }
    func append(_ values: [ColorDomain.RGBColor]) { store.append(values); colors = store.colors }
    func remove(at index: Int) { store.remove(at: index); colors = store.colors }
    func copy(_ color: ColorDomain.RGBColor) { UIPasteboard.general.string = color.hex }
}
