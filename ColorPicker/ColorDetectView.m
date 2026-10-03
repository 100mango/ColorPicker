#import "ColorDetectView.h"
#import "TCColorUtilities.h"

@interface ColorDetectView ()
@property (nonatomic, strong, readwrite) UIImageView *imageView;
@property (nonatomic, strong) UIImageView *marker;
@property (nonatomic) CGSize previousSize;
@end
@implementation ColorDetectView
@dynamic delegate;
- (instancetype)initWithFrame:(CGRect)frame andUIImage:(UIImage *)image {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = UIColor.secondarySystemBackgroundColor;
        self.maximumZoomScale = 100;
        self.minimumZoomScale = 1;
        self.bouncesZoom = NO;
        self.imageView = [[UIImageView alloc] initWithImage:image];
        self.imageView.contentMode = UIViewContentModeScaleAspectFit;
        self.imageView.userInteractionEnabled = YES;
        self.imageView.accessibilityIdentifier = @"sampleImage";
        self.imageView.isAccessibilityElement = YES;
        self.imageView.accessibilityLabel = NSLocalizedString(@"Photo for sampling", nil);
        self.imageView.accessibilityHint = NSLocalizedString(@"Use Sample Center, or tap and drag on the photo to pick a color. Pinch to zoom.", nil);
        [self addSubview:self.imageView];
        [self addGestureRecognizer:[[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(sampleGesture:)]];
        UILongPressGestureRecognizer *drag = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(sampleGesture:)];
        drag.minimumPressDuration = 0.15;
        [self addGestureRecognizer:drag];
        self.marker = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:@"plus.circle"]];
        self.marker.bounds = CGRectMake(0, 0, 28, 28);
        self.marker.tintColor = UIColor.whiteColor;
        self.marker.layer.shadowColor = UIColor.blackColor.CGColor;
        self.marker.layer.shadowOpacity = 1;
        self.marker.layer.shadowRadius = 2;
        self.marker.hidden = YES;
        [self.imageView addSubview:self.marker];
    }
    return self;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    if (!CGSizeEqualToSize(self.previousSize, self.bounds.size) && self.bounds.size.width > 0 && self.bounds.size.height > 0) {
        self.previousSize = self.bounds.size;
        self.zoomScale = 1;
        CGSize imageSize = self.imageView.image.size;
        if (imageSize.width <= 0 || imageSize.height <= 0) return;
        CGFloat fit = MIN(self.bounds.size.width/imageSize.width, self.bounds.size.height/imageSize.height);
        self.imageView.frame = CGRectMake(0, 0, imageSize.width*fit, imageSize.height*fit);
        self.contentSize = self.imageView.bounds.size;
        self.marker.hidden = YES;
    }
    self.contentInset = UIEdgeInsetsMake(MAX(0, (self.bounds.size.height-self.contentSize.height)/2), MAX(0, (self.bounds.size.width-self.contentSize.width)/2), 0, 0);
    self.marker.transform = CGAffineTransformMakeScale(1/self.zoomScale, 1/self.zoomScale);
}
- (void)sampleGesture:(UIGestureRecognizer *)gesture {
    if (gesture.state != UIGestureRecognizerStateEnded && gesture.state != UIGestureRecognizerStateBegan && gesture.state != UIGestureRecognizerStateChanged) return;
    CGPoint point = [gesture locationInView:self.imageView], normalized;
    if (!TCNormalizedPoint(point, self.imageView.bounds, &normalized)) return;
    NSString *hex = TCSampleImage(self.imageView.image, normalized);
    if (!hex) return;
    self.marker.center = point;
    self.marker.hidden = NO;
    if ([self.delegate respondsToSelector:@selector(handelColor:)]) [self.delegate handelColor:hex];
}
@end
