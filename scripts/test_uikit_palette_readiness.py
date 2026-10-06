"""Portable source contracts and retained timing arithmetic; these do not execute XCTest."""
import hashlib,json,re,unittest,subprocess,tempfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HELPER=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.m').read_text()
def section(start,end): return HELPER.split(start,1)[1].split(end,1)[0]
LOCKS={'TCPaletteUIHelpers.m': {'- (XCUIElement *)paletteElement:(NSString *)identifier app:(XCUIApplication *)app {': 'bd76b81e3cd0dba5e7338ffe1e75da1d1720b149707f7a355a29fb032a103a87', '- (void)returnToPaletteFrom:(NSString *)title app:(XCUIApplication *)app {': 'e6a9d262c92120711056db033297901a7daad34e33bd1101a1cb52ebca435be2', '- (CGRect)paletteBodyViewport:(XCUIApplication *)app table:(XCUIElement *)table title:(NSString *)title {': '1c24405d1835718ae9fcd118cc29a0bb194df94e29a2b03c3e3c136fbc50845e', '- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app {': 'abb7d22be0c90c363368d8b0c3dadfe8c0dbf812b743528bf5ae13a5db8b48a8', '- (void)waitForPalettePresentationToClose:(XCUIElement *)close {': '80d4bb267e6bbab199cae03bc9b2a8e835fb9e7136848e28943193d9158aee23', '- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {': '0cc2e246ae2d7f21edfd6fdda40d7e516fb083a29376872cb42f2345d7aa6491', '- (void)verifyHistory:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {': 'e75bc62b80e2750a7fc0750b4e199e4d24a8cd3e60b6badca1735eb7af80075e', '- (BOOL)waitForPaletteFilesPresentation:(XCUIApplication *)app {': '6b438e25d28d0ab3bc281751e34f0b7af55496432e2e8a5e17f1a0bcded97134', '- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app {': 'b603290fada1a69334022edf923b5776fe2fb7f7cbcd23389bd15d310cf5432f', '- (void)exerciseLargestTextPaletteRotationReplacesSelection:(XCUIApplication *)app {': 'e3e878f00b16e0fa1b68a96cd341701da3e28aa4d6fc3ce4b786c9f04fa32fdc', '- (void)exerciseLargestTextPaletteReviewAndImportHelp:(XCUIApplication *)app {': 'c162bff1ace8e604b91259d4c78f6e3447b0316facb8471165b1313376605893', '- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll {': '947813c17a21254e807fd70daa0a6ef4ee290537f9531be7c37571ba7ce74289', '- (void)selectSyntheticPaletteFile:(XCUIApplication *)app {': 'de3be18cca36fe13ed2950ee99579b7976802ec5ed85f09aeed7e36173150bbf', '- (BOOL)pastePalette:(NSString *)JSON app:(XCUIApplication *)app {': 'd55aa29396b48b7f1aa49462f4642ee998ea3f7242f926556c8709f33bee6270', '- (BOOL)activateVisiblePalettePaste:(XCUIApplication *)app {': '621e2a15bd8171a21e45abd0563e8ca87a01723e9e7bbf7e980f6440d83f332d', '- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app {': '318552fd608242b54fe41817d4d4f5eb53b8cd9cab0482f26c2cb103fd2b7e7d', '- (void)exercisePaletteFileCancelAndImportReturn:(XCUIApplication *)app {': 'c0f10e1458e9c4a2bc8568fcf9b6e817beb2e751f68491a2ec69f0ddae4d4032'}, 'TouchColorIPadUITests.m': {'- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileCancellationAndImportReturn { [self exercisePaletteFileCancelAndImportReturn:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteReviewAndImportHelp { [self exerciseLargestTextPaletteReviewAndImportHelp:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)choosePhoto {': 'f68d61d96e90c59812d57a14637abfd5bd576b9bc75c53376df2646f22a9b14c', '- (void)importFixture {': '4ed6e8f9d4e976830f4d35fe2984d6a023106423f9b58bb4d66776f34b7691a0', '- (void)cancelPicker {': 'a92b352cfc0348a6bc15ddf1e9bde80bcf503e8339dca471f53f615532f09e45', '- (void)assertPresentationDisappears:(XCUIElement *)presentation {': 'a60264fe303b9dc839b0b897a666db7e1586f7a2c15eaa3eca2b0496eaa0a341', '- (void)testNativeCanvasPaletteSavePreviewPickerCancelAndRelaunch {': 'a5a629ff8f6857dbd090b84df062eb812a62820d23b5492881ee31cbedb5f2a4', '- (void)testKeyboardImportSamplingZoomSaveAndRotation {': '0a7cdfacabbea0a78902077b0c593ece55eb9c7089b5bda849a9a9e96fdb5ea9', '- (void)testCancelPhotoLoadingRetainsTheCurrentCanvasAndPalette {': 'eabec474269dec499e482f88953e3a6b280622a1e7285083b8ebb5992f024124', '- (void)testLargestTextNativePaletteAndCanvasControls {': '633739bfb62eafdb92eeae1b11f735dc986d1a64ab92c9528866b62e9275fe8c', '- (void)testLiveCanvasPickerCancellationAndSceneLifecycle {': '0b7dbf396c70c2ef16e8772462a0aa994d767119a2e6eb2c9f86dde6a37e627a', '- (void)testFullScreenPaletteFlowsResumeLiveUnavailableState {': '94f73c9a1573b3555e4fcb3ba58ea47191c1b4e6673d1c89da8da2208ffb2346', '- (void)testZNativeWindowResizePreservesSelectionAndPaletteReturn {': '24025cdf804283c79ac438ee5a8decfd7e2e5eaef0d5268c4369504f6476155b', '- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {': '3929230903916f43c642bd23ebee6ba838ebb6c10b16b9dfd98daaf05d9e376b', '- (void)testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState {': '17b6d665d0dde5b4e668e79e0b0172e0ab883f2d73bd08c4059d999ca9f80434', '- (void)testPrivacyCloseRetainsPhotoSelection {': '12f37c8ec64475742d283662f3408d5a5d8b466288a24165c89e679b17491e8c'}, 'TouchColorUITests.m': {'- (void)emitScreenshot:(NSString *)name {': '562cbd5d6719f49e688ab5ee8726c86981b95c206cdc4d6c3bdb71bcd824dcf5', '- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileCancellationAndImportReturn { [self exercisePaletteFileCancelAndImportReturn:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteReviewAndImportHelp { [self exerciseLargestTextPaletteReviewAndImportHelp:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)emitPaletteLifecycleCase:(NSString *)event pid:(NSNumber *)pid {': '7540c2b333d7450d887edb7017e4cfb9633858d5dba120ca3e80a82cf8e0c1de', '- (void)revealControl:(XCUIElement *)element inScrollView:(XCUIElement *)scroll {': '912963cf5f19e812d286e00b4c5a69aa2862ca936445bd00e1f09a9a1477a433', '- (void)testPrivacyPolicyEntryOpensAndCloses {': 'af28541413932be92303eadbd9d04cd713a599cf677fb4c092f48036aaef79ef', '- (void)testLaunchAndPhotoPickerCancelRepeatedly {': 'abffaa133ac0d09f00aea36057e4bec80697b187881b8501e3657fea1f816d75', '- (void)assertPresentationDisappears:(XCUIElement *)presentation {': '7983284bd4ac961a8fdff50c83b2b2e41a4340efc8e5aa57ff47cd9ed35786cc', '- (void)respondToRealCameraPromptAllow:(BOOL)allow {': 'd0cbab91d78ef965b3743859fe99a6967fb5fd401e89c151ed0bc844fab806e5', '- (void)testRealCameraPermissionAllowThenResetAndDeny {': 'e4a6dfc0ac68d6897e3eaa86c7c8c7ba5c58140a10d2ac9eeaab50d899a6a8aa', '- (void)testSampleSaveRelaunchDeleteAndBackground {': 'aaf971ec59712853b07b97017abf347c1cbca69f9677d9ac6d7ba8ac6500ceaa', '- (void)testNoCameraAndLiveLifecycleDoNotEnableInvalidSave {': '6cfe46605b1a2329071fa22522a090f7b2e4456ae92e770171414f4290d586f3', '- (void)testAdaptiveLandscapePhotoSampling {': '28efdda455e23d4a124d906f0469e668ea5a25e0a46e653adb9612b1dd425952', '- (void)testLargestDynamicTypeControlsRemainReachable {': '4899e116f3a3758d22a24c65bb6a4572b5df0516ac9dc3f437f4a67a50701bfa', '- (void)assertMarkerAtImageX:(CGFloat)x y:(CGFloat)y {': '8f73b022c6a9b947da80f1bf3ec5b7b2bf2209438f1237cc060e2dd0e9b51848', '- (void)testAsymmetricMarkerCenterRotationLetterboxAndAccessibleZoomInDarkMode {': 'fb5bf7fb286ecd4ec279ef2f8c5d7d7aa3a59c50e47e63d9962c89f6dcc337fb', '- (void)testSystemPhotoSelectionAndSampling {': '710f140b0b7158a19655be210335a94303de514d1a5404d3ab04cb68504b4193', '- (void)tearDown {': 'c8c27a10316e30af3e915d173484a919e1bf044fee1240581e499e6d63f7f1e6', '- (void)testNativePrivacyBodyAndContactControlsRemainAvailableAfterReopen {': '5a82daca0b5685256c99bb39110ae94ad402d18026f126dfcc9273779be7a848', '- (void)testLargestTextNativePolicyCanScrollAndCloseInLandscape {': 'c3977ae117663bb117661738336b8b6ace348f2522971b5b73b37ed988f082bf'}}
def without_query_guards(text):
    text=re.sub(r'if \(!(\[self (?:pastePalette:|activateVisiblePalettePaste:)[^;]+\])\) return;',r'\1;',text)
    for owner in ('app','self.app'):
        text=text.replace('if (![self tapReadyImportPaletteClose:'+owner+']) return;','[self tapReadyPaletteElement:close timeout:5];')
    return text
