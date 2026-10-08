#import "ColorMainViewController.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"
#import "TCColorUtilities.h"
#import <PhotosUI/PhotosUI.h>
#import "TCPrivacyViewController.h"

@interface ColorMainViewController () <UITableViewDelegate, UITableViewDataSource, PHPickerViewControllerDelegate, UIImagePickerControllerDelegate, UINavigationControllerDelegate, UIAdaptivePresentationControllerDelegate>
@property (nonatomic, strong) UITableView *tableView;
@property (nonatomic, strong) UIStackView *sourceButtons;
@property (nonatomic, strong) TCColorStore *store;
@property (nonatomic, copy) NSArray<NSString *> *colors;
@property (nonatomic, strong) UIActivityIndicatorView *loading;
@property (nonatomic) NSUInteger selectionGeneration;
#if DEBUG
@property (nonatomic, strong) UILabel *permissionStatus;
@property (nonatomic) NSUInteger permissionActivations;
@property (nonatomic) NSUInteger sourceAttempts;
#endif
@end
@implementation ColorMainViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = @"TouchColor";
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(defaultsChanged:) name:NSUserDefaultsDidChangeNotification object:NSUserDefaults.standardUserDefaults];
    self.tableView = [[UITableView alloc] initWithFrame:CGRectZero style:UITableViewStyleInsetGrouped];
    self.tableView.translatesAutoresizingMaskIntoConstraints = NO;
    self.tableView.dataSource = self;
    self.tableView.delegate = self;
    self.tableView.accessibilityIdentifier = @"colorHistory";
    self.tableView.rowHeight = UITableViewAutomaticDimension;
    self.tableView.estimatedRowHeight = 70;
    [self.view addSubview:self.tableView];
    NSArray *titles = @[NSLocalizedString(@"Choose Photo", nil), NSLocalizedString(@"Take Photo", nil), NSLocalizedString(@"Live Color", nil)];
    NSArray *identifiers = @[@"choosePhoto", @"takePhoto", @"liveColor"];
    NSArray *symbols = @[@"photo", @"camera", @"viewfinder"];
    UIStackView *buttons = [UIStackView new];
    self.sourceButtons = buttons;
    buttons.axis = UILayoutConstraintAxisVertical;
    buttons.spacing = 8;
    buttons.translatesAutoresizingMaskIntoConstraints = NO;
    for (NSUInteger i = 0; i < titles.count; i++) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
        UIButtonConfiguration *configuration = UIButtonConfiguration.tintedButtonConfiguration;
        configuration.title = titles[i];
        configuration.image = [UIImage systemImageNamed:symbols[i]];
        configuration.imagePadding = 10;
        configuration.titleLineBreakMode = NSLineBreakByWordWrapping;
        configuration.titleTextAttributesTransformer = ^NSDictionary *(NSDictionary *attributes) {
            NSMutableDictionary *result = [attributes mutableCopy];
            result[NSFontAttributeName] = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
            return result;
        };
        button.configuration = configuration;
        button.titleLabel.numberOfLines = 0;
        button.pointerInteractionEnabled = YES;
        [button setContentCompressionResistancePriority:999 forAxis:UILayoutConstraintAxisVertical];
        button.accessibilityIdentifier = identifiers[i];
        button.tag = i;
        [button.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
        [button addTarget:self action:@selector(selectSource:) forControlEvents:UIControlEventTouchUpInside];
        [buttons addArrangedSubview:button];
    }
    UIScrollView *sourceControls = [UIScrollView new];
    sourceControls.accessibilityIdentifier = @"sourceControls";
    sourceControls.translatesAutoresizingMaskIntoConstraints = NO;
    [sourceControls addSubview:buttons];
    [self.view addSubview:sourceControls];
    NSLayoutConstraint *naturalHeight = [sourceControls.heightAnchor constraintEqualToAnchor:buttons.heightAnchor constant:8];
    // Content must retain its full label height and scroll when the viewport is capped.
    naturalHeight.priority = UILayoutPriorityDefaultLow;
    naturalHeight.active = YES;
    self.loading = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.loading.hidesWhenStopped = YES;
    [self showPrivacyButton];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [sourceControls.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [sourceControls.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [sourceControls.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [sourceControls.heightAnchor constraintLessThanOrEqualToAnchor:safe.heightAnchor multiplier:0.5],
        [buttons.leadingAnchor constraintEqualToAnchor:sourceControls.contentLayoutGuide.leadingAnchor constant:16],
        [buttons.trailingAnchor constraintEqualToAnchor:sourceControls.contentLayoutGuide.trailingAnchor constant:-16],
        [buttons.topAnchor constraintEqualToAnchor:sourceControls.contentLayoutGuide.topAnchor],
        [buttons.bottomAnchor constraintEqualToAnchor:sourceControls.contentLayoutGuide.bottomAnchor constant:-8],
        [buttons.widthAnchor constraintEqualToAnchor:sourceControls.frameLayoutGuide.widthAnchor constant:-32],
        [self.tableView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.tableView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.tableView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.tableView.bottomAnchor constraintEqualToAnchor:sourceControls.topAnchor constant:-8]
    ]];
#if DEBUG
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-camera-permission"]) {
        self.permissionStatus = [UILabel new];
        self.permissionStatus.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
        self.permissionStatus.accessibilityIdentifier = @"cameraPermissionStatus";
        self.navigationItem.titleView = self.permissionStatus;
        [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(permissionProbeSceneActivated:) name:UISceneDidActivateNotification object:nil];
        [self updatePermissionProbe];
    }
    // Deterministic test fixture: never compiled into Release/App Store builds.
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-reset"]) {
        [NSUserDefaults.standardUserDefaults removeObjectForKey:@"colorArray"];
        [NSUserDefaults.standardUserDefaults removeObjectForKey:@"colorArrayRecoveryBackup"];
    }
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-image"]) {
        self.navigationItem.leftBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:@"Sample Fixture" style:UIBarButtonItemStylePlain target:self action:@selector(openFixture)];
    }
