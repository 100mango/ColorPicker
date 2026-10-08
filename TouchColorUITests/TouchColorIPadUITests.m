#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#import <math.h>

@interface TouchColorIPadUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic) CGSize originalWindowSize;
@property (nonatomic) BOOL recordingIssue;
@end
@implementation TouchColorIPadUITests
- (void)recordIssue:(XCTIssue *)issue {
    if (self.recordingIssue) { [super recordIssue:issue]; return; }
    self.recordingIssue=YES;
    // Preserve real failure evidence before continueAfterFailure aborts the case.
    static NSMutableSet<NSString *> *recordedCases;
    static dispatch_once_t once;dispatch_once(&once,^{ recordedCases=[NSMutableSet new]; });
    if (self.app.state==XCUIApplicationStateRunningForeground && recordedCases.count<2 && ![recordedCases containsObject:self.name]) {
        [recordedCases addObject:self.name];
        NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
        if (bytes.length && bytes.length<=500*1024u) {
            XCTAttachment *attachment=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
            attachment.name=[NSString stringWithFormat:@"touchcolor-ipad-functional-failure-%lu",(unsigned long)recordedCases.count];
            attachment.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:attachment];
        }
    }
    // Capture pixels before the potentially slow remote hierarchy query.
    NSLog(@"IPAD_FUNCTIONAL_FAILURE case=%@ issue=%@\n%@",self.name,issue.compactDescription,self.app.debugDescription);
    self.recordingIssue=NO;
    [super recordIssue:issue];
}
- (void)setUp {
    [super setUp];self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10],@"%@",self.app.debugDescription);
    XCTAssertTrue(self.app.staticTexts[@"workspace.empty"].exists,@"Native canvas must be visible beside the palette");
}
- (void)choosePhoto {
    XCUIElement *source=self.app.buttons[@"choosePhoto"];
    XCTAssertTrue([source waitForExistenceWithTimeout:5],@"The photo source must exist");
    XCTAssertTrue(source.hittable,@"The photo source must be directly usable");
    NSLog(@"PHOTO_SOURCE_BEFORE %@",source.value);
    [source tap];
}
- (void)importFixture {
    [self choosePhoto];
    XCUIElement *photo=[self.app.images matchingPredicate:[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"]].firstMatch;
    XCTAssertTrue([photo waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [photo tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    XCUIElement *sample=self.app.buttons[@"sampleCenter"];
    for (NSUInteger i=0;i<5 && !sample.hittable;i++) [self.app.scrollViews[@"photoControls"] swipeUp];
    [sample tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [[self.app.images[@"sampleImage"] coordinateWithNormalizedOffset:CGVectorMake(0.15,0.25)] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"],@"The selected photo must be the seeded asymmetric RGB fixture");
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
}
- (void)cancelPicker {
    XCUIElement *popover=self.app.popovers.firstMatch;
    XCUIElement *content=self.app.scrollViews[@"photosView_content_scroll_view"];
    XCUIElement *cancel=self.app.navigationBars[@"Photos"].buttons[@"Cancel"].firstMatch;
    // Resolve either observed system presentation in one native existence wait.
    // Import still waits separately for the real image and validates its RGB pixels.
    NSPredicate *presentationType=[NSPredicate predicateWithFormat:@"elementType == %lu OR (elementType == %lu AND identifier == %@)",(unsigned long)XCUIElementTypePopover,(unsigned long)XCUIElementTypeNavigationBar,@"Photos"];
    XCUIElement *presented=[[self.app descendantsMatchingType:XCUIElementTypeAny] matchingPredicate:presentationType].firstMatch;
    XCTAssertTrue([presented waitForExistenceWithTimeout:15],@"The system Photos presentation must exist before cancellation");
    CGRect window=self.app.windows.firstMatch.frame;
    CGRect picker=popover.exists ? popover.frame : CGRectZero;
    BOOL dismissedPopover=NO;
    if (!CGRectIsEmpty(picker)) {
        NSArray<NSValue *> *outside=@[[NSValue valueWithCGPoint:CGPointMake(CGRectGetMaxX(window)-20,CGRectGetMidY(window))],[NSValue valueWithCGPoint:CGPointMake(CGRectGetMinX(window)+20,CGRectGetMidY(window))],[NSValue valueWithCGPoint:CGPointMake(CGRectGetMidX(window),CGRectGetMaxY(window)-20)],[NSValue valueWithCGPoint:CGPointMake(CGRectGetMidX(window),CGRectGetMinY(window)+20)]];
        for (NSValue *value in outside) {
            CGPoint point=value.CGPointValue;
            if (!CGRectContainsPoint(picker,point)) {
                XCUICoordinate *origin=[self.app.windows.firstMatch coordinateWithNormalizedOffset:CGVectorMake(0,0)];
                [[origin coordinateWithOffset:CGVectorMake(point.x-window.origin.x,point.y-window.origin.y)] tap];
                dismissedPopover=YES;break;
            }
        }
    }
    if (!dismissedPopover) {
        CGRect cancelFrame=cancel.exists ? cancel.frame : CGRectZero;
        XCTAssertTrue(!CGRectIsEmpty(cancelFrame) && !CGRectIsNull(cancelFrame) && CGRectContainsRect(window,cancelFrame),@"Adapted sheet Cancel must remain usable: %@",self.app.debugDescription);
        [cancel tap];
    }
    XCUIElement *presentation=dismissedPopover ? popover : cancel;
    // Three remote AX queries inside one predicate can exhaust its deadline even
    // after Photos has dismissed. Wait for that presentation once, then verify
    // every picker element is absent without another gesture or a longer timeout.
    [self assertPresentationDisappears:presentation];
    XCTAssertFalse(popover.exists,@"No Photos popover may remain after cancellation");
    XCTAssertFalse(content.exists,@"No Photos content may remain after cancellation");
    XCTAssertFalse(cancel.exists,@"No Photos Cancel control may remain after cancellation");
}
- (void)assertPresentationDisappears:(XCUIElement *)presentation {
    BOOL disappeared;
    if (@available(iOS 18.0, *)) disappeared=[presentation waitForNonExistenceWithTimeout:5];
    else {
        XCTNSPredicateExpectation *closed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:presentation];
        disappeared=[XCTWaiter waitForExpectations:@[closed] timeout:5]==XCTWaiterResultCompleted;
    }
    XCTAssertTrue(disappeared,@"The observed presentation must disappear within five seconds");
}
- (void)testNativeCanvasPaletteSavePreviewPickerCancelAndRelaunch {
    [self importFixture];
    XCUIElement *history=self.app.tables[@"colorHistory"], *photo=self.app.images[@"sampleImage"];
    XCTAssertTrue(history.hittable);
    XCTAssertLessThanOrEqual(CGRectGetMaxX(history.frame),CGRectGetMinX(photo.frame),@"Separate native palette and canvas columns");
    [self.app.buttons[@"saveColor"] tap];
    XCTAssertTrue([history.cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertTrue([history.cells.firstMatch.label containsString:@"#ff00ff"]);
    if (MAX(UIScreen.mainScreen.bounds.size.width,UIScreen.mainScreen.bounds.size.height)>1200) {
        NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
        XCTAssertLessThanOrEqual(bytes.length,500*1024);
        XCTAttachment *image=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
        image.name=@"touchcolor-ipad-native-canvas";image.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:image];
    }
    for (NSUInteger attempt=0;attempt<3;attempt++) {
        [history.cells.firstMatch tap];
        XCTAssertTrue([self.app.alerts.firstMatch waitForExistenceWithTimeout:5]);
        XCUIElement *close=self.app.alerts.buttons[@"Close"];
        NSLog(@"PREVIEW_CLOSE attempt=%lu alert=%@ close=%@ hittable=%d",(unsigned long)attempt,NSStringFromCGRect(self.app.alerts.firstMatch.frame),NSStringFromCGRect(close.frame),close.hittable);
        [close tap];
        [self assertPresentationDisappears:self.app.alerts.firstMatch];
    }
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [self choosePhoto];
    [self cancelPicker];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    XCTAssertEqual(history.cells.count,1);
    [self.app terminate];self.app.launchArguments=@[@"-AppleLanguages",@"(en)"];[self.app launch];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch.label containsString:@"#ff00ff"]);
}
- (void)testKeyboardImportSamplingZoomSaveAndRotation {
    [self.app typeKey:@"o" modifierFlags:XCUIKeyModifierCommand];
    [self cancelPicker];
    [self importFixture];
    [self.app.images[@"sampleImage"] tap];
    CGFloat before=self.app.images[@"sampleImage"].frame.size.width;
    [self.app typeKey:@"+" modifierFlags:0];
    XCTAssertGreaterThan(self.app.images[@"sampleImage"].frame.size.width,before);
    [self.app typeKey:@"0" modifierFlags:XCUIKeyModifierCommand];
    XCTAssertEqualWithAccuracy(self.app.images[@"sampleImage"].frame.size.width,before,2);
    [self.app typeKey:@" " modifierFlags:0];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [self.app typeKey:@"s" modifierFlags:XCUIKeyModifierCommand];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    NSString *selected=self.app.staticTexts[@"sampledColor"].label;
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    XCTAssertTrue([self.app.images[@"sampleMarker"].value containsString:@"#ff00ff"]);
    if (self.app.buttons[@"workspace.palette"].exists) [self.app.buttons[@"workspace.palette"] tap];
    XCTAssertTrue(self.app.tables[@"colorHistory"].hittable);
    if (self.app.buttons[@"workspace.canvas"].exists) [self.app.buttons[@"workspace.canvas"] tap];
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
}
- (void)testLargestTextNativePaletteAndCanvasControls {
    [self.app terminate];self.app.launchArguments=[self.app.launchArguments arrayByAddingObjectsFromArray:@[@"--ui-test-dark",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"]];[self.app launch];
    XCUIElement *sources=self.app.scrollViews[@"sourceControls"];
    for (NSString *identifier in @[@"choosePhoto",@"takePhoto",@"liveColor"]) {
        XCUIElement *button=self.app.buttons[identifier];
        for (NSUInteger i=0;i<5 && (!button.hittable || !CGRectContainsRect(sources.frame,CGRectInset(button.frame,1,1)));i++) [sources swipeUp];
        XCTAssertTrue(button.hittable,@"%@",self.app.debugDescription);
        XCTAssertGreaterThanOrEqual(button.frame.size.height,44);
    }
    [sources swipeDown];[sources swipeDown];
    [self importFixture];
    XCUIElement *controls=self.app.scrollViews[@"photoControls"];
    XCUIElement *save=self.app.buttons[@"saveColor"];
    for (NSUInteger i=0;i<5 && !save.hittable;i++) [controls swipeUp];
    XCTAssertTrue(save.hittable);[save tap];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    XCTAssertTrue(self.app.sliders[@"photoZoom"].exists);
    XCTAssertTrue(self.app.buttons[@"workspace.sources"].hittable);
}
- (void)testLiveCanvasPickerCancellationAndSceneLifecycle {
    [self.app.buttons[@"liveColor"] tap];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self choosePhoto];
    [self cancelPicker];
    XCTNSPredicateExpectation *resumed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'not available'"] object:self.app.staticTexts[@"cameraStatus"]];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[resumed] timeout:5],XCTWaiterResultCompleted,@"Popover dismissal must leave the paused state: %@",self.app.debugDescription);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];[self.app activate];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"].label containsString:@"not available"]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self importFixture];
    XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
}
- (void)testPrivacyCloseRetainsPhotoSelection {
    [self importFixture];
    [self.app.buttons[@"privacyPolicy"] tap];
    XCTAssertTrue([self.app.buttons[@"privacy.close"] waitForExistenceWithTimeout:5]);
    [self.app.buttons[@"privacy.close"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
}
- (void)testZNativeWindowResizePreservesSelectionAndPaletteReturn {
    [self importFixture];[self.app.buttons[@"saveColor"] tap];
    NSString *selection=self.app.staticTexts[@"sampledColor"].label;
    XCUIElement *window=self.app.windows.firstMatch;
    CGRect original=window.frame;
    self.originalWindowSize=original.size;
    XCUICoordinate *corner=[[window coordinateWithNormalizedOffset:CGVectorMake(1,1)] coordinateWithOffset:CGVectorMake(-12,-12)];
    @try {
        // Apple's documented iPadOS window handle; this is an OS window resize, not a test-only app frame.
        [corner pressForDuration:0.3 thenDragToCoordinate:[window coordinateWithNormalizedOffset:CGVectorMake(0.45,0.75)]];
        XCTNSPredicateExpectation *resized=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object, NSDictionary *bindings) { return window.frame.size.width < original.size.width-100; }] object:window];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[resized] timeout:8],XCTWaiterResultCompleted,@"Actual window resize required: %@",self.app.debugDescription);
        NSLog(@"NATIVE_WINDOW_RESIZE before=%@ after=%@",NSStringFromCGRect(original),NSStringFromCGRect(window.frame));
        XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selection);
        CGRect image=self.app.images[@"sampleImage"].frame, marker=self.app.images[@"sampleMarker"].frame;
        XCTAssertEqualWithAccuracy(CGRectGetMidX(marker),CGRectGetMidX(image),2);
        XCTAssertEqualWithAccuracy(CGRectGetMidY(marker),CGRectGetMidY(image),2);
        if (self.app.buttons[@"workspace.palette"].exists) [self.app.buttons[@"workspace.palette"] tap];
        XCTAssertTrue(self.app.tables[@"colorHistory"].hittable);
        if (self.app.buttons[@"workspace.canvas"].exists) [self.app.buttons[@"workspace.canvas"] tap];
        XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
        XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selection);
        [self.app typeKey:@"o" modifierFlags:XCUIKeyModifierCommand];
        [self cancelPicker]; // Exercises the toolbar anchor when the palette is hidden.
        XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selection);
    } @finally {
        if (window.frame.size.width < original.size.width-20) {
            // Apple documents double-tapping the top of a window to return it to full screen.
            [[[window coordinateWithNormalizedOffset:CGVectorMake(0.5,0)] coordinateWithOffset:CGVectorMake(0,12)] doubleTap];
            XCTNSPredicateExpectation *restored=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object, NSDictionary *bindings) { CGSize size=window.frame.size; return fabs(size.width-original.size.width)<4 && fabs(size.height-original.size.height)<4; }] object:window];
            XCTAssertEqual([XCTWaiter waitForExpectations:@[restored] timeout:8],XCTWaiterResultCompleted,@"Restore full window: %@",self.app.debugDescription);
            NSLog(@"NATIVE_WINDOW_RESTORED %@",NSStringFromCGRect(window.frame));
            self.originalWindowSize=CGSizeZero;
        }
    }
}
- (void)tearDown {
    // XCTest can end a failing case before its remaining actions. Recover the OS window
    // independently so a failed modal assertion cannot change the next suite's geometry.
    if (self.originalWindowSize.width>0) {
        [self.app terminate];[self.app launch];
        XCUIElement *window=self.app.windows.firstMatch;
        if (fabs(window.frame.size.width-self.originalWindowSize.width)>4) {
            [[[window coordinateWithNormalizedOffset:CGVectorMake(0.5,0)] coordinateWithOffset:CGVectorMake(0,12)] doubleTap];
            XCTNSPredicateExpectation *restored=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object,NSDictionary *bindings) {
                CGSize size=window.frame.size;
                return fabs(size.width-self.originalWindowSize.width)<4 && fabs(size.height-self.originalWindowSize.height)<4;
            }] object:window];
            XCTAssertEqual([XCTWaiter waitForExpectations:@[restored] timeout:8],XCTWaiterResultCompleted,@"Restore OS window after failed case: %@",self.app.debugDescription);
        }
        self.originalWindowSize=CGSizeZero;
    }
    [self.app terminate];
    XCTAssertTrue([self.app waitForState:XCUIApplicationStateNotRunning timeout:10],@"Each independent case must finish with its app process stopped");
    [super tearDown];
}
@end
