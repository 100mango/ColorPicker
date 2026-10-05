#ifndef TC_WATCH_LIST_DRAG_GEOMETRY_H
#define TC_WATCH_LIST_DRAG_GEOMETRY_H
#include <math.h>
#include <stddef.h>
#include <limits.h>

/* Test-only, public-frame arithmetic. No UI state, focus or event synthesis. */
typedef struct { double x, y, width, height; } TCWatchListRect;
typedef struct { double x, y; } TCWatchListPoint;
typedef struct { int index; TCWatchListRect frame; } TCWatchListRow;
typedef struct {
    TCWatchListRect content;
    TCWatchListPoint start, end;
    int direction;
} TCWatchListDrag;
static const int TCWatchListAmbiguous = 0, TCWatchListEarlier = -1,
    TCWatchListLater = 1, TCWatchListReady = 2;

static inline int TCWatchListValid(TCWatchListRect r) {
    return isfinite(r.x) && isfinite(r.y) && isfinite(r.width) && isfinite(r.height)
        && r.width > 0 && r.height > 0 && isfinite(r.x + r.width) && isfinite(r.y + r.height);
}
static inline int TCWatchListContains(TCWatchListRect outer, TCWatchListRect inner) {
    return TCWatchListValid(outer) && TCWatchListValid(inner)
        && inner.x >= outer.x && inner.y >= outer.y
        && inner.x + inner.width <= outer.x + outer.width
        && inner.y + inner.height <= outer.y + outer.height;
}
static inline TCWatchListRect TCWatchListIntersection(TCWatchListRect a, TCWatchListRect b) {
    double x = fmax(a.x, b.x), y = fmax(a.y, b.y);
    return (TCWatchListRect){x, y, fmin(a.x+a.width, b.x+b.width)-x,
        fmin(a.y+a.height, b.y+b.height)-y};
}
/* Navigation may overlay the CollectionView. Never drag through that chrome. */
static inline int TCWatchListContent(TCWatchListRect viewport, TCWatchListRect list,
                                    TCWatchListRect navigation, TCWatchListRect *content) {
    if (!content || !TCWatchListValid(viewport) || !TCWatchListValid(list)
        || !TCWatchListValid(navigation)) return 0;
    TCWatchListRect visible = TCWatchListIntersection(viewport, list);
    if (!TCWatchListValid(visible) || navigation.x > visible.x
        || navigation.x + navigation.width < visible.x + visible.width
        || navigation.y > visible.y || navigation.y + navigation.height < viewport.y
        || navigation.y + navigation.height >= visible.y + visible.height) return 0;
    double bottom = visible.y + visible.height;
    visible.y = fmax(visible.y, navigation.y + navigation.height);
    visible.height = bottom - visible.y;
    if (visible.width < 40 || visible.height < 60) return 0;
    *content = visible;
    return 1;
}
/* Indices -1 and INT_MAX describe observed header/footer anchors, respectively.
   Only intersecting rows contribute direction. Missing/contradictory evidence fails. */
static inline int TCWatchListPlan(TCWatchListRect viewport, TCWatchListRect list,
                                 TCWatchListRect navigation, int targetIndex,
                                 int hasTarget, TCWatchListRect target,
                                 const TCWatchListRow *rows, size_t count,
                                 TCWatchListDrag *plan) {
    if (!plan || targetIndex < 0 || (hasTarget != 0 && hasTarget != 1) || count > 24 || (count && !rows)
        || !TCWatchListContent(viewport, list, navigation, &plan->content)) return TCWatchListAmbiguous;
    TCWatchListRect content = plan->content;
    int direction = TCWatchListAmbiguous;
    if (hasTarget) {
        if (!TCWatchListValid(target) || target.x < content.x
            || target.x + target.width > content.x + content.width
            || target.height > content.height) return TCWatchListAmbiguous;
        if (TCWatchListContains(content, target)) return TCWatchListReady;
        if (target.y < content.y) direction = TCWatchListEarlier;
        else if (target.y + target.height > content.y + content.height) direction = TCWatchListLater;
    } else {
        for (size_t i = 0; i < count; ++i) {
            if (!TCWatchListValid(rows[i].frame) || rows[i].index < -1) return TCWatchListAmbiguous;
            if (!TCWatchListValid(TCWatchListIntersection(content, rows[i].frame))) continue;
            int observed = rows[i].index < targetIndex ? TCWatchListLater
                : (rows[i].index > targetIndex ? TCWatchListEarlier : TCWatchListAmbiguous);
            if (!observed || (direction && direction != observed)) return TCWatchListAmbiguous;
            direction = observed;
        }
    }
    if (!direction) return TCWatchListAmbiguous;
    /* At most 32pt / 22% of visible content; hold after drag suppresses fling.
       Clipped targets use only the remaining reveal distance plus a small margin. */
    double distance = fmin(32.0, content.height * 0.22);
    if (hasTarget) {
        double missing = direction == TCWatchListEarlier ? content.y - target.y
            : target.y + target.height - content.y - content.height;
        distance = fmin(distance, fmax(12.0, missing + 6.0));
    }
    double centerX = content.x + content.width * 0.5;
    double centerY = content.y + content.height * 0.5;
    double delta = direction == TCWatchListLater ? -distance : distance;
    plan->start = (TCWatchListPoint){centerX, centerY - delta * 0.5};
    plan->end = (TCWatchListPoint){centerX, centerY + delta * 0.5};
    plan->direction = direction;
    return direction;
}
/* Validation only: keep the already planned path byte-for-byte unchanged.
   Identified semantic leaves are candidates, not their overlapping containers.
   A clipped/ambiguous start, missing identity or stale/occluded live element fails. */
