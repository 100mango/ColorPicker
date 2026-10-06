#import <XCTest/XCTest.h>
#import "TCColorUtilities.h"
#import "TCPrivacyTesting.h"
#import "ColorDetectView.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"

@interface ColorRealTimeViewController (LifecycleTests)
- (void)captureInterrupted:(NSNotification *)notification;
- (void)pauseCapture;
- (void)displaySample:(NSString *)hex generation:(NSUInteger)generation;
@end
@interface TCGeometryDelegate : NSObject <ColorDetectViewDelegate>
@property (nonatomic, copy) NSString *hex;
@end
@implementation TCGeometryDelegate
- (UIView *)viewForZoomingInScrollView:(UIScrollView *)scrollView { return [(ColorDetectView *)scrollView imageView]; }
- (void)handelColor:(NSString *)hex { self.hex=hex; }
@end
// Records the real native button route without opening another application.
@interface TCPolicyControllerSpy : TCPrivacyViewController
@property (nonatomic, strong) NSMutableArray<NSURL *> *openedURLs;
@property (nonatomic, copy) void (^pendingCompletion)(BOOL);
@end
@implementation TCPolicyControllerSpy
- (void)openExternalURL:(NSURL *)URL completion:(void (^)(BOOL))completion {
    if (!self.openedURLs) self.openedURLs=[NSMutableArray new];
    [self.openedURLs addObject:URL]; self.pendingCompletion=completion;
}
@end
static UIView *TCPolicyFindView(UIView *root, NSString *identifier) {
    if ([root.accessibilityIdentifier isEqualToString:identifier]) return root;
    for (UIView *child in root.subviews) {
        UIView *found=TCPolicyFindView(child,identifier); if (found) return found;
    }
    return nil;
}
@interface ColorPickerTests : XCTestCase
@property (nonatomic, copy) NSString *suite;
@property (nonatomic, strong) NSUserDefaults *defaults;
@property (nonatomic, strong) TCColorStore *store;
@end
@implementation ColorPickerTests
- (void)setUp {
    [super setUp];
    self.suite = [@"TouchColorTests." stringByAppendingString:NSUUID.UUID.UUIDString];
    self.defaults = [[NSUserDefaults alloc] initWithSuiteName:self.suite];
    self.store = [[TCColorStore alloc] initWithDefaults:self.defaults];
}
- (void)tearDown {
    [self.defaults removePersistentDomainForName:self.suite];
    [super tearDown];
}
- (void)testRGBHexRoundTripAndValidation {
    XCTAssertEqualObjects(TCHexColor(0, 128, 255), @"#0080ff");
    XCTAssertEqualObjects(TCNormalizeHexColor(@"#Ab09EF"), @"#ab09ef");
    for (id invalid in @[@"", @"#fff", @"#12345678", @"#abcdef ", @"abcdefg", @"#gg0000", @123, NSNull.null]) XCTAssertNil(TCNormalizeHexColor(invalid));
    XCTAssertNil(TCNormalizeHexColor(nil));
    CGFloat r=0,g=0,b=0,a=0;
    XCTAssertTrue([TCUIColorFromHex(@"#0080ff") getRed:&r green:&g blue:&b alpha:&a]);
    XCTAssertEqualWithAccuracy(r,0,0.001); XCTAssertEqualWithAccuracy(g,128/255.0,0.001); XCTAssertEqualWithAccuracy(b,1,0.001); XCTAssertEqual(a,1);
    XCTAssertEqualObjects(TCRGBDescription(@"#0080ff"), @"R 0   G 128   B 255");
    XCTAssertEqualObjects(TCRGBDescription(@"bad"), @"");
}
- (void)testFreshHistoryFirstSaveDuplicatesAndOrder {
    XCTAssertEqual(self.store.colors.count,0);
    XCTAssertFalse([self.store addColor:nil]);
    XCTAssertFalse([self.store addColor:@"wrong"]);
    XCTAssertNil([self.defaults objectForKey:@"colorArray"]);
    XCTAssertTrue([self.store addColor:@"#ff0000"]);
    XCTAssertTrue([self.store addColor:@"#00ff00"]);
    XCTAssertTrue([self.store addColor:@"#ff0000"]);
    XCTAssertEqualObjects(self.store.colors, (@[@"#ff0000",@"#00ff00",@"#ff0000"]));
    TCColorStore *reopened=[[TCColorStore alloc] initWithDefaults:[[NSUserDefaults alloc] initWithSuiteName:self.suite]];
    XCTAssertEqualObjects(reopened.colors,self.store.colors);
    XCTAssertFalse([self.store removeColorAtIndex:3]);
    XCTAssertTrue([self.store removeColorAtIndex:1]);
    XCTAssertEqualObjects(self.store.colors, (@[@"#ff0000",@"#ff0000"]));
}
- (void)testLegacyV1HistoryStaysInOriginalKeyWithoutMigration {
    NSArray *legacy=@[@"#101010",@"#abcdef",@"#000000"];
    [self.defaults setObject:legacy forKey:@"colorArray"];
    XCTAssertEqualObjects(self.store.colors,legacy);
    XCTAssertNil([self.defaults objectForKey:@"colorArrayRecoveryBackup"]);
    [self.store addColor:@"#ffffff"];
    XCTAssertEqualObjects([self.defaults arrayForKey:@"colorArray"],(@[@"#101010",@"#abcdef",@"#000000",@"#ffffff"]));
    XCTAssertNil([self.defaults objectForKey:@"colorArrayRecoveryBackup"]);
}
- (void)testMalformedHistoryIsReadSafelyAndBackedUpBeforeRepair {
    NSArray *raw=@[@"#FF0000",@27,@"broken",@"#123456"];
    [self.defaults setObject:raw forKey:@"colorArray"];
    XCTAssertEqualObjects(self.store.colors,(@[@"#ff0000",@"#123456"]));
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArray"],raw);
    [self.store addColor:@"#ffffff"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],raw);
    XCTAssertEqualObjects(self.store.colors,(@[@"#ff0000",@"#123456",@"#ffffff"]));
    [self.store addColor:@"#000000"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],raw);
}
- (void)testWrongTopLevelHistoryAndEmptyHistory {
    [self.defaults setObject:@"not an array" forKey:@"colorArray"];
    XCTAssertEqual(self.store.colors.count,0);
    XCTAssertFalse([self.store removeColorAtIndex:0]);
    [self.store addColor:@"#010203"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],@"not an array");
    [self.defaults setObject:@[] forKey:@"colorArray"];
    XCTAssertEqual(self.store.colors.count,0);
}
- (void)testLetterboxAndInvalidCoordinateRejection {
    CGPoint normalized;
    CGRect image=CGRectMake(20,40,200,100);
    XCTAssertTrue(TCNormalizedPoint(CGPointMake(120,90),image,&normalized));
    XCTAssertEqualWithAccuracy(normalized.x,0.5,0.00001); XCTAssertEqualWithAccuracy(normalized.y,0.5,0.00001);
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(19,90),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(120,39),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(220,140),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(NAN,0),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointZero,CGRectZero,NULL));
    XCTAssertNil(TCSampleImage(nil,CGPointZero));
    XCTAssertNil(TCSampleImage([UIImage new],CGPointZero));
}
- (UIImage *)fixtureWithOrientation:(UIImageOrientation)orientation scale:(CGFloat)scale {
    const uint8_t bytes[]={255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255, 255,0,255,255, 0,255,255,255};
    NSData *data=[NSData dataWithBytes:bytes length:sizeof(bytes)];
    CGDataProviderRef provider=CGDataProviderCreateWithCFData((__bridge CFDataRef)data);
    CGColorSpaceRef space=CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGImageRef cg=CGImageCreate(3,2,8,32,12,space,(CGBitmapInfo)kCGImageAlphaPremultipliedLast|kCGBitmapByteOrder32Big,provider,NULL,NO,kCGRenderingIntentDefault);
    UIImage *image=[UIImage imageWithCGImage:cg scale:scale orientation:orientation];
    CGImageRelease(cg); CGColorSpaceRelease(space); CGDataProviderRelease(provider);
    return image;
}
- (void)testAllEightOrientationsAndScaleWithAsymmetricPixelFixture {
    // Original 3x2 rows: red, green, blue / yellow, magenta, cyan.
    NSArray *orientations=@[@(UIImageOrientationUp),@(UIImageOrientationDown),@(UIImageOrientationLeft),@(UIImageOrientationRight),@(UIImageOrientationUpMirrored),@(UIImageOrientationDownMirrored),@(UIImageOrientationLeftMirrored),@(UIImageOrientationRightMirrored)];
    NSArray *corners=@[@[@"#ff0000",@"#0000ff",@"#ffff00",@"#00ffff"],@[@"#00ffff",@"#ffff00",@"#0000ff",@"#ff0000"],@[@"#0000ff",@"#00ffff",@"#ff0000",@"#ffff00"],@[@"#ffff00",@"#ff0000",@"#00ffff",@"#0000ff"],@[@"#0000ff",@"#ff0000",@"#00ffff",@"#ffff00"],@[@"#ffff00",@"#00ffff",@"#ff0000",@"#0000ff"],@[@"#ff0000",@"#ffff00",@"#0000ff",@"#00ffff"],@[@"#00ffff",@"#0000ff",@"#ffff00",@"#ff0000"]];
    CGPoint points[]={CGPointMake(0.1,0.1),CGPointMake(0.9,0.1),CGPointMake(0.1,0.9),CGPointMake(0.9,0.9)};
    for (NSUInteger i=0;i<orientations.count;i++) {
        for (NSNumber *scale in @[@1,@2,@3]) {
            UIImage *image=[self fixtureWithOrientation:[orientations[i] integerValue] scale:scale.doubleValue];
            for (NSUInteger j=0;j<4;j++) XCTAssertEqualObjects(TCSampleImage(image,points[j]),corners[i][j],@"orientation %@ scale %@ corner %lu",orientations[i],scale,(unsigned long)j);
        }
    }
    UIImage *image=[self fixtureWithOrientation:UIImageOrientationUp scale:1];
    XCTAssertEqualObjects(TCSampleImage(image,CGPointMake(1,1)),@"#00ffff");
    XCTAssertNil(TCSampleImage(image,CGPointMake(-0.1,0)));
    XCTAssertNil(TCSampleImage(image,CGPointMake(INFINITY,0)));
    XCTAssertNil(TCSampleImage(image,CGPointMake(0,1.01)));
}
- (void)testTransparentPixelsCompositeOnWhite {
    UIGraphicsImageRendererFormat *format=UIGraphicsImageRendererFormat.defaultFormat;
    format.scale=1; format.opaque=NO; format.preferredRange=UIGraphicsImageRendererFormatRangeStandard;
    UIImage *transparent=[[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {}];
    XCTAssertEqualObjects(TCSampleImage(transparent,CGPointMake(0.5,0.5)),@"#ffffff");
}
- (void)testCameraBGRACenterUsesPaddedRowStride {
    uint8_t bytes[96] = {0};
    // 3x3 pixels with 32-byte rows: the center is row1/pixel1, not tightly packed offset16.
    bytes[36] = 20; bytes[37] = 80; bytes[38] = 200; bytes[39] = 255;
    CVPixelBufferRef buffer = NULL;
    XCTAssertEqual(CVPixelBufferCreateWithBytes(kCFAllocatorDefault,3,3,kCVPixelFormatType_32BGRA,bytes,32,NULL,NULL,NULL,&buffer),kCVReturnSuccess);
    XCTAssertEqualObjects(TCSampleCameraBuffer(buffer),@"#c85014");
    CVPixelBufferRelease(buffer);
    XCTAssertNil(TCSampleCameraBuffer(NULL));
    CVPixelBufferRef unsupported = NULL;
    XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault,2,2,kCVPixelFormatType_32ARGB,NULL,&unsupported),kCVReturnSuccess);
    XCTAssertNil(TCSampleCameraBuffer(unsupported));
    CVPixelBufferRelease(unsupported);
}
- (void)testCameraPermissionDecisionsNeverRequireRealHardware {
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusNotDetermined,YES),TCCameraAccessAsk);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusAuthorized,YES),TCCameraAccessReady);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusDenied,YES),TCCameraAccessBlocked);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusRestricted,YES),TCCameraAccessBlocked);
    for (NSNumber *status in @[@(AVAuthorizationStatusNotDetermined),@(AVAuthorizationStatusAuthorized),@(AVAuthorizationStatusDenied),@(AVAuthorizationStatusRestricted)]) XCTAssertEqual(TCCameraAccessForStatus(status.integerValue,NO),TCCameraAccessUnavailable);
}
- (void)testNativePrivacyExplicitBrowserActionAndCloseRejectLateCompletion {
    TCPolicyControllerSpy *controller=[TCPolicyControllerSpy new];[controller loadViewIfNeeded];
    UIButton *browser=(UIButton *)TCPolicyFindView(controller.view,@"privacy.externalPolicy");
    UIButton *contact=(UIButton *)TCPolicyFindView(controller.view,@"privacy.contact");
    UILabel *error=(UILabel *)TCPolicyFindView(controller.view,@"privacy.externalError");
    XCTAssertNotNil(browser);XCTAssertNotNil(contact);XCTAssertTrue(error.hidden);
    XCTAssertEqual(controller.openedURLs.count,0u,@"Loading native policy never opens a service");
    XCTAssertTrue([browser.allTargets containsObject:controller]);
    XCTAssertTrue([[browser actionsForTarget:controller forControlEvent:UIControlEventTouchUpInside] containsObject:NSStringFromSelector(@selector(openPolicyInBrowser))]);
    [browser sendActionsForControlEvents:UIControlEventTouchUpInside];
    XCTAssertEqual(controller.openedURLs.count,1u);
    XCTAssertEqualObjects(controller.openedURLs.lastObject.absoluteString,@"https://100mango.github.io/app-privacy/");
    XCTAssertFalse(browser.enabled);XCTAssertFalse(contact.enabled);
    [controller openPolicyInBrowser];[controller contactDeveloper];
    XCTAssertEqual(controller.openedURLs.count,1u,@"A pending opener admits no second action");
    [controller close];[controller close];
    void (^completion)(BOOL)=controller.pendingCompletion;
    XCTAssertNotNil(completion);if (completion) completion(NO);
    XCTestExpectation *drained=[self expectationWithDescription:@"Public opener completion returned to the main queue"];
    dispatch_async(dispatch_get_main_queue(), ^{ [drained fulfill]; });
    [self waitForExpectationsWithTimeout:5 handler:nil];
    XCTAssertTrue(error.hidden,@"A late failure must not revive a closed policy");
    XCTAssertFalse(browser.enabled);XCTAssertFalse(contact.enabled);
    [controller openPolicyInBrowser];[controller contactDeveloper];
    XCTAssertEqual(controller.openedURLs.count,1u);
}
- (void)testNativePrivacyContactFailureAndSuccessPreserveTheOfflineBody {
    TCPolicyControllerSpy *controller=[TCPolicyControllerSpy new];[controller loadViewIfNeeded];
    UIButton *contact=(UIButton *)TCPolicyFindView(controller.view,@"privacy.contact");
    UIButton *browser=(UIButton *)TCPolicyFindView(controller.view,@"privacy.externalPolicy");
    UILabel *error=(UILabel *)TCPolicyFindView(controller.view,@"privacy.externalError");
    UITextView *body=(UITextView *)TCPolicyFindView(controller.view,@"privacy.body.en");
    NSString *original=[body.text copy];
    XCTAssertEqual(controller.openedURLs.count,0u);
    XCTAssertTrue([contact.allTargets containsObject:controller]);
    XCTAssertTrue([[contact actionsForTarget:controller forControlEvent:UIControlEventTouchUpInside] containsObject:NSStringFromSelector(@selector(contactDeveloper))]);
    [contact sendActionsForControlEvents:UIControlEventTouchUpInside];
    XCTAssertEqual(controller.openedURLs.count,1u);
    XCTAssertEqualObjects(controller.openedURLs.lastObject.absoluteString,@"mailto:100mango@gmail.com");
    XCTAssertFalse(contact.enabled);XCTAssertFalse(browser.enabled);
    void (^failure)(BOOL)=controller.pendingCompletion;
    XCTAssertNotNil(failure);if (failure) failure(NO);
    XCTestExpectation *failed=[self expectationWithDescription:@"Known Mail failure observed on the main queue"];
    dispatch_async(dispatch_get_main_queue(), ^{ [failed fulfill]; });
    [self waitForExpectationsWithTimeout:5 handler:nil];
    XCTAssertFalse(error.hidden);XCTAssertGreaterThan(error.text.length,0u);
    XCTAssertTrue(contact.enabled);XCTAssertTrue(browser.enabled);
    XCTAssertEqualObjects(body.text,original);
    [contact sendActionsForControlEvents:UIControlEventTouchUpInside];
    XCTAssertEqual(controller.openedURLs.count,2u);
    XCTAssertEqualObjects(controller.openedURLs.lastObject.absoluteString,@"mailto:100mango@gmail.com");
    void (^success)(BOOL)=controller.pendingCompletion;
    XCTAssertNotNil(success);if (success) success(YES);
    XCTestExpectation *opened=[self expectationWithDescription:@"Known Mail open result observed on the main queue"];
    dispatch_async(dispatch_get_main_queue(), ^{ [opened fulfill]; });
    [self waitForExpectationsWithTimeout:5 handler:nil];
    XCTAssertTrue(error.hidden);XCTAssertTrue(contact.enabled);XCTAssertTrue(browser.enabled);
    XCTAssertEqualObjects(body.text,original);[controller close];
}
- (void)testQueuedFramesCannotSurviveInterruptionPauseOrRestart {
    TCCaptureGate *gate=[TCCaptureGate new];
    NSUInteger before=[gate beginCapture];
    XCTAssertTrue([gate acceptHex:@"#ff0000" generation:before]);
    BOOL (^queuedBeforeInterruption)(void)=^{ return [gate acceptHex:@"#00ff00" generation:before]; };
    [gate invalidate];
    XCTAssertFalse(queuedBeforeInterruption());
    XCTAssertNil(gate.selectedHex);
    NSUInteger resumed=[gate beginCapture];
    XCTAssertFalse(queuedBeforeInterruption());
    XCTAssertTrue([gate acceptHex:@"#0000ff" generation:resumed]);
    [gate invalidate]; // Background/disappearance also clears the last savable value.
    XCTAssertFalse([gate acceptHex:@"#ff0000" generation:resumed]);
    XCTAssertNil(gate.selectedHex);
    NSUInteger pending=gate.generation;
    [gate invalidate]; // Interruption races with a queued session-start request.
    XCTAssertEqual([gate beginCaptureAfterGeneration:pending],0);
    XCTAssertFalse([gate acceptsGeneration:pending]);
}
- (void)testRealInterruptionHandlerInvalidatesBeforeQueuedMainDelivery {
    ColorRealTimeViewController *controller=[ColorRealTimeViewController new];
    [controller loadViewIfNeeded];
    AVCaptureSession *session=[AVCaptureSession new];
    [controller setValue:session forKey:@"session"];
    [controller setValue:@YES forKey:@"visible"];
    [controller setValue:@YES forKey:@"wantsCapture"];
    TCCaptureGate *gate=[controller valueForKey:@"captureGate"];
    NSUInteger generation=[gate beginCapture];
    [controller displaySample:@"#ff0000" generation:generation];
    UIButton *save=[controller valueForKey:@"saveButton"];
    XCTAssertTrue(save.enabled);
    XCTestExpectation *delivery=[self expectationWithDescription:@"old frame delivered after interruption cleanup"];
    [controller captureInterrupted:[NSNotification notificationWithName:AVCaptureSessionWasInterruptedNotification object:session]];
    dispatch_async(dispatch_get_main_queue(), ^{
        [controller displaySample:@"#00ff00" generation:generation];
        XCTAssertNil(gate.selectedHex);XCTAssertFalse(save.enabled);
        [controller setValue:@NO forKey:@"interrupted"];
        [controller setValue:@YES forKey:@"wantsCapture"];
        NSUInteger resumed=[gate beginCapture];
        [controller displaySample:@"#00ff00" generation:generation];
        XCTAssertNil(gate.selectedHex);XCTAssertFalse(save.enabled);
        [controller displaySample:@"#0000ff" generation:resumed];
        XCTAssertEqualObjects(gate.selectedHex,@"#0000ff");XCTAssertTrue(save.enabled);
        [controller pauseCapture];
        [controller displaySample:@"#ff0000" generation:resumed];
        XCTAssertNil(gate.selectedHex);XCTAssertFalse(save.enabled);
        [delivery fulfill];
    });
    [self waitForExpectations:@[delivery] timeout:2];
}
- (void)testMarkerAndPixelStayTogetherThroughCenterResizeZoomAndPan {
    TCGeometryDelegate *delegate=[TCGeometryDelegate new];
    ColorDetectView *view=[[ColorDetectView alloc] initWithFrame:CGRectMake(0,0,300,500) andUIImage:[self fixtureWithOrientation:UIImageOrientationUp scale:1]];
    view.delegate=delegate;
    [view layoutIfNeeded];
    XCTAssertTrue([view sampleAtImagePoint:CGPointMake(25,25)]);
    XCTAssertEqualObjects(delegate.hex,@"#ff0000");
    XCTAssertTrue([view sampleVisibleCenter]);
    XCTAssertEqualObjects(delegate.hex,@"#ff00ff");
    CGPoint normalized=view.selectedNormalizedPoint;
    UIImageView *marker=[view valueForKey:@"marker"];
    for (NSValue *size in @[[NSValue valueWithCGSize:CGSizeMake(500,200)],[NSValue valueWithCGSize:CGSizeMake(250,400)]]) {
        view.frame=(CGRect){CGPointZero,size.CGSizeValue};
        [view setNeedsLayout];[view layoutIfNeeded];
        CGPoint point=[view convertPoint:marker.center toView:view.imageView];
        XCTAssertEqualWithAccuracy(point.x/view.imageView.bounds.size.width,normalized.x,0.0001);
        XCTAssertEqualWithAccuracy(point.y/view.imageView.bounds.size.height,normalized.y,0.0001);
        XCTAssertEqualObjects(TCSampleImage(view.imageView.image,normalized),delegate.hex);
    }
    NSString *before=delegate.hex;
    XCTAssertFalse([view sampleAtImagePoint:CGPointMake(-1,-1)]); // A letterbox tap cannot move the selection.
    XCTAssertEqualObjects(delegate.hex,before);
    [view setZoomScale:3 animated:NO];[view layoutIfNeeded];
    [view setContentOffset:CGPointMake(60,40) animated:NO];[view layoutIfNeeded];
    CGPoint center=[view convertPoint:CGPointMake(CGRectGetMidX(view.bounds),CGRectGetMidY(view.bounds)) toView:view.imageView];
    CGPoint expected;
    XCTAssertTrue(TCNormalizedPoint(center,view.imageView.bounds,&expected));
    XCTAssertTrue([view sampleVisibleCenter]);
    XCTAssertEqualObjects(delegate.hex,TCSampleImage(view.imageView.image,expected));
    CGPoint markerPoint=[view convertPoint:marker.center toView:view.imageView];
    XCTAssertEqualWithAccuracy(markerPoint.x,center.x,0.001);
    XCTAssertEqualWithAccuracy(markerPoint.y,center.y,0.001);
}
- (void)testRecoveryBackupSurvivesDeleteAndRelaunch {
    NSArray *original=@[@"#ff0000",@"broken",@"#00ff00"];
    [self.defaults setObject:original forKey:@"colorArray"];
    XCTAssertTrue([self.store removeColorAtIndex:0]);
    TCColorStore *reopened=[[TCColorStore alloc] initWithDefaults:[[NSUserDefaults alloc] initWithSuiteName:self.suite]];
    XCTAssertEqualObjects(reopened.colors,(@[@"#00ff00"]));
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],original);
    XCTAssertTrue([reopened removeColorAtIndex:0]);
    XCTAssertEqual(reopened.colors.count,0);
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],original);
}
- (void)testNativePrivacyApprovedBilingualBodyRemainsSelectableAndCopyable {
    TCPolicyControllerSpy *controller=[TCPolicyControllerSpy new];[controller loadViewIfNeeded];
    NSArray<NSString *> *identifiers=@[@"privacy.body.zh-Hans",@"privacy.body.en"];
    NSArray<NSString *> *approved=@[@"Celluloid、QRCatcher 和 TouchColor 在设备本地处理照片、相机画面、二维码或颜色数据，开发者不收集或上传这些数据。用户主动分享、打开链接，以及系统 iCloud 同步等行为由相应服务处理。如有隐私问题，请联系 100mango@gmail.com。本地数据可通过相应应用或系统删除，权限可在系统设置中撤回。",@"Celluloid, QRCatcher, and TouchColor process photos, camera images, QR codes, or color data locally on your device. The developer does not collect or upload this data. Actions you choose to take, such as sharing or opening links, and system services such as iCloud sync are handled by the respective services. For privacy questions, contact 100mango@gmail.com. Local data can be deleted through the relevant app or system, and permissions can be revoked in system settings."];
    NSArray *savedClipboard=UIPasteboard.generalPasteboard.items;
    @try {
        for (NSUInteger index=0;index<identifiers.count;index++) {
            UITextView *body=(UITextView *)TCPolicyFindView(controller.view,identifiers[index]);
            XCTAssertTrue([body isKindOfClass:UITextView.class]);
            XCTAssertEqualObjects(body.text,approved[index]);
            XCTAssertFalse(body.editable);XCTAssertTrue(body.selectable);XCTAssertFalse(body.scrollEnabled);
            XCTAssertEqual(body.dataDetectorTypes,UIDataDetectorTypeNone);
            XCTAssertTrue(body.adjustsFontForContentSizeCategory);
            __block BOOL hasLink=NO;
            [body.attributedText enumerateAttribute:NSLinkAttributeName inRange:NSMakeRange(0,body.attributedText.length) options:0 usingBlock:^(id value, NSRange range, BOOL *stop) { if (value) hasLink=YES; }];
            XCTAssertFalse(hasLink,@"Plain selectable text must not create implicit external actions");
            NSRange address=[body.text rangeOfString:@"100mango@gmail.com"];
            XCTAssertNotEqual(address.location,NSNotFound);if (address.location==NSNotFound) continue;
            body.selectedRange=address;
            UIPasteboard.generalPasteboard.string=@"privacy-copy-sentinel";
            [body copy:nil];
            XCTAssertEqualObjects(UIPasteboard.generalPasteboard.string,@"100mango@gmail.com");
            [controller.view setNeedsLayout];[controller.view layoutIfNeeded];
            XCTAssertTrue(NSEqualRanges(body.selectedRange,address));
            XCTAssertEqualObjects(body.text,approved[index]);
        }
    } @finally { UIPasteboard.generalPasteboard.items=savedClipboard; }
    for (NSString *identifier in @[@"privacy.notice.en",@"privacy.notice.zh-Hans"]) {
        UILabel *notice=(UILabel *)TCPolicyFindView(controller.view,identifier);
        XCTAssertTrue([notice.text containsString:@"GitHub Pages"]);
        XCTAssertTrue([notice.text containsString:@"IP"]);
        XCTAssertEqual([notice contentCompressionResistancePriorityForAxis:UILayoutConstraintAxisVertical],UILayoutPriorityRequired);
    }
    XCTAssertEqual(controller.openedURLs.count,0u);
    XCTAssertEqualObjects(controller.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"privacy.close");
    [controller close];
}
- (void)testTransparentPhotoAppearanceMatchesSampledWhiteMatteInLightAndDark {
    UIGraphicsImageRendererFormat *format=[UIGraphicsImageRendererFormat defaultFormat];
    format.scale=1;format.opaque=NO;format.preferredRange=UIGraphicsImageRendererFormatRangeStandard;
    UIImage *transparent=[[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) { CGContextClearRect(context.CGContext,CGRectMake(0,0,3,2)); }];
    for (NSNumber *style in @[@(UIUserInterfaceStyleLight),@(UIUserInterfaceStyleDark)]) {
        ColorDetectView *view=[[ColorDetectView alloc] initWithFrame:CGRectMake(0,0,90,90) andUIImage:transparent];
        view.overrideUserInterfaceStyle=style.integerValue;
        TCGeometryDelegate *delegate=[TCGeometryDelegate new];view.delegate=delegate;
        [view layoutIfNeeded];
        UIImage *visible=[[[UIGraphicsImageRenderer alloc] initWithSize:view.bounds.size format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) { [view.layer renderInContext:context.CGContext]; }];
        NSString *displayed=TCSampleImage(visible,CGPointMake(0.5,0.5));
        XCTAssertEqualObjects(displayed,@"#ffffff");
        XCTAssertTrue([view sampleVisibleCenter]);
        XCTAssertEqualObjects(delegate.hex,displayed,@"Visible transparent pixels and numeric samples must use the same matte");
    }
}
@end