#endif
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    // Large text needs the full width of each source title; the bounded region scrolls vertically.
    BOOL wide = self.view.bounds.size.width > self.view.bounds.size.height && !UIContentSizeCategoryIsAccessibilityCategory(self.traitCollection.preferredContentSizeCategory);
    UILayoutConstraintAxis axis = wide ? UILayoutConstraintAxisHorizontal : UILayoutConstraintAxisVertical;
    if (self.sourceButtons.axis != axis) {
        self.sourceButtons.axis = axis;
        self.sourceButtons.distribution = wide ? UIStackViewDistributionFillEqually : UIStackViewDistributionFill;
    }
    NSArray *symbols = @[@"photo", @"camera", @"viewfinder"];
    BOOL hideIcons = UIContentSizeCategoryIsAccessibilityCategory(self.traitCollection.preferredContentSizeCategory);
    for (UIButton *button in self.sourceButtons.arrangedSubviews) {
        BOOL hasImage = button.configuration.image != nil;
        if (hasImage == hideIcons) {
            UIButtonConfiguration *configuration = button.configuration;
            configuration.image = hideIcons ? nil : [UIImage systemImageNamed:symbols[button.tag]];
            button.configuration = configuration;
        }
    }
}
- (void)viewWillAppear:(BOOL)animated {
    [super viewWillAppear:animated];
    [self reloadHistory];
}
- (void)reloadHistory {
    self.colors = self.store.colors;
    [self.tableView reloadData];
    UILabel *empty = [UILabel new];
    empty.text = NSLocalizedString(@"Your saved colors appear here.\nChoose a photo or use the camera to begin.", nil);
    empty.numberOfLines = 0;
    empty.textAlignment = NSTextAlignmentCenter;
    empty.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    empty.adjustsFontForContentSizeCategory = YES;
    empty.textColor = UIColor.secondaryLabelColor;
    empty.accessibilityIdentifier = @"history.empty";
    empty.translatesAutoresizingMaskIntoConstraints = NO;
    UIScrollView *emptyScroll = [UIScrollView new];
    emptyScroll.accessibilityIdentifier = @"history.emptyScroll";
    [emptyScroll addSubview:empty];
    [NSLayoutConstraint activateConstraints:@[
        [empty.topAnchor constraintEqualToAnchor:emptyScroll.contentLayoutGuide.topAnchor constant:16],
        [empty.bottomAnchor constraintEqualToAnchor:emptyScroll.contentLayoutGuide.bottomAnchor constant:-16],
        [empty.leadingAnchor constraintEqualToAnchor:emptyScroll.contentLayoutGuide.leadingAnchor constant:16],
        [empty.trailingAnchor constraintEqualToAnchor:emptyScroll.contentLayoutGuide.trailingAnchor constant:-16],
        [empty.widthAnchor constraintEqualToAnchor:emptyScroll.frameLayoutGuide.widthAnchor constant:-32]
    ]];
    self.tableView.backgroundView = self.colors.count ? nil : emptyScroll;
}
- (void)showPrivacyButton {
    NSString *title=NSLocalizedString(@"Privacy Policy", nil);
    // The native sidebar's title needs room to grow with Dynamic Type. A labelled
    // privacy symbol keeps the same direct action without a competing long toolbar title.
    UIBarButtonItem *privacy = self.workspaceDelegate
        ? [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"hand.raised"] style:UIBarButtonItemStylePlain target:self action:@selector(openPrivacyPolicy)]
        : [[UIBarButtonItem alloc] initWithTitle:title style:UIBarButtonItemStylePlain target:self action:@selector(openPrivacyPolicy)];
    privacy.accessibilityLabel = title;
    privacy.accessibilityIdentifier = @"privacyPolicy";
    self.navigationItem.rightBarButtonItem = privacy;
}
- (UIViewController *)sourcePresenter { return [self.workspaceDelegate sourcePresenterForPalette:self] ?: self; }
- (void)sourceFlowActive:(BOOL)active { [self.workspaceDelegate palette:self sourceFlowActive:active]; }
- (void)presentSource:(UIViewController *)controller sourceView:(UIView *)sourceView {
    UIViewController *presenter = [self sourcePresenter];
    if (presenter.presentedViewController || self.loading.isAnimating) return;
    [self sourceFlowActive:YES];
    // Anchor a native iPad popover to the selected source when visible, otherwise to the canvas toolbar area.
    if (self.traitCollection.userInterfaceIdiom == UIUserInterfaceIdiomPad && ![controller isKindOfClass:UIImagePickerController.class]) {
        controller.modalPresentationStyle = UIModalPresentationPopover;
        controller.preferredContentSize = CGSizeMake(600,700); // UIKit adapts this to the available window.
        BOOL visible = sourceView.window != nil;
        for (UIView *ancestor = sourceView; visible && ancestor; ancestor = ancestor.superview) {
            CGRect rect = [sourceView convertRect:sourceView.bounds toView:ancestor];
            visible = !ancestor.hidden && ancestor.alpha > 0 && CGRectIntersectsRect(ancestor.bounds,rect);
        }
        UIBarButtonItem *toolbarAnchor = visible ? nil : [self.workspaceDelegate sourceAnchorForPalette:self];
        if (toolbarAnchor) controller.popoverPresentationController.barButtonItem = toolbarAnchor;
        else {
            UIView *anchor = visible ? sourceView : presenter.view;
            controller.popoverPresentationController.sourceView = anchor;
            controller.popoverPresentationController.sourceRect = visible ? anchor.bounds : CGRectMake(CGRectGetMidX(anchor.bounds), anchor.safeAreaInsets.top + 1, 1, 1);
        }
        controller.popoverPresentationController.permittedArrowDirections = UIPopoverArrowDirectionAny;
    }
    controller.presentationController.delegate = self;
    [presenter presentViewController:controller animated:YES completion:nil];
}
- (void)presentationControllerDidDismiss:(UIPresentationController *)presentationController { [self sourceFlowActive:NO]; }
- (void)openPrivacyPolicy {
    if ([self sourcePresenter].presentedViewController || self.loading.isAnimating) return;
    TCPrivacyViewController *document = [TCPrivacyViewController new];
    __weak typeof(self) weakSelf = self;
    document.dismissalHandler = ^{ [weakSelf sourceFlowActive:NO]; };
    UINavigationController *policy = [[UINavigationController alloc] initWithRootViewController:document];
    policy.modalPresentationStyle = UIModalPresentationFullScreen;
    [self sourceFlowActive:YES];
    [[self sourcePresenter] presentViewController:policy animated:YES completion:nil];
}
- (void)showMessage:(NSString *)message {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:NSLocalizedString(@"TouchColor", nil) message:message preferredStyle:UIAlertControllerStyleAlert];
    __weak typeof(self) weakSelf = self;
    [alert addAction:[UIAlertAction actionWithTitle:NSLocalizedString(@"OK", nil) style:UIAlertActionStyleCancel handler:^(UIAlertAction *action) { [weakSelf sourceFlowActive:NO]; }]];
    [self sourceFlowActive:YES];
    [[self sourcePresenter] presentViewController:alert animated:YES completion:nil];
}
- (void)selectSource:(UIButton *)button {
#if DEBUG
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-source-diagnostics"]) {
        UIViewController *presented=[self sourcePresenter].presentedViewController;
        button.accessibilityValue=[NSString stringWithFormat:@"attempt=%lu presented=%@ dismissing=%d loading=%d",(unsigned long)++self.sourceAttempts,presented ? NSStringFromClass(presented.class) : @"none",presented.isBeingDismissed,self.loading.isAnimating];
    }
