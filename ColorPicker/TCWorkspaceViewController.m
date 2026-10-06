#import "TCWorkspaceViewController.h"
#import "ColorMainViewController.h"
#import "ColorRealTimeViewController.h"
#import "TCColorUtilities.h"

@interface TCWorkspaceViewController () <TCColorWorkspaceDelegate, UISplitViewControllerDelegate>
@property (nonatomic, strong) ColorMainViewController *palette;
@property (nonatomic, strong) UINavigationController *canvasNavigation;
@property (nonatomic) BOOL hasCanvas;
@end
@implementation TCWorkspaceViewController
- (instancetype)init { return [super initWithStyle:UISplitViewControllerStyleDoubleColumn]; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.accessibilityIdentifier = @"colorWorkspace";
    self.delegate = self;
    self.preferredDisplayMode = UISplitViewControllerDisplayModeOneBesideSecondary;
    self.preferredSplitBehavior = UISplitViewControllerSplitBehaviorTile;
    self.primaryBackgroundStyle = UISplitViewControllerBackgroundStyleSidebar;
    self.minimumPrimaryColumnWidth = 280;
    self.maximumPrimaryColumnWidth = 380;
    self.preferredPrimaryColumnWidthFraction = 0.32;
    self.palette = [ColorMainViewController new];
    self.palette.workspaceDelegate = self;
    UINavigationController *library = [[UINavigationController alloc] initWithRootViewController:self.palette];
    // The primary sidebar can become the whole compact window. Preserve semantic
    // title contrast there as well as in the full two-column workspace.
    UINavigationBarAppearance *paletteBar = [UINavigationBarAppearance new];
    [paletteBar configureWithDefaultBackground];
    paletteBar.titleTextAttributes = @{NSForegroundColorAttributeName:UIColor.labelColor};
    library.navigationBar.standardAppearance = paletteBar;
    library.navigationBar.scrollEdgeAppearance = paletteBar;
    library.navigationBar.compactAppearance = paletteBar;
    library.navigationBar.compactScrollEdgeAppearance = paletteBar;
    UIViewController *empty = [UIViewController new];
    empty.title = NSLocalizedString(@"Color Canvas", nil);
    empty.view.backgroundColor = UIColor.systemBackgroundColor;
    UILabel *message = [UILabel new];
    message.numberOfLines = 0;
    message.textAlignment = NSTextAlignmentCenter;
    message.text = NSLocalizedString(@"Choose a photo or use the camera. Save colors to build your palette.", nil);
    message.font = [UIFont preferredFontForTextStyle:UIFontTextStyleTitle2];
    message.adjustsFontForContentSizeCategory = YES;
    message.textColor = UIColor.secondaryLabelColor;
    message.accessibilityIdentifier = @"workspace.empty";
    message.translatesAutoresizingMaskIntoConstraints = NO;
    UIScrollView *scroll = [UIScrollView new];
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    [empty.view addSubview:scroll]; [scroll addSubview:message];
    [NSLayoutConstraint activateConstraints:@[
        [scroll.topAnchor constraintEqualToAnchor:empty.view.safeAreaLayoutGuide.topAnchor],
        [scroll.bottomAnchor constraintEqualToAnchor:empty.view.safeAreaLayoutGuide.bottomAnchor],
        [scroll.leadingAnchor constraintEqualToAnchor:empty.view.safeAreaLayoutGuide.leadingAnchor],
        [scroll.trailingAnchor constraintEqualToAnchor:empty.view.safeAreaLayoutGuide.trailingAnchor],
        [message.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor constant:32],
        [message.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor constant:-32],
        [message.leadingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.leadingAnchor constant:24],
        [message.trailingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.trailingAnchor constant:-24],
        [message.widthAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.widthAnchor constant:-48]
    ]];
    self.canvasNavigation = [[UINavigationController alloc] initWithRootViewController:empty];
    [self setViewController:library forColumn:UISplitViewControllerColumnPrimary];
    [self setViewController:self.canvasNavigation forColumn:UISplitViewControllerColumnSecondary];
    [self configureCanvasNavigation:empty];
}
- (UISplitViewControllerColumn)splitViewController:(UISplitViewController *)splitViewController topColumnForCollapsingToProposedTopColumn:(UISplitViewControllerColumn)proposed {
    return self.hasCanvas ? UISplitViewControllerColumnSecondary : UISplitViewControllerColumnPrimary;
}
- (void)configureCanvasNavigation:(UIViewController *)canvas {
    [self updatePaletteNavigationForCanvas:canvas];
    __weak typeof(self) weakSelf = self;
    UIAction *photo = [UIAction actionWithTitle:NSLocalizedString(@"Choose Photo", nil) image:[UIImage systemImageNamed:@"photo"] identifier:nil handler:^(UIAction *action) { [weakSelf.palette choosePhoto]; }];
    UIAction *camera = [UIAction actionWithTitle:NSLocalizedString(@"Take Photo", nil) image:[UIImage systemImageNamed:@"camera"] identifier:nil handler:^(UIAction *action) { [weakSelf.palette takePhoto]; }];
    UIAction *live = [UIAction actionWithTitle:NSLocalizedString(@"Live Color", nil) image:[UIImage systemImageNamed:@"viewfinder"] identifier:nil handler:^(UIAction *action) { [weakSelf.palette openLiveColor]; }];
    UIAction *privacy = [UIAction actionWithTitle:NSLocalizedString(@"Privacy Policy", nil) image:[UIImage systemImageNamed:@"hand.raised"] identifier:nil handler:^(UIAction *action) { [weakSelf.palette openPrivacyPolicy]; }];
    UIAction *paletteImport = [UIAction actionWithTitle:NSLocalizedString(@"Import Palette", nil) image:[UIImage systemImageNamed:@"square.and.arrow.down"] identifier:@"palette.import.open" handler:^(UIAction *action) { [weakSelf.palette openPaletteImport]; }];
    UIBarButtonItem *sources = [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"plus"] menu:[UIMenu menuWithTitle:NSLocalizedString(@"Color Sources", nil) children:@[photo,camera,live,paletteImport,privacy]]];
    sources.accessibilityLabel = NSLocalizedString(@"Color Sources", nil);
    sources.accessibilityIdentifier = @"workspace.sources";
    canvas.navigationItem.rightBarButtonItems = @[sources];
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    [self updatePaletteNavigationForCanvas:self.canvasNavigation.topViewController];
}
- (void)updatePaletteNavigationForCanvas:(UIViewController *)canvas {
    BOOL separateNavigation = self.collapsed || self.displayMode != UISplitViewControllerDisplayModeOneBesideSecondary;
    BOOL hasPaletteButton = [canvas.navigationItem.leftBarButtonItem.accessibilityIdentifier isEqualToString:@"workspace.palette"];
    if (separateNavigation && !hasPaletteButton) {
        UIBarButtonItem *palette = [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"sidebar.left"] style:UIBarButtonItemStylePlain target:self action:@selector(showPalette)];
        palette.accessibilityLabel = NSLocalizedString(@"Saved Colors", nil);
        palette.accessibilityIdentifier = @"workspace.palette";
        canvas.navigationItem.leftBarButtonItem = palette;
    } else if (!separateNavigation && hasPaletteButton) canvas.navigationItem.leftBarButtonItem = nil;
    if (!self.hasCanvas) return;
    BOOL hasReturnButton = [self.palette.navigationItem.leftBarButtonItem.accessibilityIdentifier isEqualToString:@"workspace.canvas"];
    if (separateNavigation && !hasReturnButton) {
        UIBarButtonItem *returnToCanvas = [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"rectangle"] style:UIBarButtonItemStylePlain target:self action:@selector(showCurrentCanvas)];
        returnToCanvas.accessibilityLabel = NSLocalizedString(@"Color Canvas", nil);
        returnToCanvas.accessibilityIdentifier = @"workspace.canvas";
        self.palette.navigationItem.leftBarButtonItem = returnToCanvas;
    } else if (!separateNavigation && hasReturnButton) self.palette.navigationItem.leftBarButtonItem = nil;
}
- (void)showPalette { [self showColumn:UISplitViewControllerColumnPrimary]; }
- (void)showCurrentCanvas { if (self.hasCanvas) [self showColumn:UISplitViewControllerColumnSecondary]; }
- (UIViewController *)sourcePresenterForPalette:(ColorMainViewController *)palette { return self; }
- (UIBarButtonItem *)sourceAnchorForPalette:(ColorMainViewController *)palette { return self.canvasNavigation.topViewController.navigationItem.rightBarButtonItem; }
- (void)palette:(ColorMainViewController *)palette showCanvas:(UIViewController *)canvas {
    [self configureCanvasNavigation:canvas];
    self.hasCanvas = YES;
    [self updatePaletteNavigationForCanvas:canvas];
    [self.canvasNavigation setViewControllers:@[canvas] animated:NO];
    [self showColumn:UISplitViewControllerColumnSecondary];
}
- (void)palette:(ColorMainViewController *)palette sourceFlowActive:(BOOL)active {
    UIViewController *canvas = self.canvasNavigation.topViewController;
    if ([canvas isKindOfClass:ColorRealTimeViewController.class]) ((ColorRealTimeViewController *)canvas).sourceFlowActive = active;
}
- (void)palette:(ColorMainViewController *)palette loadingPhoto:(BOOL)loading {
    UIViewController *canvas = self.canvasNavigation.topViewController;
    if (loading) {
        UIActivityIndicatorView *activity = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
        activity.accessibilityIdentifier = @"workspace.loading";
        activity.isAccessibilityElement = YES;
        activity.accessibilityLabel = NSLocalizedString(@"Opening Photo", nil);
        [activity startAnimating];
        UIBarButtonItem *cancel = [[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemCancel target:palette action:@selector(cancelPhotoImport)];
        cancel.accessibilityIdentifier = @"photo.import.cancel";
        canvas.navigationItem.rightBarButtonItems = @[cancel, [[UIBarButtonItem alloc] initWithCustomView:activity]];
    } else [self configureCanvasNavigation:canvas];
}
- (void)palette:(ColorMainViewController *)palette previewSavedColor:(NSString *)hex {
    // A palette preview never replaces the current photo or its selected pixel/zoom state.
    if (self.presentedViewController) return;
    UIAlertController *preview = [UIAlertController alertControllerWithTitle:hex message:TCRGBDescription(hex) preferredStyle:UIAlertControllerStyleAlert];
    __weak typeof(self) weakSelf = self;
    [preview addAction:[UIAlertAction actionWithTitle:NSLocalizedString(@"Close", nil) style:UIAlertActionStyleCancel handler:^(UIAlertAction *action) { [weakSelf palette:palette sourceFlowActive:NO]; }]];
    [self palette:palette sourceFlowActive:YES];
    [self presentViewController:preview animated:YES completion:nil];
}
- (BOOL)canBecomeFirstResponder { return YES; }
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; if (!self.hasCanvas) [self becomeFirstResponder]; }
- (NSArray<UIKeyCommand *> *)keyCommands {
    if (self.presentedViewController) return @[];
    UIKeyCommand *photo = [UIKeyCommand keyCommandWithInput:@"o" modifierFlags:UIKeyModifierCommand action:@selector(importPhoto)];
    photo.discoverabilityTitle = NSLocalizedString(@"Choose Photo", nil);
    UIKeyCommand *camera = [UIKeyCommand keyCommandWithInput:@"o" modifierFlags:UIKeyModifierCommand | UIKeyModifierShift action:@selector(takePhoto)];
    camera.discoverabilityTitle = NSLocalizedString(@"Take Photo", nil);
    UIKeyCommand *live = [UIKeyCommand keyCommandWithInput:@"l" modifierFlags:UIKeyModifierCommand action:@selector(openLive)];
    live.discoverabilityTitle = NSLocalizedString(@"Live Color", nil);
    UIKeyCommand *palette = [UIKeyCommand keyCommandWithInput:@"1" modifierFlags:UIKeyModifierCommand action:@selector(showPalette)];
    palette.discoverabilityTitle = NSLocalizedString(@"Saved Colors", nil);
    return @[photo,camera,live,palette];
}
- (void)importPhoto { [self.palette choosePhoto]; }
- (void)takePhoto { [self.palette takePhoto]; }
- (void)openLive { [self.palette openLiveColor]; }
@end
