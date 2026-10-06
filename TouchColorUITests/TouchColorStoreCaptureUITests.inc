// BEGIN FIXED STORE PNG DISPLAY METHODS
@interface TouchColorStoreCaptureUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic, strong) id interruptionGuard;
@end
@implementation TouchColorStoreCaptureUITests
- (void)setUp {
    [super setUp];
    self.continueAfterFailure = NO;
    self.interruptionGuard = [self addUIInterruptionMonitorWithDescription:@"Stop on unexpected Store capture interruption" handler:^BOOL(XCUIElement *unusedAlert) {
        fputs("TOUCHCOLOR_STORE_CAPTURE_INTERRUPTION; no alert action taken\n", stderr);
        abort();
    }];
    self.app = [XCUIApplication new];
}
- (void)tearDown {
    [self.app terminate];
    if (self.interruptionGuard) [self removeUIInterruptionMonitor:self.interruptionGuard];
    [super tearDown];
}
- (void)storeOpenFixture {
    XCTAssertEqualObjects(NSProcessInfo.processInfo.environment[@"TOUCHCOLOR_STORE_CAPTURE"], @"1");
    XCUIDevice.sharedDevice.orientation = UIDeviceOrientationPortrait;
    self.app.launchArguments = @[@"--ui-test-reset", @"--ui-test-image", @"--ui-test-asymmetric",
        @"--ui-test-store-capture", @"-AppleLanguages", @"(zh-Hans)", @"-AppleLocale", @"zh_CN",
        @"-UIPreferredContentSizeCategoryName", @"UICTContentSizeCategoryL"];
    [self.app launch];
    XCUIElement *fixture = self.app.buttons[@"Sample Fixture"];
    XCTAssertTrue([fixture waitForExistenceWithTimeout:15]);
    XCTAssertTrue(fixture.hittable);
    [fixture tap];
    XCTAssertTrue([self.app.images[@"sampleImage"] waitForExistenceWithTimeout:15]);
    XCTAssertEqualObjects(self.app.buttons[@"sampleCenter"].label, @"中心取色");
    XCTAssertEqualObjects(self.app.buttons[@"saveColor"].label, @"保存颜色");
    XCTAssertFalse(self.app.buttons[@"saveColor"].enabled);
    XCTAssertFalse(self.app.buttons[@"Sample Fixture"].exists);
}
- (void)storeSampleX:(CGFloat)x y:(CGFloat)y hex:(NSString *)hex rgb:(NSString *)rgb {
    XCUIElement *photo = self.app.images[@"sampleImage"];
    XCTAssertTrue(photo.hittable);
    [[photo coordinateWithNormalizedOffset:CGVectorMake(x,y)] tap];
    XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label, ([NSString stringWithFormat:@"%@\n%@",hex,rgb]));
    XCUIElement *marker = self.app.images[@"sampleMarker"];
    XCTAssertTrue(marker.exists);
    XCTAssertTrue([(NSString *)marker.value containsString:hex]);
    CGRect frame = photo.frame, position = marker.frame;
    XCTAssertEqualWithAccuracy(CGRectGetMidX(position), CGRectGetMinX(frame)+CGRectGetWidth(frame)*x, 2);
    XCTAssertEqualWithAccuracy(CGRectGetMidY(position), CGRectGetMinY(frame)+CGRectGetHeight(frame)*y, 2);
    XCTAssertTrue(self.app.buttons[@"saveColor"].enabled);
    NSLog(@"STORE_REAL_SAMPLE x=%.6f y=%.6f hex=%@ rgb=%@",x,y,hex,rgb);
}
- (void)storeSave {
    XCUIElement *save = self.app.buttons[@"saveColor"];
    XCTAssertTrue(save.hittable);
    [save tap];
    XCTAssertFalse(save.enabled);
    XCTAssertEqualObjects(save.label, @"已保存");
}
- (void)storeCapturePNG:(NSString *)name {
    XCTAssertEqualObjects(NSProcessInfo.processInfo.environment[@"TOUCHCOLOR_STORE_CAPTURE"], @"1");
    XCTAssertEqual(self.app.state, XCUIApplicationStateRunningForeground);
    XCTAssertEqual(XCUIDevice.sharedDevice.orientation, UIDeviceOrientationPortrait);
    XCTAssertEqual(self.app.alerts.count, 0);
    XCTAssertEqual(self.app.sheets.count, 0);
    XCTAssertFalse(self.app.buttons[@"Sample Fixture"].exists);
    XCTAssertGreaterThan(self.app.frame.size.height, self.app.frame.size.width);
    NSData *PNG = XCUIScreen.mainScreen.screenshot.PNGRepresentation;
    XCTAssertGreaterThan(PNG.length, 0);
    XCTAssertLessThanOrEqual(PNG.length, 8000000);
    if (!PNG.length || PNG.length > 8000000) return;
    XCTAttachment *attachment = [XCTAttachment attachmentWithData:PNG uniformTypeIdentifier:@"public.png"];
    attachment.name = name;
    attachment.lifetime = XCTAttachmentLifetimeKeepAlways;
    [self addAttachment:attachment];
}
- (void)testStoreNormalPhotoScreenshot {
    self.executionTimeAllowance = 180;
    [self storeOpenFixture];
    // Middle of the magenta block, well away from every color boundary.
    [self storeSampleX:0.5 y:0.75 hex:@"#ff00ff" rgb:@"R 255   G 0   B 255"];
    XCTAssertTrue(self.app.buttons[@"sampleCenter"].hittable);
    XCTAssertTrue(self.app.buttons[@"saveColor"].hittable);
    [self storeCapturePNG:@"touchcolor-store-photo"];
}
- (void)testStoreNormalHistoryScreenshot {
    self.executionTimeAllowance = 240;
    [self storeOpenFixture];
    [self storeSampleX:(1.0/6.0) y:0.25 hex:@"#ff0000" rgb:@"R 255   G 0   B 0"];
    [self storeSave];
    [self storeSampleX:(5.0/6.0) y:0.25 hex:@"#0000ff" rgb:@"R 0   G 0   B 255"];
    [self storeSave];
    [self storeSampleX:0.5 y:0.75 hex:@"#ff00ff" rgb:@"R 255   G 0   B 255"];
    [self storeSave];
    if (UIDevice.currentDevice.userInterfaceIdiom == UIUserInterfaceIdiomPhone) {
        XCUIElement *back = [self.app.navigationBars[@"照片取色"].buttons matchingPredicate:
            [NSPredicate predicateWithFormat:@"identifier == 'BackButton' OR label == 'TouchColor'"]].firstMatch;
        XCTAssertTrue([back waitForExistenceWithTimeout:5]);
        XCTAssertTrue(back.hittable);
        [back tap];
    }
    XCUIElement *history = self.app.tables[@"colorHistory"];
    XCTAssertTrue([history waitForExistenceWithTimeout:10]);
    XCTAssertEqual(history.cells.count, 3);
    for (NSString *expected in @[@"#ff0000, R 255   G 0   B 0", @"#0000ff, R 0   G 0   B 255", @"#ff00ff, R 255   G 0   B 255"]) {
        XCUIElement *cell = [history.cells matchingPredicate:[NSPredicate predicateWithFormat:@"label == %@",expected]].firstMatch;
        XCTAssertTrue(cell.exists);
        XCTAssertTrue(cell.hittable);
        XCTAssertTrue(CGRectContainsRect(history.frame, CGRectInset(cell.frame,1,1)));
    }
    XCTAssertEqualObjects(self.app.buttons[@"choosePhoto"].label, @"选择照片");
    if (UIDevice.currentDevice.userInterfaceIdiom == UIUserInterfaceIdiomPad) {
        XCTAssertTrue(self.app.images[@"sampleImage"].hittable);
        XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label, @"#ff00ff\nR 255   G 0   B 255");
    }
    [self storeCapturePNG:@"touchcolor-store-history"];
}
@end
// END FIXED STORE PNG DISPLAY METHODS
