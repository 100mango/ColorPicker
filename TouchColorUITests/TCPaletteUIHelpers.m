#import "TCPaletteUIHelpers.h"
#import <UIKit/UIKit.h>

@implementation XCTestCase (TCPaletteUIHelpers)
- (XCUIElement *)paletteElement:(NSString *)identifier app:(XCUIApplication *)app {
    return [[app descendantsMatchingType:XCUIElementTypeAny] matchingIdentifier:identifier].firstMatch;
}
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app {
    XCUIElement *action=app.buttons[identifier], *scroll=app.scrollViews[@"sourceControls"];
    XCTAssertTrue([action waitForExistenceWithTimeout:5]);
    for (NSUInteger attempt=0;attempt<5 && !action.hittable;attempt++) {
        if (CGRectGetMinY(action.frame)<CGRectGetMinY(scroll.frame)) [scroll swipeDown]; else [scroll swipeUp];
    }
    XCTAssertTrue(action.hittable,@"%@",app.debugDescription);[action tap];
}
- (void)waitForPalettePresentationToClose:(XCUIElement *)close {
    BOOL closed;
    if (@available(iOS 18.0,*)) closed=[close waitForNonExistenceWithTimeout:5];
    else {
        XCTNSPredicateExpectation *gone=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"exists == false"] object:close];
        closed=[XCTWaiter waitForExpectations:@[gone] timeout:5]==XCTWaiterResultCompleted;
    }
    XCTAssertTrue(closed,@"The actual import/inbox presentation must close");
}
- (void)pastePalette:(NSString *)JSON app:(XCUIApplication *)app {
    UIPasteboard.generalPasteboard.string=JSON;
    [self openPaletteAction:@"palette.import.open" app:app];
    XCUIElement *paste=[self paletteElement:@"palette.import.paste" app:app];
    XCTAssertTrue([paste waitForExistenceWithTimeout:5]);XCTAssertTrue(paste.hittable);[paste tap];
}
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {
    XCUIElement *table=app.tables[@"palette.import.review"];
    for (NSUInteger index=0;index<colors.count;index++) {
        XCUIElement *row=[self paletteElement:[NSString stringWithFormat:@"palette.import.color.%lu",(unsigned long)index] app:app];
        for (NSUInteger attempt=0;attempt<5 && !row.hittable;attempt++) [table swipeUp];
        XCTAssertTrue([row waitForExistenceWithTimeout:5],@"%@",app.debugDescription);
        XCTAssertTrue([row.label containsString:colors[index]]);
        XCTAssertTrue([row.label containsString:@"R "] && [row.label containsString:@"G "] && [row.label containsString:@"B "],@"Numeric channels must be independently readable: %@",row.label);
    }
}
- (void)verifyHistory:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {
    XCUIElement *history=app.tables[@"colorHistory"];
    if (colors.count) XCTAssertTrue([history.cells.firstMatch waitForExistenceWithTimeout:5]);
    XCTAssertEqual(history.cells.count,colors.count,@"Palette order and duplicates must be preserved");
    for (NSUInteger index=0;index<colors.count;index++) XCTAssertTrue([[history.cells elementBoundByIndex:index].label containsString:colors[index]],@"%@",history.debugDescription);
}
- (void)acceptPalette:(XCUIApplication *)app {
    XCUIElement *accept=app.buttons[@"palette.import.accept"], *close=app.buttons[@"palette.import.close"];
    XCTAssertTrue([accept waitForExistenceWithTimeout:5]);XCTAssertTrue(accept.enabled);[accept tap];
    [self waitForPalettePresentationToClose:close];
}
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app {
    NSArray *colors=@[@"#112233",@"#112233",@"#aabbcc"];
    NSString *JSON=@"[\"#112233\",\"#112233\",\"#AABBCC\"]";
    [self pastePalette:JSON app:app];[self verifyPaletteRows:colors app:app];
    XCUIElement *close=app.buttons[@"palette.import.close"];[close tap];[self waitForPalettePresentationToClose:close];
    [self verifyHistory:@[] app:app];
    [self pastePalette:JSON app:app];[self verifyPaletteRows:colors app:app];[self acceptPalette:app];
    [self verifyHistory:colors app:app];
    [self pastePalette:@"[\"#445566\"]" app:app];[self verifyPaletteRows:@[@"#445566"] app:app];[self acceptPalette:app];
    NSArray *appended=[colors arrayByAddingObject:@"#445566"];[self verifyHistory:appended app:app];
    [app terminate];app.launchArguments=@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];[app launch];
    [self verifyHistory:appended app:app];
}
- (void)exerciseInvalidPalettePastePreservesHistory:(XCUIApplication *)app {
    [self pastePalette:@"[\"#123456\",\"#123456\"]" app:app];
    [self verifyPaletteRows:@[@"#123456",@"#123456"] app:app];[self acceptPalette:app];
    NSArray *payloads=@[@"[\"#abcdef\",123]",[[[@" " stringByPaddingToLength:1024*1024+1 withString:@" " startingAtIndex:0] stringByAppendingString:@"[]"] copy]];
    NSArray *messages=@[@"must contain only",@"no larger than 1 MB"];
    for (NSUInteger index=0;index<payloads.count;index++) {
        [self pastePalette:payloads[index] app:app];
        XCUIElement *status=[self paletteElement:@"palette.import.status" app:app];
        XCTNSPredicateExpectation *error=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"label CONTAINS %@",messages[index]] object:status];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[error] timeout:10],XCTWaiterResultCompleted,@"%@",app.debugDescription);
        XCTAssertFalse(app.buttons[@"palette.import.accept"].enabled);
        XCUIElement *close=app.buttons[@"palette.import.close"];[close tap];[self waitForPalettePresentationToClose:close];
        [self verifyHistory:@[@"#123456",@"#123456"] app:app];
    }
}
- (void)exercisePaletteFileCancelAndWatchInboxReturn:(XCUIApplication *)app {
    [self openPaletteAction:@"palette.import.open" app:app];
    XCUIElement *file=[self paletteElement:@"palette.import.file" app:app];XCTAssertTrue([file waitForExistenceWithTimeout:5]);[file tap];
    XCUIElement *cancel=[app.buttons matchingPredicate:[NSPredicate predicateWithFormat:@"label == 'Cancel' AND identifier != 'palette.import.close'"]].firstMatch;
    XCTAssertTrue([cancel waitForExistenceWithTimeout:10],@"%@",app.debugDescription);[cancel tap];
    [self waitForPalettePresentationToClose:cancel];
    XCUIElement *close=app.buttons[@"palette.import.close"];
    XCTAssertTrue(close.hittable);XCTAssertTrue([[self paletteElement:@"palette.import.status" app:app].label containsString:@"cancelled"]);
    [close tap];[self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
    [self openPaletteAction:@"watch.inbox.open" app:app];
    XCUIElement *status=[self paletteElement:@"watch.inbox.status" app:app];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]);XCTAssertGreaterThan(status.label.length,0u);
    close=app.buttons[@"watch.inbox.close"];XCTAssertTrue(close.hittable);[close tap];
    [self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
}
@end
