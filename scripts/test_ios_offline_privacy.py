"""Source and resource contracts only; not Apple compilation or packet-level network observation."""
import hashlib
import ast
import shutil
import subprocess
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY_SHA256 = '390d6c30ab0f52031417981d7477c8553572402dd9d5757bf1ccbf4e6ea0c986'
PUBLISHED = 'https://100mango.github.io/app-privacy/'
CONTACT = 'mailto:100mango@gmail.com'


class PolicyDocument(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags, self.paragraphs, self.links, self.csp = [], [], [], []
        self.mail_links, self.active_mail = [], None
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
            if attrs.get('href') == CONTACT:
                self.active_mail = {'language': self.language, 'attrs': attrs, 'text': []}
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'content-security-policy':
            self.csp.append(attrs.get('content'))

    def handle_endtag(self, tag):
        if tag == 'a' and self.active_mail is not None:
            self.mail_links.append(self.active_mail)
            self.active_mail = None
        if tag == 'p' and self.paragraph is not None:
            self.paragraphs.append((self.language, ''.join(self.paragraph)))
            self.paragraph = None
        if tag == 'section':
            self.language = None

    def handle_data(self, text):
        if self.active_mail is not None:
            self.active_mail['text'].append(text)
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
        # Only the reviewed visible contact prefix is additional; every original
        # policy word, email address and other paragraph character remains.
        normalized=[]
        for language, paragraph in self.document.paragraphs:
            prefix={'zh-Hans':'开发者邮箱：','en':'Developer email: '}[language]
            self.assertEqual(paragraph.count(prefix+'100mango@gmail.com'),1)
            normalized.append((language,paragraph.replace(prefix+'100mango@gmail.com','100mango@gmail.com')))
        self.assertEqual(normalized, list(zip(['zh-Hans', 'en'], copy)))
        self.assertEqual(len(self.html.encode()), 2916)
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
        self.assertIn('Open in browser', self.html)
        self.assertIn('在浏览器中打开', self.html)
        published = re.search(r'<p class="published">(.*?)</p>', self.html, re.S).group(1)
        english_notice = '<span lang="en">When you open this link, GitHub Pages records and stores your IP address for security.</span>'
        chinese_notice = '<span lang="zh-Hans">打开此链接时，GitHub Pages 会出于安全目的记录并存储你的 IP 地址。</span>'
        self.assertLess(published.index(english_notice), published.index('<a href="' + PUBLISHED + '">'))
        self.assertLess(published.index(chinese_notice), published.index('<a href="' + PUBLISHED + '">'))

    def test_mail_links_have_visible_localized_purpose_and_identical_accessible_names(self):
        expected={'zh-Hans':'开发者邮箱：100mango@gmail.com','en':'Developer email: 100mango@gmail.com'}
        self.assertEqual(len(self.document.mail_links),2)
        for link in self.document.mail_links:
            self.assertEqual(''.join(link['text']),expected[link['language']])
            self.assertEqual(link['attrs']['aria-label'],expected[link['language']])
            self.assertEqual(link['attrs']['href'],CONTACT)
            self.assertEqual(''.join(link['text']).count('100mango@gmail.com'),1)
        for tag, attrs in self.document.tags:
            self.assertNotIn('aria-hidden',attrs)
            self.assertNotIn('role',attrs)
        self.assertNotRegex(self.html.lower(),r'user-select:\s*none|font-size:\s*0|visibility:\s*hidden|display:\s*none')

    def test_hosted_resource_checks_preserve_raw_email_and_descriptive_captions(self):
        body=method(self.hosted,'testPolicyLocalResourceFailuresAndWebProcessTerminationExposeReload')
        self.assertIn('@"开发者邮箱：100mango@gmail.com"',body)
        self.assertIn('@"Developer email: 100mango@gmail.com"',body)
        self.assertIn('containsString:caption',body)
        self.assertIn('aria-label=',body)
        self.assertIn('mailto:100mango@gmail.com',body)

    def test_footer_action_is_short_bilingual_same_url_with_original_native_reachability(self):
        expected='<a href="'+PUBLISHED+'">Open in browser<br><span lang="zh-Hans">在浏览器中打开</span></a>'
        self.assertEqual(self.html.count(expected),1)
        self.assertEqual(self.document.links.count(PUBLISHED),1)
        self.assertNotIn('Open published policy in browser',self.html)
        body=method(self.phone,'testLargestTextLocalPolicyCanScrollReloadAndCloseInLandscape')
        self.assertIn("label CONTAINS 'Open in browser'",body)
        self.assertIn('attempt<16 && !published.hittable',body)
        self.assertIn('[policy swipeUpWithVelocity:XCUIGestureVelocityFast]',body)
        self.assertIn('XCTAssertTrue(published.hittable,',body)
        self.assertIn('XCTAssertTrue(self.app.buttons[@"privacy.close"].hittable)',body)
        self.assertNotIn('openURL:',body)
        self.assertNotIn('executionTimeAllowance',body)

    def test_only_sampled_photo_audit_gets_twenty_with_same_original_fifteen_marker(self):
        body=method(self.audit,'testAccessibilitySampledPhoto')
        self.assertEqual(body.count('[self.app.buttons[@"choosePhoto"] tap];'),1)
        self.assertEqual(body.count('waitForExistenceWithTimeout:'),1)
        self.assertIn('deadline=started+20;',body)
        self.assertIn('returned<started+15 ? @"within" : @"missed"',body)
        self.assertIn('returned<deadline && NSProcessInfo.processInfo.systemUptime<deadline',body)
        self.assertLess(body.index('self.tcPaletteReadinessExpired=YES;'),body.index('XCTAssertTrue(timely'))
        self.assertLess(body.index('if (!timely) return;'),body.index('[self sampleImportedPhoto:photo]'))
        self.assertLess(body.index('if (!appeared) return;'),body.index('[self sampleImportedPhoto:photo]'))
        self.assertNotIn('debugDescription',body)
        self.assertIn('[self auditScreen:@"sampled photo with numeric RGB and hex"]',body)
        self.assertNotIn('executionTimeAllowance',body)
        saved=method(self.audit,'testAccessibilitySavedPalette')
        self.assertIn('[self importAndSample]',saved)
        original=method(self.audit,'importAndSample')
        self.assertIn('[photo waitForExistenceWithTimeout:15]',original)
        self.assertNotIn('20',original)

    def test_sampling_actions_and_original_other_audits_are_not_changed(self):
        body=method(self.audit,'sampleImportedPhoto')
        suffix=body
        self.assertEqual(hashlib.sha256(suffix.encode()).hexdigest(),'d1e9a25e2bf6f1319bd33bf3f0ef257163465e78bc18a875ce4862b4bcbfa703')
        for token in ('[photo tap]','@"#ff00ff"','@"#ff0000"','@"R 255   G 0   B 255"','[self assertEmptyHistoryDoesNotOverlapHeader]'):
            self.assertIn(token,body)
        self.assertIn('return NO; // No category-wide or element-wide suppression',self.audit)
        self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',self.audit)),7)

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



# C preprocessing counts parentheses, not Objective-C []/{} message or literal
# grouping. Probe the actual arguments received by macros using the installed C
# preprocessor; this is not an Apple XCTest/Objective-C type-check substitute.
ASSERT_ARITY = {
    'XCTAssertTrue': 1, 'XCTAssertFalse': 1, 'XCTAssertNil': 1,
    'XCTAssertNotNil': 1, 'XCTFail': 1, 'XCTAssertEqual': 2,
    'XCTAssertEqualObjects': 2, 'XCTAssertNotEqual': 2,
    'XCTAssertGreaterThan': 2, 'XCTAssertGreaterThanOrEqual': 2,
    'XCTAssertLessThanOrEqual': 2, 'XCTAssertEqualWithAccuracy': 3,
}


def mask_c_literals_and_comments(text):
    masked = list(text)
    index = 0
    while index < len(text):
        start = index
        if text.startswith('//', index):
            end = text.find('\n', index)
            index = len(text) if end < 0 else end
        elif text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('Unclosed C comment')
            index = end + 2
        elif text[index] in ('"', "'"):
            quote = text[index]
            index += 1
            while index < len(text):
                if text[index] == '\\':
                    index += 2
                elif text[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            else:
                raise ValueError('Unclosed C literal')
        else:
            index += 1
            continue
        for position in range(start, min(index, len(text))):
            if masked[position] != '\n':
                masked[position] = ' '
    return ''.join(masked)


def assertion_calls(source):
    masked = mask_c_literals_and_comments(source)
    calls = []
    for found in re.finditer(r'\b(XCTAssert\w*|XCTFail)\s*\(', masked):
        name = found.group(1)
        if name not in ASSERT_ARITY:
            raise ValueError('Unreviewed assertion macro ' + name)
        depth, end = 1, found.end()
        while end < len(masked) and depth:
            if masked[end] == '(':
                depth += 1
            elif masked[end] == ')':
                depth -= 1
            end += 1
        if depth:
            raise ValueError('Unclosed assertion invocation')
        calls.append(source[found.start():end])
    return calls


def preprocess_assertion_arguments(calls):
    compiler = shutil.which('cc')
    if not compiler:
        raise RuntimeError('An installed C preprocessor is required; do not skip this check')
    definitions = []
    for name, arity in ASSERT_ARITY.items():
        parameters = [f'arg{i}' for i in range(arity)]
        definitions.append(f'#define {name}({", ".join(parameters)}, ...) '
                           f'TC_XCT_ARG_RECORD("{name}", {", ".join("#" + p for p in parameters)})')
    probe = '\n'.join(definitions + [call + ';' for call in calls]) + '\n'
    if len(probe.encode()) > 1_000_000:
        raise ValueError('Unexpected assertion probe size')
    result = subprocess.run([compiler, '-E', '-P', '-x', 'c', '-'], input=probe,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('C preprocessing failed: ' + result.stderr[:2000])
    if len(result.stdout.encode()) > 2_000_000:
        raise ValueError('Unexpected preprocessor output size')
    records = []
    literal = r'"(?:\\.|[^"\\])*"'
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*TC_XCT_ARG_RECORD\s*\(\s*(' + literal + r'(?:\s*,\s*' + literal + r')*)\s*\)\s*;?\s*', line)
        if not match:
            raise ValueError('Unexpected C preprocessor record: ' + line[:300])
        values = [ast.literal_eval(token) for token in re.findall(literal, match.group(1))]
        if len(values) != ASSERT_ARITY[values[0]] + 1:
            raise ValueError('Wrong assertion argument count')
        for argument in values[1:]:
            clean = mask_c_literals_and_comments(argument)
            stack = []
            pairs = {')': '(', ']': '[', '}': '{'}
            for char in clean:
                if char in '([{':
                    stack.append(char)
                elif char in ')]}':
                    if not stack or stack.pop() != pairs[char]:
                        raise ValueError('Preprocessor split an Objective-C assertion argument: ' + values[0])
            if stack:
                raise ValueError('Preprocessor split an Objective-C assertion argument: ' + values[0])
        records.append(values)
    if len(records) != len(calls):
        raise ValueError('Assertion probe omitted an invocation')
    return records


class ActualAssertionPreprocessorTests(unittest.TestCase):
    def test_all_assertions_in_changed_native_files_retain_complete_arguments(self):
        paths = ['ColorPickerTests/ColorPickerTests.m', 'TouchColorUITests/TCPaletteUIHelpers.m',
                 'TouchColorUITests/TouchColorAccessibilityUITests.m',
                 'TouchColorUITests/TouchColorIPadUITests.m', 'TouchColorUITests/TouchColorUITests.m']
        counts = {}
        for relative in paths:
            calls = assertion_calls((ROOT / relative).read_text())
            self.assertGreater(len(calls), 0)
            counts[relative] = len(preprocess_assertion_arguments(calls))
        self.assertGreater(sum(counts.values()), 200)

    def test_real_preprocessor_rejects_message_and_collection_commas(self):
        bad = [
            'XCTAssertTrue([HTML containsString:[NSString stringWithFormat:@"aria-label=\\\"%@\\\"",caption]],@"Original21 failure");',
            'XCTAssertEqualObjects(actual,@[@"one",@"two"]);',
            'XCTAssertTrue([object matches:@{@"one": @1, @"two": @2}]);',
        ]
        for source in bad:
            with self.subTest(source=source), self.assertRaises(ValueError):
                preprocess_assertion_arguments(assertion_calls(source))
        good = ['XCTAssertTrue([HTML containsString:accessibleNameAttribute],@"Same semantic assertion");',
                'XCTAssertEqualObjects(actual,(@[@"one",@"two"]));',
                'XCTAssertTrue(([HTML containsString:[NSString stringWithFormat:@"%@",caption]]));']
        for source in good:
            self.assertEqual(len(preprocess_assertion_arguments(assertion_calls(source))), 1)

if __name__ == '__main__':
    unittest.main()
