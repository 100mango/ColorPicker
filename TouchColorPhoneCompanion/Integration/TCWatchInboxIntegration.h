#import "ColorMainViewController.h"

// The original iOS header stays unchanged. Only the Watch-package projection
// restores this existing action to its shipping implementation and workspace.
@interface ColorMainViewController (TCWatchInboxIntegration)
- (void)openWatchInbox;
@end
