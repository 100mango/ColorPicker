# Isolated Mini reader-plus-launch diagnostic source

Local implementation for source review only. No publication, native run, or capacity admission. Baseline: public f3787dc4d9fe09bc142e027b258f1e6c5a9cbde9, tree d1196d47f7cda48b32584ff32af6123903d3ee52. Production warmup and canonical workflows stay unchanged.

## Evidence and safety distinction

`MINI-F3787-TERMINAL.json` and `mini-f3787-run37276196475.log` establish a five-second help deadline, owned help exit -15 and confirmed host cleanup in a source-bound memory summary. Stream and launch never started. Durability is unconfirmed; artifacts are absent. Earlier attempts' phase/cleanup unknowns remain unchanged. There is no retained successful installed-help transcript.

For an isolated terminal experiment, a readiness banner is not a necessary safety gate. The gates are exact source/product/device ownership, two owned host groups, bounded supervision, immediate stop on observed failure, and unconditional disposable-VM termination. Unknown log readiness limits interpretation. Readiness proof would be needed to claim complete prelaunch coverage, interpret silence as absence, unlock production warmup, or reuse the simulator; none is permitted.

The disposable GitHub-hosted VM is a runner/job contract. Host-group exit does not prove simulator-daemon containment or VM destruction. Require a fresh approved standard hosted runner and end its job after local evidence; never turn an unverified disposal claim into acceptance. If the required fresh disposable runner contract is unavailable, do not run this experiment.

## Public command basis

Apple's [Core Data documentation](https://developer.apple.com/documentation/coredata/syncing-a-core-data-store-with-cloudkit) explicitly uses `log stream --info --debug --predicate`. [WWDC22](https://developer.apple.com/videos/play/wwdc2022/10119/) demonstrates process predicates. An [Apple DTS response](https://developer.apple.com/forums/thread/82736) demonstrates `log stream` through `xcrun simctl spawn` with an explicit simulator UUID.

These support public mechanism/flag selection. They do not prove installed iOS 27 compatibility, readiness, delivery, or reader containment. Omit runtime help and any invented readiness preamble. Unsupported options or permissions are actual observed failures and stop the experiment.

## Fixed operations

Entry point: `python3 scripts/mini_passive_launch.py launch-once`.

1. Require exact dedicated repository/ref/workflow/run/attempt/source binding, clean source, fresh approved hosted VM, and Xcode 27.0/27A266a. No alternate device, toolchain or runner fallback.
2. Reuse the bounded ordinary unsigned Debug build and recorded Mini selection/boot/bootstatus recipe, with the original pre-import 600-second preparation clock. Validate bounded built Info.plist, fixed product path and `com.mango.touchColor` / `TouchColor` identity. Retain source/product digests and exact device UUID/runtime. No rebuild/reselection.
3. Install that exact app using the original command and 300-second maximum, clipped to the same preparation/job deadlines. Failed, late, timed-out or cancelled preparation stops permanently, without later device actions.
4. Recheck local bindings and require the full joint-operation envelope before creating its exclusive permanent marker. Start exactly one reader: `xcrun simctl spawn <recorded UUID> log stream --info --debug --predicate 'process == "TouchColor"'`.
5. Once its host group and nonblocking pipes are owned, drain/poll available output and immediately admit the original launch. No deliberate readiness wait, banner grammar or first-record requirement. Any already-observed reader failure blocks launch.
6. Launch exactly `xcrun simctl launch --terminate-running-process <same UUID> com.mango.touchColor`, preserving the original environment and absence of app arguments. No console attachment, lifecycle flag, foreground action, permission change or second launch.
7. Drain and supervise both groups together. At the first launch outcome, reader failure, cancellation or deadline, stop both owned groups and perform one shared host-only cleanup. Retain bounded local evidence and end the job. No later terminate, fixture, screenshot, inventory, shutdown, test, or other simulator command.

