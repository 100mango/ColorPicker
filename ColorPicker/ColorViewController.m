#import "ColorViewController.h"
#import "ColorDetectView.h"
#import "TCColorUtilities.h"

@interface ColorViewController () <ColorDetectViewDelegate>
@property (nonatomic, strong) UIImage *image;
@property (nonatomic, strong) ColorDetectView *colorDetectView;
@property (nonatomic, strong) UILabel *colorLabel;
@property (nonatomic, strong) UIButton *saveButton;
@property (nonatomic, copy) NSString *selectedHex;
@property (nonatomic, strong) UIView *swatch;
@end
@implementation ColorViewController
- (void)setChooseImage:(UIImage *)image { self.image = image; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = NSLocalizedString(@"Photo Color", nil);
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.colorDetectView = [[ColorDetectView alloc] initWithFrame:CGRectZero andUIImage:self.image];
    self.colorDetectView.delegate = self;
    self.colorDetectView.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.colorDetectView];
    self.colorLabel = [UILabel new];
    self.colorLabel.text = NSLocalizedString(@"Tap a pixel or sample the center", nil);
    self.colorLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    self.colorLabel.adjustsFontForContentSizeCategory = YES;
    self.colorLabel.numberOfLines = 0;
    self.colorLabel.accessibilityIdentifier = @"sampledColor";
    self.swatch = [UIView new];
    self.swatch.layer.cornerRadius = 10;
    [self.swatch.widthAnchor constraintEqualToConstant:44].active = YES;
    [self.swatch.heightAnchor constraintEqualToConstant:44].active = YES;
    UIStackView *readout = [[UIStackView alloc] initWithArrangedSubviews:@[self.swatch, self.colorLabel]];
    readout.spacing = 12;
    readout.alignment = UIStackViewAlignmentCenter;
    UIButton *sample = [UIButton buttonWithType:UIButtonTypeSystem];
    [sample setTitle:NSLocalizedString(@"Sample Center", nil) forState:UIControlStateNormal];
    sample.accessibilityIdentifier = @"sampleCenter";
    [sample addTarget:self action:@selector(sampleCenter) forControlEvents:UIControlEventTouchUpInside];
    self.saveButton = [UIButton buttonWithType:UIButtonTypeSystem];
    self.saveButton.configuration = UIButtonConfiguration.filledButtonConfiguration;
    [self.saveButton setTitle:NSLocalizedString(@"Save Color", nil) forState:UIControlStateNormal];
    self.saveButton.accessibilityIdentifier = @"saveColor";
    self.saveButton.enabled = NO;
    [self.saveButton addTarget:self action:@selector(saveColor) forControlEvents:UIControlEventTouchUpInside];
    [sample.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    [self.saveButton.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    UIStackView *actions = [[UIStackView alloc] initWithArrangedSubviews:@[sample, self.saveButton]];
    actions.distribution = UIStackViewDistributionFillEqually;
    actions.spacing = 12;
    UIStackView *panel = [[UIStackView alloc] initWithArrangedSubviews:@[readout, actions]];
    panel.axis = UILayoutConstraintAxisVertical;
    panel.spacing = 8;
    panel.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:panel];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.colorDetectView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.colorDetectView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.colorDetectView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.colorDetectView.bottomAnchor constraintEqualToAnchor:panel.topAnchor constant:-8],
        [panel.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [panel.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [panel.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-8]
    ]];
}
- (UIView *)viewForZoomingInScrollView:(UIScrollView *)scrollView { return self.colorDetectView.imageView; }
- (void)scrollViewDidZoom:(UIScrollView *)scrollView { [self.colorDetectView setNeedsLayout]; }
- (void)sampleCenter {
    // Sample the visible center, including the user's pan/zoom position.
    CGPoint point = [self.colorDetectView convertPoint:CGPointMake(CGRectGetMidX(self.colorDetectView.bounds), CGRectGetMidY(self.colorDetectView.bounds)) toView:self.colorDetectView.imageView];
    CGPoint normalized;
    if (TCNormalizedPoint(point, self.colorDetectView.imageView.bounds, &normalized)) [self handelColor:TCSampleImage(self.image, normalized)];
}
- (void)handelColor:(NSString *)hex {
    if (!TCNormalizeHexColor(hex)) return;
    self.selectedHex = hex;
    self.colorLabel.text = [NSString stringWithFormat:@"%@\n%@", hex, TCRGBDescription(hex)];
    self.swatch.backgroundColor = TCUIColorFromHex(hex);
    self.saveButton.enabled = YES;
    [self.saveButton setTitle:NSLocalizedString(@"Save Color", nil) forState:UIControlStateNormal];
}
- (void)saveColor {
    TCColorStore *store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    if ([store addColor:self.selectedHex]) {
        self.saveButton.enabled = NO;
        [self.saveButton setTitle:NSLocalizedString(@"Saved", nil) forState:UIControlStateNormal];
        UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, NSLocalizedString(@"Color saved", nil));
    }
}
@end
