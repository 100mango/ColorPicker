# Two actual Mac Store screenshots

This narrow successor starts from the first capture commit
79cd8942387841ec2fdec72815523191b78c756b, tree
d6b680228441e8c6247e8aa25f95bbb9a91de6f7. Run37565730932 built successfully
and sampled #ff00ff, but observed a 1280 by 677 window instead of 1280 by 800.
That original failure and its bounded evidence remain intact. AppKit's documented
height-only screen constraint is the leading inference; the run did not record
the actual display geometry. The original English default-launch
contact, Chinese sandbox contact, functional results and investigated audit
limitations remain recorded separately. This route does not rerun those cases.
The actual unsigned universal archive at 7d27938/run37561813814 is separate.

One fixed branch, codex/mac-store-display, automatically runs one standard
xcode-27 Mac job, maximum 25 minutes and attempt 1 only. It builds once with
the original Debug scheme and arm64 destination, then runs only
testStoreNormalSamplingAndPaletteScreenshots without rebuilding. There is no
matrix, alternate launcher, explicit locale tuple, account, signing update,
privacy permission, accessibility audit, camera, Photos or distribution upload.

The application addition remains a DEBUG gate requiring a UUID token, isolated
test defaults and the two exact capture arguments. It sets the existing
workspace window's frame to 1280 by 800 once. It centers that existing window
inside the actual visible screen, aligning the origin to backing pixels. It creates no window, activates
nothing, changes no scene/StateObject identity and changes no persistent display
setting. Release projection matches the accepted app source. Test-only inverse
helpers keep all prior source contracts pinned after removing these exact edits.

Before that sole case launches the app, its existing UITestRunner records
CGDisplay/NSScreen mode, frame, visibleFrame and backingScale. It retains a
currently sufficient mode. Otherwise it selects one actually advertised,
desktop-usable mode, preferring 1x then the smallest sufficient logical area.
Selection accounts for the current menu bar/Dock exclusion from visibleFrame.
The SDK transaction uses forAppOnly inside the runner that remains alive for
the whole case; it does not write permanent preferences. A bounded readiness
check must observe enough actual visible space before app launch. No suitable
advertised mode, rejected configuration or insufficient resulting space yields
one explicit STORE_DISPLAY_BLOCKED failure with bounded mode facts; no other
mode is tried. The catalogue is limited to 128 modes/16 KiB per display receipt.
There is no tool installation, helper runner or use of the user's computer.

Teardown attempts to restore the saved original mode and records its result.
An unsuccessful or missing explicit restore is an unconfirmed runner cleanup
observation; it does not erase source-bound screenshots or make app functionality
fail. The overall job can remain failed while capture_qualified stays true and
all four image components remain available. forAppOnly also limits the change
to the caller's lifetime; automatic reset after exit is not separately observed.

The sole case uses actual Paste commands and the existing import code:

1. Sampling: an actual 300 by 200 six-color image in the normal workspace,
   center sample #ff00ff and empty palette.
2. Palette: that same image/sample with five colors imported from a real JSON
   file, showing the ordinary palette controls.

Both are XCUIElement window screenshots, with one app window and no sheet or
dialog. The AX window is 1280 by 800 points, entirely inside the actual visible
screen. A 1x display must produce 1280 by 800 native pixels; a 2x display must
produce 2560 by 1600 native pixels. Both are accepted Apple Mac sizes. A clipped
window or disagreement between actual backing scale and native PNG fails; no resizing, stretching, cropping, generated
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
