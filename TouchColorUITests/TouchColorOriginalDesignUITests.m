#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#include <stdlib.h>
#include <stdio.h>

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
    NSMutableArray *arguments=[NSMutableArray arrayWithArray:@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"]];
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
    for (XCUIElement *control in @[choose,take,live]) {
        XCTAssertTrue(control.enabled); XCTAssertTrue(control.hittable);
        XCTAssertTrue(CGRectContainsRect(window,CGRectInset(control.frame,1,1)),@"All three original actions must fit the visible window");
        XCTAssertGreaterThanOrEqual(control.frame.size.height,44);
    }
    XCTAssertEqualWithAccuracy(choose.frame.size.width,take.frame.size.width,1);
    XCTAssertEqualWithAccuracy(take.frame.size.width,live.frame.size.width,1);
    XCTAssertLessThan(CGRectGetMaxY(choose.frame),CGRectGetMidY(take.frame));
    XCTAssertLessThan(CGRectGetMaxY(take.frame),CGRectGetMidY(live.frame));
    XCTAssertLessThan(CGRectGetMaxY(self.app.buttons[@"original.library"].frame),CGRectGetMinY(choose.frame));
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
    XCTAssertFalse(self.app.buttons[@"choosePhoto"].hittable);
    return table;
}
- (void)revealFooter:(NSString *)identifier inTable:(XCUIElement *)table {
    XCUIElement *button=self.app.buttons[identifier];
    for (NSUInteger attempt=0;attempt<5 && !button.hittable;attempt++) [table swipeUp];
    XCTAssertTrue(button.hittable,@"The secondary library action must remain reachable by normal scrolling");
}
- (void)selectOnlySeededPhoto {
    [self tap:@"choosePhoto"];
    XCUIElement *cancel=self.app.buttons[@"Cancel"].firstMatch;
    XCTAssertTrue([cancel waitForExistenceWithTimeout:10]);
    // Both selectors were observed in the release suite. The runner creates a
    // new disposable simulator and seeds exactly one synthetic 300x200 image.
    NSPredicate *selector=[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"];
    XCUIElementQuery *photos=[self.app.images matchingPredicate:selector];
    XCTAssertTrue([photos.firstMatch waitForExistenceWithTimeout:15]);
    XCTAssertEqual(photos.count,1u,@"Ambiguous picker contents must fail instead of selecting an arbitrary photo");
    XCTAssertTrue(photos.firstMatch.hittable); [photos.firstMatch tap];
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
- (void)testOriginalHomeTabsAndRepeatedPhotoPickerCancellation {
    [self launchReset:YES extra:nil];
    [self capture:@"01-original-home"];
    for (NSUInteger attempt=0;attempt<2;attempt++) {
        [self tap:@"choosePhoto"];
        XCUIElement *cancel=self.app.buttons[@"Cancel"].firstMatch;
        XCTAssertTrue([cancel waitForExistenceWithTimeout:10]); XCTAssertTrue(cancel.hittable);
        [cancel tap]; [self waitAbsent:cancel]; [self assertHomeUsable];
    }
    XCUIElement *table=[self openLibrary];
    [self assertRedHistory:table count:0];
    [self revealFooter:@"original.about" inTable:table];
    [self capture:@"02-original-empty-library"];
    [self tap:@"original.picker"]; [self assertHomeUsable];
}
- (void)testRealPhotoSaveRelaunchDeleteAndDelayedImportCancel {
    [self launchReset:YES extra:@[@"--ui-test-delay-photo-import"]];
    [self sampleAndSaveRed];
    [self capture:@"03-original-photo-sampled"];
    [self returnFromCanvas];
    // The existing Debug seam delays only the second actual provider request.
    // It neither creates an image nor changes selection, decode, or cancellation.
    [self selectOnlySeededPhoto];
    [self tap:@"photo.import.cancel"];
    [self assertHomeUsable];
    XCTNSPredicateExpectation *late=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == true"] object:self.app.buttons[@"sampleCenter"]];
    late.inverted=YES;
    XCTAssertEqual([XCTWaiter waitForExpectations:@[late] timeout:9],XCTWaiterResultCompleted,@"The cancelled delayed provider must never reopen a canvas");
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:1];
    [self capture:@"04-original-saved-library"];
    [self.app terminate]; [self launchReset:NO extra:nil];
    table=[self openLibrary]; [self assertRedHistory:table count:1];
    [table.cells.firstMatch swipeLeft];
    XCUIElement *delete=self.app.buttons[@"Delete"].firstMatch;
    XCTAssertTrue([delete waitForExistenceWithTimeout:5]); XCTAssertTrue(delete.hittable); [delete tap];
    [self assertRedHistory:table count:0];
    [self.app terminate]; [self launchReset:NO extra:nil];
    [self assertRedHistory:[self openLibrary] count:0];
}
- (void)testNativePrivacyThroughLibraryAboutCloseAndDataPreservation {
    [self launchReset:YES extra:nil];
    [self sampleAndSaveRed]; [self returnFromCanvas];
    XCUIElement *table=[self openLibrary]; [self assertRedHistory:table count:1];
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
    [XCUIDevice.sharedDevice pressButton:XCUIDeviceButtonHome]; [self.app activate];
    [self tap:@"privacy.close"];
    [self waitAbsent:content];
    XCTAssertTrue(self.app.buttons[@"original.library"].selected);
    [self assertRedHistory:self.app.tables[@"colorHistory"] count:1];
    [self revealFooter:@"original.about" inTable:self.app.tables[@"colorHistory"]];
    [self tap:@"original.about"];
    [self tap:@"original.about.close"];
    [self assertRedHistory:self.app.tables[@"colorHistory"] count:1];
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
