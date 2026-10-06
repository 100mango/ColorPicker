# Fixed Mac launch comparison: scheduling and evidence successor

This diagnostic is a separate observation-only lane. It does not change the app,
contact test, canonical collectors, canonical workflows, or release acceptance.
Publication and native execution require separate authorization. The exact source parent
is `cb5943730e128d6806f7b1b1b053e9e91ba5647a`, tree
`ad6cde09f96a54a87e5d0701a91cac074f658d94`. This successor changes only the
existing standalone controller, coordinator/validator, focused tests and this
document. All workflow, product, XCTest and shared-budget bytes are unchanged.

## Exact experiment

The dedicated push-only branch is `codex/mac-launch-comparison`; its unchanged
workflow is `.github/workflows/mac-launch-comparison.yml`. One standard
`xcode-27` arm64 disposable VM, macOS 27.0 build 26A428 and Xcode 27.0 27A266a,
builds the unchanged normal Debug app and UI test product once. It does not build
the sandbox configuration. It compiles a standalone public AppKit controller
without changing product target membership or adding signing/permissions.

The first route runs only the existing English contact testcase with
`test-without-building`, parallel testing disabled and the existing 120-second
case maximum. The original setup, contact assertions, fixture/defaults teardown,
and failure attachment behavior remain byte-identical. A final fixed post-upload
guard keeps a failed or unknown original contact outcome red in GitHub, even
when the observation comparison completed. A timely known failed
case (exit 65 and matching one-case failed summary) remains `failed`; it may
continue only with its exact existing lifecycle receipt and confirmed owned
host cleanup. A missing identity, unexpected command exit, timeout, cancellation,
late result or unknown host cleanup stops subsequent app work. Only the tightly
scoped historical-evidence exception below can run after the controller's own
host group has independently been confirmed stopped.

The second route makes exactly one public
`NSWorkspace.shared.openApplication(at:configuration:completionHandler:)`
request for the same path and reverified executable/debug-dylib bytes. A bounded
Security API inspection requests both signing and requirement information,
including the documented flag required for the entitlement blob, and distinguishes readable signing entitlements from a
successful inspection showing neither embedded entitlement representation.
API errors, malformed/unreadable or unsupported representations, or a true
App Sandbox entitlement are unavailable and stop before the contact test.
The same inspection is repeated inside the launch controller. No signing or
permission modification is attempted. This establishes declared signing state;
it does not independently measure inherited sandbox state on the standard runner.

The controller supplies exactly the requested arguments:

`["--ui-test-reset", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]`

It supplies only fresh owned `TOUCHCOLOR_TEST_DEFAULTS=TouchColor.mac-ui.<UUID>`
and `TOUCHCOLOR_MAC_LIFECYCLE=<UUID>` environment values. No arbitrary environment
is enumerated or copied. It requires zero running instances before the request,
then one exact returned process at the expected path. Substitution and prompts
are disabled. The ordinary defaults are checked (`activates=true`, `hides=false`,
`createsNewApplicationInstance=false`); no subsequent activation, reopen,
new-window operation, force termination, retry, additional XCTest, screenshot,
or accessibility query is added.

The callback only proves a process launch. Existing DEBUG app-owned lifecycle
logging is the sole product observation. The existing single passive timer is scheduled at callback + 10.5 seconds,
before the immutable callback + 12-second observation ceiling. Existing app-owned
census events finish by 10 seconds. The callback clock is captured once. Actual
timer entry and dispatch delay are retained; entry at or beyond the 12-second
ceiling permanently marks the observation incomplete. A known timer-dispatch
miss is distinct from a delayed or unknown in-flight app operation.

