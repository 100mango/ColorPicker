# TouchColor native-platform milestone

This is an implemented **native macOS** vertical slice under verification, not a claim of complete six-platform support or App Store readiness.

## Source preservation

- Isolated implementation began at repaired iOS commit `0d4c13ef4f43f5c3be2f7a25c5599f0107975480`.
- Synchronized the narrow iOS layout/permission-test change `47a65e22eae6517e35d5e1017973e07d159da876`. The iOS owner is still validating its latest test harness; final integration evidence remains pending.
- Original `com.mango.touchColor` iOS identity, iOS 15 minimum, Objective-C interfaces, camera/capture-generation behavior and all existing iOS tests remain intact.
- `Packages/ColorCore` is repository-local. Foundation-only `ColorDomain`, CoreGraphics/ImageIO `ColorRaster`, and Foundation `ColorPaletteLegacy` have independent tests. The existing iOS implementations remain the reference until direct cross-language equivalence is verified.
- No SwiftData migration, automatic cross-device sync, palette sorting/deduplication, or silent data truncation. `colorArray` and the once-only `colorArrayRecoveryBackup` retain their exact legacy meanings, in each app's local container.

## Native macOS workflow

`TouchColorMac.xcodeproj` builds a macOS SDK executable, not Catalyst. Proposed minimum is macOS 13. Each native window owns its source, marker and pending import; the local ordered palette is shared across windows. Source/selection state does not leak between windows.

Open native files, choose Photos, drag/drop files or image data, and paste images or file URLs. Sample by pointer, arrow key or accessible one-pixel controls. Zoom spans 1–100× with AppKit scrolling/trackpad magnification. Numeric hex/RGB and a marker refer to the same top-left normalized point. Save duplicate palette colors, copy/delete individual entries, export an ordered JSON array, and reopen it by explicitly appending. Export full-size, orientation-normalized PNG. Cancelled, missing or corrupt imports keep the current image unchanged.

ImageIO normalizes all eight EXIF orientations at the original largest dimension, with a strict full-dimension check; sampling never uses a reduced preview. Samples convert to sRGB and composite transparency on white, with interpolation disabled. Unsupported/broken input fails visibly. A 100-megapixel / 128 MB encoded-image safety limit rejects rather than silently reduces huge images. Import decoding is serial and generation-gated; pending work is cancelled when superseded. Export snapshots the selected full-size image.

The original 1024-pixel marketing icon is repackaged unchanged. Privacy is a native offline copy of the already-approved bilingual policy, with the original published policy/contact links. No new compliance claim or remote backend is added.

## Verification and explicit remaining gates

Run `python3 scripts/generate_mac_project.py`, `swift test --package-path Packages/ColorCore`, then the native Mac shared scheme. The single coordinated public `xcode-27` job pins Xcode 27.0 (27A266a) and macOS 27.0 (26A428), builds Release arm64, separately attempts x86_64, checks Release for DEBUG seam leakage, runs app-hosted XCTest and native UI workflows, and retains at most 20 MB of evidence for three days. Exact passed/failed results will be recorded after CI executes. No local Swift/Xcode compiler is installed in the Linux executor.

Synthetic fixtures live only in test targets. Unit tests verify real asymmetric pixel output across all orientations, alpha, wide-gamut conversion, full source dimensions, output reopen, malformed palette backup, duplicate order and async import generations. UI tests use actual files/pasteboard/native Open and runtime pointer sampling, never a fixture-only application.

Not completed: native camera adapter/hardware checks, Mac signing/sandbox/store resources, final iOS-owner synchronization and direct UIKit-vs-package equivalence, expanded import/export/window UX tests, iPad/Watch/TV/Vision platform slices. x86_64 compilation and runtime are separate gates; no Intel runtime claim is made. XCTest/OS security denials are reported, never worked around by modifying privacy databases. No Store record, identifier, capability, entitlement or signing resource was created or activated.
