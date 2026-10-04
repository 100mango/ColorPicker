#import <XCTest/XCTest.h>

@interface XCTestCase (TCPaletteUIHelpers)
- (BOOL)waitForReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout;
- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout;
- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll;
- (void)returnToPaletteFrom:(NSString *)title app:(XCUIApplication *)app;
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app;
- (void)activateVisiblePalettePaste:(XCUIApplication *)app;
- (void)pastePalette:(NSString *)JSON app:(XCUIApplication *)app;
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app;
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app;
- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app;
- (void)exercisePaletteFileCancelAndWatchInboxReturn:(XCUIApplication *)app;
- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app;
- (void)exerciseLargestTextPaletteRotationReplacesSelection:(XCUIApplication *)app;
- (void)exerciseLargestTextPaletteReviewAndInbox:(XCUIApplication *)app;
@end