Once the timer enters, the already returned owned `NSRunningApplication` may
enter its one cleanup path, including after an observation miss. Its immutable
cleanup deadline is min(timer entry + 20 seconds, original controller deadline).
Every PID, bundle, path, executable and termination-state read is pre/post fenced
to that cleanup deadline; each identity value is checked before the next app
read, and the product bytes are reverified. Only after successful revalidation
and persistence may the controller call `terminate()` once. The only subsequent
app-property query is its bounded termination status. Missing/changed identity,
a late property, rejected or late operation, or failed/late persistence fences
all subsequent app calls. A late passive timer never authorizes another launch,
window query, activation or functional phase. All mutable state and app calls
remain on the main queue; late callbacks are rejected before reading their app
object.

## Budget, persistence and cleanup

A new closed `mac-launch-comparison: 25` budget identity is the only change to
shared `job_budget.py`. The canonical `mac: 40` identity and all other rows are
unchanged. The original startup margin (30 seconds), work pool (1020 seconds),
and reserves (cleanup 130, evidence 180, validation 60, upload 60, overhead 20)
remain intact.

The scheduling correction reviewed during local implementation explicitly
charges mandatory intermediate summary/export extraction to WORK, before the
second launch. Each extraction has a 20-second command maximum plus its original
20-second owned host cleanup allowance. These do not borrow the final evidence
reserve or return from evidence phase to work.

| Work component | Maximum including owned host cleanup |
| --- | ---: |
| Build, compile, inspect, source/toolchain preparation | 500 seconds |
| One XCTest command | 300 + 20 = 320 seconds |
| Required intermediate summary and attachment export | 2 × (20 + 20) = 80 seconds |
| Standalone controller | 92 + 20 = 112 seconds |
| Total | 1012 of 1020 seconds |

Only eight seconds remain at simultaneous maxima. This is admission capacity,
not a promise that those maxima or every phase can complete. Insufficient time
honestly leaves the second route unstarted. Full 320/112-second admission precedes
the test/control routes. Preparation uses one immutable deadline. Each command
is clipped to its original absolute phase/work deadline before persistence and
again immediately before spawn; capture receives only the remaining time.
Post-return and post-persistence checks never reset that deadline. The
controller retains the original 92-second ceiling, 60-second callback ceiling,
12-second observation ceiling and maximum 20-second owned cleanup. Late timer
entry consumes existing controller time; it does not extend or reset any global
deadline, and cleanup is clipped to the original 92-second ceiling. It receives
the coordinator's absolute monotonic deadline, which native validation must
confirm shares the system-uptime clock origin on this pinned Mac toolchain.

The existing bounded capture/owned-process-group primitives enforce finite
stdout+stderr acquisition and termination of only the spawned host group.
Any uncertain launch, test, capture, termination, persistence or cancellation
latches a source/run-bound stop record before further app work. No app query,
second launch, cleanup discovery or retry can follow that fence. Local retention
remains permitted. The only external exception is the existing single read-only
historical `log show` query below, after independent retained identities and
known owned controller-host cleanup have been reconstructed. It never reads a
live app property or discovers a process. The standalone controller uses the same durable
stop location. File and parent-directory fsync must succeed; persistence failure
is unavailable, never claimed durable. A terminal receipt remains in a
finalizing stage until its write is checked. A failed or late final write
invalidates any prior completion claim; failure-receipt persistence failure
removes the stale output rather than leaving a successful receipt available. The console emits one nonblocking atomic
line of at most 512 bytes with source/run/attempt/phase and honest durability.

The final host-only evidence phase has its own immutable contiguous 180-second
ceiling and does not consume the earlier 80-second intermediate work allocation.
It makes at most one fixed app/PID/token-scoped log query, with the original
30-second budget (including two two-second owned cleanup phases), 512 KiB raw
limit and 128 KiB projected limit. The packet cap remains exactly 3,000,000 bytes.
The earlier local proposal's 2 MiB figure was a documentation error, not a new
cap. The original workflow identity and budget value are unchanged. Raw output of
compiler/build/test commands is not retained; bounded byte counts and hashes
are kept. Only the exact original summary, manifest/identity receipt, standalone
request/receipt/caller inspection, source/phase state and scoped log bytes are
retained. Other attachments are explicitly omitted and remain runner-local.

