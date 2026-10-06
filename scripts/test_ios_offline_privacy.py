"""Source and resource contracts only; not Apple compilation or packet-level network observation."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY_SHA256 = '09af166e63987e02cb3722eacf4d4aa2ab6bccf55a5b43839ca4009826865cc2'
PUBLISHED = 'https://100mango.github.io/app-privacy/'
CONTACT = 'mailto:100mango@gmail.com'


class PolicyDocument(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags, self.paragraphs, self.links, self.csp = [], [], [], []
        self.in_policy = False
        self.language = None
        self.paragraph = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'section':
            self.language = attrs.get('lang')
        if tag == 'p' and self.language:
            self.paragraph = []
        if tag == 'a':
            self.links.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'content-security-policy':
            self.csp.append(attrs.get('content'))

    def handle_endtag(self, tag):
        if tag == 'p' and self.paragraph is not None:
            self.paragraphs.append((self.language, ''.join(self.paragraph)))
            self.paragraph = None
        if tag == 'section':
            self.language = None

    def handle_data(self, text):
        if self.paragraph is not None:
            self.paragraph.append(text)


def method(source, name):
    found = re.search(r'(?ms)^- \([^\n]+\)' + re.escape(name) + r'[^\n]*\{\n(.*?)(?=^- \(|^@end)', source)
    if not found:
        raise ValueError('Missing method: ' + name)
    return found.group(1)


class OfflinePrivacyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'ColorPicker/PrivacyPolicy.html').read_text()
        cls.document = PolicyDocument(cls.html)
        cls.controller = (ROOT / 'ColorPicker/TCPrivacyViewController.m').read_text()
        cls.hosted = (ROOT / 'ColorPickerTests/ColorPickerTests.m').read_text()
        cls.phone = (ROOT / 'TouchColorUITests/TouchColorUITests.m').read_text()
        cls.ipad = (ROOT / 'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        cls.audit = (ROOT / 'TouchColorUITests/TouchColorAccessibilityUITests.m').read_text()

    def test_exact_approved_bilingual_copy_and_pinned_bytes(self):
        source = (ROOT / 'TouchColorMac/PrivacyView.swift').read_text()
        copy = [json.loads(value) for value in re.findall(r'^    static let (?:simplifiedChinese|english) = (".*")$', source, re.M)]
        self.assertEqual(self.document.paragraphs, list(zip(['zh-Hans', 'en'], copy)))
        self.assertEqual(len(self.html.encode()), 2823)
        self.assertEqual(hashlib.sha256(self.html.encode()).hexdigest(), POLICY_SHA256)
        self.assertIn('@"' + POLICY_SHA256 + '"', self.controller)
        self.assertIn("POLICY_SHA256 = '" + POLICY_SHA256 + "'", (ROOT / 'scripts/verify_original_ios_package.py').read_text())

    def test_self_contained_resource_has_restrictive_csp_and_only_explicit_links(self):
        self.assertEqual(len(self.document.csp), 1)
        directives = dict(item.strip().split(' ', 1) for item in self.document.csp[0].split(';'))
        expected = {name: "'none'" for name in ['default-src', 'script-src', 'img-src', 'font-src', 'connect-src', 'frame-src', 'object-src', 'media-src', 'base-uri', 'form-action']}
        expected['style-src'] = "'unsafe-inline'"
        self.assertEqual(directives, expected)
        self.assertEqual(self.document.links, [CONTACT, CONTACT, PUBLISHED])
        for tag, attrs in self.document.tags:
            self.assertIn(tag, ['html', 'head', 'meta', 'title', 'style', 'body', 'main', 'h1', 'h2', 'span', 'br', 'section', 'p', 'a'])
            self.assertFalse(set(attrs) & {'src', 'srcset', 'action', 'formaction', 'background', 'ping'})
            self.assertFalse(any(key.lower().startswith('on') for key in attrs))
            if 'href' in attrs:
                self.assertEqual(tag, 'a')
        self.assertNotRegex(self.html.lower(), r'url\s*\(|@import|http-equiv="refresh"|user-select:\s*none|maximum-scale|user-scalable')
        self.assertIn('font: -apple-system-body', self.html)
        self.assertIn('color-scheme: light dark', self.html)
        self.assertIn('overflow-wrap: anywhere', self.html)
        self.assertIn('lang="zh-Hans"', self.html)
        self.assertIn('Open published policy in browser', self.html)
        self.assertIn('在浏览器中打开已发布的隐私政策', self.html)
        published = re.search(r'<p class="published">(.*?)</p>', self.html, re.S).group(1)
        english_notice = '<span lang="en">When you open this link, GitHub Pages records and stores your IP address for security.</span>'
        chinese_notice = '<span lang="zh-Hans">打开此链接时，GitHub Pages 会出于安全目的记录并存储你的 IP 地址。</span>'
        self.assertLess(published.index(english_notice), published.index('<a href="' + PUBLISHED + '">'))
        self.assertLess(published.index(chinese_notice), published.index('<a href="' + PUBLISHED + '">'))

    def test_default_and_reload_only_read_validated_bundle_with_nil_base(self):
        load = method(self.controller, 'loadPolicy')
        self.assertIn('if (self.closing) return;', load)
        self.assertIn('NSURL *URL = [self policyResourceURL];', load)
        self.assertIn('URL.isFileURL', load)
        self.assertIn('size.unsignedLongLongValue <= 16384', load)
        self.assertIn('NSString *HTML = TCPrivacyPolicyHTML(data);', load)
        self.assertLess(load.index('if (!HTML)'), load.index('[self.webView loadHTMLString:HTML baseURL:nil]'))
        self.assertIn('return;', load.split('if (!HTML)', 1)[1].split('self.errorView.hidden = YES;', 1)[0])
        self.assertIn('[NSBundle.mainBundle URLForResource:@"PrivacyPolicy" withExtension:@"html"]', method(self.controller, 'policyResourceURL'))
        self.assertEqual(self.controller.count('loadHTMLString:'), 1)
        self.assertNotRegex(self.controller, r'loadRequest:|loadFileURL:|loadData:|NSURLSession|NSURLConnection|evaluateJavaScript:')
        self.assertEqual(self.controller.count(PUBLISHED), 1)  # Exact external allowlist, not the loader.
        self.assertIn('configuration.defaultWebpagePreferences.allowsContentJavaScript = NO;', self.controller)
        self.assertIn('configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;', self.controller)
        self.assertIn('configuration.dataDetectorTypes = WKDataDetectorTypeNone;', self.controller)
        self.assertIn('self.webView.allowsLinkPreview = NO;', self.controller)

    def test_external_browser_and_contact_routes_require_a_live_main_frame_user_action(self):
        route = self.controller.split('decidePolicyForNavigationAction:', 1)[1].split('- (void)close', 1)[0]
        self.assertIn('!self.closing && action.navigationType == WKNavigationTypeLinkActivated && action.sourceFrame.isMainFrame', route)
        self.assertIn('TCPrivacyAllowsContactURL(URL, userActivated) || TCPrivacyAllowsPublishedURL(URL, userActivated)', route)
        self.assertEqual(self.controller.count('[self openExternalPolicyURL:URL]'), 1)
        self.assertEqual(self.controller.count('[UIApplication.sharedApplication openURL:'), 1)
        self.assertIn('action.targetFrame.isMainFrame && TCPrivacyAllowsDocumentURL(URL)', route)
        self.assertIn('decisionHandler(allowed ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);', route)
        self.assertIn('!parts.query && !parts.fragment', self.controller)
        self.assertIn('!parts.host && !parts.user && !parts.password && !parts.port', self.controller)
        self.assertIn('!self.closing && response.isForMainFrame && TCPrivacyAllowsResponse(response.response)', self.controller)
        self.assertIn('![response isKindOfClass:NSHTTPURLResponse.class]', self.controller)
        self.assertIn('parts.scheme.lowercaseString isEqualToString:@"about"', self.controller)
        self.assertNotIn('parts.scheme.lowercaseString isEqualToString:@"https"', self.controller)

    def test_hosted_spies_cover_actual_loader_missing_malformed_recovery_and_close(self):
        body = method(self.hosted, 'testPolicyLocalResourceFailuresAndWebProcessTerminationExposeReload')
        for token in ['NSBundle.mainBundle', 'TCPrivacyPolicyHTML(nil)', 'changed.mutableBytes', 'TCPrivacyPolicyHTML(changed)',
                      'NSURLErrorCancelled', 'webViewWebContentProcessDidTerminate:', 'decidePolicyForNavigationResponse:',
                      'controller.usesFixtureURL=YES', 'Missing local resource', 'Same-size tampered local resource',
                      'Malformed local resource', 'controller.usesFixtureURL=NO', 'controller.spy.HTMLLoads,3u',
                      'controller.spy.requestLoads,0u', 'controller.openedURLs.count,0u', '[controller close]',
                      'Late failure after Close', 'controller.spy.loadedBaseURL', 'Method spy:']:
            self.assertIn(token, body)
        nav = method(self.hosted, 'testPrivacyNavigationIsLocalAndPublishedPolicyRequiresExplicitBrowserTap')
        for token in ['about:blank#english-title', 'tracking=1', 'user@', ':8443', 'javascript:alert', 'WKNavigationTypeOther',
                      'WKNavigationTypeLinkActivated', 'controller.openedURLs.lastObject', 'sourceFrame.mainFrame=NO',
                      '[controller close]', 'WKNavigationActionPolicyCancel']:
            self.assertIn(token, nav)
        self.assertIn('TCPrivacyAllowsContactURL(contact,NO)', self.hosted)
        self.assertIn('mailto:100mango@gmail.com?body=private', self.hosted)

    def test_every_cross_file_hosted_selector_is_declared_in_imported_header(self):
        header = (ROOT / 'ColorPickerTests/TCPrivacyTesting.h').read_text()
        signatures = [
            '- (void)loadPolicy',
            '- (NSURL *)policyResourceURL',
            '- (WKWebView *)makePolicyWebViewWithConfiguration:(WKWebViewConfiguration *)configuration',
            '- (void)openExternalPolicyURL:(NSURL *)URL',
            '- (void)close',
            '- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView',
            '- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error',
            '- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler',
            '- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler',
        ]
        for signature in signatures:
            self.assertEqual(header.count(signature + ';'), 1)
            self.assertEqual(self.controller.count(signature + ' {'), 1)
        self.assertIn('@interface TCPrivacyViewController (HostedPolicyTests)', header)
        for name in ['ColorPickerTests.m', 'TCAdaptiveLayoutTests.m']:
            self.assertIn('#import "TCPrivacyTesting.h"', (ROOT / 'ColorPickerTests' / name).read_text())

    def test_debug_fixture_and_truthful_localized_error_have_no_http_fallback(self):
        load = method(self.controller, 'loadPolicy')
        debug = load.split('#if DEBUG', 1)[1].split('#endif', 1)[0]
        self.assertIn('--ui-test-policy-local-error', debug)
        self.assertIn('simulatedLocalErrorOnce = YES', debug)
        self.assertIn('NSFileReadCorruptFileError', debug)
        for source in [self.controller, self.phone, self.audit]:
            self.assertNotIn('--ui-test-policy-offline', source)
        message = 'The local privacy policy could not load. Reload to try again.'
        self.assertIn(message, self.controller)
        for locale in ['en', 'zh-Hans']:
            text = (ROOT / 'ColorPicker' / (locale + '.lproj') / 'Localizable.strings').read_text()
            self.assertIn('"' + message + '" = ', text)
            self.assertIn('"Reload" = ', text)
            self.assertNotIn('Check your connection', text)

    def test_phone_and_ipad_keep_return_and_real_bilingual_observations(self):
        entry = method(self.phone, 'testPrivacyPolicyEntryOpensAndCloses')
        for token in ['attempt<2', '[self assertLocalPolicyBody]', 'XCUIDeviceButtonHome', '[self.app activate]', '[close tap]', 'choosePhoto']:
            self.assertIn(token, entry)
        for name in ['testPrivacyLocalErrorReloadAndClose', 'testLargestTextLocalPolicyCanScrollReloadAndCloseInLandscape']:
            body = method(self.phone, name)
            for token in ['--ui-test-policy-local-error', 'privacy.retry', '[retry tap]', '[self assertLocalPolicyBody]', 'privacy.close', 'choosePhoto']:
                self.assertIn(token, body)
        large = method(self.phone, 'testLargestTextLocalPolicyCanScrollReloadAndCloseInLandscape')
        for token in ['UICTContentSizeCategoryAccessibilityXXXL', 'privacy.errorScroll', 'published.hittable', 'UIDeviceOrientationLandscapeLeft', '--ui-test-dark']:
            self.assertIn(token, large)
        ipad = method(self.ipad, 'testPrivacyCloseRetainsPhotoSelection')
        for token in ['[self importFixture]', 'Celluloid、QRCatcher 和 TouchColor', 'Celluloid, QRCatcher, and TouchColor', 'sampleCenter', '#ff00ff']:
            self.assertIn(token, ipad)

    def test_strict_error_audit_then_real_bilingual_body_audit_and_separate_evidence(self):
        body = method(self.audit, 'testAccessibilityLocalPolicyErrorAndBody')
        self.assertEqual(body.count('[self auditScreen:'), 2)
        error = body.index('[self auditScreen:@"local policy error in dark appearance"]')
        reload = body.index('[self.app.buttons[@"privacy.retry"] tap]')
        normal = body.index('[self auditScreen:@"bundled bilingual policy in dark appearance"]')
        self.assertLess(error, reload)
        self.assertLess(reload, normal)
        self.assertIn('Celluloid、QRCatcher 和 TouchColor', body[reload:normal])
        self.assertIn('Celluloid, QRCatcher, and TouchColor', body[reload:normal])
        audit = method(self.audit, 'auditScreen:')
        self.assertIn('XCUIAccessibilityAuditTypeAll', audit)
        self.assertIn('return NO; // No category-wide or element-wide suppression', audit)
        self.assertIn('XCTAssertTrue(passed', audit)
        exporter = (ROOT / 'scripts/export_audit_failures.py').read_text()
        for state in ['policy-error', 'policy-local-body']:
            self.assertIn('@"' + state + '"', self.audit)
            self.assertIn("'touchcolor-audit-failure-" + state + "'", exporter)
        self.assertIn('@"touchcolor-policy-local-body"', self.audit)
        self.assertIn("['touchcolor-policy-local-body'], limit - count)", exporter)
        self.assertIn('XCTAssertLessThanOrEqual(bytes.length,500*1024u)', self.audit)
        self.assertIn("ALLOCATIONS = {'iPadMini': 2, 'iPadLarge': 4, 'iPhoneCompact': 2, 'iPhoneLarge': 2}", exporter)
        self.assertIn('MAX_RUN_LOG_BYTES = 20_000_000', exporter)

    def test_focused_contract_is_in_existing_prerequisite_without_changing_native_clocks(self):
        workflow = (ROOT / '.github/workflows/ios.yml').read_text()
        prerequisite = workflow.split('  compile-prerequisites:\n', 1)[1].split('  compatibility:\n', 1)[0]
        self.assertIn('test_original_ios_package test_ios_offline_privacy', prerequisite)
        self.assertIn('python3 -O -m unittest test_ios_offline_privacy test_original_ios_package', prerequisite)


if __name__ == '__main__':
    unittest.main()
