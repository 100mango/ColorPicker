#import "ColorViewController.h"
#import "TCOriginalDesign.h"
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
@property (nonatomic, strong) UIView *originalHeader;
@property (nonatomic, strong) UIImageView *originalTitle;
@property (nonatomic, strong) UIButton *backButton;
@property (nonatomic, strong) TCOriginalReadout *originalReadout;
@property (nonatomic, strong) UIButton *sampleButton;
@property (nonatomic, strong) UIScrollView *readoutScroll;
@end
@implementation ColorViewController
- (void)setChooseImage:(UIImage *)image { self.image = image; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title=NSLocalizedString(@"Photo Color",nil); self.view.backgroundColor=TCOriginalBackground();
    self.originalHeader=[UIView new]; self.originalHeader.backgroundColor=TCOriginalDark();
    [self.view addSubview:self.originalHeader]; self.originalTitle=TCOriginalArtwork(@"00 B"); [self.originalHeader addSubview:self.originalTitle];
    self.backButton=TCOriginalButton(@"30x64",nil,NSLocalizedString(@"Back",nil),@"original.back",self,@selector(originalBack));
    self.saveButton=TCOriginalButton(@"530,64",@"530,64 B",NSLocalizedString(@"Save Color",nil),@"saveColor",self,@selector(saveColor));
    self.saveButton.enabled=NO;
    [self.originalHeader addSubview:self.backButton]; [self.originalHeader addSubview:self.saveButton];
    self.colorDetectView=[[ColorDetectView alloc] initWithFrame:CGRectZero andUIImage:self.image];
    self.colorDetectView.delegate=self; self.colorDetectView.backgroundColor=TCOriginalBackground(); [self.view addSubview:self.colorDetectView];
    self.zoomSlider=[UISlider new]; self.zoomSlider.minimumValue=0; self.zoomSlider.maximumValue=2;
    [self.zoomSlider setThumbImage:TCOriginalImage(@"y 148") forState:UIControlStateNormal];
    [self.zoomSlider setMinimumTrackImage:TCOriginalImage(@"130x159") forState:UIControlStateNormal];
    self.zoomSlider.accessibilityLabel=NSLocalizedString(@"Zoom",nil); self.zoomSlider.accessibilityIdentifier=@"photoZoom"; self.zoomSlider.accessibilityValue=@"1.0×";
    [self.zoomSlider addTarget:self action:@selector(zoomChanged:) forControlEvents:UIControlEventValueChanged]; [self.view addSubview:self.zoomSlider];
    self.readoutScroll=[UIScrollView new]; self.readoutScroll.accessibilityIdentifier=@"photoControls";
    self.readoutScroll.contentInsetAdjustmentBehavior=UIScrollViewContentInsetAdjustmentNever;
    [self.view addSubview:self.readoutScroll];
    self.originalReadout=[TCOriginalReadout new]; self.originalReadout.hex=nil;
    self.originalReadout.accessibilityIdentifier=@"sampledColor"; [self.readoutScroll addSubview:self.originalReadout];
    self.swatch=self.originalReadout.swatch;
    // The original color chip remains the visible control. Its explicit action
    // retains center sampling for VoiceOver, keyboard and precise pointer users.
    self.sampleButton=[UIButton buttonWithType:UIButtonTypeCustom];
    self.sampleButton.accessibilityLabel=NSLocalizedString(@"Sample Center",nil); self.sampleButton.accessibilityIdentifier=@"sampleCenter";
    [self.sampleButton addTarget:self action:@selector(sampleCenter) forControlEvents:UIControlEventTouchUpInside]; [self.readoutScroll addSubview:self.sampleButton];
    self.colorLabel=[UILabel new]; // Keep the existing controller's numeric state.
}
- (UIStatusBarStyle)preferredStatusBarStyle { return UIStatusBarStyleLightContent; }
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.navigationController setNavigationBarHidden:YES animated:NO]; }
- (void)originalBack { [self.navigationController popViewControllerAnimated:YES]; }
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    UIEdgeInsets safe=self.view.safeAreaInsets; CGFloat scale=TCOriginalScale(self.view), width=320*scale;
    CGFloat x=(self.view.bounds.size.width-width)/2, header=safe.top+44*scale;
    self.originalHeader.frame=CGRectMake(0,0,self.view.bounds.size.width,header);
    self.originalTitle.frame=CGRectMake(x,safe.top-20*scale,width,64*scale);
    self.backButton.frame=CGRectMake(x+3*scale,safe.top,MAX(44,44*scale),44*scale);
    self.saveButton.frame=CGRectMake(x+253*scale,safe.top,MAX(44,55*scale),44*scale);
    ((TCOriginalImageButton *)self.backButton).artworkScale=scale; ((TCOriginalImageButton *)self.saveButton).artworkScale=scale;
    self.zoomSlider.frame=CGRectMake(x+65*scale,header,190*scale,44);
    CGFloat readoutHeight=[self.originalReadout preferredHeightForWidth:width];
    CGFloat available=MAX(0,self.view.bounds.size.height-safe.bottom-header-44);
    CGFloat readoutViewport=MIN(readoutHeight,MAX(44,available*0.55));
    self.readoutScroll.frame=CGRectMake(x,self.view.bounds.size.height-safe.bottom-readoutViewport,width,readoutViewport);
    self.originalReadout.frame=CGRectMake(0,0,width,readoutHeight); self.readoutScroll.contentSize=CGSizeMake(width,readoutHeight);
    BOOL large=UIContentSizeCategoryIsAccessibilityCategory(self.traitCollection.preferredContentSizeCategory);
    self.sampleButton.frame=large ? CGRectMake(16,16,63,63) : CGRectMake(21*scale,(readoutHeight-63*scale)/2,63*scale,63*scale);
    self.colorDetectView.frame=CGRectMake(x,header+44,width,MAX(1,available-readoutViewport));
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
    self.saveButton.enabled = YES; self.saveButton.selected=NO;
    self.originalReadout.hex=hex; self.saveButton.accessibilityValue=nil;
}
- (void)saveColor {
    TCColorStore *store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    if ([store addColor:self.selectedHex]) {
        self.saveButton.enabled = NO;
        self.saveButton.selected=YES; self.saveButton.accessibilityValue=NSLocalizedString(@"Saved",nil);
        UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, NSLocalizedString(@"Color saved", nil));
    }
}
- (BOOL)canBecomeFirstResponder { return YES; }
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; [self becomeFirstResponder]; }
- (NSArray<UIKeyCommand *> *)keyCommands {
    if (self.presentedViewController || self.splitViewController.presentedViewController) return @[];
    NSMutableArray *commands = [NSMutableArray new];
    NSArray *inputs = @[@"s", @" ", @"+", @"-", @"0", UIKeyInputLeftArrow, UIKeyInputRightArrow, UIKeyInputUpArrow, UIKeyInputDownArrow];
    NSArray *actions = @[@"saveColor", @"sampleCenter", @"zoomIn", @"zoomOut", @"resetZoom", @"movePixel:", @"movePixel:", @"movePixel:", @"movePixel:"];
    NSArray *titles = @[NSLocalizedString(@"Save Color", nil), NSLocalizedString(@"Sample Center", nil), NSLocalizedString(@"Zoom In", nil), NSLocalizedString(@"Zoom Out", nil), NSLocalizedString(@"Actual Fit", nil)];
    for (NSUInteger i = 0; i < inputs.count; i++) {
        UIKeyCommand *command = [UIKeyCommand keyCommandWithInput:inputs[i] modifierFlags:(i == 0 || i == 4) ? UIKeyModifierCommand : 0 action:NSSelectorFromString(actions[i])];
        command.discoverabilityTitle = i < titles.count ? titles[i] : NSLocalizedString(@"Move Selected Pixel", nil);
        if (@available(iOS 15.0, *)) command.wantsPriorityOverSystemBehavior = i >= 5;
        [commands addObject:command];
    }
    return commands;
}
- (BOOL)canPerformAction:(SEL)action withSender:(id)sender {
    if (action == @selector(saveColor)) return self.saveButton.enabled && !self.presentedViewController && !self.splitViewController.presentedViewController;
    return [super canPerformAction:action withSender:sender];
}
- (void)zoomIn { [self.colorDetectView setZoomScale:MIN(100,self.colorDetectView.zoomScale * 2) animated:NO]; }
- (void)zoomOut { [self.colorDetectView setZoomScale:MAX(1,self.colorDetectView.zoomScale / 2) animated:NO]; }
- (void)resetZoom { [self.colorDetectView setZoomScale:1 animated:NO]; }
- (void)movePixel:(UIKeyCommand *)command {
    ColorDetectView *canvas = self.colorDetectView;
    if (!canvas.hasSelectedPoint) { [canvas sampleVisibleCenter]; return; }
    CGSize pixels = CGSizeMake(CGImageGetWidth(self.image.CGImage),CGImageGetHeight(self.image.CGImage));
    if (self.image.imageOrientation == UIImageOrientationLeft || self.image.imageOrientation == UIImageOrientationRight || self.image.imageOrientation == UIImageOrientationLeftMirrored || self.image.imageOrientation == UIImageOrientationRightMirrored) pixels = CGSizeMake(pixels.height,pixels.width);
    if (pixels.width <= 0 || pixels.height <= 0) return;
    CGPoint point = canvas.selectedNormalizedPoint;
    if ([command.input isEqualToString:UIKeyInputLeftArrow]) point.x -= 1 / pixels.width;
    if ([command.input isEqualToString:UIKeyInputRightArrow]) point.x += 1 / pixels.width;
    if ([command.input isEqualToString:UIKeyInputUpArrow]) point.y -= 1 / pixels.height;
    if ([command.input isEqualToString:UIKeyInputDownArrow]) point.y += 1 / pixels.height;
    point.x = MAX(0,MIN(1 - 0.5 / pixels.width,point.x));
    point.y = MAX(0,MIN(1 - 0.5 / pixels.height,point.y));
    [canvas sampleAtImagePoint:CGPointMake(point.x * canvas.imageView.bounds.size.width,point.y * canvas.imageView.bounds.size.height)];
    CGPoint selected = [canvas.imageView convertPoint:CGPointMake(point.x * canvas.imageView.bounds.size.width,point.y * canvas.imageView.bounds.size.height) toView:canvas];
    [canvas scrollRectToVisible:CGRectMake(selected.x-22,selected.y-22,44,44) animated:NO];
}
@end