## Evidence and interpretation

The standalone receipt is a separate closed `NSWorkspace` schema 2. It has no
XCTest test/case identity. The request retains its original schema 1. State and
report are schema 2; new-source receipts cannot omit any required field. The
existing fields retain their meanings, with absent not-yet-observed timestamps
explicitly null. Six fields distinguish the new facts:

- `observationScheduledMonotonic`: verified callback clock + 10.5 seconds
- `observationEnteredMonotonic`: actual passive timer entry, or null
- `observationLatenessSeconds`: max(0, entry minus scheduled clock), or null;
  this is dispatch delay, not just time beyond the 12-second ceiling
- `observationComplete`: entry strictly before callback + 12 seconds; false
  stays false even when owned cleanup succeeds; null means no retained entry
- `cleanupStartedMonotonic`: the same timer-entry clock when cleanup is admitted
- `operationUncertain`: an actual operation, identity, deadline or persistence
  fence; a known passive timer miss alone does not set it

`cleanupConfirmed` is true only after the owned app was observed terminated and
terminal persistence succeeded. It is false when cleanup was not confirmed
before a termination request, or null after an uncertain request/finalization.
`terminateRequests` records at most one admitted request; persistence can fence
before its actual call. `status=completed` requires on-time observation, confirmed
cleanup and no uncertainty. Late observation with successful cleanup remains
`status=incomplete`, reason `observation-scheduling-miss`; the controller exits
0, while the coordinator preserves the incomplete state and its own nonzero
result. An uncertainty has unavailable status and a durable stop fence.

The report's `comparison` contains the independently reconstructed observation,
app-cleanup and uncertainty facts plus `controllerHostCleanupConfirmed` from the
bounded capture receipt. These are distinct facts. A known host end does not
imply the app was cleaned up. Unknown host cleanup forbids the historical query.

Historical query eligibility requires the exact retained original contact
receipt and a timely independently verified ordinary callback, matching source,
run, product hashes, caller, arguments, PID, token and request hash. Every prior
command must have completed its original phase; the controller command must be
the exact owned path/arguments with a known stopped host group and retained end
clocks within its original outer cleanup ceiling. The sole query is the existing
fixed predicate for those two PID/token scopes, with its interval derived only
from retained request/result/end facts. It may retain records despite app cleanup
being false/unknown or an observation miss, but report status stays incomplete
and all flags remain. Missing identity or timestamps permits no query. The latch
is never removed. A persisted query attempt cannot be retried. Every raw event
is checked against PID/token/product/time before retention, so unexpected raw
output is not added to the packet.

The exact immutable predecessor receipt and report from cb594/run37391944166
remain historical unknown, accepted only under their original source and exact
retained byte hashes. Their absent timer-entry/dispatch fields are never filled
in. They do not authorize a query or become a schema-2 result. The predecessor
contact remains failed; its receipt ended about 0.608 seconds after the ceiling,
which includes failure persistence and does not establish exact dispatch delay.
No retained ordinary-route window records exist in that packet.

Only after independently validating these scoped facts does the diagnostic reuse
the existing passive event parser. Canonical collector
acceptance and its four allowed XCTest methods are untouched. Actual captured
summary/caller/query bytes and retained derived records are hash-bound. Final
validation reconstructs both routes and checks source-file, phase, command,
receipt and capture hashes; tampering cannot invent a positive observation.

- A positive app-owned visible workspace is a positive observation, even if
  other records are absent. It is not contact readiness or release acceptance.
- Zero-window classification requires the two actual timely app-owned censuses
  around one and five seconds plus their complete, unomitted stream prefix.
  Missing, late, or omitted required samples remain unknown. A late final record
  remains late and contributes no invented census. This does not prove absence
  of windows throughout the interval.
