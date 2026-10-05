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
#endif
