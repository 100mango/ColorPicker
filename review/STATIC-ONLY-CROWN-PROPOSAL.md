# Static-only fresh-job Crown diagnostic

Status: LOCAL PROPOSAL ONLY. No implementation, publication, workflow dispatch, simulator command, or native execution is included. This document is the only new file.

## Decision and evidence

Use a new, dedicated `codex/watch-static-crown-diagnostic` branch, descended from published `e4180a23b73a2c455100cfb4143e30ad6b720103` (tree `e55a70b27a38077330c6ab88d215b949d2854ada`). Add a dedicated push-only workflow and narrow the existing diagnostic Python files on that branch to one fixed case. Do not add a selectable mode, arbitrary method selector, matrix, fallback, or continuation of an old job.

Run only:

`TouchColorWatchCrownControlUITests/WatchStaticCrownControlTests/testStaticListDigitalCrownThreeRotations`

The existing static app and test need no changes. The test already checks the product bundle is `.notRunning` before launching its separate app. A fresh owned Watch can satisfy that check without building, installing, launching, terminating, or first testing the product. Do not replace this assertion with a receipt boolean or add a product termination to make it pass.

Why this is a new measurement:

- `CROWN-11A6AD-TERMINAL.json`: run `37325045737` genuinely executed cold Home XCTest for 92.804 seconds, delivered 12 negative Crown calls, and failed the original privacy-target hittability assertion. The subsequent 3-second termination timeout fenced both controls. Logged snapshot starts do not establish retained frame contents or movement.
- `CROWN-E4180A-TERMINAL.json`: run `37329754325` on the current source never reached XCTest. Watch boot returned raw zero after 195.681 seconds against its 180-second bound, causing an uncertainty fence. No result from this run supersedes the earlier cold failure.
- The simple static control has never executed. The previously passing canonical `da9570` RGB case is a different test, source, and job; its success is background evidence, never an input result for this job.

Keep delta `-0.1`. Apple's [XCUIDevice contract](https://developer.apple.com/documentation/xcuiautomation/xcuidevice/rotatedigitalcrown%28delta%3A%29?language=objc%2Cobjc) defines negative values as downward scrolling independently of Watch orientation. The RGB test's `-0.25` remains unchanged and is not scheduled here.

The local inspection verified all 395 tracked file contents against `watch-crown-retain-cleanup-manifest.json`. The inspected directory is `watch-crown-retain-cleanup-next`; its local Git HEAD is the preparation baseline, not the published e4180a commit. The manifest/verified published tree, not that local HEAD label, defines the proposed parent content. No AGENTS.md or checkout-local skill files were found in the inspected scope.

## Exact source and workflow delta

Prepare any later implementation in a separate `watch-static-crown-only-next` candidate directory, leaving the Mac/adaptive/directMini work untouched. Proposed runtime/source inventory is exactly four paths:

1. ADD `.github/workflows/watch-static-crown-control.yml`.
   - Name: `Static-only Watch Crown diagnostic`; job/lane: `watch-static-crown-control-smallest`.
   - Push only to `codex/watch-static-crown-diagnostic`, with exact repository/ref/event job guard; no dispatch, PR trigger, matrix, or automatic rerun.
   - Reuse `xcode-27`, exact DEVELOPER_DIR, smallest/normal, 25 minutes, contents-read permission, credential-free checkout of `github.sha`, pinned checkout/upload actions, three-day artifact retention, cap guard, and original clock stamp before checkout.
   - Reuse concurrency group `touchcolor-watch-crown-control`, `cancel-in-progress: false`, so the two diagnostic workflows cannot run concurrently in that group. This is not capacity approval.
   - Existing driver and validator entrypoint filenames are reused. Label their steps explicitly one-case/static-only. Artifact name becomes `watch-static-crown-smallest-${github.sha}-${github.run_id}-${github.run_attempt}`.
2. MODIFY `scripts/watch_crown_contract.py` on this new branch only.
   - Bind the new ref, workflow path, lane and fixed `diagnostic_scope = static-list-crown-only-v1`.
   - `METHODS` contains only the unchanged `isolated_static` dictionary. `PHASES` is exactly `preflight:30, builds:240, setup:600, isolated_static:180`.
   - Retain the existing budget platform `watch-crown-control` and its 25-minute registration. It names the shared resource envelope; the exact lane/ref/workflow/scope identifies the distinct diagnostic. No `job_budget.py` change or new budget row is necessary.
   - Preserve exact static test argv, source/workflow SHA binding, profile/toolchain binding and per-case scheduling reconciliation. No runtime switch accepts the old three-case sequence.
