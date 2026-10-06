# TouchColor original native Store screenshot candidate

Local preparation only. This does not authorize publication, a Mac job, signing,
a binary upload, or Store screenshot upload. No new native screenshot exists yet.

## Product and isolated delta

The exact sole proposed capture parent is
`459c70bf616e5bb488b2140bc79c72745704a8b4`, tree
`bd59eff3932b1dd1d5a055e7d7153870ba2802fd`. Original iOS app 859727780 is
`com.mango.touchColor`, version 2.0, build 20001, iPhone/iPad families `[1,2]`.
The later acceptance candidate tree `35baaf3fe29cee370229c2806b852febb862ba5f`
has the same product inputs; its separate acceptance changes are not copied into
this capture branch. This route does not alter or replace its qualification.

381 of 383 base files stay byte-identical. Two precisely hashed additions are
reversible to the complete original bytes:

- A compile-gated include is appended to the already compiled
  `TouchColorUITests/TouchColorUITests.m`. It includes the separate
  `TouchColorStoreCaptureUITests.inc` class only with the capture build’s explicit
  `TOUCHCOLOR_STORE_CAPTURE=1` definition. Ordinary scheme builds do not compile
  or discover the new cases. Original class methods, source test counts and
  selectors remain unchanged. No project change is needed.
- Seven lines inside the existing `#if DEBUG` `openFixture` method remove only
  the test-only “Sample Fixture” navigation item when the new
  `--ui-test-store-capture` argument is present. Without that argument the old
  DEBUG behavior remains. The ordinary `showImage`, image/pixel sampling,
  crosshair, save, persistence, history and navigation code stays unchanged.

There are seven new text files: the gated capture class, this document, the
single capture workflow, runner, protected-source manifest, small bounded-process
adapter, and focused local tests. No binary or image file is added. The adapter reuses the existing
TouchColor `bounded_process.stop_group` and `atomic_json.write_json`; its bounded
streaming and durable uncertainty barrier follow the reviewed QRCatcher route.

A portable check runs the real host C preprocessor with `DEBUG=0` on both app-file
versions after removing the identical framework import directives. It compares
all nonblank physical lines byte-for-byte and proves this source projection is
identical; only blank physical lines may be ignored. Strings and nonblank tokens
are never normalized. This is a source proof without an Apple SDK, not a native
Release binary build or a claim of byte-identical signed binaries. `DEBUG=1`
retains the isolated capture branch, and deleting the delimited addition restores
the exact original full source file hash.

## Four useful genuine UI views

The unchanged existing DEBUG entrance makes a 300×200 six-color synthetic image
(red/green/blue above cyan/magenta/yellow) using the existing renderer. It then
calls the normal `showImage:` path. The image is synthetic, not a user's photo or
a physical camera result. There is no system Photos cold-start, image download,
photo-library mutation, separate fixture host, or direct write of saved colors.

On each device, two independently reset, selected tests run:

1. Photo: tap the center of the magenta block at image point `(0.5,0.75)`, away
   from color borders. Assert the real readout is `#ff00ff` and
   `R 255   G 0   B 255`, the crosshair is at that actual point, and normal sample
   and save controls remain usable.
2. History/palette: genuinely sample and save red at `(1/6,1/4)`, blue at
   `(5/6,1/4)`, and magenta at `(1/2,3/4)` through the ordinary UI. Check every
   sampled hex/RGB and marker position, the real saved/disabled button state,
   exactly three visible history rows and their complete hex/RGB labels. iPhone
   returns through the real Back button; iPad keeps the native photo+palette
   workspace. No history is injected or substituted.

Both use existing Simplified Chinese localization, normal Large/default body text,
light appearance and portrait orientation. Capture refuses an alert, sheet,
non-portrait app/device geometry, or a remaining “Sample Fixture” control. This
only proves the pictured synthetic-image sample/save path if the native tests
pass. It does not independently prove system photo import, physical camera
capture, a new Release build, or all release acceptance tests.

The old locally retained images were inspected first. There was no 1206×2622
phone PNG. The three 2064×2752 iPad audit PNGs are English and contain EXIF
orientation 8, so they are landscape despite portrait stored dimensions. They
are unsuitable as this Chinese portrait Store set and are not reused.

## Exact pixels and receipts

