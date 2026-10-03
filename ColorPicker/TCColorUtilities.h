#import <UIKit/UIKit.h>
#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN
/// sRGB values, in the original application's lowercase #rrggbb format.
FOUNDATION_EXPORT NSString *TCHexColor(uint8_t red, uint8_t green, uint8_t blue);
FOUNDATION_EXPORT NSString * _Nullable TCNormalizeHexColor(id _Nullable value);
FOUNDATION_EXPORT UIColor * _Nullable TCUIColorFromHex(id _Nullable value);
FOUNDATION_EXPORT NSString *TCRGBDescription(NSString *hex);
/// UIKit applies all eight UIImage orientations. Transparent pixels are composited on white.
FOUNDATION_EXPORT NSString * _Nullable TCSampleImage(UIImage * _Nullable image, CGPoint normalizedPoint);
FOUNDATION_EXPORT BOOL TCNormalizedPoint(CGPoint point, CGRect imageRect, CGPoint * _Nullable normalized);
typedef NS_ENUM(NSInteger, TCCameraAccess) { TCCameraAccessUnavailable, TCCameraAccessAsk, TCCameraAccessReady, TCCameraAccessBlocked };
FOUNDATION_EXPORT TCCameraAccess TCCameraAccessForStatus(AVAuthorizationStatus status, BOOL available);

@interface TCColorStore : NSObject
- (instancetype)initWithDefaults:(NSUserDefaults *)defaults;
@property (nonatomic, readonly) NSArray<NSString *> *colors;
- (BOOL)addColor:(id _Nullable)color;
- (BOOL)removeColorAtIndex:(NSUInteger)index;
@end
NS_ASSUME_NONNULL_END
