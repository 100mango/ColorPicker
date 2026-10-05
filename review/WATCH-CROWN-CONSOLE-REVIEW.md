# Crown persisted-status console mirror, local successor

This is a narrow LOCAL source change on public commit96d5de2c5f379d8a1e8a1a734133a6204d557ec3, exact treeafb926b9975452a671f0ff2e1fa67c93098399be. Frozen prior candidates are preserved. No publication or native retry is authorized or performed.

## What the first native run established

Run37265385272/job111621005291 is terminal red. The bounded driver exited0 after approximately139 seconds without receipt output in the job log. The independent validator and artifact upload each hit their existing one-minute limits; no artifact was retained. Phase execution, actual case results and cleanup are therefore unknown from available evidence. Driver exit0 is not product acceptance or evidence that the methods ran. This change does not diagnose or repair the validation/upload timeout, reinterpret that run, increase any budget, or authorize a retry.

## Exact narrow change

The existing driver now mirrors a fixed allowlist from its just-persisted report after each existing phase boundary and after its final persistence. No extra file reads, simulator operations, subprocesses, source checks or result-extraction calls are added. The independent validator never consumes these console lines. Existing report/evidence schemas, acceptance decisions, clocks, workflow steps and all timeout/reserve values are unchanged.

Each WATCH_CROWN_STATUS line contains the persisted source SHA/run ID/attempt, boundary, phase-completion flag, bounded stage count, an allowlisted operation label, actual stored exits/timeout/owned-process cleanup flags, the three stored case statuses, cleanup-confirmation state and error count. Missing or malformed optional facts are null. A raw exit never manufactures a case result; a failed stored result remains failed. Invalid or contradictory source/run binding drops the line rather than attributing it to the wrong run. No error text, command arguments, paths, app output, model data, screenshots or other raw payloads are emitted.

There are at most nine unique attempts: the eight existing phase boundaries and final. Each entire encoded line, including marker/newline, is capped at512 bytes; total attempted bytes are capped at4,608. Duplicate/unknown boundaries cannot expand the bound. This console mirror adds no artifact files and does not widen the existing1.2MB evidence cap or32KiB Home/static observations. Best-effort omissions are counted in the next emitted line; absent output is never proof that a phase did not run.

The writer accepts only an actual stdout pipe and respects its observed PIPE_BUF. It temporarily uses O_NONBLOCK, attempts one atomic write, restores the original blocking flag, and never retries or waits. A full pipe, non-pipe stdout, insufficient atomic-write allowance, closed stdout or writer error drops the record. It does not fall back to potentially blocking regular-file/terminal writes. Serialization/write time remains charged to the original job clock; no timestamp or allowance is reset. Logging failures do not change the report, test verdict, work-stop latch or cleanup state.

## Verification and limits

Thirteen portable console tests run normally and under python3 -O: strict encoded/count bounds, source/run mismatch, unknown/null preservation, real failure retention, redaction of hostile/private payloads, ambiguous/malformed fields, duplicate emissions, drop accounting/no retry, persistence ordering/original-clock charging, writer-error isolation, unsupported stdout and PIPE_BUF limits, flag restoration, and an actual full-pipe nonblocking check.

Full normal/optimized canonical and focused regression counts, generator/invariant results and fresh patch replay are recorded in the sibling manifest/check packet. Canonical Apple/iOS workflows, budgets, original cold/RGB XCTest assertions, the independent validator and prior continuation fixes remain byte-identical to the baseline. This Linux environment cannot compile or run the Watch target. The console path has portable pipe proof, but actual GitHub/macOS delivery, native phase outcomes and the original validator/upload timeout cause remain unverified.

## Darwin atomic-pipe correction

The preserved c8c086 packet was blocked because its actual669–679-byte minimum records exceeded Darwin PIPE_BUF512 and were dropped before writing. This successor retains the identical single-write pipe guard, and compacts only the advisory projection into schema v=1. All entire encoded records fit512 bytes, including marker/newline; maximal admitted fields have an executable positive-size regression. No report/validator schema changes.

Compact keys: run=run ID, try=attempt, phase=boundary, done=stored phase completion, stages=stage count, cleanup=stored aggregate cleanup, errors=error count, omitted=earlier omitted console attempts. Source sha, acceptance and delivery retain their meanings. last is exactly [phase, operation, exit, raw_exit, timed_out, group_gone, reader_finished]. cases.cold/static/rgb are exactly [started, stored_result, raw_exit, cleanup_confirmed], corresponding to the existing three ordered methods. Unknown fields remain JSON null. The new 512-byte positive regression exercises generated records through the real writer logic for all nine boundaries; the prior tests still exercise errors and full pipes.

The independent reproducer now observes9 write calls under PIPE_BUF512, rather than0. Its bare mocked os.write has no integer return configured, so its omission counter remains9; the new positive regression configures an exact complete write and separately proves9 emissions with0 omissions. Real delivery remains unproved until an admitted native attempt.
