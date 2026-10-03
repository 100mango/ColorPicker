#import "TCPaletteUIHelpers.h"
#import <UIKit/UIKit.h>

@implementation XCTestCase (TCPaletteUIHelpers)
- (void)scrollTowardElement:(XCUIElement *)element inScroll:(XCUIElement *)scroll {
    CGRect viewport=scroll.frame,target=element.frame;
    CGFloat distance=CGRectGetMidY(target)-CGRectGetMidY(viewport);
    CGFloat limit=CGRectGetHeight(viewport)*0.45;
    distance=MAX(-limit,MIN(limit,distance));
    // Start in the observed 16-point content gutter, outside UIButton tracking.
    // A held drag starting on a control can legitimately remain owned by that control.
    XCUICoordinate *start=[[scroll coordinateWithNormalizedOffset:CGVectorMake(0,0.5)] coordinateWithOffset:CGVectorMake(8,0)];
    XCUICoordinate *end=[start coordinateWithOffset:CGVectorMake(0,-distance)];
    // Full-speed flicks overshoot this short viewport and oscillate between its
    // ends. A measured held drag uses the same real scrolling without inertia.
    NSLog(@"CONTROL_SCROLL before target=%@ frame=%@ viewport=%@ state=%@ gutterX=8 delta=%.2f",element.identifier,NSStringFromCGRect(target),NSStringFromCGRect(viewport),scroll.value,distance);
    [start pressForDuration:0.05 thenDragToCoordinate:end withVelocity:100 thenHoldForDuration:0.15];
    NSLog(@"CONTROL_SCROLL after target=%@ frame=%@ viewport=%@ state=%@",element.identifier,NSStringFromCGRect(element.frame),NSStringFromCGRect(scroll.frame),scroll.value);
}
- (XCUIElement *)paletteElement:(NSString *)identifier app:(XCUIApplication *)app {
    return [[app descendantsMatchingType:XCUIElementTypeAny] matchingIdentifier:identifier].firstMatch;
}
- (void)returnToPaletteFrom:(NSString *)title app:(XCUIApplication *)app {
    XCUIElement *bar=app.navigationBars[title];
    XCUIElement *back=[bar.buttons matchingPredicate:[NSPredicate predicateWithFormat:@"identifier == 'BackButton' OR label == 'TouchColor'"]].firstMatch;
    XCTAssertTrue([back waitForExistenceWithTimeout:5]);XCTAssertTrue(back.enabled);XCTAssertTrue(back.hittable);
    NSLog(@"PALETTE_RETURN title=%@ button=%@ frame=%@",title,back.identifier,NSStringFromCGRect(back.frame));
    [back tap];
    XCTAssertTrue([app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
    XCTAssertFalse(bar.exists,@"The exact detail navigation must disappear after Back");
}
- (CGRect)paletteBodyViewport:(XCUIApplication *)app table:(XCUIElement *)table title:(NSString *)title {
    CGRect frame=CGRectIntersection(table.frame,app.windows.firstMatch.frame);
    CGFloat top=MAX(CGRectGetMinY(frame),CGRectGetMaxY(app.navigationBars[title].frame));
    return CGRectMake(frame.origin.x,top,frame.size.width,MAX(0,CGRectGetMaxY(frame)-top));
}
- (void)openPaletteAction:(NSString *)identifier app:(XCUIApplication *)app {
    XCUIElement *action=app.buttons[identifier], *scroll=app.scrollViews[@"sourceControls"];
    XCTAssertTrue([action waitForExistenceWithTimeout:5]);
    for (NSUInteger attempt=0;attempt<5 && !action.hittable;attempt++) {
        [self scrollTowardElement:action inScroll:scroll];
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
    [self activateVisiblePalettePaste:app];
}
- (void)activateVisiblePalettePaste:(XCUIApplication *)app {
    XCUIElement *paste=[self paletteElement:@"palette.import.paste" app:app];
    XCTAssertTrue([paste waitForExistenceWithTimeout:5]);
    XCTNSPredicateExpectation *ready=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"enabled == true"] object:paste];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[ready] timeout:5],XCTWaiterResultCompleted,@"The system Paste control must be enabled before the single tap");
    XCUIElement *table=app.tables[@"palette.import.review"];
    for (NSUInteger attempt=0;attempt<5 && !CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(paste.frame,1,1));attempt++) [self scrollTowardElement:paste inScroll:table];
    XCTAssertTrue(CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(paste.frame,1,1)),@"The complete system Paste control must be visible");
    XCTAssertTrue(paste.hittable);
    NSLog(@"NATIVE_PASTE_CONTROL frame=%@ body=%@ orientation=%ld",NSStringFromCGRect(paste.frame),NSStringFromCGRect([self paletteBodyViewport:app table:table title:@"Import Palette"]),(long)XCUIDevice.sharedDevice.orientation);
    if ([app.launchArguments containsObject:@"--ui-test-scroll-state"]) {
        NSData *bytes=UIImageJPEGRepresentation(XCUIScreen.mainScreen.screenshot.image,0.55);
        XCTAssertLessThanOrEqual(bytes.length,500*1024u);
        XCTAttachment *attachment=[XCTAttachment attachmentWithData:bytes uniformTypeIdentifier:@"public.jpeg"];
        attachment.name=@"touchcolor-largest-paste-control";attachment.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:attachment];
    }
    [paste tap];
}
- (void)verifyPaletteRows:(NSArray<NSString *> *)colors app:(XCUIApplication *)app {
    XCUIElement *table=app.tables[@"palette.import.review"];
    XCTNSPredicateExpectation *loaded=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithFormat:@"enabled == true"] object:app.buttons[@"palette.import.accept"]];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[loaded] timeout:5],XCTWaiterResultCompleted,@"Real import must finish before its exact contents are reviewed");
    for (NSUInteger index=0;index<colors.count;index++) {
        XCUIElement *row=[self paletteElement:[NSString stringWithFormat:@"palette.import.color.%lu",(unsigned long)index] app:app];
        // Large self-sizing status rows can put the next color outside UITableView's
        // accessibility virtualization range. Scroll the real table to materialize it.
        for (NSUInteger attempt=0;attempt<5 && (!row.exists || !row.hittable);attempt++) {
            if (!row.exists) [table swipeUpWithVelocity:XCUIGestureVelocitySlow]; else [self scrollTowardElement:row inScroll:table];
        }
        XCTAssertTrue([row waitForExistenceWithTimeout:5],@"%@",app.debugDescription);
        unsigned int value=0;XCTAssertTrue([[NSScanner scannerWithString:[colors[index] substringFromIndex:1]] scanHexInt:&value]);
        NSString *RGB=[NSString stringWithFormat:@"R %u   G %u   B %u",(value>>16)&255,(value>>8)&255,value&255];
        // UITableView exposes these as two actual StaticText children, not a
        // synthesized label on the Cell. Assert both exact rendered values.
        XCTAssertTrue(row.staticTexts[colors[index]].exists,@"%@",row.debugDescription);
        XCTAssertTrue(row.staticTexts[RGB].exists,@"Numeric channels must be independently readable: %@",row.debugDescription);
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
        XCUIElement *status=[self paletteElement:@"palette.import.status" app:app].staticTexts.firstMatch;
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
    XCTAssertTrue(close.hittable);XCTAssertTrue([[self paletteElement:@"palette.import.status" app:app].staticTexts.firstMatch.label containsString:@"cancelled"]);
    [close tap];[self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
    [self openPaletteAction:@"watch.inbox.open" app:app];
    XCUIElement *status=[self paletteElement:@"watch.inbox.status" app:app];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]);XCTAssertGreaterThan(status.staticTexts.firstMatch.label.length,0u);
    close=app.buttons[@"watch.inbox.close"];XCTAssertTrue(close.hittable);[close tap];
    [self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
}
- (void)selectSyntheticPaletteFile:(XCUIApplication *)app {
    [self openPaletteAction:@"palette.import.open" app:app];
    XCUIElement *source=[self paletteElement:@"palette.import.file" app:app];
    XCTAssertTrue([source waitForExistenceWithTimeout:5]);[source tap];
    XCUIElement *file=[app.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label BEGINSWITH 'TouchColor-Ordered-Colors'"]].firstMatch;
    if (![file waitForExistenceWithTimeout:3]) {
        NSString *location=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad ? @"On My iPad" : @"On My iPhone";
        XCUIElement *local=app.staticTexts[location].firstMatch;
        if (!local.exists) {
            XCUIElement *browse=app.buttons[@"Browse"].firstMatch;
            XCTAssertTrue([browse waitForExistenceWithTimeout:5],@"%@",app.debugDescription);[browse tap];
        }
        XCTAssertTrue([local waitForExistenceWithTimeout:5],@"%@",app.debugDescription);[local tap];
        XCUIElement *folder=app.staticTexts[@"Palette Fixtures"].firstMatch;
        XCTAssertTrue([folder waitForExistenceWithTimeout:10],@"%@",app.debugDescription);[folder tap];
    }
    XCTAssertTrue([file waitForExistenceWithTimeout:10],@"%@",app.debugDescription);
    XCUIElement *tile=[app.cells containingType:XCUIElementTypeStaticText identifier:@"TouchColor-Ordered-Colors.json"].firstMatch;
    XCTAssertTrue([tile waitForExistenceWithTimeout:5]);
    XCUIElement *icon=tile.images.firstMatch;
    XCTAssertTrue(icon.exists);XCTAssertTrue(tile.enabled);XCTAssertTrue(tile.hittable);
    XCTAssertTrue(CGRectContainsRect(tile.frame,icon.frame));
    CGRect tileFrame=tile.frame, iconFrame=icon.frame;
    NSLog(@"FILE_TILE_SELECTION cell=%@ enabled=%d hittable=%d frame=%@ icon=%@",tile.identifier,tile.enabled,tile.hittable,NSStringFromCGRect(tileFrame),NSStringFromCGRect(iconFrame));
    // The icon is decorative; its selectable parent owns this observed hit point.
    [[tile coordinateWithNormalizedOffset:CGVectorMake((CGRectGetMidX(iconFrame)-CGRectGetMinX(tileFrame))/tileFrame.size.width,(CGRectGetMidY(iconFrame)-CGRectGetMinY(tileFrame))/tileFrame.size.height)] tap];
    // A visible filename is not evidence that the picker handed a URL to the app.
    [self waitForPalettePresentationToClose:tile];
    [self verifyPaletteRows:@[@"#445566",@"#445566",@"#aabbcc"] app:app];
}
- (void)exercisePaletteFileSelectionReviewAndRelaunch:(XCUIApplication *)app {
    [self pastePalette:@"[\"#112233\"]" app:app];
    [self verifyPaletteRows:@[@"#112233"] app:app];[self acceptPalette:app];
    [self selectSyntheticPaletteFile:app];
    XCUIElement *close=app.buttons[@"palette.import.close"];[close tap];[self waitForPalettePresentationToClose:close];
    [self verifyHistory:@[@"#112233"] app:app];
    [self selectSyntheticPaletteFile:app];[self acceptPalette:app];
    NSArray *expected=@[@"#112233",@"#445566",@"#445566",@"#aabbcc"];
    [self verifyHistory:expected app:app];
    [app terminate];app.launchArguments=@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];[app launch];
    [self verifyHistory:expected app:app];
}
- (void)exerciseLargestTextPaletteReviewAndInbox:(XCUIApplication *)app {
    [app terminate];
    app.launchArguments=@[@"--ui-test-reset",@"--ui-test-dark",@"--ui-test-scroll-state",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;[app launch];
    [self pastePalette:@"[\"#112233\",\"#aabbcc\"]" app:app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:app];
    // Rotate the still-present native control, then activate it again and verify
    // the same actual selection. A visible frame alone cannot prove Paste works.
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    [self activateVisiblePalettePaste:app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:app];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    XCUIElement *table=app.tables[@"palette.import.review"];
    for (NSString *text in @[@"#aabbcc",@"R 170   G 187   B 204"]) {
        XCUIElement *label=table.staticTexts[text].firstMatch;
        XCTAssertTrue([label waitForExistenceWithTimeout:5]);
        for (NSUInteger attempt=0;attempt<5 && !CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(label.frame,1,1));attempt++) {
            [self scrollTowardElement:label inScroll:table];
        }
        XCTAssertTrue(CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(label.frame,1,1)),@"Full numeric text must remain readable below navigation: %@",app.debugDescription);
    }
    XCUIElement *close=app.buttons[@"palette.import.close"];
    XCTAssertTrue(close.hittable);XCTAssertTrue(app.buttons[@"palette.import.accept"].hittable);
    [close tap];[self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
    [self openPaletteAction:@"watch.inbox.open" app:app];
    XCUIElement *status=[self paletteElement:@"watch.inbox.status" app:app];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]);
    table=app.tables[@"watch.inbox"];
    XCUIElement *label=status.staticTexts.firstMatch;
    XCTAssertTrue(label.exists);XCTAssertGreaterThan(label.label.length,0u);
    // Long explanations may exceed this short viewport; their beginning and end
    // must both be scroll-reachable without shrinking the user's text size.
    for (NSUInteger attempt=0;attempt<5 && CGRectGetMinY(label.frame)<CGRectGetMinY([self paletteBodyViewport:app table:table title:@"Watch Inbox"])-1;attempt++) [table swipeDown];
    XCTAssertGreaterThanOrEqual(CGRectGetMinY(label.frame),CGRectGetMinY([self paletteBodyViewport:app table:table title:@"Watch Inbox"])-1);
    for (NSUInteger attempt=0;attempt<5 && CGRectGetMaxY(label.frame)>CGRectGetMaxY([self paletteBodyViewport:app table:table title:@"Watch Inbox"])+1;attempt++) [table swipeUp];
    XCTAssertLessThanOrEqual(CGRectGetMaxY(label.frame),CGRectGetMaxY([self paletteBodyViewport:app table:table title:@"Watch Inbox"])+1);
    close=app.buttons[@"watch.inbox.close"];XCTAssertTrue(close.hittable);[close tap];
    [self waitForPalettePresentationToClose:close];
}
@end