static inline int TCWatchListPointInside(TCWatchListRect frame, TCWatchListPoint point) {
    return TCWatchListValid(frame) && isfinite(point.x) && isfinite(point.y)
        && point.x > frame.x && point.x < frame.x + frame.width
        && point.y > frame.y && point.y < frame.y + frame.height;
}
static inline int TCWatchListTouchAnchorIndex(const TCWatchListDrag *plan,
                                             const TCWatchListRect *frames, size_t count) {
    if (!plan || !frames || !count || count > 24
        || (plan->direction != TCWatchListEarlier && plan->direction != TCWatchListLater)
        || !TCWatchListPointInside(plan->content, plan->start)
        || !TCWatchListPointInside(plan->content, plan->end)) return -1;
    int match = -1;
    for (size_t i = 0; i < count; ++i) {
        if (!TCWatchListValid(frames[i])) return -1;
        if (!TCWatchListPointInside(frames[i], plan->start)) continue;
        if (match >= 0 || !TCWatchListContains(plan->content, frames[i])) return -1;
        match = (int)i;
    }
    return match;
}
static inline int TCWatchListTouchAnchorReady(const TCWatchListDrag *plan,
                                              TCWatchListRect captured, TCWatchListRect live,
                                              size_t matches, int exists, int hittable, int currentHome) {
    return plan && matches == 1 && exists == 1 && hittable == 1 && currentHome == 1
        && captured.x == live.x && captured.y == live.y
        && captured.width == live.width && captured.height == live.height
        && TCWatchListTouchAnchorIndex(plan, &live, 1) == 0;
}
/* Gap-only adaptation. The accepted planner/validators above remain unchanged.
   The input plan is immutable; separate output is written only on success.
   Public semantic frames include leaves outside the List so they can veto a
   start, never qualify as an anchor. Border contact is not a genuine gap. */
