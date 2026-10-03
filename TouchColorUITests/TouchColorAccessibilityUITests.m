#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#import <math.h>

/// Official XCTest audits run as their own bounded CI stage on each supported simulator family.
@interface TouchColorAccessibilityUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic) CGSize originalWindowSize;
@end
@implementation TouchColorAccessibilityUITests
- (void)setUp {
    [super setUp]; self.continueAfterFailure=NO;
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    XCUIDevice.sharedDevice.orientation=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad ? UIDeviceOrientationLandscapeLeft : UIDeviceOrientationPortrait;
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10]);
}
- (void)auditScreen:(NSString *)screen {
    NSError *error=nil;
    BOOL passed=[self.app performAccessibilityAuditWithAuditTypes:XCUIAccessibilityAuditTypeAll issueHandler:^BOOL(XCUIAccessibilityAuditIssue *issue) {
        NSLog(@"ACCESSIBILITY_ISSUE screen=%@ type=%lu description=%@ detail=%@ element=%@",screen,(unsigned long)issue.auditType,issue.compactDescription,issue.detailedDescription,issue.element.debugDescription);
        return NO; // No category-wide or element-wide suppression; every reported issue remains actionable.
    } error:&error];
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
    [self auditScreen:@"empty palette in actual compact iPad window"];
    [self restoreFullWindow];
}
- (void)restoreFullWindow {
    XCUIElement *window=self.app.windows.firstMatch;
    if (fabs(window.frame.size.width-self.originalWindowSize.width)>4) {
        [[[window coordinateWithNormalizedOffset:CGVectorMake(0.5,0)] coordinateWithOffset:CGVectorMake(0,12)] doubleTap];
        XCTNSPredicateExpectation *restored=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object,NSDictionary *bindings) {
            return fabs(window.frame.size.width-self.originalWindowSize.width)<4 && fabs(window.frame.size.height-self.originalWindowSize.height)<4;
        }] object:window];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[restored] timeout:8],XCTWaiterResultCompleted,@"Restore window after accessibility audit: %@",self.app.debugDescription);
    }
    self.originalWindowSize=CGSizeZero;
}
- (void)testAccessibilitySampledPhoto {
    [self importAndSample];
    [self auditScreen:@"sampled photo with numeric RGB and hex"];
}
- (void)testAccessibilitySavedPalette {
    [self importAndSample];[self.app.buttons[@"saveColor"] tap];
    if (UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPhone) [self.app.navigationBars.buttons.firstMatch tap];
    else if (self.app.buttons[@"workspace.palette"].exists) [self.app.buttons[@"workspace.palette"] tap];
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertTrue([self.app.tables[@"colorHistory"].cells.firstMatch.label containsString:@"R 255   G 0   B 255"]);
    [self auditScreen:@"saved palette with numeric RGB and hex"];
}
- (void)testAccessibilityLiveCameraUnavailable {
    [self.app.buttons[@"liveColor"] tap];
    XCTAssertTrue([self.app.staticTexts[@"cameraStatus"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled);
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
    if (self.originalWindowSize.width>0) {
        [self.app terminate];[self.app launch];
        [self restoreFullWindow];
    }
    [super tearDown];
}
@end
