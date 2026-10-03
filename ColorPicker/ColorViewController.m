#import "ColorViewController.h"
#import "ColorDetectView.h"
#import "TCColorUtilities.h"
#import <math.h>

@interface ColorViewController () <ColorDetectViewDelegate>
@property (nonatomic, strong) UIImage *image;
@property (nonatomic, strong) ColorDetectView *colorDetectView;
@property (nonatomic, strong) UILabel *colorLabel;
@property (nonatomic, strong) UIButton *saveButton;
@property (nonatomic, copy) NSString *selectedHex;
@property (nonatomic, strong) UIView *swatch;
@property (nonatomic, strong) UISlider *zoomSlider;
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
    self.zoomSlider = [UISlider new];
    self.zoomSlider.minimumValue = 0;
    self.zoomSlider.maximumValue = 2; // Logarithmic 1–100×, matching the original zoom range.
    self.zoomSlider.minimumValueImage = [UIImage systemImageNamed:@"minus.magnifyingglass"];
    self.zoomSlider.maximumValueImage = [UIImage systemImageNamed:@"plus.magnifyingglass"];
    self.zoomSlider.accessibilityLabel = NSLocalizedString(@"Zoom", nil);
    self.zoomSlider.accessibilityIdentifier = @"photoZoom";
    self.zoomSlider.accessibilityValue = @"1.0×";
    [self.zoomSlider.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    [self.zoomSlider addTarget:self action:@selector(zoomChanged:) forControlEvents:UIControlEventValueChanged];
    UIStackView *panel = [[UIStackView alloc] initWithArrangedSubviews:@[readout, self.zoomSlider, actions]];
    panel.axis = UILayoutConstraintAxisVertical;
    panel.spacing = 8;
    panel.translatesAutoresizingMaskIntoConstraints = NO;
    UIScrollView *controls = [UIScrollView new];
    controls.accessibilityIdentifier = @"photoControls";
    controls.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:controls];
    [controls addSubview:panel];
    NSLayoutConstraint *naturalHeight = [controls.heightAnchor constraintEqualToAnchor:panel.heightAnchor constant:16];
    naturalHeight.priority = UILayoutPriorityDefaultHigh;
    naturalHeight.active = YES;
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.colorDetectView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.colorDetectView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.colorDetectView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.colorDetectView.bottomAnchor constraintEqualToAnchor:controls.topAnchor constant:-8],
        [controls.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [controls.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [controls.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [controls.heightAnchor constraintLessThanOrEqualToAnchor:safe.heightAnchor multiplier:0.6],
        [panel.leadingAnchor constraintEqualToAnchor:controls.contentLayoutGuide.leadingAnchor constant:16],
        [panel.trailingAnchor constraintEqualToAnchor:controls.contentLayoutGuide.trailingAnchor constant:-16],
        [panel.topAnchor constraintEqualToAnchor:controls.contentLayoutGuide.topAnchor constant:8],
        [panel.bottomAnchor constraintEqualToAnchor:controls.contentLayoutGuide.bottomAnchor constant:-8],
        [panel.widthAnchor constraintEqualToAnchor:controls.frameLayoutGuide.widthAnchor constant:-32]
    ]];
}
- (UIView *)viewForZoomingInScrollView:(UIScrollView *)scrollView { return self.colorDetectView.imageView; }
- (void)scrollViewDidZoom:(UIScrollView *)scrollView {
    [self.colorDetectView setNeedsLayout];
    self.zoomSlider.value = log10(MAX(1,scrollView.zoomScale));
    self.zoomSlider.accessibilityValue = [NSString stringWithFormat:@"%.1f×",scrollView.zoomScale];
}
- (void)zoomChanged:(UISlider *)slider { [self.colorDetectView setZoomScale:pow(10,slider.value) animated:NO]; }
- (void)sampleCenter { [self.colorDetectView sampleVisibleCenter]; }
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
