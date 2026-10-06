#import <UIKit/UIKit.h>

/// Only the in-memory bundled document (and its in-page fragments) may load.
FOUNDATION_EXPORT BOOL TCPrivacyAllowsDocumentURL(NSURL *URL);
FOUNDATION_EXPORT BOOL TCPrivacyAllowsResponse(NSURLResponse *response);
/// The exact published document may open externally only after an explicit user tap.
FOUNDATION_EXPORT BOOL TCPrivacyAllowsPublishedURL(NSURL *URL, BOOL userActivated);
/// Reject missing, malformed or modified bundle bytes before WebKit sees them.
FOUNDATION_EXPORT NSString *TCPrivacyPolicyHTML(NSData *data);
/// Contact links may open Mail only after an explicit user tap.
FOUNDATION_EXPORT BOOL TCPrivacyAllowsContactURL(NSURL *URL, BOOL userActivated);

@interface TCPrivacyViewController : UIViewController
@property (nonatomic, copy) void (^dismissalHandler)(void);
@end
