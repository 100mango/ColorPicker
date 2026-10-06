"""Portable source contracts and retained timing arithmetic; these do not execute XCTest."""
import hashlib,json,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HELPER=(ROOT/'TouchColorUITests/TCPaletteUIHelpers.m').read_text()
def section(start,end): return HELPER.split(start,1)[1].split(end,1)[0]
LOCKS={'TCPaletteUIHelpers.m': {'- (XCUIElement *)paletteElement:(NSString *)identifier app:(XCUIApplication *)app {': 'bd76b81e3cd0dba5e7338ffe1e75da1d1720b149707f7a355a29fb032a103a87', '- (void)returnToPaletteFrom:(NSString *)title app:(XCUIApplication *)app {': 'e6a9d262c92120711056db033297901a7daad34e33bd1101a1cb52ebca435be2', '- (CGRect)paletteBodyViewport:(XCUIApplication *)app table:(XCUIElement *)table title:(NSString *)title {': '1c24405d1835718ae9fcd118cc29a0bb194df94e29a2b03c3e3c136fbc50845e', '- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app {': 'abb7d22be0c90c363368d8b0c3dadfe8c0dbf812b743528bf5ae13a5db8b48a8', '- (void)waitForPalettePresentationToClose:(XCUIElement *)close {': '80d4bb267e6bbab199cae03bc9b2a8e835fb9e7136848e28943193d9158aee23', '- (void)pastePalette:(NSString *)JSON app:(XCUIApplication *)app {': 'c08167f15d514c1e198f73388569907eb19808b6019183e40b0732f0dfed1c50', '- (void)activateVisiblePalettePaste:(XCUIApplication *)app {': 'b582598a55bf65ee522cc7d27ff4a2b518c6ebbe7ef62ce5e35e71a9426525b4', '- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {': '1197df52e6126912f57b07eca023b3c7013f4f4248622456c810f6de663d1613', '- (void)verifyHistory:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {': 'e75bc62b80e2750a7fc0750b4e199e4d24a8cd3e60b6badca1735eb7af80075e', '- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app {': '603d23ed2f5952f34adcf96babb1c8609f3ac36869b2ae9d7afcf16c32a4634f', '- (BOOL)waitForPaletteFilesPresentation:(XCUIApplication *)app {': '6b438e25d28d0ab3bc281751e34f0b7af55496432e2e8a5e17f1a0bcded97134', '- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app {': 'b603290fada1a69334022edf923b5776fe2fb7f7cbcd23389bd15d310cf5432f', '- (void)exerciseLargestTextPaletteRotationReplacesSelection:(XCUIApplication *)app {': 'e3e878f00b16e0fa1b68a96cd341701da3e28aa4d6fc3ce4b786c9f04fa32fdc', '- (void)exerciseLargestTextPaletteReviewAndImportHelp:(XCUIApplication *)app {': 'c162bff1ace8e604b91259d4c78f6e3447b0316facb8471165b1313376605893', '- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll {': '947813c17a21254e807fd70daa0a6ef4ee290537f9531be7c37571ba7ce74289', '- (void)exercisePaletteFileCancelAndImportReturn:(XCUIApplication *)app {': 'aca216481a5b8b4de9396fd08f0c51a2bb5be5b0ef143a0311dc984dac1eadbc', '- (void)selectSyntheticPaletteFile:(XCUIApplication *)app {': 'de3be18cca36fe13ed2950ee99579b7976802ec5ed85f09aeed7e36173150bbf'}, 'TouchColorIPadUITests.m': {'- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileCancellationAndImportReturn { [self exercisePaletteFileCancelAndImportReturn:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteReviewAndImportHelp { [self exerciseLargestTextPaletteReviewAndImportHelp:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)choosePhoto {': 'f68d61d96e90c59812d57a14637abfd5bd576b9bc75c53376df2646f22a9b14c', '- (void)importFixture {': '4ed6e8f9d4e976830f4d35fe2984d6a023106423f9b58bb4d66776f34b7691a0', '- (void)cancelPicker {': 'a92b352cfc0348a6bc15ddf1e9bde80bcf503e8339dca471f53f615532f09e45', '- (void)assertPresentationDisappears:(XCUIElement *)presentation {': 'a60264fe303b9dc839b0b897a666db7e1586f7a2c15eaa3eca2b0496eaa0a341', '- (void)testNativeCanvasPaletteSavePreviewPickerCancelAndRelaunch {': 'a5a629ff8f6857dbd090b84df062eb812a62820d23b5492881ee31cbedb5f2a4', '- (void)testKeyboardImportSamplingZoomSaveAndRotation {': '0a7cdfacabbea0a78902077b0c593ece55eb9c7089b5bda849a9a9e96fdb5ea9', '- (void)testCancelPhotoLoadingRetainsTheCurrentCanvasAndPalette {': 'eabec474269dec499e482f88953e3a6b280622a1e7285083b8ebb5992f024124', '- (void)testLargestTextNativePaletteAndCanvasControls {': '633739bfb62eafdb92eeae1b11f735dc986d1a64ab92c9528866b62e9275fe8c', '- (void)testLiveCanvasPickerCancellationAndSceneLifecycle {': '0b7dbf396c70c2ef16e8772462a0aa994d767119a2e6eb2c9f86dde6a37e627a', '- (void)testFullScreenPaletteFlowsResumeLiveUnavailableState {': '94f73c9a1573b3555e4fcb3ba58ea47191c1b4e6673d1c89da8da2208ffb2346', '- (void)testPrivacyCloseRetainsPhotoSelection {': '5a42447627e2a9d946e39a632d42697123a50b1f48231bfa30b4233e9d2613c3', '- (void)testZNativeWindowResizePreservesSelectionAndPaletteReturn {': '24025cdf804283c79ac438ee5a8decfd7e2e5eaef0d5268c4369504f6476155b', '- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {': '3929230903916f43c642bd23ebee6ba838ebb6c10b16b9dfd98daaf05d9e376b', '- (void)testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState {': '17b6d665d0dde5b4e668e79e0b0172e0ab883f2d73bd08c4059d999ca9f80434'}, 'TouchColorUITests.m': {'- (void)emitScreenshot:(NSString *)name {': '562cbd5d6719f49e688ab5ee8726c86981b95c206cdc4d6c3bdb71bcd824dcf5', '- (void)testPalettePasteReviewAcceptAndRelaunch { [self exercisePalettePasteReviewAcceptAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileCancellationAndImportReturn { [self exercisePaletteFileCancelAndImportReturn:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testPaletteFileSelectionReviewAndRelaunch { [self exercisePaletteFileSelectionReviewAndRelaunch:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteReviewAndImportHelp { [self exerciseLargestTextPaletteReviewAndImportHelp:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)testLargestTextPaletteRotationReplacesSelection { [self exerciseLargestTextPaletteRotationReplacesSelection:self.app]; }': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '- (void)emitPaletteLifecycleCase:(NSString *)event pid:(NSNumber *)pid {': 'f73beaf8f36d5c3cf18026753ca48c29b432458816f673b814120c3cb49de4ba', '- (void)revealControl:(XCUIElement *)element inScrollView:(XCUIElement *)scroll {': '912963cf5f19e812d286e00b4c5a69aa2862ca936445bd00e1f09a9a1477a433', '- (void)testPrivacyPolicyEntryOpensAndCloses {': '72ea29cc8e37565ce97ed31acb89d3d50faf6c3165f4fe76ccae8f51a373d731', '- (void)testPrivacyOfflineRetryAndClose {': 'ca076a1ca93908dd01ea3bc439d1a3214ac7a9f702cb37847b40cb5118b897fa', '- (void)testLaunchAndPhotoPickerCancelRepeatedly {': 'abffaa133ac0d09f00aea36057e4bec80697b187881b8501e3657fea1f816d75', '- (void)assertPresentationDisappears:(XCUIElement *)presentation {': '7983284bd4ac961a8fdff50c83b2b2e41a4340efc8e5aa57ff47cd9ed35786cc', '- (void)respondToRealCameraPromptAllow:(BOOL)allow {': 'd0cbab91d78ef965b3743859fe99a6967fb5fd401e89c151ed0bc844fab806e5', '- (void)testRealCameraPermissionAllowThenResetAndDeny {': 'e4a6dfc0ac68d6897e3eaa86c7c8c7ba5c58140a10d2ac9eeaab50d899a6a8aa', '- (void)testSampleSaveRelaunchDeleteAndBackground {': 'aaf971ec59712853b07b97017abf347c1cbca69f9677d9ac6d7ba8ac6500ceaa', '- (void)testNoCameraAndLiveLifecycleDoNotEnableInvalidSave {': '6cfe46605b1a2329071fa22522a090f7b2e4456ae92e770171414f4290d586f3', '- (void)testAdaptiveLandscapePhotoSampling {': '28efdda455e23d4a124d906f0469e668ea5a25e0a46e653adb9612b1dd425952', '- (void)testLargestDynamicTypeControlsRemainReachable {': '4899e116f3a3758d22a24c65bb6a4572b5df0516ac9dc3f437f4a67a50701bfa', '- (void)assertMarkerAtImageX:(CGFloat)x y:(CGFloat)y {': '8f73b022c6a9b947da80f1bf3ec5b7b2bf2209438f1237cc060e2dd0e9b51848', '- (void)testAsymmetricMarkerCenterRotationLetterboxAndAccessibleZoomInDarkMode {': 'fb5bf7fb286ecd4ec279ef2f8c5d7d7aa3a59c50e47e63d9962c89f6dcc337fb', '- (void)testLargestTextOfflinePolicyCanScrollRetryAndCloseInLandscape {': '90ee3d4b51adb56a68c9b5b11be7179e0254fdb601ce8bc1250ef5ec7a0aef8b', '- (void)testSystemPhotoSelectionAndSampling {': '710f140b0b7158a19655be210335a94303de514d1a5404d3ab04cb68504b4193', '- (void)tearDown {': 'c8c27a10316e30af3e915d173484a919e1bf044fee1240581e499e6d63f7f1e6'}}
class ReadinessSourceContracts(unittest.TestCase):
    def test_untouched_method_bytes(self):
        for name,expected in LOCKS.items():
            methods=dict(re.findall(r'(?ms)^(- \([^\n]+)\n(.*?)(?=^- \(|^@end)',(ROOT/'TouchColorUITests'/name).read_text()))
            for signature,digest in expected.items():
                with self.subTest(file=name,signature=signature):
                    body=methods[signature]
                    if ((name=='TouchColorIPadUITests.m' and signature=='- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {') or
                        (name=='TCPaletteUIHelpers.m' and signature=='- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app {')):
                        self.assertEqual(body.count('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'),1)
                        body=body.replace('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]',
                                          '[self tapReadyPaletteElement:close timeout:5]')
                    self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),digest)
    def test_only_ipad_cancel_action_allowance_changes_with_original_body_retained(self):
        text=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        call='[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]'
        self.assertEqual(text.count(call),1)
        body=text.split('- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        self.assertIn(call,body)
        restored=text.replace(call,'[self tapReadyPaletteElement:close timeout:5]')
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
        self.assertEqual(HELPER.count(call),1)
        restored=HELPER.replace(call,'[self tapReadyPaletteElement:close timeout:5]')
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),'2cba5729c60d3a320385ce31058f1ba3a8477da3d88b462ed07f90b4ba084304')
        self.assertIn('for (NSUInteger index=0;index<payloads.count;index++)',body)
        self.assertIn('[self verifyHistory:@[@"#123456",@"#123456"] app:app];',body)
        for file in ('TouchColorUITests.m','TouchColorIPadUITests.m'):
            self.assertIn('- (void)testInvalidPalettePastePreservesHistory { [self exerciseInvalidPalettePastePreservesHistory:self.app]; }', (ROOT/'TouchColorUITests'/file).read_text())
        self.assertNotIn('executionTimeAllowance',body)

    def test_exact_three_case_allowances_and_full_workflow(self):
        body=section('- (void)exercisePalettePasteReviewAcceptAndRelaunch:', '- (void)exercisePalette')
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
                    self.assertIn('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]',line)
        self.assertEqual(callers,['TouchColorIPadUITests.m'])

    def test_existing_wrapper_grants_are_unchanged(self):
        self.assertIn('readyUntil:started+timeout started:started existenceTimeout:timeout',HELPER)
        self.assertIn('[self tapReadyPaletteElement:element timeout:timeout existenceTimeout:timeout]',HELPER)
        self.assertIn('[self acceptPalette:app readinessTimeout:5]',HELPER)
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
            text=(ROOT/'TouchColorUITests'/name).read_text()
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
        self.assertIn('timeout-minutes: 60',workflow)
        self.assertIn('test_uikit_palette_readiness',workflow)
        for name in ['testPalettePasteReviewAcceptAndRelaunch']:
            for file in ['TouchColorIPadUITests.m','TouchColorUITests.m']:
                text=(ROOT/'TouchColorUITests'/file).read_text()
                self.assertIn(name,text)
                self.assertIn('[self exercisePalettePasteReviewAcceptAndRelaunch:self.app]',text)
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
        text=(ROOT/'TouchColorUITests/TouchColorIPadUITests.m').read_text()
        cancel=text.split('- (void)testFullScreenPaletteCancelRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        accept=text.split('- (void)testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState {',1)[1].split('- (void)',1)[0]
        joined=cancel+accept
        current=Counter(re.findall(r'XCTAssert[^;]+;',joined))
        for item,n in Counter(self.ORIGINAL_ASSERTIONS).items():self.assertGreaterEqual(current[item],n,item)
        actions=joined.replace('[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5]', '[self tapReadyPaletteElement:close timeout:5]')
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
    def test_system_cancel_is_unchanged_and_old_latency_is_retained(self):
        body=section('- (void)exercisePaletteFileCancelAndImportReturn:', '- (BOOL)waitForPaletteFilesPresentation:')
        self.assertEqual(HELPER.count('timeout:10 existenceTimeout:5'),2)
        self.assertIn('[self tapReadyPaletteElement:cancel timeout:10 existenceTimeout:5];',body)
        self.assertLess(body.index('if (self.tcPaletteReadinessExpired) return;'),body.index('[self waitForPalettePresentationToClose:cancel]'))
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
        self.assertLess(after.index('if (self.tcPaletteReadinessExpired) return;'),after.index('[self tapReadyPaletteElement:close'))
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

if __name__=='__main__': unittest.main()
