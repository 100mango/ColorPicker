#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#include <stdio.h>
@interface TouchColorUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@end
@implementation TouchColorUITests
- (void)emitScreenshot:(NSString *)name {
    // At most two synthetic-fixture JPEGs in the entire serial iPhone+iPad job.
    if (UIDevice.currentDevice.userInterfaceIdiom != UIUserInterfaceIdiomPhone) return;
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
    if ([self.name containsString:@"testCaptureAppStoreImages"]) {
        self.app.launchArguments=@[@"-AppleLanguages",@"(zh-Hans)",@"-AppleLocale",@"zh_CN",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryL"];
    } else {
        self.app.launchArguments=@[@"--ui-test-reset",@"--ui-test-image",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    }
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [self.app launch];
}
- (void)emitAppStoreImage:(NSString *)state {
    UIImage *image=XCUIScreen.mainScreen.screenshot.image;
    BOOL phone=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPhone;
    size_t width=CGImageGetWidth(image.CGImage), height=CGImageGetHeight(image.CGImage);
    XCTAssertEqual(width,phone ? 1320 : 2064);
    XCTAssertEqual(height,phone ? 2868 : 2752);
    NSData *data=UIImageJPEGRepresentation(image,0.80);
    XCTAssertGreaterThan(data.length,0);
    XCTAssertLessThanOrEqual(data.length,1024*1024);
    NSString *name=[NSString stringWithFormat:@"touchcolor-%@-%@-zh-Hans",phone ? @"iphone69" : @"ipad13",state];
    printf("STORE_SCREENSHOT_METADATA:%s width=%zu height=%zu bytes=%lu format=RGB-JPEG appSource=8d9220d326f2f6c5a5d0b3bc0e990cd500af45dd\n",name.UTF8String,width,height,(unsigned long)data.length);
    NSString *encoded=[data base64EncodedStringWithOptions:0];
    printf("STORE_SCREENSHOT_BEGIN:%s\n",name.UTF8String);
    for (NSUInteger offset=0;offset<encoded.length;offset+=4096) {
        printf("%s\n",[[encoded substringWithRange:NSMakeRange(offset,MIN(4096,encoded.length-offset))] UTF8String]);
    }
    printf("STORE_SCREENSHOT_END:%s\n",name.UTF8String);
    fflush(stdout);
}
- (void)testCaptureAppStoreImages {
    // Release configuration, normal text, no in-app fixture controls or seeded history.
    XCTAssertFalse(self.app.buttons[@"Sample Fixture"].exists);
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10]);
    [self.app.buttons[@"choosePhoto"] tap];
    XCUIElement *photo=[self.app.images matchingIdentifier:@"PXGGridLayout-Info"].firstMatch;
    XCTAssertTrue([photo waitForExistenceWithTimeout:20],@"%@",self.app.debugDescription);
    [photo tap];
    XCTAssertTrue([self.app.buttons[@"sampleCenter"] waitForExistenceWithTimeout:20]);
    XCUIElement *image=self.app.images[@"sampleImage"];
    XCTAssertTrue(image.exists);
    NSArray *points=@[@0.5,@0.17,@0.83];
    NSArray *expected=@[@"#3da9b4",@"#ee6a5d",@"#f8c75b"];
    for (NSUInteger i=0;i<points.count;i++) {
        [[image coordinateWithNormalizedOffset:CGVectorMake([points[i] doubleValue],0.5)] tap];
        XCTAssertTrue([self.app.staticTexts[@"sampledColor"].label containsString:expected[i]]);
        if (i==0) [self emitAppStoreImage:@"photo-sampling"];
        XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
        [self.app.buttons[@"saveColor"] tap];
        XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    }
    [self.app.navigationBars.buttons.firstMatch tap];
    XCUIElement *table=self.app.tables[@"colorHistory"];
    XCTAssertTrue([table.cells.firstMatch waitForExistenceWithTimeout:10]);
    XCTAssertEqual(table.cells.count,3);
    XCTAssertTrue([table.cells.firstMatch.label containsString:@"#3da9b4"]);
    XCTAssertFalse(self.app.buttons[@"Sample Fixture"].exists);
    [self emitAppStoreImage:@"saved-colors"];
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
