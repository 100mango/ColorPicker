#import <UIKit/UIKit.h>
#if !DEBUG
#error PaletteFixtures is a simulator-only test host and must never be built for release.
#endif

@interface PaletteFixtureDelegate : UIResponder <UIApplicationDelegate, UIWindowSceneDelegate>
@property (nonatomic, strong) UIWindow *window;
@end
@implementation PaletteFixtureDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    NSURL *documents=[NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSData *data=[NSJSONSerialization dataWithJSONObject:@[@"#445566",@"#445566",@"#AABBCC"] options:0 error:nil];
    NSError *error=nil;
    BOOL written=[data writeToURL:[documents URLByAppendingPathComponent:@"TouchColor-Ordered-Colors.json"] options:NSDataWritingAtomic error:&error];
    NSAssert(written,@"Synthetic JSON fixture failed: %@",error);
    return YES;
}
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    self.window=[[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    UIViewController *controller=[UIViewController new];controller.view.backgroundColor=UIColor.systemBackgroundColor;
    UILabel *label=[UILabel new];label.translatesAutoresizingMaskIntoConstraints=NO;
    label.text=@"Synthetic palette fixture ready";label.accessibilityIdentifier=@"fixture.ready";
    label.numberOfLines=0;label.font=[UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    [controller.view addSubview:label];
    [NSLayoutConstraint activateConstraints:@[[label.leadingAnchor constraintEqualToAnchor:controller.view.safeAreaLayoutGuide.leadingAnchor constant:20],[label.trailingAnchor constraintEqualToAnchor:controller.view.safeAreaLayoutGuide.trailingAnchor constant:-20],[label.centerYAnchor constraintEqualToAnchor:controller.view.safeAreaLayoutGuide.centerYAnchor]]];
    self.window.rootViewController=controller;[self.window makeKeyAndVisible];
}
@end
int main(int argc,char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(PaletteFixtureDelegate.class)); }
}