The reader and launcher are the two explicitly admitted members of a fixed compound operation. Do not nest independent `Warmup.command()` owners, clear uncertainty between spawns, or add a generic bypass of the existing marker. The new fixed supervisor must distinguish its two admitted initial spawns from forbidden subsequent work.

## Absolute bounds

Keep original 600-second preparation, 20-minute job, evidence cap and all `job_budget.py` reserves. Proposed admission requires 85 seconds remaining:

- Reader process creation/ownership: maximum 5 seconds, with no intentional wait.
- Launcher: the original maximum 60 seconds.
- One shared host cleanup, pipe closure and final-output tail: maximum 20 seconds.

Fix the absolute envelope at admission, clipped to the preparation and inherited work boundaries. Reader work expires no later than operation start +65 seconds. Launcher expiry is launch attempt +60 seconds, clipped to that same work boundary. Re-admit a full 60 seconds immediately before launch; insufficient time means no launch. Process creation, local checks, receipts, draining and scheduling delays consume these clocks. A late spawn cannot start a fresh window.

On early termination, cleanup ends within 20 seconds of that event and no later than the original envelope. Signal both groups in the same TERM and KILL phases, never serial 20-second allowances. Leader exit alone is insufficient: reuse `group_exists` and bounded pipe-drain/close semantics. Late bytes remain separate discarded/late counters, never in-window observation evidence. Python cannot preempt a kernel-blocked spawn or filesystem call; the unchanged hosted-job deadline remains the outer bound.

## Fail-stop semantics

- Reader exit, even zero, spawn/read error, permission error, cancellation, binding change or deadline stops the experiment. Nonempty stderr is not itself a failure. Other bounded stderr remains unclassified evidence. The implementation separately detects the operating system’s standard EACCES/EPERM permission-denial phrases using a bounded rolling byte matcher; it never treats a banner as readiness. Process/spawn/read status remains authoritative for other failures.
- Before launch, observed failure prevents it. After launch starts, failure only terminates already-owned host groups. Such a launch is aborted, not automatically the historical 60-second timeout.
- Prioritize reader failure/deadline over a simultaneously observed launcher result.
- Reader readiness stays unknown. Host liveness establishes neither readiness nor simulator-side containment.
- Preserve the permanent marker on all outcomes, including timely launch exit zero. Do not query the device to resolve daemon uncertainty. Always return diagnostic/non-acceptance status; no later UI or warmup qualification.

## Evidence

Raw ceilings: stream 64 KiB; reader stderr 4 KiB; combined launcher output 8 KiB; encoded receipt 8 KiB. Reuse fixed head/tail buffers, incremental counters/hashes and bounded chunks, continuing drain/discard after retention overflow. No unbounded line parser. Mark omitted bytes, encoding failures, discontinuity and late reads. Cleanup bytes are separate from the observation window.

Receipt: exact source/workflow/run/attempt, device/runtime, product identity, two argv, fixed clocks, attempted/owned states, PID/PGID, exit/abort/timeout/late states, per-group host cleanup, output counts/hashes, readiness unknown, daemon completion unconfirmed, tests unexecuted, VM disposal required, warmup acceptance false.

Emit one <=512-byte single nonblocking advisory console record from the same process after owned cleanup, before bulk file persistence. Label memory source and unconfirmed durability/delivery. Reuse the reviewed atomic writer behavior; no new process, reread, retry or evidence allowance. Keep one-minute staging/upload and existing evidence caps, staging only bounded allowlisted files.

Positive identifiable app-origin records can demonstrate observed startup activity. Silence, a banner, missing/truncated records or reader liveness cannot show the app never ran or establish a root cause. A timely launch return is only that command's observed result.

## Proposed source and tests

Four added paths:

- `scripts/mini_passive_launch.py`
- `scripts/test_mini_passive_launch.py`
- `MINI-PASSIVE-LAUNCH.md`
- `.github/workflows/mini-passive-launch.yml`

