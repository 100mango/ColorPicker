#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>

@interface TouchColorIPadUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@end
@implementation TouchColorIPadUITests
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
    XCTNSPredicateExpectation *ready=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == true AND hittable == true"] object:source];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[ready] timeout:5],XCTWaiterResultCompleted,@"%@",self.app.debugDescription);
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
}
- (void)cancelPicker {
    XCUIElement *cancel=self.app.buttons[@"Cancel"].firstMatch;
    XCTNSPredicateExpectation *ready=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == true AND hittable == true"] object:cancel];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[ready] timeout:15],XCTWaiterResultCompleted,@"System picker Cancel must be interactive: %@",self.app.debugDescription);
    [cancel tap];
    XCTNSPredicateExpectation *closed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:cancel];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[closed] timeout:5],XCTWaiterResultCompleted,@"%@",self.app.debugDescription);
}
- (void)testNativeCanvasPaletteSavePreviewPickerCancelAndRelaunch {
    [self importFixture];
    XCUIElement *history=self.app.tables[@"colorHistory"], *photo=self.app.images[@"sampleImage"];
    XCTAssertTrue(history.hittable);
    XCTAssertLessThanOrEqual(CGRectGetMaxX(history.frame),CGRectGetMinX(photo.frame),@"Separate native palette and canvas columns");
    [self.app.buttons[@"saveColor"] tap];
    XCTAssertTrue([history.cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertTrue([history.cells.firstMatch.label containsString:@"#ff00ff"]);
    NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
    XCTAssertLessThanOrEqual(bytes.length,500*1024);
    XCTAttachment *image=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
    image.name=@"touchcolor-ipad-native-canvas";image.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:image];
    [history.cells.firstMatch tap];
    XCTAssertTrue([self.app.alerts.firstMatch waitForExistenceWithTimeout:5]);
    [self.app.alerts.buttons[@"Close"] tap];
    XCTNSPredicateExpectation *previewClosed=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:self.app.alerts.firstMatch];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[previewClosed] timeout:5],XCTWaiterResultCompleted);
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
    [self.app.buttons[@"workspace.palette"] tap];
    XCTAssertTrue(self.app.tables[@"colorHistory"].hittable);
    [self.app.buttons[@"workspace.canvas"] tap];
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
@end