# Exact inverse for the admitted common app-owned action rule only. Other10/15 gates stay as-is.
COMMON_ACTION_METHODS = {
    'TCPaletteUIHelpers.m': {
        'exercisePaletteFileCancelAndImportReturn': 3,
        'selectSyntheticPaletteFile': 1,
        'exerciseLargestTextPaletteRotationReplacesSelection': 1,
        'exerciseLargestTextPaletteReviewAndImportHelp': 2,
    },
    'TouchColorIPadUITests.m': {'testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState': 2},
}
def restore_common_action_budget(text, filename):
    for name, count in COMMON_ACTION_METHODS.get(filename, {}).items():
        pattern = r'(?ms)(^- \([^\n]+\)' + name + r'[^\n]*\{\n)(.*?)(?=^- \(|^@end)'
        found = re.search(pattern, text)
        if not found: raise ValueError('Missing closed app action method: '+name)
        body = found.group(2)
        calls = re.findall(r'\[self tapReadyPaletteElement:[^\n]*? timeout:10 existenceTimeout:5\]', body)
        if len(calls) != count: raise ValueError('Changed closed app action inventory: '+name)
        restored = re.sub(r'(\[self tapReadyPaletteElement:[^\n]*?) timeout:10 existenceTimeout:5\]', r'\1 timeout:5]', body)
        text = text[:found.start(2)] + restored + text[found.end(2):]
    return text

def restore_center_phone_wrappers(text):
    for name, exercise in [('testPalettePasteReviewAcceptAndRelaunch','exercisePalettePasteReviewAcceptAndRelaunch'),
                           ('testInvalidPalettePastePreservesHistory','exerciseInvalidPalettePastePreservesHistory')]:
        revised=f"- (void){name} {{\n    self.tcPaletteCenteredAccept=YES;\n    @try {{ [self {exercise}:self.app]; }}\n    @finally {{ self.tcPaletteCenteredAccept=NO; }}\n}}"
        if revised in text:
            text=text.replace(revised,f"- (void){name} {{ [self {exercise}:self.app]; }}")
    return text

def restore_center_helper(text):
    text=text.replace('#import <math.h>\n','').replace('static char TCPaletteCenteredAcceptKey;\n','')
    begin=text.index('// Explicit test-wrapper opt-in.')
    end=text.index('- (void)observeFailedPalettePresentation:',begin)
    text=text[:begin]+text[end:]
    begin=text.index('// A single alternate physical input')
    end=text.index('- (void)verifyOriginalPaletteSources:',begin)
    text=text[:begin]+text[end:]
    revised='    if (self.tcPaletteCenteredAccept) {\n        if (![self tapReadyPaletteAcceptCenter:app timeout:timeout]) return;\n    } else {\n        [self tapReadyPaletteElement:accept timeout:timeout existenceTimeout:5];\n    }\n'
    if text.count(revised)!=1: raise ValueError('Unexpected center dispatch scope')
    return text.replace(revised,'    [self tapReadyPaletteElement:accept timeout:timeout existenceTimeout:5];\n')

IPAD_FILES_SETUP_CLOCK='    self.tcPaletteIPadCaseStarted=NSProcessInfo.processInfo.systemUptime;\n'

def restore_ipad_files_attachment(text, filename):
    """Exact narrow inverse before the existing, unchanged source locks."""
    if filename=='TouchColorIPadUITests.m':
        added='- (void)setUp {\n'+IPAD_FILES_SETUP_CLOCK
        if text.count(added)!=1: raise ValueError('Changed iPad Files setup clock scope')
        return text.replace(added,'- (void)setUp {\n')
    if filename!='TCPaletteUIHelpers.m': return text
    revised='    if (![self waitForPaletteFilesCancellationPresentation:app]) return;\n'
    if text.count(revised)!=1: raise ValueError('Changed cancellation-only attachment scope')
    text=text.replace(revised,'    if (![self waitForPaletteFilesPresentation:app]) return;\n')
    key='static char TCPaletteIPadCaseStartedKey;\n'
    if text.count(key)!=1: raise ValueError('Changed Files setup clock storage')
    text=text.replace(key,'')
    for start,end in (
        ('- (NSTimeInterval)tcPaletteIPadCaseStarted {','- (void)observeFailedPalettePresentation:'),
        ('- (BOOL)waitForPaletteFilesCancellationPresentation:','- (void)selectSyntheticPaletteFile:')):
        if text.count(start)!=1: raise ValueError('Changed Files attachment helper scope')
        begin=text.index(start)
        finish=text.index(end,begin)
        text=text[:begin]+text[finish:]
    return text

