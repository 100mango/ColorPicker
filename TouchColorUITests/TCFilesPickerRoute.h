#ifndef TC_FILES_PICKER_ROUTE_H
#define TC_FILES_PICKER_ROUTE_H
#include <string.h>
#include <math.h>

typedef enum { TCFilesNodeOther, TCFilesNodeCell, TCFilesNodeButton, TCFilesNodeStaticText } TCFilesNodeKind;
typedef enum { TCFilesRouteNone, TCFilesRouteLocalProvider, TCFilesRouteLocationCell, TCFilesRouteBrowse, TCFilesRouteFixtureFile } TCFilesRoute;

static inline int TCFilesRouteFrameIsUsable(double x, double y, double width, double height) {
    return isfinite(x) && isfinite(y) && isfinite(width) && isfinite(height) && width > 0 && height > 0;
}

static inline int TCFilesNameEquals(const char *value, const char *expected) {
    return value && expected && strcmp(value,expected)==0;
}
static inline int TCFilesPrefixedNameEquals(const char *value, const char *prefix, const char *suffix) {
    return value && suffix && strncmp(value,prefix,strlen(prefix))==0 && strcmp(value+strlen(prefix),suffix)==0;
}
static inline TCFilesRoute TCClassifyFilesRoute(TCFilesNodeKind kind, const char *identifier,
                                               const char *label, const char *location) {
    if (kind==TCFilesNodeOther && TCFilesPrefixedNameEquals(identifier,
        "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: ",location)) return TCFilesRouteLocalProvider;
    // A navigation-title StaticText is state, never an actionable location.
    if (kind==TCFilesNodeCell && (TCFilesPrefixedNameEquals(identifier,"DOC.sidebar.item.",location) ||
        TCFilesNameEquals(label,location))) return TCFilesRouteLocationCell;
    if (kind==TCFilesNodeButton && TCFilesNameEquals(label,"Browse")) return TCFilesRouteBrowse;
    const char *filePrefix="TouchColor-Ordered-Colors";
    if (kind==TCFilesNodeStaticText && label && strncmp(label,filePrefix,strlen(filePrefix))==0) return TCFilesRouteFixtureFile;
    return TCFilesRouteNone;
}
#endif
