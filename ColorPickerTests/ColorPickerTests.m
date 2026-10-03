#import <XCTest/XCTest.h>
#import "TCColorUtilities.h"

@interface ColorPickerTests : XCTestCase
@property (nonatomic, copy) NSString *suite;
@property (nonatomic, strong) NSUserDefaults *defaults;
@property (nonatomic, strong) TCColorStore *store;
@end
@implementation ColorPickerTests
- (void)setUp {
    [super setUp];
    self.suite = [@"TouchColorTests." stringByAppendingString:NSUUID.UUID.UUIDString];
    self.defaults = [[NSUserDefaults alloc] initWithSuiteName:self.suite];
    self.store = [[TCColorStore alloc] initWithDefaults:self.defaults];
}
- (void)tearDown {
    [self.defaults removePersistentDomainForName:self.suite];
    [super tearDown];
}
- (void)testRGBHexRoundTripAndValidation {
    XCTAssertEqualObjects(TCHexColor(0, 128, 255), @"#0080ff");
    XCTAssertEqualObjects(TCNormalizeHexColor(@"#Ab09EF"), @"#ab09ef");
    for (id invalid in @[@"", @"#fff", @"#12345678", @"#abcdef ", @"abcdefg", @"#gg0000", @123, NSNull.null]) XCTAssertNil(TCNormalizeHexColor(invalid));
    XCTAssertNil(TCNormalizeHexColor(nil));
    CGFloat r=0,g=0,b=0,a=0;
    XCTAssertTrue([TCUIColorFromHex(@"#0080ff") getRed:&r green:&g blue:&b alpha:&a]);
    XCTAssertEqualWithAccuracy(r,0,0.001); XCTAssertEqualWithAccuracy(g,128/255.0,0.001); XCTAssertEqualWithAccuracy(b,1,0.001); XCTAssertEqual(a,1);
    XCTAssertEqualObjects(TCRGBDescription(@"#0080ff"), @"R 0   G 128   B 255");
    XCTAssertEqualObjects(TCRGBDescription(@"bad"), @"");
}
- (void)testFreshHistoryFirstSaveDuplicatesAndOrder {
    XCTAssertEqual(self.store.colors.count,0);
    XCTAssertFalse([self.store addColor:nil]);
    XCTAssertFalse([self.store addColor:@"wrong"]);
    XCTAssertNil([self.defaults objectForKey:@"colorArray"]);
    XCTAssertTrue([self.store addColor:@"#ff0000"]);
    XCTAssertTrue([self.store addColor:@"#00ff00"]);
    XCTAssertTrue([self.store addColor:@"#ff0000"]);
    XCTAssertEqualObjects(self.store.colors, (@[@"#ff0000",@"#00ff00",@"#ff0000"]));
    TCColorStore *reopened=[[TCColorStore alloc] initWithDefaults:[[NSUserDefaults alloc] initWithSuiteName:self.suite]];
    XCTAssertEqualObjects(reopened.colors,self.store.colors);
    XCTAssertFalse([self.store removeColorAtIndex:3]);
    XCTAssertTrue([self.store removeColorAtIndex:1]);
    XCTAssertEqualObjects(self.store.colors, (@[@"#ff0000",@"#ff0000"]));
}
- (void)testLegacyV1HistoryStaysInOriginalKeyWithoutMigration {
    NSArray *legacy=@[@"#101010",@"#abcdef",@"#000000"];
    [self.defaults setObject:legacy forKey:@"colorArray"];
    XCTAssertEqualObjects(self.store.colors,legacy);
    XCTAssertNil([self.defaults objectForKey:@"colorArrayRecoveryBackup"]);
    [self.store addColor:@"#ffffff"];
    XCTAssertEqualObjects([self.defaults arrayForKey:@"colorArray"],(@[@"#101010",@"#abcdef",@"#000000",@"#ffffff"]));
    XCTAssertNil([self.defaults objectForKey:@"colorArrayRecoveryBackup"]);
}
- (void)testMalformedHistoryIsReadSafelyAndBackedUpBeforeRepair {
    NSArray *raw=@[@"#FF0000",@27,@"broken",@"#123456"];
    [self.defaults setObject:raw forKey:@"colorArray"];
    XCTAssertEqualObjects(self.store.colors,(@[@"#ff0000",@"#123456"]));
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArray"],raw);
    [self.store addColor:@"#ffffff"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],raw);
    XCTAssertEqualObjects(self.store.colors,(@[@"#ff0000",@"#123456",@"#ffffff"]));
    [self.store addColor:@"#000000"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],raw);
}
- (void)testWrongTopLevelHistoryAndEmptyHistory {
    [self.defaults setObject:@"not an array" forKey:@"colorArray"];
    XCTAssertEqual(self.store.colors.count,0);
    XCTAssertFalse([self.store removeColorAtIndex:0]);
    [self.store addColor:@"#010203"];
    XCTAssertEqualObjects([self.defaults objectForKey:@"colorArrayRecoveryBackup"],@"not an array");
    [self.defaults setObject:@[] forKey:@"colorArray"];
    XCTAssertEqual(self.store.colors.count,0);
}
- (void)testLetterboxAndInvalidCoordinateRejection {
    CGPoint normalized;
    CGRect image=CGRectMake(20,40,200,100);
    XCTAssertTrue(TCNormalizedPoint(CGPointMake(120,90),image,&normalized));
    XCTAssertEqualWithAccuracy(normalized.x,0.5,0.00001); XCTAssertEqualWithAccuracy(normalized.y,0.5,0.00001);
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(19,90),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(120,39),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(220,140),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointMake(NAN,0),image,NULL));
    XCTAssertFalse(TCNormalizedPoint(CGPointZero,CGRectZero,NULL));
    XCTAssertNil(TCSampleImage(nil,CGPointZero));
    XCTAssertNil(TCSampleImage([UIImage new],CGPointZero));
}
- (UIImage *)fixtureWithOrientation:(UIImageOrientation)orientation scale:(CGFloat)scale {
    const uint8_t bytes[]={255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255, 255,0,255,255, 0,255,255,255};
    NSData *data=[NSData dataWithBytes:bytes length:sizeof(bytes)];
    CGDataProviderRef provider=CGDataProviderCreateWithCFData((__bridge CFDataRef)data);
    CGColorSpaceRef space=CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGImageRef cg=CGImageCreate(3,2,8,32,12,space,kCGImageAlphaPremultipliedLast|kCGBitmapByteOrder32Big,provider,NULL,NO,kCGRenderingIntentDefault);
    UIImage *image=[UIImage imageWithCGImage:cg scale:scale orientation:orientation];
    CGImageRelease(cg); CGColorSpaceRelease(space); CGDataProviderRelease(provider);
    return image;
}
- (void)testAllEightOrientationsAndScaleWithAsymmetricPixelFixture {
    // Original 3x2 rows: red, green, blue / yellow, magenta, cyan.
    NSArray *orientations=@[@(UIImageOrientationUp),@(UIImageOrientationDown),@(UIImageOrientationLeft),@(UIImageOrientationRight),@(UIImageOrientationUpMirrored),@(UIImageOrientationDownMirrored),@(UIImageOrientationLeftMirrored),@(UIImageOrientationRightMirrored)];
    NSArray *corners=@[@[@"#ff0000",@"#0000ff",@"#ffff00",@"#00ffff"],@[@"#00ffff",@"#ffff00",@"#0000ff",@"#ff0000"],@[@"#0000ff",@"#00ffff",@"#ff0000",@"#ffff00"],@[@"#ffff00",@"#ff0000",@"#00ffff",@"#0000ff"],@[@"#0000ff",@"#ff0000",@"#00ffff",@"#ffff00"],@[@"#ffff00",@"#00ffff",@"#ff0000",@"#0000ff"],@[@"#ff0000",@"#ffff00",@"#0000ff",@"#00ffff"],@[@"#00ffff",@"#0000ff",@"#ffff00",@"#ff0000"]];
    CGPoint points[]={CGPointMake(0.1,0.1),CGPointMake(0.9,0.1),CGPointMake(0.1,0.9),CGPointMake(0.9,0.9)};
    for (NSUInteger i=0;i<orientations.count;i++) {
        for (NSNumber *scale in @[@1,@2,@3]) {
            UIImage *image=[self fixtureWithOrientation:[orientations[i] integerValue] scale:scale.doubleValue];
            for (NSUInteger j=0;j<4;j++) XCTAssertEqualObjects(TCSampleImage(image,points[j]),corners[i][j],@"orientation %@ scale %@ corner %lu",orientations[i],scale,(unsigned long)j);
        }
    }
    UIImage *image=[self fixtureWithOrientation:UIImageOrientationUp scale:1];
    XCTAssertEqualObjects(TCSampleImage(image,CGPointMake(1,1)),@"#00ffff");
    XCTAssertNil(TCSampleImage(image,CGPointMake(-0.1,0)));
    XCTAssertNil(TCSampleImage(image,CGPointMake(INFINITY,0)));
    XCTAssertNil(TCSampleImage(image,CGPointMake(0,1.01)));
}
- (void)testTransparentPixelsCompositeOnWhite {
    UIGraphicsImageRendererFormat *format=UIGraphicsImageRendererFormat.defaultFormat;
    format.scale=1; format.opaque=NO; format.preferredRange=UIGraphicsImageRendererFormatRangeStandard;
    UIImage *transparent=[[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {}];
    XCTAssertEqualObjects(TCSampleImage(transparent,CGPointMake(0.5,0.5)),@"#ffffff");
}
- (void)testCameraPermissionDecisionsNeverRequireRealHardware {
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusNotDetermined,YES),TCCameraAccessAsk);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusAuthorized,YES),TCCameraAccessReady);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusDenied,YES),TCCameraAccessBlocked);
    XCTAssertEqual(TCCameraAccessForStatus(AVAuthorizationStatusRestricted,YES),TCCameraAccessBlocked);
    for (NSNumber *status in @[@(AVAuthorizationStatusNotDetermined),@(AVAuthorizationStatusAuthorized),@(AVAuthorizationStatusDenied),@(AVAuthorizationStatusRestricted)]) XCTAssertEqual(TCCameraAccessForStatus(status.integerValue,NO),TCCameraAccessUnavailable);
}
@end
