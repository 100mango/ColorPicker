#import <XCTest/XCTest.h>

@interface XCTestCase (TCPaletteUIHelpers)
- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll;
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app;
- (void)pastePalette:(NSString *)JSON app:(XCUIApplication *)app;
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app;
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app;
- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app;
- (void)exercisePaletteFileCancelAndWatchInboxReturn:(XCUIApplication *)app;
- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app;
- (void)exerciseLargestTextPaletteReviewAndInbox:(XCUIApplication *)app;
@end