3. MODIFY `scripts/run_watch_crown_control.py`.
   - Invoke only `generate_watch_crown_control_project.py`, one static build, one static fingerprint, and one static method. Narrow runner IDs and console case labels to `static`; do not accidentally label the singleton `cold` through the old positional zip.
   - Remove product-only frame collection and Home OSLog extraction from this branch's run. Do not emit empty or fabricated cold/Home/RGB evidence.
   - Keep static marker retention in its existing position: after the owned test process/reader returns, before summary extraction or app cleanup. Keep report persistence, original command exits and incomplete/failed distinctions.
   - Reuse setup, `phase`, `run`, admission, durable uncertainty latch, owned process cleanup, safe evidence retention, static `stop_apps`, device cleanup, source/product fingerprint checks and single static result export. No new native operation is required.
   - Console boundaries become preflight/builds/setup/isolated_static/cleanup/evidence/final. Keep the current per-record 512-byte and total 4,608-byte maxima; seven eligible boundaries use less than the old ceiling. The mirror stays advisory/nonblocking.
4. MODIFY `scripts/watch_crown_result.py`.
   - Require the new fixed lane/ref/scope and exactly one static case, phase, product fingerprint and runner identity; reject any extra/repeated/unassigned test invocation.
   - Retain the static half of existing observation validation, every exact command/lifecycle/summary/test-tree/source/device/time/hash/cleanup check and the setup-event validator. Do not require excluded cold/Home files.
   - Reconcile the static marker with the exact XCTest outcome: a qualifying pass requires three calls, `moved_downward`, no failure reason/omission/error, and the matching genuine passing lifecycle/summary/tree/exit. Touch can never satisfy this condition. A genuine stationary Crown failure remains failed; missing evidence, interrupted execution, or uncertain cleanup prevents completeness.
   - Output must identify the one-case scope even on validator exceptions or validation-write failure.

The original `.github/workflows/watch-crown-control.yml` remains byte-identical and only listens to its original branch. Canonical Apple/ UIKit workflows also remain byte-identical; their push filters do not match the new branch. Do not push the narrowed Python files to the old Crown branch or a canonical branch. Using the old branch instead would save one workflow path but silently replace the meaning of its historical job name and artifact stream; it is not recommended.

Planned portable test edits: `scripts/test_watch_crown_driver.py`, `scripts/test_watch_crown_result.py`, `scripts/test_watch_crown_console.py`, `scripts/test_watch_crown_setup_allowances.py`, `scripts/test_watch_crown_setup600.py`, and `scripts/test_watch_crown_simulator_fence.py`. Adapt their active fixtures/expectations to the fixed singleton; preserve historical failure receipts as historical cases rather than deleting their safety lessons. Add `scripts/test_watch_static_crown_scope.py` for the new exact workflow/scope/frozen-source inventory. Other setup-event, target, packet-invariant and shared budget/process tests should remain applicable unchanged. Any further required source path is a reviewable scope change, not an implicit permission to broaden this proposal.

No Swift, header, generated project/scheme, product app/test, canonical harness, `job_budget.py`, `watch_crown_setup_events.py`, or prior terminal receipt is changed. A later implementation should add this reviewed proposal as `review/STATIC-ONLY-CROWN-PROPOSAL.md`; candidate manifests/check logs stay separate from native-result claims.

## Receipt schema and result identity

Keep receipt schema `2` and setup protocol `owned-pair-boot-events-v1` unchanged. This preserves the setup transport contract; it does not reuse the old three-case diagnostic meaning. Add the mandatory, exact scope discriminator `diagnostic_scope: static-list-crown-only-v1` and `excluded_cases: [actual_cold, rgb_positive]` to both producer and validator output. Missing/other scope, fabricated excluded-case results, old ref/lane, or a second case are rejected.

Validation output remains format schema `1`, with `purpose: static_list_crown_only`, `acceptance: false`, the same scope/exclusions, and one case outcome. `complete` means only this one diagnostic has all required provenance, observations and cleanup. It is never a three-way comparison, product pass, release gate, or replacement for the original failed cold result.

Bind and retain the new commit SHA/tree, workflow hash, exact checkout before/after, run ID/attempt, original budget clocks, Xcode `27.0 / 27A266a`, macOS `26A428`, arm64, exact owned phone/40mm Watch/pair IDs, smallest/normal profile, built static fingerprint before/after, exact test selector, and immutable evidence hashes/byte counts. The new source SHA cannot be known until a separate implementation is frozen. Never stamp the future result with e4180a, which is its parent rather than its tested source.

## Runtime command inventory

These are proposed commands, not commands executed for this document. Each remains inside the existing owned bounded-process wrapper.

