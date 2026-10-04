#import "ColorAppDelegate.h"
#import "TouchColor-Swift.h"
@implementation ColorAppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {
    [[TCWatchPaletteInbox sharedInbox] activate];
    return YES;
}
@end
