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

typedef struct { CGRect window; CGPoint origin, axisX, axisY; double determinant; BOOL valid; } TCPickerScreenMap;
typedef struct { long orientation; BOOL landscape; CGRect currentBounds, fixedBounds; } TCPickerScreenContext;
typedef enum { TCPickerEnvelopeInvalid, TCPickerEnvelopeFixed, TCPickerEnvelopeCurrent } TCPickerScreenEnvelope;

static inline BOOL TCPickerPointIsFinite(CGPoint point) { return isfinite(point.x) && isfinite(point.y); }

static inline BOOL TCPickerScreenBoundsUsable(CGRect bounds) {
    return TCPickerRectIsUsable(bounds) && isfinite(CGRectGetMaxX(bounds)) && isfinite(CGRectGetMaxY(bounds));
}
static inline BOOL TCPickerScreenContextUsable(TCPickerScreenContext context) {
    return context.landscape && TCPickerScreenBoundsUsable(context.currentBounds) && TCPickerScreenBoundsUsable(context.fixedBounds);
}
static inline BOOL TCPickerScreenContextStable(TCPickerScreenContext before, TCPickerScreenContext after) {
    return TCPickerScreenContextUsable(before) && TCPickerScreenContextUsable(after) &&
        before.orientation==after.orientation && CGRectEqualToRect(before.currentBounds,after.currentBounds) &&
        CGRectEqualToRect(before.fixedBounds,after.fixedBounds);
}
static inline BOOL TCPickerScreenContainsCoordinates(CGRect bounds, const CGPoint *points, NSUInteger count) {
    if (!TCPickerScreenBoundsUsable(bounds) || !points || count!=5) return NO;
    // Four basis corners can lie exactly on screen edges. Use one inclusive
    // screen-point tolerance for the complete sample, not a different space per point.
    for (NSUInteger i=0;i<count;i++) {
        if (!TCPickerPointIsFinite(points[i]) || points[i].x<CGRectGetMinX(bounds)-1 || points[i].x>CGRectGetMaxX(bounds)+1 ||
            points[i].y<CGRectGetMinY(bounds)-1 || points[i].y>CGRectGetMaxY(bounds)+1) return NO;
    }
    return YES;
}
static inline TCPickerScreenEnvelope TCPickerChooseScreenEnvelope(TCPickerScreenContext context, const CGPoint points[5], CGRect *envelope) {
    if (!envelope) return TCPickerEnvelopeInvalid;
    *envelope=CGRectNull;
    if (!TCPickerScreenContextUsable(context)) return TCPickerEnvelopeInvalid;
    if (TCPickerScreenContainsCoordinates(context.fixedBounds,points,5)) { *envelope=context.fixedBounds;return TCPickerEnvelopeFixed; }
    if (TCPickerScreenContainsCoordinates(context.currentBounds,points,5)) { *envelope=context.currentBounds;return TCPickerEnvelopeCurrent; }
    return TCPickerEnvelopeInvalid;
}

// Basis points are measured from the same window's normalized XCTest coordinates.
// Do not assume screenPoint and the landscape AX frame use the same axes.
static inline BOOL TCPickerMakeScreenMap(CGRect window, CGPoint zero, CGPoint oneX, CGPoint oneY,
                                         TCPickerScreenMap *map) {
    if (!map) return NO;
    *map=(TCPickerScreenMap){0};
    if (!TCPickerRectIsUsable(window) || !isfinite(CGRectGetMaxX(window)) || !isfinite(CGRectGetMaxY(window)) || !TCPickerPointIsFinite(zero) ||
        !TCPickerPointIsFinite(oneX) || !TCPickerPointIsFinite(oneY)) return NO;
    CGPoint x=CGPointMake(oneX.x-zero.x,oneX.y-zero.y), y=CGPointMake(oneY.x-zero.x,oneY.y-zero.y);
    double lengthX=hypot(x.x,x.y), lengthY=hypot(y.x,y.y);
    double area=lengthX*lengthY, determinant=x.x*y.y-x.y*y.x;
    if (!isfinite(area) || !isfinite(determinant) || lengthX<=1e-6 || lengthY<=1e-6 ||
        fabs(determinant)<=area*1e-6) return NO;
    *map=(TCPickerScreenMap){window,zero,x,y,determinant,YES};
    return YES;
}

static inline BOOL TCPickerMapAXPoint(TCPickerScreenMap map, CGPoint point, CGPoint *screenPoint) {
    if (!map.valid || !screenPoint || !TCPickerPointIsFinite(point)) return NO;
    double u=(point.x-map.window.origin.x)/map.window.size.width;
    double v=(point.y-map.window.origin.y)/map.window.size.height;
    CGPoint result=CGPointMake(map.origin.x+u*map.axisX.x+v*map.axisY.x,
                               map.origin.y+u*map.axisX.y+v*map.axisY.y);
    if (!TCPickerPointIsFinite(result)) return NO;
    *screenPoint=result;return YES;
}

static inline BOOL TCPickerMapAXRect(TCPickerScreenMap map, CGRect rect, CGPoint corners[4]) {
    if (!map.valid || !corners || !TCPickerRectIsUsable(rect)) return NO;
    CGPoint points[]={CGPointMake(CGRectGetMinX(rect),CGRectGetMinY(rect)),CGPointMake(CGRectGetMaxX(rect),CGRectGetMinY(rect)),
        CGPointMake(CGRectGetMaxX(rect),CGRectGetMaxY(rect)),CGPointMake(CGRectGetMinX(rect),CGRectGetMaxY(rect))};
    for (NSUInteger i=0;i<4;i++) if (!TCPickerMapAXPoint(map,points[i],&corners[i])) return NO;
    return YES;
}

// Work entirely in measured screen-point space, including the exclusion polygon.
// An invalid transform never counts as an outside point. Edges are included.
typedef enum { TCPickerScreenRelationInvalid, TCPickerScreenRelationInside, TCPickerScreenRelationOutside } TCPickerScreenRelation;
static inline TCPickerScreenRelation TCPickerScreenPointRelation(TCPickerScreenMap map, CGRect rect, CGPoint point) {
    CGPoint corners[4];
    if (!TCPickerPointIsFinite(point) || !TCPickerMapAXRect(map,rect,corners)) return TCPickerScreenRelationInvalid;
    BOOL outside=NO;
    for (NSUInteger i=0;i<4;i++) {
        CGPoint a=corners[i], b=corners[(i+1)%4];
        double dx=b.x-a.x,dy=b.y-a.y;
        double cross=dx*(point.y-a.y)-dy*(point.x-a.x);
        double length=hypot(dx,dy);
        if (!isfinite(cross) || !isfinite(length) || length<=1e-6) return TCPickerScreenRelationInvalid;
        double inward=map.determinant>0 ? cross : -cross;
        if (inward < -length) outside=YES; // Keep a one-screen-point safety margin.
    }
    return outside ? TCPickerScreenRelationOutside : TCPickerScreenRelationInside;
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
