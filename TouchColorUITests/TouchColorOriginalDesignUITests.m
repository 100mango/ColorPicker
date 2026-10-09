#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#include <stdlib.h>
#include <stdio.h>
#include <math.h>

// This test-only recognizer identifies the seeded chart by image content, not
// picker ordering or the number of unrelated built-in simulator photos.
static BOOL TCDesignFixturePixel(UIImage *image, CGFloat nx, CGFloat ny, const uint8_t expected[3]) {
    CGSize size=CGSizeMake(image.size.width*image.scale,image.size.height*image.scale);
    if (!isfinite(size.width) || !isfinite(size.height) || size.width<1 || size.height<1 || size.width>4096 || size.height>4096) return NO;
    CGFloat x=MIN(floor(nx*size.width),size.width-1), y=MIN(floor(ny*size.height),size.height-1);
    uint8_t pixel[4]={0,0,0,0};
    CGColorSpaceRef space=CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context=CGBitmapContextCreate(pixel,1,1,8,4,space,(CGBitmapInfo)kCGImageAlphaPremultipliedLast|kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(space);
    if (!context) return NO;
    CGContextTranslateCTM(context,0,1); CGContextScaleCTM(context,1,-1);
    CGContextSetInterpolationQuality(context,kCGInterpolationNone);
    UIGraphicsPushContext(context);
    [image drawInRect:CGRectMake(-x,-y,size.width,size.height)];
    UIGraphicsPopContext(); CGContextRelease(context);
    if (pixel[3]!=255) return NO;
    for (NSUInteger channel=0;channel<3;channel++) {
        if (abs((int)pixel[channel]-(int)expected[channel])>8) return NO;
    }
    return YES;
}
static BOOL TCDesignFixtureThumbnail(UIImage *image) {
    if (!image) return NO;
    const uint8_t colors[6][3]={{255,0,0},{0,255,0},{0,0,255},{0,255,255},{255,0,255},{255,255,0}};
    const CGFloat columns[3]={0.125,0.5,0.875}, rows[2]={0.25,0.75};
    const CGPoint probes[5]={{0,0},{-0.02,-0.02},{0.02,-0.02},{-0.02,0.02},{0.02,0.02}};
    for (NSUInteger row=0;row<2;row++) for (NSUInteger column=0;column<3;column++) {
        for (NSUInteger probe=0;probe<5;probe++) {
            if (!TCDesignFixturePixel(image,columns[column]+probes[probe].x,rows[row]+probes[probe].y,colors[row*3+column])) return NO;
        }
    }
    return YES;
}
static UIImage *TCDesignRecognitionControl(BOOL mutate) {
    UIGraphicsImageRendererFormat *format=UIGraphicsImageRendererFormat.defaultFormat; format.scale=1; format.preferredRange=UIGraphicsImageRendererFormatRangeStandard;
    return [[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(300,200) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {
        NSArray<UIColor *> *colors=@[UIColor.redColor,UIColor.greenColor,UIColor.blueColor,UIColor.cyanColor,UIColor.magentaColor,mutate ? UIColor.blackColor : UIColor.yellowColor];
        for (NSUInteger index=0;index<6;index++) {
            [colors[index] setFill]; [context fillRect:CGRectMake((index%3)*100,(index/3)*100,100,100)];
        }
    }];
}

static BOOL TCDesignFiniteRect(CGRect frame) {
    return isfinite(frame.origin.x) && isfinite(frame.origin.y) && isfinite(frame.size.width) && isfinite(frame.size.height) && frame.size.width>0 && frame.size.height>0;
}

// Separate original-product regression suite. No production fixture button,
// sidebar, redesigned home history, or direct home privacy action is required.
@interface TouchColorOriginalDesignUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic, strong) id<NSObject> failClosedInterruption;
@property (nonatomic) BOOL recordingFailure;
@end

@implementation TouchColorOriginalDesignUITests
- (void)setUp {
    [super setUp];
    self.continueAfterFailure=NO;
    self.failClosedInterruption=[self addUIInterruptionMonitorWithDescription:@"Unexpected prompt must not receive implicit consent" handler:^BOOL(XCUIElement *alert) {
        fputs("ORIGINAL_DESIGN_UNHANDLED_SYSTEM_PROMPT; no consent action taken\n",stderr);
        abort();
    }];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    self.app=[XCUIApplication new];
}
- (void)tearDown {
    [self.app terminate];
    if (self.failClosedInterruption) [self removeUIInterruptionMonitor:self.failClosedInterruption];
    self.failClosedInterruption=nil;
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [super tearDown];
}
- (void)recordIssue:(XCTIssue *)issue {
    if (!self.recordingFailure) {
        self.recordingFailure=YES;
        [self recordAppPickerTrace:@"failure"];
        NSData *png=UIImagePNGRepresentation(XCUIScreen.mainScreen.screenshot.image);
        if (png.length && png.length<=2*1024*1024) {
            XCTAttachment *attachment=[XCTAttachment attachmentWithData:png uniformTypeIdentifier:@"public.png"];
            attachment.name=@"original-design-failure"; attachment.lifetime=XCTAttachmentLifetimeKeepAlways;
            [self addAttachment:attachment];
        }
        NSLog(@"ORIGINAL_DESIGN_FAILURE %@\n%@",issue.compactDescription,self.app.debugDescription);
    }
    [super recordIssue:issue];
}
- (void)capture:(NSString *)name {
    NSData *png=UIImagePNGRepresentation(XCUIScreen.mainScreen.screenshot.image);
    XCTAssertGreaterThan(png.length,0u);
    XCTAssertLessThanOrEqual(png.length,2*1024*1024u,@"Each lossless visual-review image has a fixed evidence budget");
    XCTAttachment *attachment=[XCTAttachment attachmentWithData:png uniformTypeIdentifier:@"public.png"];
    attachment.name=name; attachment.lifetime=XCTAttachmentLifetimeKeepAlways; [self addAttachment:attachment];
}
- (void)launchReset:(BOOL)reset extra:(NSArray<NSString *> *)extra {
    NSMutableArray *arguments=[NSMutableArray arrayWithArray:@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US",@"--ui-test-picker-trace"]];
    if (reset) [arguments addObject:@"--ui-test-reset"];
    [arguments addObjectsFromArray:extra ?: @[]];
    self.app.launchArguments=arguments;
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"original.picker"] waitForExistenceWithTimeout:10]);
    XCTAssertTrue(self.app.buttons[@"original.picker"].selected);
    [self assertHomeUsable];
}
- (void)assertHomeUsable {
    XCUIElement *choose=self.app.buttons[@"choosePhoto"], *take=self.app.buttons[@"takePhoto"], *live=self.app.buttons[@"liveColor"];
    XCTAssertTrue([choose waitForExistenceWithTimeout:5]);
    CGRect window=self.app.windows.firstMatch.frame;
    // Each frame read crosses the automation boundary. Capture each once for
    // this settled home state; retain every original geometry assertion below.
    CGRect chooseFrame=choose.frame, takeFrame=take.frame, liveFrame=live.frame;
    CGRect libraryFrame=self.app.buttons[@"original.library"].frame;
    NSArray<XCUIElement *> *controls=@[choose,take,live];
    NSArray<NSValue *> *frames=@[[NSValue valueWithCGRect:chooseFrame],[NSValue valueWithCGRect:takeFrame],[NSValue valueWithCGRect:liveFrame]];
    for (NSUInteger index=0;index<controls.count;index++) {
        XCUIElement *control=controls[index]; CGRect frame=frames[index].CGRectValue;
        XCTAssertTrue(control.enabled); XCTAssertTrue(control.hittable);
        XCTAssertTrue(CGRectContainsRect(window,CGRectInset(frame,1,1)),@"All three original actions must fit the visible window");
        XCTAssertGreaterThanOrEqual(frame.size.height,44);
    }
    XCTAssertEqualWithAccuracy(chooseFrame.size.width,takeFrame.size.width,1);
    XCTAssertEqualWithAccuracy(takeFrame.size.width,liveFrame.size.width,1);
    XCTAssertLessThan(CGRectGetMaxY(chooseFrame),CGRectGetMidY(takeFrame));
    XCTAssertLessThan(CGRectGetMaxY(takeFrame),CGRectGetMidY(liveFrame));
    XCTAssertLessThan(CGRectGetMaxY(libraryFrame),CGRectGetMinY(chooseFrame));
    XCTAssertTrue(!self.app.buttons[@"privacyPolicy"].exists || !self.app.buttons[@"privacyPolicy"].hittable,@"Privacy must remain reachable through Library/About, not become a primary home action");
    XCTAssertTrue(!self.app.buttons[@"palette.import.open"].exists || !self.app.buttons[@"palette.import.open"].hittable);
}
- (void)tap:(NSString *)identifier {
    XCUIElement *button=self.app.buttons[identifier];
    XCTAssertTrue([button waitForExistenceWithTimeout:5],@"Missing actionable control %@",identifier);
    XCTAssertTrue(button.enabled); XCTAssertTrue(button.hittable); [button tap];
}
- (XCUIElement *)readout {
    XCUIElement *value=[self.app descendantsMatchingType:XCUIElementTypeAny][@"sampledColor"];
    XCTAssertTrue([value waitForExistenceWithTimeout:5]); return value;
}
- (void)assertLabel:(XCUIElement *)element contains:(NSString *)text {
    XCTNSPredicateExpectation *ready=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS[c] %@",text] object:element];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[ready] timeout:10],XCTWaiterResultCompleted);
}
- (void)waitAbsent:(XCUIElement *)element {
    XCTNSPredicateExpectation *closed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:element];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[closed] timeout:10],XCTWaiterResultCompleted);
}
- (XCUIElement *)openLibrary {
    [self tap:@"original.library"];
    XCTAssertTrue(self.app.buttons[@"original.library"].selected);
    XCUIElement *table=self.app.tables[@"colorHistory"];
    XCTAssertTrue([table waitForExistenceWithTimeout:5]);
    XCTAssertTrue(!self.app.buttons[@"choosePhoto"].exists || !self.app.buttons[@"choosePhoto"].hittable);
    return table;
}
- (void)revealFooter:(NSString *)identifier inTable:(XCUIElement *)table {
    XCUIElement *button=self.app.buttons[identifier];
    for (NSUInteger attempt=0;attempt<5 && !button.hittable;attempt++) [table swipeUp];
    XCTAssertTrue(button.hittable,@"The secondary library action must remain reachable by normal scrolling");
}
- (void)selectOnlySeededPhoto {
    XCTAssertTrue(TCDesignFixtureThumbnail(TCDesignRecognitionControl(NO)));
    XCTAssertFalse(TCDesignFixtureThumbnail(TCDesignRecognitionControl(YES)),@"A changed color must never be accepted as the fixture");
    [self tap:@"choosePhoto"];
    if (![self waitForPhotoPickerSurface]) return;
    // Fresh iOS27 simulators contain six stock photos before the one seeded
    // chart is added. A label/date or first-row position alone is not identity.
    NSPredicate *selector=[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"];
    XCUIElementQuery *photos=[self.app.images matchingPredicate:selector];
    XCTAssertTrue([photos.firstMatch waitForExistenceWithTimeout:15]);
    NSArray<XCUIElement *> *candidates=photos.allElementsBoundByIndex;
    XCTAssertLessThanOrEqual(candidates.count,16u,@"Fixture discovery is bounded to the reviewed disposable-library inventory");
    if (candidates.count>16) return;
    NSMutableArray<XCUIElement *> *matches=[NSMutableArray new];
    for (XCUIElement *candidate in candidates) {
        if (!candidate.hittable) continue;
        BOOL match=TCDesignFixtureThumbnail(candidate.screenshot.image);
        NSLog(@"ORIGINAL_FIXTURE_CONTENT_CANDIDATE label=%@ frame=%@ sixColorGrid=%d",candidate.label,NSStringFromCGRect(candidate.frame),match);
        if (match) [matches addObject:candidate];
    }
    XCTAssertEqual(matches.count,1u,@"Exactly one independently verified six-color chart must match; never choose an arbitrary first photo");
    if (matches.count!=1) return;
    XCUIElement *fixture=matches.firstObject;
    BOOL actionable=fixture.hittable;
    XCTAssertTrue(actionable);
    if (!actionable) return;
    BOOL verified=TCDesignFixtureThumbnail(fixture.screenshot.image);
    XCTAssertTrue(verified,@"Recheck the selected content immediately before tapping");
    if (!verified) return;
    NSLog(@"ORIGINAL_FIXTURE_CONTENT_SELECTED label=%@ frame=%@ probes=30 tolerance=8",fixture.label,NSStringFromCGRect(fixture.frame));
    [fixture tap];
}
- (void)sampleAndSaveRed {
    [self selectOnlySeededPhoto];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:15]);
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    [self tap:@"sampleCenter"];
    [self assertLabel:[self readout] contains:@"#ff00ff"];
    XCUIElement *image=self.app.images[@"sampleImage"];
    XCTAssertTrue(image.hittable);
    [[image coordinateWithNormalizedOffset:CGVectorMake(0.15,0.25)] tap];
    [self assertLabel:[self readout] contains:@"#ff0000"];
    [self tap:@"saveColor"];
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled,@"One unchanged sample cannot be accidentally saved twice");
}
- (void)returnFromCanvas {
    [self tap:@"original.back"];
    [self assertHomeUsable];
}
- (void)assertRedHistory:(XCUIElement *)table count:(NSUInteger)count {
    XCTNSPredicateExpectation *rows=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id unused,NSDictionary *bindings) {
        return table.cells.count==count;
    }] object:nil];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[rows] timeout:5],XCTWaiterResultCompleted);
    if (count) {
        XCUIElement *red=[[table descendantsMatchingType:XCUIElementTypeAny] matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS[c] '#ff0000'"]].firstMatch;
        XCTAssertTrue([red waitForExistenceWithTimeout:5],@"Stored value must remain the actual sampled color");
    }
}
- (void)revealPrivacyAction:(XCUIElement *)element inScrollView:(XCUIElement *)scroll {
    // This footer has its own short viewport. The retained largest-text Compact
    // trace needed a sixth drag; allow at most seven, leaving all other controls
    // on their original five-drag policy.
    CGRect viewport=scroll.frame, target=element.frame;
    BOOL hittable=element.hittable;
    for (NSUInteger attempt=0;attempt<7 && (!hittable || !CGRectContainsRect(viewport,CGRectInset(target,1,1)));attempt++) {
        CGFloat limit=CGRectGetHeight(viewport)*0.45;
        CGFloat distance=MAX(-limit,MIN(limit,CGRectGetMidY(target)-CGRectGetMidY(viewport)));
        XCUICoordinate *start=[[scroll coordinateWithNormalizedOffset:CGVectorMake(0,0.5)] coordinateWithOffset:CGVectorMake(8,0)];
        XCUICoordinate *end=[start coordinateWithOffset:CGVectorMake(0,-distance)];
        NSLog(@"PRIVACY_ACTION_SCROLL attempt=%lu frame=%@ viewport=%@ gutterX=8 delta=%.2f",(unsigned long)attempt,NSStringFromCGRect(target),NSStringFromCGRect(viewport),distance);
        [start pressForDuration:0.05 thenDragToCoordinate:end withVelocity:100 thenHoldForDuration:0.15];
        viewport=scroll.frame;target=element.frame;hittable=element.hittable;
    }
    NSLog(@"PRIVACY_ACTION_VISIBLE frame=%@ viewport=%@ hittable=%d",NSStringFromCGRect(target),NSStringFromCGRect(viewport),hittable);
    XCTAssertTrue(hittable,@"The independent native privacy action must remain live hittable");
    XCTAssertTrue(CGRectContainsRect(viewport,CGRectInset(target,1,1)),@"The entire control must remain inside its scroll viewport");
}
- (void)assertLocalPolicyBody {
    XCUIElement *chinese=self.app.textViews[@"privacy.body.zh-Hans"];
    XCUIElement *english=self.app.textViews[@"privacy.body.en"];
    XCTAssertTrue([chinese waitForExistenceWithTimeout:30],@"The approved Chinese policy must render natively");
    XCTAssertTrue([english waitForExistenceWithTimeout:30],@"The approved English policy must render natively");
    XCTAssertTrue([(NSString *)chinese.value containsString:@"Celluloid、QRCatcher 和 TouchColor"]);
    XCTAssertTrue([(NSString *)english.value containsString:@"Celluloid, QRCatcher, and TouchColor"]);
    XCTAssertTrue([(NSString *)chinese.value containsString:@"100mango@gmail.com"]);
    XCTAssertTrue([(NSString *)english.value containsString:@"100mango@gmail.com"]);
}
- (void)recordAppPickerTrace:(NSString *)phase {
    XCUIElement *source=self.app.buttons[@"choosePhoto"];
    id value=source.exists ? source.value : nil;
    BOOL available=[value isKindOfClass:NSString.class] && [(NSString *)value containsString:@"TC_PICKER_TRACE"];
    NSLog(@"ORIGINAL_PICKER_APP_TRACE phase=%@ evidence=%@ value=%@",phase,available ? @"available" : @"missing",available ? value : @"AX may hide the source; missing is not proof the delegate was not called");
}
- (BOOL)waitForPhotoPickerSurface {
    if (UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad) {
        XCUIElement *popover=[self.app descendantsMatchingType:XCUIElementTypePopover].firstMatch;
        XCUIElement *region=self.app.otherElements[@"PopoverDismissRegion"].firstMatch;
        if (![popover waitForExistenceWithTimeout:10] || ![region waitForExistenceWithTimeout:10]) {
            XCTFail(@"The original iPad picker must expose its native popover and dismissal region");
            return NO;
        }
    } else if (![self.app.buttons[@"Cancel"].firstMatch waitForExistenceWithTimeout:10]) {
        XCTFail(@"The phone picker must expose its native Cancel button");
        return NO;
    }
    if (![self.app.scrollViews[@"photosView_content_scroll_view"] waitForExistenceWithTimeout:10]) {
        XCTFail(@"The real Photos gallery must be available before selection or dismissal");
        return NO;
    }
    return YES;
}
- (void)dismissPopoverOnceWithAttachment:(NSString *)name {
    XCUIElement *popover=[self.app descendantsMatchingType:XCUIElementTypePopover].firstMatch;
    XCUIElement *region=self.app.otherElements[@"PopoverDismissRegion"].firstMatch;
    // Every caller has already observed the real Photos gallery, popover and
    // native dismissal region. Keep one screenshot, then let XCTest compute
    // the region's current hittable point through its public element action.
    // No prior frame or hittability read can guarantee the later event result.
    [self capture:name];
    NSLog(@"ORIGINAL_PICKER_POPOVER_SINGLE_TAP uptime=%.6f method=element-hit-point phase=%@",NSProcessInfo.processInfo.systemUptime,name);
    [region tap];
    // An action invocation is never sufficient evidence of cancellation.
    [self waitAbsent:popover];
    XCTAssertFalse(region.exists,@"The native dismissal region must disappear with its popover");
    XCTAssertFalse(self.app.scrollViews[@"photosView_content_scroll_view"].exists,@"The dismissed popover must not retain its gallery");
    XCTAssertTrue(self.app.buttons[@"original.picker"].selected,@"Cancellation must retain the original source tab");
    XCTAssertFalse(self.app.buttons[@"sampleCenter"].exists,@"An outside dismissal must not select a photo or open a canvas");
    XCTAssertFalse(self.app.buttons[@"photo.import.cancel"].exists,@"An outside dismissal must not start a photo import");
    XCTAssertEqual(self.app.alerts.count,0u,@"An outside dismissal must not activate an underlying camera action");
    [self recordAppPickerTrace:@"after-popover-dismiss"];
}
- (void)dismissPhotoPickerOnceWithAttachment:(NSString *)name {
    if (UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad) {
        [self dismissPopoverOnceWithAttachment:name];
    } else {
        [self cancelPickerOnce:self.app.buttons[@"Cancel"].firstMatch attachment:name];
    }
}
- (void)cancelPickerOnce:(XCUIElement *)cancel attachment:(NSString *)name {
    if (![cancel waitForExistenceWithTimeout:5]) {
        XCTFail(@"Cancel must exist before observing its frame");
        return;
    }
    BOOL enabled=cancel.enabled, hittable=cancel.hittable;
    if (!enabled || !hittable) {
        XCTFail(@"Cancel must be enabled and hittable before exactly one tap");
        return;
    }
    // AX reads can each take seconds. Cache the window and sample the actual
    // frame only twice, around evidence we already need, rather than polling
    // five remote properties inside an artificial five-second settling gate.
    CGRect window=self.app.windows.firstMatch.frame;
    CGRect firstFrame=cancel.frame;
    NSTimeInterval firstSample=NSProcessInfo.processInfo.systemUptime;
    BOOL inside=firstFrame.size.width>0 && firstFrame.size.height>0 && CGRectContainsRect(window,CGRectInset(firstFrame,1,1));
    if (!inside) {
        XCTFail(@"Cancel must have a nonempty frame inside the cached window");
        return;
    }
    [self capture:name];
    [self recordAppPickerTrace:@"before-cancel"];
    NSTimeInterval secondSample=NSProcessInfo.processInfo.systemUptime;
    CGRect secondFrame=cancel.frame;
    BOOL stable=CGRectEqualToRect(firstFrame,secondFrame) && secondSample-firstSample>=0.25;
    if (!stable) {
        XCTFail(@"Cancel frame must be unchanged across two samples at least 0.25 seconds apart: %@ -> %@, elapsed=%.6f",NSStringFromCGRect(firstFrame),NSStringFromCGRect(secondFrame),secondSample-firstSample);
        return;
    }
    NSLog(@"ORIGINAL_PICKER_CANCEL_SINGLE_TAP uptime=%.6f frame=%@ sampleGap=%.6f",NSProcessInfo.processInfo.systemUptime,NSStringFromCGRect(secondFrame),secondSample-firstSample);
    [cancel tap];
    [self waitAbsent:cancel];
    [self recordAppPickerTrace:@"after-cancel"];
}
- (void)testPhotosLibraryBootstrapCanCancelWithoutSelecting {
    [self launchReset:YES extra:nil];
    [self tap:@"choosePhoto"];
    if (![self waitForPhotoPickerSurface]) return;
    [self dismissPhotoPickerOnceWithAttachment:@"bootstrap-picker-ready"];
    [self assertHomeUsable];
    XCTAssertFalse(self.app.buttons[@"sampleCenter"].exists);
    XCTAssertFalse(self.app.buttons[@"photo.import.cancel"].exists);
    [self assertRedHistory:[self openLibrary] count:0];
}
- (void)testOriginalHomeTabsAndRepeatedPhotoPickerCancellation {
    [self launchReset:YES extra:nil];
    [self capture:@"01-original-home"];
    for (NSUInteger attempt=0;attempt<2;attempt++) {
        [self tap:@"choosePhoto"];
        if (![self waitForPhotoPickerSurface]) return;
        [self dismissPhotoPickerOnceWithAttachment:[NSString stringWithFormat:@"picker-cancel-before-%lu",(unsigned long)attempt+1]]; [self assertHomeUsable];
    }
    XCUIElement *table=[self openLibrary];
    [self assertRedHistory:table count:0];
    [self revealFooter:@"original.about" inTable:table];
    [self capture:@"02-original-empty-library"];
    [self tap:@"original.picker"]; [self assertHomeUsable];
}
- (void)deleteOnlySavedColor:(XCUIElement *)table {
    [self assertRedHistory:table count:1];
    [table.cells.firstMatch swipeLeft];
    XCUIElement *delete=self.app.buttons[@"Delete"].firstMatch;
    XCTAssertTrue([delete waitForExistenceWithTimeout:5]); XCTAssertTrue(delete.hittable); [delete tap];
    [self assertRedHistory:table count:0];
}
- (void)testRealPhotoSaveRelaunchDelete {
    // Independent real-photo setup; no state is inherited from another test.
    [self launchReset:YES extra:nil];
    [self sampleAndSaveRed];
    [self capture:@"03-original-photo-sampled"];
    [self returnFromCanvas];
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:1];
    [self capture:@"04-original-saved-library"];
    [self.app terminate]; [self launchReset:NO extra:nil];
    table=[self openLibrary]; [self assertRedHistory:table count:1];
    [self deleteOnlySavedColor:table];
    [self.app terminate]; [self launchReset:NO extra:nil];
    [self assertRedHistory:[self openLibrary] count:0];
}
- (void)testDelayedImportCancellationPreservesSavedColor {
    // Prime the actual first import before exercising the existing second-
    // provider delay. This case owns its initial and final synthetic data.
    [self launchReset:YES extra:@[@"--ui-test-delay-photo-import"]];
    [self sampleAndSaveRed]; [self returnFromCanvas];
    [self selectOnlySeededPhoto];
    [self tap:@"photo.import.cancel"];
    [self assertHomeUsable];
    XCTNSPredicateExpectation *late=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == true"] object:self.app.buttons[@"sampleCenter"]];
    late.inverted=YES;
    XCTAssertEqual([XCTWaiter waitForExpectations:@[late] timeout:9],XCTWaiterResultCompleted,@"The cancelled delayed provider must never reopen a canvas");
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:1];
    [self deleteOnlySavedColor:table];
}
- (void)testNativePrivacyContentAndActionsFromEmptyLibrary {
    [self launchReset:YES extra:nil];
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:0];
    [self revealFooter:@"original.about" inTable:table]; [self tap:@"original.about"];
    XCTAssertTrue([self.app.buttons[@"original.about.close"] waitForExistenceWithTimeout:5]);
    [self tap:@"privacyPolicy"];
    [self assertLocalPolicyBody];
    XCUIElement *content=self.app.scrollViews[@"privacy.content"];
    XCUIElement *actions=self.app.scrollViews[@"privacy.actions"];
    for (NSString *identifier in @[@"privacy.contact",@"privacy.externalPolicy"]) {
        XCUIElement *button=actions.buttons[identifier];
        XCTAssertTrue([button waitForExistenceWithTimeout:5]);
        [self revealPrivacyAction:button inScrollView:actions];
        XCTAssertTrue(button.enabled); XCTAssertTrue(button.hittable);
        // Do not open Mail/Safari in this visual and navigation gate. The exact
        // release hosted tests verify the guarded external opener separately.
    }
    XCTAssertFalse(self.app.staticTexts[@"privacy.externalError"].exists);
    [self capture:@"05-secondary-privacy-policy"];
    [self tap:@"privacy.close"]; [self waitAbsent:content];
    XCTAssertTrue(self.app.buttons[@"original.library"].selected);
    [self assertRedHistory:self.app.tables[@"colorHistory"] count:0];
    [self tap:@"original.picker"]; [self assertHomeUsable];
}
- (void)testNativePrivacyBackgroundClosePreservesRealSavedColor {
    [self launchReset:YES extra:nil];
    [self sampleAndSaveRed]; [self returnFromCanvas];
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:1];
    [self revealFooter:@"original.about" inTable:table]; [self tap:@"original.about"];
    XCTAssertTrue([self.app.buttons[@"original.about.close"] waitForExistenceWithTimeout:5]);
    [self tap:@"privacyPolicy"];
    XCUIElement *content=self.app.scrollViews[@"privacy.content"];
    XCTAssertTrue([content waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.buttons[@"privacy.close"] waitForExistenceWithTimeout:5]);
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome]; [self.app activate];
    XCTAssertTrue([content waitForExistenceWithTimeout:5],@"Foreground restoration must retain the open native policy");
    [self tap:@"privacy.close"];
    [self waitAbsent:content];
    XCTAssertTrue(self.app.buttons[@"original.library"].selected);
    [self assertRedHistory:self.app.tables[@"colorHistory"] count:1];
    [self revealFooter:@"original.about" inTable:self.app.tables[@"colorHistory"]];
    [self tap:@"original.about"];
    [self tap:@"original.about.close"];
    [self assertRedHistory:self.app.tables[@"colorHistory"] count:1];
    [self deleteOnlySavedColor:self.app.tables[@"colorHistory"]];
    [self tap:@"original.picker"]; [self assertHomeUsable];
}
- (void)testLiveUnavailableCannotSaveAndReturnsToOriginalHome {
    [self launchReset:YES extra:nil];
    [self tap:@"takePhoto"];
    XCUIElement *unavailable=[self.app.alerts.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS 'camera is not available'"]].firstMatch;
    XCTAssertTrue([unavailable waitForExistenceWithTimeout:5],@"This gate runs only on an owned simulator without camera hardware");
    XCUIElement *okay=self.app.alerts.buttons[@"OK"];
    XCTAssertTrue(okay.hittable); [okay tap]; [self assertHomeUsable];
    [self tap:@"liveColor"];
    XCUIElement *status=self.app.staticTexts[@"cameraStatus"];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]); [self assertLabel:status contains:@"not available"];
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self capture:@"06-original-live-unavailable"];
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome]; [self.app activate];
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self returnFromCanvas];
    [self assertRedHistory:[self openLibrary] count:0];
}
@end