- iPhone 17 Pro: 1206×2622, two raw PNGs
- iPad Pro 13-inch (M5): 2064×2752, two raw PNGs
- Observed target runtime: iOS 27.0, build 24A434
- Required Xcode: 27.0, build 27A266a

Each test attaches `XCUIScreen.mainScreen.screenshot.PNGRepresentation` directly
as `public.png` / KeepAlways. Exported original bytes are never cropped, resized,
reencoded, alpha-stripped, color-converted or composited. PNG signature, chunk
bounds/CRC, bounded decompression/raster, dimensions, 8-bit RGB, absence of alpha
or transparency, and upright EXIF orientation (1 or absent) are validated. A
non-upright or alpha PNG is retained unchanged but is not a successful Store
candidate. The file SHA256 is over the exact original bytes.

Each selected single-case attachment must belong to its exact capture class and
method and carry the owned simulator UUID. The exact test must pass 1/1 with no
failures, skips, warnings or expected failures; its summary must match the same
model, UUID, runtime/build, architecture and actual invocation wall-clock window.

The runner binds source/workflow SHA, sole parent/tree, exact changed-path set,
run ID/attempt, one shared clock, original-source hashes and exact actual built
app identity. Full built/installed app file inventories are compared before and
after the cases. Every PNG is fsynced into the final packet immediately after its
own export, before summary validation, postflight, another case or device, and
cleanup. Source/run/device/product/attachment/PNG byte count and SHA receipts
accompany it. Later failure cannot erase a previously retained PNG. A retained
image alone does not imply its case passed, and visual approval remains pending.

## Resource consumers and clocks

Only one standard `xcode-27` Mac job is proposed, without a matrix, extra paid
service or added credentials. It performs one unsigned Debug build-for-testing
of the existing TouchColor scheme, then four selected UI invocations. The scheme
may compile its existing hosted test target; that target is never dispatched.
No Release archive, signing, companion platform, fixture app, Store operation,
Photos seeding, network data fetch or user Mac is involved.

It requires an initially idle disposable simulator host. Each exact model is
created fresh, read back with its unique owned name, UUID, type, runtime and
Shutdown state, and operated serially. Phone shutdown/delete and both readbacks
must finish before creating iPad. No pre-existing device is mutated. No failed,
late, ambiguous or cleanup-uncertain native operation is retried; the route
stops. Failure handling and final file admission are file-only. Disposable-host
teardown is the owner’s responsibility after failure.

One source/run-bound monotonic clock starts before checkout. Normal work ends at
2700 seconds and exporter/summary/source-command/owned-cleanup tails at 2940.
Every command must fit its full allowance plus 20 seconds before dispatch; grants
are never shortened and device clocks are not refreshed. Source scans are bounded
to 30 seconds; app inventories to 20 seconds, 4096 files, 8192 entries and 200 MB.
The capture step is capped at 52 minutes and the enclosing job at 60 minutes.

Fixed maximum command allowances, seconds:

- Source reads 15; Xcode and device inventories 30
- One unsigned Debug build 600
- Each device create 60/readback 30, boot 60/bootstatus 240, install 600
- Installed-app lookup 60, normal size and light appearance 60 each
- First UI command on each fresh device 600; second command 420
- Photo method body 180; history body and maximum test allowance 240
- Each export 45; finalized summary 30
- Owned shutdown/delete 45 each; each corresponding readback 30

The first test on *both* new devices retains the full 600-second cold-start
allowance. Worst-case summed maxima exceed the fixed work window; later work is
conditional on full admission and this does not permit another run. Root must
check global capacity and separately authorize the exact frozen public write and
job before execution. This local packet cannot assert that capacity is available.

The retained packet is capped at 40 MB, at most 256 regular files, each of four
fixed PNG names at most 8 MB, other files at most 1 MB, and command log tails at
64 KB. Empty real command logs are allowed; empty JSON/PNG/manifest files are not.
No xcresult, DerivedData, app bundle or unselected screenshot is retained/uploaded.
The workflow’s artifact step would publish only this bounded evidence after a
separately approved run, never directly to App Store Connect.

## Local verification and remaining gates

`python3 scripts/store_capture.py verify-source` checks source restoration.
`python3 -m unittest discover -s scripts -p test_store_capture.py -v` and the same
command with `python3 -O` check the capture-specific portable contract.

Native compilation, four actual cases, visual review of all raw images, and the
current App Store Connect screenshot slots remain unverified until separately
executed. The route is local-only and frozen for review first.