- XCTest zero samples plus a visible ordinary-launch workspace supports a
  route/context difference for these bytes, VM and order. It does not establish
  a platform bug or instrumentation as the sole cause.
- Both zero leaves causes beyond only the XCTest route. Both visible leaves the
  earlier cohort/order difference unresolved. Missing evidence remains unknown.
- The sequence is always XCTest then NSWorkspace on one VM. Normal test teardown,
  inherited launch environment, sequential order and system restoration state
  are residual confounders. These are not independently cold OS states.

## Verification and remaining native gates

Portable tests exercise the exact command/configuration, existing receipt
parsers, two-token/PID/product binding, missing/duplicate/wrong-path data,
sandboxed/unreadable caller reports, missing/error/late callbacks, deadline and
cleanup reserves, persistence latency, cancellation/unknown cleanup fences,
exhausted preparation, failed-case continuation, distinct receipt schemas,
source/phase/capture tampering, byte limits, omission/late-event handling, and
full-packet reconstruction. Added tests cover 10.5/11.9/12.0/12.6-second timer
entries, every delayed cleanup identity property, rejected/late termination,
expired global deadlines, each persistence checkpoint, permanent miss flags,
false/unknown app cleanup with known host cleanup, missing identity and unknown
host rejection, altered query scopes/ranges, late query output, and original
contact-outcome promotion. The scheduling model derives constants/property order
from Swift and pins its control-flow structure; it is still a portable synthetic
model, not execution of Swift or AppKit. Source assertions additionally fence public API
selection and callback-before-query ordering. These are not a native execution
claim and do not replace macOS validation of the actual controller.

Normal and optimized portable suite commands:

```
cd scripts
python3 -m unittest -v test_mac_launch_comparison test_mac_comparison_scheduling test_mac_passive_lifecycle test_job_budget test_budgeted_step test_bounded_process test_atomic_json test_retain_mac_evidence test_mac_workspace_launch_policy test_mac_only_repair_route
python3 -O -m unittest -v test_mac_launch_comparison test_mac_comparison_scheduling test_mac_passive_lifecycle test_job_budget test_budgeted_step test_bounded_process test_atomic_json test_retain_mac_evidence test_mac_workspace_launch_policy test_mac_only_repair_route
```

Native gates are intentionally unrun in this Linux/local-only review:
public API compilation on the pinned SDK; readable declared signing information;
ordinary caller behavior and main-run-loop delivery; matching monotonic clock
origin; exact build product layout; one unchanged contact summary/receipt;
zero preexisting instance; timely ordinary callback/owned termination; and
actual timely bounded app-owned log collection. Compilation, process launch,
artifact completeness and the original contact pass/fail are separate results.
No native workflow dispatch, remote write, publication or release qualification
is authorized by this document.

## Primary public contracts

- [NSWorkspace openApplication](https://developer.apple.com/documentation/appkit/nsworkspace/openapplication(at:configuration:completionhandler:)) and [OpenConfiguration](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration)
- [Arguments](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration/arguments) and [environment](https://developer.apple.com/documentation/appkit/nsworkspace/openconfiguration/environment), whose sandboxed-caller behavior motivates the signing inspection
- [SecCodeCopySelf](https://developer.apple.com/documentation/security/seccodecopyself(_:_:)) and [SecCodeCopyStaticCode](https://developer.apple.com/documentation/security/seccodecopystaticcode(_:_:_:))
- [SecCodeCopySigningInformation](https://developer.apple.com/documentation/security/seccodecopysigninginformation(_:_:_:)), including successful unsigned results and the need to validate signatures before trusting signing information
- [Entitlements dictionary](https://developer.apple.com/documentation/security/kseccodeinfoentitlementsdict) and [entitlements blob](https://developer.apple.com/documentation/security/kseccodeinfoentitlements), distinguishing absent entitlement representations from unsupported data
