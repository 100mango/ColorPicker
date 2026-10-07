# Fixed Mac single-contact scene diagnostic, local review candidate

## Source and execution identity

The final composite has exactly one intended parent commit:
`ea9da854f4658b36a28a3b80f6f48e06185cfedb` (tree
`141bcec9a89e74ebf519b513a7042a2503fe84d4`). It includes the previously reviewed
checkpoint snapshot `f2211e7f70aa5cbc531aecacfa95a1c54e974956` unchanged in both
instrumented Swift files and the closed checkpoint parser. The independent
local candidate/replay and frozen manifest establish the full composition.
No synthetic commit, remote ref or native run is created by local preparation.

The new, closed proposed runtime identity is:

- Repository: `100mango/ColorPicker`
- Branch: `codex/mac-scene-checkpoints`
- Workflow: `.github/workflows/mac-scene-checkpoints.yml`
- Event: push only; one job `single-contact`, one `xcode-27` arm64 runner
- macOS 27.0 build 26A428; Xcode 27.0 build 27A266a
- Job timeout: 25 minutes; artifact cap: 3,000,000 bytes
- Test: only `TouchColorMacUITests/TouchColorMacUITests/testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail`

The depth-2 checkout makes the actual sole parent visible to the first bounded
Git command. HEAD, parent, clean source, OS, architecture and Xcode are checked
before a build. The source/run/attempt/workflow tuple and all execution/parser
source-file hashes are retained. The old comparison branch/workflow/controller
remain unchanged and are never called by this entrypoint. Other existing push
workflows have different fixed branches, so this new branch selects only this
single standard-Mac job. There is no matrix, dispatch selector or retry route.

## Exact operations

`scripts/mac_scene_diagnostic.py` owns a closed ten-command plan:

1. Read exact HEAD and sole parent with one Git command.
2. Verify the checkout is clean.
3. Read pinned macOS build.
4. Read arm64 architecture.
5. Read pinned Xcode version.
6. Run the unchanged TouchColorMac Debug scheme's build-for-testing exactly once.
7. Run the original English contact case exactly once, test-without-building.
8. Read the one completed xcresult summary.
9. Export its existing attachments on the disposable runner.
10. Query only the original app's retained PID/token/time-scoped lifecycle log.

Before step9, local summary admission requires exactly one non-skipped,
non-expected-failure case, pass/fail counts and result consistent with the original
native exit, and finite start/finish times inside that test command's wall-clock
interval. An invalid summary stops before attachment export. This adds no command
or phase; complete PID/token/product/receipt validation still runs after export.

Steps 8–10 require the prior native command to have returned within its absolute
clock and the bounded capture to have confirmed that its owned host process
group stopped. The original XCTest assertions, exact app path, hashes, English/
reset arguments, fixture setup and teardown are unchanged. Its existing failure
screenshot/AX output remains original test behavior; the driver adds no screenshot,
AX read, process enumeration, app activation, timer, window creation or launch.
The original test's application teardown is not relabelled as an independently
measured process-termination receipt.

Only pure, already reviewed product/receipt/serialization helpers are imported
from mac_launch_comparison.py. Its Coordinator, run, control, evidence and main
entrypoints are never invoked. No NSWorkspace controller is compiled or run.
No project generation, app-source repair, StateObject change or iOS/archive
change is included. The shared budget file adds exactly one fixed 25-minute
identity; all previous rows and reserve logic remain byte-equivalent after
removing that one literal addition.

## Immutable clocks and reserves

The original job clock starts before checkout and is never reset.

- 1,500 seconds hard job time minus 30-second startup margin and 450 seconds of
  existing reserves leaves a 1,020-second work pool.
- Preparation: one immutable maximum 500-second ceiling, including every
  preflight/build capture, source/product hashing, persistence and owned cleanup.
  The build command itself is capped at 420 seconds and clipped to that ceiling.
  Preparation subcommands retain their existing 20-second owned cleanup reserve.
- XCTest: full admission of 300 command seconds plus 20 seconds owned host cleanup
  is required before spawn. The actual XCTest case still has its original
  120-second allowance. No clipped partial test admission or repeat is allowed.
- Preparation plus test/cleanup maxima total 820 seconds. The work pool retains
  200 seconds of headroom; headroom never extends any individual phase ceiling.
