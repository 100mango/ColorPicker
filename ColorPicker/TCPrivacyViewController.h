#import <UIKit/UIKit.h>

/// Only the approved static document (and its in-page fragments) may load.
FOUNDATION_EXPORT BOOL TCPrivacyAllowsDocumentURL(NSURL *URL);
FOUNDATION_EXPORT BOOL TCPrivacyAllowsResponse(NSURLResponse *response);
/// Contact links may open Mail only after an explicit user tap.
FOUNDATION_EXPORT BOOL TCPrivacyAllowsContactURL(NSURL *URL, BOOL userActivated);

@interface TCPrivacyViewController : UIViewController
@property (nonatomic, copy) void (^dismissalHandler)(void);
@end
