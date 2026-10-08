import Foundation
import Combine
import ColorDomain
import ColorPaletteLegacy

/// tvOS defaults have a strict OS quota. Refuse an additional write atomically;
/// never evict, truncate or silently repair the user's existing palette to make room.
@MainActor final class PaletteLibrary: ObservableObject {
    static let maximumBytes = 256 * 1024
    private let defaults: UserDefaults
    private let domain: String
    private let store: LegacyPalette
    @Published private(set) var colors: [RGBColor]
    @Published var error: String?
    init(defaults: UserDefaults = .standard, domain: String = Bundle.main.bundleIdentifier ?? "com.mango.touchColor") {
        self.defaults = defaults; self.domain = domain; store = LegacyPalette(defaults: defaults); colors = store.colors
    }
    func append(_ additions: [RGBColor]) {
        guard !additions.isEmpty else { return }
        let result = colors + additions
        guard permits(result) else { error = NSLocalizedString("The TV palette is full. Export or delete selected colors before saving more.", comment: "TV storage limit"); return }
        store.append(additions); colors = store.colors; error = nil
    }
    func remove(at index: Int) {
        guard colors.indices.contains(index) else { return }
        var result = colors; result.remove(at: index)
        guard permits(result) else { error = NSLocalizedString("TV storage is over its limit. Export the palette before changing it.", comment: "TV storage limit"); return }
        store.remove(at: index); colors = store.colors; error = nil
    }
    private func permits(_ values: [RGBColor]) -> Bool {
        var domainValues = defaults.persistentDomain(forName: domain) ?? [:]
        if let raw = defaults.object(forKey: LegacyPalette.key),
           !(raw as? NSObject ?? NSObject()).isEqual(colors.map(\.hex)), domainValues[LegacyPalette.recoveryKey] == nil {
            domainValues[LegacyPalette.recoveryKey] = raw
        }
        domainValues[LegacyPalette.key] = values.map(\.hex)
        guard let bytes = try? PropertyListSerialization.data(fromPropertyList: domainValues, format: .binary, options: 0) else { return false }
        return bytes.count <= Self.maximumBytes
    }
}
