import SwiftUI
import UIKit
import ColorDomain
import ColorRaster

/// Native visionOS window canvas. UIKit supplies pinch, pan and coordinate conversion;
/// precision buttons provide an alternative when spatial targeting is imprecise.
struct VisionCanvas: UIViewRepresentable {
    @ObservedObject var session: ImageSession
    func makeUIView(context: Context) -> VisionColorScrollView {
        let scroll = VisionColorScrollView()
        scroll.session = session
        return scroll
    }
    func updateUIView(_ scroll: VisionColorScrollView, context: Context) {
        scroll.session = session
        scroll.refresh()
    }
}

final class VisionColorScrollView: UIScrollView, UIScrollViewDelegate {
    weak var session: ImageSession?
    let canvas = VisionPixelCanvas()
    private var lastViewport = CGSize.zero
    private var fitting = false
    private var applyingModel = false
    override init(frame: CGRect) {
        super.init(frame: frame)
        delegate = self; minimumZoomScale = 1; maximumZoomScale = 100
        alwaysBounceVertical = false; alwaysBounceHorizontal = false
        contentInsetAdjustmentBehavior = .never
        addSubview(canvas)
        accessibilityIdentifier = "vision.scroll"
        let tap = UITapGestureRecognizer(target: self, action: #selector(sample(_:)))
        canvas.addGestureRecognizer(tap)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func layoutSubviews() {
        super.layoutSubviews()
        if bounds.size != lastViewport { refreshLayout() }
    }
    func refresh() {
        guard let session, let raster = session.raster else { return }
        // UIViewRepresentable updates apply model values to UIKit. The synchronous
        // UIScrollView delegate must not publish the same value back into SwiftUI.
        applyingModel = true; defer { applyingModel = false }
        let newImage = canvas.image !== raster.image
        canvas.image = raster.image; canvas.session = session
        if newImage || bounds.size != lastViewport { refreshLayout() }
        if abs(Double(zoomScale) - session.zoom) > 0.001 { setZoomScale(session.zoom, animated: false) }
        canvas.setNeedsDisplay()
    }
    private func refreshLayout() {
        guard !fitting, bounds.width > 0, bounds.height > 0, let raster = session?.raster else { return }
        fitting = true; defer { fitting = false }
        lastViewport = bounds.size
        let zoom = CGFloat(session?.zoom ?? 1)
        let ratio = min(bounds.width / CGFloat(raster.width), bounds.height / CGFloat(raster.height))
        setZoomScale(1, animated: false)
        canvas.frame = CGRect(origin: .zero, size: CGSize(width: CGFloat(raster.width) * ratio, height: CGFloat(raster.height) * ratio))
        contentSize = canvas.bounds.size
        setZoomScale(zoom, animated: false)
        centerSmallImage()
        // Window resizing preserves the chosen source pixel and brings it into view.
        if let point = session?.selectedPoint {
            let x = point.x * canvas.frame.width - bounds.width / 2
            let y = point.y * canvas.frame.height - bounds.height / 2
            let maxX = max(-contentInset.left, contentSize.width - bounds.width + contentInset.right)
            let maxY = max(-contentInset.top, contentSize.height - bounds.height + contentInset.bottom)
            setContentOffset(CGPoint(x: min(maxX, max(-contentInset.left, x)), y: min(maxY, max(-contentInset.top, y))), animated: false)
        }
    }
    private func centerSmallImage() {
        let horizontal = max(0, (bounds.width - contentSize.width) / 2)
        let vertical = max(0, (bounds.height - contentSize.height) / 2)
        contentInset = UIEdgeInsets(top: vertical, left: horizontal, bottom: vertical, right: horizontal)
    }
    func viewForZooming(in scrollView: UIScrollView) -> UIView? { canvas }
    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        centerSmallImage(); canvas.setNeedsDisplay()
        if !fitting, !applyingModel, let session, abs(session.zoom - Double(zoomScale)) > 0.001 {
            session.changeZoom(Double(zoomScale))
        }
    }
    @objc private func sample(_ gesture: UITapGestureRecognizer) {
        choose(gesture.location(in: canvas))
    }
    func choose(_ point: CGPoint) {
        guard let value = NormalizedPoint.inside(x: point.x, y: point.y, originX: 0, originY: 0, width: canvas.bounds.width, height: canvas.bounds.height) else { return }
        session?.select(value); canvas.setNeedsDisplay()
    }
}

final class VisionPixelCanvas: UIView {
    var image: CGImage?
    weak var session: ImageSession?
    override init(frame: CGRect) {
        super.init(frame: frame)
        isOpaque = true; backgroundColor = .white; isUserInteractionEnabled = true
        isAccessibilityElement = true; accessibilityTraits = .image
        accessibilityIdentifier = "vision.canvas"
        accessibilityLabel = NSLocalizedString("Image canvas. Select a point, or use the precision pixel controls.", comment: "Canvas accessibility")
        contentMode = .redraw
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func draw(_ rect: CGRect) {
        guard let image, let session, let context = UIGraphicsGetCurrentContext() else { return }
        UIColor.white.setFill(); context.fill(bounds)
        context.interpolationQuality = .none
        UIImage(cgImage: image).draw(in: bounds)
        let zoom = (superview as? UIScrollView)?.zoomScale ?? 1
        let point = CGPoint(x: session.selectedPoint.x * bounds.width, y: session.selectedPoint.y * bounds.height)
        let radius = 7 / max(1, zoom)
        let marker = UIBezierPath(ovalIn: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2))
        marker.lineWidth = 3 / max(1, zoom); UIColor.black.setStroke(); marker.stroke()
        marker.lineWidth /= 2; UIColor.white.setStroke(); marker.stroke()
        accessibilityValue = session.selectedColor?.hex
    }
}
