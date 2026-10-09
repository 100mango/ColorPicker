#import "ColorMainViewController.h"
#import "TCOriginalDesign.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"
#import "TCColorUtilities.h"
#import <PhotosUI/PhotosUI.h>
#import "TCPrivacyViewController.h"
#import "TouchColor-Swift.h"

#if DEBUG
// Read-only test diagnostics. Touch handling and layout remain UIScrollView's.
@interface TCScrollStateProbe : UIScrollView
@end
@implementation TCScrollStateProbe
- (NSString *)accessibilityValue {
    return [NSString stringWithFormat:@"offsetY=%.3f contentHeight=%.3f boundsHeight=%.3f insetTop=%.3f insetBottom=%.3f canCancelTouches=%d",
        self.contentOffset.y,self.contentSize.height,self.bounds.size.height,
        self.adjustedContentInset.top,self.adjustedContentInset.bottom,self.canCancelContentTouches];
}
@end
#endif

@interface ColorMainViewController () <UITableViewDelegate, UITableViewDataSource, PHPickerViewControllerDelegate, UIImagePickerControllerDelegate, UINavigationControllerDelegate, UIAdaptivePresentationControllerDelegate>
@property (nonatomic, strong) UITableView *tableView;
@property (nonatomic, strong) UIStackView *sourceButtons;
@property (nonatomic, strong) TCColorStore *store;
@property (nonatomic, copy) NSArray<NSString *> *colors;
@property (nonatomic, strong) UIActivityIndicatorView *loading;
@property (nonatomic) NSUInteger selectionGeneration;
@property (nonatomic, strong) UIView *originalHeader;
@property (nonatomic, strong) UIImageView *originalTitle;
@property (nonatomic, strong) UIButton *pickerTab;
@property (nonatomic, strong) UIButton *libraryTab;
@property (nonatomic, strong) UIScrollView *homeScroll;
@property (nonatomic, strong) UIView *homeStage;
@property (nonatomic, strong) UIImageView *originalDroplet;
@property (nonatomic, strong) UIStackView *libraryFooter;
@property (nonatomic, strong) UIButton *aboutButton;
@property (nonatomic, strong) UIButton *importPaletteButton;
@property (nonatomic, strong) UIStackView *loadingPanel;
@property (nonatomic) BOOL libraryVisible;
@property (nonatomic, strong) TCPhotoImportTask *photoImportTask;
#if DEBUG
@property (nonatomic, strong) UILabel *permissionStatus;
@property (nonatomic) NSUInteger permissionActivations;
@property (nonatomic) NSUInteger sourceAttempts;
@property (nonatomic) NSUInteger photoImportAttempts;
#endif
@end
@implementation ColorMainViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title=@"Touch Color";
    self.view.backgroundColor=TCOriginalBackground();
    self.store=[[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(defaultsChanged:) name:NSUserDefaultsDidChangeNotification object:NSUserDefaults.standardUserDefaults];
    self.originalHeader=[UIView new]; self.originalHeader.backgroundColor=TCOriginalDark();
    [self.view addSubview:self.originalHeader];
    self.originalTitle=TCOriginalArtwork(@"00"); [self.originalHeader addSubview:self.originalTitle];
    self.pickerTab=TCOriginalButton(@"112x138",@"112x138 B",NSLocalizedString(@"Color Sources",nil),@"original.picker",self,@selector(showOriginalPicker));
    self.libraryTab=TCOriginalButton(@"320x138",@"320x138 B",NSLocalizedString(@"Saved Colors",nil),@"original.library",self,@selector(showOriginalLibrary));
    [self.originalHeader addSubview:self.pickerTab]; [self.originalHeader addSubview:self.libraryTab];
    self.homeScroll=[UIScrollView new]; self.homeScroll.accessibilityIdentifier=@"sourceControls";
    self.homeScroll.contentInsetAdjustmentBehavior=UIScrollViewContentInsetAdjustmentNever;
    [self.view addSubview:self.homeScroll]; self.homeStage=[UIView new]; [self.homeScroll addSubview:self.homeStage];
    self.originalDroplet=TCOriginalArtwork(@"245x248"); [self.homeStage addSubview:self.originalDroplet];
    self.sourceButtons=[UIStackView new]; self.sourceButtons.axis=UILayoutConstraintAxisVertical;
    self.sourceButtons.distribution=UIStackViewDistributionFillEqually;
    NSArray *art=@[@"117x532",@"117x638",@"117x744"];
    NSArray *titles=@[NSLocalizedString(@"Choose Photo",nil),NSLocalizedString(@"Take Photo",nil),NSLocalizedString(@"Live Color",nil)];
    NSArray *identifiers=@[@"choosePhoto",@"takePhoto",@"liveColor"];
    for (NSUInteger i=0;i<3;i++) {
        UIButton *button=TCOriginalButton(art[i],[art[i] stringByAppendingString:@" B"],titles[i],identifiers[i],self,@selector(selectSource:));
        button.tag=i; [self.sourceButtons addArrangedSubview:button];
    }
    [self.homeStage addSubview:self.sourceButtons];
    self.tableView=[[UITableView alloc] initWithFrame:CGRectZero style:UITableViewStylePlain];
    self.tableView.backgroundColor=TCOriginalBackground(); self.tableView.separatorStyle=UITableViewCellSeparatorStyleNone;
    self.tableView.dataSource=self; self.tableView.delegate=self;
    self.tableView.accessibilityIdentifier=@"colorHistory";
    [self.view addSubview:self.tableView];
    self.libraryFooter=[UIStackView new]; self.libraryFooter.axis=UILayoutConstraintAxisVertical; self.libraryFooter.spacing=4;
    self.importPaletteButton=[UIButton buttonWithType:UIButtonTypeSystem];
    [self.importPaletteButton setTitle:NSLocalizedString(@"Import Palette",nil) forState:UIControlStateNormal];
    self.importPaletteButton.accessibilityIdentifier=@"palette.import.open";
    [self.importPaletteButton addTarget:self action:@selector(openPaletteImport) forControlEvents:UIControlEventTouchUpInside];
    self.aboutButton=[UIButton buttonWithType:UIButtonTypeSystem];
    [self.aboutButton setTitle:NSLocalizedString(@"About",nil) forState:UIControlStateNormal];
    self.aboutButton.accessibilityIdentifier=@"original.about";
    [self.aboutButton addTarget:self action:@selector(openOriginalAbout) forControlEvents:UIControlEventTouchUpInside];
    for (UIButton *button in @[self.importPaletteButton,self.aboutButton]) {
        button.tintColor=TCOriginalText(); button.titleLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleFootnote];
        button.titleLabel.adjustsFontForContentSizeCategory=YES; button.titleLabel.numberOfLines=0;
        [button.heightAnchor constraintGreaterThanOrEqualToConstant:44].active=YES;
        [self.libraryFooter addArrangedSubview:button];
    }
    self.tableView.tableFooterView=self.libraryFooter;
    self.loading=[[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.loading.hidesWhenStopped=YES;
    UIButton *cancel=[UIButton buttonWithType:UIButtonTypeSystem];
    [cancel setTitle:NSLocalizedString(@"Cancel",nil) forState:UIControlStateNormal];
    cancel.titleLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleBody]; cancel.titleLabel.adjustsFontForContentSizeCategory=YES;
    cancel.titleLabel.numberOfLines=0; cancel.accessibilityIdentifier=@"photo.import.cancel";
    [cancel.heightAnchor constraintGreaterThanOrEqualToConstant:44].active=YES;
    [cancel addTarget:self action:@selector(cancelPhotoImport) forControlEvents:UIControlEventTouchUpInside];
    self.loadingPanel=[[UIStackView alloc] initWithArrangedSubviews:@[self.loading,cancel]];
    self.loadingPanel.axis=UILayoutConstraintAxisHorizontal; self.loadingPanel.spacing=12;
    self.loadingPanel.alignment=UIStackViewAlignmentCenter; self.loadingPanel.backgroundColor=TCOriginalBackground();
    self.loadingPanel.hidden=YES; [self.view addSubview:self.loadingPanel];
    [self showOriginalPicker];
#if DEBUG
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-camera-permission"]) {
        self.permissionStatus = [UILabel new];
        self.permissionStatus.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
        self.permissionStatus.accessibilityIdentifier = @"cameraPermissionStatus";
        self.navigationItem.titleView = self.permissionStatus;
        self.permissionStatus.textColor=UIColor.whiteColor;
        self.permissionStatus.backgroundColor=TCOriginalDark();
        [self.originalHeader addSubview:self.permissionStatus];
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
    CGFloat scale=TCOriginalScale(self.view), width=320*scale;
    UIEdgeInsets safe=self.view.safeAreaInsets;
    CGFloat x=(self.view.bounds.size.width-width)/2;
    CGFloat headerHeight=safe.top+76*scale;
    self.originalHeader.frame=CGRectMake(0,0,self.view.bounds.size.width,headerHeight);
    self.originalTitle.frame=CGRectMake(x,safe.top-20*scale,width,96*scale);
    self.pickerTab.frame=CGRectMake(x+56*scale,safe.top+58*scale-22,104*scale,44);
    self.libraryTab.frame=CGRectMake(x+160*scale,safe.top+58*scale-22,104*scale,44);
    CGFloat available=MAX(0,self.view.bounds.size.height-headerHeight-safe.bottom);
    self.homeScroll.frame=CGRectMake(x,headerHeight,width,available);
    CGFloat stageHeight=MAX(472*scale,available);
    self.homeStage.frame=CGRectMake(0,0,width,stageHeight); self.homeScroll.contentSize=self.homeStage.bounds.size;
    CGFloat centerOffset=MAX(0,(stageHeight-472*scale)/2);
    self.originalDroplet.frame=CGRectMake(122.5*scale,centerOffset+59*scale,75.5*scale,115*scale);
    self.sourceButtons.spacing=2*scale;
    self.sourceButtons.frame=CGRectMake(58.5*scale,centerOffset+225*scale,203*scale,157*scale);
    self.tableView.frame=CGRectMake(x,headerHeight,width,available);
    CGFloat footerHeight=MAX(96,2*[UIFont preferredFontForTextStyle:UIFontTextStyleFootnote].lineHeight+48);
    if (fabs(self.libraryFooter.frame.size.width-width)>0.5 || fabs(self.libraryFooter.frame.size.height-footerHeight)>0.5) {
        self.libraryFooter.frame=CGRectMake(0,0,width,footerHeight); self.tableView.tableFooterView=self.libraryFooter;
    }
    CGFloat busyHeight=MAX(56,[UIFont preferredFontForTextStyle:UIFontTextStyleBody].lineHeight+24);
    self.loadingPanel.frame=CGRectMake(x+16,self.view.bounds.size.height-safe.bottom-busyHeight,width-32,busyHeight);
#if DEBUG
    self.permissionStatus.frame=CGRectMake(x+16,safe.top,width-32,30);
#endif
}
- (UIStatusBarStyle)preferredStatusBarStyle { return UIStatusBarStyleLightContent; }
- (void)showOriginalPicker {
    self.libraryVisible=NO; self.pickerTab.selected=YES; self.libraryTab.selected=NO;
    self.homeScroll.hidden=NO; self.tableView.hidden=YES;
}
- (void)showOriginalLibrary {
    self.libraryVisible=YES; self.pickerTab.selected=NO; self.libraryTab.selected=YES;
    self.homeScroll.hidden=YES; self.tableView.hidden=NO; [self reloadHistory];
}
- (void)openOriginalAbout {
    if ([self sourcePresenter].presentedViewController || self.loading.isAnimating) return;
    UIViewController *about=[UIViewController new];
    about.title=NSLocalizedString(@"About",nil); about.view.backgroundColor=TCOriginalBackground();
    about.navigationItem.rightBarButtonItem=[[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemClose target:self action:@selector(closeOriginalAbout)];
    about.navigationItem.rightBarButtonItem.accessibilityIdentifier=@"original.about.close";
    UIButton *policy=[UIButton buttonWithType:UIButtonTypeSystem];
    [policy setTitle:NSLocalizedString(@"Privacy Policy",nil) forState:UIControlStateNormal];
    policy.titleLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleBody]; policy.titleLabel.adjustsFontForContentSizeCategory=YES;
    policy.titleLabel.numberOfLines=0; policy.tintColor=TCOriginalText(); policy.accessibilityIdentifier=@"privacyPolicy";
    [policy addTarget:self action:@selector(openPolicyFromOriginalAbout) forControlEvents:UIControlEventTouchUpInside];
    policy.translatesAutoresizingMaskIntoConstraints=NO; [about.view addSubview:policy];
    [NSLayoutConstraint activateConstraints:@[
        [policy.leadingAnchor constraintEqualToAnchor:about.view.safeAreaLayoutGuide.leadingAnchor constant:24],
        [policy.trailingAnchor constraintEqualToAnchor:about.view.safeAreaLayoutGuide.trailingAnchor constant:-24],
        [policy.topAnchor constraintEqualToAnchor:about.view.safeAreaLayoutGuide.topAnchor constant:24],
        [policy.heightAnchor constraintGreaterThanOrEqualToConstant:44]
    ]];
    UINavigationController *navigation=[[UINavigationController alloc] initWithRootViewController:about];
    [[self sourcePresenter] presentViewController:navigation animated:YES completion:nil];
}
- (void)closeOriginalAbout { [[self sourcePresenter] dismissViewControllerAnimated:YES completion:nil]; }
- (void)openPolicyFromOriginalAbout {
    [[self sourcePresenter] dismissViewControllerAnimated:YES completion:^{ [self openPrivacyPolicy]; }];
}