#endif
    if (self.loading.isAnimating || [self sourcePresenter].presentedViewController) return;
    if (button.tag == 0) [self choosePhoto];
    else if (button.tag == 1) [self takePhoto];
    else [self openLiveColor];
}
- (void)choosePhoto {
    PHPickerConfiguration *configuration = [[PHPickerConfiguration alloc] init];
    configuration.filter = PHPickerFilter.imagesFilter;
    configuration.selectionLimit = 1;
    PHPickerViewController *picker = [[PHPickerViewController alloc] initWithConfiguration:configuration];
    picker.delegate = self;
    [self presentSource:picker sourceView:self.sourceButtons.arrangedSubviews.firstObject];
}
- (void)openLiveColor {
    if ([self sourcePresenter].presentedViewController || self.loading.isAnimating) return;
    [self showCanvas:[ColorRealTimeViewController new]];
}
- (void)showCanvas:(UIViewController *)controller {
    if (self.workspaceDelegate) [self.workspaceDelegate palette:self showCanvas:controller];
    else [self.navigationController pushViewController:controller animated:YES];
}
- (void)takePhoto {
    if ([self sourcePresenter].presentedViewController || self.loading.isAnimating) return;
    BOOL available = [UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypeCamera];
#if DEBUG
    // Simulator-only test route uses the real TCC API/dialog, then stops before camera presentation.
    BOOL permissionProbe = [NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-camera-permission"];
    if (permissionProbe) { available = YES; [self updatePermissionProbe]; }
#endif
    TCCameraAccess access = TCCameraAccessForStatus([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo], available);
    if (access == TCCameraAccessUnavailable) {
        [self showMessage:NSLocalizedString(@"A camera is not available on this device. You can still choose a photo.", nil)];
    } else if (access == TCCameraAccessBlocked) {
        [self showMessage:NSLocalizedString(@"Camera access is off. You can enable it for TouchColor in Settings, or choose a photo instead.", nil)];
    } else if (access == TCCameraAccessAsk) {
        __weak typeof(self) weakSelf = self;
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {
            dispatch_async(dispatch_get_main_queue(), ^{ if ([weakSelf sourcePresenter].view.window && ![weakSelf sourcePresenter].presentedViewController) [weakSelf takePhoto]; });
        }];
    } else {
#if DEBUG
        if (permissionProbe) return;
#endif
        UIImagePickerController *picker = [UIImagePickerController new];
        picker.sourceType = UIImagePickerControllerSourceTypeCamera;
        picker.delegate = self;
        picker.modalPresentationStyle = UIModalPresentationFullScreen;
        [self presentSource:picker sourceView:self.sourceButtons.arrangedSubviews[1]];
    }
}
- (void)showImage:(UIImage *)image {
    if (!image || image.size.width <= 0 || image.size.height <= 0) {
        [self showMessage:NSLocalizedString(@"This image could not be opened. Please choose another photo.", nil)];
        return;
    }
    ColorViewController *controller = [ColorViewController new];
    [controller setChooseImage:image];
    [self showCanvas:controller];
}
- (void)picker:(PHPickerViewController *)picker didFinishPicking:(NSArray<PHPickerResult *> *)results {
    NSUInteger generation = ++self.selectionGeneration;
    [picker dismissViewControllerAnimated:YES completion:^{
        NSItemProvider *provider = results.firstObject.itemProvider;
        if (!provider) { [self sourceFlowActive:NO]; return; } // Cancel retains the current canvas.
        if (![provider canLoadObjectOfClass:UIImage.class]) {
            [self showMessage:NSLocalizedString(@"This image could not be opened. Please choose another photo.", nil)];
            return;
        }
        self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithCustomView:self.loading];
        [self.loading startAnimating];
        [self.workspaceDelegate palette:self loadingPhoto:YES];
        __weak typeof(self) weakSelf = self;
        [provider loadObjectOfClass:UIImage.class completionHandler:^(id<NSItemProviderReading> object, NSError *error) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) self = weakSelf;
                if (!self || generation != self.selectionGeneration) return;
                [self.loading stopAnimating];
                [self.workspaceDelegate palette:self loadingPhoto:NO];
                [self showPrivacyButton];
                [self sourceFlowActive:NO];
                [self showImage:[object isKindOfClass:UIImage.class] ? (UIImage *)object : nil];
            });
        }];
    }];
}
- (void)imagePickerControllerDidCancel:(UIImagePickerController *)picker {
    [picker dismissViewControllerAnimated:YES completion:^{ [self sourceFlowActive:NO]; }];
}
- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary<UIImagePickerControllerInfoKey,id> *)info {
    UIImage *image = info[UIImagePickerControllerOriginalImage];
    [picker dismissViewControllerAnimated:YES completion:^{ [self sourceFlowActive:NO]; [self showImage:image]; }];
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return self.colors.count; }
- (NSString *)tableView:(UITableView *)tableView titleForHeaderInSection:(NSInteger)section {
    // UITableView draws its background behind section headers. The empty-state
    // paragraph already describes the palette and must not share that header area.
    return self.colors.count ? NSLocalizedString(@"Saved Colors", nil) : nil;
}
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [tableView dequeueReusableCellWithIdentifier:@"color"];
    if (!cell) cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleSubtitle reuseIdentifier:@"color"];
    NSString *hex = self.colors[indexPath.row];
    UIListContentConfiguration *content = cell.defaultContentConfiguration;
    content.text = hex;
    content.secondaryText = TCRGBDescription(hex);
    content.image = [UIImage systemImageNamed:@"circle.fill"];
    content.imageProperties.tintColor = TCUIColorFromHex(hex);
    content.textProperties.font = [UIFont preferredFontForTextStyle:UIFontTextStyleHeadline];
    content.textProperties.numberOfLines = 0;
    content.secondaryTextProperties.numberOfLines = 0;
    cell.contentConfiguration = content;
    cell.selectionStyle = self.workspaceDelegate ? UITableViewCellSelectionStyleDefault : UITableViewCellSelectionStyleNone;
    cell.accessoryType = self.workspaceDelegate ? UITableViewCellAccessoryDisclosureIndicator : UITableViewCellAccessoryNone;
    if (self.workspaceDelegate) cell.accessibilityTraits |= UIAccessibilityTraitButton;
    cell.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", hex, TCRGBDescription(hex)];
    return cell;
}
- (void)tableView:(UITableView *)tableView commitEditingStyle:(UITableViewCellEditingStyle)style forRowAtIndexPath:(NSIndexPath *)indexPath {
    if (style == UITableViewCellEditingStyleDelete && [self.store removeColorAtIndex:indexPath.row]) [self reloadHistory];
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES];
    if (self.loading.isAnimating) return;
    if (indexPath.row < self.colors.count) [self.workspaceDelegate palette:self previewSavedColor:self.colors[indexPath.row]];
}
- (void)defaultsChanged:(NSNotification *)notification {
    dispatch_async(dispatch_get_main_queue(), ^{ if (self.isViewLoaded) [self reloadHistory]; });
}
- (void)dealloc { [NSNotificationCenter.defaultCenter removeObserver:self]; }
#if DEBUG
- (void)updatePermissionProbe {
    AVAuthorizationStatus status = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
    NSString *value = status == AVAuthorizationStatusAuthorized ? @"allowed" : status == AVAuthorizationStatusDenied ? @"denied" : status == AVAuthorizationStatusRestricted ? @"restricted" : @"not determined";
    self.permissionStatus.text = [@"Camera: " stringByAppendingString:value];
    self.permissionStatus.accessibilityValue = [NSString stringWithFormat:@"%lu",(unsigned long)self.permissionActivations];
}
- (void)permissionProbeSceneActivated:(NSNotification *)notification {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (notification.object != self.view.window.windowScene) return;
        self.permissionActivations++;
        [self updatePermissionProbe];
    });
}
- (void)openFixture {
    UIGraphicsImageRendererFormat *format = [UIGraphicsImageRendererFormat defaultFormat];
    format.scale = 1;
    format.preferredRange = UIGraphicsImageRendererFormatRangeStandard;
    UIImage *image = [[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(300, 200) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {
        [[UIColor colorWithRed:1 green:0 blue:0 alpha:1] setFill];
        [context fillRect:CGRectMake(0, 0, 300, 200)];
        if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-asymmetric"]) {
            NSArray *colors=@[UIColor.redColor,UIColor.greenColor,UIColor.blueColor,UIColor.cyanColor,UIColor.magentaColor,UIColor.yellowColor];
            for (NSUInteger i=0;i<colors.count;i++) {
                [colors[i] setFill];
                [context fillRect:CGRectMake((i%3)*100,(i/3)*100,100,100)];
            }
        }
    }];
    [self showImage:image];
}
#endif
@end
