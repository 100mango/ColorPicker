// Real UIKit view hierarchies constrained to historical minimum window geometry.
// This is layout coverage, not a claim of running an iOS 15 device/runtime.
#import <XCTest/XCTest.h>
#import "ColorMainViewController.h"
#import "ColorRealTimeViewController.h"
#import "TCWorkspaceViewController.h"
#import "ColorViewController.h"
#import "ColorDetectView.h"
#import "TCColorUtilities.h"
#import "TCPrivacyViewController.h"
#import <WebKit/WebKit.h>

@interface ColorMainViewController (MinimumLayoutTests)
- (void)reloadHistory;
@end
@interface TCPrivacyViewController (MinimumLayoutTests)
- (void)loadPolicy;
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView;
@end
@interface TCMinimumLayoutPolicy : TCPrivacyViewController
@end
@implementation TCMinimumLayoutPolicy
- (void)loadPolicy {} // Exercise native error layout without a network request.
@end

static UIView *TCLayoutView(UIView *root, NSString *identifier) {
    if ([root.accessibilityIdentifier isEqualToString:identifier]) return root;
    for (UIView *child in root.subviews) { UIView *found=TCLayoutView(child,identifier); if (found) return found; }
    return nil;
}
static UILabel *TCLayoutLabel(UIView *root, NSString *text) {
    if ([root isKindOfClass:UILabel.class] && [((UILabel *)root).text isEqualToString:text]) return (UILabel *)root;
    for (UIView *child in root.subviews) { UILabel *found=TCLayoutLabel(child,text); if (found) return found; }
    return nil;
}

