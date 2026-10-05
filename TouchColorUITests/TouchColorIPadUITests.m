#include <stdlib.h>
#include <stdio.h>
#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#import "TCPaletteUIHelpers.h"
#import "TCSystemPickerGeometry.h"
#import <math.h>

static void TCObservePhotosSnapshot(id<XCUIElementSnapshot> snapshot, TCPickerSnapshotObservation *observation, BOOL isRoot) {
    TCPickerNodeKind kind=TCPickerNodeOther;
    if (snapshot.elementType==XCUIElementTypePopover) kind=TCPickerNodePopover;
    else if (snapshot.elementType==XCUIElementTypeNavigationBar) kind=TCPickerNodeNavigationBar;
    else if (snapshot.elementType==XCUIElementTypeScrollView) kind=TCPickerNodeScrollView;
    TCObservePhotosSnapshotNode(observation,kind,snapshot.identifier.UTF8String,snapshot.label.UTF8String,snapshot.frame,isRoot);
    if (!observation->rootUsable) return; // Reject the actual root before traversing any children.
    for (id<XCUIElementSnapshot> child in snapshot.children) TCObservePhotosSnapshot(child,observation,NO);
}

@interface TouchColorIPadUITests : XCTestCase
@property (nonatomic, strong) id<NSObject> failClosedInterruption;
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic) CGSize originalWindowSize;
@property (nonatomic) BOOL recordingIssue;
@end
@implementation TouchColorIPadUITests
- (void)recordIssue:(XCTIssue *)issue {
    if (self.tcPaletteReadinessExpired) {
        // Preserve the failure without our own post-deadline AX/screenshot requests.
        NSLog(@"IPAD_FUNCTIONAL_FAILURE case=%@ readinessExpired=1 issue=%@",self.name,issue.compactDescription);
        [super recordIssue:issue]; return;
    }
    if (self.recordingIssue) { [super recordIssue:issue]; return; }
    self.recordingIssue=YES;
    // Preserve real failure evidence before continueAfterFailure aborts the case.
    static NSMutableSet<NSString *> *recordedCases;
    static dispatch_once_t once;dispatch_once(&once,^{ recordedCases=[NSMutableSet new]; });
    if (recordedCases.count<2 && ![recordedCases containsObject:self.name]) {
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
    [self observeFailedPalettePresentation:self.app caseName:self.name];
    self.recordingIssue=NO;
    [super recordIssue:issue];
}
- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }
- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }
- (void)testPaletteFileCancellationAndWatchInboxReturn { [self exercisePaletteFileCancelAndWatchInboxReturn:self.app]; }
- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }
- (void)testLargestTextPaletteReviewAndInbox { [self exerciseLargestTextPaletteReviewAndInbox:self.app]; }
- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }
- (void)setUp {
    self.tcPaletteReadinessExpired=NO;
    [super setUp];
    // Install before launch; known dialog controls stay in their explicit tests.
    self.failClosedInterruption=[self addUIInterruptionMonitorWithDescription:@"Abort every unhandled system interruption" handler:^BOOL(XCUIElement *unusedAlert) {
        // No UI query or failure recorder can throw and reach XCTest's default handler.
        fputs("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT class=TouchColorIPadUITests; no alert action taken\n",stderr);
        abort();
    }];self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    if ([self.name containsString:@"testInvalidPalettePastePreservesHistory"] || [self.name containsString:@"testPaletteFileCancellationAndWatchInboxReturn"] || [self.name containsString:@"testPaletteFileSelectionReviewAndRelaunch"])
        self.app.launchArguments=[self.app.launchArguments arrayByAddingObject:@"--ui-test-palette-lifecycle"];
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
    // Resolve actual Photos chrome, not the app-owned placeholder popover. The
    // keyed query accepts the observed system title as an identifier or label.
    // Cancellation does not wait for any photo grid item to finish loading.
    XCUIElement *photosNavigation=self.app.navigationBars[@"Photos"].firstMatch;
    XCTAssertTrue([photosNavigation waitForExistenceWithTimeout:15],@"Actual system Photos navigation must attach before cancellation");
    XCUIElement *windowElement=self.app.windows.firstMatch;
    CGRect window=windowElement.frame;
    CGRect picker=popover.exists ? popover.frame : CGRectZero;
    BOOL dismissedPopover=NO;
    if (!CGRectIsEmpty(picker)) {
        // A first-window snapshot is not the resolved Photos presentation. Its
        // missing/unexpanded remote descendants must not be a readiness gate.
        // Snapshot the actual popover root after Photos chrome attaches, keeping
        // its outer bounds even when remote descendants are not returned.
        __block CGRect previous=CGRectNull, observedPicker=CGRectNull;
        __block NSError *snapshotError=nil;
        __block NSUInteger observations=0;
        NSTimeInterval start=NSProcessInfo.processInfo.systemUptime;
        XCTNSPredicateExpectation *settled=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object, NSDictionary *bindings) {
            id<XCUIElementSnapshot> snapshot=[popover snapshotWithError:&snapshotError];
            ++observations;
            if (!snapshot) {
                TCPickerAdvanceStability(NULL,&previous,&observedPicker);
                if (observations<=5) NSLog(@"PHOTO_PICKER_SNAPSHOT observation=%lu missing=1 errorDomain=%@ errorCode=%ld",(unsigned long)observations,snapshotError.domain,(long)snapshotError.code);
                return NO;
            }
            TCPickerSnapshotObservation observation={CGRectNull,0,0,NO};
            TCObservePhotosSnapshot(snapshot,&observation,YES);
            CGRect bounds=observation.bounds;
            BOOL same=TCPickerAdvanceStability(&observation,&previous,&observedPicker);
            if (observations<=5) NSLog(@"PHOTO_PICKER_SNAPSHOT observation=%lu root=%@ bounds=%@ nodes=%lu chrome=%lu stable=%d elapsed=%.3f",(unsigned long)observations,NSStringFromCGRect(snapshot.frame),NSStringFromCGRect(bounds),(unsigned long)observation.nodes,(unsigned long)observation.chromeMatches,same,NSProcessInfo.processInfo.systemUptime-start);
            return same;
        }] object:nil];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[settled] timeout:5],XCTWaiterResultCompleted,@"Photos presentation geometry must settle before cancellation: %@",snapshotError);
        XCTAssertLessThanOrEqual(NSProcessInfo.processInfo.systemUptime-start,5,@"Snapshot resolution must stay within the geometry budget");
        XCTAssertTrue(CGRectEqualToRect(windowElement.frame,window),@"The host window must not change during picker cancellation");
        picker=observedPicker;
        CGPoint point;
        if (TCPickerDismissalPoint(window,picker,&point)) {
            UIDeviceOrientation orientation=XCUIDevice.sharedDevice.orientation;
            TCPickerScreenContext screenContext={(long)orientation,UIDeviceOrientationIsLandscape(orientation),UIScreen.mainScreen.bounds,UIScreen.mainScreen.fixedCoordinateSpace.bounds};
            XCTAssertTrue(TCPickerScreenContextUsable(screenContext),@"A valid recorded landscape screen context is required before measuring coordinates");
            if (!TCPickerScreenContextUsable(screenContext)) return;
            // AX frames follow the app orientation; screenPoint is dynamically
            // resolved by XCTest. Measure its basis instead of assuming that an
            // AX point can be added as an absolute offset in the same space.
            CGPoint zero=[windowElement coordinateWithNormalizedOffset:CGVectorMake(0,0)].screenPoint;
            CGPoint oneX=[windowElement coordinateWithNormalizedOffset:CGVectorMake(1,0)].screenPoint;
            CGPoint oneY=[windowElement coordinateWithNormalizedOffset:CGVectorMake(0,1)].screenPoint;
            NSLog(@"PHOTO_PICKER_BASIS deviceOrientation=%ld runnerScreenBounds=%@ fixedScreenBounds=%@ AXWindow=%@ basis00=%@ basis10=%@ basis01=%@",screenContext.orientation,NSStringFromCGRect(screenContext.currentBounds),NSStringFromCGRect(screenContext.fixedBounds),NSStringFromCGRect(window),NSStringFromCGPoint(zero),NSStringFromCGPoint(oneX),NSStringFromCGPoint(oneY));
            TCPickerScreenMap map;
            BOOL validMap=TCPickerMakeScreenMap(window,zero,oneX,oneY,&map);
            XCTAssertTrue(validMap,@"Measured XCTest coordinate basis must be finite and nondegenerate");
            if (!validMap) return;
            CGPoint expected,expectedCorner,corners[4];
            CGRect exclusion=CGRectInset(picker,-12,-12);
            BOOL mapped=TCPickerMapAXPoint(map,point,&expected) &&
                TCPickerMapAXPoint(map,CGPointMake(CGRectGetMaxX(window),CGRectGetMaxY(window)),&expectedCorner) &&
                TCPickerMapAXRect(map,exclusion,corners);
            XCTAssertTrue(mapped,@"Window and popover exclusion must map into the same screen-point space");
            if (!mapped) return;
            XCUICoordinate *target=[windowElement coordinateWithNormalizedOffset:CGVectorMake((point.x-window.origin.x)/window.size.width,(point.y-window.origin.y)/window.size.height)];
            CGPoint actual=target.screenPoint;
            CGPoint farCorner=[windowElement coordinateWithNormalizedOffset:CGVectorMake(1,1)].screenPoint;
            NSLog(@"PHOTO_PICKER_COORDINATES deviceOrientation=%ld runnerScreenBounds=%@ fixedScreenBounds=%@ AXWindow=%@ AXPresentation=%@ AXPoint=%@ basis00=%@ basis10=%@ basis01=%@ basis11=%@ expected=%@ actual=%@ screenExclusion=%@,%@,%@,%@",screenContext.orientation,NSStringFromCGRect(screenContext.currentBounds),NSStringFromCGRect(screenContext.fixedBounds),NSStringFromCGRect(window),NSStringFromCGRect(picker),NSStringFromCGPoint(point),NSStringFromCGPoint(zero),NSStringFromCGPoint(oneX),NSStringFromCGPoint(oneY),NSStringFromCGPoint(farCorner),NSStringFromCGPoint(expected),NSStringFromCGPoint(actual),NSStringFromCGPoint(corners[0]),NSStringFromCGPoint(corners[1]),NSStringFromCGPoint(corners[2]),NSStringFromCGPoint(corners[3]));
            BOOL affine=TCPickerPointIsFinite(farCorner) && fabs(farCorner.x-expectedCorner.x)<=1 && fabs(farCorner.y-expectedCorner.y)<=1;
            BOOL targetMatches=TCPickerPointIsFinite(actual) && fabs(actual.x-expected.x)<=1 && fabs(actual.y-expected.y)<=1;
            XCTAssertTrue(affine,@"The fourth normalized corner must agree with the measured affine basis");
            XCTAssertEqualWithAccuracy(actual.x,expected.x,1);XCTAssertEqualWithAccuracy(actual.y,expected.y,1);
            BOOL outside=TCPickerScreenPointRelation(map,exclusion,actual)==TCPickerScreenRelationOutside;
            BOOL insideWindow=TCPickerScreenPointRelation(map,CGRectInset(window,20,20),actual)==TCPickerScreenRelationInside;
            XCTAssertTrue(outside,@"The actual screen coordinate must be outside the transformed popover exclusion");
            XCTAssertTrue(insideWindow,@"The actual screen coordinate must remain inside the transformed host window");
            CGPoint reportedCoordinates[5]={zero,oneX,oneY,farCorner,actual};CGRect screenEnvelope;
            TCPickerScreenEnvelope envelopeKind=TCPickerChooseScreenEnvelope(screenContext,reportedCoordinates,&screenEnvelope);
            XCTAssertNotEqual(envelopeKind,TCPickerEnvelopeInvalid,@"All four basis corners and target must fit one complete reported screen envelope");
            if (envelopeKind==TCPickerEnvelopeInvalid) return;
            BOOL unchanged=CGRectEqualToRect(windowElement.frame,window) && CGRectEqualToRect(popover.frame,picker);
            XCTAssertTrue(unchanged,@"The measured window and popover must remain unchanged before the single tap");
            if (!affine || !targetMatches || !outside || !insideWindow || !unchanged) return;
            // Coordinates are dynamic. Verify the final value against the same
            // selected envelope, then recheck the recorded orientation and both bounds.
            CGPoint finalPoint=target.screenPoint;
            reportedCoordinates[4]=finalPoint;
            BOOL finalSafe=TCPickerScreenContainsCoordinates(screenEnvelope,reportedCoordinates,5) &&
                fabs(finalPoint.x-expected.x)<=1 && fabs(finalPoint.y-expected.y)<=1 &&
                TCPickerScreenPointRelation(map,exclusion,finalPoint)==TCPickerScreenRelationOutside &&
                TCPickerScreenPointRelation(map,CGRectInset(window,20,20),finalPoint)==TCPickerScreenRelationInside;
            UIDeviceOrientation finalOrientation=XCUIDevice.sharedDevice.orientation;
            TCPickerScreenContext finalContext={(long)finalOrientation,UIDeviceOrientationIsLandscape(finalOrientation),UIScreen.mainScreen.bounds,UIScreen.mainScreen.fixedCoordinateSpace.bounds};
            BOOL contextStable=TCPickerScreenContextStable(screenContext,finalContext);
            NSLog(@"PHOTO_PICKER_SCREEN_ENVELOPE kind=%d bounds=%@ finalPoint=%@ finalOrientation=%ld finalCurrent=%@ finalFixed=%@ stable=%d",envelopeKind,NSStringFromCGRect(screenEnvelope),NSStringFromCGPoint(finalPoint),finalContext.orientation,NSStringFromCGRect(finalContext.currentBounds),NSStringFromCGRect(finalContext.fixedBounds),contextStable);
            XCTAssertTrue(finalSafe,@"The final coordinate must remain safe in the same verified physical-screen envelope");
            XCTAssertTrue(contextStable,@"Recorded landscape orientation and both reported screen bounds must remain stable before tapping");
            if (!finalSafe || !contextStable) return;
            NSLog(@"PHOTO_PICKER_DISMISS window=%@ presentation=%@ screenPoint=%@",NSStringFromCGRect(window),NSStringFromCGRect(picker),NSStringFromCGPoint(finalPoint));
            [target tap];dismissedPopover=YES;
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
- (void)testCancelPhotoLoadingRetainsTheCurrentCanvasAndPalette {
    [self.app terminate];
    self.app.launchArguments=[self.app.launchArguments arrayByAddingObject:@"--ui-test-delay-photo-import"];
    [self.app launch];[self importFixture];
    [self.app.buttons[@"saveColor"] tap];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    NSString *selected=self.app.staticTexts[@"sampledColor"].label;
    [self choosePhoto];
    XCUIElement *photo=[self.app.images matchingPredicate:[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"]].firstMatch;
    XCTAssertTrue([photo waitForExistenceWithTimeout:15]);[photo tap];
    XCUIElement *cancel=self.app.buttons[@"photo.import.cancel"].firstMatch;
    XCTAssertTrue([cancel waitForExistenceWithTimeout:5]);XCTAssertTrue(cancel.hittable);[cancel tap];
    [self assertPresentationDisappears:cancel];
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,1u);
    XCTestExpectation *late=[self expectationWithDescription:@"The delayed provider-start boundary has elapsed"];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,9*NSEC_PER_SEC),dispatch_get_main_queue(),^{ [late fulfill]; });
    [self waitForExpectations:@[late] timeout:10];
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    XCTAssertFalse(self.app.buttons[@"photo.import.cancel"].firstMatch.exists);
    XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,1u);
}
- (void)testLargestTextNativePaletteAndCanvasControls {
    [self.app terminate];self.app.launchArguments=[self.app.launchArguments arrayByAddingObjectsFromArray:@[@"--ui-test-dark",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"]];[self.app launch];
    XCUIElement *sources=self.app.scrollViews[@"sourceControls"];
    for (NSString *identifier in @[@"choosePhoto",@"takePhoto",@"liveColor",@"palette.import.open",@"watch.inbox.open"]) {
        XCUIElement *button=self.app.buttons[identifier];
        for (NSUInteger i=0;i<5 && (!button.hittable || !CGRectContainsRect(sources.frame,CGRectInset(button.frame,1,1)));i++) [self scrollTowardElement:button inScroll:sources];
        XCTAssertTrue(button.hittable,@"%@",self.app.debugDescription);
        XCTAssertGreaterThanOrEqual(button.frame.size.height,44);
    }
    for (NSUInteger i=0;i<5 && !self.app.buttons[@"choosePhoto"].hittable;i++) [self scrollTowardElement:self.app.buttons[@"choosePhoto"] inScroll:sources];
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
    XCTAssertFalse(self.app.images[@"sampleImage"].exists,@"Cancelling Photos must not import an image or replace the live canvas");
    XCTNSPredicateExpectation *resumed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'not available'"] object:self.app.staticTexts[@"cameraStatus"]];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[resumed] timeout:5],XCTWaiterResultCompleted,@"Popover dismissal must leave the paused state: %@",self.app.debugDescription);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];[self.app activate];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"].label containsString:@"not available"]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self importFixture];
    XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
}
- (void)testFullScreenPaletteReviewRetainsPhotoAndKeyboardState {
    [self importFixture];
    [self.app.images[@"sampleImage"] tap];
    [self.app typeKey:@"+" modifierFlags:0];
    NSString *selected=self.app.staticTexts[@"sampledColor"].label;
    NSString *marker=self.app.images[@"sampleMarker"].value;
    CGFloat imageWidth=self.app.images[@"sampleImage"].frame.size.width;
    [self pastePalette:@"[\"#112233\",\"#112233\"]" app:self.app];
    [self verifyPaletteRows:@[@"#112233",@"#112233"] app:self.app];
    XCUIElement *close=self.app.buttons[@"palette.import.close"];[self tapReadyPaletteElement:close timeout:5];[self assertPresentationDisappears:close];
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0u,@"Cancel preserves the palette");
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    XCTAssertEqualObjects(self.app.images[@"sampleMarker"].value,marker);
    XCTAssertEqualWithAccuracy(self.app.images[@"sampleImage"].frame.size.width,imageWidth,2);
    [self pastePalette:@"[\"#112233\",\"#112233\"]" app:self.app];
    [self verifyPaletteRows:@[@"#112233",@"#112233"] app:self.app];
    [self tapReadyPaletteElement:self.app.buttons[@"palette.import.accept"] timeout:5];[self assertPresentationDisappears:close];
    XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,2u,@"Dismissal refreshes the retained palette controller");
    for (NSUInteger index=0;index<2;index++) XCTAssertTrue([[self.app.tables[@"colorHistory"].cells elementBoundByIndex:index].label containsString:@"#112233"]);
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    [self openPaletteAction:@"watch.inbox.open" app:self.app];
    close=self.app.buttons[@"watch.inbox.close"];XCTAssertTrue([close waitForExistenceWithTimeout:5]);[self tapReadyPaletteElement:close timeout:5];[self assertPresentationDisappears:close];
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);
    XCTAssertEqualObjects(self.app.images[@"sampleMarker"].value,marker);
    [self.app typeKey:@"+" modifierFlags:0];
    XCTAssertGreaterThan(self.app.images[@"sampleImage"].frame.size.width,imageWidth,@"Photo keyboard focus returns after full-screen dismissal");
}
- (void)testFullScreenPaletteFlowsResumeLiveUnavailableState {
    [self.app.buttons[@"liveColor"] tap];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    NSArray *actions=@[@"palette.import.open",@"watch.inbox.open"];
    NSArray *closers=@[@"palette.import.close",@"watch.inbox.close"];
    for (NSUInteger index=0;index<actions.count;index++) {
        [self openPaletteAction:actions[index] app:self.app];
        XCUIElement *close=self.app.buttons[closers[index]];
        XCTAssertTrue([close waitForExistenceWithTimeout:5]);
        XCTAssertFalse(self.app.buttons[@"saveLiveColor"].hittable,@"Inactive live controls must not be actionable under the full-screen flow");
        if (index==1) { [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome];[self.app activate];XCTAssertTrue(close.hittable); }
        [self tapReadyPaletteElement:close timeout:5];[self assertPresentationDisappears:close];
        XCTNSPredicateExpectation *resumed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'not available'"] object:self.app.staticTexts[@"cameraStatus"]];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[resumed] timeout:5],XCTWaiterResultCompleted,@"Full-screen dismissal must release source suspension");
        XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
        XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0u);
    }
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
    @try {
        if (self.tcPaletteReadinessExpired) {
            // XCTest's internal teardown is outside this hook's control. Our code
            // must not request window recovery, new snapshots or termination now.
            NSLog(@"PALETTE_READINESS_TEARDOWN_OMITTED case=%@ originalFailurePreserved=1",self.name);
            [super tearDown]; return;
        }
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
    } @finally {
        if (self.failClosedInterruption) [self removeUIInterruptionMonitor:self.failClosedInterruption];
        self.failClosedInterruption=nil;
    }
}
@end
