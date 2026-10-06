#import "TCPaletteUIHelpers.h"
#import <UIKit/UIKit.h>
#import "TCFilesPickerRoute.h"
#import <objc/runtime.h>

static char TCPaletteReadinessExpiryKey;

static TCFilesRoute TCFilesRouteForSnapshot(id<XCUIElementSnapshot> snapshot, NSString *location) {
    if (!snapshot) return TCFilesRouteNone;
    CGRect frame=snapshot.frame;
    if (!TCFilesRouteFrameIsUsable(frame.origin.x,frame.origin.y,frame.size.width,frame.size.height)) return TCFilesRouteNone;
    XCUIElementType type=snapshot.elementType;
    TCFilesNodeKind kind=TCFilesNodeOther;
    if (type==XCUIElementTypeCell) kind=TCFilesNodeCell;
    else if (type==XCUIElementTypeButton) kind=TCFilesNodeButton;
    else if (type==XCUIElementTypeStaticText) kind=TCFilesNodeStaticText;
    else if (type!=XCUIElementTypeOther) return TCFilesRouteNone;
    return TCClassifyFilesRoute(kind,snapshot.identifier.UTF8String,snapshot.label.UTF8String,location.UTF8String);
}

@implementation XCTestCase (TCPaletteUIHelpers)
- (BOOL)tcPaletteReadinessExpired { return [objc_getAssociatedObject(self,&TCPaletteReadinessExpiryKey) boolValue]; }
- (void)setTcPaletteReadinessExpired:(BOOL)value { objc_setAssociatedObject(self,&TCPaletteReadinessExpiryKey,value ? @YES : nil,OBJC_ASSOCIATION_RETAIN_NONATOMIC); }
- (void)observeFailedPalettePresentation:(XCUIApplication *)app caseName:(NSString *)caseName {
    if (![app.launchArguments containsObject:@"--ui-test-palette-lifecycle"]) return;
    BOOL fileCase=[caseName containsString:@"testPaletteFileCancellationAndImportReturn"] || [caseName containsString:@"testPaletteFileSelectionReviewAndRelaunch"];
    if (!fileCase) return;
    // The original failure and its pixels have already been recorded. Observe
    // the same presentation once, without tapping, retrying the flow or changing
    // its result. XCTest remote calls remain subject to the outer case deadline.
    XCUIElement *picker=[app.navigationBars matchingPredicate:[NSPredicate predicateWithFormat:@"identifier IN %@",@[@"FullDocumentManagerViewControllerNavigationBar",@"DOCSidebarView"]]].firstMatch;
    NSTimeInterval start=NSProcessInfo.processInfo.systemUptime;
    BOOL appeared=[picker waitForExistenceWithTimeout:5];
    NSLog(@"PALETTE_POST_FAILURE_OBSERVATION originalFailurePreserved=1 pickerAppeared=%d elapsed=%.3f budget=5",appeared,NSProcessInfo.processInfo.systemUptime-start);
    if (appeared) NSLog(@"PALETTE_POST_FAILURE_PICKER identifier=%@ frame=%@",picker.identifier,NSStringFromCGRect(picker.frame));
}
// Every remote getter uses the original deadline; logging reads runner-local values only.
- (BOOL)paletteElement:(XCUIElement *)element readyUntil:(NSTimeInterval)deadline
               started:(NSTimeInterval)started existenceTimeout:(NSTimeInterval)existenceTimeout {
    __block BOOL expired=NO;
    __block NSUInteger loggedReads=0;
    __block NSTimeInterval slowestRead=0;
    void (^recordRead)(NSString *, BOOL, NSTimeInterval)=^(NSString *phase, BOOL value, NSTimeInterval began) {
        NSTimeInterval now=NSProcessInfo.processInfo.systemUptime, duration=now-began;
        slowestRead=MAX(slowestRead,duration);
        // At most eight ordinary records, plus slow reads bounded by this gate's deadline.
        if (loggedReads<8 || duration>5) {
            NSLog(@"PALETTE_READINESS case=%@ phase=%@ value=%d read=%.3f total=%.3f budget=%.3f slow=%d",
                  self.name,phase,value,duration,now-started,deadline-started,duration>5);
            loggedReads++;
        }
    };
    BOOL (^withinDeadline)(void)=^BOOL {
        if (self.tcPaletteReadinessExpired || expired || NSProcessInfo.processInfo.systemUptime>=deadline) {
            expired=YES; self.tcPaletteReadinessExpired=YES; return NO;
        }
        return YES;
    };
    if (!withinDeadline()) { XCTFail(@"Palette readiness expired before existence lookup"); return NO; }
    NSTimeInterval began=NSProcessInfo.processInfo.systemUptime;
    NSTimeInterval existenceGrant=MIN(existenceTimeout,MAX(0,deadline-began));
    if (existenceGrant<=0) { self.tcPaletteReadinessExpired=YES; XCTFail(@"Palette readiness has no existence allowance"); return NO; }
    BOOL exists=[element waitForExistenceWithTimeout:existenceGrant];
    recordRead(@"exists",exists,began);
    BOOL timely=withinDeadline();
    XCTAssertTrue(timely,@"Native existence resolution exhausted the original readiness budget");
    if (!timely) return NO;
    XCTAssertTrue(exists,@"The observed palette element must exist before checking readiness");
    if (!exists) return NO;
    BOOL (^readyNow)(void)=^BOOL {
        if (!withinDeadline()) return NO;
        NSTimeInterval enabledStarted=NSProcessInfo.processInfo.systemUptime;
        if (enabledStarted>=deadline) { expired=YES; self.tcPaletteReadinessExpired=YES; return NO; }
        BOOL enabled=element.enabled;
        recordRead(@"enabled",enabled,enabledStarted);
        if (!withinDeadline() || !enabled) return NO;
        NSTimeInterval hittableStarted=NSProcessInfo.processInfo.systemUptime;
        // A slow enabled read must never be followed by another AX read after expiry.
        if (!withinDeadline()) return NO;
        BOOL hittable=element.hittable;
        recordRead(@"hittable",hittable,hittableStarted);
        if (!withinDeadline()) return NO;
        return hittable;
    };
    BOOL ready=readyNow();
    if (!ready && !expired) {
        NSPredicate *predicate=[NSPredicate predicateWithBlock:^BOOL(id ignored, NSDictionary *bindings) { return readyNow(); }];
        XCTNSPredicateExpectation *expectation=[[XCTNSPredicateExpectation alloc] initWithPredicate:predicate object:nil];
        NSTimeInterval remaining=MAX(0,deadline-NSProcessInfo.processInfo.systemUptime);
        if (remaining>0) ready=[XCTWaiter waitForExpectations:@[expectation] timeout:remaining]==XCTWaiterResultCompleted;
        else expired=YES;
    }
    timely=withinDeadline();
    NSLog(@"PALETTE_READINESS_FINAL case=%@ ready=%d timelyBeforeLog=%d total=%.3f budget=%.3f slowestRead=%.3f slow=%d",
          self.name,ready,timely,NSProcessInfo.processInfo.systemUptime-started,deadline-started,slowestRead,slowestRead>5);
    // Local logging can consume time too; the final tap wrapper rechecks again.
    timely=withinDeadline();
    XCTAssertTrue(timely,@"Remote readiness evaluation overran the original budget");
    if (!timely) return NO;
    XCTAssertTrue(ready,@"Palette action must be enabled and hittable before its single tap");
    return ready;
}
- (BOOL)waitForReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout {
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime;
    return [self paletteElement:element readyUntil:started+timeout started:started existenceTimeout:timeout];
}
- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout existenceTimeout:(NSTimeInterval)existenceTimeout {
    NSTimeInterval started=NSProcessInfo.processInfo.systemUptime, deadline=started+timeout;
    if (![self paletteElement:element readyUntil:deadline started:started existenceTimeout:existenceTimeout]) return;
    NSLog(@"PALETTE_ACTION_READY case=%@ total=%.3f budget=%.3f",self.name,NSProcessInfo.processInfo.systemUptime-started,timeout);
    BOOL timely=NSProcessInfo.processInfo.systemUptime<deadline;
    if (!timely) self.tcPaletteReadinessExpired=YES;
    XCTAssertTrue(timely,@"Palette action deadline expired before tap");
    if (!timely) return;
    [element tap];
    // A dispatched action may itself return late. Preserve that action, then fence
    // all following owned AX work before recording its unchanged-deadline failure.
    NSTimeInterval actionReturned=NSProcessInfo.processInfo.systemUptime;
    NSLog(@"PALETTE_ACTION_RETURN case=%@ total=%.3f budget=%.3f responsiveness5=%@",
          self.name,actionReturned-started,timeout,actionReturned<started+5 ? @"within" : @"missed");
    BOOL completedTimely=NSProcessInfo.processInfo.systemUptime<deadline;
    if (!completedTimely) self.tcPaletteReadinessExpired=YES;
    XCTAssertTrue(completedTimely,@"Palette action returned after its original deadline");
}
- (void)tapReadyPaletteElement:(XCUIElement *)element timeout:(NSTimeInterval)timeout {
    [self tapReadyPaletteElement:element timeout:timeout existenceTimeout:timeout];
}
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
    NSLog(@"CONTROL_SCROLL before frame=%@ viewport=%@ gutterX=8 delta=%.2f",NSStringFromCGRect(target),NSStringFromCGRect(viewport),distance);
    [start pressForDuration:0.05 thenDragToCoordinate:end withVelocity:100 thenHoldForDuration:0.15];
    NSLog(@"CONTROL_SCROLL after frame=%@ viewport=%@",NSStringFromCGRect(element.frame),NSStringFromCGRect(scroll.frame));
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
        attachment.name=UIDeviceOrientationIsLandscape(XCUIDevice.sharedDevice.orientation)?@"touchcolor-largest-paste-control-landscape":@"touchcolor-largest-paste-control-portrait";attachment.lifetime=XCTAttachmentLifetimeKeepAlways;[self addAttachment:attachment];
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
- (void)acceptPalette:(XCUIApplication *)app readinessTimeout:(NSTimeInterval)timeout {
    XCUIElement *accept=app.buttons[@"palette.import.accept"], *close=app.buttons[@"palette.import.close"];
    [self tapReadyPaletteElement:accept timeout:timeout existenceTimeout:5];
    if (self.tcPaletteReadinessExpired) return;
    [self waitForPalettePresentationToClose:close];
}
- (void)acceptPalette:(XCUIApplication *)app {
    [self acceptPalette:app readinessTimeout:5];
}
- (void)verifyOriginalPaletteSources:(XCUIApplication *)app {
    XCUIElement *sources=app.scrollViews[@"sourceControls"];
    XCTAssertTrue([sources waitForExistenceWithTimeout:5]);
    NSArray *identifiers=[sources.buttons.allElementsBoundByIndex valueForKey:@"identifier"];
    XCTAssertEqualObjects(identifiers,(@[@"choosePhoto",@"takePhoto",@"liveColor",@"palette.import.open"]));
    XCTAssertFalse(app.buttons[@"watch.inbox.open"].exists);
}
- (void)verifyInitialPaletteImportControls:(XCUIApplication *)app {
    XCUIElement *table=app.tables[@"palette.import.review"];
    XCTAssertTrue([table waitForExistenceWithTimeout:5]);
    for (NSString *identifier in @[@"palette.import.file",@"palette.import.paste"]) {
        XCUIElement *control=[self paletteElement:identifier app:app];
        for (NSUInteger attempt=0;attempt<5 && (!control.exists || !CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(control.frame,1,1)));attempt++) {
            if (!control.exists) [table swipeDown]; else [self scrollTowardElement:control inScroll:table];
        }
        XCTAssertTrue(CGRectContainsRect([self paletteBodyViewport:app table:table title:@"Import Palette"],CGRectInset(control.frame,1,1)));
        if (![self waitForReadyPaletteElement:control timeout:5]) return;
    }
    XCTAssertFalse(app.buttons[@"palette.import.accept"].enabled);
    XCTAssertFalse(app.cells[@"palette.import.color.0"].exists);
    XCTAssertTrue(app.buttons[@"palette.import.close"].hittable);
    XCTAssertFalse(app.buttons[@"watch.inbox.open"].exists);
}
- (void)exercisePalettePasteReviewAcceptAndRelaunch:(XCUIApplication *)app {
    NSArray *colors=@[@"#112233",@"#112233",@"#aabbcc"];
    NSString *JSON=@"[\"#112233\",\"#112233\",\"#AABBCC\"]";
    [self pastePalette:JSON app:app];[self verifyPaletteRows:colors app:app];
    XCUIElement *close=app.buttons[@"palette.import.close"];[self tapReadyPaletteElement:close timeout:15 existenceTimeout:5];
    if (self.tcPaletteReadinessExpired) return;
    [self waitForPalettePresentationToClose:close];
    [self verifyHistory:@[] app:app];
    [self pastePalette:JSON app:app];[self verifyPaletteRows:colors app:app];[self acceptPalette:app readinessTimeout:15];
    if (self.tcPaletteReadinessExpired) return;
    [self verifyHistory:colors app:app];
    [self pastePalette:@"[\"#445566\"]" app:app];[self verifyPaletteRows:@[@"#445566"] app:app];[self acceptPalette:app readinessTimeout:15];
    if (self.tcPaletteReadinessExpired) return;
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
        XCUIElement *close=app.buttons[@"palette.import.close"];[self tapReadyPaletteElement:close timeout:10 existenceTimeout:5];[self waitForPalettePresentationToClose:close];
        [self verifyHistory:@[@"#123456",@"#123456"] app:app];
    }
}
- (void)exercisePaletteFileCancelAndImportReturn:(XCUIApplication *)app {
    [self openPaletteAction:@"palette.import.open" app:app];
    XCUIElement *file=[self paletteElement:@"palette.import.file" app:app];[self tapReadyPaletteElement:file timeout:5];
    if (![self waitForPaletteFilesPresentation:app]) return;
    // Observed system navigation owners differ between the wide sidebar and
    // phone picker. Scope positively to those owners, not a global exclusion.
    XCUIElementQuery *pickerBars=[app.navigationBars matchingPredicate:[NSPredicate predicateWithFormat:@"identifier IN %@",@[@"FullDocumentManagerViewControllerNavigationBar",@"DOCSidebarView"]]];
    XCUIElement *cancel=pickerBars.buttons[@"Cancel"].firstMatch;
    // The retained large-phone gate needed4.044s readiness plus about2s for
    // the real system tap. Keep existence at5; report the former5s total separately.
    [self tapReadyPaletteElement:cancel timeout:10 existenceTimeout:5];
    if (self.tcPaletteReadinessExpired) return;
    [self waitForPalettePresentationToClose:cancel];
    XCUIElement *close=app.buttons[@"palette.import.close"];
    XCTAssertTrue(close.hittable);XCTAssertTrue([[self paletteElement:@"palette.import.status" app:app].staticTexts.firstMatch.label containsString:@"cancelled"]);
    [self tapReadyPaletteElement:close timeout:5];[self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
    [self verifyOriginalPaletteSources:app];
    UIPasteboard.generalPasteboard.string=@"[\"#112233\"]";
    [self openPaletteAction:@"palette.import.open" app:app];
    [self verifyInitialPaletteImportControls:app];
    if (self.tcPaletteReadinessExpired) return;
    XCUIElement *status=[self paletteElement:@"palette.import.status" app:app];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]);XCTAssertGreaterThan(status.staticTexts.firstMatch.label.length,0u);
    XCTAssertTrue([status.staticTexts.firstMatch.label containsString:@"review every color"]);
    close=app.buttons[@"palette.import.close"];XCTAssertTrue(close.hittable);[self tapReadyPaletteElement:close timeout:5];
    [self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
}
- (BOOL)waitForPaletteFilesPresentation:(XCUIApplication *)app {
    // Cold remote attachment took 11.9–15.8s on iPads at 510fd5a and 21.853s
    // on the compact phone at 80cef6ad. This is a harness allowance, not a product
    // startup SLO. Keep iPad 20s and use a bounded 25s phone presentation gate;
    // attached controls still require 5s readiness. Never reopen or retry a flow.
    NSTimeInterval budget=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPhone ? 25 : 20;
    XCUIElement *picker=[app.navigationBars matchingPredicate:[NSPredicate predicateWithFormat:@"identifier IN %@",@[@"FullDocumentManagerViewControllerNavigationBar",@"DOCSidebarView"]]].firstMatch;
    NSTimeInterval start=NSProcessInfo.processInfo.systemUptime;
    BOOL appeared=[picker waitForExistenceWithTimeout:budget];
    NSTimeInterval elapsed=NSProcessInfo.processInfo.systemUptime-start;
    NSLog(@"PALETTE_FILES_PRESENTATION appeared=%d elapsed=%.3f budget=%.0f",appeared,elapsed,budget);
    XCTAssertTrue(appeared,@"The real system Files presentation must attach");
    XCTAssertLessThanOrEqual(elapsed,budget,@"Files remote attachment must stay within its presentation budget");
    return appeared && elapsed<=budget;
}
- (void)selectSyntheticPaletteFile:(XCUIApplication *)app {
    [self openPaletteAction:@"palette.import.open" app:app];
    XCUIElement *source=[self paletteElement:@"palette.import.file" app:app];
    [self tapReadyPaletteElement:source timeout:5];
    if (![self waitForPaletteFilesPresentation:app]) return;
    XCUIElement *file=[app.staticTexts matchingPredicate:[NSPredicate predicateWithFormat:@"label BEGINSWITH 'TouchColor-Ordered-Colors'"]].firstMatch;
    if (!file.exists) {
        NSString *location=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad ? @"On My iPad" : @"On My iPhone";
        NSPredicate *localType=[NSPredicate predicateWithFormat:@"elementType == %lu AND (identifier == %@ OR label == %@)",(unsigned long)XCUIElementTypeCell,[@"DOC.sidebar.item." stringByAppendingString:location],location];
        NSString *providerIdentifier=[@"DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " stringByAppendingString:location];
        NSPredicate *providerType=[NSPredicate predicateWithFormat:@"elementType == %lu AND identifier == %@",(unsigned long)XCUIElementTypeOther,providerIdentifier];
        NSPredicate *browseType=[NSPredicate predicateWithFormat:@"elementType == %lu AND label == 'Browse'",(unsigned long)XCUIElementTypeButton];
        NSPredicate *fileType=[NSPredicate predicateWithFormat:@"elementType == %lu AND label BEGINSWITH 'TouchColor-Ordered-Colors'",(unsigned long)XCUIElementTypeStaticText];
        XCUIElement *provider=app.otherElements[providerIdentifier];
        BOOL needsFolder=YES;
        NSTimeInterval folderStarted=0, folderDeadline=0;
        if (!provider.exists) {
            // Only real location cells and Browse are navigation actions. The
            // On My iPhone/iPad navigation title must never enter this query.
            XCUIElement *route=[[app descendantsMatchingType:XCUIElementTypeAny] matchingPredicate:[NSCompoundPredicate orPredicateWithSubpredicates:@[localType,browseType,fileType]]].firstMatch;
            if (![self waitForReadyPaletteElement:route timeout:5]) return;
            NSError *routeSnapshotError=nil;
            id<XCUIElementSnapshot> routeSnapshot=[route snapshotWithError:&routeSnapshotError];
            XCTAssertNotNil(routeSnapshot,@"Files route snapshot must be available: %@",routeSnapshotError);
            XCTAssertNil(routeSnapshotError);
            if (!routeSnapshot || routeSnapshotError) return;
            TCFilesRoute kind=TCFilesRouteForSnapshot(routeSnapshot,location);
            XCTAssertTrue(kind==TCFilesRouteBrowse || kind==TCFilesRouteLocationCell || kind==TCFilesRouteFixtureFile,@"Only a classified Files action may be tapped");
            if (kind!=TCFilesRouteBrowse && kind!=TCFilesRouteLocationCell && kind!=TCFilesRouteFixtureFile) return;
            NSLog(@"FILE_PICKER_ROUTE kind=%d label=%@ identifier=%@ frame=%@",kind,routeSnapshot.label,routeSnapshot.identifier,NSStringFromCGRect(routeSnapshot.frame));
            if (kind==TCFilesRouteFixtureFile) needsFolder=NO;
            else {
                [route tap];
                if (kind==TCFilesRouteBrowse) {
                    // Browse can restore an already-open local provider. Use
                    // one15s functional clock to resolve that state and its
                    // folder; keep the former10s latency visible, never tap a title.
                    folderStarted=NSProcessInfo.processInfo.systemUptime;
                    folderDeadline=folderStarted+15;
                    XCUIElement *state=[[app descendantsMatchingType:XCUIElementTypeAny] matchingPredicate:[NSCompoundPredicate orPredicateWithSubpredicates:@[providerType,localType]]].firstMatch;
                    BOOL appeared=[state waitForExistenceWithTimeout:MAX(0,folderDeadline-NSProcessInfo.processInfo.systemUptime)];
                    BOOL providerTimely=NSProcessInfo.processInfo.systemUptime<folderDeadline;
                    if (!providerTimely) self.tcPaletteReadinessExpired=YES;
                    XCTAssertTrue(providerTimely,@"The provider lookup must return within the original functional deadline");
                    if (!providerTimely) return;
                    XCTAssertTrue(appeared,@"Browse must expose the local provider or a location cell");
                    if (!appeared) return;
                    // One immutable snapshot avoids six separate remote
                    // resolutions observed to consume the last2.3s of this
                    // deadline. It classifies state, never action readiness.
                    NSError *destinationSnapshotError=nil;
                    id<XCUIElementSnapshot> destinationSnapshot=[state snapshotWithError:&destinationSnapshotError];
                    BOOL snapshotTimely=NSProcessInfo.processInfo.systemUptime<folderDeadline;
                    if (!snapshotTimely) self.tcPaletteReadinessExpired=YES;
                    XCTAssertTrue(snapshotTimely,@"The provider snapshot must return within the same functional deadline");
                    if (!snapshotTimely) return;
                    XCTAssertNotNil(destinationSnapshot,@"Files destination snapshot must be available: %@",destinationSnapshotError);
                    XCTAssertNil(destinationSnapshotError);
                    if (!destinationSnapshot || destinationSnapshotError) return;
                    TCFilesRoute destination=TCFilesRouteForSnapshot(destinationSnapshot,location);
                    XCTAssertTrue(destination==TCFilesRouteLocalProvider || destination==TCFilesRouteLocationCell,@"A Files title is not a location action");
                    if (destination!=TCFilesRouteLocalProvider && destination!=TCFilesRouteLocationCell) return;
                    NSLog(@"FILE_PICKER_DESTINATION kind=%d folderBudgetRemaining=%.3f",destination,folderDeadline-NSProcessInfo.processInfo.systemUptime);
                    if (destination==TCFilesRouteLocationCell) {
                        NSTimeInterval readiness=MIN(5,MAX(0,folderDeadline-NSProcessInfo.processInfo.systemUptime));
                        XCTAssertGreaterThan(readiness,0,@"A location action must fit inside the remaining folder budget");
                        if (readiness<=0 || ![self waitForReadyPaletteElement:state timeout:readiness]) return;
                        BOOL locationTimely=NSProcessInfo.processInfo.systemUptime<folderDeadline;
                        if (!locationTimely) self.tcPaletteReadinessExpired=YES;
                        XCTAssertTrue(locationTimely,@"A location tap must start before the shared folder deadline");
                        if (!locationTimely) return;
                        [state tap];
                        locationTimely=NSProcessInfo.processInfo.systemUptime<folderDeadline;
                        if (!locationTimely) self.tcPaletteReadinessExpired=YES;
                        XCTAssertTrue(locationTimely,@"A location tap must return before any folder lookup");
                        if (!locationTimely) return;
                    }
                }
            }
        }
        if (needsFolder) {
            XCUIElement *folder=app.staticTexts[@"Palette Fixtures"].firstMatch;
            // An already-open provider retains its10s folder allowance. Browse
            // and folder share the one15s deadline established before resolution.
            if (!folderDeadline) { folderStarted=NSProcessInfo.processInfo.systemUptime;folderDeadline=folderStarted+10; }
            NSTimeInterval remaining=MAX(0,folderDeadline-NSProcessInfo.processInfo.systemUptime);
            if (remaining<=0) self.tcPaletteReadinessExpired=YES;
            XCTAssertGreaterThan(remaining,0,@"Browse resolution must leave time for the fixture folder");
            if (remaining<=0) return;
            BOOL found=[folder waitForExistenceWithTimeout:remaining];
            NSTimeInterval folderReturned=NSProcessInfo.processInfo.systemUptime;
            NSLog(@"FILE_PROVIDER_FOLDER found=%d elapsed=%.3f budget=%.0f responsiveness10=%@",
                  found,folderReturned-folderStarted,folderDeadline-folderStarted,
                  folderReturned<folderStarted+10 ? @"within" : @"missed");
            BOOL withinBudget=folderReturned<folderDeadline && NSProcessInfo.processInfo.systemUptime<folderDeadline;
            if (!withinBudget) self.tcPaletteReadinessExpired=YES;
            XCTAssertTrue(withinBudget,@"Provider and folder must complete within their one functional deadline");
            if (!withinBudget) return;
            XCTAssertTrue(found,@"The actual fixture folder must exist before its single tap");
            if (!found) return;
            [folder tap];
        }
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
    if (self.tcPaletteReadinessExpired) return;
    XCUIElement *close=app.buttons[@"palette.import.close"];[self tapReadyPaletteElement:close timeout:5];[self waitForPalettePresentationToClose:close];
    [self verifyHistory:@[@"#112233"] app:app];
    [self selectSyntheticPaletteFile:app];
    if (self.tcPaletteReadinessExpired) return;
    [self acceptPalette:app];
    NSArray *expected=@[@"#112233",@"#445566",@"#445566",@"#aabbcc"];
    [self verifyHistory:expected app:app];
    [app terminate];app.launchArguments=@[@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];[app launch];
    [self verifyHistory:expected app:app];
}
- (void)exerciseLargestTextPaletteRotationReplacesSelection:(XCUIApplication *)app {
    [app terminate];
    app.launchArguments=@[@"--ui-test-reset",@"--ui-test-dark",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    // This independent rotation scenario enters through portrait. The separate
    // largest-text review/inbox case retains landscape source-control reveal.
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;[app launch];
    [self pastePalette:@"[\"#112233\",\"#aabbcc\"]" app:app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:app];
    // Keep this same populated dialog through both orientations; no app relaunch
    // or state transfer from another testcase can establish the rotation proof.
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:app];
    // Preserve the original landscape-to-portrait replacement and exact values.
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationPortrait;
    UIPasteboard.generalPasteboard.string=@"[\"#112233\",\"#aabbcc\",\"#445566\"]";
    [self activateVisiblePalettePaste:app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc",@"#445566"] app:app];
    XCUIElement *close=app.buttons[@"palette.import.close"];
    XCTAssertTrue(close.hittable);[self tapReadyPaletteElement:close timeout:5];[self waitForPalettePresentationToClose:close];
    [self verifyHistory:@[] app:app];
}
- (void)exerciseLargestTextPaletteReviewAndImportHelp:(XCUIApplication *)app {
    [app terminate];
    app.launchArguments=@[@"--ui-test-reset",@"--ui-test-dark",@"--ui-test-scroll-state",@"-AppleLanguages",@"(en)",@"-UIPreferredContentSizeCategoryName",@"UICTContentSizeCategoryAccessibilityXXXL"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;[app launch];
    [self pastePalette:@"[\"#112233\",\"#aabbcc\"]" app:app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:app];
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
    [self tapReadyPaletteElement:close timeout:5];[self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
    [self verifyOriginalPaletteSources:app];
    [self openPaletteAction:@"palette.import.open" app:app];
    [self verifyInitialPaletteImportControls:app];
    if (self.tcPaletteReadinessExpired) return;
    XCUIElement *status=[self paletteElement:@"palette.import.status" app:app];
    table=app.tables[@"palette.import.review"];
    for (NSUInteger attempt=0;attempt<5 && !status.exists;attempt++) [table swipeUp];
    XCTAssertTrue([status waitForExistenceWithTimeout:5]);
    XCUIElement *label=status.staticTexts.firstMatch;
    XCTAssertTrue(label.exists);XCTAssertGreaterThan(label.label.length,0u);
    // Long explanations may exceed this short viewport; their beginning and end
    // must both be scroll-reachable without shrinking the user's text size.
    for (NSUInteger attempt=0;attempt<5 && CGRectGetMinY(label.frame)<CGRectGetMinY([self paletteBodyViewport:app table:table title:@"Import Palette"])-1;attempt++) [table swipeDown];
    XCTAssertGreaterThanOrEqual(CGRectGetMinY(label.frame),CGRectGetMinY([self paletteBodyViewport:app table:table title:@"Import Palette"])-1);
    for (NSUInteger attempt=0;attempt<5 && CGRectGetMaxY(label.frame)>CGRectGetMaxY([self paletteBodyViewport:app table:table title:@"Import Palette"])+1;attempt++) [table swipeUp];
    XCTAssertLessThanOrEqual(CGRectGetMaxY(label.frame),CGRectGetMaxY([self paletteBodyViewport:app table:table title:@"Import Palette"])+1);
    close=app.buttons[@"palette.import.close"];XCTAssertTrue(close.hittable);[self tapReadyPaletteElement:close timeout:5];
    [self waitForPalettePresentationToClose:close];[self verifyHistory:@[] app:app];
}
@end