- Evidence: one separate immutable 180-second phase, beginning before state/
  source revalidation. Summary is at most 20+20 seconds; attachment export at
  most 20+20; the single historical query at most 26+4. These total 110 seconds,
  leaving 70 seconds for bounded local parsing, hashing, retention and persistence.
  Each command is pre/post fenced to both its own absolute deadline and this
  same evidence ceiling. Initial hashing cannot reset the evidence clock.
- Existing tail reserves remain cleanup 130, evidence 180, validation 60, upload
  60 and overhead 20 seconds. The workflow checks a full 60-second upload reserve.
- The full packet validator runs once inside its reserved 60 seconds. A durable
  attempt is written before validation. A tiny source/report-hash-bound outcome
  receipt is written only after successful validation, and all writes finish
  before that original deadline. Failed/late final persistence removes the
  outcome receipt and leaves the attempt, so it cannot restart a new allowance.
- After upload, the final status guard does only capped receipt/report reads and
  hash checks, pre/post fenced to at most the original 20-second overhead and
  hard job deadline. It does not run a second unbudgeted full validation.

Every external command attempt is persisted before spawn. Time spent persisting
is subtracted from the original grant. Post-capture and post-persistence checks
cannot restart clocks. Deadline comparisons use the original absolute sums,
avoiding false under-admission from floating-point subtraction roundoff.

## Stop conditions and retained meaning

Timeout, cancellation, unknown host cleanup, late return, failed persistence,
wrong source/product/identity, unexpected command exit or exhausted admission
fences all subsequent process work. Confirmed cleanup after a timeout does not
authorize another process command. No retry, alternate launch, cleanup discovery
or generic scheduling/recovery framework is introduced. Stale state, stop latch,
report, validation attempt/outcome, result or upload directory blocks a new run.

A natural, timely exit 65 is a known case result only after the unchanged summary
and original lifecycle receipt prove exactly the selected assertion-failed case,
its source product, PID/token and result interval. It may then retain diagnostic
evidence, but the final workflow stays failed. Exit 0 likewise needs the exact
one-case passed summary; instrumentation making the failure disappear remains
causally inconclusive. `acceptance` is always false and the report explicitly
states that this is no repair or release qualification.

Unknown or late case completion permits no summary/export/query. It can retain
only bounded local incomplete-state metadata. If a later query fails, already
validated timely case summary/identity remain distinguishable from unavailable
checkpoint evidence. Query bytes are retained only after every log envelope is
validated against that exact identity/product/time scope. Raw compiler/test
stdout, unrelated logs and additional XCTest attachments are not uploaded.

The maximum payload contains state, optional stop latch, exact case summary,
attachment manifest, one original identity receipt and scoped query stdout/stderr.
All retained files have exact byte counts/hashes. The independent validator
reconstructs command order/argv, admissions, phase clocks, source files, original
case result, receipt correlation and checkpoint projection. The retained report
end cannot predate any retained evidence-command completion.

The producer remains the reviewed f221 version: four process-wide first-hit
metadata checkpoints, no added AppKit census, original one/five/final-ten-second
callbacks, 23+final records and original 4,096/8,192/12,288-byte producer limits.
Original 512-KiB raw and 128-KiB projected capture limits remain unchanged.
Missing or budget-omitted checkpoints stay unknown; no window/readiness fact is
inferred from a logging gap. Existing Mac audit and release blockers remain open.

## Local checks and unrun native gate

Targeted tests cover fresh runner directories; depth-1 versus depth-2 local Git
fixtures; fixed branch/source/parent/command selection; exact f221 Swift/parser
bytes; original Release projections; immutable clock/admission/persistence faults;
closed and uncertain native outcomes; no query after uncertainty; wrong receipt
product, unknown/foreign query output and stale artifact rejection; independent
packet mutations; failed UI promotion; post-rename fsync failures; single validation
attempt and lightweight source/hash-bound final outcome. Synthetic runners never
execute native commands. Full related portable suites and a clean exact-ea9 patch
replay are recorded in the freeze packet.

SwiftUI/AppKit compilation, actual Xcode execution, native checkpoint emission,
observer effects and the original contact result remain unrun. Publication and
that one native job still require explicit approval outside this local review.
