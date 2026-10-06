# Fixed Mac launch comparison: local review candidate

This diagnostic is a separate observation-only lane. It does not change the app,
contact test, canonical collectors, canonical workflows, or release acceptance.
Publication and native execution require separate authorization. The source base
is `74ccaa93ae3f0cb5d0a63f6957460e9e8e576add`, tree
`c6bb5466a57dfd919b5dbd0edb3b58b7bf5a8683`.

## Exact experiment

The dedicated push-only branch is `codex/mac-launch-comparison`; its only new
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
late result or unknown cleanup stops the VM's diagnostic.

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
logging is the sole product observation. After an at-most-12-second passive
interval, the controller reverifies and calls `terminate()` once on the returned
owned `NSRunningApplication`; the only subsequent process query is its bounded
termination status. The timer is scheduled half a second before the immutable
12-second ceiling to allow dispatch, receipt persistence and byte verification;
late execution fails closed rather than extending the passive interval. All
state/app operations are serialized on the main queue; concurrent callbacks
only enqueue work. Late callbacks are rejected before their app object is read.

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
controller's 92 seconds includes at most 60 seconds to callback, at most 12
seconds passive delay and at most 20 seconds owned app termination. It receives
the coordinator's absolute monotonic deadline, which native validation must
confirm shares the system-uptime clock origin on this pinned Mac toolchain.

The existing bounded capture/owned-process-group primitives enforce finite
stdout+stderr acquisition and termination of only the spawned host group.
Any uncertain launch, test, capture, termination or cancellation latches a
source/run-bound stop record before further operations. Thereafter only local
persistence/retention remains; no new command, app query, second launch or app
cleanup discovery is attempted. The standalone controller uses the same durable
stop location. File and parent-directory fsync must succeed; persistence failure
is unavailable, never claimed durable. The console emits one nonblocking atomic
line of at most 512 bytes with source/run/attempt/phase and honest durability.

The final host-only evidence phase has its own immutable contiguous 180-second
ceiling and does not consume the earlier 80-second intermediate work allocation.
It makes at most one fixed app/PID/token-scoped log query, with the original
30-second budget (including two two-second owned cleanup phases), 512 KiB raw
limit and 128 KiB projected limit. The packet is capped at 3 MB. Raw output of
compiler/build/test commands is not retained; bounded byte counts and hashes
are kept. Only the exact original summary, manifest/identity receipt, standalone
request/receipt/caller inspection, source/phase state and scoped log bytes are
retained. Other attachments are explicitly omitted and remain runner-local.

## Evidence and interpretation

The standalone receipt is a separate closed `NSWorkspace` schema. It has no
XCTest test/case identity. Only after validating source/run/attempt, requested
arguments and two tokens, callback PID/path, both product hashes, caller signing
state, exact operation counts, fixed deadlines and known termination does the
diagnostic reuse the existing passive event parser. Canonical collector
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
full-packet reconstruction. Source assertions additionally fence public API
selection and callback-before-query ordering. These are not a native execution
claim and do not replace macOS validation of the actual controller.

Normal and optimized portable suite commands:

```
cd scripts
python3 -m unittest -v test_mac_launch_comparison test_mac_passive_lifecycle test_job_budget test_budgeted_step test_bounded_process test_atomic_json test_retain_mac_evidence test_mac_workspace_launch_policy test_mac_only_repair_route
python3 -O -m unittest -v test_mac_launch_comparison test_mac_passive_lifecycle test_job_budget test_budgeted_step test_bounded_process test_atomic_json test_retain_mac_evidence test_mac_workspace_launch_policy test_mac_only_repair_route
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
