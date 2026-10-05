> Historical source-admitted component record. The proposal-only driver/budget wording below is superseded by review/WATCH-CROWN-RUNNABLE-REVIEW.md. The canonical full Watch job remains 45 minutes; only the separate diagnostic identity is 25 minutes. Native execution is still unrun.

# Watch Crown control: local review packet

Status: local implementation for review only. No publication, workflow dispatch, simulator/device run or native test outcome is claimed. Frozen input tree: `914d82a9b8e8f10a86c495c1547eb4b2f55f1b9a` (`install-lifecycle-cohort-v3-next`; parent verified public commit `1410ed01f0d153be79cbd688c3385320670d7367`). The original input and the separate Vision candidate are not edited.

## Product observation

`WatchHome` receives only DEBUG lifecycle and public `palette.objectWillChange` / `transfer.objectWillChange` notifications. A plain MainActor enum owns four fixed UInt32 counters and four distinct omission counters. No property wrapper, model mutation, view ID, focus request, Crown binding, layout modification, timer, task, or new transfer activation is added. Observation is enabled only for the exact existing cold test case name. Each channel retains its first 4/4/8/8 events plus one first-overflow record, at most 28 records of 512 bytes. JSON includes sanitized case, process PID, system uptime and all counters. The host retains the OSLog timestamp for matching the existing cold geometry timeline. The existing log collection call is reused, with the same subsystem, timeout and lookback.

The counters describe notifications delivered to this subscription, not all publisher activity. Subscriptions may be recreated with SwiftUI's lifetime, and system logging can omit records. The final retained count is explicitly a lower bound; no termination flush is installed. First-overflow and later lifecycle records contain separate accumulated omissions, but a stationary failing cold test may terminate without a later lifecycle snapshot. Neither a quiet retained trace nor lack of visible focus events proves that no transient event occurred. Timing perturbation from DEBUG subscriptions/logging remains a measurement limitation.

The entire existing `WatchWorkflowTests.swift`, including actual cold Home and real RGB Crown methods, is byte-identical. The actual cold method still allows exactly the existing twelve downward `-0.1` calls, requires Privacy to become hittable, taps it, and verifies the real destination. No expected-failure wrapper, skip, assertion replacement, touch fallback or result alias is introduced. Product Release Swift projection is unchanged; native Release binary verification remains unrun.

## Isolation decision

An in-product environment-flag route is rejected: `TouchColorWatchApp` always constructs palette and transfer StateObjects and the latter activates WatchConnectivity. Instead a separate DEBUG-only app/project compiles only immutable static control content, with a separate bundle, scheme and UI target. It links no product sources or packages and does not instantiate, observe or mutate palette/transfer objects. It has no connectivity session, editor, custom Crown listener or focus modifier. Existing product App and project generator behavior are unchanged apart from including an empty-in-Release diagnostic source.

The control has its own test identifier and process launch. It checks initial top/offscreen geometry, captures exactly six Crown snapshots around exactly three `-0.1` rotations, and optionally measures one native touch drag with two separately labeled snapshots only if stationary. Touch cannot satisfy the Crown assertion. Strict diagnostic Crown status remains separate from required actual cold status. A generic static list is a comparison with different content, so motion differences narrow hypotheses rather than identifying a causal product fix.

## Proposed run scope and budget

One standard `xcode-27` VM, one observed smallest watchOS 27 profile (40 mm in the retained prior inventory), normal text, same Watch UDID/toolchain, three sequential method invocations. Original cold, isolated static, unchanged RGB. No system-largest-text lane, second size or all-platform rerun. There are no retries or runner upgrades.

Important source correction: the frozen full Watch workflow and `job_budget.EXPECTED_MINUTES['watch']` are **45 minutes**, not 25. They remain unchanged. The requested diagnostic is a distinct **25-minute proposal**, with 30 seconds startup margin and the existing 450-second aggregate cleanup/evidence/validation/upload/overhead reserves. This leaves 1,020 seconds maximum work. The proposed phases sum to 990 seconds and leave 30 seconds unallocated. Every method phase preserves at least the full 120-second execution allowance plus 60 seconds for launch; the unchanged RGB phase is 180 seconds, not 120. This is an admission ceiling, not a promise those builds/launches will fit. A dedicated source-bound budget registration and bounded driver still require implementation/review before any launch; the inactive workflow contains an unconditional safety stop. Reusing the full Watch identity with a false 25-minute environment is forbidden because its existing validator correctly rejects that mismatch.

All new structured observations share a 32 KiB ceiling (16 KiB Home, 16 KiB static); retain them inside the existing 1,200,000-byte normal Watch evidence cap, without widening it. Snapshots/timestamps/PIDs, actual method summaries, omission counts, toolchain/profile/source identity and cleanup proof are mandatory. If required evidence is missing or its reserve is exhausted, the row is incomplete. Ordinary Crown assertion failures stay failures while independent controls may continue only after verified cleanup and admission within the remaining budget.

## Interpretation and stopping point

- Static moves, actual stationary, model notifications observed: supports investigating product publishing/invalidation; does not prove a writeback loop.
- Static moves, actual stationary, quiet retained model trace: examine actual composition/routing, with the trace limitations above.
- Both Lists stationary, real RGB passes: narrows to List/scroll-focus/runtime delivery. Any later explicit-focus comparison needs separate review; no production focus change is made here.
- Crown controls all fail: investigate automation/device delivery before changing product behavior.
- Native touch moves: establishes separate touch scrollability only. It cannot turn either Crown result green.

