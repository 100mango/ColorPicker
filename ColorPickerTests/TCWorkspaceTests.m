#import <XCTest/XCTest.h>
#import "TCWorkspaceViewController.h"
#import "ColorMainViewController.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"
#import "ColorDetectView.h"
#import "TCColorUtilities.h"

@interface ColorRealTimeViewController (WorkspaceTests)
- (void)displaySample:(NSString *)hex generation:(NSUInteger)generation;
@end
@interface ColorViewController (WorkspaceTests)
- (void)sampleCenter;
- (void)zoomIn;
- (void)zoomOut;
- (void)resetZoom;
- (void)movePixel:(UIKeyCommand *)command;
@end
@interface ColorMainViewController (WorkspaceTests)
- (void)reloadHistory;
@end
@interface TCWorkspaceTests : XCTestCase
@end
@implementation TCWorkspaceTests
- (UIImage *)fixture {
    UIGraphicsImageRendererFormat *format=[UIGraphicsImageRendererFormat defaultFormat];format.scale=1;
    return [[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {
        NSArray *colors=@[UIColor.redColor,UIColor.greenColor,UIColor.blueColor,UIColor.cyanColor,UIColor.magentaColor,UIColor.yellowColor];
        for (NSUInteger i=0;i<6;i++) { [colors[i] setFill];[context fillRect:CGRectMake(i%3,i/3,1,1)]; }
    }];
}
- (void)testNativePaletteAndCanvasKeepSeparateNavigationAndFullResolutionImage {
    TCWorkspaceViewController *workspace=[TCWorkspaceViewController new];[workspace loadViewIfNeeded];
    UINavigationController *primary=(id)[workspace viewControllerForColumn:UISplitViewControllerColumnPrimary];
    UINavigationController *secondary=(id)[workspace viewControllerForColumn:UISplitViewControllerColumnSecondary];
    ColorMainViewController *palette=(id)primary.topViewController;
    XCTAssertTrue([palette isKindOfClass:ColorMainViewController.class]);
    XCTAssertNotEqual(primary,secondary);
    UIImage *image=[self fixture];
    ColorViewController *canvas=[ColorViewController new];[canvas setChooseImage:image];
    [palette.workspaceDelegate palette:palette showCanvas:canvas];
    XCTAssertEqual(secondary.topViewController,canvas);
    XCTAssertEqual(primary.topViewController,palette);
    if (workspace.collapsed || workspace.displayMode!=UISplitViewControllerDisplayModeOneBesideSecondary) XCTAssertEqualObjects(palette.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"workspace.canvas");
    [canvas loadViewIfNeeded];
    XCTAssertEqual(((ColorDetectView *)[canvas valueForKey:@"colorDetectView"]).imageView.image,image,@"No downsampling or replacement of the imported image");
    if (workspace.collapsed || workspace.displayMode!=UISplitViewControllerDisplayModeOneBesideSecondary) XCTAssertEqualObjects(canvas.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"workspace.palette");
    XCTAssertEqualObjects(canvas.navigationItem.rightBarButtonItem.accessibilityIdentifier,@"workspace.sources");
    NSArray<UIMenuElement *> *actions=canvas.navigationItem.rightBarButtonItem.menu.children;
    NSArray *titles=@[NSLocalizedString(@"Choose Photo",nil),NSLocalizedString(@"Take Photo",nil),NSLocalizedString(@"Live Color",nil),NSLocalizedString(@"Import Palette",nil),NSLocalizedString(@"Privacy Policy",nil)];
    XCTAssertEqual(actions.count,5u);
    XCTAssertEqualObjects([actions valueForKey:@"title"],titles);
    for (UIMenuElement *element in actions) {
        XCTAssertTrue([element isKindOfClass:UIAction.class]);
        XCTAssertNotEqualObjects(((UIAction *)element).identifier,@"watch.inbox.open");
        XCTAssertNotEqualObjects(element.title,NSLocalizedString(@"Watch Inbox",nil));
    }
    XCTAssertEqualObjects(((UIAction *)actions[3]).identifier,@"palette.import.open");
    XCTAssertGreaterThanOrEqual(workspace.keyCommands.count,4);
}
- (void)testSourcePopoverInvalidatesAlreadyQueuedCameraSample {
    ColorRealTimeViewController *live=[ColorRealTimeViewController new];[live loadViewIfNeeded];
    [live setValue:@YES forKey:@"visible"];[live setValue:@YES forKey:@"wantsCapture"];
    TCCaptureGate *gate=[live valueForKey:@"captureGate"];
    NSUInteger generation=[gate beginCapture];
    [live displaySample:@"#ff0000" generation:generation];
    XCTAssertTrue([[live valueForKey:@"saveButton"] isEnabled]);
    live.sourceFlowActive=YES;
    XCTAssertEqualObjects([[live valueForKey:@"statusLabel"] text],NSLocalizedString(@"Camera paused",nil));
    XCTAssertNil(gate.selectedHex);
    [live displaySample:@"#00ff00" generation:generation];
    XCTAssertNil(gate.selectedHex);
    XCTAssertFalse([[live valueForKey:@"saveButton"] isEnabled]);
    live.sourceFlowActive=NO; // A controller without a visible active scene cannot restart capture.
    XCTAssertFalse([[live valueForKey:@"wantsCapture"] boolValue]);
}
- (void)testKeyboardPixelMovementZoomAndPointerUseProductionCanvas {
    ColorViewController *photo=[ColorViewController new];[photo setChooseImage:[self fixture]];[photo loadViewIfNeeded];
    photo.view.frame=CGRectMake(0,0,600,600);[photo.view layoutIfNeeded];
    ColorDetectView *canvas=[photo valueForKey:@"colorDetectView"];[canvas layoutIfNeeded];
    [photo sampleCenter];
    XCTAssertEqualObjects([photo valueForKey:@"selectedHex"],@"#ff00ff");
    [photo movePixel:[UIKeyCommand keyCommandWithInput:UIKeyInputRightArrow modifierFlags:0 action:@selector(movePixel:)]];
    XCTAssertEqualObjects([photo valueForKey:@"selectedHex"],@"#ffff00");
    [photo movePixel:[UIKeyCommand keyCommandWithInput:UIKeyInputUpArrow modifierFlags:0 action:@selector(movePixel:)]];
    XCTAssertEqualObjects([photo valueForKey:@"selectedHex"],@"#0000ff");
    [photo zoomIn];XCTAssertEqualWithAccuracy(canvas.zoomScale,2,0.001);
    [photo zoomOut];XCTAssertEqualWithAccuracy(canvas.zoomScale,1,0.001);
    [photo zoomIn];[photo resetZoom];XCTAssertEqualWithAccuracy(canvas.zoomScale,1,0.001);
    XCTAssertGreaterThanOrEqual(photo.keyCommands.count,9);
    XCTAssertTrue([[photo valueForKey:@"saveButton"] isPointerInteractionEnabled]);
    XCTAssertTrue([canvas.imageView.interactions.firstObject isKindOfClass:UIPointerInteraction.class]);
    UIPointerInteraction *pointer=(id)canvas.imageView.interactions.firstObject;
    XCTAssertNotNil([pointer.delegate pointerInteraction:pointer styleForRegion:[UIPointerRegion regionWithRect:canvas.imageView.bounds identifier:nil]]);
}
- (void)testVisiblePaletteReloadsLegacyOrderedDuplicatesAfterCanvasSave {
    NSString *suite=[@"TouchColor.Workspace." stringByAppendingString:NSUUID.UUID.UUIDString];
    NSUserDefaults *defaults=[[NSUserDefaults alloc] initWithSuiteName:suite];
    [defaults setObject:@[@"#ff0000",@"#00ff00",@"#ff0000"] forKey:@"colorArray"];
    ColorMainViewController *palette=[ColorMainViewController new];[palette loadViewIfNeeded];
    TCColorStore *store=[[TCColorStore alloc] initWithDefaults:defaults];[palette setValue:store forKey:@"store"];[palette reloadHistory];
    XCTAssertTrue([store addColor:@"#0000ff"]);
    [NSNotificationCenter.defaultCenter postNotificationName:NSUserDefaultsDidChangeNotification object:NSUserDefaults.standardUserDefaults];
    XCTestExpectation *updated=[self expectationWithDescription:@"Visible palette refreshes without navigating away"];
    dispatch_async(dispatch_get_main_queue(), ^{
        XCTAssertEqualObjects([palette valueForKey:@"colors"],(@[@"#ff0000",@"#00ff00",@"#ff0000",@"#0000ff"]));
        [updated fulfill];
    });
    [self waitForExpectations:@[updated] timeout:2];
    [defaults removePersistentDomainForName:suite];
}
@end
