# One unsigned universal Mac archive, proof only

This candidate adds only archive verification tooling to the exact qualified
Chinese-contact commit68c8e09fef5187d549e5e032a5b083a04d0c1c79,
tree1635d893d34af37daa28afc6c31bcec94380e8fe. The existing50 app/product inputs,
project, normal scheme, entitlements and all UI code remain unchanged.

74cc/run37385172706 already passed genuine arm64 and x86_64 Release builds.
Current48 inputs match that source byte-for-byte; the other two Swift files have
identical Release projections. Those build and functional results are preserved.
The old command was build, not archive; it retained proof, not an xcarchive.
This route fills only the archive/metadata/universal-binary/dSYM observation.
It does not rerun hosted/UI/accessibility suites or capture Store screenshots.

Fixed branch codex/mac-unsigned-archive, push only, one standard xcode-27 job,
20-minute hard timeout, attempt1 only. One xcodebuild archive uses the existing
TouchColorMac Release scheme, generic macOS destination, arm64+x86_64,
ONLY_ACTIVE_ARCH=NO and CODE_SIGNING_ALLOWED=NO. No Apple account, credentials,
provisioning update, distribution signing, native launch or export/upload to
Apple is involved. The full archive stays on the disposable VM and is never
included in the public artifact. Signing will rebuild from frozen source.

The command and upload clock machinery is adapted from the reviewed original
unsigned-iOS archive proof. Pure Mach-O parser functions are copied unchanged
and locked by source hashes; Mac-specific checks cover Contents layout, macOS
platform, two supported CPU slices and matching two-architecture dSYM UUIDs.
The dSYM's version fields are observations, not invented equality gates.

A generic bounded catalogue runs before semantic checks. It records all paths,
types, sizes, file identities/hashes and internal symlink targets, then persists
that full catalogue. Standard Assets.car, .icns and localization resources are
not tested against a guessed filename whitelist. Escaping links, nonregular
entries, unexpected nested apps/tests/provisioning payloads and malformed Mach-O
remain rejected with an actual offending path. Proof includes the catalogue on
semantic failure; no artifact shape is silently reclassified as an app bug.

Bounds:2048 entries,1GiB aggregate bytes,1MiB inventory metadata,30 seconds per
snapshot;64MiB per Mach-O parse;64KiB per plist;2MiB public JSON proof. Catalogue
and source/clock survive report-size fallback. The proof-only artifact contains
report.json, never the app/archive/dSYM binaries or signing materials.

Clock offsets from the owned script start:prepare180s, archive end800s,
proof end950s, final source/report end980s, evidence/upload end1040s,
finalization end1060s. The single archive command is capped600s plus20s owned
cleanup inside its620s ceiling. Proof has150s, source/report30s, upload60s and
post-upload finalization20s; no retry or reserve borrowing. Checkout is capped
one minute inside the20-minute job, leaving at least80s job headroom beyond
checkout+1060s. Capture proves only the owned client/process-group closure,
not the lifetime of independent Xcode system daemons.

Native compilation/archive is unrun during local preparation. Local source,
format/fault tests and clean replay do not constitute signing or Store acceptance.
