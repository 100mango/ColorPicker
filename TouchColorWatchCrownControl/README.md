# Isolated static Watch Crown control

Implementation-only diagnostic. No Swift compilation, Watch installation, simulator
execution, CI dispatch, or publication was performed in the Linux workspace.
Existing product Home and real RGB Crown tests keep their own acceptance results.
A passing static control must never relabel an existing Home failure.

## Isolation

- Project and shared scheme: `TouchColorWatchCrownControl.xcodeproj` /
  `TouchColorWatchCrownControl`.
- App bundle: `com.mango.touchColor.watchCrownControl`.
- UI bundle: `com.mango.touchColor.watchCrownControl.uitests`.
- Test selector:
  `TouchColorWatchCrownControlUITests/WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations`.
- Only Debug configurations exist; both Swift files fail compilation without DEBUG.
  There is no archive action. The source allowlist contains one static app source
  and one independent UI-test source, with a test-only C arithmetic header.
- No product sources, local packages, resources, model objects, persistence,
  connectivity, editor, application-owned mutable state, custom Crown handling,
  or focus requests are linked into the app. The 12 immutable rows lead only to
  inert text destinations. There is no related phone target or companion bundle.
- The test checks that the real product bundle is already not running, before it
  launches the separate control. A running product aborts this measurement; the
  test does not terminate or otherwise interact with it.

## Exact observation contract

After asserting the initial top row is fully inside the actual content rectangle
and row 11 is offscreen/nonhittable, the independent test sends exactly three
`rotateDigitalCrown(delta: -0.1)` calls. Each has one before and one after public
`app.snapshot()` capture. Failed startup/preconditions or incomplete geometry abort
rather than silently changing the event count or fabricating evidence.

A downward result requires a common observed row to move upward in screen Y by
more than one point, with stable width/X/height and unchanged viewport, actual
List and navigation geometry. The snapshot must contain exactly one List with
identifier `static.list`, one `Crown Control` navigation bar, no BackButton and
complete bounded traversal. Other changes are inconclusive. Captures and the
result marker include the actual identifiers/title; they do not infer focus or
prove absence of transient event delivery.

Only a stationary Crown result permits the optional touch control. It takes a
fresh snapshot, confirms nothing moved since the final Crown observation, clips
the actual List to the actual viewport and navigation bar, and computes a single
upward finger drag of at most 32 points. It checks live identities, foreground
state, List hittability, viewport/List/navigation frames, and both dynamic screen
coordinates immediately before the public native gesture. One post-gesture
snapshot determines the separately named touch status. Geometry ambiguity prevents
the drag. Touch failure is caught so it cannot suppress the final Crown result.
Touch movement cannot modify or satisfy the strict final Crown assertion.

Unhandled UI interruptions print a bounded abort marker and terminate the test
process before XCTest's default handlers can take an unintended alert action.
The abort is a failure/inconclusive control, never a skip or expected pass.

## Bounded evidence

- At most 6 explicit Crown captures plus 2 explicit touch captures.
- At most 256 visited/retained pending snapshot nodes and 12 identified rows per
  capture. Omitted subtree-root counts are explicit; descendant totals are marked
  unknown instead of treating a skipped subtree as one omitted node.
- Each `WATCH_STATIC_CROWN_FRAME` JSON payload is capped at 1,536 bytes. Extra rows
  are omitted with counts, and any such omission disqualifies that capture.
- `WATCH_STATIC_CROWN_RESULT` reserves at most 2,048 bytes and includes separate
  `crownStatus`/`touchStatus`, actual call/capture counts, snapshot errors, omissions,
  failure reason and the serialized-byte total. The total structured payload cap
  is 16 KiB, leaving the other 16 KiB of the joint 32 KiB observation budget for
  the product Home observer. Marker overhead also fits within the 16 KiB bound.
- The public snapshot and normal element queries are implemented by XCTest/OS.
  These limits govern explicit captures, client traversal/retention and output;
  they do not claim to bound undocumented OS snapshot allocation/query activity.
- No raw hierarchy, screenshot, element values, or product data is dumped.

The final XCTest assertion requires `crownStatus == moved_downward` and exactly
three Crown calls. XCTest success alone is not evidence: review the separate marker,
matching case identity, geometry completeness, omissions and exact event counts.
The result is only the isolated static control; actual Home/RGB outcomes remain
separate and must be retained, even when either fails.

## Local verification

Run `python3 scripts/generate_watch_crown_control_project.py`, then
`python3 scripts/test_watch_crown_control_target.py -v`.

The 11 checks cover generated project determinism and source isolation, Debug-only
configuration/scheme, immutable app composition, exact Crown/status contracts,
bounded snapshot/output structure and fail-closed live touch guards. Five checks
compile and execute the actual C geometry helper using C11, strict warnings and
UBSan, including the retained 162x197 and 211x257 viewports, shifting/clipped
geometry, invalid/floating navigation bars, nonfinite inputs and broad dimensions.
These are portable arithmetic/source checks, not Swift type checking or native UI
acceptance. Exact Xcode 27 compilation, standalone watch-only installation, actual
AX identities/List/nav geometry, native press API availability and runtime Crown
behavior remain unverified. A future native run needs separate admission and must
stay inside the existing job/cleanup/evidence budget; this project does not add a
workflow or change a production test identifier.

## Primary API references

Reviewed against Apple documentation, not third-party usage examples:

- [Digital Crown delta and documented negative/downward direction](https://developer.apple.com/documentation/xcuiautomation/xcuidevice/rotatedigitalcrown(delta:))
- [Native coordinate drag with velocity and hold duration](https://developer.apple.com/documentation/xcuiautomation/xcuicoordinate/press(forduration:thendragto:withvelocity:thenholdforduration:))
- [Dynamic coordinate screen points and offsets](https://developer.apple.com/documentation/xcuiautomation/xcuicoordinate)
- [Public snapshot API](https://developer.apple.com/documentation/xcuiautomation/xcuielementsnapshotproviding)
- [UI interruption handling and handler ordering](https://developer.apple.com/documentation/xctest/handling-ui-interruptions)
- [Watch-only app declaration](https://developer.apple.com/documentation/bundleresources/information-property-list/wkwatchonly)
