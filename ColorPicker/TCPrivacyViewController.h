#import <UIKit/UIKit.h>

/// Native, read-only bilingual privacy information. External services require a real action.
@interface TCPrivacyViewController : UIViewController
@property (nonatomic, copy) void (^dismissalHandler)(void);
@end