1. Preflight, 30-second phase: `git rev-parse HEAD` (2s), `git rev-parse HEAD^{tree}` (2s), clean `git status --porcelain --untracked-files=all` (2s); `xcodebuild -version` (4s), `sw_vers -buildVersion` (2s), `uname -m` (2s); Python static-project generator (3s); repeat the same source/clean checks. Read workflow bytes and hash locally.
2. Build, unchanged 240-second phase: one 110-second `xcodebuild -quiet -project TouchColorWatchCrownControl.xcodeproj -scheme TouchColorWatchCrownControl -configuration Debug -destination generic/platform=watchOS Simulator -derivedDataPath build/crown-static ARCHS=arm64 CODE_SIGNING_ALLOWED=NO build-for-testing`. Read the existing runner Info.plist and bounded static product fingerprint (10s host traversal/hash bound, at most 8,192 files / 1 GiB).
3. Setup, unchanged 600-second phase: `simctl list devices available -j`; `list pairs -j`; create owned phone then Watch from observed templates; pair exact owned IDs; pair readback; conditional existing `pair_activate` only if its verified pre-boot state requires it; pair readback; phone boot then phone bootstatus `-b`; Watch boot then Watch bootstatus `-b`. Exactly 11 commands, or 12 with pair activation. Family caps remain list30/create60/pair60/pair_activate60/boot180/bootstatus420, clipped to setup and original work deadlines. No post-boot readiness inventory is added. This pre-boot pair operation is not app activation or focus forcing.
4. Static phase, unchanged 180 seconds: exactly one `xcodebuild test-without-building` with the existing static project/scheme, Debug, exact Watch UUID destination, `build/crown-static`, parallel testing NO, one maximum destination, no collected test diagnostics, enabled test timeouts, default/maximum case allowances120, result bundle `build/watch-crown-isolated_static.xcresult`, the sole selector above, arm64, and no signing. Process cap180; no repetition/retry options. Retain captured lifecycle/console/static markers in host memory/files first. Then `xcresulttool get test-results summary --path` (15s), exact lifecycle/summary reconciliation, static app terminate (30s), static runner terminate (30s), `simctl spawn <watch> launchctl list` (5s). Neither terminate targets the product.
5. Cleanup reserve, unchanged 130 seconds: shutdown owned Watch then phone (10s each), exact device state inventory (5s), unpair the owned pair (10s), delete owned Watch then phone (10s each), final device inventory (5s) and pair inventory (5s) proving absence. No Home OSLog extraction.
6. Evidence reserve, unchanged 180 seconds: source/clean checks as above, static product fingerprint again, and `xcresulttool get test-results tests --path build/watch-crown-isolated_static.xcresult` (20s). No simulator query or new UI.
7. Independent filesystem-only validation60; upload reserve check and safe directory/1,200,000-byte cap guard; bounded upload60. Existing 20-second overhead and 30-second startup margin remain unchanged.

No command may follow simulator uncertainty through the driver, including cleanup, inventory, re-boot, xcresult extraction, or a host command hidden behind a wrapper. Finish only already-owned host process-group/reader cleanup and permitted persistence of already captured bytes; then dispose of the VM. The independent filesystem-only validator/cap guard/upload may retain the incomplete evidence without querying the device or claiming cleanup success. Raw zero at/after a deadline is still timeout/uncertainty.

## Original-clock admission and evidence

The 25-minute job is still 1,500 seconds: startup30 + work1,020 + cleanup130 + evidence180 + validation60 + upload60 + overhead20. No reserve is lent to testing. Phase ceilings share the original clock; they are not additive promises. The remaining work phase ceilings total1,050 seconds, already greater than1,020, so even this reduced scope does not guarantee every worst case fits.

Setup requires the full600-second admission before starting (latest original-work offset420). Static requires the full180-second phase before its first command (latest offset840); never shorten a case to squeeze it in. Within static's180 seconds, the test process must return early enough for summary15 and each full subsequent terminate30/terminate30/inventory5 allowance. These maxima do not all fit if the test itself consumes180. Preserve the current fail-closed admission rather than increasing the phase or moving its commands into another reserve. A slow test can therefore produce useful retained observations with an incomplete overall receipt.

Expected bounded evidence paths, all under `build/evidence`, are:

- `report.json`, `validation.json`
- `isolated_static-build.log`
- `setup-phone-bootstatus.log`, `setup-watch-bootstatus.log`
- `isolated_static-lifecycle.log`, `isolated_static-console.log`, `static-observations.log`
- `isolated_static-summary.json`, `isolated_static-cleanup-services.log`, `isolated_static-tests.json`
- `cleanup-devices.json`, `cleanup-pairs.json`

Files exist only if their producing step ran. Static observations use the existing 16,384-byte cap; do not spend the absent Home observer allocation on extra probes. Keep report300,000, validation16,384, process capture262,144, manifest64-entry, and total1,200,000-byte limits plus the existing per-file limits. Before/after payloads become obtainable because static runs as the first and only XCTest, and `static-observations.log` is retained before any later termination can fail. If setup fails first, there is still no static result. If the process never returns safely or no payload was emitted, do not reconstruct or claim missing observations.

