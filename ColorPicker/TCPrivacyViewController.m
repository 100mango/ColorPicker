#import "TCPrivacyViewController.h"

@interface TCPrivacyViewController ()
@property (nonatomic, strong) UIButton *contactButton;
@property (nonatomic, strong) UIButton *browserButton;
@property (nonatomic, strong) UILabel *externalError;
@property (nonatomic) BOOL closing;
@property (nonatomic) BOOL opening;
@end

@implementation TCPrivacyViewController
- (NSString *)textForLanguage:(NSString *)language key:(NSString *)key {
    NSString *path = [NSBundle.mainBundle pathForResource:language ofType:@"lproj"];
    NSBundle *bundle = path ? [NSBundle bundleWithPath:path] : nil;
    return [bundle localizedStringForKey:key value:@"" table:@"Localizable"] ?: @"";
}
- (UILabel *)labelWithText:(NSString *)text identifier:(NSString *)identifier style:(UIFontTextStyle)style {
    UILabel *label = [UILabel new];
    label.text = text;
    label.accessibilityIdentifier = identifier;
    label.font = [UIFont preferredFontForTextStyle:style];
    label.adjustsFontForContentSizeCategory = YES;
    label.textColor = UIColor.labelColor;
    label.numberOfLines = 0;
    [label setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical];
    return label;
}
- (UITextView *)bodyForLanguage:(NSString *)language {
    UITextView *body = [UITextView new];
    body.text = [self textForLanguage:language key:@"Approved Privacy Body"];
    body.accessibilityIdentifier = [@"privacy.body." stringByAppendingString:language];
    body.accessibilityLanguage = [language isEqualToString:@"zh-Hans"] ? @"zh-Hans" : @"en";
    body.editable = NO;
    body.selectable = YES;
    body.scrollEnabled = NO; // The content scroll view owns vertical scrolling.
    body.dataDetectorTypes = UIDataDetectorTypeNone;
    body.textContainerInset = UIEdgeInsetsZero;
    body.textContainer.lineFragmentPadding = 0;
    body.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    body.adjustsFontForContentSizeCategory = YES;
    body.textColor = UIColor.labelColor;
    body.backgroundColor = UIColor.clearColor;
    [body setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical];
    return body;
}
- (UIButton *)actionWithTitle:(NSString *)title identifier:(NSString *)identifier action:(SEL)action {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
    UIButtonConfiguration *configuration = UIButtonConfiguration.tintedButtonConfiguration;
    configuration.title = title;
    configuration.titleLineBreakMode = NSLineBreakByWordWrapping;
    configuration.titleTextAttributesTransformer = ^NSDictionary *(NSDictionary *attributes) {
        NSMutableDictionary *result = [attributes mutableCopy];
        result[NSFontAttributeName] = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
        return result;
    };
    button.configuration = configuration;
    button.titleLabel.numberOfLines = 0;
    button.accessibilityIdentifier = identifier;
    [button setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical];
    [button.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    [button addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    return button;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = NSLocalizedString(@"Privacy Policy", nil);
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.navigationItem.leftBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:NSLocalizedString(@"Close", nil) style:UIBarButtonItemStyleDone target:self action:@selector(close)];
    self.navigationItem.leftBarButtonItem.accessibilityIdentifier = @"privacy.close";

    UILabel *chinese = [self labelWithText:@"中文" identifier:@"privacy.heading.zh-Hans" style:UIFontTextStyleHeadline];
    chinese.accessibilityTraits |= UIAccessibilityTraitHeader;
    UILabel *english = [self labelWithText:@"English" identifier:@"privacy.heading.en" style:UIFontTextStyleHeadline];
    english.accessibilityTraits |= UIAccessibilityTraitHeader;
    UIStackView *paragraphs = [[UIStackView alloc] initWithArrangedSubviews:@[chinese, [self bodyForLanguage:@"zh-Hans"], english, [self bodyForLanguage:@"en"]]];
    paragraphs.axis = UILayoutConstraintAxisVertical;
    paragraphs.spacing = 16;
    paragraphs.translatesAutoresizingMaskIntoConstraints = NO;
    UIScrollView *content = [UIScrollView new];
    content.accessibilityIdentifier = @"privacy.content";
    content.translatesAutoresizingMaskIntoConstraints = NO;
    content.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
    [self.view addSubview:content];
    [content addSubview:paragraphs];

    UILabel *englishNotice = [self labelWithText:[self textForLanguage:@"en" key:@"External Privacy Website Notice"] identifier:@"privacy.notice.en" style:UIFontTextStyleFootnote];
    UILabel *chineseNotice = [self labelWithText:[self textForLanguage:@"zh-Hans" key:@"External Privacy Website Notice"] identifier:@"privacy.notice.zh-Hans" style:UIFontTextStyleFootnote];
    englishNotice.accessibilityLanguage = @"en";
    chineseNotice.accessibilityLanguage = @"zh-Hans";
    self.contactButton = [self actionWithTitle:NSLocalizedString(@"Contact Developer", nil) identifier:@"privacy.contact" action:@selector(contactDeveloper)];
    self.browserButton = [self actionWithTitle:NSLocalizedString(@"Open in Browser", nil) identifier:@"privacy.externalPolicy" action:@selector(openPolicyInBrowser)];
    self.externalError = [self labelWithText:@"" identifier:@"privacy.externalError" style:UIFontTextStyleBody];
    self.externalError.hidden = YES;
    UIStackView *actions = [[UIStackView alloc] initWithArrangedSubviews:@[englishNotice, chineseNotice, self.contactButton, self.browserButton, self.externalError]];
    actions.axis = UILayoutConstraintAxisVertical;
    actions.spacing = 8;
    actions.translatesAutoresizingMaskIntoConstraints = NO;
    UIScrollView *actionScroll = [UIScrollView new];
    actionScroll.accessibilityIdentifier = @"privacy.actions";
    actionScroll.translatesAutoresizingMaskIntoConstraints = NO;
    actionScroll.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
    [self.view addSubview:actionScroll];
    [actionScroll addSubview:actions];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    NSLayoutConstraint *naturalActions = [actionScroll.heightAnchor constraintEqualToAnchor:actions.heightAnchor constant:16];
    naturalActions.priority = UILayoutPriorityDefaultHigh;
    [NSLayoutConstraint activateConstraints:@[
        [content.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [content.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [content.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [content.bottomAnchor constraintEqualToAnchor:actionScroll.topAnchor constant:-8],
        [actionScroll.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [actionScroll.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [actionScroll.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [actionScroll.heightAnchor constraintGreaterThanOrEqualToConstant:44],
        [actionScroll.heightAnchor constraintLessThanOrEqualToAnchor:safe.heightAnchor multiplier:0.45],
        naturalActions,
        [paragraphs.topAnchor constraintEqualToAnchor:content.contentLayoutGuide.topAnchor constant:16],
        [paragraphs.bottomAnchor constraintEqualToAnchor:content.contentLayoutGuide.bottomAnchor constant:-16],
        [paragraphs.leadingAnchor constraintEqualToAnchor:content.contentLayoutGuide.leadingAnchor constant:20],
        [paragraphs.trailingAnchor constraintEqualToAnchor:content.contentLayoutGuide.trailingAnchor constant:-20],
        [paragraphs.widthAnchor constraintEqualToAnchor:content.frameLayoutGuide.widthAnchor constant:-40],
        [actions.topAnchor constraintEqualToAnchor:actionScroll.contentLayoutGuide.topAnchor constant:8],
        [actions.bottomAnchor constraintEqualToAnchor:actionScroll.contentLayoutGuide.bottomAnchor constant:-8],
        [actions.leadingAnchor constraintEqualToAnchor:actionScroll.contentLayoutGuide.leadingAnchor constant:20],
        [actions.trailingAnchor constraintEqualToAnchor:actionScroll.contentLayoutGuide.trailingAnchor constant:-20],
        [actions.widthAnchor constraintEqualToAnchor:actionScroll.frameLayoutGuide.widthAnchor constant:-40]
    ]];
}
- (void)openExternalURL:(NSURL *)URL completion:(void (^)(BOOL))completion {
    [UIApplication.sharedApplication openURL:URL options:@{} completionHandler:completion];
}
- (void)beginExternalURL:(NSURL *)URL failureText:(NSString *)failureText {
    if (self.closing || self.opening) return;
    self.opening = YES;
    self.contactButton.enabled = NO;
    self.browserButton.enabled = NO;
    self.externalError.hidden = YES;
    __weak typeof(self) weakSelf = self;
    [self openExternalURL:URL completion:^(BOOL opened) {
        dispatch_async(dispatch_get_main_queue(), ^{
            TCPrivacyViewController *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.closing || !strongSelf.opening) return;
            strongSelf.opening = NO;
            strongSelf.contactButton.enabled = YES;
            strongSelf.browserButton.enabled = YES;
            strongSelf.externalError.text = opened ? @"" : failureText;
            strongSelf.externalError.hidden = opened;
        });
    }];
}
- (void)contactDeveloper {
    [self beginExternalURL:[NSURL URLWithString:@"mailto:100mango@gmail.com"] failureText:NSLocalizedString(@"Mail could not be opened. You can copy the email address from the policy.", nil)];
}
- (void)openPolicyInBrowser {
    [self beginExternalURL:[NSURL URLWithString:@"https://100mango.github.io/app-privacy/"] failureText:NSLocalizedString(@"The browser could not be opened. The complete policy remains available here.", nil)];
}
- (void)close {
    if (self.closing) return;
    self.closing = YES;
    UIViewController *presentation = self.navigationController ?: self;
    [presentation dismissViewControllerAnimated:YES completion:self.dismissalHandler];
}
@end