- (void)viewWillAppear:(BOOL)animated {
    [super viewWillAppear:animated];
    [self.navigationController setNavigationBarHidden:YES animated:NO];
    [self reloadHistory];
}

- (void)reloadHistory {
    self.colors=self.store.colors; [self.tableView reloadData];
    self.tableView.backgroundView=nil;
    [self.view setNeedsLayout];
}

- (void)showPrivacyButton {
    // Policy is reachable from Color Library > About, never a primary home action.
    self.navigationItem.rightBarButtonItems=nil;
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
- (void)openPaletteImport {
    UIViewController *presenter = [self sourcePresenter];
    if (presenter.presentedViewController || self.loading.isAnimating) return;
    [self sourceFlowActive:YES];
    __weak typeof(self) weakSelf = self;
    [TCPaletteImportController presentFrom:presenter completion:^{ [weakSelf sourceFlowActive:NO]; }];
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
    else if (button.tag == 2) [self openLiveColor];
    else if (button.tag == 3) [self openPaletteImport];
}
- (void)choosePhoto {
    PHPickerConfiguration *configuration = [[PHPickerConfiguration alloc] init];
    configuration.filter = PHPickerFilter.imagesFilter;
    configuration.selectionLimit = 1;
    configuration.preferredAssetRepresentationMode = PHPickerConfigurationAssetRepresentationModeCurrent;
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
- (void)beginPhotoLoading {
    [self sourceFlowActive:YES];
    self.loading.accessibilityIdentifier=@"photo.import.loading"; self.loading.isAccessibilityElement=YES;
    self.loading.accessibilityLabel=NSLocalizedString(@"Opening Photo",nil);
    [self.loading startAnimating]; self.loadingPanel.hidden=NO;
    [self.view bringSubviewToFront:self.loadingPanel]; [self.view setNeedsLayout];
    [self.workspaceDelegate palette:self loadingPhoto:YES];
}

- (void)endPhotoLoading {
    [self.loading stopAnimating]; self.loadingPanel.hidden=YES;
    [self showPrivacyButton]; [self.workspaceDelegate palette:self loadingPhoto:NO];
}

- (void)cancelPhotoImport {
    ++self.selectionGeneration;
    [self.photoImportTask cancel];
    self.photoImportTask = nil;
    [self endPhotoLoading];
    [self sourceFlowActive:NO];
}
- (void)loadPhotoFromProvider:(NSItemProvider *)provider {
    NSUInteger generation = ++self.selectionGeneration;
    [self.photoImportTask cancel];
    self.photoImportTask = nil;
    [self beginPhotoLoading];
    __weak typeof(self) weakSelf = self;
    void (^startImport)(void) = ^{
        typeof(self) self = weakSelf;
        if (!self || generation != self.selectionGeneration) return;
        self.photoImportTask = [TCPhotoImportTask loadProvider:provider completion:^(UIImage *image, NSError *error) {
            typeof(self) self = weakSelf;
            if (!self || generation != self.selectionGeneration) return;
            self.photoImportTask = nil;
            [self endPhotoLoading];
            if (error) {
                // Keep the current canvas and keep live capture paused until the native alert closes.
                [self showMessage:error.localizedDescription];
            } else {
                if (image) [self showImage:image];
                [self sourceFlowActive:NO];
            }
        }];
    };
#if DEBUG
    // Exercise the real loading Cancel control before a provider request starts.
    // The actual file selection and decoding paths remain the production paths.
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-delay-photo-import"] && ++self.photoImportAttempts == 2) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,8*NSEC_PER_SEC),dispatch_get_main_queue(),startImport);
        return;
    }
#endif
    startImport();
}
- (void)picker:(PHPickerViewController *)picker didFinishPicking:(NSArray<PHPickerResult *> *)results {
    NSUInteger dismissalGeneration = ++self.selectionGeneration;
    [self.photoImportTask cancel];
    self.photoImportTask = nil;
    [picker dismissViewControllerAnimated:YES completion:^{
        if (dismissalGeneration != self.selectionGeneration) return;
        NSItemProvider *provider = results.firstObject.itemProvider;
        if (!provider) { [self endPhotoLoading]; [self sourceFlowActive:NO]; return; }
        [self loadPhotoFromProvider:provider];
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
- (NSString *)tableView:(UITableView *)tableView titleForHeaderInSection:(NSInteger)section { return nil; }

- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell=[tableView dequeueReusableCellWithIdentifier:@"original.color"];
    if (!cell) {
        cell=[[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:@"original.color"];
        TCOriginalReadout *readout=[TCOriginalReadout new]; readout.tag=601; readout.historyRow=YES;
        readout.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
        [cell.contentView addSubview:readout]; cell.selectionStyle=UITableViewCellSelectionStyleNone;
    }
    TCOriginalReadout *readout=[cell.contentView viewWithTag:601];
    readout.frame=cell.contentView.bounds; readout.hex=self.colors[indexPath.row];
    cell.backgroundColor=TCOriginalBackground();
    return cell;
}
- (CGFloat)tableView:(UITableView *)tableView heightForRowAtIndexPath:(NSIndexPath *)indexPath {
    TCOriginalReadout *readout=[TCOriginalReadout new]; readout.historyRow=YES;
    return [readout preferredHeightForWidth:tableView.bounds.size.width traits:tableView.traitCollection];
}

- (void)tableView:(UITableView *)tableView commitEditingStyle:(UITableViewCellEditingStyle)style forRowAtIndexPath:(NSIndexPath *)indexPath {
    if (style == UITableViewCellEditingStyleDelete && [self.store removeColorAtIndex:indexPath.row]) [self reloadHistory];
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES];
    if (self.loading.isAnimating) return;
    if (indexPath.row >= self.colors.count) return;
    if (self.workspaceDelegate) [self.workspaceDelegate palette:self previewSavedColor:self.colors[indexPath.row]];
    else if (self.traitCollection.userInterfaceIdiom == UIUserInterfaceIdiomPad) {
        NSString *hex=self.colors[indexPath.row];
        UIAlertController *preview=[UIAlertController alertControllerWithTitle:hex message:TCRGBDescription(hex) preferredStyle:UIAlertControllerStyleAlert];
        [preview addAction:[UIAlertAction actionWithTitle:NSLocalizedString(@"Close",nil) style:UIAlertActionStyleCancel handler:nil]];
        [self presentViewController:preview animated:YES completion:nil];
    }
}
- (void)traitCollectionDidChange:(UITraitCollection *)previous {
    [super traitCollectionDidChange:previous];
    if (![previous.preferredContentSizeCategory isEqual:self.traitCollection.preferredContentSizeCategory]) { [self.tableView reloadData]; [self.view setNeedsLayout]; }
}
- (BOOL)canBecomeFirstResponder { return YES; }
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; [self becomeFirstResponder]; }
- (NSArray<UIKeyCommand *> *)keyCommands {
    if ([self sourcePresenter].presentedViewController || self.loading.isAnimating) return @[];
    UIKeyCommand *photo=[UIKeyCommand keyCommandWithInput:@"o" modifierFlags:UIKeyModifierCommand action:@selector(choosePhoto)];
    photo.discoverabilityTitle=NSLocalizedString(@"Choose Photo",nil);
    UIKeyCommand *camera=[UIKeyCommand keyCommandWithInput:@"o" modifierFlags:UIKeyModifierCommand|UIKeyModifierShift action:@selector(takePhoto)];
    camera.discoverabilityTitle=NSLocalizedString(@"Take Photo",nil);
    UIKeyCommand *live=[UIKeyCommand keyCommandWithInput:@"l" modifierFlags:UIKeyModifierCommand action:@selector(openLiveColor)];
    live.discoverabilityTitle=NSLocalizedString(@"Live Color",nil);
    UIKeyCommand *library=[UIKeyCommand keyCommandWithInput:@"1" modifierFlags:UIKeyModifierCommand action:@selector(showOriginalLibrary)];
    library.discoverabilityTitle=NSLocalizedString(@"Saved Colors",nil);
    return @[photo,camera,live,library];
}
- (void)defaultsChanged:(NSNotification *)notification {
    dispatch_async(dispatch_get_main_queue(), ^{ if (self.isViewLoaded) [self reloadHistory]; });
}
- (void)dealloc { [_photoImportTask cancel]; [NSNotificationCenter.defaultCenter removeObserver:self]; }
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

