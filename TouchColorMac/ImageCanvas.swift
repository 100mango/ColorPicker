import SwiftUI
import AppKit
import ColorDomain

/// AppKit handles scrolling and trackpad magnification. The document view is top-left based.
struct ImageCanvas: NSViewRepresentable {
    @ObservedObject var session: ImageSession
    func makeNSView(context: Context) -> ColorScrollView {
        let scroll = ColorScrollView()
        scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true
        scroll.allowsMagnification = true; scroll.minMagnification = 1; scroll.maxMagnification = 100
        let canvas = PixelCanvas(); canvas.session = session
        scroll.documentView = canvas
        scroll.session = session
        scroll.setAccessibilityIdentifier("image.scroll")
        scroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        scroll.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        return scroll
    }
    // AppKit's document fitting size must not feed back into SwiftUI's minimum window height.
    // The viewport consumes the proposed space; the full source remains in the scroll document.
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: ColorScrollView, context: Context) -> CGSize? {
        let width = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? 500
        let height = proposal.height.flatMap { $0.isFinite ? max(0, $0) : nil } ?? 300
        return CGSize(width: width, height: height)
    }
    func updateNSView(_ scroll: ColorScrollView, context: Context) {
        guard let canvas = scroll.documentView as? PixelCanvas else { return }
        canvas.session = session
        scroll.updateCanvasSize()
        if abs(scroll.magnification - session.zoom) > 0.001 {
            let center = NSPoint(x: scroll.contentView.bounds.midX, y: scroll.contentView.bounds.midY)
            scroll.setMagnification(session.zoom, centeredAt: center)
        }
        canvas.needsDisplay = true
    }
}

final class ColorScrollView: NSScrollView {
    weak var session: ImageSession?
    private var fitting = false
    override func layout() { super.layout(); updateCanvasSize() }
    func updateCanvasSize() {
        guard !fitting, let raster = session?.raster, let canvas = documentView else { return }
        fitting = true; defer { fitting = false }
        // At 1× the source fits the viewport. Zoom changes the clip magnification, not source pixels.
        let viewport = contentSize
        let ratio = min(viewport.width / CGFloat(raster.width), viewport.height / CGFloat(raster.height))
        let size = NSSize(width: max(1, CGFloat(raster.width) * ratio), height: max(1, CGFloat(raster.height) * ratio))
        if canvas.frame.size != size { canvas.setFrameSize(size) }
    }
    override func magnify(with event: NSEvent) {
        super.magnify(with: event)
        session?.changeZoom(magnification)
    }
}

final class PixelCanvas: NSView {
    weak var session: ImageSession?
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        setAccessibilityElement(true); setAccessibilityRole(.image)
        setAccessibilityIdentifier("image.canvas")
        setAccessibilityLabel(NSLocalizedString("Color sampler", comment: "Canvas accessibility label"))
        setAccessibilityHelp(NSLocalizedString("Click to sample a pixel; arrow keys move one pixel.", comment: "Canvas accessibility help"))
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.white.setFill(); bounds.fill()
        guard let session, let raster = session.raster else { return }
        let image = NSImage(cgImage: raster.image, size: NSSize(width: raster.width, height: raster.height))
        NSGraphicsContext.current?.imageInterpolation = .none
        image.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        let point = NSPoint(x: session.selectedPoint.x * bounds.width, y: session.selectedPoint.y * bounds.height)
        // Marker and sample use the same normalized image point, independent of zoom/resize.
        let radius = 7 / max(1, enclosingScrollView?.magnification ?? 1)
        let marker = NSBezierPath(ovalIn: NSRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2))
        marker.lineWidth = 3 / max(1, enclosingScrollView?.magnification ?? 1)
        NSColor.black.setStroke(); marker.stroke()
        marker.lineWidth /= 2; NSColor.white.setStroke(); marker.stroke()
        setAccessibilityValue(session.selectedColor?.hex ?? "")
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        choose(convert(event.locationInWindow, from: nil))
    }
    override func mouseDragged(with event: NSEvent) { choose(convert(event.locationInWindow, from: nil)) }
    private func choose(_ point: NSPoint) {
        guard let value = NormalizedPoint.inside(x: point.x, y: point.y, originX: 0, originY: 0, width: bounds.width, height: bounds.height) else { return }
        session?.select(value); needsDisplay = true
    }
    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case 123: session?.move(dx: -1, dy: 0)
        case 124: session?.move(dx: 1, dy: 0)
        case 125: session?.move(dx: 0, dy: 1)
        case 126: session?.move(dx: 0, dy: -1)
        default: super.keyDown(with: event)
        }
    }
}
