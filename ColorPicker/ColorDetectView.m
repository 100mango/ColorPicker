#import "ColorDetectView.h"
#import "TCOriginalDesign.h"
#import "TCColorUtilities.h"

@interface ColorDetectView () <UIPointerInteractionDelegate>
@property (nonatomic, strong, readwrite) UIImageView *imageView;
@property (nonatomic, strong) UIImageView *marker;
@property (nonatomic) CGSize previousSize;
@property (nonatomic, readwrite) BOOL hasSelectedPoint;
@property (nonatomic, readwrite) CGPoint selectedNormalizedPoint;
@end
@implementation ColorDetectView
@dynamic delegate;
- (instancetype)initWithFrame:(CGRect)frame andUIImage:(UIImage *)image {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = TCOriginalBackground();
        self.maximumZoomScale = 100;
        self.minimumZoomScale = 1;
        self.bouncesZoom = NO;
        self.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
        self.accessibilityIdentifier = @"photoViewport";
        self.imageView = [[UIImageView alloc] initWithImage:image];
        self.imageView.contentMode = UIViewContentModeScaleAspectFit;
        // Match the sampler's documented white matte, including in dark appearance.
        self.imageView.backgroundColor = UIColor.whiteColor;
        self.imageView.userInteractionEnabled = YES;
        self.imageView.accessibilityIdentifier = @"sampleImage";
        self.imageView.isAccessibilityElement = YES;
        self.imageView.accessibilityTraits = UIAccessibilityTraitImage;
        self.imageView.accessibilityLabel = NSLocalizedString(@"Photo for sampling", nil);
        self.imageView.accessibilityHint = NSLocalizedString(@"Use Sample Center, or tap and drag on the photo to pick a color. Pinch or use Zoom to magnify.", nil);
        [self addSubview:self.imageView];
        [self.imageView addInteraction:[[UIPointerInteraction alloc] initWithDelegate:self]];
        [self addGestureRecognizer:[[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(sampleGesture:)]];
        UILongPressGestureRecognizer *drag = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(sampleGesture:)];
        drag.minimumPressDuration = 0.15;
        [self addGestureRecognizer:drag];
        self.marker = [[UIImageView alloc] initWithImage:TCOriginalImage(@"picker")];
        self.marker.bounds = CGRectMake(0, 0, 25, 25);
        self.marker.tintColor = UIColor.whiteColor;
        self.marker.layer.shadowColor = UIColor.blackColor.CGColor;
        self.marker.layer.shadowOpacity = 1;
        self.marker.layer.shadowRadius = 2;
        self.marker.hidden = YES;
        self.marker.accessibilityIdentifier = @"sampleMarker";
        self.marker.isAccessibilityElement = YES;
        self.marker.accessibilityLabel = NSLocalizedString(@"Selected pixel", nil);
        self.marker.accessibilityTraits = UIAccessibilityTraitImage;
        // A sibling keeps its visual/accessible size constant as the photo zooms.
        [self addSubview:self.marker];
    }
    return self;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    BOOL resized = !CGSizeEqualToSize(self.previousSize, self.bounds.size) && self.bounds.size.width > 0 && self.bounds.size.height > 0;
    if (resized) {
        self.previousSize = self.bounds.size;
        self.zoomScale = 1;
        CGSize imageSize = self.imageView.image.size;
        if (imageSize.width <= 0 || imageSize.height <= 0) return;
        CGFloat fit = MIN(self.bounds.size.width/imageSize.width, self.bounds.size.height/imageSize.height);
        self.imageView.frame = CGRectMake(0, 0, imageSize.width*fit, imageSize.height*fit);
        self.contentSize = self.imageView.bounds.size;
    }
    CGFloat vertical = MAX(0,(self.bounds.size.height-self.contentSize.height)/2);
    CGFloat horizontal = MAX(0,(self.bounds.size.width-self.contentSize.width)/2);
    UIEdgeInsets inset = UIEdgeInsetsMake(vertical,horizontal,vertical,horizontal);
    if (!UIEdgeInsetsEqualToEdgeInsets(self.contentInset, inset)) self.contentInset = inset;
    if (resized) self.contentOffset = CGPointMake(-inset.left,-inset.top);
    if (self.hasSelectedPoint) {
        CGPoint point = CGPointMake(self.selectedNormalizedPoint.x*self.imageView.bounds.size.width,
                                    self.selectedNormalizedPoint.y*self.imageView.bounds.size.height);
        self.marker.center = [self.imageView convertPoint:point toView:self];
        self.marker.hidden = NO;
    }
}
- (BOOL)sampleAtImagePoint:(CGPoint)point {
    CGPoint normalized;
    if (!TCNormalizedPoint(point, self.imageView.bounds, &normalized)) return NO;
    NSString *hex = TCSampleImage(self.imageView.image, normalized);
    if (!hex) return NO;
    self.selectedNormalizedPoint = normalized;
    self.hasSelectedPoint = YES;
    self.marker.center = [self.imageView convertPoint:point toView:self];
    self.marker.hidden = NO;
    self.marker.accessibilityValue = [NSString stringWithFormat:@"%@, %@", hex, TCRGBDescription(hex)];
    if ([self.delegate respondsToSelector:@selector(handelColor:)]) [self.delegate handelColor:hex];
    return YES;
}
- (BOOL)sampleVisibleCenter {
    CGPoint visibleCenter = CGPointMake(CGRectGetMidX(self.bounds), CGRectGetMidY(self.bounds));
    return [self sampleAtImagePoint:[self convertPoint:visibleCenter toView:self.imageView]];
}
- (void)sampleGesture:(UIGestureRecognizer *)gesture {
    if (gesture.state != UIGestureRecognizerStateEnded && gesture.state != UIGestureRecognizerStateBegan && gesture.state != UIGestureRecognizerStateChanged) return;
    [self sampleAtImagePoint:[gesture locationInView:self.imageView]];
}
- (UIPointerStyle *)pointerInteraction:(UIPointerInteraction *)interaction styleForRegion:(UIPointerRegion *)region {
    // A precise crosshair indicates the same pixel selected by clicking; hover never changes a saved selection.
    UIBezierPath *path = [UIBezierPath bezierPathWithRect:CGRectMake(-1,-10,2,20)];
    [path appendPath:[UIBezierPath bezierPathWithRect:CGRectMake(-10,-1,20,2)]];
    return [UIPointerStyle styleWithShape:[UIPointerShape shapeWithPath:path] constrainedAxes:UIAxisNeither];
}
@end

