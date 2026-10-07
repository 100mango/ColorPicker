# Fixed reset-only Mac scene control, local review candidate

## Scope and controlled input

This independent composition has sole intended parent
`ea9da854f4658b36a28a3b80f6f48e06185cfedb`, tree
`141bcec9a89e74ebf519b513a7042a2503fe84d4`. Its reference diagnostic is
commit `d238410a5a45818e20116e835669f1740a81eec2`, tree
`d014ad6c1e92c0f4ef965797964d181cc9fa750d`, run 37546669625.
The inherited explicit-English documentation describes that predecessor, not
qualification granted to this control.

The only controlled application-launch variable is removal of the explicit
English tuple `-AppleLanguages (en) -AppleLocale en_US`. The selected original
`testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail` still
launches once, with `--ui-test-reset`, the original isolated defaults suite,
diagnostic token and complete original setup, assertions and teardown. Its
method name remains unchanged to preserve exactly the same case and assertions.
Chinese and unrelated test setup remains unchanged. This control does not
qualify as explicit-English contact acceptance even if the case passes.

All 50 app/product source, resource, package and project/scheme files are
byte-identical to d238. Both instrumented Swift files, four first-hit scene
checkpoints, logger initialization, AppKit reads, scene structure, StateObject
identity, view hierarchy and observation limits are unchanged. There is no new
App hook, AX query, timer, activation, forced window, or second launch. The
original explicit-English controller, parser and workflow remain unchanged;
this branch does not execute them or the comparison/NSWorkspace executor.

The fixed new route is `codex/mac-scene-reset-only`, push only,
`.github/workflows/mac-scene-reset-only.yml`, one `xcode-27` arm64 job and one
original case. No dispatch, matrix, retry or unrelated platform is present.

## Necessary harness differences

- A separate closed reset-only receipt contract accepts exactly one ordinal-1
  original-case receipt with reset-only arguments, never either argument tuple.
  PID/token, source/run, time, destination, path and actual new-build hashes
  remain bound. The original parser still rejects reset-only receipts.
- One read-only Foundation runner-locale probe runs in the existing preparation
  phase before the single build. It reports only `Locale.current.identifier`
  and `Locale.preferredLanguages`, capped at 4,096 bytes. It imports no AppKit,
  reads no app, changes no preferences and launches no app. This host process's
  observation is separate from the app's effective locale.
- App language is derived only from the already-retained, identity-bound app
  failure hierarchy or the original exact contact-label assertion passing.
  Only owned menu strings in the single matching app subtree count. Foreign,
  ambiguous or missing evidence stays unknown. Effective app locale stays
  unknown; it is never inferred from the host or removed launch arguments.
- Test-only exact inverse normalization allows inherited source guards to
  verify the predecessor after undoing only the tuple removal. A new full UI
  source hash check proves all assertions and other UI test code unchanged.
- The shared budget adds one fixed 25-minute route identity without changing
  any previous value or accounting rule.

## Independent-build comparability

The reference artifact contains seven diagnostic JSON/text files and no app,
Mach-O, DerivedData or retained UUID. The old product cannot be reused. There
is no retained evidence establishing cross-run reproducible Debug bytes.
Therefore this is an independent build with identical app source/resource/
project inputs, exact Xcode 27.0 build 27A266a, macOS 27.0 build 26A428, arm64,
and identical build-for-testing argv. It is not asserted to be the same binary.

New executable/debug-library SHA256 values are retained and bound to the case's
receipt as before. Reference hashes and whether the new bytes equal or differ
are reported as observations only; a normal independent-build difference is
not a pre-test rejection gate. Reference UUIDs were not retained, current UUIDs
are not additionally collected, and their comparison is explicitly unknown.
This avoids adding a command or unsupported equality requirement. Independent
build/run differences remain a limitation of any causal inference.

Reference executable SHA256:
`c403365bf0daa56fff9af731650c4cf038efb26458c8d25b6fdfc746a2fba497`

Reference debug-library SHA256:
`5c693857e26821ba7cc8cab0610db8000e2b764906f82af24f3417f2f11f06af`

## Fixed clock and evidence budget

One 25-minute job, with the original clock beginning before checkout. Work is
1,020 seconds after the existing 30-second startup and 450-second reserves.
Preparation remains one immutable 500-second ceiling including preflight,
source hashing, Foundation probe, one build, product hashing and persistence.
The new locale probe is at most 20 seconds plus the original 20-second owned
cleanup, entirely inside those 500 seconds. The single build remains at most
420 seconds clipped to the same preparation ceiling. The sole test needs full
300-second command plus 20-second cleanup admission; its original XCTest case
allowance is 120 seconds. Preparation/test maxima remain 820 seconds with
200 seconds work headroom, never extra phase time.

The fixed plan has eleven commands: five original preflights, one locale read,
one build, one test, one summary, one existing-attachment export, one scoped
historical lifecycle query. Summary admission still rejects zero/multiple/
skipped cases, inconsistent exit/result/counts and out-of-command timestamps
before export. Exact receipt/product binding follows export without a new
validation phase.

Evidence remains 180 seconds: summary 20+20, export 20+20, historical query
26+4, leaving 70 seconds local headroom. Existing reserves stay cleanup 130,
evidence 180, validation 60, upload 60, overhead 20. One full validator and the
original final lightweight outcome guard remain unchanged in structure.
Capture ownership and uncertainty fences remain fail-closed. Original native
exit/assertion failure is retained; no failure is turned into success.

The app's original 1/5/10-second schedule, 10-second observation boundary,
24-record/12,288-byte total producer cap (8,192 bytes before the final reserve) and once-only scene checkpoints are unchanged.
No missing or late checkpoint establishes that execution never happened.
Historical query cap remains 512 KiB. Retained artifact cap stays 3,000,000
bytes; the one host-locale file is added within it. No AX attachment bodies or
other new payloads are retained.

## Interpretation and limits

A mapped window under reset-only inputs would favor a launch-input-dependent
explanation over an unconditional inability of this source/toolchain to build
a scene. It would not isolate AppleLanguages from AppleLocale, prove a product
fix, remove independent-build/run uncertainty, or satisfy explicit-English
contact/release acceptance. Continued zero windows would not prove the tuple
irrelevant to all launch sequences. An unknown/missing observation remains
unknown. Instrumentation or timing altering the outcome remains inconclusive.

Only local portable contract/fault tests and clean replay are claimed here.
This Linux executor has no Swift compiler/macOS SDK, so the Foundation probe,
UI compilation and native behavior have not been run. Public/native execution
requires a new exact-tree approval; the prior d238 approval is consumed.
