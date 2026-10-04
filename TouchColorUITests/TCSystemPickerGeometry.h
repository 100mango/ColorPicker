#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <math.h>

// Test-only geometry shared by the real picker gesture and hosted regressions.
static inline BOOL TCPickerRectIsUsable(CGRect rect) {
    return !CGRectIsNull(rect) && !CGRectIsEmpty(rect) &&
        isfinite(rect.origin.x) && isfinite(rect.origin.y) &&
        isfinite(rect.size.width) && isfinite(rect.size.height) && rect.size.width>0 && rect.size.height>0;
}

static inline BOOL TCPickerDismissalPoint(CGRect window, CGRect presentation, CGPoint *point) {
    if (!TCPickerRectIsUsable(window) || !TCPickerRectIsUsable(presentation) || !point) return NO;
    CGRect usable=CGRectInset(window,20,20);
    CGRect excluded=CGRectInset(presentation,-12,-12);
    if (!TCPickerRectIsUsable(usable) || !CGRectIntersectsRect(window,presentation)) return NO;
    // Prefer the source/sidebar side and the middle of a real free region, not
    // a far screen edge next to Photos' asynchronously expanding remote view.
    CGRect regions[]={
        CGRectMake(CGRectGetMinX(usable),CGRectGetMinY(usable),MAX(0,CGRectGetMinX(excluded)-CGRectGetMinX(usable)),CGRectGetHeight(usable)),
        CGRectMake(CGRectGetMaxX(excluded),CGRectGetMinY(usable),MAX(0,CGRectGetMaxX(usable)-CGRectGetMaxX(excluded)),CGRectGetHeight(usable)),
        CGRectMake(CGRectGetMinX(usable),CGRectGetMaxY(excluded),CGRectGetWidth(usable),MAX(0,CGRectGetMaxY(usable)-CGRectGetMaxY(excluded))),
        CGRectMake(CGRectGetMinX(usable),CGRectGetMinY(usable),CGRectGetWidth(usable),MAX(0,CGRectGetMinY(excluded)-CGRectGetMinY(usable)))
    };
    for (NSUInteger index=0;index<sizeof(regions)/sizeof(regions[0]);index++) {
        CGRect region=CGRectIntersection(regions[index],usable);
        if (TCPickerRectIsUsable(region) && region.size.width>=44 && region.size.height>=44) {
            *point=CGPointMake(CGRectGetMidX(region),CGRectGetMidY(region));
            return !CGRectContainsPoint(excluded,*point);
        }
    }
    return NO; // An adapted/full-window presentation must use its real Cancel.
}
