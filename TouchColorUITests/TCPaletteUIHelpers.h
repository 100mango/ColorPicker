#import <XCTest/XCTest.h>

@interface XCTestCase (TCPaletteUIHelpers)
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app;
- (void)pastePalette:(NSString *)JSON app:(XCUIApplication *)app;
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app;
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app;
- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app;
- (void)exercisePaletteFileCancelAndWatchInboxReturn:(XCUIApplication *)app;
@end
