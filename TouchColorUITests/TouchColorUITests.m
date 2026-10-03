#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#include <stdio.h>
@interface TouchColorUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@end
@implementation TouchColorUITests
- (void)emitScreenshot:(NSString *)name {
    // Log at most two synthetic-fixture JPEGs, from the compact iPhone only.
    if (UIDevice.currentDevice.userInterfaceIdiom != UIUserInterfaceIdiomPhone) return;
    CGSize displaySize=UIScreen.mainScreen.bounds.size;
    if (MIN(displaySize.width,displaySize.height)>400) return;
    NSString *marker=[NSTemporaryDirectory() stringByAppendingPathComponent:[name stringByAppendingString:@".logged"]];
    if ([NSFileManager.defaultManager fileExistsAtPath:marker]) return;
    NSData *data=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
    XCTAssertGreaterThan(data.length,0);
    XCTAssertLessThanOrEqual(data.length,500*1024);
    if (data.length > 500*1024) return;
    [@"logged" writeToFile:marker atomically:YES encoding:NSUTF8StringEncoding error:nil];
    NSString *encoded=[data base64EncodedStringWithOptions:0];
    printf("SCREENSHOT_BEGIN:%s\n",name.UTF8String);
    for (NSUInteger offset=0;offset<encoded.length;offset+=4096) {
        NSString *chunk=[encoded substringWithRange:NSMakeRange(offset,MIN(4096,encoded.length-offset))];
        printf("%s\n",chunk.UTF8String);
    }
    printf("SCREENSHOT_END:%s\n",name.UTF8String);
    fflush(stdout);
}
- (void)setUp {
    [super setUp];
    self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [self.app launch];
}
- (void)revealControl:(XCUIElement *)element inScrollView:(XCUIElement *)scroll {
    for (NSUInteger attempt=0;attempt<5 && (!element.hittable || !CGRectContainsRect(scroll.frame,CGRectInset(element.frame,1,1)));attempt++) {
        if (CGRectGetMinY(element.frame)<CGRectGetMinY(scroll.frame)) [scroll swipeDown]; else [scroll swipeUp];
    }
    XCTAssertTrue(element.hittable,@"%@",self.app.debugDescription);
}
- (void)testPrivacyPolicyEntryOpensAndCloses {
    for (NSUInteger attempt=0; attempt<2; attempt++) {
        XCUIElement *privacy=self.app.buttons[@"privacyPolicy"];
        XCTAssertTrue([privacy waitForExistenceWithTimeout:5]);
        XCTAssertTrue(privacy.hittable);
        [privacy tap];
        XCUIElement *close=self.app.buttons[@"privacy.close"];
        XCTAssertTrue([close waitForExistenceWithTimeout:5],@"%@",self.app.debugDescription);
        XCTAssertTrue(close.hittable);
        if (attempt==0) {
            [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];
            [self.app activate];
            XCTAssertTrue(close.hittable);
        }
        [close tap];
        XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
        XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
    }
}
- (void)testPrivacyOfflineRetryAndClose {
    [self.app terminate];
    self.app.launchArguments=[self.app.launchArguments arrayByAddingObject:@"--ui-test-policy-offline"];
    [self.app launch];
    [self.app.buttons[@"privacyPolicy"] tap];
    XCTAssertTrue([self.app.staticTexts[@"privacy.error"] waitForExistenceWithTimeout:5]);
    XCUIElement *retry=self.app.buttons[@"privacy.retry"];
    XCTAssertTrue(retry.hittable);
    [retry tap];
    XCTAssertFalse(self.app.staticTexts[@"privacy.error"].exists);
    XCTAssertTrue(self.app.webViews[@"privacy.content"].exists);
    XCUIElement *policyText=[self.app.webViews.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'TouchColor'"]].firstMatch;
    XCTAssertTrue([policyText waitForExistenceWithTimeout:30],@"The approved policy body must load after Retry");
    [self.app.buttons[@"privacy.close"] tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
}
- (void)testLaunchAndPhotoPickerCancelRepeatedly {
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10]);
    for (NSUInteger i=0;i<2;i++) {
        [self.app.buttons[@"choosePhoto"] tap];
        XCUIElement *cancel=self.app.buttons[@"Cancel"].firstMatch;
        XCTAssertTrue([cancel waitForExistenceWithTimeout:10],@"%@",self.app.debugDescription);
        [cancel tap];
        XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    }
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0);
}
- (void)respondToRealCameraPromptAllow:(BOOL)allow {
    XCUIApplication *system=[[XCUIApplication alloc] initWithBundleIdentifier:@"com.apple.springboard"];
    XCUIElement *alert=system.alerts.firstMatch;
    XCTAssertTrue([alert waitForExistenceWithTimeout:15],@"Camera prompt missing. App: %@ System: %@",self.app.debugDescription,system.debugDescription);
    BOOL namesApp=[alert.label containsString:@"TouchColor"] || [alert.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'TouchColor'"]].count>0;
    XCTAssertTrue(namesApp,@"Only answer the TouchColor camera dialog: %@",alert.debugDescription);
    XCTAssertTrue(alert.buttons[@"Don’t Allow"].exists || alert.buttons[@"Don't Allow"].exists,@"An app-owned OK alert is not proof of system camera consent: %@",alert.debugDescription);
    XCUIElement *button=alert.buttons[allow ? @"Allow" : @"Don’t Allow"];
    if (!button.exists) button=alert.buttons[allow ? @"OK" : @"Don't Allow"];
    XCTAssertTrue(button.exists,@"%@",alert.debugDescription);
    [button tap];
    XCTNSPredicateExpectation *dismissed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:alert];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[dismissed] timeout:5],XCTWaiterResultCompleted,@"The system dialog must disappear before checking app authorization state");
    NSLog(@"REAL_OS_CAMERA_PROMPT_%@",allow ? @"ALLOW" : @"DENY");
}
- (void)testRealCameraPermissionAllowThenResetAndDeny {
    [self.app terminate];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-camera-permission",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    [self.app resetAuthorizationStatusForResource:XCUIProtectedResourceCamera];
    [self.app launch];[self.app.buttons[@"takePhoto"] tap];
    [self respondToRealCameraPromptAllow:YES];
    XCTAssertTrue([self.app.alerts.staticTexts[@"CAMERA_PERMISSION_ALLOWED"] waitForExistenceWithTimeout:10],@"%@",self.app.debugDescription);
    [self.app.alerts.buttons[@"OK"] tap];
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];[self.app activate];
    [self.app.buttons[@"takePhoto"] tap];
    XCTAssertTrue([self.app.alerts.staticTexts[@"CAMERA_PERMISSION_ALLOWED"] waitForExistenceWithTimeout:5]);
    [self.app.alerts.buttons[@"OK"] tap];
    [self.app terminate];XCTAssertTrue([self.app waitForState:XCUIApplicationStateNotRunning timeout:5]);
    [self.app resetAuthorizationStatusForResource:XCUIProtectedResourceCamera];
    [self.app launch];[self.app.buttons[@"takePhoto"] tap];
    [self respondToRealCameraPromptAllow:NO];
    XCUIElement *denied=[self.app.alerts.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'Camera access is off'"]].firstMatch;
    XCTAssertTrue([denied waitForExistenceWithTimeout:10],@"%@",self.app.debugDescription);
    [self.app terminate];XCTAssertTrue([self.app waitForState:XCUIApplicationStateNotRunning timeout:5]);
    [self.app resetAuthorizationStatusForResource:XCUIProtectedResourceCamera];
    NSLog(@"REAL_CAMERA_TCC_ALLOW_DENY: real OS dialogs/status via Debug availability probe; camera hardware not exercised");
}
- (void)testSampleSaveRelaunchDeleteAndBackground {
    [self.app.buttons[@"Sample Fixture"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);

    [self.app.buttons[@"saveColor"] tap];
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];
    [self.app activate];
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].exists);
    [self.app terminate];
    self.app.launchArguments=@[@"-AppleLanguages",@"(en)"];
    [self.app launch];
    XCUIElement *table=self.app.tables[@"colorHistory"];
    XCTAssertTrue([table.cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertEqual(table.cells.count,1);
    XCTAssertTrue([table.cells.firstMatch.label containsString:@"#ff0000"]);
    [table.cells.firstMatch swipeLeft];
    [self.app.buttons[@"Delete"] tap];
    XCTAssertEqual(table.cells.count,0);
    [self.app terminate];[self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0);
}
- (void)testNoCameraAndLiveLifecycleDoNotEnableInvalidSave {
    [self.app.buttons[@"takePhoto"] tap];
    XCTAssertTrue([self.app.alerts.firstMatch waitForExistenceWithTimeout:5]);
    [self.app.alerts.buttons[@"OK"] tap];
    [self.app.buttons[@"liveColor"] tap];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"].label containsString:@"not available"]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];
    [self.app activate];
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self.app.navigationBars.buttons.firstMatch tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
}
- (void)testAdaptiveLandscapePhotoSampling {
    [self.app.buttons[@"Sample Fixture"] tap];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    [self revealControl:self.app.buttons[@"sampleCenter"] inScrollView:self.app.scrollViews[@"photoControls"]];
    [self.app.buttons[@"sampleCenter"] tap];
    [self revealControl:self.app.buttons[@"saveColor"] inScrollView:self.app.scrollViews[@"photoControls"]];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
}
- (void)testLargestDynamicTypeControlsRemainReachable {
    [self.app terminate];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    [self revealControl:self.app.buttons[@"choosePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"takePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"liveColor"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self.app.buttons[@"Sample Fixture"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    [self revealControl:self.app.buttons[@"sampleCenter"] inScrollView:self.app.scrollViews[@"photoControls"]];
    [self.app.buttons[@"sampleCenter"] tap];
    [self revealControl:self.app.buttons[@"saveColor"] inScrollView:self.app.scrollViews[@"photoControls"]];
    XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
    [self.app.buttons[@"saveColor"] tap];
    [self.app.navigationBars.buttons.firstMatch tap];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    XCUIElement *table=self.app.tables[@"colorHistory"];
    XCUIElement *detail=table.staticTexts[@"R 255   G 0   B 0"];
    XCTAssertTrue([detail waitForExistenceWithTimeout:5]);
    for (NSUInteger i=0;i<4 && !CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1));i++) {
        if (CGRectGetMinY(detail.frame) < CGRectGetMinY(table.frame)) [table swipeDown]; else [table swipeUp];
    }
    XCTAssertTrue(CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1)),@"RGB detail must be fully readable after scrolling");
    [self emitScreenshot:@"touchcolor-history-large-text"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    [self revealControl:self.app.buttons[@"choosePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"takePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"liveColor"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    XCTAssertGreaterThan(table.frame.size.height,44);
    for (NSUInteger i=0;i<4 && !CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1));i++) {
        if (CGRectGetMinY(detail.frame) < CGRectGetMinY(table.frame)) [table swipeDown]; else [table swipeUp];
    }
    XCTAssertTrue(CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1)),@"Landscape RGB detail must remain readable at largest text size");
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
}
- (void)assertMarkerAtImageX:(CGFloat)x y:(CGFloat)y {
    XCUIElement *photo=self.app.images[@"sampleImage"], *marker=self.app.images[@"sampleMarker"];
    XCTAssertTrue(marker.exists,@"%@",self.app.debugDescription);
    XCTAssertEqualWithAccuracy(CGRectGetMidX(marker.frame),photo.frame.origin.x+photo.frame.size.width*x,2);
    XCTAssertEqualWithAccuracy(CGRectGetMidY(marker.frame),photo.frame.origin.y+photo.frame.size.height*y,2);
}
- (void)testAsymmetricMarkerCenterRotationLetterboxAndAccessibleZoomInDarkMode {
    [self.app terminate];
    self.app.launchArguments=[self.app.launchArguments arrayByAddingObjectsFromArray:@[@"--ui-test-asymmetric",@"--ui-test-dark"]];
    [self.app launch];[self.app.buttons[@"Sample Fixture"] tap];
    XCUIElement *photo=self.app.images[@"sampleImage"];
    XCTAssertTrue([photo waitForExistenceWithTimeout:5]);
    [[photo coordinateWithNormalizedOffset:CGVectorMake(0.15,0.25)] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
    [self assertMarkerAtImageX:0.15 y:0.25];
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [self assertMarkerAtImageX:0.5 y:0.5];
    [self emitScreenshot:@"touchcolor-asymmetric-dark"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    [self assertMarkerAtImageX:0.5 y:0.5];
    XCUIElement *viewport=self.app.scrollViews[@"photoViewport"];
    XCTAssertGreaterThan(viewport.frame.size.width,photo.frame.size.width+20);
    [[viewport coordinateWithNormalizedOffset:CGVectorMake(0.02,0.5)] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [self assertMarkerAtImageX:0.5 y:0.5];
    XCUIElement *zoom=self.app.sliders[@"photoZoom"];
    [self revealControl:zoom inScrollView:self.app.scrollViews[@"photoControls"]];
    XCTAssertEqualObjects(zoom.label,@"Zoom");
    CGFloat unzoomedWidth=photo.frame.size.width;
    // XCTest's thumb placement is approximate, especially with endpoint images.
    // Verify real magnification and the documented range rather than an assumed exact drag result.
    [zoom adjustToNormalizedSliderPosition:0.5];
    XCTAssertGreaterThan([zoom.value doubleValue],1);
    XCTAssertLessThanOrEqual([zoom.value doubleValue],100);
    XCTAssertGreaterThan(photo.frame.size.width,unzoomedWidth);
    [self revealControl:self.app.buttons[@"sampleCenter"] inScrollView:self.app.scrollViews[@"photoControls"]];
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue(self.app.images[@"sampleMarker"].exists);
    NSString *hex=[self.app.staticTexts[@"sampledColor"].label componentsSeparatedByString:@"\n"].firstObject;
    XCTAssertTrue([self.app.images[@"sampleMarker"].value containsString:hex]);
    CGRect photoFrame=photo.frame, markerFrame=self.app.images[@"sampleMarker"].frame;
    CGFloat x=(CGRectGetMidX(markerFrame)-photoFrame.origin.x)/photoFrame.size.width;
    CGFloat y=(CGRectGetMidY(markerFrame)-photoFrame.origin.y)/photoFrame.size.height;
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [self assertMarkerAtImageX:x y:y];
}
- (void)testLargestTextOfflinePolicyCanScrollRetryAndCloseInLandscape {
    [self.app terminate];
    // This route uses production navigation: no unrelated Debug fixture button crowds the SE navigation bar.
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-policy-offline",@"--ui-test-dark",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"privacyPolicy"] waitForExistenceWithTimeout:5]);
    [self.app.buttons[@"privacyPolicy"] tap];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    XCUIElement *retry=self.app.buttons[@"privacy.retry"];
    XCTAssertTrue([retry waitForExistenceWithTimeout:5]);
    [self revealControl:retry inScrollView:self.app.scrollViews[@"privacy.errorScroll"]];
    XCTAssertTrue(self.app.buttons[@"privacy.close"].hittable);
    [retry tap];
    XCTAssertFalse(self.app.staticTexts[@"privacy.error"].exists);
    [self.app.buttons[@"privacy.close"] tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
}
- (void)testSystemPhotoSelectionAndSampling {
    // CI seeds one known 300×200 RGB fixture. iOS17 labels it Photo; iOS27 adds a grid identifier.
    [self.app.buttons[@"choosePhoto"] tap];
    NSPredicate *photoPredicate=[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"];
    XCUIElement *photo=[self.app.images matchingPredicate:photoPredicate].firstMatch;
    XCTAssertTrue([photo waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [photo tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [[self.app.images[@"sampleImage"] coordinateWithNormalizedOffset:CGVectorMake(0.15,0.25)] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
}
@end
