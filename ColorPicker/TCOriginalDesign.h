#import <UIKit/UIKit.h>
#import <math.h>

@interface TCOriginalImageButton : UIButton
@property (nonatomic) CGFloat artworkScale;
@end
@interface TCOriginalNavigationController : UINavigationController
@end

// The shipped-era artwork is copied byte-for-byte from c21792c. These helpers
// only make its presentation safe-area-aware; sampling and storage stay modern.
static inline UIColor *TCOriginalBackground(void) { return [UIColor colorWithRed:239.0/255 green:239.0/255 blue:237.0/255 alpha:1]; }
static inline UIColor *TCOriginalDark(void) { return [UIColor colorWithRed:55.0/255 green:55.0/255 blue:54.0/255 alpha:1]; }
static inline UIColor *TCOriginalText(void) { return [UIColor colorWithRed:76.0/255 green:103.0/255 blue:122.0/255 alpha:1]; }
static inline UIImage *TCOriginalImage(NSString *name) { return [UIImage imageNamed:[@"Original." stringByAppendingString:name]]; }
static inline UIImageView *TCOriginalArtwork(NSString *name) {
    UIImageView *view = [[UIImageView alloc] initWithImage:TCOriginalImage(name)];
    view.contentMode = UIViewContentModeScaleAspectFit;
    view.isAccessibilityElement = NO;
    return view;
}
static inline UIButton *TCOriginalButton(NSString *normal, NSString *selected, NSString *label, NSString *identifier, id target, SEL action) {
    UIButton *button = [[TCOriginalImageButton alloc] initWithFrame:CGRectZero];
    [button setImage:TCOriginalImage(normal) forState:UIControlStateNormal];
    if (selected) {
        [button setImage:TCOriginalImage(selected) forState:UIControlStateHighlighted];
        [button setImage:TCOriginalImage(selected) forState:UIControlStateSelected];
    }
    button.imageView.contentMode = UIViewContentModeScaleAspectFit;
    button.accessibilityLabel = label;
    button.accessibilityIdentifier = identifier;
    button.pointerInteractionEnabled = YES;
    [button addTarget:target action:action forControlEvents:UIControlEventTouchUpInside];
    return button;
}
static inline UILabel *TCOriginalValueLabel(void) {
    UILabel *label = [UILabel new];
    label.textColor = TCOriginalText();
    label.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:12]];
    label.adjustsFontForContentSizeCategory = YES;
    label.numberOfLines = 1;
    label.isAccessibilityElement = NO;
    return label;
}
static inline CGFloat TCOriginalScale(UIView *view) {
    return MIN(1.5, MAX(0.5, (view.bounds.size.width-view.safeAreaInsets.left-view.safeAreaInsets.right)/320.0));
}

@interface TCOriginalReadout : UIView
@property (nonatomic, copy) NSString *hex;
@property (nonatomic) BOOL historyRow;
@property (nonatomic, strong, readonly) UIView *swatch;
- (CGFloat)preferredHeightForWidth:(CGFloat)width;
- (CGFloat)preferredHeightForWidth:(CGFloat)width traits:(UITraitCollection *)traits;
@end
