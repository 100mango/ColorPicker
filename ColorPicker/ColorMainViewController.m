#import "ColorMainViewController.h"
#import "ColorViewController.h"
#import "ColorRealTimeViewController.h"
#import "TCColorUtilities.h"
#import <PhotosUI/PhotosUI.h>

@interface ColorMainViewController () <UITableViewDelegate, UITableViewDataSource, PHPickerViewControllerDelegate, UIImagePickerControllerDelegate, UINavigationControllerDelegate>
@property (nonatomic, strong) UITableView *tableView;
@property (nonatomic, strong) TCColorStore *store;
@property (nonatomic, copy) NSArray<NSString *> *colors;
@property (nonatomic, strong) UIActivityIndicatorView *loading;
@property (nonatomic) NSUInteger selectionGeneration;
@end
@implementation ColorMainViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = @"TouchColor";
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.store = [[TCColorStore alloc] initWithDefaults:NSUserDefaults.standardUserDefaults];
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
    buttons.axis = UILayoutConstraintAxisVertical;
    buttons.spacing = 8;
    buttons.translatesAutoresizingMaskIntoConstraints = NO;
    for (NSUInteger i = 0; i < titles.count; i++) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
        UIButtonConfiguration *configuration = UIButtonConfiguration.tintedButtonConfiguration;
        configuration.title = titles[i];
        configuration.image = [UIImage systemImageNamed:symbols[i]];
        configuration.imagePadding = 10;
        button.configuration = configuration;
        button.accessibilityIdentifier = identifiers[i];
        button.tag = i;
        [button.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
        [button addTarget:self action:@selector(selectSource:) forControlEvents:UIControlEventTouchUpInside];
        [buttons addArrangedSubview:button];
    }
    [self.view addSubview:buttons];
    self.loading = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.loading.hidesWhenStopped = YES;
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithCustomView:self.loading];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [buttons.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [buttons.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [buttons.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-8],
        [self.tableView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.tableView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.tableView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.tableView.bottomAnchor constraintEqualToAnchor:buttons.topAnchor constant:-8]
    ]];
