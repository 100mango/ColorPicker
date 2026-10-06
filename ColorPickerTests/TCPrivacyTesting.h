#import <UIKit/UIKit.h>
#import "TCPrivacyViewController.h"

@interface TCPrivacyViewController (HostedPolicyTests)
- (void)openExternalURL:(NSURL *)URL completion:(void (^)(BOOL))completion;
- (void)contactDeveloper;
- (void)openPolicyInBrowser;
- (void)close;
@end