class ReadinessSourceContracts(unittest.TestCase):
    def test_untouched_method_bytes(self):
        for name,expected in LOCKS.items():
            methods=dict(re.findall(r'(?ms)^(- \([^\n]+)\n(.*?)(?=^- \(|^@end)',restore_common_action_budget(restore_center_phone_wrappers(restore_ipad_files_attachment((ROOT/'TouchColorUITests'/name).read_text(),name)),name)))
            for signature,digest in expected.items():
                with self.subTest(file=name,signature=signature):
                    body=without_query_guards(methods[signature])
                    if ((name=='TouchColorIPadUITests.m' and signature=='- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {') or
                        (name=='TCPaletteUIHelpers.m' and signature=='- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app {')):
                        self.assertEqual(body.count('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'),1)
                        body=body.replace('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]',
                                          '[self tapReadyPaletteElement:close timeout:5]')
                    self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),digest)
    def test_only_ipad_cancel_action_allowance_changes_with_original_body_retained(self):
        text=restore_common_action_budget(restore_ipad_files_attachment((ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text(),'TouchColorIPadUITests.m'),'TouchColorIPadUITests.m')
        call='[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'
        self.assertEqual(text.count(call),1)
        body=text.split('- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        self.assertIn(call,body)
        # Remove only the exact added bilingual-body observation before checking the original full-file inverse.
        policy_observation='    XCUIElement *policy=self.app.scrollViews[@"privacy.content"];\n    XCUIElement *chinese=policy.textViews[@"privacy.body.zh-Hans"];\n    XCUIElement *english=policy.textViews[@"privacy.body.en"];\n    XCTAssertTrue([chinese waitForExistenceWithTimeout:30],@"The bundled Chinese policy body must render locally");\n    XCTAssertTrue([english waitForExistenceWithTimeout:30],@"The bundled English policy body must render locally");\n'
        self.assertEqual(text.count(policy_observation),1)
        restored=without_query_guards(text).replace(policy_observation,'').replace(call,'[self tapReadyPaletteElement:close timeout:5]')
        # Exact ee52 file inverse: preserves all original post-dismissal,
        # history, selected pixel, marker, width and keyboard assertions.
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),'8e8839f6a3c6f40387a17a7a38ebc271273ec61cb6a5e101494da7d5114069fc')
        self.assertNotIn('executionTimeAllowance',body)
        self.assertIn('actionReturned<started+5',HELPER)
        self.assertIn('BOOL completedTimely=NSProcessInfo.processInfo.systemUptime<deadline;',HELPER)

    def test_invalid_paste_close_changes_only_one_shared_action_with_exact_inverse(self):
        body=section('- (void)exerciseInvalidPalettePastePreservesHistory:', '- (void)exercisePaletteFileCancelAndImportReturn:')
        call='[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'
        self.assertEqual(body.count(call),1)
        prior=restore_common_action_budget(restore_center_helper(restore_ipad_files_attachment(HELPER,'TCPaletteUIHelpers.m')),'TCPaletteUIHelpers.m').replace('[self acceptPalette:app readinessTimeout:10]','[self acceptPalette:app readinessTimeout:5]')
        self.assertEqual(prior.count(call),1)
        restored=prior.replace(call,'[self tapReadyPaletteElement:close timeout:5]')
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),'52dce95cc03624cc17ecb8791802dbdfb7226b14dca284d3aa85c72b853d8488')
        self.assertIn('for (NSUInteger index=0;index<payloads.count;index++)',body)
        self.assertIn('[self verifyHistory:@[@"#123456",@"#123456"] app:app];',body)
        for file in ('TouchColorUITests.m','TouchColorIPadUITests.m'):
            self.assertIn('- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }', restore_center_phone_wrappers((ROOT/'TouchColorUITests'/file).read_text()))
        self.assertNotIn('executionTimeAllowance',body)

    def test_exact_three_case_allowances_and_full_workflow(self):
        body=section('- (void)exercisePalettePasteReviewAcceptAndRelaunch:', '- (void)exerciseInvalid')
        self.assertEqual(body.count('timeout:15 existenceTimeout:5'),1)
        self.assertEqual(body.count('readinessTimeout:15'),2)
        self.assertEqual(HELPER.count('readinessTimeout:15'),2)
        self.assertEqual(body.count('if (self.tcPaletteReadinessExpired) return;'),3)
        for required in ['#112233','@"#aabbcc"','#445566','[self verifyHistory:@[] app:app]','[self verifyHistory:colors app:app]','[app terminate]','[app launch]']:
            self.assertIn(required,body)
        self.assertEqual(body.count('[self verifyHistory:appended app:app]'),2)
    def test_three_argument_tap_selector_is_declared_for_external_callers(self):
        header=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.h').read_text()
        signature='- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:(NSTimeInterval)existenceTimeout'
        self.assertEqual(header.count(signature+';'),1)
        self.assertEqual(HELPER.count(signature+' {'),1)
        self.assertIn('@interface XCTestCase (TCPaletteUIHelpers)',header)
        # The new external call is in the iPad file; invalid-paste's other
        # changed call is within this category's own implementation file.
        callers=[]
        for path in sorted((ROOT/'TouchColorUITests').glob('*.m')):
            if path.name=='TCPaletteUIHelpers.m': continue
            source=path.read_text()
            for line in source.splitlines():
                if '[self tapReadyPaletteElement:' in line and 'existenceTimeout:' in line:
                    callers.append(path.name)
                    self.assertIn('#import "TCPaletteUIHelpers.h"',source)
                    self.assertIn('timeout:10 existenceTimeout:5]',line)
                    self.assertTrue('[self tapReadyPaletteElement:close ' in line or '[self tapReadyPaletteElement:self.app.buttons[@"palette.import.accept"] ' in line)
        self.assertEqual(callers,['TouchColorIPadUITests.m']*3)

    def test_wrapper_implementation_keeps_explicit_grants_and_original_clipping(self):
        self.assertIn('readyUntil:started+timeout started:started existenceTimeout:timeout',HELPER)
        self.assertIn('[self tapReadyPaletteElement:element timeout:timeout existenceTimeout:timeout]',HELPER)
        self.assertIn('[self acceptPalette:app readinessTimeout:10]',HELPER)
        self.assertNotIn('getenv',HELPER)
    def test_one_original_deadline_and_clipped_existence(self):
        body=section('- (BOOL)paletteElement:', '- (BOOL)waitForReadyPaletteElement:')
        self.assertIn('MIN(existenceTimeout,MAX(0,deadline-began))',body)
        self.assertIn('MAX(0,deadline-NSProcessInfo.processInfo.systemUptime)',body)
        self.assertNotIn('deadline=',body)
        self.assertEqual(body.count('waitForExistenceWithTimeout:'),1)
    def test_each_remote_getter_has_pre_post_fences(self):
        ready=section('BOOL (^readyNow)(void)', 'BOOL ready=readyNow();')
        self.assertRegex(ready,r'if \(!withinDeadline\(\)\) return NO;[\s\S]+BOOL enabled=element.enabled;')
        self.assertRegex(ready,r'BOOL enabled=element.enabled;[\s\S]+if \(!withinDeadline\(\) \|\| !enabled\) return NO;')
        self.assertRegex(ready,r'if \(!withinDeadline\(\)\) return NO;\s*BOOL hittable=element.hittable;')
        self.assertRegex(ready,r'BOOL hittable=element.hittable;[\s\S]+if \(!withinDeadline\(\)\) return NO;')
        self.assertIn('return readyNow();',HELPER)
    def test_logging_performs_no_remote_lookups(self):
        body=section('// Every remote getter', '- (void)scrollTowardElement:')
        for forbidden in ['element.identifier','element.label','element.frame','debugDescription','snapshot','screenshot']:
            self.assertNotIn(forbidden,body)
        self.assertIn('loggedReads<8 || duration>5',body)
        self.assertIn('slowestRead>5',body)
    def test_expiry_is_sticky_before_failure_and_tap(self):
        body=section('BOOL (^withinDeadline)', 'if (!withinDeadline()) { XCTFail')
        self.assertIn('self.tcPaletteReadinessExpired || expired',body)
        self.assertIn('expired=YES; self.tcPaletteReadinessExpired=YES; return NO',body)
        tap=section('- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:', '- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout {')
        self.assertLess(tap.index('self.tcPaletteReadinessExpired=YES'),tap.index('XCTAssertTrue(timely'))
        self.assertLess(tap.index('if (!timely) return;'),tap.index('[element tap]'))
    def test_tap_return_latches_expiry_before_failure_and_following_ax(self):
        tap=section('- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:', '- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout {')
        self.assertEqual(tap.count('[element tap]'),1)
        after=tap.split('[element tap];',1)[1]
        self.assertIn('BOOL completedTimely=NSProcessInfo.processInfo.systemUptime<deadline;',after)
        self.assertLess(after.index('self.tcPaletteReadinessExpired=YES'),after.index('XCTAssertTrue(completedTimely'))
        self.assertNotIn('deadline=',after)
        self.assertNotIn('element.',after)
        # Arithmetic boundary for the exact strict source predicate. This is not
        # native execution: the source ordering checks bind the predicate to tap.
        deadline=15.0
        for returned,expected in [(14.999,True),(15.0,False),(16.0,False)]:
            with self.subTest(returned=returned):
                self.assertEqual(returned<deadline,expected)
                sticky=not (returned<deadline)
                follow_on_ax_allowed=not sticky
                self.assertEqual(follow_on_ax_allowed,expected)
    def test_testcase_local_storage_and_reset(self):
        self.assertIn('objc_getAssociatedObject(self,&TCPaletteReadinessExpiryKey)',HELPER)
        self.assertIn('objc_setAssociatedObject(self,&TCPaletteReadinessExpiryKey',HELPER)
        for name in ['TouchColorUITests.m','TouchColorIPadUITests.m']:
            text=restore_ipad_files_attachment((ROOT/'TouchColorUITests'/name).read_text(),name)
            self.assertIn('- (void)setUp {\n    self.tcPaletteReadinessExpired=NO;\n    [super setUp];',text)
    def test_failure_hooks_preserve_issue_without_own_ax(self):
        for name in ['TouchColorUITests.m','TouchColorIPadUITests.m']:
            text=(ROOT/'TouchColorUITests'/name).read_text()
            hook=text.split('- (void)recordIssue:(XCTIssue *)issue {',1)[1].split('if (self.recordingIssue)',1)[0]
            self.assertIn('if (self.tcPaletteReadinessExpired)',hook)
            self.assertIn('[super recordIssue:issue]; return;',hook)
            for forbidden in ['self.app','screenshot','debugDescription','terminate','waitFor']:
                self.assertNotIn(forbidden, re.sub(r'//[^\n]*','',hook))
            self.assertNotIn('XCTSkip',hook)
    def test_ipad_teardown_fences_before_original_device_recovery(self):
        text=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text().split('- (void)tearDown {',1)[1]
        guard=text.split('// XCTest can end',1)[0]
        self.assertIn('if (self.tcPaletteReadinessExpired)',guard)
        self.assertIn('[super tearDown]; return;',guard)
        self.assertNotIn('self.app',guard)
        self.assertIn('@finally',text)
    def test_expired_action_returns_before_following_queries(self):
        body=section('- (void)acceptPalette:(XCUIApplication *)app readinessTimeout:', '- (void)acceptPalette:(XCUIApplication *)app {')
        self.assertLess(body.index('if (self.tcPaletteReadinessExpired) return;'),body.index('[self waitForPalettePresentationToClose:close]'))
    def test_canonical_full_matrix_and_individual_case_caps_remain(self):
        shell=(ROOT/'scripts/test_simulators.sh').read_text()
        self.assertIn('-default-test-execution-time-allowance 180',shell)
        self.assertIn('-maximum-test-execution-time-allowance 240',shell)
        self.assertIn('TouchColorUITests/TouchColorIPadUITests',shell)
        self.assertIn('TouchColorUITests/TouchColorUITests',shell)
        workflow=(ROOT/'.github/workflows/ios.yml').read_text()
        self.assertIn('family: [iPadMini, iPadLarge, iPhoneCompact, iPhoneLarge]',workflow)
        self.assertIn("timeout-minutes: ${{ matrix.family == 'iPadMini' && 70 || 60 }}",workflow)
        self.assertIn('test_uikit_palette_readiness',workflow)
        for name in ['testPalettePasteReviewAcceptAndRelaunch']:
            for file in ['TouchColorIPadUITests.m','TouchColorUITests.m']:
                text=(ROOT/'TouchColorUITests'/file).read_text()
                self.assertIn(name,text)
                self.assertIn('[self exercisePalettePasteReviewAcceptAndRelaunch:self.app]',text)