#if DEBUG
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
- (void)viewWillAppear:(BOOL)animated {
    [super viewWillAppear:animated];
    self.colors = self.store.colors;
    [self.tableView reloadData];
    UILabel *empty = [UILabel new];
    empty.text = NSLocalizedString(@"Your saved colors appear here.\nChoose a photo or use the camera to begin.", nil);
    empty.numberOfLines = 0;
    empty.textAlignment = NSTextAlignmentCenter;
    empty.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    empty.adjustsFontForContentSizeCategory = YES;
    empty.textColor = UIColor.secondaryLabelColor;
    self.tableView.backgroundView = self.colors.count ? nil : empty;
}
- (void)showMessage:(NSString *)message {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:NSLocalizedString(@"TouchColor", nil) message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:NSLocalizedString(@"OK", nil) style:UIAlertActionStyleCancel handler:nil]];
    [self presentViewController:alert animated:YES completion:nil];
}
- (void)selectSource:(UIButton *)button {
    if (self.loading.isAnimating) return;
    if (button.tag == 0) {
        PHPickerConfiguration *configuration = [[PHPickerConfiguration alloc] init];
        configuration.filter = PHPickerFilter.imagesFilter;
        configuration.selectionLimit = 1;
        PHPickerViewController *picker = [[PHPickerViewController alloc] initWithConfiguration:configuration];
        picker.delegate = self;
        [self presentViewController:picker animated:YES completion:nil];
    } else if (button.tag == 1) {
        [self takePhoto];
    } else {
        [self.navigationController pushViewController:[ColorRealTimeViewController new] animated:YES];
    }
}
- (void)takePhoto {
    BOOL available = [UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypeCamera];
    TCCameraAccess access = TCCameraAccessForStatus([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo], available);
    if (access == TCCameraAccessUnavailable) {
        [self showMessage:NSLocalizedString(@"A camera is not available on this device. You can still choose a photo.", nil)];
    } else if (access == TCCameraAccessBlocked) {
        [self showMessage:NSLocalizedString(@"Camera access is off. You can enable it for TouchColor in Settings, or choose a photo instead.", nil)];
    } else if (access == TCCameraAccessAsk) {
        __weak typeof(self) weakSelf = self;
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {
            dispatch_async(dispatch_get_main_queue(), ^{ if (weakSelf.view.window && !weakSelf.presentedViewController) [weakSelf takePhoto]; });
        }];
    } else {
        UIImagePickerController *picker = [UIImagePickerController new];
        picker.sourceType = UIImagePickerControllerSourceTypeCamera;
        picker.delegate = self;
        picker.modalPresentationStyle = UIModalPresentationFullScreen;
        [self presentViewController:picker animated:YES completion:nil];
    }
}
- (void)showImage:(UIImage *)image {
    if (!image || image.size.width <= 0 || image.size.height <= 0) {
        [self showMessage:NSLocalizedString(@"This image could not be opened. Please choose another photo.", nil)];
        return;
    }
    ColorViewController *controller = [ColorViewController new];
    [controller setChooseImage:image];
    [self.navigationController pushViewController:controller animated:YES];
}
- (void)picker:(PHPickerViewController *)picker didFinishPicking:(NSArray<PHPickerResult *> *)results {
    NSUInteger generation = ++self.selectionGeneration;
    [picker dismissViewControllerAnimated:YES completion:^{
        NSItemProvider *provider = results.firstObject.itemProvider;
        if (!provider) return; // Cancel leaves both history and navigation unchanged.
        if (![provider canLoadObjectOfClass:UIImage.class]) {
            [self showMessage:NSLocalizedString(@"This image could not be opened. Please choose another photo.", nil)];
            return;
        }
        [self.loading startAnimating];
        __weak typeof(self) weakSelf = self;
        [provider loadObjectOfClass:UIImage.class completionHandler:^(id<NSItemProviderReading> object, NSError *error) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) self = weakSelf;
                if (!self || generation != self.selectionGeneration) return;
                [self.loading stopAnimating];
                [self showImage:[object isKindOfClass:UIImage.class] ? (UIImage *)object : nil];
            });
        }];
    }];
}
- (void)imagePickerControllerDidCancel:(UIImagePickerController *)picker {
    [picker dismissViewControllerAnimated:YES completion:nil];
}
- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary<UIImagePickerControllerInfoKey,id> *)info {
    UIImage *image = info[UIImagePickerControllerOriginalImage];
    [picker dismissViewControllerAnimated:YES completion:^{ [self showImage:image]; }];
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return self.colors.count; }
- (NSString *)tableView:(UITableView *)tableView titleForHeaderInSection:(NSInteger)section { return NSLocalizedString(@"Saved Colors", nil); }
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
    cell.contentConfiguration = content;
    cell.selectionStyle = UITableViewCellSelectionStyleNone;
    cell.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", hex, TCRGBDescription(hex)];
    return cell;
}
- (void)tableView:(UITableView *)tableView commitEditingStyle:(UITableViewCellEditingStyle)style forRowAtIndexPath:(NSIndexPath *)indexPath {
    if (style == UITableViewCellEditingStyleDelete && [self.store removeColorAtIndex:indexPath.row]) [self viewWillAppear:NO];
}
#if DEBUG
- (void)openFixture {
    UIGraphicsImageRendererFormat *format = [UIGraphicsImageRendererFormat defaultFormat];
    format.scale = 1;
    format.preferredRange = UIGraphicsImageRendererFormatRangeStandard;
    UIImage *image = [[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(200, 200) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {
        [[UIColor colorWithRed:1 green:0 blue:0 alpha:1] setFill];
        [context fillRect:CGRectMake(0, 0, 200, 200)];
    }];
    [self showImage:image];
}
#endif
@end
