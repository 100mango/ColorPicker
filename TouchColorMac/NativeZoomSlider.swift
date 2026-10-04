import AppKit
import SwiftUI
import ColorDomain

/// Preserve AppKit's range-control role, accessible value, keyboard interaction
/// and native descendants. The sampling model still owns zoom clamping/math.
struct NativeZoomSlider: NSViewRepresentable {
    @Binding var value: Double
    @Environment(\.isEnabled) private var enabled
    func makeCoordinator() -> Coordinator { Coordinator(value: $value) }
    func makeNSView(context: Context) -> NSSlider {
        let slider = NSSlider(value: value, minValue: ColorZoom.range.lowerBound,
                              maxValue: ColorZoom.range.upperBound,
                              target: context.coordinator, action: #selector(Coordinator.changed(_:)))
        slider.isContinuous = true
        slider.setAccessibilityLabel(NSLocalizedString("Image zoom", comment: "Zoom accessibility"))
        slider.setAccessibilityIdentifier("sample.zoom")
        return slider
    }
    func updateNSView(_ slider: NSSlider, context: Context) {
        context.coordinator.value = $value
        if slider.doubleValue != value { slider.doubleValue = value }
        slider.isEnabled = enabled
    }
    final class Coordinator: NSObject {
        var value: Binding<Double>
        init(value: Binding<Double>) { self.value = value }
        @objc func changed(_ sender: NSSlider) { value.wrappedValue = sender.doubleValue }
    }
}