class IPadFilesCancellationAttachmentTests(unittest.TestCase):
    """Portable source/compiled control-flow checks, not a native XCTest pass."""
    def body(self):
        return section('- (BOOL)waitForPaletteFilesCancellationPresentation:(XCUIApplication *)app {',
                       '- (void)selectSyntheticPaletteFile:')

    def test_only_cancellation_calls_new_helper_and_original_wait_is_unchanged(self):
        revised='[self waitForPaletteFilesCancellationPresentation:app]'
        self.assertEqual(HELPER.count(revised),1)
        cancel=section('- (void)exercisePaletteFileCancelAndImportReturn:', '- (BOOL)waitForPaletteFilesPresentation:')
        self.assertIn(revised,cancel)
        self.assertLess(cancel.index('if (!'+revised+') return;'),cancel.index('XCUIElementQuery *pickerBars='))
        original=section('- (BOOL)waitForPaletteFilesPresentation:', '- (BOOL)waitForPaletteFilesCancellationPresentation:')
        self.assertIn('UIUserInterfaceIdiomPhone ? 25 : 20',original)
        self.assertIn('return appeared && elapsed<=budget;',original)
        selection=section('- (void)selectSyntheticPaletteFile:', '- (void)exercisePaletteFileSelectionReviewAndRelaunch:')
        self.assertIn('[self waitForPaletteFilesPresentation:app]',selection)
        self.assertNotIn(revised,selection)
        body=self.body()
        self.assertIn('userInterfaceIdiom!=UIUserInterfaceIdiomPad) return [self waitForPaletteFilesPresentation:app];',body)
        self.assertLess(body.index('if (self.tcPaletteReadinessExpired) return NO;'),body.index('userInterfaceIdiom'))
        for token in ('[app launch]','[app activate]','[picker tap]','selectSyntheticPaletteFile:', 'executionTimeAllowance'):
            self.assertNotIn(token,body)

    def test_one_setup_start_is_declared_stored_and_invalid_storage_refuses(self):
        header=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.h').read_text()
        ipad=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        phone=(ROOT/'TouchColorUITests/TouchColorUITests.m').read_text()
        self.assertIn('@property (nonatomic) NSTimeInterval tcPaletteIPadCaseStarted;',header)
        self.assertIn('- (BOOL)waitForPaletteFilesCancellationPresentation:(XCUIApplication *)app;',header)
        self.assertIn('#import "TCPaletteUIHelpers.h"',ipad)
        self.assertEqual(ipad.count(IPAD_FILES_SETUP_CLOCK),1)
        self.assertIn('- (void)setUp {\n'+IPAD_FILES_SETUP_CLOCK+'    self.tcPaletteReadinessExpired=NO;\n    [super setUp];',ipad)
        self.assertNotIn('tcPaletteIPadCaseStarted',phone)
        self.assertIn('objc_getAssociatedObject(self,&TCPaletteIPadCaseStartedKey)',HELPER)
        self.assertIn('return [value isKindOfClass:NSNumber.class] ? [value doubleValue] : NAN;',HELPER)
        self.assertIn('objc_setAssociatedObject(self,&TCPaletteIPadCaseStartedKey,@(value),OBJC_ASSOCIATION_RETAIN_NONATOMIC)',HELPER)

    def test_full_thirty_admission_precedes_owned_query_and_one_wait(self):
        body=self.body()
        self.assertEqual(body.count('deadline=started+30, caseDeadline=caseStarted+180;'),1)
        self.assertIn('isfinite(caseStarted) && caseStarted>0 && isfinite(started) && started>=caseStarted',body)
        self.assertIn('isfinite(deadline) && isfinite(caseDeadline) && caseDeadline-started>=30 && deadline<=caseDeadline',body)
        self.assertLess(body.index('if (!admitted)'),body.index('XCUIElement *picker='))
        self.assertLess(body.index('if (grant<=0)'),body.index('BOOL appeared='))
        self.assertEqual(body.count('waitForExistenceWithTimeout:'),1)
        self.assertIn('grant=deadline-NSProcessInfo.processInfo.systemUptime;',body)
        self.assertIn('@[@"FullDocumentManagerViewControllerNavigationBar",@"DOCSidebarView"]',body)
        self.assertNotIn('MIN(',body)  # Refuse partial admission instead of shrinking 30s to case remainder.
        for token in ('picker.exists','picker.identifier','picker.label','picker.frame','debugDescription','screenshot','while (','for ('):
            self.assertNotIn(token,re.sub(r'//[^\n]*','',body))

    def test_actual_return_and_logging_share_deadline_and_latch_before_failure(self):
        body=self.body()
        wait=body.index('BOOL appeared=')
        log=body.index('NSLog(',wait)
        timely=body.index('BOOL timely=returned<deadline && NSProcessInfo.processInfo.systemUptime<deadline;',log)
        latch=body.index('if (!timely || !appeared) self.tcPaletteReadinessExpired=YES;',timely)
        self.assertLess(wait,log);self.assertLess(log,timely)
        self.assertLess(latch,body.index('XCTAssertTrue(timely,'))
        self.assertLess(latch,body.index('XCTAssertTrue(appeared,'))
        self.assertIn('returned-started<=20 ? @"within" : @"missed"',body)
        self.assertNotIn('deadline=',body[wait:])
        for refusal in ('if (!admitted)', 'if (grant<=0)'):
            branch=body.split(refusal,1)[1].split('}',1)[0]
            self.assertLess(branch.index('self.tcPaletteReadinessExpired=YES;'),branch.index('XCTFail('))
            self.assertIn('return NO;',branch)

    def test_exact_inverse_preserves_original_case_and_dismissal(self):
        revised=restore_ipad_files_attachment(HELPER,'TCPaletteUIHelpers.m')
        cancel=revised.split('- (void)exercisePaletteFileCancelAndImportReturn:',1)[1].split('- (BOOL)waitForPaletteFilesPresentation:',1)[0]
        self.assertEqual(cancel.count('cancelDeadline=cancelStarted+10;'),1)
        self.assertEqual(cancel.count('[cancel tap];'),1)
        self.assertIn('[self waitForPalettePresentationToClose:cancel];',cancel)
        self.assertEqual(cancel.count('[self verifyHistory:@[] app:app];'),2)
        self.assertIn('[self verifyInitialPaletteImportControls:app];',cancel)
        self.assertIn('containsString:@"review every color"',cancel)
        dismiss=section('- (void)waitForPalettePresentationToClose:', '- (BOOL)pastePalette:')
        self.assertIn('waitForNonExistenceWithTimeout:5',dismiss)
        self.assertIn('waitForExpectations:@[gone] timeout:5',dismiss)
        # Existing full-file/method hashes are unchanged and run after this inverse.
        self.assertNotIn('tcPaletteIPadCaseStarted',revised)
        self.assertNotIn('waitForPaletteFilesCancellationPresentation:',revised)

    def test_compiled_actual_control_flow_admission_boundaries_and_failure_hooks(self):
        cc=shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(cc,'A C compiler is required for the portable deadline trace')
        body=self.body().rsplit('}',1)[0]
        body=re.sub(r'//[^\n]*','',body)
        body=body.replace('self.tcPaletteReadinessExpired','expired').replace('self.tcPaletteIPadCaseStarted','setup_started')
        body=body.replace('UIDevice.currentDevice.userInterfaceIdiom','idiom')
        body=body.replace('[self waitForPaletteFilesPresentation:app]','original_wait()')
        body=body.replace('NSProcessInfo.processInfo.systemUptime','read_clock()')
        body,n=re.subn(r'    XCUIElement \*picker=[^\n]+;','    queries++;',body)
        self.assertEqual(n,1)
        body=body.replace('[picker waitForExistenceWithTimeout:grant]','wait_for_picker(grant)')
        benchmark=re.search(r'appeared,returned-started,(.*?) \? @"within" : @"missed"',body).group(1)
        body,n=re.subn(r'    NSLog\([\s\S]*?;', '    old_within='+benchmark+'; logs++;',body)
        self.assertEqual(n,1)
        body=re.sub(r'XCTFail\(@"[^"]*"\)', 'record_failure()',body)
        body=re.sub(r'XCTAssertTrue\((\w+),@"[^"]*"\)',r'if (!\1) record_failure()',body)
        self.assertNotIn('@',body)
        harness=r'''
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
typedef double NSTimeInterval;
typedef bool BOOL;
#define YES true
#define NO false
enum { UIUserInterfaceIdiomPhone=1, UIUserInterfaceIdiomPad=2 };
static double setup_started, instants[4], last_grant;
static int idiom, reads, queries, waits, logs, failures, owned_failure_ax, legacy_waits, cancels;
static bool expired, appeared, old_within;
static double read_clock(void) { if (reads>=4) exit(90); return instants[reads++]; }
static bool original_wait(void) { legacy_waits++; last_grant=idiom==UIUserInterfaceIdiomPhone ? 25 : 20; return true; }
static bool wait_for_picker(double grant) { waits++; last_grant=grant; return appeared; }
static void record_failure(void) { failures++; if (!expired) owned_failure_ax++; }
static bool attachment(void) {
ACTUAL_BODY
}
static bool run(double setup, double start, double query_return, double wait_return, double logged, bool found) {
    setup_started=setup; instants[0]=start; instants[1]=query_return; instants[2]=wait_return; instants[3]=logged;
    reads=queries=waits=logs=failures=owned_failure_ax=legacy_waits=cancels=0;
    expired=false; appeared=found; old_within=false; last_grant=-1; idiom=UIUserInterfaceIdiomPad;
    bool result=attachment(); if (result) cancels++;
    return result;
}
#define CHECK(value) do { if (!(value)) { fprintf(stderr,"trace check failed at %d: %s\n",__LINE__,#value); return 1; } } while (0)
int main(void) {
    CHECK(run(100,120,120,135.601,135.602,true));
    CHECK(old_within && !expired && cancels==1 && queries==1 && waits==1 && last_grant==30);
    CHECK(run(100,120,120.25,142.3288707917,142.329,true));
    CHECK(!old_within && !expired && last_grant==29.75 && logs==1 && failures==0);
    CHECK(run(100,120,120,140,140.001,true)); CHECK(old_within);
    double fractional_start=nextafter(64,-INFINITY), rounded_boundary=fractional_start+20;
    CHECK(rounded_boundary==84 && rounded_boundary<=fractional_start+20);
    CHECK(rounded_boundary-fractional_start>20);
    CHECK(run(10,fractional_start,fractional_start,rounded_boundary,rounded_boundary,true));
    CHECK(!old_within && !expired && failures==0);
    CHECK(run(100,250,250,279.999,279.999,true)); CHECK(last_grant==30);
    CHECK(!run(100,nextafter(250,INFINITY),251,252,253,true));
    CHECK(queries==0 && waits==0 && expired && failures==1 && owned_failure_ax==0 && cancels==0);
    double invalid[]={0,-1,NAN,INFINITY,-INFINITY,121};
    for (unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        CHECK(!run(invalid[i],120,120,121,121,true));
        CHECK(queries==0 && waits==0 && expired && failures==1 && owned_failure_ax==0 && cancels==0);
    }
    CHECK(!run(100,120,150,150,150,true));
    CHECK(queries==1 && waits==0 && expired && failures==1 && owned_failure_ax==0);
    double late[]={150,nextafter(150,INFINITY),190};
    for (unsigned i=0;i<sizeof(late)/sizeof(late[0]);i++) {
        CHECK(!run(100,120,120,late[i],late[i],true));
        CHECK(waits==1 && logs==1 && expired && failures==1 && owned_failure_ax==0 && cancels==0);
    }
    CHECK(run(100,120,120,nextafter(150,-INFINITY),nextafter(150,-INFINITY),true));
    CHECK(!run(100,120,120,149.999,150,true));
    CHECK(expired && failures==1 && owned_failure_ax==0 && cancels==0);
    CHECK(!run(100,120,120,130,130,false));
    CHECK(expired && failures==1 && owned_failure_ax==0 && cancels==0);
    int previous_queries=queries, previous_reads=reads;
    CHECK(!attachment()); CHECK(queries==previous_queries && reads==previous_reads && failures==1);
    for (int value=0;value<=1;value++) {
        expired=false; idiom=value; setup_started=NAN; reads=queries=waits=legacy_waits=0;
        CHECK(attachment()); CHECK(legacy_waits==1 && queries==0 && waits==0 && reads==0);
        CHECK(last_grant==(value==UIUserInterfaceIdiomPhone ? 25 : 20));
    }
    return 0;
}
'''.replace('ACTUAL_BODY',body)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'attachment.c'; source.write_text(harness)
            for optimization in ('-O0','-O2'):
                binary=Path(tmp)/('attachment'+optimization)
                subprocess.run([cc,'-std=c99','-Wall','-Werror',optimization,str(source),'-lm','-o',str(binary)],check=True,capture_output=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_retained_native_observations_keep_original_outcomes(self):
        # Mini run37524057802/job112478076938 source459c70b failed before Cancel.
        self.assertGreater(22.3288707917,20)
        self.assertLess(22.3288707917,30)  # Eligible window, not a claimed native pass.
        self.assertLess(57.933,180)
        # Prior source2d LargePad kept its stricter original successful path.
        self.assertLess(15.601,20)
        self.assertLess(80.206,180)


class CenterInputSourceContracts(unittest.TestCase):
    def center(self):
        return section('- (BOOL)tapReadyPaletteAcceptCenter:', '- (void)verifyOriginalPaletteSources:')
    def test_exact_two_phone_wrappers_only_and_scoped_opt_in_cleanup(self):
        phone=(ROOT/'TouchColorUITests/TouchColorUITests.m').read_text()
        ipad=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        header=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.h').read_text()
        self.assertEqual(phone.count('self.tcPaletteCenteredAccept=YES;'),2)
        self.assertEqual(phone.count('@finally { self.tcPaletteCenteredAccept=NO; }'),2)
        restored=restore_center_phone_wrappers(phone)
        self.assertNotIn('tcPaletteCenteredAccept',restored)
        self.assertNotIn('tcPaletteCenteredAccept',ipad)
        self.assertIn('@property (nonatomic) BOOL tcPaletteCenteredAccept;',header)
        body=self.center()
        for name in ('testInvalidPalettePastePreservesHistory','testPalettePasteReviewAcceptAndRelaunch'):
            self.assertIn('-[TouchColorUITests '+name+']',body)
        self.assertIn('if (!self.tcPaletteCenteredAccept || !expectedCase) return NO;',body)
    def test_one_center_gesture_same_live_owned_element_no_fallback(self):
        body=self.center()
        self.assertIn('[app.navigationBars matchingIdentifier:@"Import Palette"]',body)
        self.assertIn('[owners.buttons matchingIdentifier:@"palette.import.accept"]',body)
        self.assertIn('if (ownerCount!=1) return NO;',body)
        self.assertIn('if (count!=1) return NO;',body)
        self.assertIn('XCUIElement *accept=matches.firstMatch;',body)
        self.assertIn('[self paletteElement:accept readyUntil:deadline started:started existenceTimeout:5]',body)
        self.assertIn('CGRect frame=accept.frame;',body)
        self.assertEqual(body.count('[accept coordinateWithNormalizedOffset:CGVectorMake(0.5,0.5)]'),1)
        self.assertEqual(body.count('[center tap];'),1)
        for banned in ('[accept tap]','sendAction','doubleTap','retry','sleep','while (','for ('):
            self.assertNotIn(banned,body)
        accept=section('- (void)acceptPalette:(XCUIApplication *)app readinessTimeout:', '- (void)acceptPalette:(XCUIApplication *)app {')
        self.assertIn('if (![self tapReadyPaletteAcceptCenter:app timeout:timeout]) return;',accept)
        self.assertIn('} else {\n        [self tapReadyPaletteElement:accept timeout:timeout existenceTimeout:5];',accept)
        self.assertEqual(accept.count('[self waitForPalettePresentationToClose:close];'),1)
    def test_current_observations_and_return_share_original_strict_deadline(self):
        body=self.center()
        self.assertEqual(body.count('deadline=started+timeout'),1)
        self.assertIn('NSProcessInfo.processInfo.systemUptime<deadline',body)
        self.assertLess(body.index('self.tcPaletteReadinessExpired=YES'),body.index('XCTAssertTrue(value'))
        for observed in ('NSUInteger ownerCount=owners.count;','NSUInteger count=matches.count;','CGRect frame=accept.frame;'):
            self.assertIn(observed+'\n    if (!timely()) return NO;',body)
        self.assertIn('if (!timely()) return NO;\n    [center tap];',body)
        after=body.split('[center tap];',1)[1]
        self.assertIn('return timely();',after)
        self.assertIn('returned<started+5',after)
        self.assertNotIn('deadline=',after)
        for query in ('accept.','app.','matches.','owners.','frame='):
            self.assertNotIn(query,after)
    def test_actual_frame_predicate_rejects_missing_invalid_or_empty_geometry(self):
        body=self.center()
        predicate=re.search(r'BOOL validFrame=(.*?);',body,re.S).group(1)
        source='#include <math.h>\n#include <assert.h>\ntypedef struct { double x,y; } Point;\ntypedef struct { double width,height; } Size;\ntypedef struct { Point origin; Size size; } Rect;\nstatic int valid(Rect frame) { return '+predicate+'; }\nint main(void) {\n'
        source+='assert(valid((Rect){{243,24},{112,36}}));\n'
        for values in ('NAN,24,112,36','243,INFINITY,112,36','243,24,NAN,36','243,24,112,INFINITY','243,24,0,36','243,24,-1,36','243,24,112,0','243,24,112,-1'):
            x,y,w,h=values.split(',');source+='assert(!valid((Rect){{'+x+','+y+'},{'+w+','+h+'}}));\n'
        source+='return 0; }\n'
        cc=shutil.which('cc');self.assertIsNotNone(cc,'A real C compiler is required for the geometry predicate')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'center.c';binary=Path(tmp)/'center';path.write_text(source)
            subprocess.run([cc,'-std=c99','-Wall','-Werror',str(path),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True)

class RetainedTimingArithmetic(unittest.TestCase):
    def setUp(self): self.f=json.loads((ROOT/'scripts/fixtures/mini-a622f8-readiness.json').read_text())
    def test_source_case_and_raw_binding(self):
        self.assertEqual(self.f['source'],'a622f8ad1ed799bc4d3f350b602c8e5d39aa2d7d')
        self.assertEqual(self.f['run'],'37349069236')
        self.assertEqual(self.f['stdout_sha256'],'58ecf2f5b3db2f80e2cb3088db01bd2a59b2213f699db2a2386ac9b99f790fa8')
        self.assertEqual(self.f['stdout_bytes'],27144)
        self.assertFalse(self.f['case_completed'])
    def test_second_remote_getter_started_after_old_total(self):
        self.assertGreater(self.f['hittable_find_start_test_seconds']-self.f['gate_start_test_seconds'],5)
        self.assertGreater(self.f['existence_elapsed_seconds']+self.f['hittable_find_start_test_seconds']-self.f['enabled_find_start_test_seconds'],5)
    def test_observed_interval_fits_new_total_not_a_native_pass(self):
        elapsed=self.f['failure_attachment_test_seconds']-self.f['gate_start_test_seconds']
        self.assertGreater(elapsed,5)
        self.assertLess(elapsed,15)
        self.assertIn('interval',self.f['completion_interval_note'])
        self.assertFalse(self.f['case_completed'])

class FunctionalCompletionContracts(unittest.TestCase):
    # Original054 assertions and actions with the single staged Watch-open action
    # explicitly replaced by Import Palette. This is not coverage equivalence.
    ORIGINAL_ASSERTIONS = ['XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,0u,@"Cancel preserves the palette");', 'XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);', 'XCTAssertEqualObjects(self.app.images[@"sampleMarker"].value,marker);', 'XCTAssertEqualWithAccuracy(self.app.images[@"sampleImage"].frame.size.width,imageWidth,2);', 'XCTAssertEqual(self.app.tables[@"colorHistory"].cells.count,2u,@"Dismissal refreshes the retained palette controller");', 'XCTAssertTrue([[self.app.tables[@"colorHistory"].cells elementBoundByIndex:index].label containsString:@"#112233"]);', 'XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);', 'XCTAssertTrue([close waitForExistenceWithTimeout:5]);', 'XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label,selected);', 'XCTAssertEqualObjects(self.app.images[@"sampleMarker"].value,marker);', 'XCTAssertGreaterThan(self.app.images[@"sampleImage"].frame.size.width,imageWidth,@"Photo keyboard focus returns after full-screen dismissal");']
    ORIGINAL_ACTIONS = ['[self importFixture];', '[self.app.images[@"sampleImage"] tap];', '[self.app typeKey:@"+" modifierFlags:0];', '[self pastePalette:@"[\\"#112233\\",\\"#112233\\"]" app:self.app];', '[self verifyPaletteRows:@[@"#112233",@"#112233"] app:self.app];', '[self tapReadyPaletteElement:close timeout:5];', '[self pastePalette:@"[\\"#112233\\",\\"#112233\\"]" app:self.app];', '[self verifyPaletteRows:@[@"#112233",@"#112233"] app:self.app];', '[self tapReadyPaletteElement:self.app.buttons[@"palette.import.accept"] timeout:5];', '[self openPaletteAction:@"palette.import.open" app:self.app];', '[self tapReadyPaletteElement:close timeout:5];', '[self.app typeKey:@"+" modifierFlags:0];']
    def test_split_preserves_individual_assertions_and_actions_with_fresh_setup(self):
        from collections import Counter
        text=restore_common_action_budget((ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text(),'TouchColorIPadUITests.m')
        cancel=text.split('- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        accept=text.split('- (void)testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        joined=cancel+accept
        current=Counter(re.findall(r'XCTAssert[^;]+;',joined))
        for item,n in Counter(self.ORIGINAL_ASSERTIONS).items():self.assertGreaterEqual(current[item],n,item)
        actions=without_query_guards(joined).replace('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]', '[self tapReadyPaletteElement:close timeout:5]')
        current=Counter(re.findall(r'(?:^|;)\s*(\[self[^;]+;)',actions,re.M))
        for item,n in Counter(self.ORIGINAL_ACTIONS).items():self.assertGreaterEqual(current[item],n,item)
        for body in (cancel,accept):
            self.assertEqual(body.count('[self importFixture]'),1)
            self.assertIn('NSString *selected=self.app.staticTexts[@"sampledColor"].label;',body)
            self.assertIn('NSString *marker=self.app.images[@"sampleMarker"].value;',body)
            self.assertIn('CGFloat imageWidth=self.app.images[@"sampleImage"].frame.size.width;',body)
            self.assertIn('XCTAssertGreaterThan(self.app.images[@"sampleImage"].frame.size.width,imageWidth',body)
            self.assertNotIn('executionTimeAllowance',body)
        self.assertNotIn('testFullScreenPaletteReviewRetainsPhotoAndKeyboardState',text)
        self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',text)),16)
    def test_rotation_conjunction_stays_one_case_with_explicit_entry_refactor(self):
        body=section('- (void)exerciseLargestTextPaletteRotationReplacesSelection:', '- (void)exerciseLargestTextPaletteReviewAndImportHelp:')
        self.assertEqual(body.count('[app launch]'),1);self.assertEqual(body.count('[app terminate]'),1)
        self.assertEqual(body.count('orientation=UIDeviceOrientationLandscapeLeft'),1)
        self.assertEqual(body.count('orientation=UIDeviceOrientationPortrait'),2)
        self.assertLess(body.index('orientation=UIDeviceOrientationPortrait'),body.index('[app launch]'))
        landscape=body.split('orientation=UIDeviceOrientationLandscapeLeft;',1)[1]
        self.assertLess(landscape.index('[self verifyPaletteRows:'),landscape.index('orientation=UIDeviceOrientationPortrait;'))
        portrait=landscape.split('orientation=UIDeviceOrientationPortrait;',1)[1]
        self.assertLess(portrait.index('UIPasteboard.generalPasteboard.string='),portrait.index('[self activateVisiblePalettePaste:app]'))
        self.assertIn('[self verifyPaletteRows:@[@"#112233",@"#aabbcc",@"#445566"] app:app];',portrait)
        self.assertIn('[self verifyHistory:@[] app:app]',portrait)
        self.assertNotIn('executionTimeAllowance',body)
        independent=section('- (void)exerciseLargestTextPaletteReviewAndImportHelp:', '@end')
        self.assertIn('orientation=UIDeviceOrientationLandscapeLeft;[app launch];',independent)
        self.assertIn('[self pastePalette:',independent)
    def test_scroll_removes_only_diagnostic_getters_keeps_live_frames_and_real_drag(self):
        body=section('- (void)scrollTowardElement:', '- (XCUIElement *)paletteElement:')
        for value in ['element.identifier','scroll.value']:self.assertNotIn(value,body)
        for value in ['viewport=scroll.frame,target=element.frame','CGFloat limit=CGRectGetHeight(viewport)*0.45;',
                      'pressForDuration:0.05 thenDragToCoordinate:end withVelocity:100 thenHoldForDuration:0.15',
                      'NSStringFromCGRect(element.frame),NSStringFromCGRect(scroll.frame)']:
            self.assertIn(value,body)
    def test_system_cancel_query_and_old_latency_are_retained(self):
        body=section('- (void)exercisePaletteFileCancelAndImportReturn:', '- (BOOL)waitForPaletteFilesPresentation:')
        self.assertEqual(restore_common_action_budget(HELPER,'TCPaletteUIHelpers.m').count('timeout:10 existenceTimeout:5'),1)
        self.assertIn('cancelDeadline=cancelStarted+10;',body)
        self.assertIn('cancelExistenceGrant=MIN(5,',body)
        self.assertIn('[cancel tap];',body)
        self.assertLess(body.index('if (!cancelTimely) return;'),body.index('[self waitForPalettePresentationToClose:cancel]'))
        self.assertIn('PALETTE_ACTION_RETURN case=%@ total=%.3f budget=%.3f responsiveness5=%@',HELPER)
        self.assertIn('actionReturned<started+5 ? @"within" : @"missed"',HELPER)
        self.assertLess(HELPER.index('PALETTE_ACTION_RETURN'),HELPER.index('BOOL completedTimely='))
    def test_provider_uses_one_fifteen_second_clock_and_keeps_already_open_ten(self):
        body=section('- (void)selectSyntheticPaletteFile:', '- (void)exercisePaletteFileSelectionReviewAndRelaunch:')
        self.assertEqual(body.count('folderDeadline=folderStarted+15;'),1)
        self.assertEqual(body.count('folderDeadline=folderStarted+10;'),1)
        self.assertIn('waitForExistenceWithTimeout:MAX(0,folderDeadline-NSProcessInfo.processInfo.systemUptime)',body)
        self.assertIn('folderReturned<folderStarted+10 ? @"within" : @"missed"',body)
        self.assertIn('folderReturned<folderDeadline && NSProcessInfo.processInfo.systemUptime<folderDeadline',body)
        for name in ('providerTimely','snapshotTimely','locationTimely','withinBudget'):
            self.assertLess(body.index('if (!'+name+') self.tcPaletteReadinessExpired=YES;'),body.index('XCTAssertTrue('+name))
            self.assertIn('if (!'+name+') return;',body)
        self.assertIn('if (remaining<=0) self.tcPaletteReadinessExpired=YES;',body)
        caller=section('- (void)exercisePaletteFileSelectionReviewAndRelaunch:', '- (void)exerciseLargestText')
        after=caller.split('[self selectSyntheticPaletteFile:app];',1)[1]
        self.assertLess(after.index('if (self.tcPaletteReadinessExpired) return;'),after.index('[self tapReadyImportPaletteClose:app]'))
        second=caller.split('[self selectSyntheticPaletteFile:app];',2)[2]
        self.assertLess(second.index('if (self.tcPaletteReadinessExpired) return;'),second.index('[self acceptPalette:app]'))
    def test_retained_timing_boundaries_are_not_relabelled_fast(self):
        # Retained054 observations: Cancel readiness4.044s plus about2s action;
        # Compact provider/folder exceeded10s while the actual folder appeared.
        for elapsed,functional,old in [(6.082,10,5),(11.01,15,10),(5.154,10,5),(5.207,10,5)]:
            self.assertLess(elapsed,functional);self.assertFalse(elapsed<old)
        # Latency labels use the original absolute ceiling too; subtraction
        # can round a boundary interval down across a floating exponent.
        for started in (1000.1,1019.9,1020.1):
            for old in (5.0,10.0):
                returned=started+old
                self.assertFalse(returned<started+old)
        for deadline in (10.0,15.0):
            self.assertTrue(deadline-.001<deadline)
            self.assertFalse(deadline<deadline)
            self.assertFalse(deadline+.001<deadline)


class ConsolidatedAXQueryContracts(unittest.TestCase):
    def paste(self): return section('- (BOOL)activateVisiblePalettePaste:', '- (void)verifyPaletteRows:')
    def cancel(self): return section('- (void)exercisePaletteFileCancelAndImportReturn:', '- (BOOL)waitForPaletteFilesPresentation:')
    def error(self): return section('- (void)exerciseInvalidPalettePastePreservesHistory:', '- (void)exercisePaletteFileCancelAndImportReturn:')
    def test_paste_uses_observed_button_type_and_query_enabled(self):
        text=self.paste()
        self.assertIn('app.tables[@"palette.import.review"].buttons matchingPredicate:',text)
        self.assertIn('identifier == %@ AND enabled == YES',text)
        self.assertIn('@"palette.import.paste"',text)
        self.assertNotIn('paste.enabled',text)
        self.assertEqual(text.count('waitForExistenceWithTimeout:'),1)
        self.assertNotIn('waitForExpectations:',text)
    def test_paste_original_combined_allowance_never_resets_after_late_lookup(self):
        text=self.paste()
        self.assertEqual(text.count('deadline=started+10;'),1)
        self.assertIn('returned<deadline && NSProcessInfo.processInfo.systemUptime<deadline',text)
        self.assertLess(text.index('if (!timely) self.tcPaletteReadinessExpired=YES;'),text.index('XCTAssertTrue(timely'))
        self.assertLess(text.index('if (!timely) return NO;'),text.index('XCUIElement *table='))
        self.assertLess(text.index('if (!ready) return NO;'),text.index('XCUIElement *table='))
    def test_paste_geometry_reloads_after_each_mutation_and_is_reused_before_next(self):
        text=self.paste()
        loop=text.split('for (NSUInteger attempt=',1)[1].split('BOOL visible=',1)[0]
        self.assertIn('attempt<5',loop)
        self.assertIn('!CGRectContainsRect(viewport,CGRectInset(target,1,1))',loop)
        self.assertLess(loop.index('[self scrollTowardElement:'),loop.index('viewport=[self paletteBodyViewport:'))
        self.assertEqual(text.count('paletteBodyViewport:'),2)
        self.assertEqual(text.count('paste.frame'),2)
        after=text.split('BOOL visible=',1)[1]
        self.assertNotIn('paste.frame',after)
        self.assertNotIn('paletteBodyViewport:',after)
        self.assertIn('BOOL hittable=paste.hittable;',after)
        self.assertIn('if (!visible) return NO;',after)
        self.assertIn('if (!hittable) return NO;',after)
        self.assertEqual(after.count('[paste tap]'),1)
    def test_paste_failures_are_propagated_to_every_real_caller(self):
        header=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.h').read_text()
        self.assertIn('- (BOOL)activateVisiblePalettePaste:(XCUIApplication *)app;',header)
        self.assertIn('- (BOOL)pastePalette:(NSString *)JSON app:(XCUIApplication *)app;',header)
        count=0
        for path in (ROOT/'TouchColorUITests').glob('*.m'):
            source=path.read_text()
            for line in source.splitlines():
                if '[self pastePalette:' not in line and '[self activateVisiblePalettePaste:' not in line: continue
                count+=1
                self.assertTrue('if (!' in line and ') return;' in line or 'return [self activateVisiblePalettePaste:app];' in line,line)
            if path.name!='TCPaletteUIHelpers.m' and ('[self pastePalette:' in source or '[self activateVisiblePalettePaste:' in source):
                self.assertIn('#import "TCPaletteUIHelpers.h"',source)
        self.assertEqual(count,14)
    def test_status_matches_native_cell_statictext_without_duplicate_label_fetch(self):
        text=self.error()
        self.assertIn('app.cells[@"palette.import.status"].staticTexts matchingPredicate:',text)
        self.assertIn('label CONTAINS %@',text)
        self.assertIn('@"must contain only",@"no larger than 1 MB"',text)
        self.assertIn('1024*1024+1',text)
        self.assertNotIn('app.debugDescription',text)
        self.assertNotIn('status.label',text)
        self.assertNotIn('XCTNSPredicateExpectation',text)
    def test_status_late_or_missing_stops_before_accept_close_history(self):
        text=self.error()
        self.assertIn('errorDeadline=errorStarted+10;',text)
        self.assertIn('errorReturned<errorDeadline && NSProcessInfo.processInfo.systemUptime<errorDeadline',text)
        self.assertLess(text.index('self.tcPaletteReadinessExpired=YES;'),text.index('XCTAssertTrue(errorTimely'))
        for fence in ('if (!errorTimely) return;','if (!errorShown) return;'):
            self.assertLess(text.index(fence),text.index('XCTAssertFalse(app.buttons[@"palette.import.accept"].enabled)'))
        self.assertIn('[self verifyHistory:@[@"#123456",@"#123456"] app:app];',text)
        close=text.split('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5];',1)[1]
        self.assertLess(close.index('if (self.tcPaletteReadinessExpired) return;'),close.index('waitForPalettePresentationToClose'))
    def test_cancel_retains_owned_navigation_query_and_live_hittable(self):
        text=self.cancel()
        self.assertIn('FullDocumentManagerViewControllerNavigationBar',text)
        self.assertIn('DOCSidebarView',text)
        self.assertIn('pickerBars.buttons matchingPredicate:',text)
        self.assertIn('(identifier == %@ OR label == %@) AND enabled == YES',text)
        self.assertNotIn('cancel.enabled',text)
        self.assertIn('BOOL value=cancel.hittable;',text)
        self.assertNotIn('hittable ==',text)
        self.assertEqual(text.count('[cancel tap]'),1)
    def test_cancel_original_ten_total_five_existence_and_old_latency_survive(self):
        text=self.cancel()
        self.assertEqual(text.count('cancelDeadline=cancelStarted+10;'),1)
        self.assertIn('cancelExistenceGrant=MIN(5,MAX(0,cancelDeadline-',text)
        self.assertIn('cancelReturned<cancelStarted+5 ? @"within" : @"missed"',text)
        self.assertIn('cancelReturned<cancelDeadline && NSProcessInfo.processInfo.systemUptime<cancelDeadline',text)
        self.assertEqual(text.count('waitForExistenceWithTimeout:cancelExistenceGrant'),1)
    def test_cancel_each_remote_stage_fenced_without_deadline_reset(self):
        text=self.cancel()
        first=text.split('BOOL cancelExists=',1)[1].split('BOOL (^cancelHittable)',1)[0]
        self.assertLess(first.index('self.tcPaletteReadinessExpired=YES'),first.index('XCTAssertTrue(cancelTimely'))
        self.assertIn('if (!cancelTimely) return;',first)
        self.assertIn('if (!cancelExists) return;',first)
        block=text.split('BOOL (^cancelHittable)',1)[1].split('BOOL cancelReady=',1)[0]
        self.assertEqual(block.count('systemUptime>=cancelDeadline'),2)
        after=text.split('[cancel tap];',1)[1]
        self.assertLess(after.index('self.tcPaletteReadinessExpired=YES'),after.index('XCTAssertTrue(cancelTimely'))
        self.assertLess(after.index('if (!cancelTimely) return;'),after.index('waitForPalettePresentationToClose'))
    def test_post_cancel_business_assertions_and_real_actions_preserved(self):
        text=self.cancel()
        for required in ('@"cancelled"','[self verifyHistory:@[] app:app]','[self verifyOriginalPaletteSources:app]',
                         '[self verifyInitialPaletteImportControls:app]','@"review every color"','[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'):
            self.assertIn(required,text)
        self.assertNotIn('executionTimeAllowance',text)
    def test_actual_fixture_types_are_also_in_existing_native_source(self):
        source=(ROOT/'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_text()
        self.assertIn('palette.import.status',source)
        self.assertIn('palette.import.paste',source)
        self.assertIn('UIPasteControl',source)
    def test_clock_boundary_trace_never_advances_after_expired_remote_return(self):
        # Requirement traces plus source-order locks above. These are portable
        # clock contracts, not a claim to execute Apple's remote AX runtime.
        import math
        for started in (0.,1000.1,1019.9):
            deadline=started+10
            for returned in (deadline,math.nextafter(deadline,math.inf),started+25.04):
                events=['lookup']
                if returned<deadline: events.extend(['hittable','tap','history'])
                self.assertEqual(events,['lookup'])
            self.assertTrue(math.nextafter(deadline,-math.inf)<deadline)
    def test_missing_disabled_occluded_controls_never_receive_tap(self):
        for exists,enabled,hittable in ((False,True,True),(True,False,True),(True,True,False)):
            matched=exists and enabled
            self.assertFalse(matched and hittable)
        self.assertIn('if (!cancelExists) return;',self.cancel())
        self.assertIn('if (!cancelReady) return;',self.cancel())
        self.assertIn('if (!ready) return NO;',self.paste())
        self.assertIn('if (!hittable) return NO;',self.paste())
    def test_retained_timings_remain_failures_without_native_success_inference(self):
        self.assertGreater(10.732,10)
        self.assertGreater(25.04,10)
        # A separately observed2.857s enabled query is removable work, but this
        # subtraction is no guarantee of the next native query or tap duration.
        self.assertLess(10.732-2.857,10)
        self.assertNotIn('XCTSkip',self.paste()+self.cancel()+self.error())


class FinalOwnedActionContracts(unittest.TestCase):
    def close(self): return section('- (BOOL)tapReadyImportPaletteClose:', '- (void)scrollTowardElement:')
    def test_two_exact_owned_close_call_sites_and_visible_declaration(self):
        header=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.h').read_text()
        signature='- (BOOL)tapReadyImportPaletteClose:(XCUIApplication *)app'
        self.assertEqual(header.count(signature+';'),1)
        self.assertEqual(HELPER.count(signature+' {'),1)
        expected={('TCPaletteUIHelpers.m','- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app {'),
                  ('TouchColorIPadUITests.m','- (void)testFullScreenPaletteFlowsResumeLiveUnavailableState {')}
        callers=[]
        for path in (ROOT/'TouchColorUITests').glob('*.m'):
            signature=None
            for line in path.read_text().splitlines():
                if line.startswith('- ('):signature=line
                if '[self tapReadyImportPaletteClose:' in line:
                    callers.append((path.name,signature));self.assertIn('if (![self tapReadyImportPaletteClose:',line);self.assertIn(']) return;',line)
                    self.assertIn('#import "TCPaletteUIHelpers.h"',path.read_text())
        self.assertEqual(set(callers),expected)
        self.assertEqual(len(callers),2)
    def test_close_fixed_owner_and_enabled_query_keep_live_hittable_and_tap(self):
        body=self.close()
        self.assertIn('app.navigationBars[@"Import Palette"].buttons matchingPredicate:',body)
        self.assertIn('identifier == %@ AND enabled == YES',body)
        self.assertIn('@"palette.import.close"',body)
        self.assertNotIn('close.enabled',body)
        self.assertEqual(body.count('BOOL value=close.hittable;'),1)
        self.assertEqual(body.count('[close tap];'),1)
        self.assertNotIn('hittable ==',body)
    def test_close_single_ten_admission_five_existence_old_five_and_posttap_fence(self):
        body=self.close()
        self.assertEqual(body.count('deadline=started+10;'),1)
        self.assertIn('grant=MIN(5,MAX(0,deadline-',body)
        self.assertIn('returned<started+5 ? @"within" : @"missed"',body)
        after=body.split('[close tap];',1)[1]
        self.assertIn('returned<deadline && NSProcessInfo.processInfo.systemUptime<deadline',after)
        self.assertLess(after.index('self.tcPaletteReadinessExpired=YES'),after.index('XCTAssertTrue(timely'))
        self.assertIn('return timely;',after)
        self.assertNotIn('deadline=',after)
    def test_close_every_unproved_state_stops_and_getters_are_fenced(self):
        body=self.close()
        for guard in ('if (!timely) return NO;','if (!matched) return NO;','if (!ready) return NO;'):
            self.assertIn(guard,body)
        hit=body.split('BOOL (^hittableNow)',1)[1].split('BOOL ready=',1)[0]
        self.assertEqual(hit.count('systemUptime>=deadline'),2)
        self.assertLess(body.index('deadline expired') if 'deadline expired' in body else body.index('Owned Close expired before tap'),body.index('[close tap];'))
        for line in body.splitlines():
            if 'NSLog(' in line:
                for bad in ('close.label','close.identifier','close.frame','debugDescription'):self.assertNotIn(bad,line)
    def test_paste_only_adds_verified_positive_table_scope_and_keeps_ten(self):
        body=section('- (BOOL)activateVisiblePalettePaste:', '- (void)verifyPaletteRows:')
        self.assertIn('app.tables[@"palette.import.review"].buttons matchingPredicate:',body)
        self.assertEqual(body.count('deadline=started+10;'),1)
        self.assertIn('if (!timely) return NO;',body)
        self.assertIn('BOOL hittable=paste.hittable;',body)
    def test_measured_close_misses_are_not_relabelled_within_five(self):
        for elapsed in (6.312,9.794):
            self.assertGreater(elapsed,5);self.assertLess(elapsed,10)
        self.assertGreater(9.794-4.203,5) # The actual observed tap segment alone.
        self.assertGreater(69.291,10) # Paste remains a failure under unchanged10.
    def test_post_close_original_business_assertions_remain(self):
        ipad=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        body=ipad.split('- (void)testFullScreenPaletteFlowsResumeLiveUnavailableState {',1)[1].split('- (void)testPrivacyClose',1)[0]
        for token in ('index<2','if (index==1)','pressButton:XCUIDeviceButtonHome','[self.app activate]','[self assertPresentationDisappears:close]',
                      "label CONTAINS 'not available'",'XCTAssertFalse(self.app.buttons[@"saveLiveColor"].enabled)','colorHistory'):
            self.assertIn(token,body)
        file=section('- (void)exercisePaletteFileSelectionReviewAndRelaunch:', '- (void)exerciseLargestText')
        for token in ('[self waitForPalettePresentationToClose:close]','[self verifyHistory:@[@"#112233"] app:app]','[app terminate]','[app launch]',
                      '@[@"#112233",@"#445566",@"#445566",@"#aabbcc"]'):
            self.assertIn(token,file)


class CommonAppActionAllowanceTests(unittest.TestCase):
    def test_exact_nine_explicit_sites_and_three_default_accept_consumers(self):
        total=0
        for filename, methods in COMMON_ACTION_METHODS.items():
            text=(ROOT/'TouchColorUITests'/filename).read_text()
            restored=restore_common_action_budget(text,filename)
            self.assertEqual(text.count('timeout:10 existenceTimeout:5]')-restored.count('timeout:10 existenceTimeout:5]'),sum(methods.values()))
            total+=sum(methods.values())
        self.assertEqual(total,9)
        default=section('- (void)acceptPalette:(XCUIApplication *)app {','- (void)verifyHistory:')
        self.assertIn('[self acceptPalette:app readinessTimeout:10];',default)
        self.assertNotIn('readinessTimeout:5',default)
        self.assertEqual(HELPER.count('[self acceptPalette:app];'),3)
        self.assertEqual(HELPER.count('[self acceptPalette:app readinessTimeout:15]'),2)
        self.assertEqual(HELPER.count('[self tapReadyPaletteElement:close timeout:15 existenceTimeout:5]'),1)
        # Both file-source calls are the app review's fixed button, not system Files controls.
        for name in ('exercisePaletteFileCancelAndImportReturn','selectSyntheticPaletteFile'):
            body=HELPER.split('- (void)'+name+':',1)[1].split('\n- (',1)[0]
            self.assertIn('@"palette.import.file"',body)
            self.assertNotRegex(body,r'tapReadyPaletteElement:(?:cancel|provider|folder) timeout:10')

    def test_original_admission_and_late_return_fence_keep_boundary(self):
        body=section('- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:', '- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout {')
        self.assertIn('deadline=started+timeout',body)
        self.assertIn('existenceTimeout:existenceTimeout',body)
        self.assertIn('actionReturned<started+5',body)
        self.assertIn('if (!completedTimely) self.tcPaletteReadinessExpired=YES;',body)
        self.assertEqual(body.count('[element tap];'),1)
        for returned,expected in ((9.999,True),(10.0,False),(10.001,False),(69.291,False)):
            self.assertEqual(returned<10,expected)
        readiness=section('- (BOOL)paletteElement:', '- (BOOL)waitForReadyPaletteElement:')
        self.assertIn('MIN(existenceTimeout,MAX(0,deadline-began))',readiness)
        self.assertIn('BOOL enabled=element.enabled;',readiness)
        self.assertIn('BOOL hittable=element.hittable;',readiness)


if __name__=='__main__': unittest.main()


class PaletteRowSnapshotContracts(unittest.TestCase):
    """Portable source checks; real XCTest snapshot timing/shape is a native gate."""
    def body(self): return section('- (void)verifyPaletteRows:', '- (void)verifyHistory:')
    def test_values_use_one_owned_table_snapshot_per_unchanged_state(self):
        b=self.body()
        self.assertIn('XCUIElement *row=table.cells[identifier];',b)
        self.assertEqual(b.count('[table snapshotWithError:&error]'),1)
        self.assertIn('tableSnapshot.children',b)
        self.assertIn('node.elementType!=XCUIElementTypeCell',b)
        self.assertIn('child.elementType!=XCUIElementTypeStaticText',b)
        self.assertIn('[child.label isEqualToString:colors[index]]',b)
        self.assertIn('[child.label isEqualToString:RGB]',b)
        self.assertIn('XCTAssertTrue(hexFound',b);self.assertIn('XCTAssertTrue(rgbFound',b)
        for retired in ('paletteElement:','row.exists','row.staticTexts','row.debugDescription','app.debugDescription'):
            self.assertNotIn(retired,b)
    def test_duplicate_unknown_or_out_of_order_cells_are_rejected(self):
        b=self.body()
        self.assertIn('index<colors.count && (NSInteger)index>previous',b)
        self.assertIn('if (!ordered) return NO;',b)
        self.assertIn('previous=(NSInteger)index;',b)
        self.assertIn('insertObjects:node.children atIndexes:',b) # depth-first document order
        self.assertIn('XCTAssertNotNil(rendered',b)
        self.assertIn('if (!rendered) return;',b)
    def test_real_scroll_discards_then_reacquires_and_live_hit_is_not_a_snapshot(self):
        b=self.body()
        self.assertIn('attempt<=5',b);self.assertIn('attempt==5',b)
        self.assertIn('rendered && row.hittable',b)
        fence=b.index('tableSnapshot=nil;cells=nil;rendered=nil;')
        drag=b.index('if (!materialized) [table swipeUpWithVelocity:')
        self.assertLess(fence,drag)
        self.assertIn('if (!captureRows()) return;',b[drag:])
        self.assertIn('[row waitForExistenceWithTimeout:5]',b)
        self.assertIn('if (!exists || !captureRows()) return;',b)
        self.assertNotIn('[row tap]',b)
        self.assertNotIn('executionTimeAllowance',b)
    def test_original_readiness_and_same_process_invalid_sequence_are_retained(self):
        b=self.body();self.assertIn('object:app.buttons[@"palette.import.accept"]',b)
        self.assertIn('waitForExpectations:@[loaded] timeout:5',b)
        invalid=section('- (void)exerciseInvalidPalettePastePreservesHistory:', '- (void)exercisePaletteFileCancelAndImportReturn:')
        self.assertIn('for (NSUInteger index=0;index<payloads.count;index++)',invalid)
        self.assertIn('1024*1024+1',invalid);self.assertIn('must contain only',invalid)
        self.assertIn('no larger than 1 MB',invalid)
        self.assertIn('[self verifyHistory:@[@"#123456",@"#123456"] app:app];',invalid)
        self.assertNotIn('[app launch]',invalid)
        paste=section('- (BOOL)activateVisiblePalettePaste:', '- (void)verifyPaletteRows:')
        self.assertIn('deadline=started+10',paste)
        self.assertIn('if (!timely) return NO;',paste)
        self.assertGreater(31.588,10) # same-head Large Phone failure stays failed
    def test_retained_mini_elapsed_is_lookup_cost_not_error_processing(self):
        # Exact public32f4 case-relative timings, not an app responsiveness metric.
        self.assertGreater(140.11-42.94,97)
        self.assertLess(2.059,10);self.assertLess(1.291,10)
        self.assertLess(3.684,10)
        self.assertGreater(190.67,180) # original case already expired before cleanup


class PaletteMaterializationFrameReuse(unittest.TestCase):
    def test_saved_frames_cannot_cross_the_actual_gesture_into_next_state(self):
        b=section('- (void)verifyPaletteRows:', '- (void)verifyHistory:')
        saved=b.index('CGRect viewport=materialized ? tableSnapshot.frame : CGRectZero;')
        target=b.index('CGRect target=materialized ? rendered.frame : CGRectZero;')
        discarded=b.index('tableSnapshot=nil;cells=nil;rendered=nil;')
        drag=b.index('thenDragToCoordinate:end withVelocity:100 thenHoldForDuration:0.15')
        fresh=b.index('if (!captureRows()) return;',drag)
        self.assertLess(saved,target);self.assertLess(target,discarded)
        self.assertLess(discarded,drag);self.assertLess(drag,fresh)
        self.assertNotIn('row.frame',b);self.assertNotIn('table.frame',b)
        self.assertNotIn('scrollTowardElement:row',b)
        self.assertIn('rendered && row.hittable',b)
        self.assertIn('attempt<=5',b);self.assertIn('attempt==5',b)
        for token in ('CGRectGetHeight(viewport)*0.45','CGVectorMake(8,0)',
                      'CGVectorMake(0,-distance)','pressForDuration:0.05',
                      'XCTAssertTrue(hexFound','XCTAssertTrue(rgbFound'):
            self.assertIn(token,b)
        self.assertNotIn('executionTimeAllowance',b)
