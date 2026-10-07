# Two actual Mac Store screenshots

This independent candidate starts from qualified Chinese-contact commit
68c8e09fef5187d549e5e032a5b083a04d0c1c79, tree
1635d893d34af37daa28afc6c31bcec94380e8fe. The original English default-launch
contact, Chinese sandbox contact, functional results and investigated audit
limitations remain recorded separately. This route does not rerun those cases.
The actual unsigned universal archive at 7d27938/run37561813814 is separate.

One fixed branch, codex/mac-store-capture, automatically runs one standard
xcode-27 Mac job, maximum 25 minutes and attempt 1 only. It builds once with
the original Debug scheme and arm64 destination, then runs only
testStoreNormalSamplingAndPaletteScreenshots without rebuilding. There is no
matrix, alternate launcher, explicit locale tuple, account, signing update,
privacy permission, accessibility audit, camera, Photos or distribution upload.

The only application addition is a DEBUG gate requiring a UUID token, isolated
test defaults and the two exact capture arguments. It sets the existing
workspace window's frame to 1280 by 800 once. It creates no window, activates
nothing, changes no scene/StateObject identity and changes no persistent display
setting. Release projection matches the accepted app source. Test-only inverse
helpers keep all prior source contracts pinned after removing these exact edits.

The sole case uses actual Paste commands and the existing import code:

1. Sampling: an actual 300 by 200 six-color image in the normal workspace,
   center sample #ff00ff and empty palette.
2. Palette: that same image/sample with five colors imported from a real JSON
   file, showing the ordinary palette controls.

Both are XCUIElement window screenshots, with one app window and no sheet or
dialog. Exact PNG dimensions must be 1280 by 800. A clipped/constrained window
or different backing scale fails; no resizing, stretching, cropping, generated
UI or fallback window is used. Actual complete-window pixels and presentation
remain subject to human visual review after capture.

Apple accepts PNG screenshots and requires 16:10 Mac sizes including 1280 by
800. Its current rules prohibit alpha channels:
https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
The original native PNG is always retained. An already-RGB PNG stays identical.
A fully opaque RGBA PNG gets an RGB copy only after every alpha value is 255;
decoded RGB bytes and color-profile data stay equal. Transparency rejects the
copy. No background is added, and pixels are never interpolated or redrawn.

Expected artifact: native-sampling.png, native-palette.png, store-sampling.png,
store-palette.png and report.json. The two store files are the proposed assets;
the native files are their provenance. Each PNG is at most 3 MiB, the report
at most 2 MiB and the packet at most 14 MiB. No app, xcarchive, dSYM or xcresult
binary is shared. Failure keeps bounded diagnostic JSON and remains failed.
If the original case and all pixel-source checks pass but PNG format conversion
rejects an image, its bound native original remains available for inspection;
it is not marked as a qualified Store image.

The report binds one successful, non-skipped case to its original command wall
clock, exported attachment identities, one PID/token, exact product path and
executable/debug-dylib hashes. Original PNG bytes match the in-test digest.
Product and source hashes are rechecked after capture. A green capture remains
pending human visual acceptance and does not claim App Store release approval.

The existing bounded process capture and reviewed archive clock/upload pattern
are reused. Phase ceilings from the original script start are: prepare 180 s,
build 640 s, test 960 s, proof 1140 s, source/report 1170 s, upload 1230 s,
finalization 1250 s. Build has at most 420 s plus 20 s owned cleanup; the one
test at most 300 s plus 20 s cleanup, with XCTest allowance 120 s. Evidence has
180 s including summary/export (40 s each with cleanup), validation and PNG
conversion. Final source/report has 30 s; upload and post-upload get 60/20 s.
Checkout is capped at 60 s, leaving 190 s before the 25-minute job limit.
No phase borrows cleanup or upload reserves, and no operation is retried.

Local portable tests do not execute Swift, AppKit, XCTest or a native capture.