## Frozen assertions and finite UI bounds

- Unmodified Debug-only app: a NavigationStack and static List of12 immutable NavigationLinks, separate bundle/project, no product model, connectivity, persistence, custom Crown binding, mutable app state, or focus modifier.
- Product `.notRunning`; normal control launch; row0 exists within15s, fully contained at the top of actual content, and hittable; row11 initially offscreen/nonhittable; no BackButton; exact List/navigation identities and valid complete public geometry.
- Exactly3 Crown calls at `-0.1` and six before/after captures. Downward movement requires a shared visible/intersecting row's Y to decrease by more than1 point with stable geometry; existing0.5-point equality tolerance unchanged. Other geometry changes are inconclusive.
- Optional touch only after the Crown result is frozen as stationary: at most two extra snapshots and one upward finger motion of at most32 points, computed from current clipped content. Keep every live frame/identity/foreground/hittability/screen-point recheck, edge inset and geometry rejection. The existing gesture is press0.01s, slow drag, hold0.15s. No touch retry or destination tap.
- At most256 visited/retained snapshot nodes,12 rows/capture,1,536 bytes/frame,2,048-byte result,16KiB structured static payload. Omissions/snapshot errors cannot qualify. These bounds do not claim to limit undocumented OS snapshot work.
- Final assertions remain exactly3 calls, `crownStatus == moved_downward`, and `failureReason == none`. Touch success leaves stationary Crown failed. Existing fail-closed interruption handling and teardown remain unchanged.
- Cold Home remains byte-identical: initial empty/top conditions, at most12 `-0.1` rotations, privacy target hittability, tap, Privacy navigation and BackButton. RGB remains byte-identical: red-channel change following `-0.25`, valid hex and unchanged other channels. Neither method runs here.

## Required validation before any separate run admission

1. Freeze/compare the four runtime-path delta and named test/document paths against the exact395-file parent manifest. Hash the static app/test/header/generator/project/scheme, product tests/views/app, shared clock/fence/setup helpers, canonical workflows, and historical receipts; reject unexpected drift. Verify clean deterministic static-project generation.
2. Normal and optimized Python tests: fixed one-case sequencing; no product generator/build/test/launch/terminate/log read; exact single static argv; correct console label; singleton products/runner/cases; old/missing scope and branch/lane rejection; no false full-comparison output on exceptions; hash/source/run/device swaps; extra/repeated/foreign test commands; malformed summaries/trees/lifecycles; zero/skipped/expected-failure cases; static observations tampering and touch-to-Crown acceptance aliases.
3. Replay every existing relevant deadline/fence adversary: 600 setup,180 boot,420 bootstatus, late raw zero including the e4180a195.681s timing, native/structured timeout text, unknown reader/process cleanup, persistence failure, durable marker reload, cancellation/interruption, and wrapped post-setup commands. Prove no later command after uncertainty. Preserve historical cold failure without upgrading it.
4. Exercise full180 static admission at offset840 and rejection after840; rejected full30 termination when time is short; inventory remains5. Prove static marker/lifecycle/console retention precedes a later termination failure and remains immutable, bounded and source-bound. A missing summary/tests/cleanup never becomes complete.
5. Run existing target isolation/geometry checks and setup-event tests, shared job-budget/process/atomic/evidence guards, and relevant aggregate normal/optimized suites. Portable C geometry/source tests are not native XCTest proof. Review exact patch replay and candidate manifest independently.
6. Only after separate implementation/source/capacity approval: one fresh source-triggered hosted job. Confirm exact published SHA/tree/workflow and exactly one new run before interpreting its bounded artifact. Never rerun unchanged e4180a or resume either uncertain VM.

None of these implementation checks or native tests was performed for this proposal; only source/receipt inspection and the395-file parent-content comparison were performed.

## What the measurement can and cannot distinguish

- Static Crown movement would establish that the existing public Crown API can move this simple List on this exact fresh Watch/job/toolchain. Combined only as historical context with the earlier cold failure, that points toward a product/path-specific or intermittent difference; it does not identify a cause.
- Stationary Crown with independently observed downward touch movement would show a scrollable simple List and successful touch movement while these three Crown calls produced no qualifying observed movement. It cannot distinguish XCTest event delivery, OS/List behavior, transient focus ownership, or another system cause, and does not prove a universal simulator bug.
- Stationary Crown plus stationary/unavailable touch gives less separation. Changed/incomplete geometry, startup failure, setup timeout or uncertain cleanup remains inconclusive/incomplete at the affected level.
- No result establishes product Home scrolling, repairs the known privacy assertion, reruns the RGB test, proves a same-session three-case comparison, qualifies another Watch size/text phase, or grants release acceptance. No forced focus, sign reversal, assertion weakening, or larger cap is part of the proposed measurement.