@interface TCAdaptiveLayoutTests : XCTestCase
@end
@implementation TCAdaptiveLayoutTests
- (void)withController:(UIViewController *)controller size:(CGSize)size style:(UIUserInterfaceStyle)style check:(void (^)(UIViewController *))check {
    UIWindowScene *scene=nil;
    for (UIScene *candidate in UIApplication.sharedApplication.connectedScenes) {
        if ([candidate isKindOfClass:UIWindowScene.class] && candidate.activationState==UISceneActivationStateForegroundActive) { scene=(UIWindowScene *)candidate; break; }
    }
    XCTAssertNotNil(scene,@"A running UIKit scene is required for actual view-layout coverage");
    if (!scene) return;
    UIWindow *previous=nil;
    for (UIWindow *candidate in scene.windows) if (candidate.isKeyWindow) previous=candidate;
    UIWindow *window=[[UIWindow alloc] initWithWindowScene:scene];

    window.overrideUserInterfaceStyle=style;
    UIViewController *navigation=[controller isKindOfClass:UISplitViewController.class] ? controller : [[UINavigationController alloc] initWithRootViewController:controller];
    UITraitCollection *largest=[UITraitCollection traitCollectionWithPreferredContentSizeCategory:UIContentSizeCategoryAccessibilityExtraExtraExtraLarge];
    UIViewController *host = [UIViewController new];
    [host addChildViewController:navigation];
    navigation.traitOverrides.preferredContentSizeCategory = UIContentSizeCategoryAccessibilityExtraExtraExtraLarge;
    navigation.traitOverrides.horizontalSizeClass = size.width<600 ? UIUserInterfaceSizeClassCompact : UIUserInterfaceSizeClassRegular;
    navigation.traitOverrides.verticalSizeClass = size.height>400 ? UIUserInterfaceSizeClassRegular : UIUserInterfaceSizeClassCompact;
    navigation.view.translatesAutoresizingMaskIntoConstraints = NO;
    [host.view addSubview:navigation.view];
    [navigation didMoveToParentViewController:host];
    [NSLayoutConstraint activateConstraints:@[[navigation.view.widthAnchor constraintEqualToConstant:size.width],[navigation.view.heightAnchor constraintEqualToConstant:size.height],[navigation.view.topAnchor constraintEqualToAnchor:host.view.topAnchor],[navigation.view.leadingAnchor constraintEqualToAnchor:host.view.leadingAnchor]]];
    @try {
        [largest performAsCurrentTraitCollection:^{
            window.rootViewController=host;
            [window makeKeyAndVisible];
            [window layoutIfNeeded];
            [host.view layoutIfNeeded];
            [navigation.view layoutIfNeeded];
            [controller.view setNeedsLayout];
            [controller.view layoutIfNeeded];
        }];
        XCTAssertEqualWithAccuracy(navigation.view.bounds.size.width,size.width,0.5);
        XCTAssertEqualWithAccuracy(navigation.view.bounds.size.height,size.height,0.5);
        XCTAssertEqualWithAccuracy(controller.view.bounds.size.width,size.width,0.5);
        XCTAssertEqualObjects(controller.traitCollection.preferredContentSizeCategory,UIContentSizeCategoryAccessibilityExtraExtraExtraLarge);
        NSLog(@"MINIMUM_GEOMETRY viewport=%@ style=%ld category=%@ safe=%@",NSStringFromCGSize(size),(long)style,controller.traitCollection.preferredContentSizeCategory,NSStringFromCGRect(controller.view.safeAreaLayoutGuide.layoutFrame));
        check(controller);
    } @finally {
        window.hidden=YES;
        window.rootViewController=nil;
        [previous makeKeyAndVisible];
    }
}
- (void)assertViewReadable:(UIView *)view inScroll:(UIScrollView *)scroll {
    XCTAssertNotNil(view);XCTAssertNotNil(scroll);
    if (!view || !scroll) return;
    CGRect target=[view convertRect:view.bounds toView:scroll];
    [scroll scrollRectToVisible:target animated:NO];
    [scroll layoutIfNeeded];
    target=[view convertRect:view.bounds toView:scroll];
    XCTAssertTrue(CGRectContainsRect(scroll.bounds,CGRectInset(target,1,1)),@"Unreadable %@: content=%@ viewport=%@",view.accessibilityIdentifier,NSStringFromCGRect(target),NSStringFromCGRect(scroll.bounds));
}
- (void)exerciseSize:(CGSize)size {
    NSString *suite=[@"TouchColor.MinimumLayout." stringByAppendingString:NSUUID.UUID.UUIDString];
    NSUserDefaults *defaults=[[NSUserDefaults alloc] initWithSuiteName:suite];
    TCColorStore *store=[[TCColorStore alloc] initWithDefaults:defaults];
    [store addColor:@"#ff0000"];
    @try {
        for (NSNumber *appearance in @[@(UIUserInterfaceStyleLight),@(UIUserInterfaceStyleDark)]) {
            [self withController:[ColorMainViewController new] size:size style:appearance.integerValue check:^(UIViewController *controller) {
                ColorMainViewController *main=(ColorMainViewController *)controller;
                [main setValue:store forKey:@"store"];
                [defaults setObject:@[] forKey:@"colorArray"];
                [main reloadHistory];[main.view layoutIfNeeded];
                UIScrollView *emptyScroll=(UIScrollView *)TCLayoutView(main.view,@"history.emptyScroll");
                UILabel *empty=(UILabel *)TCLayoutView(main.view,@"history.empty");
                [emptyScroll layoutIfNeeded];
                XCTAssertNotNil(emptyScroll);XCTAssertNotNil(empty);
                XCTAssertGreaterThanOrEqual(emptyScroll.contentSize.height,empty.bounds.size.height);
                // A long empty-state paragraph can span screens; both its beginning and end must scroll into view.
                CGRect paragraph=[empty convertRect:empty.bounds toView:emptyScroll];
                [emptyScroll scrollRectToVisible:CGRectMake(paragraph.origin.x,CGRectGetMaxY(paragraph)-1,paragraph.size.width,1) animated:NO];
                XCTAssertGreaterThanOrEqual(CGRectGetMaxY(emptyScroll.bounds)+1,CGRectGetMaxY(paragraph));
                [defaults setObject:@[@"#ff0000"] forKey:@"colorArray"];
                [main reloadHistory];
                [main.view layoutIfNeeded];
                UITableView *history=(UITableView *)TCLayoutView(main.view,@"colorHistory");
                [history layoutIfNeeded];
                NSIndexPath *index=[NSIndexPath indexPathForRow:0 inSection:0];
                [history scrollToRowAtIndexPath:index atScrollPosition:UITableViewScrollPositionBottom animated:NO];
                [history layoutIfNeeded];
                UILabel *RGB=TCLayoutLabel([history cellForRowAtIndexPath:index],@"R 255   G 0   B 0");
                [self assertViewReadable:RGB inScroll:history];
                UIScrollView *actions=(UIScrollView *)TCLayoutView(main.view,@"sourceControls");
                for (NSString *identifier in @[@"choosePhoto",@"takePhoto",@"liveColor"]) {
                    UIButton *button=(UIButton *)TCLayoutView(main.view,identifier);
                    XCTAssertGreaterThanOrEqual(button.bounds.size.height,44);
                    [self assertViewReadable:button.titleLabel inScroll:actions];
                    CGRect title = [button.titleLabel convertRect:button.titleLabel.bounds toView:button];
                    XCTAssertTrue(CGRectContainsRect(button.bounds,CGRectInset(title,0.5,0.5)),@"Button clips its own title: %@ title=%@ button=%@",identifier,NSStringFromCGRect(title),NSStringFromCGRect(button.bounds));
                    CGSize needed = [button.titleLabel sizeThatFits:CGSizeMake(button.titleLabel.bounds.size.width,CGFLOAT_MAX)];
                    XCTAssertLessThanOrEqual(needed.height,button.titleLabel.bounds.size.height+1,@"Full title height must fit %@",identifier);
                    XCTAssertTrue(button.pointerInteractionEnabled);
                }
            }];
            UIGraphicsImageRenderer *renderer=[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2)];
            UIImage *image=[renderer imageWithActions:^(UIGraphicsImageRendererContext *context) { [UIColor.redColor setFill];[context fillRect:CGRectMake(0,0,3,2)]; }];
            ColorViewController *photo=[ColorViewController new];[photo setChooseImage:image];
            [self withController:photo size:size style:appearance.integerValue check:^(UIViewController *controller) {
                ColorDetectView *viewport=(ColorDetectView *)TCLayoutView(controller.view,@"photoViewport");
                XCTAssertGreaterThan(viewport.bounds.size.height,44);
                XCTAssertTrue([viewport sampleVisibleCenter]);
                [controller.view layoutIfNeeded];
                UIScrollView *controls=(UIScrollView *)TCLayoutView(controller.view,@"photoControls");
                [self assertViewReadable:TCLayoutView(controller.view,@"sampledColor") inScroll:controls];
                for (NSString *identifier in @[@"sampleCenter",@"saveColor",@"photoZoom"]) {
                    UIView *control=TCLayoutView(controller.view,identifier);
                    XCTAssertGreaterThanOrEqual(control.bounds.size.height,44);
                    [self assertViewReadable:control inScroll:controls];
                    if ([control isKindOfClass:UIButton.class]) {
                        UIButton *button=(UIButton *)control;
                        XCTAssertTrue(CGRectContainsRect(button.bounds,CGRectInset([button.titleLabel convertRect:button.titleLabel.bounds toView:button],0.5,0.5)));
                    }
                }
            }];
            [self withController:[TCMinimumLayoutPolicy new] size:size style:appearance.integerValue check:^(UIViewController *controller) {
                [(TCPrivacyViewController *)controller webViewWebContentProcessDidTerminate:nil];
                [controller.view layoutIfNeeded];
                UIScrollView *error=(UIScrollView *)TCLayoutView(controller.view,@"privacy.errorScroll");
                UIButton *retry=(UIButton *)TCLayoutView(controller.view,@"privacy.retry");
                XCTAssertGreaterThanOrEqual(retry.bounds.size.height,44);
                [self assertViewReadable:retry inScroll:error];
                XCTAssertEqualObjects(controller.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"privacy.close");
            }];
        }
    } @finally { [defaults removePersistentDomainForName:suite]; }
}
- (void)test320x568LargestTextActualViewLayouts { [self exerciseSize:CGSizeMake(320,568)]; }
- (void)test568x320LargestTextActualViewLayouts { [self exerciseSize:CGSizeMake(568,320)]; }
- (void)testNativeWorkspaceCompactAndSplitWindowGeometry {
    for (NSValue *value in @[[NSValue valueWithCGSize:CGSizeMake(320,568)],[NSValue valueWithCGSize:CGSizeMake(507,768)],[NSValue valueWithCGSize:CGSizeMake(694,507)],[NSValue valueWithCGSize:CGSizeMake(1024,768)]]) {
        TCWorkspaceViewController *workspace=[TCWorkspaceViewController new];
        [self withController:workspace size:value.CGSizeValue style:UIUserInterfaceStyleDark check:^(UIViewController *controller) {
            ColorMainViewController *palette=[workspace valueForKey:@"palette"];
            ColorViewController *canvas=[ColorViewController new];
            UIGraphicsImageRenderer *renderer=[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2)];
            [canvas setChooseImage:[renderer imageWithActions:^(UIGraphicsImageRendererContext *context) { [UIColor.magentaColor setFill];[context fillRect:CGRectMake(0,0,3,2)]; }]];
            [UIView performWithoutAnimation:^{ [palette.workspaceDelegate palette:palette showCanvas:canvas]; }];
            // Wait for UIKit's transition/layout transaction rather than measuring a newly loaded,
            // still-unattached secondary view against an already laid-out primary column.
            XCTestExpectation *settled=[self expectationWithDescription:@"Column transition completed"];
            id<UIViewControllerTransitionCoordinator> transition=workspace.transitionCoordinator;
            BOOL scheduled=transition && [transition animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context) { [settled fulfill]; }];
            if (!scheduled) dispatch_async(dispatch_get_main_queue(), ^{ [settled fulfill]; });
            [self waitForExpectations:@[settled] timeout:3];
            XCTNSPredicateExpectation *attached=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object, NSDictionary *bindings) { return canvas.view.window == workspace.view.window && canvas.view.window != nil; }] object:canvas];
            XCTAssertEqual([XCTWaiter waitForExpectations:@[attached] timeout:3],XCTWaiterResultCompleted,@"Canvas must be attached before comparing column geometry");
            [workspace.view.window layoutIfNeeded];[workspace.view layoutIfNeeded];[canvas.view layoutIfNeeded];
            NSLog(@"SPLIT_GEOMETRY size=%@ horizontal=%ld collapsed=%d mode=%ld primaryWidth=%.1f palette=%@ canvas=%@",NSStringFromCGSize(value.CGSizeValue),(long)workspace.traitCollection.horizontalSizeClass,workspace.collapsed,(long)workspace.displayMode,workspace.primaryColumnWidth,NSStringFromCGRect([palette.view convertRect:palette.view.bounds toView:workspace.view]),NSStringFromCGRect([canvas.view convertRect:canvas.view.bounds toView:workspace.view]));
            ColorDetectView *viewport=(ColorDetectView *)TCLayoutView(canvas.view,@"photoViewport");
            [viewport layoutIfNeeded];
            XCTAssertGreaterThan(viewport.bounds.size.width,44);
            XCTAssertGreaterThan(viewport.bounds.size.height,44);
            XCTAssertTrue([viewport sampleVisibleCenter]);
            UIScrollView *controls=(UIScrollView *)TCLayoutView(canvas.view,@"photoControls");
            [self assertViewReadable:TCLayoutView(canvas.view,@"sampleCenter") inScroll:controls];
            [self assertViewReadable:TCLayoutView(canvas.view,@"saveColor") inScroll:controls];
            if (value.CGSizeValue.width>=600) {
                CGRect paletteFrame=[palette.view convertRect:palette.view.bounds toView:workspace.view];
                CGRect canvasFrame=[canvas.view convertRect:canvas.view.bounds toView:workspace.view];
                XCTAssertLessThanOrEqual(CGRectGetMaxX(paletteFrame),CGRectGetMinX(canvasFrame)+1);
                XCTAssertGreaterThanOrEqual(paletteFrame.size.width,280);
            }
        }];
    }
}
@end
