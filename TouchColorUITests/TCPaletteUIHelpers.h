#import <XCTest/XCTest.h>

@interface XCTestCase (TCPaletteUIHelpers)
@property (nonatomic) BOOL tcPaletteReadinessExpired; // Testcase-local, sticky until setUp.
- (void)observeFailedPalettePresentation:(XCUIApplication *)app caseName:(NSString *)caseName;
- (BOOL)waitForReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout;
- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout;
- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:(NSTimeInterval)existenceTimeout;
- (BOOL)tapReadyImportPaletteClose:(XCUIApplication *)app;
- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll;
- (void)returnToPaletteFrom:(NSString *)title app:(XCUIApplication *)app;
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app;
- (BOOL)activateVisiblePalettePaste:(XCUIApplication *)app;
- (BOOL)pastePalette:(NSString *)JSON app:(XCUIApplication *)app;
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app;
- (BOOL)waitForPaletteFilesPresentation:(XCUIApplication *)app;
- (void)verifyOriginalPaletteSources:(XCUIApplication *)app;
- (void)verifyInitialPaletteImportControls:(XCUIApplication *)app;
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app;
- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app;
- (void)exercisePaletteFileCancelAndImportReturn:(XCUIApplication *)app;
- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app;
- (void)exerciseLargestTextPaletteRotationReplacesSelection:(XCUIApplication *)app;
- (void)exerciseLargestTextPaletteReviewAndImportHelp:(XCUIApplication *)app;
@end
