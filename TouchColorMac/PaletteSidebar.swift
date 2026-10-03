import SwiftUI

struct PaletteSidebar: View {
    @ObservedObject var library: PaletteLibrary
    @ObservedObject var session: ImageSession
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Palette").font(.headline)
                Spacer()
                Text("\(library.colors.count)").foregroundStyle(.secondary).accessibilityIdentifier("palette.count")
            }.padding()
            List {
                ForEach(Array(library.colors.enumerated()), id: \.offset) { index, color in
                    HStack {
                        Color(red: Double(color.red) / 255, green: Double(color.green) / 255, blue: Double(color.blue) / 255)
                            .frame(width: 24, height: 36).border(.gray.opacity(0.5)).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(color.hex).font(.body.monospaced())
                            Text(color.rgbDescription).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                        Menu {
                            Button("Copy Color") { library.copy(color) }
                            Button("Delete Color", role: .destructive) { library.remove(at: index) }
                        } label: { Image(systemName: "ellipsis.circle") }
                            .menuStyle(.borderlessButton).frame(width: 24)
                            .accessibilityLabel("Actions for color \(index + 1)")
                            .accessibilityIdentifier("palette.actions.\(index)")
                    }.padding(.vertical, 4).accessibilityIdentifier("palette.row.\(index)")
                }
            }
            if library.colors.isEmpty { Text("Saved colors appear here, in order.").foregroundStyle(.secondary).padding() }
            Button("Export Palette…") { MacImportExport.exportPalette(library: library, session: session) }
                .disabled(library.colors.isEmpty).accessibilityIdentifier("palette.export").padding()
        }
    }
}
