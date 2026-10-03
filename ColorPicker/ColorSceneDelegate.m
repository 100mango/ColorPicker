#import "ColorSceneDelegate.h"
#import "ColorMainViewController.h"
@implementation ColorSceneDelegate
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)connectionOptions {
    if (![scene isKindOfClass:UIWindowScene.class]) return;
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.window.rootViewController = [[UINavigationController alloc] initWithRootViewController:[ColorMainViewController new]];
#if DEBUG
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--ui-test-dark"]) self.window.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
#endif
    [self.window makeKeyAndVisible];
}
@end
