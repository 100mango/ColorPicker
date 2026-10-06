// Shared declarations for the narrow controller seams exercised by hosted tests.
// Keep selectors here, rather than relying on undeclared cross-file Objective-C messages.
#import "TCPrivacyViewController.h"
#import <WebKit/WebKit.h>

@interface TCPrivacyViewController (HostedPolicyTests)
- (void)loadPolicy;
- (NSURL *)policyResourceURL;
- (WKWebView *)makePolicyWebViewWithConfiguration:(WKWebViewConfiguration *)configuration;
- (void)openExternalPolicyURL:(NSURL *)URL;
- (void)close;
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView;
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error;
- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler;
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler;
@end
