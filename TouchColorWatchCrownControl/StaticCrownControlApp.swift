#if DEBUG
import SwiftUI

/// A separate diagnostic executable. No product model, persistence, connectivity,
/// editor, custom Crown binding, focus modifier, or application-owned state.
@main
struct StaticCrownControlApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                List {
                    ForEach(0..<12, id: \.self) { index in
                        NavigationLink(destination: Text("Static destination")) {
                            Text("Static row \(index + 1)")
                        }
                        .accessibilityIdentifier("static.row.\(index)")
                    }
                }
                .accessibilityIdentifier("static.list")
                .navigationTitle("Crown Control")
            }
        }
    }
}
#else
#error("The isolated Crown control is DEBUG-only and must never ship.")
#endif
