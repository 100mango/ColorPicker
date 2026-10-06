"""Native privacy source/packaging contracts. Actual layout, selection and audits require XCTest."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from verify_original_ios_package import source_graph, strings_dictionary, POLICY_LOCALIZATIONS

ROOT=Path(__file__).resolve().parents[1]
PUBLISHED='https://100mango.github.io/app-privacy/'
CONTACT='mailto:100mango@gmail.com'

def method(source,name):
    found=re.search(r'(?ms)^- \([^\n]+\)'+re.escape(name)+r'[^\n]*\{\n(.*?)(?=^- \(|^@end)',source)
    if not found: raise ValueError('Missing method: '+name)
    return found.group(1)

class OfflinePrivacyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller=(ROOT/'ColorPicker/TCPrivacyViewController.m').read_text()
        cls.hosted=(ROOT/'ColorPickerTests/ColorPickerTests.m').read_text()
        cls.phone=(ROOT/'TouchColorUITests/TouchColorUITests.m').read_text()
        cls.ipad=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        cls.audit=(ROOT/'TouchColorUITests/TouchColorAccessibilityUITests.m').read_text()
        cls.layout=(ROOT/'ColorPickerTests/TCAdaptiveLayoutTests.m').read_text()

    def test_exact_approved_bilingual_copy_in_both_actual_locale_resources(self):
        mac=(ROOT/'TouchColorMac/PrivacyView.swift').read_text()
        approved=[json.loads(x) for x in re.findall(r'^    static let (?:simplifiedChinese|english) = (".*")$',mac,re.M)]
        for language,expected in zip(('zh-Hans','en'),approved):
            raw=(ROOT/f'ColorPicker/{language}.lproj/Localizable.strings').read_bytes()
            values=strings_dictionary(raw)
            self.assertEqual(values['Approved Privacy Body'],expected)
            self.assertEqual(expected.count('100mango@gmail.com'),1)
            self.assertIn('GitHub Pages',values['External Privacy Website Notice'])
            self.assertIn('IP',values['External Privacy Website Notice'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),POLICY_LOCALIZATIONS[language])
        self.assertIn('pathForResource:language ofType:@"lproj"',self.controller)
        self.assertIn('key:@"Approved Privacy Body"',self.controller)

    def test_native_body_is_plain_selectable_and_has_no_implicit_external_actions(self):
        body=method(self.controller,'bodyForLanguage:')
        for value in ['body.editable = NO;', 'body.selectable = YES;', 'body.scrollEnabled = NO;',
                      'body.dataDetectorTypes = UIDataDetectorTypeNone;', 'body.adjustsFontForContentSizeCategory = YES;',
                      'body.textContainerInset = UIEdgeInsetsZero;', 'body.textContainer.lineFragmentPadding = 0;',
                      'body.textColor = UIColor.labelColor;', 'UILayoutPriorityRequired']:
            self.assertIn(value,body)
        self.assertNotIn('NSLinkAttributeName',self.controller)
        self.assertNotRegex(self.controller,r'accessibilityElementsHidden|isAccessibilityElement|accessibilityLabel\s*=')
        self.assertNotIn('setAccessibilityElements:',self.controller)

    def test_default_screen_has_no_web_renderer_resource_or_request(self):
        self.assertFalse((ROOT/'ColorPicker/PrivacyPolicy.html').exists())
        self.assertNotRegex(self.controller,r'WKWeb|WebKit|NSURLSession|NSURLConnection|loadHTML|loadRequest|loadFile|evaluateJavaScript|loadPolicy|policy-local-error')
        loaded=method(self.controller,'viewDidLoad')
        self.assertNotIn('openExternalURL:',loaded)
        self.assertEqual(self.controller.count('[UIApplication.sharedApplication openURL:'),1)
        self.assertEqual(self.controller.count(PUBLISHED),1)
        self.assertEqual(self.controller.count(CONTACT),1)
        self.assertNotIn('PrivacyPolicy.html',(ROOT/'scripts/generate_project.py').read_text())

    def test_fixed_real_buttons_use_closed_destinations_and_keep_pending_fence(self):
        loaded=method(self.controller,'viewDidLoad')
        self.assertIn('identifier:@"privacy.contact" action:@selector(contactDeveloper)',loaded)
        self.assertIn('identifier:@"privacy.externalPolicy" action:@selector(openPolicyInBrowser)',loaded)
        self.assertIn(CONTACT,method(self.controller,'contactDeveloper'))
        self.assertIn(PUBLISHED,method(self.controller,'openPolicyInBrowser'))
        route=method(self.controller,'beginExternalURL:')
        self.assertLess(route.index('if (self.closing || self.opening) return;'),route.index('[self openExternalURL:'))
        self.assertIn('self.contactButton.enabled = NO;',route)
        self.assertIn('self.browserButton.enabled = NO;',route)
        self.assertIn('dispatch_async(dispatch_get_main_queue()',route)
        self.assertIn('if (!strongSelf || strongSelf.closing || !strongSelf.opening) return;',route)
        self.assertIn('strongSelf.externalError.hidden = opened;',route)
        close=method(self.controller,'close')
        self.assertLess(close.index('if (self.closing) return;'),close.index('self.closing = YES;'))
        self.assertIn('completion:self.dismissalHandler',close)

    def test_footer_notice_and_button_intrinsic_heights_are_not_compressed(self):
        label=method(self.controller,'labelWithText:')
        self.assertIn('label.numberOfLines = 0;',label)
        self.assertIn('UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical',label)
        button=method(self.controller,'actionWithTitle:')
        self.assertIn('NSLineBreakByWordWrapping',button)
        self.assertIn('UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical',button)
        self.assertIn('constraintGreaterThanOrEqualToConstant:44',button)
        self.assertIn('multiplier:0.45',self.controller)
        self.assertIn('naturalActions.priority = UILayoutPriorityDefaultHigh;',self.controller)
        self.assertIn('content.contentLayoutGuide',self.controller)
        self.assertIn('actionScroll.contentLayoutGuide',self.controller)
        self.assertIn('glyphRangeForTextContainer:',self.layout)
        self.assertIn('body.layoutManager.numberOfGlyphs',self.layout)
        self.assertIn('notice.bounds.size.height+0.5,natural.height',self.layout)
        self.assertIn('[self assertViewReadable:button inScroll:actions]',self.layout)
        self.assertIn('test320x568LargestTextActualViewLayouts',self.layout)
        self.assertIn('test568x320LargestTextActualViewLayouts',self.layout)

    def test_actual_hosted_buttons_copy_and_late_close_replace_web_simulation(self):
        for token in ['sendActionsForControlEvents:UIControlEventTouchUpInside','pendingCompletion','if (failure) failure(NO)',
                      'if (success) success(YES)','if (completion) completion(NO)', '[controller close];[controller close];',
                      '[body copy:nil]','privacy-copy-sentinel','NSEqualRanges(body.selectedRange,address)',
                      'XCTAssertEqualObjects(body.text,approved[index])', 'XCTAssertFalse(hasLink']:
            self.assertIn(token,self.hosted)
        self.assertNotRegex(self.hosted,r'WKWebView|TCPolicyAction|TCPolicyResponse|webViewWebContentProcessDidTerminate')
        header=(ROOT/'ColorPickerTests/TCPrivacyTesting.h').read_text()
        for token in ['openExternalURL:(NSURL *)URL completion:(void (^)(BOOL))completion','contactDeveloper','openPolicyInBrowser','close']:
            self.assertIn(token,header)
        self.assertNotIn('WebKit',header)

    def test_native_phone_actions_keep_live_scroll_close_and_background_assertions(self):
        entry=method(self.phone,'testPrivacyPolicyEntryOpensAndCloses')
        for token in ['attempt<2','XCUIDeviceButtonHome','[self.app activate]','[close tap]','choosePhoto']:
            self.assertIn(token,entry)
        large=method(self.phone,'testLargestTextNativePolicyCanScrollAndCloseInLandscape')
        for token in ['UICTContentSizeCategoryAccessibilityXXXL','UIDeviceOrientationLandscapeLeft','attempt<16',
                      'XCTAssertTrue(english.hittable','[self revealControl:button inScrollView:actions]',
                      'XCTAssertTrue(button.hittable)','privacy.close','choosePhoto']:
            self.assertIn(token,large)
        self.assertNotIn('--ui-test-policy-local-error',self.phone)
        self.assertNotIn('privacy.retry',self.phone)
        self.assertIn('testNativePrivacyBodyAndContactControlsRemainAvailableAfterReopen',self.phone)
        ipad=method(self.ipad,'testPrivacyCloseRetainsPhotoSelection')
        for token in ['[self importFixture]','privacy.body.zh-Hans','privacy.body.en','privacy.close','sampleCenter','#ff00ff']:
            self.assertIn(token,ipad)

    def test_native_body_and_actions_have_two_real_strict_audit_observations(self):
        body=method(self.audit,'testAccessibilityNativePolicyBodyAndActions')
        self.assertEqual(body.count('[self auditScreen:'),2)
        self.assertIn('native bilingual policy in dark appearance',body)
        self.assertIn('native policy actions in dark appearance',body)
        self.assertIn('privacy.body.zh-Hans',body);self.assertIn('privacy.body.en',body)
        self.assertIn('XCTAssertTrue(button.hittable)',body)
        self.assertNotIn('privacy.retry',self.audit)
        self.assertNotIn('--ui-test-policy-local-error',self.audit)
        audit=method(self.audit,'auditScreen:')
        self.assertIn('XCUIAccessibilityAuditTypeAll',audit)
        self.assertIn('return NO; // No category-wide or element-wide suppression',audit)
        self.assertIn('XCTAssertTrue(passed',audit)

    def test_actual_original_package_checks_native_localizations_not_retired_html(self):
        graph=source_graph(ROOT)
        self.assertEqual(set(graph['native_privacy_localizations']),{'en','zh-Hans'})
        self.assertNotIn('ColorPicker/PrivacyPolicy.html',graph['resource_paths'])
        self.assertEqual(len(graph['source_paths']),12)

    def test_counts_and_workflow_clocks_are_explicit_and_unchanged(self):
        for source,expected in [(self.phone,17),(self.ipad,16),(self.audit,7)]:
            self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',source)),expected)
        workflow=(ROOT/'.github/workflows/ios.yml').read_text()
        self.assertIn('test_original_ios_package test_ios_offline_privacy',workflow)
        self.assertIn('python3 -O -m unittest test_ios_offline_privacy test_original_ios_package',workflow)
        self.assertNotIn('executionTimeAllowance',method(self.phone,'testLargestTextNativePolicyCanScrollAndCloseInLandscape'))

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


# C preprocessing counts parentheses, not Objective-C []/{} message or literal
# grouping. Probe the actual arguments received by macros using the installed C
# preprocessor; this is not an Apple XCTest/Objective-C type-check substitute.
ASSERT_ARITY = {
    'XCTAssertTrue': 1, 'XCTAssertFalse': 1, 'XCTAssertNil': 1,
    'XCTAssertNotNil': 1, 'XCTFail': 1, 'XCTAssertEqual': 2,
    'XCTAssertEqualObjects': 2, 'XCTAssertNotEqual': 2,
    'XCTAssertGreaterThan': 2, 'XCTAssertGreaterThanOrEqual': 2,
    'XCTAssertLessThan': 2, 'XCTAssertLessThanOrEqual': 2, 'XCTAssertEqualWithAccuracy': 3,
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
        paths = ['ColorPickerTests/ColorPickerTests.m', 'ColorPickerTests/TCAdaptiveLayoutTests.m',
                 'TouchColorUITests/TCPaletteUIHelpers.m',
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
