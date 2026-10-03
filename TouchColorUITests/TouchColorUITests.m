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
- (void)testPrivacyPolicyEntryOpensAndCloses {
    XCUIElement *privacy=self.app.buttons[@"privacyPolicy"];
    XCTAssertTrue([privacy waitForExistenceWithTimeout:5]);
    XCTAssertTrue(privacy.hittable);
    [privacy tap];
    XCUIElement *done=self.app.buttons[@"Done"].firstMatch;
    XCTAssertTrue([done waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [done tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
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
- (void)testSampleSaveRelaunchDeleteAndBackground {
    [self.app.buttons[@"Sample Fixture"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
    [self emitScreenshot:@"touchcolor-photo-sampled"];
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
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue(self.app.buttons[@"saveColor"].hittable);
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
}
- (void)testLargestDynamicTypeControlsRemainReachable {
    [self.app terminate];
    self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
    XCTAssertTrue(self.app.buttons[@"liveColor"].hittable);
    [self.app.buttons[@"Sample Fixture"] tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:5]);
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue(self.app.buttons[@"saveColor"].hittable);
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
    XCTAssertTrue(self.app.buttons[@"choosePhoto"].hittable);
    XCTAssertTrue(self.app.buttons[@"takePhoto"].hittable);
    XCTAssertTrue(self.app.buttons[@"liveColor"].hittable);
    XCTAssertGreaterThan(table.frame.size.height,44);
    for (NSUInteger i=0;i<4 && !CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1));i++) {
        if (CGRectGetMinY(detail.frame) < CGRectGetMinY(table.frame)) [table swipeDown]; else [table swipeUp];
    }
    XCTAssertTrue(CGRectContainsRect(table.frame,CGRectInset(detail.frame,1,1)),@"Landscape RGB detail must remain readable at largest text size");
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
}
- (void)testSystemPhotoSelectionAndSampling {
    // CI seeds an opaque red PNG into this simulator's Photos library.
    [self.app.buttons[@"choosePhoto"] tap];
    XCUIElement *cell=[self.app.images matchingIdentifier:@"PXGGridLayout-Info"].firstMatch;
    XCTAssertTrue([cell waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [cell tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:15],@"%@",self.app.debugDescription);
    [self.app.buttons[@"sampleCenter"] tap];
    XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:@"#ff0000"]);
}
@end
