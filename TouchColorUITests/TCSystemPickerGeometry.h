#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <math.h>
#include <string.h>

typedef enum { TCPickerNodeOther, TCPickerNodePopover, TCPickerNodeNavigationBar, TCPickerNodeScrollView } TCPickerNodeKind;
typedef struct { CGRect bounds; NSUInteger nodes; NSUInteger chromeMatches; BOOL rootUsable; } TCPickerSnapshotObservation;

static inline BOOL TCPickerNameMatches(const char *identifier, const char *label, const char *name) {
    return (identifier && strcmp(identifier,name)==0) || (label && strcmp(label,name)==0);
}

static inline BOOL TCPhotosSnapshotNodeIsChrome(TCPickerNodeKind kind, const char *identifier, const char *label) {
    // XCTest matchingIdentifier and keyed queries accept either identifier or
    // label. Snapshot inspection must preserve those same public semantics.
    return (kind==TCPickerNodeNavigationBar && TCPickerNameMatches(identifier,label,"Photos")) ||
        (kind==TCPickerNodeScrollView && TCPickerNameMatches(identifier,label,"photosView_content_scroll_view"));
}

// Test-only geometry shared by the real picker gesture and hosted regressions.
static inline BOOL TCPickerRectIsUsable(CGRect rect) {
    return !CGRectIsNull(rect) && !CGRectIsEmpty(rect) &&
        isfinite(rect.origin.x) && isfinite(rect.origin.y) &&
        isfinite(rect.size.width) && isfinite(rect.size.height) && rect.size.width>0 && rect.size.height>0;
}

static inline void TCObservePhotosSnapshotNode(TCPickerSnapshotObservation *observation, TCPickerNodeKind kind,
                                               const char *identifier, const char *label, CGRect frame,
                                               BOOL isQueriedPopoverRoot) {
    if (isQueriedPopoverRoot) {
        observation->rootUsable=TCPickerRectIsUsable(frame);
        observation->bounds=CGRectNull;
        observation->nodes=0;observation->chromeMatches=0;
    }
    observation->nodes++;
    // No child can substitute its own frame for an invalid/missing root.
    if (!observation->rootUsable) return;
    BOOL chrome=TCPhotosSnapshotNodeIsChrome(kind,identifier,label);
    if (chrome) observation->chromeMatches++;
    // The root is the already resolved app.popovers element. Its outer frame
    // remains authoritative even if a public snapshot omits remote descendants.
    if ((isQueriedPopoverRoot || kind==TCPickerNodePopover || chrome) && TCPickerRectIsUsable(frame))
        observation->bounds=CGRectUnion(observation->bounds,frame);
}

static inline BOOL TCPickerAdvanceStability(const TCPickerSnapshotObservation *observation,
                                            CGRect *previous, CGRect *observedPicker) {
    if (!observation || !observation->rootUsable || !TCPickerRectIsUsable(observation->bounds)) {
        *previous=CGRectNull;*observedPicker=CGRectNull;
        return NO;
    }
    BOOL same=CGRectEqualToRect(observation->bounds,*previous);
    *previous=observation->bounds;*observedPicker=observation->bounds;
    return same;
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
