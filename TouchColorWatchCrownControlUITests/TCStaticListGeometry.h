#ifndef TC_STATIC_LIST_GEOMETRY_H
#define TC_STATIC_LIST_GEOMETRY_H
#include <math.h>
#include <stddef.h>

/* Test-only portable arithmetic; all inputs come from the current AX snapshot. */
typedef struct { double x, y, width, height; } TCStaticRect;
typedef struct { double x, y; } TCStaticPoint;
typedef struct { TCStaticRect content; TCStaticPoint start, end; } TCStaticDrag;

static inline int TCStaticValid(TCStaticRect r) {
    return isfinite(r.x) && isfinite(r.y) && isfinite(r.width) && isfinite(r.height)
        && r.width > 0 && r.height > 0 && isfinite(r.x + r.width) && isfinite(r.y + r.height);
}
static inline int TCStaticContains(TCStaticRect outer, TCStaticRect inner) {
    return TCStaticValid(outer) && TCStaticValid(inner) && inner.x >= outer.x && inner.y >= outer.y
        && inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;
}
static inline int TCStaticContent(TCStaticRect viewport, TCStaticRect list, TCStaticRect nav, TCStaticRect *out) {
    if (!out || !TCStaticValid(viewport) || !TCStaticValid(list) || !TCStaticValid(nav)) return 0;
    double x = fmax(viewport.x, list.x), right = fmin(viewport.x + viewport.width, list.x + list.width);
    double y = fmax(viewport.y, list.y), bottom = fmin(viewport.y + viewport.height, list.y + list.height);
    /* Require a top-spanning current navigation bar; ambiguous floating bars fail closed. */
    if (nav.x > x || nav.x + nav.width < right || nav.y > y || nav.y + nav.height <= viewport.y) return 0;
    y = fmax(y, nav.y + nav.height);
    TCStaticRect content = {x, y, right-x, bottom-y};
    if (!TCStaticValid(content) || content.width < 32 || content.height < 48) return 0;
    *out = content;
    return 1;
}
static inline int TCStaticPlan(TCStaticRect viewport, TCStaticRect list, TCStaticRect nav, TCStaticDrag *out) {
    TCStaticRect c;
    if (!out || !TCStaticContent(viewport, list, nav, &c)) return 0;
    /* One upward finger motion, <=32 points, inset from all content edges. */
    double distance = fmin(32.0, (c.height - 24.0) / 2.0);
    if (!isfinite(distance) || distance < 12) return 0;
    out->content = c;
    out->start = (TCStaticPoint){c.x + c.width/2, c.y + c.height/2 + distance/2};
    out->end = (TCStaticPoint){out->start.x, out->start.y - distance};
    return out->end.y > c.y + 8 && out->start.y < c.y + c.height - 8;
}
#endif
