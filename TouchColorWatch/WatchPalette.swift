import Foundation
import Combine
import ColorDomain
import ColorPaletteLegacy

@MainActor final class WatchPalette: ObservableObject {
    private let store: LegacyPalette
    @Published private(set) var colors: [RGBColor]
    @Published var red = 255.0
    @Published var green = 0.0
    @Published var blue = 0.0
    var selected: RGBColor { RGBColor(red: UInt8(min(255, max(0, red.rounded()))), green: UInt8(min(255, max(0, green.rounded()))), blue: UInt8(min(255, max(0, blue.rounded())))) }
    init(defaults: UserDefaults = .standard) { store = LegacyPalette(defaults: defaults); colors = store.colors }
    func setComponent(_ value: Double, channel: Int) {
        guard value.isFinite else { return }
        let bounded = min(255, max(0, value))
        switch channel {
        case 0: if red != bounded { red = bounded }
        case 1: if green != bounded { green = bounded }
        case 2: if blue != bounded { blue = bounded }
        default: break
        }
    }
    func select(_ color: RGBColor) {
        // Reappearing edit-copy destinations may select the same saved value.
        // Avoid publishing unchanged channels back into navigation/Crown layout.
        setComponent(Double(color.red), channel: 0)
        setComponent(Double(color.green), channel: 1)
        setComponent(Double(color.blue), channel: 2)
    }
    func save() { store.append([selected]); colors = store.colors }
    func remove(at index: Int) { store.remove(at: index); colors = store.colors }
}
