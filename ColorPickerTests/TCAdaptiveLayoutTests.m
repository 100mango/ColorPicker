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
#import "../TouchColorUITests/TCSystemPickerGeometry.h"

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
- (void)loadPolicy {
    // Establish the actual native error state before attaching the test window.
    // Leaving an unused, visible WKWebView here starts WebKit during the host's
    // appearance transition and makes this geometry test depend on a cold service.
    [self webViewWebContentProcessDidTerminate:nil];
}
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

@interface TCLayoutHost : UIViewController
@property (nonatomic) BOOL appeared;
@end
@implementation TCLayoutHost
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; self.appeared=YES; }
@end

@interface TCAdaptiveLayoutTests : XCTestCase
@end
@implementation TCAdaptiveLayoutTests
- (void)testInvalidPopoverRootCannotBeReplacedByValidPhotosChild {
    TCPickerSnapshotObservation invalid={CGRectNull,0,0,NO};
    TCObservePhotosSnapshotNode(&invalid,TCPickerNodePopover,"","",CGRectMake(NAN,0,0,0),YES);
    TCObservePhotosSnapshotNode(&invalid,TCPickerNodeNavigationBar,"Photos","",CGRectMake(380,120,600,62),NO);
    XCTAssertFalse(invalid.rootUsable);
    XCTAssertTrue(CGRectIsNull(invalid.bounds));
    CGPoint point=CGPointZero;
    XCTAssertFalse(TCPickerDismissalPoint(CGRectMake(0,0,1376,1032),invalid.bounds,&point));
}
- (void)testMissingOrInvalidPopoverPollResetsConsecutiveStability {
    TCPickerSnapshotObservation good={CGRectNull,0,0,NO}, invalid={CGRectNull,0,0,NO};
    TCObservePhotosSnapshotNode(&good,TCPickerNodePopover,"","",CGRectMake(364,372,833,640),YES);
    TCObservePhotosSnapshotNode(&invalid,TCPickerNodePopover,"","",CGRectMake(NAN,0,0,0),YES);
    TCObservePhotosSnapshotNode(&invalid,TCPickerNodeNavigationBar,"Photos","",CGRectMake(380,120,600,62),NO);
    for (NSUInteger missing=0;missing<2;missing++) {
        CGRect previous=CGRectNull, observedPicker=CGRectNull;
        XCTAssertFalse(TCPickerAdvanceStability(&good,&previous,&observedPicker));
        XCTAssertFalse(TCPickerAdvanceStability(missing ? NULL : &invalid,&previous,&observedPicker));
        XCTAssertTrue(CGRectIsNull(previous));XCTAssertTrue(CGRectIsNull(observedPicker));
        XCTAssertFalse(TCPickerAdvanceStability(&good,&previous,&observedPicker),@"The first good poll after interruption cannot be stable");
        XCTAssertTrue(TCPickerAdvanceStability(&good,&previous,&observedPicker),@"Two consecutive good polls remain required");
        XCTAssertFalse(TCPickerAdvanceStability(missing ? NULL : &invalid,&previous,&observedPicker));
        XCTAssertTrue(CGRectIsNull(previous));XCTAssertTrue(CGRectIsNull(observedPicker));
    }
}
- (void)testRetainedPhotosHierarchyAndLabelOnlyChromeUseQueriedPopoverBounds {
    NSURL *URL=[[NSBundle bundleForClass:self.class] URLForResource:@"photos-ipad-large-7e3-hierarchy" withExtension:@"json"];
    XCTAssertNotNil(URL);
    if (!URL) return;
    NSDictionary *fixture=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:URL] options:0 error:nil];
    NSArray<NSDictionary *> *nodes=fixture[@"nodes"];
    XCTAssertEqual(nodes.count,256u,@"Replay the retained hierarchy, not only idealized rectangles");
    if (nodes.count!=256) return;
    NSUInteger root=[nodes indexOfObjectPassingTest:^BOOL(NSDictionary *node,NSUInteger index,BOOL *stop) { return [node[@"type"] isEqualToString:@"Popover"]; }];
    XCTAssertNotEqual(root,NSNotFound);
    if (root==NSNotFound) return;
    for (NSUInteger labelOnly=0;labelOnly<2;labelOnly++) {
        TCPickerSnapshotObservation observation={CGRectNull,0,0,NO};
        for (NSUInteger index=root;index<nodes.count;index++) {
            NSInteger ancestor=(NSInteger)index;
            while (ancestor>=0 && ancestor!=(NSInteger)root) ancestor=[nodes[(NSUInteger)ancestor][@"parent"] integerValue];
            if (ancestor<0) continue;
            NSDictionary *node=nodes[index];NSArray<NSNumber *> *frame=node[@"frame"];
            TCPickerNodeKind kind=TCPickerNodeOther;
            if ([node[@"type"] isEqualToString:@"Popover"]) kind=TCPickerNodePopover;
            else if ([node[@"type"] isEqualToString:@"NavigationBar"]) kind=TCPickerNodeNavigationBar;
            else if ([node[@"type"] isEqualToString:@"ScrollView"]) kind=TCPickerNodeScrollView;
            NSString *identifier=node[@"identifier"], *label=node[@"label"];
            if (labelOnly && [identifier isEqualToString:@"Photos"]) { identifier=@"";label=@"Photos"; }
            TCObservePhotosSnapshotNode(&observation,kind,identifier.UTF8String,label.UTF8String,
                CGRectMake(frame[0].doubleValue,frame[1].doubleValue,frame[2].doubleValue,frame[3].doubleValue),index==root);
        }
        XCTAssertTrue(CGRectEqualToRect(observation.bounds,CGRectMake(364,372,833,640)));
        XCTAssertEqual(observation.chromeMatches,2u);
        CGPoint point=CGPointZero;
        XCTAssertTrue(TCPickerDismissalPoint(CGRectMake(0,0,1376,1032),observation.bounds,&point));
        XCTAssertEqualWithAccuracy(point.x,186,0.001);XCTAssertEqualWithAccuracy(point.y,516,0.001);
    }
    // Public snapshots may omit a remote subtree. The independently resolved
    // popover root still has outer bounds; arbitrary unbound windows do not.
    TCPickerSnapshotObservation shallow={CGRectNull,0,0,NO};
    TCObservePhotosSnapshotNode(&shallow,TCPickerNodeOther,"","",CGRectMake(364,372,833,640),YES);
    XCTAssertTrue(CGRectEqualToRect(shallow.bounds,CGRectMake(364,372,833,640)));
    XCTAssertEqual(shallow.chromeMatches,0u);
    TCPickerSnapshotObservation unrelated={CGRectNull,0,0,NO};
    TCObservePhotosSnapshotNode(&unrelated,TCPickerNodeOther,"","Photos",CGRectMake(0,0,1376,1032),NO);
    XCTAssertTrue(CGRectIsNull(unrelated.bounds));
    XCTAssertFalse(TCPhotosSnapshotNodeIsChrome(TCPickerNodeNavigationBar,"Color Canvas","Color Canvas"));
}
- (void)testPickerDismissalUsesInteriorFreeSpaceInRecordedAndShiftedWindows {
    NSArray<NSValue *> *windows=@[[NSValue valueWithCGRect:CGRectMake(0,0,1133,744)],
        [NSValue valueWithCGRect:CGRectMake(0,0,1376,1032)], [NSValue valueWithCGRect:CGRectMake(80,40,694,600)]];
    NSArray<NSValue *> *presentations=@[[NSValue valueWithCGRect:CGRectMake(346.5,84,593,640)],
        [NSValue valueWithCGRect:CGRectMake(380,120,600,700)], [NSValue valueWithCGRect:CGRectMake(280,60,450,560)]];
    for (NSUInteger index=0;index<windows.count;index++) {
        CGRect window=windows[index].CGRectValue, presentation=presentations[index].CGRectValue;
        CGPoint point=CGPointZero;
        XCTAssertTrue(TCPickerDismissalPoint(window,presentation,&point));
        XCTAssertTrue(CGRectContainsPoint(CGRectInset(window,20,20),point));
        XCTAssertLessThan(point.x,CGRectGetMinX(presentation)-12,@"Prefer the stable source-side gap");
        XCTAssertFalse(CGRectContainsPoint(CGRectInset(presentation,-12,-12),point));
        // Remote Photos can expand to the far-right edge without putting this
        // source-side cancellation point inside the gallery.
        CGRect expanded=CGRectMake(presentation.origin.x,presentation.origin.y,CGRectGetMaxX(window)-presentation.origin.x,presentation.size.height);
        XCTAssertFalse(CGRectContainsPoint(expanded,point));
    }
}
- (void)testPickerDismissalRejectsFullWindowInvalidAndNarrowGaps {
    CGRect window=CGRectMake(0,0,375,514);CGPoint point=CGPointZero;
    for (NSValue *value in @[[NSValue valueWithCGRect:window], [NSValue valueWithCGRect:CGRectInset(window,10,10)],
        [NSValue valueWithCGRect:CGRectZero], [NSValue valueWithCGRect:CGRectNull],
        [NSValue valueWithCGRect:CGRectMake(NAN,0,100,100)], [NSValue valueWithCGRect:CGRectMake(400,0,100,100)]]) {
        XCTAssertFalse(TCPickerDismissalPoint(window,value.CGRectValue,&point),@"Use actual sheet Cancel when no safe outside region exists");
    }
    XCTAssertFalse(TCPickerDismissalPoint(window,CGRectMake(100,50,200,300),NULL));
}
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
    TCLayoutHost *host = [TCLayoutHost new];
    [host addChildViewController:navigation];
    UIUserInterfaceSizeClass horizontal = size.width<600 ? UIUserInterfaceSizeClassCompact : UIUserInterfaceSizeClassRegular;
    UIUserInterfaceSizeClass vertical = size.height>400 ? UIUserInterfaceSizeClassRegular : UIUserInterfaceSizeClassCompact;
    if (@available(iOS 17.0, *)) {
        navigation.traitOverrides.preferredContentSizeCategory = UIContentSizeCategoryAccessibilityExtraExtraExtraLarge;
        navigation.traitOverrides.horizontalSizeClass = horizontal;
        navigation.traitOverrides.verticalSizeClass = vertical;
    } else {
        UITraitCollection *traits = [UITraitCollection traitCollectionWithTraitsFromCollections:@[
            largest, [UITraitCollection traitCollectionWithHorizontalSizeClass:horizontal],
            [UITraitCollection traitCollectionWithVerticalSizeClass:vertical]]];
        [host setOverrideTraitCollection:traits forChildViewController:navigation];
    }
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
        // Let UIKit finish presenting this test window before measuring or removing it.
        // Tearing a root down during its incoming appearance transition produces invalid lifecycle evidence.
        XCTNSPredicateExpectation *appeared=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"appeared == true"] object:host];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[appeared] timeout:3],XCTWaiterResultCompleted);
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
    // Sampling changes the label's intrinsic height; resolve the parent stack and content guide
    // before computing the rectangle to scroll, rather than scrolling to the previous layout.
    [scroll.superview layoutIfNeeded];[scroll layoutIfNeeded];
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
                UITableView *emptyHistory=(UITableView *)TCLayoutView(main.view,@"colorHistory");
                [emptyHistory layoutIfNeeded];
                UITableViewHeaderFooterView *emptyHeader=[emptyHistory headerViewForSection:0];
                if (emptyHeader && !emptyHeader.hidden) {
                    CGRect header=[emptyHeader convertRect:emptyHeader.bounds toView:main.view];
                    CGRect message=[empty convertRect:empty.bounds toView:main.view];
                    XCTAssertFalse(CGRectIntersectsRect(header,message),@"Empty palette header %@ overlaps explanation %@",NSStringFromCGRect(header),NSStringFromCGRect(message));
                }
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
                for (NSString *identifier in @[@"choosePhoto",@"takePhoto",@"liveColor",@"palette.import.open",@"watch.inbox.open"]) {
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
                [controller.view layoutIfNeeded];
                UIScrollView *error=(UIScrollView *)TCLayoutView(controller.view,@"privacy.errorScroll");
                UIButton *retry=(UIButton *)TCLayoutView(controller.view,@"privacy.retry");
                XCTAssertFalse(error.hidden,@"The native failure state must be visible before layout is measured");
                XCTAssertGreaterThanOrEqual(retry.bounds.size.height,44);
                [self assertViewReadable:retry inScroll:error];
                XCTAssertEqualObjects(controller.navigationItem.leftBarButtonItem.accessibilityIdentifier,@"privacy.close");
            }];
        }
    } @finally { [defaults removePersistentDomainForName:suite]; }
}
- (void)test320x568LargestTextActualViewLayouts { [self exerciseSize:CGSizeMake(320,568)]; }
- (void)test568x320LargestTextActualViewLayouts { [self exerciseSize:CGSizeMake(568,320)]; }
- (void)settleWorkspace:(TCWorkspaceViewController *)workspace {
    XCTestExpectation *settled=[self expectationWithDescription:@"Column transition completed"];
    id<UIViewControllerTransitionCoordinator> transition=workspace.transitionCoordinator;
    BOOL scheduled=transition && [transition animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context) { [settled fulfill]; }];
    if (!scheduled) dispatch_async(dispatch_get_main_queue(), ^{ [settled fulfill]; });
    [self waitForExpectations:@[settled] timeout:3];
    [workspace.view.window layoutIfNeeded];[workspace.view layoutIfNeeded];
}
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
            [self settleWorkspace:workspace];
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
            if (value.CGSizeValue.width>=1000) XCTAssertEqual(workspace.displayMode,UISplitViewControllerDisplayModeOneBesideSecondary);
            if (!workspace.collapsed && workspace.displayMode==UISplitViewControllerDisplayModeOneBesideSecondary) {
                // Modern UISplitViewController extends the secondary background beneath the sidebar.
                // Compare usable content, matching the actual table/image non-overlap UI assertion.
                CGRect paletteFrame=[palette.view convertRect:palette.view.safeAreaLayoutGuide.layoutFrame toView:workspace.view];
                CGRect canvasFrame=[canvas.view convertRect:canvas.view.safeAreaLayoutGuide.layoutFrame toView:workspace.view];
                XCTAssertLessThanOrEqual(CGRectGetMaxX(paletteFrame),CGRectGetMinX(canvasFrame)+1);
                XCTAssertGreaterThanOrEqual(paletteFrame.size.width,280);
            } else {
                XCTAssertEqualWithAccuracy(canvas.view.bounds.size.width,value.CGSizeValue.width,1);
                UIBarButtonItem *showPalette=canvas.navigationItem.leftBarButtonItem;
                XCTAssertTrue([UIApplication.sharedApplication sendAction:showPalette.action to:showPalette.target from:showPalette forEvent:nil]);
                [self settleWorkspace:workspace];
                XCTAssertEqual(palette.view.window,workspace.view.window);
                UIBarButtonItem *returnToCanvas=palette.navigationItem.leftBarButtonItem;
                XCTAssertEqualObjects(returnToCanvas.accessibilityIdentifier,@"workspace.canvas");
                XCTAssertTrue([UIApplication.sharedApplication sendAction:returnToCanvas.action to:returnToCanvas.target from:returnToCanvas forEvent:nil]);
                [self settleWorkspace:workspace];
                XCTAssertEqual(canvas.view.window,workspace.view.window);
                XCTAssertEqualObjects([canvas valueForKey:@"selectedHex"],@"#ff00ff");
            }
        }];
    }
}
@end
