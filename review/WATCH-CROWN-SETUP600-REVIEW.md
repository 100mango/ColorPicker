# Crown setup600 redistribution, local source packet

LOCAL successor on publishedfa1ff007a88729f8acc77f86c036809cbd2a90e3, exact treeb88c6fedf4166613b0ed2f39b105ae0661944ebc. Prior frozen source and native evidence are preserved. No publication, native retry, concurrency or readiness skip is authorized or performed.

## Measured failure stays failed

Run37274520266/job111648512724 exhausted the450-second setup ceiling before any UI case. Phone boot/readiness completed in3.598/164.289s, and Watch boot in131.222s. Watch readiness received a clipped141.458-second allowance and returned raw0 after the absolute setup deadline. Exact retained deadline616.224344666 and command finish616.309486750 differ by0.085142084 seconds. The driver correctly recorded exit124/timed_out, an fsync-confirmed uncertainty marker at stage23, zero subsequent commands and no cleanup confirmation. No positive final Booted inventory exists for that run. This result is not reinterpreted.

## Only the setup ceiling changes

The executable change is setup450→600 in the source contract and independent validator. The driver receives only a matching module-description update; every driver method, including exact deadline checks, uncertainty/persistence barrier, command routing, readiness proof and finalizers, is unchanged.

The original work pool remains1,020 seconds from its original wall/monotonic clocks. The job remains25 minutes, startup30, and cleanup130/evidence180/validation60/upload60/overhead20 reserves remain unchanged. Canonical per-command maxima remain inventories30, create/pair/conditional activation60, boot180 and readiness420, each still clipped by remaining setup and original work time. All later UI phases still need full240/180/180-second admission; each test command retains180 seconds and its120-second XCTest execution allowance. No late-result tolerance or retry is added.

Work phase ceilings now sum to1,470 seconds. This is not an additive reservation or expanded work budget. Setup600 borrows potential work time from later phases; slow setup can leave one or more controls unstarted/incomplete. Full setup admission is possible only at original elapsed420 seconds or earlier;420.001 seconds starts no command. Historical450-second setup-ceiling descriptions are superseded by this packet only.

## Timing/deadline proof

Eight new portable tests exercise:

- The exact historical raw0 finishing0.085142084s after the450-second bound remains failed/incomplete and fenced.
- The same measured last readiness command fits the600-second ceiling, without changing its420-second family cap.
- Moving that same raw0 completion0.085142084s beyond the new600-second deadline still fails and fences; the deadline check has no grace.
- The full measured fa1ff command sequence, including recorded inter-command gaps, plus a clearly hypothetical19.237-second final inventory completes a synthetic setup in469.322142084s. The final inventory requires both owned devices to be Booted. This replay is scheduling evidence, not a new native result or guarantee of fit.
- At that timing, original work consumption is542.146289042s. Simulated full240s cold and180s static phases would leave57.853710958s, so the180s RGB phase must not start or be shortened.
- Exact latest admission, original-pool exhaustion, unchanged reserves/caps, and independent-validator rejection of any setup phase limit other than600.

Existing complete-order, conditional-activation, positive-readiness, cap-clipping and uncertainty tests remain active. Historical450-second custom test phases remain as deadline regression fixtures; production setup uses600.

## Source-backed overlap answer

No already-reviewed source path authorizes deliberate overlapping boot requests. The canonical Watch path executes phone boot, waits for phone bootstatus, then executes Watch boot and waits for Watch bootstatus in scripts/test_extra_platforms.py:240–247. The paired preparation loops in phone/Watch order and waits for each role's bootstatus inside that loop in scripts/test_paired_watch.py:110–113; its positive owned-pair inventory follows at114–116. scripts/watch_runtime_pair.py contains pure identity/activation checks and no boot scheduler.

Issuing Watch boot before phone readiness completes would reorder these reviewed calls. Concurrent subprocesses would also require new ownership/deadline/uncertainty coordination. Existing reader threads or later paired-test execution do not establish a reviewed boot-overlap contract. Underlying simulator-internal concurrency is not proof that a new explicit ordering is safe. No overlap is implemented here and no readiness proof is skipped.

## Scope and limits

The original UI file/assertions, per-command map, global helper defaults,512-byte console, pure helpers, canonical/diagnostic workflows, job budget and reserves are byte-identical. The two executable setup constants, driver description, corresponding portable test expectations, new tests and this review are the entire delta.

Full normal/optimized checks, source invariants and fresh patch replay are retained in the sibling manifest. Linux cannot establish whether a new VM's timing or Crown behavior will pass. Final exact-source/capacity review is still required before any native attempt.
