#import <XCTest/XCTest.h>
#import "TCColorUtilities.h"
#import "TCPrivacyTesting.h"
#import "ColorDetectView.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"
#import <WebKit/WebKit.h>

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
// Method-call spies prove app routing only; they are not packet-level network observations.
@interface TCPolicyWebViewSpy : WKWebView
@property (nonatomic) NSUInteger requestLoads;
@property (nonatomic) NSUInteger HTMLLoads;
@property (nonatomic) NSUInteger stops;
@property (nonatomic, copy) NSString *loadedHTML;
@property (nonatomic, strong) NSURL *loadedBaseURL;
@end
@implementation TCPolicyWebViewSpy
- (WKNavigation *)loadRequest:(NSURLRequest *)request { self.requestLoads++; return nil; }
- (WKNavigation *)loadHTMLString:(NSString *)string baseURL:(NSURL *)baseURL {
    self.HTMLLoads++; self.loadedHTML=string; self.loadedBaseURL=baseURL; return nil;
}
- (void)stopLoading { self.stops++; }
@end
@interface TCPolicyControllerSpy : TCPrivacyViewController
@property (nonatomic) BOOL usesFixtureURL;
@property (nonatomic, strong) NSURL *fixtureURL;
@property (nonatomic, strong) TCPolicyWebViewSpy *spy;
@property (nonatomic, strong) NSMutableArray<NSURL *> *openedURLs;
@end
@implementation TCPolicyControllerSpy
- (WKWebView *)makePolicyWebViewWithConfiguration:(WKWebViewConfiguration *)configuration {
    self.spy=[[TCPolicyWebViewSpy alloc] initWithFrame:CGRectZero configuration:configuration];
    self.openedURLs=[NSMutableArray new]; return self.spy;
}
- (NSURL *)policyResourceURL { return self.usesFixtureURL ? self.fixtureURL : [super policyResourceURL]; }
- (void)openExternalPolicyURL:(NSURL *)URL { [self.openedURLs addObject:URL]; }
@end
@interface TCPolicyFrame : NSObject
@property (nonatomic, getter=isMainFrame) BOOL mainFrame;
@end
@implementation TCPolicyFrame
@end
@interface TCPolicyAction : NSObject
@property (nonatomic, strong) NSURLRequest *request;
@property (nonatomic) WKNavigationType navigationType;
@property (nonatomic, strong) TCPolicyFrame *sourceFrame;
@property (nonatomic, strong) TCPolicyFrame *targetFrame;
@end
@implementation TCPolicyAction
@end
@interface TCPolicyResponse : NSObject
@property (nonatomic, strong) NSURLResponse *response;
@property (nonatomic, getter=isForMainFrame) BOOL forMainFrame;
@end
@implementation TCPolicyResponse
@end
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
- (void)testPrivacyNavigationIsLocalAndPublishedPolicyRequiresExplicitBrowserTap {
    for (NSString *value in @[@"about:blank", @"about:blank#english-title"]) XCTAssertTrue(TCPrivacyAllowsDocumentURL([NSURL URLWithString:value]));
    NSArray *remoteOrMalformed=@[@"https://100mango.github.io/app-privacy/", @"https://100mango.github.io:443/app-privacy/#touchcolor", @"http://100mango.github.io/app-privacy/", @"https://example.com/app-privacy/", @"https://100mango.github.io/other/", @"https://100mango.github.io/app-privacy/?tracking=1", @"https://100mango.github.io/app-privacy/?", @"https://user@100mango.github.io/app-privacy/", @"https://100mango.github.io:8443/app-privacy/", @"file:///app-privacy/", @"javascript:alert(1)", @"about:blank?", @"about:srcdoc", @"about://blank"];
    for (NSString *value in remoteOrMalformed) XCTAssertFalse(TCPrivacyAllowsDocumentURL([NSURL URLWithString:value]), @"%@", value);
    XCTAssertFalse(TCPrivacyAllowsDocumentURL(nil));
    NSURL *published=[NSURL URLWithString:@"https://100mango.github.io/app-privacy/"];
    XCTAssertTrue(TCPrivacyAllowsPublishedURL(published,YES));
    XCTAssertFalse(TCPrivacyAllowsPublishedURL(published,NO));
    XCTAssertFalse(TCPrivacyAllowsPublishedURL(nil,YES));
    for (NSString *value in [remoteOrMalformed subarrayWithRange:NSMakeRange(1,remoteOrMalformed.count-1)]) XCTAssertFalse(TCPrivacyAllowsPublishedURL([NSURL URLWithString:value],YES), @"%@", value);
    TCPolicyControllerSpy *controller=[TCPolicyControllerSpy new]; [controller loadViewIfNeeded];
    TCPolicyAction *action=[TCPolicyAction new]; action.sourceFrame=[TCPolicyFrame new];action.sourceFrame.mainFrame=YES;
    action.targetFrame=[TCPolicyFrame new];action.targetFrame.mainFrame=YES;
    for (NSString *value in @[@"https://100mango.github.io/app-privacy/", @"mailto:100mango@gmail.com", @"https://example.com/", @"about:blank#english-title"]) {
        action.request=[NSURLRequest requestWithURL:[NSURL URLWithString:value]];
        for (NSNumber *navigationType in @[@(WKNavigationTypeOther),@(WKNavigationTypeLinkActivated)]) {
            action.navigationType=navigationType.integerValue;
            NSUInteger before=controller.openedURLs.count;
            __block NSUInteger decisions=0;
            [controller webView:controller.spy decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:^(WKNavigationActionPolicy policy) {
                decisions++; XCTAssertEqual(policy,[value hasPrefix:@"about:"] ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
            }];
            XCTAssertEqual(decisions,1u);
            BOOL explicitAllowed=action.navigationType==WKNavigationTypeLinkActivated && (TCPrivacyAllowsPublishedURL(action.request.URL,YES) || TCPrivacyAllowsContactURL(action.request.URL,YES));
            XCTAssertEqual(controller.openedURLs.count,before+(explicitAllowed ? 1 : 0));
            if (explicitAllowed) XCTAssertEqualObjects(controller.openedURLs.lastObject,action.request.URL);
        }
    }
    action.request=[NSURLRequest requestWithURL:published]; action.navigationType=WKNavigationTypeLinkActivated;
    action.sourceFrame.mainFrame=NO; NSUInteger before=controller.openedURLs.count;
    [controller webView:controller.spy decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:^(WKNavigationActionPolicy policy) { XCTAssertEqual(policy,WKNavigationActionPolicyCancel); }];
    XCTAssertEqual(controller.openedURLs.count,before);
    action.sourceFrame.mainFrame=YES; [controller close];
    [controller webView:controller.spy decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:^(WKNavigationActionPolicy policy) { XCTAssertEqual(policy,WKNavigationActionPolicyCancel); }];
    XCTAssertEqual(controller.openedURLs.count,before);
    XCTAssertEqual(controller.spy.requestLoads,0u);
}
- (void)testPrivacyMailRequiresExplicitApprovedContactTap {
    NSURL *contact=[NSURL URLWithString:@"mailto:100mango@gmail.com"];
    XCTAssertTrue(TCPrivacyAllowsContactURL(contact,YES));
    XCTAssertFalse(TCPrivacyAllowsContactURL(contact,NO));
    for (NSString *value in @[@"mailto:other@example.com", @"mailto:100mango@gmail.com?body=private", @"mailto:100mango@gmail.com?", @"mailto:100mango@gmail.com#", @"mailto://100mango@gmail.com", @"mailto:100mango@gmail.com#fragment", @"https://100mango.github.io/app-privacy/"]) XCTAssertFalse(TCPrivacyAllowsContactURL([NSURL URLWithString:value],YES));
    XCTAssertFalse(TCPrivacyAllowsContactURL(nil,YES));
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
- (void)testPolicyLocalResourceFailuresAndWebProcessTerminationExposeReload {
    NSURL *resource=[NSBundle.mainBundle URLForResource:@"PrivacyPolicy" withExtension:@"html"];
    XCTAssertNotNil(resource,@"The actual host app must bundle the reviewed policy");
    NSData *approved=[NSData dataWithContentsOfURL:resource];
    NSString *HTML=TCPrivacyPolicyHTML(approved);
    for (NSString *caption in @[@"开发者邮箱：100mango@gmail.com", @"Developer email: 100mango@gmail.com"]) {
        XCTAssertTrue([HTML containsString:caption],@"Visible contact text preserves the complete selectable address and explains its purpose");
        NSString *accessibleNameAttribute=[NSString stringWithFormat:@"aria-label=\"%@\"",caption];
        XCTAssertTrue([HTML containsString:accessibleNameAttribute],@"The localized link name must match its readable visible text");
    }
    XCTAssertTrue([HTML containsString:@"href=\"mailto:100mango@gmail.com\""],@"The exact original contact destination remains unchanged");
    XCTAssertNotNil(HTML);
    if (!HTML) return; // The assertion above fails safely if packaging is broken.
    XCTAssertTrue([HTML containsString:@"开发者不收集或上传这些数据"]);
    XCTAssertTrue([HTML containsString:@"The developer does not collect or upload this data."]);
    XCTAssertNil(TCPrivacyPolicyHTML(nil));
    XCTAssertNil(TCPrivacyPolicyHTML([@"<html>malformed policy</html>" dataUsingEncoding:NSUTF8StringEncoding]));
    NSMutableData *changed=[approved mutableCopy];
    ((unsigned char *)changed.mutableBytes)[0]^=1;
    XCTAssertNil(TCPrivacyPolicyHTML(changed));
    NSURLResponse *local=[[NSURLResponse alloc] initWithURL:[NSURL URLWithString:@"about:blank"] MIMEType:@"text/html" expectedContentLength:approved.length textEncodingName:@"utf-8"];
    XCTAssertTrue(TCPrivacyAllowsResponse(local));
    XCTAssertFalse(TCPrivacyAllowsResponse(nil));
    for (NSNumber *status in @[@200,@404,@500]) {
        NSURLResponse *response=[[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:@"https://100mango.github.io/app-privacy/"] statusCode:status.integerValue HTTPVersion:@"HTTP/1.1" headerFields:@{}];
        XCTAssertFalse(TCPrivacyAllowsResponse(response),@"All remote HTTP responses are now rejected, including 200");
    }
    NSURLResponse *foreign=[[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:@"https://example.com/"] statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:@{}];
    XCTAssertFalse(TCPrivacyAllowsResponse(foreign));
    XCTAssertFalse(TCPrivacyAllowsResponse([[NSURLResponse alloc] initWithURL:[NSURL URLWithString:@"about:blank"] MIMEType:@"image/png" expectedContentLength:1 textEncodingName:nil]));
    TCPolicyControllerSpy *controller=[TCPolicyControllerSpy new];[controller loadViewIfNeeded];
    XCTAssertEqualObjects(controller.spy.loadedHTML,HTML);
    XCTAssertNil(controller.spy.loadedBaseURL);
    XCTAssertEqual(controller.spy.HTMLLoads,1u);
    XCTAssertFalse(controller.spy.configuration.defaultWebpagePreferences.allowsContentJavaScript);
    XCTAssertFalse(controller.spy.allowsLinkPreview);
    XCTAssertFalse(controller.spy.configuration.websiteDataStore.persistent);
    XCTAssertTrue([[controller valueForKey:@"errorScroll"] isHidden]);
    [controller webView:nil didFailNavigation:nil withError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCancelled userInfo:nil]];
    XCTAssertTrue([[controller valueForKey:@"errorScroll"] isHidden]);
    [controller webViewWebContentProcessDidTerminate:nil];
    XCTAssertFalse([[controller valueForKey:@"errorScroll"] isHidden]);
    [controller loadPolicy];
    XCTAssertTrue([[controller valueForKey:@"errorScroll"] isHidden]);
    XCTAssertEqual(controller.spy.HTMLLoads,2u);
    TCPolicyResponse *response=[TCPolicyResponse new];response.response=local;response.forMainFrame=YES;
    [controller webView:controller.spy decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:^(WKNavigationResponsePolicy policy) { XCTAssertEqual(policy,WKNavigationResponsePolicyAllow); }];
    response.response=foreign;
    [controller webView:controller.spy decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:^(WKNavigationResponsePolicy policy) { XCTAssertEqual(policy,WKNavigationResponsePolicyCancel); }];
    XCTAssertFalse([[controller valueForKey:@"errorScroll"] isHidden]);
    NSURL *fixture=[NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString]];
    @try {
        controller.usesFixtureURL=YES;controller.fixtureURL=fixture;
        [controller loadPolicy]; // Missing local resource.
        XCTAssertFalse([[controller valueForKey:@"errorScroll"] isHidden]);
        XCTAssertEqual(controller.spy.HTMLLoads,2u);
        XCTAssertTrue([changed writeToURL:fixture atomically:YES]);
        [controller loadPolicy]; // Same-size tampered local resource.
        XCTAssertFalse([[controller valueForKey:@"errorScroll"] isHidden]);
        XCTAssertEqual(controller.spy.HTMLLoads,2u);
        XCTAssertTrue([[@"<html>broken</html>" dataUsingEncoding:NSUTF8StringEncoding] writeToURL:fixture atomically:YES]);
        [controller loadPolicy]; // Malformed local resource.
        XCTAssertFalse([[controller valueForKey:@"errorScroll"] isHidden]);
        XCTAssertEqual(controller.spy.HTMLLoads,2u);
        controller.usesFixtureURL=NO; [controller loadPolicy];
        XCTAssertTrue([[controller valueForKey:@"errorScroll"] isHidden]);
        XCTAssertEqual(controller.spy.HTMLLoads,3u);
        XCTAssertEqualObjects(controller.spy.loadedHTML,HTML);
        [controller close]; [controller loadPolicy];
        XCTAssertEqual(controller.spy.stops,1u);
        XCTAssertEqual(controller.spy.HTMLLoads,3u,@"Reload after Close must do nothing");
        [controller webViewWebContentProcessDidTerminate:nil];
        XCTAssertTrue([[controller valueForKey:@"errorScroll"] isHidden],@"Late failure after Close must be ignored");
        XCTAssertEqual(controller.spy.requestLoads,0u,@"Method spy: no app-authored remote load, not packet capture");
        XCTAssertEqual(controller.openedURLs.count,0u);
    } @finally { [NSFileManager.defaultManager removeItemAtURL:fixture error:nil]; }
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
