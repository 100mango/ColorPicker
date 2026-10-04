#include <stdlib.h>
#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#import "TCPaletteUIHelpers.h"
#include <stdio.h>
@interface TouchColorUITests : XCTestCase
@property (nonatomic, strong) id<NSObject> failClosedInterruption;
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic) BOOL recordingIssue;
@end
@implementation TouchColorUITests
- (void)recordIssue:(XCTIssue *)issue {
    if (self.recordingIssue) { [super recordIssue:issue]; return; }
    self.recordingIssue=YES;
    // Preserve real failure evidence before continueAfterFailure aborts the case.
    static NSMutableSet<NSString *> *recordedCases;
    static dispatch_once_t once;dispatch_once(&once,^{ recordedCases=[NSMutableSet new]; });
    if (recordedCases.count<1 && ![recordedCases containsObject:self.name]) {
        [recordedCases addObject:self.name];
        NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
        if (bytes.length && bytes.length<=500*1024u) {
            XCTAttachment *attachment=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
            attachment.name=[NSString stringWithFormat:@"touchcolor-phone-functional-failure-%lu",(unsigned long)recordedCases.count];
            attachment.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:attachment];
        }
    }
    // Capture pixels before the potentially slow remote hierarchy query.
    NSLog(@"PHONE_FUNCTIONAL_FAILURE case=%@ issue=%@\n%@",self.name,issue.compactDescription,self.app.debugDescription);
    [self observeFailedPalettePresentation:self.app caseName:self.name];
    self.recordingIssue=NO;
    [super recordIssue:issue];
}
- (void)emitScreenshot:(NSString *)name {
    if (![name isEqualToString:@"touchcolor-history-large-text"] || UIDevice.currentDevice.userInterfaceIdiom != UIUserInterfaceIdiomPhone || MIN(UIScreen.mainScreen.bounds.size.width,UIScreen.mainScreen.bounds.size.height)>400) return;
    NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
    XCTAssertLessThanOrEqual(bytes.length,500*1024);
    XCTAttachment *image=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
    image.name=name;image.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:image];
}
- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }
- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }
- (void)testPaletteFileCancellationAndWatchInboxReturn { [self exercisePaletteFileCancelAndWatchInboxReturn:self.app]; }
- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }
- (void)testLargestTextPaletteReviewAndInbox { [self exerciseLargestTextPaletteReviewAndInbox:self.app]; }
- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }
- (void)setUp {
    [super setUp];
    // Install before launch; known dialog controls stay in their explicit tests.
    self.failClosedInterruption=[self addUIInterruptionMonitorWithDescription:@"Abort every unhandled system interruption" handler:^BOOL(XCUIElement *unusedAlert) {
        // No UI query or failure recorder can throw and reach XCTest's default handler.
        fputs("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT class=TouchColorUITests; no alert action taken\n",stderr);
        abort();
    }];
    self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    if ([self.name containsString:@"testInvalidPalettePastePreservesHistory"] || [self.name containsString:@"testPaletteFileCancellationAndWatchInboxReturn"] || [self.name containsString:@"testPaletteFileSelectionReviewAndRelaunch"])
        self.app.launchArguments=[self.app.launchArguments arrayByAddingObject:@"--ui-test-palette-lifecycle"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [self.app launch];
}
- (void)revealControl:(XCUIElement *)element inScrollView:(XCUIElement *)scroll {
    for (NSUInteger attempt=0;attempt<5 && (!element.hittable || !CGRectContainsRect(scroll.frame,CGRectInset(element.frame,1,1)));attempt++) {
        [self scrollTowardElement:element inScroll:scroll];
    }
    XCTAssertTrue(element.hittable,@"%@",self.app.debugDescription);
    XCTAssertTrue(CGRectContainsRect(scroll.frame,CGRectInset(element.frame,1,1)),@"The entire control must remain inside its scroll viewport");
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
        [self assertPresentationDisappears:cancel];
        XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
        XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable,@"Photo cancellation must restore the usable source action");
    }
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0);
}
- (void)assertPresentationDisappears:(XCUIElement *)presentation {
    BOOL disappeared;
    if (@available(iOS 18.0, *)) disappeared=[presentation waitForNonExistenceWithTimeout:5];
    else {
        XCTNSPredicateExpectation *closed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:presentation];
        disappeared=[XCTWaiter waitForExpectations:@[closed] timeout:5]==XCTWaiterResultCompleted;
    }
    XCTAssertTrue(disappeared,@"The observed system presentation must disappear within five seconds");
}
- (void)respondToRealCameraPromptAllow:(BOOL)allow {
    XCUIApplication *system=[[XCUIApplication alloc] initWithBundleIdentifier:@"com.apple.springboard"];
    // Exact English title observed in run37162409475/job111318389328 for both choices.
    NSString *cameraTitle=@"Allow “TouchColor” to access your camera?";
    XCUIElement *alert=system.alerts[cameraTitle];
    if (![alert waitForExistenceWithTimeout:15]) {
        XCTFail(@"The exact TouchColor system camera prompt is missing; no consent action taken");
        return;
    }
    BOOL namesApp=[alert.label containsString:@"TouchColor"] || [alert.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'TouchColor'"]].count>0;
    if (!namesApp || ![alert.label isEqualToString:cameraTitle]) {
        XCTFail(@"Unexpected system prompt; no consent action taken");
        return;
    }
    XCUIElement *allowButton=alert.buttons[@"Allow"], *denyButton=alert.buttons[@"Don’t Allow"];
    if (!allowButton.exists || !denyButton.exists) {
        XCTFail(@"Observed camera consent choices are missing; no consent action taken");
        return;
    }
    XCUIElement *button=allow ? allowButton : denyButton;
    if (!button.enabled || !button.hittable) {
        XCTFail(@"Observed camera consent choice is not actionable; no consent action taken");
        return;
    }
    [button tap];
    [self assertPresentationDisappears:alert];
    NSLog(@"REAL_OS_CAMERA_PROMPT_%@",allow ? @"ALLOW" : @"DENY");
}
- (void)testRealCameraPermissionAllowThenResetAndDeny {
    [self.app terminate];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-camera-permission",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    [self.app resetAuthorizationStatusForResource:XCUIProtectedResourceCamera];
    [self.app launch];[self.app.buttons[@"takePhoto"] tap];
    [self respondToRealCameraPromptAllow:YES];
    XCUIElement *status=self.app.staticTexts[@"cameraPermissionStatus"];
    NSPredicate *allowed=[NSPredicate predicateWithFormat:@"label == 'Camera: allowed'"];
    XCTNSPredicateExpectation *authorized=[[XCTNSPredicateExpectation alloc] initWithPredicate:allowed object:status];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[authorized] timeout:10],XCTWaiterResultCompleted,@"%@",self.app.debugDescription);
    NSInteger activation=[status.value integerValue];
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];[self.app activate];
    NSPredicate *reread=[NSPredicate predicateWithBlock:^BOOL(id object, NSDictionary *bindings) { XCUIElement *element=object; return [element.value integerValue]>activation; }];
    XCTNSPredicateExpectation *foreground=[[XCTNSPredicateExpectation alloc] initWithPredicate:reread object:status];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[foreground] timeout:10],XCTWaiterResultCompleted,@"Foreground must reread the real OS authorization status");
    XCTAssertEqualObjects(status.label,@"Camera: allowed");
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
    [self returnToPaletteFrom:@"Live Color" app:self.app];
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
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"--ui-test-scroll-state",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCUIElement *emptyScroll=self.app.scrollViews[@"history.emptyScroll"];
    XCUIElement *emptyMessage=emptyScroll.staticTexts[@"history.empty"].firstMatch;
    XCTAssertTrue([emptyMessage waitForExistenceWithTimeout:5]);
    NSLog(@"EMPTY_INSTRUCTION before frame=%@ viewport=%@ state=%@",NSStringFromCGRect(emptyMessage.frame),NSStringFromCGRect(emptyScroll.frame),emptyScroll.value);
    XCTAssertGreaterThanOrEqual(CGRectGetMinY(emptyMessage.frame),CGRectGetMinY(emptyScroll.frame)-1);
    for (NSUInteger attempt=0;attempt<5 && CGRectGetMaxY(emptyMessage.frame)>CGRectGetMaxY(emptyScroll.frame)+1;attempt++) {
        [emptyScroll swipeUpWithVelocity:XCUIGestureVelocitySlow];
    }
    NSLog(@"EMPTY_INSTRUCTION after frame=%@ viewport=%@ state=%@",NSStringFromCGRect(emptyMessage.frame),NSStringFromCGRect(emptyScroll.frame),emptyScroll.value);
    XCTAssertLessThanOrEqual(CGRectGetMaxY(emptyMessage.frame),CGRectGetMaxY(emptyScroll.frame)+1,@"The complete instruction's final line must be revealable by actual user scrolling");
    [self revealControl:self.app.buttons[@"choosePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"takePhoto"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"liveColor"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"palette.import.open"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"watch.inbox.open"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self.app.buttons[@"Sample Fixture"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    [self revealControl:self.app.buttons[@"sampleCenter"] inScrollView:self.app.scrollViews[@"photoControls"]];
    [self.app.buttons[@"sampleCenter"] tap];
    [self revealControl:self.app.buttons[@"saveColor"] inScrollView:self.app.scrollViews[@"photoControls"]];
    XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
    [self.app.buttons[@"saveColor"] tap];
    [self returnToPaletteFrom:@"Photo Color" app:self.app];
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
    [self revealControl:self.app.buttons[@"palette.import.open"] inScrollView:self.app.scrollViews[@"sourceControls"]];
    [self revealControl:self.app.buttons[@"watch.inbox.open"] inScrollView:self.app.scrollViews[@"sourceControls"]];
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
- (void)tearDown {
    @try {
        [super tearDown];
    } @finally {
        if (self.failClosedInterruption) [self removeUIInterruptionMonitor:self.failClosedInterruption];
        self.failClosedInterruption=nil;
    }
}
@end
