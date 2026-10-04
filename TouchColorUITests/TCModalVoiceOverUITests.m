#import <XCTest/XCTest.h>
#import <UIKit/UIKit.h>
#include <stdio.h>
#include <stdlib.h>
#import "TCPaletteUIHelpers.h"

__attribute__((noreturn)) static void TCAbortUnexpectedVoiceOverInterruption(void) {
    fputs("TOUCHCOLOR_VOICEOVER_UNEXPECTED_INTERRUPTION_ABORT\n", stderr);
    fflush(stderr);
    abort();
}

/// Isolated SDK 27 diagnostics. Official audit cases run separately with VoiceOver off.
@interface TCModalVoiceOverUITests : XCTestCase
@property (nonatomic, strong) XCUIApplication *app;
@property (nonatomic, strong) id unexpectedInterruptionMonitor;
@end
@implementation TCModalVoiceOverUITests
- (void)setUp {
    [super setUp]; self.continueAfterFailure=NO;
#if __IPHONE_OS_VERSION_MAX_ALLOWED < 270000
    XCTSkipIf(YES,@"VoiceOver navigation diagnostics require the Xcode 27 SDK");
#endif
    if (@available(iOS 27.0,*)) {} else { XCTSkipIf(YES,@"VoiceOver navigation diagnostics require iOS 27"); }
    self.unexpectedInterruptionMonitor=[self addUIInterruptionMonitorWithDescription:@"Reject every unexpected VoiceOver-probe interruption" handler:^BOOL(XCUIElement *alert) {
        TCAbortUnexpectedVoiceOverInterruption(); // Never return to XCTest fallback handlers.
    }];
    self.app=[XCUIApplication new];
    self.app.launchArguments=@[@"--ui-test-reset",@"-AppleLanguages",@"(en)",@"-AppleLocale",@"en_US"];
    XCUIDevice.sharedDevice.orientation=UIDeviceOrientationLandscapeLeft;
    [self.app launch];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:10]);
}
- (NSString *)normalizedSpeech:(NSString *)text {
    NSArray *parts=[text componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    return [[parts filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"length > 0"]] componentsJoinedByString:@" "];
}
- (void)verifyModalVoiceOver:(NSString *)screen required:(NSArray<NSString *> *)required {
#if __IPHONE_OS_VERSION_MAX_ALLOWED >= 270000
    if (@available(iOS 27.0,*)) {
        XCUIVoiceOverService *service=XCUIDevice.sharedDevice.voiceOverService;
        NSError *error=nil;
        XCTAssertTrue([service enableAndReturnError:&error],@"VoiceOver startup: %@",error);
        XCTAssertTrue(service.enabled);
        NSLog(@"VOICEOVER_BEGIN screen=%@ window=%@ service=%@",screen,NSStringFromCGRect(self.app.windows.firstMatch.frame),service.debugDescription);
        NSMutableArray<NSString *> *speech=[NSMutableArray new];
        BOOL wrapped=NO;
        NSTimeInterval deadline=NSProcessInfo.processInfo.systemUptime+75;
        for (NSUInteger index=0;index<24 && NSProcessInfo.processInfo.systemUptime<deadline;index++) {
            error=nil;
            XCUIVoiceOverOutput *output=index==0 ? [service currentSpeechAndReturnError:&error] : [service moveForwardAndReturnError:&error];
            NSLog(@"VOICEOVER_STEP screen=%@ index=%lu utterance=%@ error=%@",screen,(unsigned long)index,output.utterance,error);
            XCTAssertNotNil(output,@"VoiceOver navigation must return real speech: %@",error);
            XCTAssertGreaterThan(output.utterance.length,0u);
            NSString *utterance=output.utterance;
            for (NSString *background in @[@"Choose Photo",@"Take Photo",@"Live Color",@"Color Sources",@"Your saved colors appear here",@"Choose a photo or use the camera"]) {
                XCTAssertEqual([utterance rangeOfString:background options:NSCaseInsensitiveSearch].location,NSNotFound,@"Modal VoiceOver focus escaped to background content: %@",utterance);
            }
            if (index>2 && [utterance isEqualToString:speech.firstObject]) { wrapped=YES; break; }
            [speech addObject:utterance];
        }
        NSString *transcript=[speech componentsJoinedByString:@"\n"];
        NSLog(@"VOICEOVER_END screen=%@ wrapped=%d count=%lu transcript=%@",screen,wrapped,(unsigned long)speech.count,transcript);
        for (NSString *text in required) XCTAssertNotEqual([[self normalizedSpeech:transcript] rangeOfString:[self normalizedSpeech:text] options:NSCaseInsensitiveSearch].location,NSNotFound,@"Required modal information was not reached by VoiceOver: %@",text);
        XCTAssertTrue(wrapped,@"The bounded traversal must complete a modal focus cycle");
        error=nil;XCTAssertTrue([service disableAndReturnError:&error],@"VoiceOver shutdown: %@",error);
        XCTAssertFalse(service.enabled);
    }
#endif
}
- (void)testImportReviewVoiceOverStaysInThePresentedSheet {
    [self pastePalette:@"[\"#112233\",\"#aabbcc\"]" app:self.app];
    [self verifyPaletteRows:@[@"#112233",@"#aabbcc"] app:self.app];
    [self verifyModalVoiceOver:@"import review" required:@[@"Import Palette",@"Add Colors",@"Choose JSON File",@"Paste",@"Adding this selection appends every color in order",@"Existing colors and duplicates are kept",@"#112233",@"R 17 G 34 B 51",@"#aabbcc",@"R 170 G 187 B 204"]];
    XCUIElement *close=self.app.buttons[@"palette.import.close"];[close tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
}
- (void)testWatchInboxVoiceOverStaysInThePresentedSheet {
    [self openPaletteAction:@"watch.inbox.open" app:self.app];
    XCTAssertTrue([self.app.cells[@"watch.inbox.status"] waitForExistenceWithTimeout:5]);
    [self verifyModalVoiceOver:@"watch inbox" required:@[@"Watch Inbox",@"Done",@"Watch transfer is unavailable on this device",@"You can import a palette using Files or Paste"]];
    XCUIElement *close=self.app.buttons[@"watch.inbox.close"];[close tap];
    XCTAssertTrue([self.app.buttons[@"choosePhoto"] waitForExistenceWithTimeout:5]);
}
- (void)tearDown {
    NSError *shutdownError=nil;
    BOOL shutdownSucceeded=YES;
    @try {
#if __IPHONE_OS_VERSION_MAX_ALLOWED >= 270000
        if (@available(iOS 27.0,*)) {
            XCUIVoiceOverService *service=XCUIDevice.sharedDevice.voiceOverService;
            if (service.enabled) shutdownSucceeded=[service disableAndReturnError:&shutdownError] && !service.enabled;
        }
#endif
        [self.app terminate];
    } @finally {
        if (self.unexpectedInterruptionMonitor) { [self removeUIInterruptionMonitor:self.unexpectedInterruptionMonitor];self.unexpectedInterruptionMonitor=nil; }
        [super tearDown];
    }
    XCTAssertTrue(shutdownSucceeded,@"Always restore VoiceOver after diagnostic: %@",shutdownError);
}
@end