Existing cold expectation and broader release gates remain required. No run has occurred, and no Crown regression is declared fixed.

## Primary API references

- [Apple: onReceive(_:perform:)](https://developer.apple.com/documentation/swiftui/view/onreceive(_:perform:))
- [Apple: ObservableObject.objectWillChange](https://developer.apple.com/documentation/combine/observableobject/objectwillchange)
- [Apple: rotateDigitalCrown(delta:)](https://developer.apple.com/documentation/xcuiautomation/xcuidevice/rotatedigitalcrown(delta:)) (negative means downward, independent of wrist orientation)
- [Apple: native coordinate press and drag](https://developer.apple.com/documentation/xcuiautomation/xcuicoordinate/press(forduration:thendragto:withvelocity:thenholdforduration:))

Apple's indexed official documentation was reviewed. Linux has neither Swift nor Xcode; exact watchOS compilation, actor diagnostics, accessibility hierarchy and runtime control movement are still native proof gates.

### Exact future budget integration (proposal, not installed)

The smallest source change for a future driver is a distinct `EXPECTED_MINUTES['watch-crown-control'] = 25` entry. Do not alter `EXPECTED_MINUTES['watch'] = 45`, its rows, or `RESERVES`. A dedicated driver must declare `TOUCHCOLOR_JOB_PLATFORM=watch-crown-control` and lane `watch-crown-control-smallest`; it must not enter the existing full native-platform or native-text dispatch paths. Capture monotonic and wall starts in the first workflow step before checkout. After checkout, initialize the existing `JobBudget` record against the exact admitted SHA/run ID and these original timestamps. Its hard deadline is the minimum of wall and monotonic start + 1,500 - 30 seconds; work admission subtracts the unchanged 450-second tail. Every setup/build/install/test/capture command uses the existing bounded process groups and requests admission at its declared phase, with its full minimum rather than shrinking a required test allowance. No new timestamp may reset the clock between phases. A latched unconfirmed cleanup bars all subsequent work. The outer GitHub job also has an absolute 25-minute timeout. This dual enforcement is required in the independently reviewed future driver; the present proposal deliberately cannot run it.

## Resume adversarial review and freeze, 2026-10-05

The existing candidate was inspected in place and preserved. The resumed review made no product/UI implementation change. Two review gaps were corrected:

1. The inactive budget proposal assigned the RGB invocation only 120 seconds including launch. This conflicted with preserving its full 120-second test allowance plus the existing 60-second launch allowance. Its proposed phase is now 180 seconds, with 990 total work seconds and 30 unallocated seconds inside the same 1,020-second work ceiling. A regression assertion requires all three method phases to keep that minimum. No active workflow, job-budget registration, timeout or reserve was changed.
2. A source-contract test searched for `crownSnapshots < 6` as a substring, which also accepted `< 60`. It now matches the full guard boundary. Navigation-before-movement guards now assert their required source fragments before checking their order, producing a clear failed assertion for a removed guard.

Nine destructive mutations applied only to disposable copies were all rejected: changed existing cold-test file, Release title/layout change, observable logger storage, reversed Crown sign, touch overwriting Crown status, expanded snapshot allowance, omitted navigation stability check, shortened RGB launch budget even with balanced totals, and moving the proposal into the active workflow path. These are portable source/mutation guards, not native behavior or Swift compilation proof.

Final portable validation:

- Existing workflow aggregate: 472 tests passed.
- Existing optimized workflow aggregate: 269 tests passed. This smaller configured suite does not itself include all Crown checks.
- Explicit focused Crown/Watch/runtime-pair/failure-continuation/budget set: 92 passed normally and 92 under `python3 -O`.
- Actual static-control C geometry: compiled/executed by five tests using C11, strict warnings and UBSan, in both explicit focused modes.
- Existing evidence guard: 21 synthetic boundary checks passed.
- All five original project generators and the new isolated-control generator: rerun with no file drift. Native localization coverage passed; 87 script ASTs and both shell scripts parsed.
- All five existing Watch product Swift Release projections match the frozen source; the new Home diagnostic projects to empty. This is source-level exclusion, not an Xcode Release binary result.
- The entire existing Watch UI-test file, product App, both active workflows, `job_budget.py`, and original Watch project generator match the frozen base bytes. The original index and all prior work were preserved.

The exact local tree, per-file hashes, patch hash and clean replay result are retained in the sibling manifest and freeze record. The packet is based on frozen tree `914d82a9b8e8f10a86c495c1547eb4b2f55f1b9a`; it is not integrated into the separate Vision+Mac successor. Both candidates touch `scripts/test_extra_platforms.py`, so any later combination requires explicit integration review and revalidation. The original proposal/evidence copies are retained unchanged as historical source inputs.

Verdict: the local implementation/review packet is ready for parent source review. This verdict does not admit publication or a native diagnostic. Linux has neither Swift nor Xcode. Exact watchOS 27 compilation, Swift actor/API compatibility, standalone Watch installation, runtime accessibility identities, top/offscreen geometry, Crown/touch motion and Release binary exclusion remain unrun. Before native execution, a distinct 25-minute source-bound budget registration, bounded sequential driver and reviewed evidence/status validator are still required, followed by separate exact-source/capacity admission. Any absent or incomplete measurement remains inconclusive; the original cold assertion remains required.
