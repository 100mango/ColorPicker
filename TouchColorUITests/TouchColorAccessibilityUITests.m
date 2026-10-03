#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>

/// Official XCTest audits run as their own bounded CI stage on each supported simulator family.
@interface TouchColorAccessibilityUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
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
- (void)testAccessibilityEmptyPalette { [self auditScreen:@"empty palette"]; }
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
@end
