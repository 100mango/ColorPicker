#include <stdlib.h>
#include <stdio.h>
#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#import "TCPaletteUIHelpers.h"
#import <math.h>

/// Official XCTest audits run as their own bounded CI stage on each supported simulator family.
@interface TouchColorAccessibilityUITests : XCTestCase
@property (nonatomic, strong) id<NSObject> failClosedInterruption;
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic) CGSize originalWindowSize;
@end
@implementation TouchColorAccessibilityUITests
- (void)setUp {
    [super setUp];
    // Install before launch; known dialog controls stay in their explicit tests.
    self.failClosedInterruption=[self addUIInterruptionMonitorWithDescription:@"Abort every unhandled system interruption" handler:^BOOL(XCUIElement *unusedAlert) {
        // No UI query or failure recorder can throw and reach XCTest's default handler.
        fputs("TOUCHCOLOR_UI_FAIL_CLOSED_ABORT class=TouchColorAccessibilityUITests; no alert action taken\n",stderr);
        abort();
    }];
    self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    XCUIDevice.sharedDevice.orientation=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad ? UIDeviceOrientationLandscapeLeft : UIDeviceOrientationPortrait;
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10]);
    NSString *sourceValue=[self.app.scrollViews[@"sourceControls"].value description];
    XCTAssertFalse([sourceValue containsString:@"offsetY="],@"Official audits must use the production accessibility tree without diagnostic values");
    [self assertEmptyHistoryDoesNotOverlapHeader];
}
- (void)assertEmptyHistoryDoesNotOverlapHeader {
    XCUIElement *message=self.app.staticTexts[@"history.empty"];
    // The primary column may intentionally be hidden in a compact detail window.
    if (!message.exists) return;
    XCUIElement *header=self.app.tables[@"colorHistory"].staticTexts[@"Saved Colors"].firstMatch;
    if (header.exists) XCTAssertFalse(CGRectIntersectsRect(header.frame,message.frame),@"Empty-state paragraph overlaps section header: %@ / %@",NSStringFromCGRect(message.frame),NSStringFromCGRect(header.frame));
}
- (void)recordAuditScreenshot:(NSString *)screen failure:(BOOL)failure {
    NSString *name=nil;
    if (failure) {
        NSDictionary *states=@{@"palette import review":@"import",@"palette import help":@"import-help",@"empty palette":@"empty",@"empty palette in actual compact iPad window":@"empty-compact",@"live camera unavailable":@"live",@"offline policy error in dark appearance":@"policy",@"sampled photo with numeric RGB and hex":@"photo",@"saved palette with numeric RGB and hex":@"saved"};
        if (states[screen]) name=[@"touchcolor-audit-failure-" stringByAppendingString:states[screen]];
    } else {
        if ([screen isEqualToString:@"sampled photo with numeric RGB and hex"]) name=@"touchcolor-mini-audit-photo-state";
        if ([screen isEqualToString:@"saved palette with numeric RGB and hex"]) name=@"touchcolor-mini-audit-saved-state";
        if ([screen isEqualToString:@"palette import review"]) name=@"touchcolor-palette-import-review";
        if ([screen isEqualToString:@"palette import help"]) name=@"touchcolor-palette-import-help";
    }
    if (!name) return;
    NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
    XCTAssertLessThanOrEqual(bytes.length,500*1024u);
    XCTAttachment *attachment=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
    attachment.name=name;attachment.lifetime=XCTAttachmentLifetimeKeepAlways;
    [self addAttachment:attachment];
}
- (void)auditScreen:(NSString *)screen {
    NSLog(@"ACCESSIBILITY_CHECKPOINT screen=%@ window=%@ deviceOrientation=%ld runnerPreferredContentSizeCategory=%@",screen,NSStringFromCGRect(self.app.windows.firstMatch.frame),(long)XCUIDevice.sharedDevice.orientation,UIApplication.sharedApplication.preferredContentSizeCategory);
    NSError *error=nil;
    __block BOOL recordedFailure=NO;
    BOOL passed=[self.app performAccessibilityAuditWithAuditTypes:XCUIAccessibilityAuditTypeAll issueHandler:^BOOL(XCUIAccessibilityAuditIssue *issue) {
        NSLog(@"ACCESSIBILITY_ISSUE screen=%@ type=%lu description=%@ detail=%@ element=%@",screen,(unsigned long)issue.auditType,issue.compactDescription,issue.detailedDescription,issue.element.debugDescription);
        if (!recordedFailure) {
            recordedFailure=YES;
            [self recordAuditScreenshot:screen failure:YES];
            NSLog(@"ACCESSIBILITY_FAILURE_GEOMETRY screen=%@ window=%@ runnerPreferredContentSizeCategory=%@",screen,NSStringFromCGRect(self.app.windows.firstMatch.frame),UIApplication.sharedApplication.preferredContentSizeCategory);
            NSLog(@"ACCESSIBILITY_FAILURE_HIERARCHY_BEGIN screen=%@\n%@\nACCESSIBILITY_FAILURE_HIERARCHY_END",screen,self.app.debugDescription);
        }
        return NO; // No category-wide or element-wide suppression; every reported issue remains actionable.
    } error:&error];
    if (!recordedFailure) [self recordAuditScreenshot:screen failure:NO];
    NSLog(@"ACCESSIBILITY_RESULT screen=%@ passed=%d error=%@",screen,passed,error);
    XCTAssertTrue(passed,@"%@ accessibility audit: %@",screen,error);
}
- (void)importAndSample {
    [self.app.buttons[@"choosePhoto"] tap];
    XCUIElement *photo=[self.app.images matchingPredicate:[NSPredicate predicateWithFormat:@"identifier == 'PXGGridLayout-Info' OR label BEGINSWITH 'Photo,'"]].firstMatch;
    XCTAssertTrue([photo waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [photo tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:15]);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    [[self.app.images[@"sampleImage"] coordinateWithNormalizedOffset:CGVectorMake(0.15,0.25)] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"],@"The selected photo must be the seeded asymmetric RGB fixture");
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff00ff"]);
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"R 255   G 0   B 255"]);
    [self assertEmptyHistoryDoesNotOverlapHeader];
}
- (void)testAccessibilityEmptyPalette {
    [self auditScreen:@"empty palette"];
    if (UIDevice.currentDevice.userInterfaceIdiom!=UIUserInterfaceIdiomPad) return;
    XCUIElement *window=self.app.windows.firstMatch;
    self.originalWindowSize=window.frame.size;
    XCUICoordinate *corner=[[window coordinateWithNormalizedOffset:CGVectorMake(1,1)] coordinateWithOffset:CGVectorMake(-12,-12)];
    [corner pressForDuration:0.3 thenDragToCoordinate:[window coordinateWithNormalizedOffset:CGVectorMake(0.45,0.75)]];
    XCTNSPredicateExpectation *resized=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object,NSDictionary *bindings) {
        return window.frame.size.width<self.originalWindowSize.width-100;
    }] object:window];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[resized] timeout:8],XCTWaiterResultCompleted);
    XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
    NSLog(@"ACCESSIBILITY_COMPACT_WINDOW %@",NSStringFromCGRect(window.frame));
    [self assertEmptyHistoryDoesNotOverlapHeader];
    [self auditScreen:@"empty palette in actual compact iPad window"];
    [self restoreFullWindow];
    [self assertEmptyHistoryDoesNotOverlapHeader];
}
- (void)restoreFullWindow {
    XCUIElement *window=self.app.windows.firstMatch;
    if (fabs(window.frame.size.width-self.originalWindowSize.width)>4) {
        [[[window coordinateWithNormalizedOffset:CGVectorMake(0.5,0)] coordinateWithOffset:CGVectorMake(0,12)] doubleTap];
        XCTNSPredicateExpectation *restored=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object,NSDictionary *bindings) {
            CGSize size=window.frame.size;
            return fabs(size.width-self.originalWindowSize.width)<4 && fabs(size.height-self.originalWindowSize.height)<4;
        }] object:window];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[restored] timeout:8],XCTWaiterResultCompleted,@"Restore window after accessibility audit: %@",self.app.debugDescription);
    }
    self.originalWindowSize=CGSizeZero;
}
- (void)testAccessibilityPaletteImportReview {
    [self pastePalette:@"[\"#112233\",\"#aabbcc\"]" app:self.app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:self.app];
    [self auditScreen:@"palette import review"];
}
- (void)testAccessibilityPaletteImportHelp {
    [self verifyOriginalPaletteSources:self.app];
    UIPasteboard.generalPasteboard.string=@"[\"#112233\"]";
    [self openPaletteAction:@"palette.import.open" app:self.app];
    [self verifyInitialPaletteImportControls:self.app];
    if (self.tcPaletteReadinessExpired) return;
    XCTAssertTrue([self.app.cells[@"palette.import.status"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.cells[@"palette.import.status"].staticTexts.firstMatch.label containsString:@"review every color"]);
    [self auditScreen:@"palette import help"];
}
- (void)testAccessibilitySampledPhoto {
    [self importAndSample];
    [self auditScreen:@"sampled photo with numeric RGB and hex"];
}
- (void)testAccessibilitySavedPalette {
    [self importAndSample];[self.app.buttons[@"saveColor"] tap];
    if (UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPhone) [self returnToPaletteFrom:@"Photo Color" app:self.app];
    else if (self.app.buttons[@"workspace.palette"].exists) [self.app.buttons[@"workspace.palette"] tap];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch.label containsString:@"R 255   G 0   B 255"]);
    [self auditScreen:@"saved palette with numeric RGB and hex"];
}
- (void)testAccessibilityLiveCameraUnavailable {
    [self.app.buttons[@"liveColor"] tap];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
    [self assertEmptyHistoryDoesNotOverlapHeader];
    [self auditScreen:@"live camera unavailable"];
}
- (void)testAccessibilityOfflinePolicyError {
    [self.app terminate];
    self.app.launchArguments=[self.app.launchArguments arrayByAddingObjectsFromArray:@[@"--ui-test-policy-offline",@"--ui-test-dark"]];
    [self.app launch];[self.app.buttons[@"privacyPolicy"] tap];
    XCTAssertTrue([self.app.buttons[@"privacy.retry"] waitForExistenceWithTimeout:5]);
    [self auditScreen:@"offline policy error in dark appearance"];
}
- (void)tearDown {
    @try {
        if (self.originalWindowSize.width>0) {
            [self.app terminate];[self.app launch];
            [self restoreFullWindow];
        }
        [super tearDown];
    } @finally {
        if (self.failClosedInterruption) [self removeUIInterruptionMonitor:self.failClosedInterruption];
        self.failClosedInterruption=nil;
    }
}
@end
