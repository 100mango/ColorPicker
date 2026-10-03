#import "TCColorUtilities.h"
#import <math.h>

NSString *TCHexColor(uint8_t r, uint8_t g, uint8_t b) {
    return [NSString stringWithFormat:@"#%02x%02x%02x", r, g, b];
}
NSString *TCNormalizeHexColor(id value) {
    if (![value isKindOfClass:NSString.class] || [value length] != 7 || ![value hasPrefix:@"#"]) return nil;
    NSString *digits = [value substringFromIndex:1];
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdefABCDEF"] invertedSet];
    return [digits rangeOfCharacterFromSet:invalid].location == NSNotFound ? [value lowercaseString] : nil;
}
static unsigned TCColorNumber(NSString *value) {
    unsigned result = 0;
    [[NSScanner scannerWithString:[value substringFromIndex:1]] scanHexInt:&result];
    return result;
}
UIColor *TCUIColorFromHex(id value) {
    NSString *hex = TCNormalizeHexColor(value);
    if (!hex) return nil;
    unsigned rgb = TCColorNumber(hex);
    return [UIColor colorWithRed:((rgb >> 16) & 255)/255.0 green:((rgb >> 8) & 255)/255.0 blue:(rgb & 255)/255.0 alpha:1];
}
NSString *TCRGBDescription(NSString *hex) {
    if (!TCNormalizeHexColor(hex)) return @"";
    unsigned rgb = TCColorNumber(hex);
    return [NSString stringWithFormat:@"R %u   G %u   B %u", (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255];
}
BOOL TCNormalizedPoint(CGPoint point, CGRect rect, CGPoint *normalized) {
    if (!isfinite(point.x) || !isfinite(point.y) || rect.size.width <= 0 || rect.size.height <= 0 || !CGRectContainsPoint(rect, point)) return NO;
    if (normalized) *normalized = CGPointMake((point.x - rect.origin.x)/rect.size.width, (point.y - rect.origin.y)/rect.size.height);
    return YES;
}
NSString *TCSampleImage(UIImage *image, CGPoint p) {
    if (!image || image.size.width <= 0 || image.size.height <= 0 || !isfinite(p.x) || !isfinite(p.y) || p.x < 0 || p.y < 0 || p.x > 1 || p.y > 1) return nil;
    CGSize pixels = CGSizeMake(image.size.width * image.scale, image.size.height * image.scale);
    CGFloat x = MIN(floor(p.x * pixels.width), pixels.width - 1);
    CGFloat y = MIN(floor(p.y * pixels.height), pixels.height - 1);
    uint8_t pixel[4] = {255, 255, 255, 255};
    CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = CGBitmapContextCreate(pixel, 1, 1, 8, 4, space, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(space);
    if (!context) return nil;
    CGContextSetRGBFillColor(context, 1, 1, 1, 1);
    CGContextFillRect(context, CGRectMake(0, 0, 1, 1));
    CGContextTranslateCTM(context, 0, 1);
    CGContextScaleCTM(context, 1, -1);
    CGContextSetInterpolationQuality(context, kCGInterpolationNone);
    UIGraphicsPushContext(context);
    [image drawInRect:CGRectMake(-x, -y, pixels.width, pixels.height)];
    UIGraphicsPopContext();
    CGContextRelease(context);
    return TCHexColor(pixel[0], pixel[1], pixel[2]);
}
NSString *TCSampleCameraBuffer(CVPixelBufferRef buffer) {
    if (!buffer || CVPixelBufferGetPixelFormatType(buffer) != kCVPixelFormatType_32BGRA || CVPixelBufferLockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) return nil;
    size_t width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer), stride = CVPixelBufferGetBytesPerRow(buffer);
    uint8_t *bytes = CVPixelBufferGetBaseAddress(buffer);
    NSString *hex = nil;
    if (bytes && width && height && width <= SIZE_MAX / 4 && stride >= width * 4) {
        uint8_t *pixel = bytes + (height / 2) * stride + (width / 2) * 4;
        hex = TCHexColor(pixel[2], pixel[1], pixel[0]);
    }
    CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
    return hex;
}
TCCameraAccess TCCameraAccessForStatus(AVAuthorizationStatus status, BOOL available) {
    if (!available) return TCCameraAccessUnavailable;
    switch (status) {
        case AVAuthorizationStatusAuthorized: return TCCameraAccessReady;
        case AVAuthorizationStatusNotDetermined: return TCCameraAccessAsk;
        default: return TCCameraAccessBlocked;
    }
}

@interface TCColorStore ()
@property (nonatomic, strong) NSUserDefaults *defaults;
@end
@implementation TCColorStore
- (instancetype)initWithDefaults:(NSUserDefaults *)defaults {
    if ((self = [super init])) _defaults = defaults;
    return self;
}
- (NSArray<NSString *> *)colors {
    id raw = [self.defaults objectForKey:@"colorArray"];
    NSMutableArray *colors = [NSMutableArray array];
    if ([raw isKindOfClass:NSArray.class]) {
        for (id candidate in raw) {
            NSString *hex = TCNormalizeHexColor(candidate);
            if (hex) [colors addObject:hex];
        }
    }
    return [colors copy];
}
- (void)writeColors:(NSArray *)colors {
    // Preserve the untouched original if recovery had to skip malformed entries.
    id original = [self.defaults objectForKey:@"colorArray"];
    if (original && ![original isEqual:self.colors] && ![self.defaults objectForKey:@"colorArrayRecoveryBackup"]) {
        [self.defaults setObject:original forKey:@"colorArrayRecoveryBackup"];
    }
    [self.defaults setObject:colors forKey:@"colorArray"];
}
- (BOOL)addColor:(id)value {
    NSString *hex = TCNormalizeHexColor(value);
    if (!hex) return NO;
    @synchronized (self.defaults) {
        NSMutableArray *colors = [self.colors mutableCopy];
        [colors addObject:hex];
        [self writeColors:colors];
    }
    return YES;
}
- (BOOL)removeColorAtIndex:(NSUInteger)index {
    @synchronized (self.defaults) {
        NSMutableArray *colors = [self.colors mutableCopy];
        if (index >= colors.count) return NO;
        [colors removeObjectAtIndex:index];
        [self writeColors:colors];
    }
    return YES;
}
@end
