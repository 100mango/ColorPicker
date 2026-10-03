#import "ColorRealTimeViewController.h"
#import "TCColorUtilities.h"

@interface ColorRealTimeViewController ()
@property (nonatomic, strong) AVCaptureSession *session;
@property (nonatomic, strong) AVCaptureVideoDataOutput *output;
@property (nonatomic, strong) AVCaptureVideoPreviewLayer *preview;
@property (nonatomic, strong) UIView *cameraView;
@property (nonatomic, strong) UILabel *statusLabel;
@property (nonatomic, strong) UIButton *saveButton;
@property (nonatomic, strong) UIImageView *reticle;
@property (nonatomic, copy) NSString *selectedHex;
@property (nonatomic, strong) dispatch_queue_t sessionQueue;
@property (atomic) BOOL wantsCapture;
@property (nonatomic) BOOL visible;
@property (nonatomic) CFTimeInterval lastSampleTime;
@end
@implementation ColorRealTimeViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = NSLocalizedString(@"Live Color", nil);
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.sessionQueue = dispatch_queue_create("com.mango.touchColor.camera", DISPATCH_QUEUE_SERIAL);
    self.cameraView = [UIView new];
    self.cameraView.backgroundColor = UIColor.blackColor;
    self.cameraView.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.cameraView];
    self.reticle = [[UIImageView alloc] initWithImage:[UIImage systemImageNamed:@"viewfinder"]];
    self.reticle.tintColor = UIColor.whiteColor;
    self.reticle.translatesAutoresizingMaskIntoConstraints = NO;
    self.reticle.isAccessibilityElement = YES;
    self.reticle.accessibilityLabel = NSLocalizedString(@"Live color sample point at the center of the camera", nil);
    [self.cameraView addSubview:self.reticle];
    self.statusLabel = [UILabel new];
    self.statusLabel.numberOfLines = 0;
    self.statusLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    self.statusLabel.adjustsFontForContentSizeCategory = YES;
    self.statusLabel.text = NSLocalizedString(@"Waiting for camera", nil);
    self.statusLabel.accessibilityIdentifier = @"cameraStatus";
    self.saveButton = [UIButton buttonWithType:UIButtonTypeSystem];
    self.saveButton.configuration = UIButtonConfiguration.filledButtonConfiguration;
    [self.saveButton setTitle:NSLocalizedString(@"Save Color", nil) forState:UIControlStateNormal];
    self.saveButton.enabled = NO;
    self.saveButton.accessibilityIdentifier = @"saveLiveColor";
    [self.saveButton addTarget:self action:@selector(save) forControlEvents:UIControlEventTouchUpInside];
    [self.saveButton.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    UIStackView *panel = [[UIStackView alloc] initWithArrangedSubviews:@[self.statusLabel, self.saveButton]];
    panel.axis = UILayoutConstraintAxisVertical;
    panel.spacing = 8;
    panel.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:panel];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.cameraView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor], [self.cameraView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.cameraView.topAnchor constraintEqualToAnchor:safe.topAnchor], [self.cameraView.bottomAnchor constraintEqualToAnchor:panel.topAnchor constant:-8],
        [panel.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16], [panel.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [panel.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-8],
        [self.reticle.centerXAnchor constraintEqualToAnchor:self.cameraView.centerXAnchor], [self.reticle.centerYAnchor constraintEqualToAnchor:self.cameraView.centerYAnchor],
        [self.reticle.widthAnchor constraintEqualToConstant:44], [self.reticle.heightAnchor constraintEqualToConstant:44]
    ]];
    NSNotificationCenter *notifications = NSNotificationCenter.defaultCenter;
    [notifications addObserver:self selector:@selector(sceneDeactivated:) name:UISceneWillDeactivateNotification object:nil];
    [notifications addObserver:self selector:@selector(sceneActivated:) name:UISceneDidActivateNotification object:nil];
    [notifications addObserver:self selector:@selector(captureInterrupted:) name:AVCaptureSessionWasInterruptedNotification object:nil];
    [notifications addObserver:self selector:@selector(captureEndedInterruption:) name:AVCaptureSessionInterruptionEndedNotification object:nil];
    [notifications addObserver:self selector:@selector(captureError:) name:AVCaptureSessionRuntimeErrorNotification object:nil];
}
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; self.visible = YES; [self resumeCapture]; }
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; self.visible = NO; [self pauseCapture]; }
- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
    [_output setSampleBufferDelegate:nil queue:NULL];
    AVCaptureSession *session = _session;
    if (_sessionQueue) dispatch_async(_sessionQueue, ^{ [session stopRunning]; });
}
- (void)sceneActivated:(NSNotification *)notification { if (notification.object == self.view.window.windowScene) [self resumeCapture]; }
- (void)sceneDeactivated:(NSNotification *)notification { if (notification.object == self.view.window.windowScene) [self pauseCapture]; }
- (void)pauseCapture {
    self.wantsCapture = NO;
    self.selectedHex = nil;
    self.saveButton.enabled = NO;
    dispatch_async(self.sessionQueue, ^{ [self.session stopRunning]; });
}
- (void)resumeCapture {
    if (!self.visible || self.view.window.windowScene.activationState != UISceneActivationStateForegroundActive) return;
    AVCaptureDevice *device = [AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];
    TCCameraAccess access = TCCameraAccessForStatus([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo], device != nil);
    if (access == TCCameraAccessUnavailable || access == TCCameraAccessBlocked) {
        self.wantsCapture = NO;
        self.statusLabel.text = access == TCCameraAccessUnavailable ? NSLocalizedString(@"A camera is not available on this device. Choose a photo from the main screen instead.", nil) : NSLocalizedString(@"Camera access is off. Enable it for TouchColor in Settings, or choose a photo instead.", nil);
        return;
    }
    if (access == TCCameraAccessAsk) {
        __weak typeof(self) weakSelf = self;
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {
            dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf resumeCapture]; });
        }];
        return;
    }
    self.wantsCapture = YES;
    self.statusLabel.text = NSLocalizedString(@"Waiting for camera", nil);
    __weak typeof(self) weakSelf = self;
    dispatch_async(self.sessionQueue, ^{
        typeof(self) self = weakSelf;
        if (!self || !self.wantsCapture) return;
        if (!self.session) {
            AVCaptureSession *session = [AVCaptureSession new];
            [session beginConfiguration];
            if ([session canSetSessionPreset:AVCaptureSessionPreset640x480]) session.sessionPreset = AVCaptureSessionPreset640x480;
            NSError *error;
            AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&error];
            AVCaptureVideoDataOutput *output = [AVCaptureVideoDataOutput new];
            output.videoSettings = @{(NSString *)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA)};
            output.alwaysDiscardsLateVideoFrames = YES;
            if (!input || ![session canAddInput:input] || ![session canAddOutput:output]) {
                [session commitConfiguration];
                dispatch_async(dispatch_get_main_queue(), ^{ [self showCaptureFailure]; });
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
                [self.view setNeedsLayout];
            });
        }
        if (self.wantsCapture && !self.session.running) [self.session startRunning];
    });
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    self.preview.frame = self.cameraView.bounds;
    AVCaptureConnection *connection = self.preview.connection;
    UIInterfaceOrientation orientation = self.view.window.windowScene.interfaceOrientation;
    if (@available(iOS 17.0, *)) {
        CGFloat angle = 90;
        if (orientation == UIInterfaceOrientationLandscapeLeft) angle = 0;
        if (orientation == UIInterfaceOrientationLandscapeRight) angle = 180;
        if (orientation == UIInterfaceOrientationPortraitUpsideDown) angle = 270;
        if ([connection isVideoRotationAngleSupported:angle]) connection.videoRotationAngle = angle;
    } else if (connection.isVideoOrientationSupported) {
        connection.videoOrientation = (AVCaptureVideoOrientation)orientation;
    }
    [CATransaction commit];
}
- (void)showCaptureFailure {
    self.wantsCapture = NO;
    self.selectedHex = nil;
    self.saveButton.enabled = NO;
    self.statusLabel.text = NSLocalizedString(@"The camera could not start. Go back and try again, or choose a photo.", nil);
}
- (void)captureInterrupted:(NSNotification *)notification {
    if (notification.object != self.session) return;
    dispatch_async(dispatch_get_main_queue(), ^{ self.selectedHex = nil; self.saveButton.enabled = NO; self.statusLabel.text = NSLocalizedString(@"Camera interrupted. Waiting to resume.", nil); });
}
- (void)captureEndedInterruption:(NSNotification *)notification {
    if (notification.object == self.session) dispatch_async(dispatch_get_main_queue(), ^{ [self resumeCapture]; });
}
- (void)captureError:(NSNotification *)notification {
    if (notification.object != self.session) return;
    NSError *error = notification.userInfo[AVCaptureSessionErrorKey];
    dispatch_async(dispatch_get_main_queue(), ^{
        if (error.code == AVErrorMediaServicesWereReset) [self resumeCapture]; else [self showCaptureFailure];
    });
}
- (void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer fromConnection:(AVCaptureConnection *)connection {
    if (!self.wantsCapture) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - self.lastSampleTime < 0.1) return;
    self.lastSampleTime = now;
    CVPixelBufferRef buffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (!buffer || CVPixelBufferGetPixelFormatType(buffer) != kCVPixelFormatType_32BGRA || CVPixelBufferLockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) return;
    size_t width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer), stride = CVPixelBufferGetBytesPerRow(buffer);
    uint8_t *bytes = CVPixelBufferGetBaseAddress(buffer);
    NSString *hex;
    // Aspect-fill crop and rotations share the sensor's center; no assumed dimensions/row stride.
    if (bytes && width && height && stride >= width * 4) {
        uint8_t *pixel = bytes + (height / 2) * stride + (width / 2) * 4;
        hex = TCHexColor(pixel[2], pixel[1], pixel[0]);
    }
    CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
    if (!hex) return;
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        typeof(self) self = weakSelf;
        if (!self.wantsCapture || !self.visible) return;
        self.selectedHex = hex;
        self.statusLabel.text = [NSString stringWithFormat:@"%@  •  %@", hex, TCRGBDescription(hex)];
        self.saveButton.enabled = YES;
    });
}
- (void)save {
    TCColorStore *store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    if ([store addColor:self.selectedHex]) UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, NSLocalizedString(@"Color saved", nil));
}
@end
