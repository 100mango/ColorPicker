# Crown event-only diagnostic admission

Local successor on public `fe4195bdc0fe620fb81118fa53358cc795f9f0b9`, tree `7a5afc76cb59e12ad2beb18b553e9120400d6071`. No native execution or publication is included.

## Meaning of the new contract

Receipt schema 2 and protocol `owned-pair-boot-events-v1` replace the diagnostic's simultaneous two-device state snapshot with separately timestamped, successful bounded command-completion events. This is an explicit readiness-precondition change for the isolated three-method diagnostic, not a claim that bootstatus proves continuing app readiness or post-boot pair connectivity.

The driver still creates and verifies both exact owned devices and their pair, verifies pre-boot activation, and sequentially runs phone boot/bootstatus then Watch boot/bootstatus. It no longer schedules the extra final full-device inventory. The record says inventory `not_requested`, simultaneous state `unobserved`, connectivity `unobserved` and continued readiness `unobserved`. It never synthesizes `setup_readback` or `state=Booted`.

Apple's [Simulator guidance](https://developer.apple.com/videos/play/wwdc2019/418/) points to installed per-command help. The [Simulator engineer's public answer](https://stackoverflow.com/questions/37033405/how-can-i-tell-when-the-ios-simulator-has-booted-to-its-home-screen) supports boot-progress monitoring, but this source does not claim an exact Xcode 27 semantic-success guarantee. Admission depends only on facts observed in the source-bound command receipts. Actual later XCTest startup, exact destination/source/result binding and original cold/static/RGB assertions remain mandatory. No diagnostic receipt can grant product acceptance.

## Narrow implementation

- Driver methods other than `__init__` (schema/protocol) and `setup` are byte/AST unchanged. No new command, retry, concurrent boot, shortened readiness call or phase reset is added.
- The independent setup validator reconstructs all 11 planned setup commands, or 12 when pair activation was needed. Initial inventory, creations, pairing, activation readbacks and four boot commands must match the exact role/UUID/runtime order. It checks creation/pair output digests against the owned UUIDs.
- Both exact bootstatus byte streams are retained under fixed names with their stage indices, source/run/attempt, role and completion timestamps. Each has a 16,384-byte ceiling inside the existing 1,200,000-byte evidence cap. Exactly retained empty output is permitted and remains empty; no banner or terminal-message grammar is invented. Invalid UTF-8, truncation, size/hash mismatch, missing files and negative timeout evidence fail closed.
- The independent validator reconstructs the claimed event dictionaries rather than trusting a readiness boolean. Every setup stage needs genuine integer exit zero, started=true, complete group/reader cleanup, no native timeout/uncertainty, canonical command cap and strict completion before its absolute deadline. Wall/monotonic chronology, original setup/work cutoffs and later-case ordering remain enforced.
- Additional, reordered, missing or interleaved setup calls are rejected. A later device mutation before the first actual XCTest also invalidates event admission. Old schema-1 reports, synthetic snapshot claims and unsupported protocols are rejected.
- The existing durable uncertainty fence, host cleanup, per-case cross-evidence checks, console mirror, workflow, 600-second setup, 1,020-second work pool, 25-minute job and every cleanup/evidence reserve are unchanged.

The producer independently checks the reconstructed proof before leaving setup. Final reconciliation reads the immutable manifest-bound files and reconstructs it again. Its existing safe file reader and total evidence limit remain authoritative. Console format version 1 and validation-output format version 1 are unchanged output formats; they do not permit schema-1 input receipts.

## Historical evidence remains failed

fe419 run 37277435545 completed both bootstatus commands, then actually attempted a final inventory that timed out with zero bytes. Its stage-24 fsync barrier, absent UI cases and unconfirmed simulator cleanup remain unchanged. The new source deletes that query from a future planned sequence. It does not ignore a failed query, remove an old uncertainty marker, resume the old VM or upgrade an old artifact.

The canonical hosted path has previously started Watch tests after exact bootstatus completion. Its later UI checkpoint includes a Watch state observation; this proposal does not claim canonical UI was inventory-free. Canonical and paired/release validators are not modified by this diagnostic-specific protocol.

## Tests and remaining proof

Seventeen new focused tests exercise protocol/role/runtime/source mismatch, creation hashes, command order/extra final inventory, missing readiness, late zero at and after deadlines, cleanup/truncation flags, byte/hash/role corruption, invalid UTF-8 and negative output, explicit empty evidence, fabricated claims, intervening device changes, old-version rejection, and unchanged later source/device/case gates. Existing fixture setup placeholders are replaced with source-shaped synthetic events. Historical inventory-timeout tests still prove the fence; future event-only setup explicitly does not request the removed query.

All 230 focused tests pass in normal and optimized Python, including the existing simulator-fence, actual owned-process and per-case adversaries. Canonical checks pass 537 normally and 334 optimized. Generator/source invariants, evidence limits and exact patch replay are recorded in the sibling manifest after the final check pass.

No new native timing, simulator availability or Crown outcome is established locally. Devices may become unavailable after their individual completion events; actual bounded XCTest will report that as failure/incompleteness. Cold failure remains a real failed assertion even if controls later pass. Exact source review and separate capacity admission are required before one fresh hosted run.

## Narrow independent-review successor

The first local packet was blocked on two reproduced validation gaps and was never published. This successor derives the activation branch from the original pair state, then requires the recorded activation decision and exact command sequence to agree. An inactive original state cannot use the already-active branch; unknown states are rejected.

The admitted source emits no command between setup and the first XCTest. The validator now enforces that closed sequence, rather than classifying only the literal `xcrun` prefix. Absolute-path xcrun, env/shell wrappers, and unrelated host commands inserted there all fail. These are explicit adversarial receipt checks, not added native operations. The driver, protocol, budgets, UI and cleanup remain unchanged from the first local event packet.

Three new regression methods cover both blockers and all four recognized active/inactive branches. The full focused count is now 233 per Python mode. The original blocked tree and patch remain preserved for comparison; only this successor is offered for review.

## Native allocator-to-stage timestamp correction

The e7b29 run retained nominal Watch bootstatus allowance408.957645917s, calculated before the later stage start timestamp. Scheduling advanced0.163456333s between those events; the later setup remainder was408.794189584s. The actual enforced deadline remained the original setup cutoff1511.109129375 and the command finished at1269.502899291, more than241s early. The old validator incorrectly compared the earlier nominal grant with the later remainder.

This successor independently bounds the recorded effective deadline by min(stage start + nominal grant, original setup cutoff, original work cutoff). Nominal grant remains within its canonical cap; all clocks must be finite, and completion must remain strictly before the effective deadline. No timing tolerance is added. The previous1ms nominal comparison tolerance is removed. An allocator observation delay can only shorten the effective window, never extend its deadline.

The committed minimal real fixture is explicitly a timing-field projection from run37287069946/stage23, bound to the retained report and artifact digests. It is not a successful-run fixture. The original setup rejection, later shutdown timeout, durable uncertainty, absent UI cases and unconfirmed cleanup are preserved. The full native report must still fail validation.

Five new tests reproduce the real numeric projection, inject actual pre-stamp delay into the unchanged driver allocator, and reject extended deadlines, any completion at/after the effective cutoff, changed caps and invalid original clocks. This yields238 focused tests per mode. Driver, workflow, command sequence, event semantics, budgets and every other validator gate are unchanged.