Proposed dedicated push-only branch/job: `codex/mini-passive-launch` / `mini-passive-launch`. Reuse original 20-minute iOS budget machinery. Before runnable source admission, verify every existing budget/source/workflow guard actually admits this exact identity. If narrow metadata admission is required, disclose that additional delta rather than claiming four paths suffice. Canonical workflows must exclude this branch. No job is admitted here.

Reuse bounded setup capture, `Warmup` preparation ownership, `HeadTail`, `group_exists` and budget primitives. Keep the two-process controller local and fixed, not a general framework or production helper modification.

Required executable tests in normal and optimized Python:

- Exact setup/install/reader/launch argv and unchanged app arguments; source/device/product mismatch fences.
- Silent live reader permits launch with readiness unknown; banners cannot become readiness proof.
- Failure before launch prevents it; failure after launch stops both; permission/stderr errors and exit-zero reader also stop.
- Cancellation, late spawn/read/persistence, original remainder exhaustion and full-60-second re-admission.
- One shared cleanup deadline, leader gone/descendant alive, pipe uncertainty and late-byte exclusion.
- Flood, giant/invalid-UTF8 output and raw/encoded caps.
- Permanent marker and zero later device calls through every failure/finalizer path.
- Fixed console size/context/memory labels, Darwin512-byte atomic pipe success, failure/omitted delivery.
- Dedicated workflow isolation and all unchanged ownership/budget/warmup regressions.

Source review, native compatibility, exact publication and capacity admission remain separate gates.

## Implemented details and review limits

The fixed controller subclasses the already reviewed compatibility owner only to reuse its exact fixed-size buffers, persistence and post-read deadline accounting. It replaces the binding, two-spawn schedule and shared cleanup; it never calls the compatibility help or observation workflow. Compatibility and canonical source bytes remain unchanged. The new dedicated workflow is materialized in this tree, uses the existing 20-minute iOS job identity mechanism, and needs no shared guard or budget change.

Before installation and before the joint launch, local identity includes the bounded Info.plist and SHA-256/size of the exact executable and optional Debug dylib, each capped at16MiB. Links, nonregular/hardlinked code and changing identity fail closed. These reads consume existing preparation/admission time; they are not new simulator queries.

The permitted two commands are separately recorded as attempted/owned. A failed spawn without an owned process handle is cleanup-unconfirmed, never vacuous success. Both owned groups receive the same TERM/KILL phases. Raw exits observed during work are kept separate from exits caused by cleanup signals. A launcher permission indicator is also a stop signal. Other stderr, including informational text, remains bounded and unclassified.

The implementation leaves the marker present even after a timely zero launch result. It always exits3 and cannot qualify warmup or run UI tests. Confirmed host-group/pipe cleanup does not establish simulator-daemon completion or VM destruction. Python cannot preempt a blocked kernel spawn or filesystem operation; late observations fail closed and the unchanged disposable hosted-job deadline remains the outer bound.

The one console record reports phase, source/run/attempt, observed and cleanup exits, nullable cleanup, unknown readiness, memory source, unconfirmed durability and acceptance=false. It uses the existing single atomic nonblocking <=512-byte writer. Bulk output and receipt persistence share the original cleanup tail. If that tail expires, no new output-file write starts; a stale earlier receipt is not promoted to a final durable result.

Portable verification includes synthetic exact-argument/status/deadline/permission tests, informational and giant/binary stderr, late-read exclusion, both-owned-group cleanup, source/product/workflow guards, generated512-byte writer success, and a real two-Python-process/pipe test with no Apple command execution. The known compatibility late-read adversaries are rerun against the reused byte-identical reader. These checks do not establish installed native log compatibility, launch completion or native timing. The exact source manifest and final test inventory accompany the packet.

Preparation stores the exact bounded selection record and product digest on its controller before installation. Joint entry must match those original values; it cannot adopt a newly replaced device JSON or product. This uses the existing trusted bounded identity reader, because Warmup.select writes the record but does not initialize the distinct owned_device helper’s identity fields. No extra simulator inventory is added.