static inline int TCWatchListPointTouches(TCWatchListRect frame, TCWatchListPoint point) {
    return TCWatchListValid(frame) && isfinite(point.x) && isfinite(point.y)
        && point.x >= frame.x && point.x <= frame.x + frame.width
        && point.y >= frame.y && point.y <= frame.y + frame.height;
}
static inline int TCWatchListSameRect(TCWatchListRect a, TCWatchListRect b) {
    return a.x == b.x && a.y == b.y && a.width == b.width && a.height == b.height;
}
static inline int TCWatchListSingleSemanticStart(TCWatchListRect row, TCWatchListPoint start,
                                                 const TCWatchListRect *leaves, size_t count) {
    size_t covers = 0;
    for (size_t i = 0; i < count; ++i) {
        if (!TCWatchListPointTouches(leaves[i], start)) continue;
        if (!TCWatchListSameRect(row, leaves[i]) || !TCWatchListPointInside(leaves[i], start)) return 0;
        ++covers;
    }
    return covers == 1;
}
static inline int TCWatchListSelectTouch(const TCWatchListDrag *original,
                                         const TCWatchListRect *frames, size_t count,
                                         const TCWatchListRect *leaves, size_t leafCount,
                                         TCWatchListDrag *output, int *usedGap) {
    if (!original || !output || original == output || !usedGap || !frames || !count || count > 24
        || !leaves || !leafCount || leafCount > 512
        || (original->direction != TCWatchListEarlier && original->direction != TCWatchListLater)
        || !TCWatchListPointInside(original->content, original->start)
        || !TCWatchListPointInside(original->content, original->end)
        || original->start.x != original->end.x) return -1;
    double delta = original->end.y - original->start.y;
    double cap = fmin(32.0, original->content.height * 0.22);
    /* Use the unchanged planner's own endpoint arithmetic for fractional caps.
       Never accept a larger representable delta or an absolute size over 32pt. */
    double centerY = original->content.y + original->content.height * 0.5;
    double maximumDelta = (centerY + cap * 0.5) - (centerY - cap * 0.5);
    if (!isfinite(delta) || delta == 0 || fabs(delta) > maximumDelta || fabs(delta) > 32.0
        || (original->direction == TCWatchListLater ? delta >= 0 : delta <= 0)) return -1;
    for (size_t i = 0; i < count; ++i) if (!TCWatchListValid(frames[i])) return -1;
    for (size_t i = 0; i < leafCount; ++i) if (!TCWatchListValid(leaves[i])) return -1;
    int originalIndex = TCWatchListTouchAnchorIndex(original, frames, count);
    if (originalIndex >= 0) {
        if (!TCWatchListSingleSemanticStart(frames[originalIndex], original->start, leaves, leafCount)) return -1;
        *output = *original;
        *usedGap = 0;
        return originalIndex;
    }
    /* A clipped, covered, overlapping or border start cannot trigger fallback. */
    for (size_t i = 0; i < count; ++i)
        if (TCWatchListPointTouches(frames[i], original->start)) return -1;
    for (size_t i = 0; i < leafCount; ++i)
        if (TCWatchListPointTouches(leaves[i], original->start)) return -1;
    int selected = -1, tied = 0;
    double nearest = INFINITY;
    TCWatchListDrag best = *original;
    for (size_t i = 0; i < count; ++i) {
        if (!TCWatchListContains(original->content, frames[i])) continue;
        TCWatchListDrag candidate = *original;
        candidate.start.y = frames[i].y + frames[i].height * 0.5;
        candidate.end.y = candidate.start.y + delta;
        if (!isfinite(candidate.end.y) || candidate.end.y - candidate.start.y != delta
            || TCWatchListTouchAnchorIndex(&candidate, frames, count) != (int)i
            || !TCWatchListSingleSemanticStart(frames[i], candidate.start, leaves, leafCount)) continue;
        double distance = fabs(candidate.start.y - original->start.y);
        if (!isfinite(distance)) return -1;
        if (distance < nearest) { nearest = distance; selected = (int)i; best = candidate; tied = 0; }
        else if (distance == nearest) tied = 1;
    }
    if (selected < 0 || tied) return -1;
    *output = best;
    *usedGap = 1;
    return selected;
}
/* Action readiness only: preserve the original full-containment planner above.
   A partial button may be tapped only at its explicit center. Horizontal clipping,
   more than 4pt or 10% vertical clipping, and centers within 2pt of chrome fail.
   This never qualifies readable text or the tap:false full-row observation. */
static inline int TCWatchListPartialTapPoint(TCWatchListRect content, TCWatchListRect target,
                                              TCWatchListPoint *point) {
    if (!point || !TCWatchListValid(content) || !TCWatchListValid(target)
        || TCWatchListContains(content, target) || target.height > content.height
        || target.x < content.x || target.x + target.width > content.x + content.width) return 0;
    TCWatchListRect visible = TCWatchListIntersection(content, target);
    double clipped = target.height - visible.height;
    TCWatchListPoint center = {target.x + target.width * 0.5, target.y + target.height * 0.5};
    if (!TCWatchListValid(visible) || !isfinite(clipped) || clipped <= 0
        || clipped > fmin(4.0, target.height * 0.1)
        || !TCWatchListPointInside(content, center)
        || center.x <= content.x + 2 || center.x >= content.x + content.width - 2
        || center.y <= content.y + 2 || center.y >= content.y + content.height - 2) return 0;
    *point = center;
    return 1;
}
static inline int TCWatchListPartialTapReady(TCWatchListRect content,
                                              TCWatchListRect captured, TCWatchListRect live,
                                              const TCWatchListRect *leaves, size_t leafCount,
                                              size_t matches, int exists, int hittable, int currentHome,
                                              TCWatchListPoint actualPoint) {
    TCWatchListPoint expected;
    if (!leaves || !leafCount || leafCount > 512 || matches != 1 || exists != 1
        || hittable != 1 || currentHome != 1 || !TCWatchListSameRect(captured, live)
        || !TCWatchListPartialTapPoint(content, captured, &expected)
        || actualPoint.x != expected.x || actualPoint.y != expected.y) return 0;
    for (size_t i = 0; i < leafCount; ++i) if (!TCWatchListValid(leaves[i])) return 0;
    return TCWatchListSingleSemanticStart(captured, actualPoint, leaves, leafCount);
}
#endif
