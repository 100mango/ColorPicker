# Crown complete setup-allowance alignment

LOCAL successor on publice107d21dc64c5df3e9a9eca60d0649db3de9b9f0, exact tree8b02bf2c5bb1af27e1779ff86775a717e9d51d74. Frozen packets and prior native evidence remain unchanged. No publication or native retry is authorized or performed.

## What the latest native attempt established

Run37271545657/job111639414509 completed preflight and both builds, then phone boot/readiness13.327/77.943s and Watch boot/readiness56.080/91.770s. The required final devices-available inventory hit its inherited5-second cap; setup ended at249.238s before any UI method. The fsync-confirmed uncertainty barrier stopped at stage24: no later commands and no cleanup-confirmation claim. The retained failure remains failed/incomplete; it is not rerun or relabeled here.

The canonical setup source allows inventories30s, create/pair/conditional activation60s, boot180s and readiness420s. The retained paired1410 post-boot devices inventory completed in19.237s under the30-second inventory allowance. Its argv lacks Crown's available filter, so this is operation-family timing evidence rather than a claim that both invocations always take the same time.

## Narrow implementation

One explicit canonical setup-family map now routes every existing Crown setup call through its existing bounded process owner and durable uncertainty fence:

- list:30 seconds
- create, pair and conditional pair_activate:60 seconds
- boot:180 seconds
- bootstatus:420 seconds

This supersedes the narrower120/240 boot caps and5/10-second setup calls described in the historical setup-safety packet.

All setup inventories use the map: initial available devices, initial pairs, new-pair readback, activation readback and the final positive two-device Booted proof. Both creations, pairing, optional activation and all four boot/readiness calls use it too. The existing order/arguments remain unchanged. There are12 commands when pairing is already active and13 when explicit activation is needed. No runtime-capability/resource query, device command or proof removal is added.

The setup-only text/JSON adapters call the existing text/value/run path. General text/value defaults remain5 seconds; cleanup, evidence, source/toolchain and unrelated callers are unchanged. The pure ownership/profile/pair helpers remain shared. The imperative canonical runner is never imported; an AST-based test checks the complete map against its actual setup source.

Every setup maximum is clipped to the remaining450-second setup phase and original1,020-second work pool, with the existing one-second minimum admission. The job stays25 minutes; startup30 and all450 seconds of cleanup/evidence/validation/upload/overhead reserves stay unchanged. UI phases still require full240/180/180-second admission and all three UI commands retain their180-second command/120-second XCTest allowances. A slow setup can leave later controls not started/incomplete. The1,320-second sum of work phase ceilings is still not an additive reservation or expanded pool.

The validator independently checks each setup family against the canonical cap and its actual clipped allowance; boot/readiness outside setup remain forbidden. Durable uncertainty, persisted intent, post-cleanup/post-persistence deadlines, native timeout detection, finalizer/reload barriers, true exit65 handling and the512-byte console mirror are unchanged.

## Executable timing and safety checks

Ten new tests cover complete setup order, the conditional-activation branch, every per-family cap, comparison with canonical source without importing it, unchanged general helper defaults, mandatory final Booted state, clipped/exhausted final reads, full later UI admission and independent-validator rejection of altered caps.

Two full synthetic controller replays retain source-shaped command receipts:

1. Rounded e107 command timings plus the19.237-second final inventory complete setup in261.148 seconds. The final read has its full30-second allowance.
2. The retained419.381-second canonical boot sequence, the same measured inventory/create/pair prelude and19.237-second final inventory complete setup in441.409 seconds. The final inventory is clipped to27.828 seconds, still enough for the fixture's19.237 seconds.

These are successful scheduling/proof replays using mocked native processes, not native runs or product passes. They do not reproduce real filesystem/controller overhead or guarantee that a future VM will fit. A final read exceeding30 seconds, or exceeding its shorter remaining phase allowance, retains the fsync-confirmed fence and starts no later command. A sub-one-second remainder starts no read. Missing Booted state fails the setup proof even when all commands returned0. The existing24 uncertainty-barrier tests also pass in both normal and optimized Python, preserving the earlier safety correction.

Full canonical/focused checks, generator/source invariants and fresh source-patch replay are recorded in the sibling manifest. Linux cannot establish native timing, simulator readiness or Crown results. Exact-source/capacity review remains required before any new native attempt.
