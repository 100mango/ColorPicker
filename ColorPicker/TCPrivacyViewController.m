#import "TCPrivacyViewController.h"
#import <WebKit/WebKit.h>
#import <CommonCrypto/CommonDigest.h>
BOOL TCPrivacyAllowsDocumentURL(NSURL *URL) {
    if (!URL) return NO;
    NSURLComponents *parts = [NSURLComponents componentsWithURL:URL resolvingAgainstBaseURL:NO];
    return [parts.scheme.lowercaseString isEqualToString:@"about"] &&
        [parts.path isEqualToString:@"blank"] && !parts.query && !parts.host &&
        !parts.user && !parts.password && !parts.port;
}
BOOL TCPrivacyAllowsResponse(NSURLResponse *response) {
    return response && ![response isKindOfClass:NSHTTPURLResponse.class] &&
        TCPrivacyAllowsDocumentURL(response.URL) && [response.MIMEType.lowercaseString isEqualToString:@"text/html"];
}
BOOL TCPrivacyAllowsPublishedURL(NSURL *URL, BOOL userActivated) {
    // Exact spelling intentionally rejects queries, fragments, credentials and alternate ports.
    return userActivated && [URL.absoluteString isEqualToString:@"https://100mango.github.io/app-privacy/"];
}
NSString *TCPrivacyPolicyHTML(NSData *data) {
    // This digest pins the reviewed self-contained document, including its CSP and approved copy.
    // A changed or malformed resource must show local recovery, never an HTTP fallback.
    if (!data || data.length != 2916) return nil;
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *hex = [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (NSUInteger index = 0; index < CC_SHA256_DIGEST_LENGTH; index++) [hex appendFormat:@"%02x", digest[index]];
    if (![hex isEqualToString:@"390d6c30ab0f52031417981d7477c8553572402dd9d5757bf1ccbf4e6ea0c986"]) return nil;
    return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
}
BOOL TCPrivacyAllowsContactURL(NSURL *URL, BOOL userActivated) {
    if (!URL || !userActivated) return NO;
    NSURLComponents *parts = [NSURLComponents componentsWithURL:URL resolvingAgainstBaseURL:NO];
    return [parts.scheme.lowercaseString isEqualToString:@"mailto"] &&
        [parts.path.lowercaseString isEqualToString:@"100mango@gmail.com"] && !parts.query && !parts.fragment &&
        !parts.host && !parts.user && !parts.password && !parts.port;
}
@interface TCPrivacyViewController () <WKNavigationDelegate>
@property (nonatomic, strong) WKWebView *webView;
@property (nonatomic, strong) UIStackView *errorView;
@property (nonatomic, strong) UIScrollView *errorScroll;
@property (nonatomic, strong) UIActivityIndicatorView *activity;
@property (nonatomic) BOOL closing;
#if DEBUG
@property (nonatomic) BOOL simulatedLocalErrorOnce;
#endif
@end
@implementation TCPrivacyViewController
- (WKWebView *)makePolicyWebViewWithConfiguration:(WKWebViewConfiguration *)configuration {
    return [[WKWebView alloc] initWithFrame:CGRectZero configuration:configuration];
}
- (NSURL *)policyResourceURL {
    return [NSBundle.mainBundle URLForResource:@"PrivacyPolicy" withExtension:@"html"];
}
- (void)openExternalPolicyURL:(NSURL *)URL {
    [UIApplication.sharedApplication openURL:URL options:@{} completionHandler:nil];
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = NSLocalizedString(@"Privacy Policy", nil);
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.navigationItem.leftBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:NSLocalizedString(@"Close", nil) style:UIBarButtonItemStyleDone target:self action:@selector(close)];
    self.navigationItem.leftBarButtonItem.accessibilityIdentifier = @"privacy.close";
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    configuration.dataDetectorTypes = WKDataDetectorTypeNone;
    configuration.defaultWebpagePreferences.allowsContentJavaScript = NO;
    self.webView = [self makePolicyWebViewWithConfiguration:configuration];
    self.webView.allowsLinkPreview = NO;
    self.webView.navigationDelegate = self;
    self.webView.accessibilityIdentifier = @"privacy.content";
    self.webView.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.webView];
    self.activity = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.activity.hidesWhenStopped = YES;
    self.activity.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.activity];
    UILabel *message = [UILabel new];
    message.text = NSLocalizedString(@"The local privacy policy could not load. Reload to try again.", nil);
    message.accessibilityIdentifier = @"privacy.error";
    message.numberOfLines = 0;
    message.textAlignment = NSTextAlignmentCenter;
    message.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    message.adjustsFontForContentSizeCategory = YES;
    UIButton *retry = [UIButton buttonWithType:UIButtonTypeSystem];
    [retry setTitle:NSLocalizedString(@"Reload", nil) forState:UIControlStateNormal];
    retry.accessibilityIdentifier = @"privacy.retry";
    retry.titleLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    retry.titleLabel.adjustsFontForContentSizeCategory = YES;
    [retry addTarget:self action:@selector(loadPolicy) forControlEvents:UIControlEventTouchUpInside];
    [retry.heightAnchor constraintGreaterThanOrEqualToConstant:44].active = YES;
    self.errorView = [[UIStackView alloc] initWithArrangedSubviews:@[message, retry]];
    self.errorView.axis = UILayoutConstraintAxisVertical;
    self.errorView.spacing = 16;
    self.errorView.translatesAutoresizingMaskIntoConstraints = NO;
    self.errorView.hidden = YES;
    self.errorScroll = [UIScrollView new];
    self.errorScroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.errorScroll.accessibilityIdentifier = @"privacy.errorScroll";
    self.errorScroll.hidden = YES;
    [self.view addSubview:self.errorScroll];
    [self.errorScroll addSubview:self.errorView];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.webView.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.webView.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [self.webView.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.webView.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.activity.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [self.activity.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [self.errorScroll.topAnchor constraintEqualToAnchor:safe.topAnchor],
        [self.errorScroll.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor],
        [self.errorScroll.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [self.errorScroll.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.errorView.topAnchor constraintEqualToAnchor:self.errorScroll.contentLayoutGuide.topAnchor constant:24],
        [self.errorView.bottomAnchor constraintEqualToAnchor:self.errorScroll.contentLayoutGuide.bottomAnchor constant:-24],
        [self.errorView.leadingAnchor constraintEqualToAnchor:self.errorScroll.contentLayoutGuide.leadingAnchor constant:24],
        [self.errorView.trailingAnchor constraintEqualToAnchor:self.errorScroll.contentLayoutGuide.trailingAnchor constant:-24],
        [self.errorView.widthAnchor constraintEqualToAnchor:self.errorScroll.frameLayoutGuide.widthAnchor constant:-48]
    ]];
    [self loadPolicy];
}
- (void)loadPolicy {
    if (self.closing) return;
#if DEBUG
    // Deterministic one-shot local-render error, not an offline HTTP request.
    // Excluded from every Release build. Reload reads the same bundled resource.
    if (!self.simulatedLocalErrorOnce && [NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-policy-local-error"]) {
        self.simulatedLocalErrorOnce = YES;
        [self showLoadError:[NSError errorWithDomain:NSCocoaErrorDomain code:NSFileReadCorruptFileError userInfo:nil]];
        return;
    }
#endif
    NSURL *URL = [self policyResourceURL];
    NSError *error = nil;
    NSNumber *size = nil;
    NSData *data = nil;
    if (URL.isFileURL && [URL getResourceValue:&size forKey:NSURLFileSizeKey error:&error] && size.unsignedLongLongValue <= 16384) {
        data = [NSData dataWithContentsOfURL:URL options:NSDataReadingMappedIfSafe error:&error];
    }
    NSString *HTML = TCPrivacyPolicyHTML(data);
    if (!HTML) {
        [self showLoadError:error ?: [NSError errorWithDomain:NSCocoaErrorDomain code:NSFileReadCorruptFileError userInfo:nil]];
        return;
    }
    self.errorView.hidden = YES;
    self.errorScroll.hidden = YES;
    self.webView.hidden = NO;
    [self.activity startAnimating];
    [self.webView loadHTMLString:HTML baseURL:nil];
}
- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [self.activity stopAnimating];
}
- (void)showLoadError:(NSError *)error {
    if (self.closing || ([error.domain isEqualToString:NSURLErrorDomain] && error.code == NSURLErrorCancelled)) return;
    [self.activity stopAnimating];
    self.errorView.hidden = NO;
    self.errorScroll.hidden = NO;
    self.webView.hidden = YES;
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self showLoadError:error]; }
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error { [self showLoadError:error]; }
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [self showLoadError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorUnknown userInfo:nil]];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    BOOL allowed = !self.closing && response.isForMainFrame && TCPrivacyAllowsResponse(response.response);
    if (!allowed) [self showLoadError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCannotDecodeContentData userInfo:nil]];
    decisionHandler(allowed ? WKNavigationResponsePolicyAllow : WKNavigationResponsePolicyCancel);
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    BOOL userActivated = !self.closing && action.navigationType == WKNavigationTypeLinkActivated && action.sourceFrame.isMainFrame;
    NSURL *URL = action.request.URL;
    if (TCPrivacyAllowsContactURL(URL, userActivated) || TCPrivacyAllowsPublishedURL(URL, userActivated)) {
        [self openExternalPolicyURL:URL];
    }
    // External destinations are always cancelled in this embedded view, even after a user tap.
    BOOL allowed = !self.closing && action.targetFrame.isMainFrame && TCPrivacyAllowsDocumentURL(URL);
    decisionHandler(allowed ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
- (void)close {
    if (self.closing) return;
    self.closing = YES;
    [self.webView stopLoading];
    UIViewController *presentation = self.navigationController ?: self;
    [presentation dismissViewControllerAnimated:YES completion:self.dismissalHandler];
}
@end
