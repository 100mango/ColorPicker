import AppKit
import ColorDomain
import ColorPaletteLegacy

@MainActor final class PaletteLibrary: ObservableObject {
    private let store: LegacyPalette
    @Published private(set) var colors: [RGBColor]

    init(defaults: UserDefaults = .standard) {
        store = LegacyPalette(defaults: defaults)
        colors = store.colors
    }
    func append(_ values: [RGBColor]) { store.append(values); colors = store.colors }
    func remove(at index: Int) { store.remove(at: index); colors = store.colors }
    func copy(_ color: RGBColor) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(color.hex, forType: .string)
    }
}
