#import "TCPrivacyViewController.h"
#import <WebKit/WebKit.h>
BOOL TCPrivacyAllowsDocumentURL(NSURL *URL) {
    if (!URL) return NO;
    NSURLComponents *parts = [NSURLComponents componentsWithURL:URL resolvingAgainstBaseURL:NO];
    return [parts.scheme.lowercaseString isEqualToString:@"https"] &&
        [parts.host.lowercaseString isEqualToString:@"100mango.github.io"] &&
        [parts.path isEqualToString:@"/app-privacy/"] && !parts.query.length && !parts.user.length && !parts.password.length &&
        (!parts.port || parts.port.integerValue == 443);
}
BOOL TCPrivacyAllowsContactURL(NSURL *URL, BOOL userActivated) {
    if (!URL || !userActivated) return NO;
    NSURLComponents *parts = [NSURLComponents componentsWithURL:URL resolvingAgainstBaseURL:NO];
    return [parts.scheme.lowercaseString isEqualToString:@"mailto"] &&
        [parts.path.lowercaseString isEqualToString:@"100mango@gmail.com"] && !parts.query.length && !parts.fragment.length &&
        !parts.host.length && !parts.user.length && !parts.password.length && !parts.port;
}
@interface TCPrivacyViewController () <WKNavigationDelegate>
@property (nonatomic, strong) WKWebView *webView;
@property (nonatomic, strong) UIStackView *errorView;
@property (nonatomic, strong) UIActivityIndicatorView *activity;
@property (nonatomic) BOOL closing;
#if DEBUG
@property (nonatomic) BOOL simulatedOfflineOnce;
#endif
@end
@implementation TCPrivacyViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = NSLocalizedString(@"Privacy Policy", nil);
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.navigationItem.leftBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:NSLocalizedString(@"Close", nil) style:UIBarButtonItemStyleDone target:self action:@selector(close)];
    self.navigationItem.leftBarButtonItem.accessibilityIdentifier = @"privacy.close";
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    configuration.defaultWebpagePreferences.allowsContentJavaScript = NO;
    self.webView = [[WKWebView alloc] initWithFrame:CGRectZero configuration:configuration];
    self.webView.navigationDelegate = self;
    self.webView.accessibilityIdentifier = @"privacy.content";
    self.webView.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.webView];
    self.activity = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.activity.hidesWhenStopped = YES;
    self.activity.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.activity];
    UILabel *message = [UILabel new];
    message.text = NSLocalizedString(@"The privacy policy could not load. Check your connection and try again.", nil);
    message.accessibilityIdentifier = @"privacy.error";
    message.numberOfLines = 0;
    message.textAlignment = NSTextAlignmentCenter;
    message.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    message.adjustsFontForContentSizeCategory = YES;
    UIButton *retry = [UIButton buttonWithType:UIButtonTypeSystem];
    [retry setTitle:NSLocalizedString(@"Retry", nil) forState:UIControlStateNormal];
    retry.accessibilityIdentifier = @"privacy.retry";
    [retry addTarget:self action:@selector(loadPolicy) forControlEvents:UIControlEventTouchUpInside];
    [retry.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    self.errorView = [[UIStackView alloc] initWithArrangedSubviews:@[message, retry]];
    self.errorView.axis = UILayoutConstraintAxisVertical;
    self.errorView.spacing = 16;
    self.errorView.translatesAutoresizingMaskIntoConstraints = NO;
    self.errorView.hidden = YES;
    [self.view addSubview:self.errorView];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.webView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.webView.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [self.webView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.webView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.activity.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [self.activity.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [self.errorView.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [self.errorView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:24],
        [self.errorView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-24]
    ]];
    [self loadPolicy];
}
- (void)loadPolicy {
    if (self.closing) return;
#if DEBUG
    // Deterministic offline recovery test; excluded from every Release build.
    if (!self.simulatedOfflineOnce && [NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-policy-offline"]) {
        self.simulatedOfflineOnce = YES;
        [self showLoadError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorNotConnectedToInternet userInfo:nil]];
        return;
    }
#endif
    self.errorView.hidden = YES;
    self.webView.hidden = NO;
    [self.activity startAnimating];
    NSURL *URL = [NSURL URLWithString:@"https://100mango.github.io/app-privacy/"];
    [self.webView loadRequest:[NSURLRequest requestWithURL:URL cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:20]];
}
- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [self.activity stopAnimating];
}
- (void)showLoadError:(NSError *)error {
    if (self.closing || ([error.domain isEqualToString:NSURLErrorDomain] && error.code == NSURLErrorCancelled)) return;
    [self.activity stopAnimating];
    self.errorView.hidden = NO;
    self.webView.hidden = YES;
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self showLoadError:error]; }
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self showLoadError:error]; }
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [self showLoadError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorUnknown userInfo:nil]];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    BOOL allowed = TCPrivacyAllowsDocumentURL(response.response.URL);
    if ([response.response isKindOfClass:NSHTTPURLResponse.class] && [(NSHTTPURLResponse *)response.response statusCode] >= 400) allowed = NO;
    if (!allowed) [self showLoadError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorBadServerResponse userInfo:nil]];
    decisionHandler(allowed ? WKNavigationResponsePolicyAllow : WKNavigationResponsePolicyCancel);
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    if (TCPrivacyAllowsContactURL(action.request.URL, action.navigationType == WKNavigationTypeLinkActivated)) {
        [UIApplication.sharedApplication openURL:action.request.URL options:@{} completionHandler:nil];
    }
    decisionHandler(TCPrivacyAllowsDocumentURL(action.request.URL) ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
- (void)close {
    if (self.closing) return;
    self.closing = YES;
    [self.webView stopLoading];
    UIViewController *presentation = self.navigationController ?: self;
    [presentation dismissViewControllerAnimated:YES completion:nil];
}
@end
