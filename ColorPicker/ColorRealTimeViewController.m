#import "ColorRealTimeViewController.h"
#import "TCOriginalDesign.h"
#import "TCColorUtilities.h"

@interface ColorRealTimeViewController ()
@property (atomic, strong) AVCaptureSession *session;
@property (nonatomic, strong) AVCaptureVideoDataOutput *output;
@property (nonatomic, strong) AVCaptureVideoPreviewLayer *preview;
@property (nonatomic, strong) UIView *cameraView;
@property (nonatomic, strong) UILabel *statusLabel;
@property (nonatomic, strong) UIButton *saveButton;
@property (nonatomic, strong) UIImageView *reticle;
@property (nonatomic, strong) TCCaptureGate *captureGate;
@property (nonatomic, strong) UIButton *backButton;
@property (nonatomic, strong) UIImageView *originalRGB;
@property (nonatomic, strong) NSArray<UILabel *> *originalValues;
@property (nonatomic, strong) UIView *centerSwatch;
@property (nonatomic, strong) UIScrollView *statusScroll;
@property (atomic) BOOL interrupted;
@property (nonatomic) BOOL permissionRequestPending;
@property (nonatomic, strong) dispatch_queue_t sessionQueue;
@property (atomic) BOOL wantsCapture;
@property (nonatomic) BOOL visible;
@property (nonatomic) CFTimeInterval lastSampleTime;
@property (nonatomic, strong) AVCaptureDeviceRotationCoordinator *rotationCoordinator API_AVAILABLE(ios(17.0));
@end
@implementation ColorRealTimeViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title=NSLocalizedString(@"Live Color",nil); self.view.backgroundColor=UIColor.blackColor;
    self.captureGate=[TCCaptureGate new]; self.sessionQueue=dispatch_queue_create("com.mango.touchColor.camera",DISPATCH_QUEUE_SERIAL);
    self.cameraView=[UIView new]; self.cameraView.backgroundColor=UIColor.blackColor; self.cameraView.accessibilityIdentifier=@"liveViewport";
    [self.view addSubview:self.cameraView];
    self.centerSwatch=[UIView new]; [self.cameraView addSubview:self.centerSwatch];
    self.reticle=TCOriginalArtwork(@"275,436"); self.reticle.isAccessibilityElement=YES;
    self.reticle.accessibilityLabel=NSLocalizedString(@"Live color sample point at the center of the camera",nil); [self.cameraView addSubview:self.reticle];
    self.backButton=TCOriginalButton(@"0,23",@"0,23 B",NSLocalizedString(@"Back",nil),@"original.back",self,@selector(originalBack));
    [self.view addSubview:self.backButton];
    self.saveButton=TCOriginalButton(@"500,883",@"500,883 B",NSLocalizedString(@"Save Color",nil),@"saveLiveColor",self,@selector(save));
    [self.saveButton setImage:TCOriginalImage(@"500,883 C") forState:UIControlStateSelected]; self.saveButton.enabled=NO; [self.view addSubview:self.saveButton];
    self.originalRGB=TCOriginalArtwork(@"0,817"); [self.view addSubview:self.originalRGB];
    NSMutableArray *values=[NSMutableArray new];
    for (NSUInteger i=0;i<3;i++) { UILabel *label=TCOriginalValueLabel(); label.text=@"—"; [values addObject:label]; [self.view addSubview:label]; }
    self.originalValues=values;
    self.statusLabel=[UILabel new]; self.statusLabel.numberOfLines=0; self.statusLabel.textColor=UIColor.whiteColor;
    self.statusLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleBody]; self.statusLabel.adjustsFontForContentSizeCategory=YES;
    self.statusLabel.accessibilityIdentifier=@"cameraStatus";
    self.statusLabel.text=self.sourceFlowActive ? NSLocalizedString(@"Camera paused",nil) : NSLocalizedString(@"Waiting for camera",nil);
    self.statusScroll=[UIScrollView new]; self.statusScroll.accessibilityIdentifier=@"liveControls";
    self.statusScroll.backgroundColor=[UIColor colorWithWhite:0 alpha:0.65]; self.statusScroll.layer.cornerRadius=8;
    [self.statusScroll addSubview:self.statusLabel]; [self.view addSubview:self.statusScroll];
    NSNotificationCenter *notifications = NSNotificationCenter.defaultCenter;
    [notifications addObserver:self selector:@selector(sceneDeactivated:) name:UISceneWillDeactivateNotification object:nil];
    [notifications addObserver:self selector:@selector(sceneActivated:) name:UISceneDidActivateNotification object:nil];
    [notifications addObserver:self selector:@selector(captureInterrupted:) name:AVCaptureSessionWasInterruptedNotification object:nil];
    [notifications addObserver:self selector:@selector(captureEndedInterruption:) name:AVCaptureSessionInterruptionEndedNotification object:nil];
    [notifications addObserver:self selector:@selector(captureError:) name:AVCaptureSessionRuntimeErrorNotification object:nil];
}
- (UIStatusBarStyle)preferredStatusBarStyle { return UIStatusBarStyleLightContent; }
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.navigationController setNavigationBarHidden:YES animated:NO]; }
- (void)originalBack { [self.navigationController popViewControllerAnimated:YES]; }
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; self.visible = YES; [self resumeCapture]; }
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; self.visible = NO; [self pauseCapture]; }
- (void)dealloc {
    if (@available(iOS 17.0, *)) [_rotationCoordinator removeObserver:self forKeyPath:@"videoRotationAngleForHorizonLevelPreview" context:NULL];
    [NSNotificationCenter.defaultCenter removeObserver:self];
    [_captureGate invalidate];
    AVCaptureSession *session = _session;
    AVCaptureVideoDataOutput *output = _output;
    if (_sessionQueue) dispatch_async(_sessionQueue, ^{ [output setSampleBufferDelegate:nil queue:NULL]; [session stopRunning]; });
}
- (void)sceneActivated:(NSNotification *)notification { if (notification.object == self.view.window.windowScene) [self resumeCapture]; }
- (void)sceneDeactivated:(NSNotification *)notification { if (notification.object == self.view.window.windowScene) [self pauseCapture]; }
- (void)pauseCapture {
    self.wantsCapture = NO;
    [self.captureGate invalidate];
    self.saveButton.enabled = NO; [self.view setNeedsLayout];
    dispatch_async(self.sessionQueue, ^{ [self.session stopRunning]; });
}
- (void)setSourceFlowActive:(BOOL)sourceFlowActive {
    _sourceFlowActive = sourceFlowActive;
    if (!self.isViewLoaded) return;
    if (sourceFlowActive) { [self pauseCapture]; self.statusLabel.text = NSLocalizedString(@"Camera paused", nil); }
    else [self resumeCapture];
}
- (void)resumeCapture {
    if (self.sourceFlowActive || !self.visible || !self.view.window || self.view.window.windowScene.activationState != UISceneActivationStateForegroundActive) return;
    if (self.interrupted) { self.statusLabel.text = NSLocalizedString(@"Camera interrupted. Waiting to resume.", nil); return; }
    [self.captureGate invalidate];
    self.saveButton.enabled = NO; [self.view setNeedsLayout];
    AVCaptureDevice *device = [AVCaptureDevice defaultDeviceWithDeviceType:AVCaptureDeviceTypeBuiltInWideAngleCamera mediaType:AVMediaTypeVideo position:AVCaptureDevicePositionBack] ?: [AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];
    TCCameraAccess access = TCCameraAccessForStatus([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo], device != nil);
    if (access == TCCameraAccessUnavailable || access == TCCameraAccessBlocked) {
        self.wantsCapture = NO;
        self.statusLabel.text = access == TCCameraAccessUnavailable ? NSLocalizedString(@"A camera is not available on this device. Choose a photo from the main screen instead.", nil) : NSLocalizedString(@"Camera access is off. Enable it for TouchColor in Settings, or choose a photo instead.", nil);
        return;
    }
    if (access == TCCameraAccessAsk) {
        self.wantsCapture = NO;
        if (self.permissionRequestPending) return;
        self.permissionRequestPending = YES;
        __weak typeof(self) weakSelf = self;
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {
            dispatch_async(dispatch_get_main_queue(), ^{ weakSelf.permissionRequestPending = NO; [weakSelf resumeCapture]; });
        }];
        return;
    }
    self.wantsCapture = YES;
    NSUInteger requestedGeneration = self.captureGate.generation;
    self.statusLabel.text = NSLocalizedString(@"Waiting for camera", nil);
    __weak typeof(self) weakSelf = self;
    dispatch_async(self.sessionQueue, ^{
        typeof(self) self = weakSelf;
        if (!self || !self.wantsCapture || self.interrupted || self.captureGate.generation != requestedGeneration) return;
        NSUInteger generation = [self.captureGate beginCaptureAfterGeneration:requestedGeneration];
        if (!generation) return;
        if (!self.session) {
            AVCaptureSession *session = [AVCaptureSession new];
            session.automaticallyConfiguresCaptureDeviceForWideColor = NO;
            [session beginConfiguration];
            if ([session canSetSessionPreset:AVCaptureSessionPreset640x480]) session.sessionPreset = AVCaptureSessionPreset640x480;
            NSError *error;
            AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&error];
            AVCaptureVideoDataOutput *output = [AVCaptureVideoDataOutput new];
            output.videoSettings = @{(NSString *)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA)};
            output.alwaysDiscardsLateVideoFrames = YES;
            if (!input || ![session canAddInput:input] || ![session canAddOutput:output]) {
                [session commitConfiguration];
                dispatch_async(dispatch_get_main_queue(), ^{ if ([self.captureGate acceptsGeneration:generation]) [self showCaptureFailure]; });
                return;
            }
            [session addInput:input];
            [session addOutput:output];
            // sRGB camera output avoids interpreting wide-gamut bytes as sRGB.
            if ([device.activeFormat.supportedColorSpaces containsObject:@(AVCaptureColorSpace_sRGB)] && [device lockForConfiguration:&error]) {
                device.activeColorSpace = AVCaptureColorSpace_sRGB;
                [device unlockForConfiguration];
            }
            [output setSampleBufferDelegate:self queue:self.sessionQueue];
            [session commitConfiguration];
            self.output = output;
            self.session = session;
            dispatch_async(dispatch_get_main_queue(), ^{
                self.preview = [AVCaptureVideoPreviewLayer layerWithSession:session];
                self.preview.videoGravity = AVLayerVideoGravityResizeAspectFill;
                [self.cameraView.layer insertSublayer:self.preview atIndex:0];
                if (@available(iOS 17.0, *)) {
                    self.rotationCoordinator = [[AVCaptureDeviceRotationCoordinator alloc] initWithDevice:device previewLayer:self.preview];
                    [self.rotationCoordinator addObserver:self forKeyPath:@"videoRotationAngleForHorizonLevelPreview" options:NSKeyValueObservingOptionInitial | NSKeyValueObservingOptionNew context:NULL];
                }
                [self.view setNeedsLayout];
            });
        }
        if (self.wantsCapture && [self.captureGate acceptsGeneration:generation] && !self.session.running) [self.session startRunning];
    });
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    UIEdgeInsets safe=self.view.safeAreaInsets; CGFloat scale=TCOriginalScale(self.view);
    CGFloat width=self.view.bounds.size.width, height=self.view.bounds.size.height;
    self.cameraView.frame=self.view.bounds;
    self.reticle.frame=CGRectMake((width-45*scale)/2,(height-45*scale)/2,45*scale,45*scale);
    self.centerSwatch.frame=CGRectMake((width-23*scale)/2,(height-23*scale)/2,23*scale,23*scale); self.centerSwatch.layer.cornerRadius=11.5*scale;
    self.backButton.frame=CGRectMake(safe.left,safe.top,MAX(44,52.5*scale),MAX(44,48*scale));
    self.saveButton.frame=CGRectMake(width-safe.right-70*scale,height-safe.bottom-MAX(44,38.5*scale),70*scale,MAX(44,38.5*scale));
    CGFloat rgbHeight=71.5*scale;
    self.originalRGB.frame=CGRectMake(safe.left,height-safe.bottom-rgbHeight,85.5*scale,rgbHeight);
    for (NSUInteger i=0;i<3;i++) {
        UILabel *label=self.originalValues[i]; label.font=[[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:17*scale]];
        label.frame=CGRectMake(safe.left+37*scale,height-safe.bottom-rgbHeight+(2+20*i)*scale,45*scale,40*scale);
    }
    BOOL large=UIContentSizeCategoryIsAccessibilityCategory(self.traitCollection.preferredContentSizeCategory);
    for (UILabel *label in self.originalValues) label.hidden=large;
    self.originalRGB.hidden=large;
    BOOL sampled=self.saveButton.enabled && self.captureGate.selectedHex.length;
    self.statusLabel.textColor=sampled && !large ? UIColor.clearColor : UIColor.whiteColor;
    self.statusScroll.backgroundColor=sampled && !large ? UIColor.clearColor : [UIColor colorWithWhite:0 alpha:0.65];
    CGFloat statusWidth=MAX(44,width-safe.left-safe.right-32);
    CGSize statusSize=[self.statusLabel sizeThatFits:CGSizeMake(statusWidth-24,CGFLOAT_MAX)];
    CGFloat viewport=MIN(statusSize.height+24,MAX(44,(height-safe.top-safe.bottom)*0.45));
    self.statusScroll.frame=CGRectMake(safe.left+16,safe.top+MAX(44,48*scale)+8,statusWidth,viewport);
    self.statusLabel.frame=CGRectMake(12,12,statusWidth-24,statusSize.height); self.statusScroll.contentSize=CGSizeMake(statusWidth,statusSize.height+24);

    [CATransaction begin]; [CATransaction setDisableActions:YES];
    self.preview.frame = self.cameraView.bounds;
    AVCaptureConnection *connection = self.preview.connection;
    UIInterfaceOrientation orientation = self.view.window.windowScene.interfaceOrientation;
    if (@available(iOS 17.0, *)) {
        CGFloat angle = self.rotationCoordinator.videoRotationAngleForHorizonLevelPreview;
        if (self.rotationCoordinator && [connection isVideoRotationAngleSupported:angle]) connection.videoRotationAngle = angle;
    } else if (connection.isVideoOrientationSupported && orientation != UIInterfaceOrientationUnknown) {
        connection.videoOrientation = (AVCaptureVideoOrientation)orientation;
    }
    [CATransaction commit];
}
- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object change:(NSDictionary<NSKeyValueChangeKey,id> *)change context:(void *)context {
    if (@available(iOS 17.0, *)) {
        if (object == self.rotationCoordinator && [keyPath isEqualToString:@"videoRotationAngleForHorizonLevelPreview"]) {
            // AVFoundation delivers rotation observations on main; preview geometry stays on main too.
            CGFloat angle = self.rotationCoordinator.videoRotationAngleForHorizonLevelPreview;
            if ([self.preview.connection isVideoRotationAngleSupported:angle]) self.preview.connection.videoRotationAngle = angle;
            return;
        }
    }
    [super observeValueForKeyPath:keyPath ofObject:object change:change context:context];
}
- (void)showCaptureFailure {
    self.wantsCapture = NO;
    [self.captureGate invalidate];
    self.saveButton.enabled = NO; [self.view setNeedsLayout];
    self.statusLabel.text = NSLocalizedString(@"The camera could not start. Go back and try again, or choose a photo.", nil);
}
- (void)captureInterrupted:(NSNotification *)notification {
    if (notification.object != self.session) return;
    // Invalidate immediately on the notification thread, before any queued UI delivery can run.
    self.interrupted = YES;
    self.wantsCapture = NO;
    NSUInteger generation = [self.captureGate invalidate];
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.captureGate.generation != generation) return;
        self.saveButton.enabled = NO; [self.view setNeedsLayout];
        self.statusLabel.text = NSLocalizedString(@"Camera interrupted. Waiting to resume.", nil);
    });
}
- (void)captureEndedInterruption:(NSNotification *)notification {
    if (notification.object != self.session) return;
    self.interrupted = NO;
    dispatch_async(dispatch_get_main_queue(), ^{ [self resumeCapture]; });
}
- (void)captureError:(NSNotification *)notification {
    if (notification.object != self.session) return;
    self.wantsCapture = NO;
    NSUInteger generation = [self.captureGate invalidate];
    NSError *error = notification.userInfo[AVCaptureSessionErrorKey];
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.captureGate.generation != generation) return;
        self.saveButton.enabled = NO; [self.view setNeedsLayout];
        if (error.code == AVErrorMediaServicesWereReset) [self resumeCapture]; else [self showCaptureFailure];
    });
}
- (void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer fromConnection:(AVCaptureConnection *)connection {
    NSUInteger generation = self.captureGate.generation;
    if (!self.wantsCapture || self.interrupted || output != self.output || ![self.captureGate acceptsGeneration:generation]) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - self.lastSampleTime < 0.1) return;
    self.lastSampleTime = now;
    // Aspect-fill crop and rotations share the sensor's center; no assumed dimensions/row stride.
    NSString *hex = TCSampleCameraBuffer(CMSampleBufferGetImageBuffer(sampleBuffer));
    if (!hex) return;
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf displaySample:hex generation:generation]; });
}
- (void)displaySample:(NSString *)hex generation:(NSUInteger)generation {
    if (self.sourceFlowActive || !self.wantsCapture || self.interrupted || !self.visible || ![self.captureGate acceptHex:hex generation:generation]) return;
    self.statusLabel.text = [NSString stringWithFormat:@"%@  •  %@", hex, TCRGBDescription(hex)];
    self.saveButton.enabled = YES; self.saveButton.selected=NO;
    self.centerSwatch.backgroundColor=TCUIColorFromHex(hex);
    unsigned int value=0; [[NSScanner scannerWithString:[hex substringFromIndex:1]] scanHexInt:&value];
    self.originalValues[0].text=[NSString stringWithFormat:@"%u",(value>>16)&255];
    self.originalValues[1].text=[NSString stringWithFormat:@"%u",(value>>8)&255];
    self.originalValues[2].text=[NSString stringWithFormat:@"%u",value&255];
    self.reticle.accessibilityValue=[NSString stringWithFormat:@"%@, %@",hex,TCRGBDescription(hex)];
    [self.view setNeedsLayout];
}
- (void)save {
    TCColorStore *store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    if ([store addColor:self.captureGate.selectedHex]) { self.saveButton.selected=YES; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, NSLocalizedString(@"Color saved", nil)); }
}
@end

