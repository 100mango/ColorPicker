# Mini log-stream compatibility measurement (source-review candidate)

This is an isolated, runnable measurement recipe, not a production warmup change. The dedicated workflow is materialized for exact source review; publication and native execution remain separately gated. The two historical install-success/launch-60-second-timeout observations (1410 job 111593678852 and e980 job 111611786255) motivate obtaining missing tool evidence; they do not prove an app regression.

The six source additions relative to e980 are this document, `scripts/mini_passive_compatibility.py` and its portable tests, `scripts/mini_passive_status.py` and its staging tests, and `.github/workflows/mini-passive-compatibility.yml`. All 357 e980 baseline files, including active UIKit warmup, workflows, watch touch and Crown code, stay byte-identical. No existing launch argv, app argument, environment, acceptance rule, or 60/600/20 warmup limit changes.

## Exactly what it can do

On a newly allocated, dedicated disposable GitHub-hosted macOS VM with the existing Xcode 27 runner image:

1. Start the inherited 20-minute iOS native job budget in the first step. Initialize the unchanged source-bound budget after checkout. Its existing reserves are unchanged: startup margin 30 seconds; cleanup 130, evidence 180, validation 60, upload 60, overhead 20 seconds.
2. In one Python invocation, start the original 600-second preparation clock before imports, then verify the checkout SHA equals the workflow/source SHA and the checkout is clean. Require Xcode 27.0, build 27A266a, with no alternate toolchain fallback.
3. Build the ordinary Debug iOS simulator app, unsigned, using a 300-second command maximum and only the remaining original preparation/job allowance minus cleanup. This is a local build, not an install or launch. A setup command retains at most 64 KiB stdout+stderr before failing closed. `-quiet` avoids a full build transcript; overflow is failure, never partial successful output.
4. Use the unchanged `Warmup.select()` once to choose the available `iPad mini (A17 Pro)` under `com.apple.CoreSimulator.SimRuntime.iOS-27-0` and persist its exact UUID/runtime binding. Inventory has a 30-second maximum. Boot only that recorded UUID (180-second maximum), then wait for its bootstatus (240-second maximum), clipped by the same original clocks. These are per-command maxima, not additive fresh allowances. Any timeout, late result, cancellation or uncertain command retains the existing marker and prevents every subsequent simulator command. No create/rebind fallback or second selection occurs.
5. Validate the bounded built Info.plist and require identifier `com.mango.touchColor`, executable `TouchColor`. Recheck that app and device binding before observation. The app need not be installed: this measurement observes the installed public logging tool's own output.
6. Require at least 30 seconds of original preparation and inherited job allowance: help 5 + observation 5 + shared cleanup 20. Acquire one exclusive, immutable uncertainty marker. Read only `xcrun simctl spawn <recorded UUID> log help stream` for at most 5 seconds/8 KiB. Require a timely zero exit, no remaining host descendants, and listed `--info`, `--debug`, `--predicate` options. No unsupported flags are guessed.
7. Start only `xcrun simctl spawn <recorded UUID> log stream --info --debug --predicate 'process == "TouchColor"'`. Observe for at most 5 seconds, including spawn and persistence latency, with bounded nonblocking head/tail drains. No readiness parser is present. First/last observed-output timestamps, raw bytes, hashes, omissions and owned PIDs/PGIDs are retained.
8. Stop already-owned host groups with TERM then KILL, using one shared absolute 20-second cleanup deadline, also clipped by the original clocks. Pipe draining uses that same deadline; bytes arriving in cleanup are discarded and counted separately, never appended to the five-second observation. A reaped leader never proves its descendants or the simulator-side producer exited.
9. Keep the uncertainty marker permanently. Return exit 3 even when the compatibility observation finishes. Only local file retention and artifact upload may follow. Do not invoke any simulator query, screenshot, launch, shutdown, retry, or fixture cleanup. End the job and dispose of the whole VM.

The measurement never installs or launches an app, enables app logging, attaches launch console flags, changes a permission, broadens the app predicate, or declares readiness/containment. A quiet or apparently reassuring banner remains raw evidence. It does not establish no app launch, a hang, a simulator defect, or eligibility to continue warmup.

## Exact dedicated workflow

This YAML is byte-identical to the dedicated checked-in workflow. The candidate must be separately source/capacity-admitted before publication or use. The `xcode-27` label must resolve to a fresh disposable GitHub-hosted VM with `/Applications/Xcode_27.app`; the script refuses self-hosted runners. If that label does not have that contract, allocation is blocked until the runner owner supplies an eligible VM. Never relabel or reuse an uncertain VM. The existing global capacity ceiling remains TouchColor 3 + QRCatcher 1 + Celluloid 1 <= 5: this needs its own later source/capacity GO and an admitted free TouchColor slot. Existing TouchColor allocation does not authorize an extra job.

Publish the proposed workflow only after a separate source/capacity GO, on the dedicated push-only `codex/mini-passive-compatibility` branch in `100mango/ColorPicker`, as `.github/workflows/mini-passive-compatibility.yml`. Hold this measurement behind the separately admitted Crown work. Do not publish it on either canonical branch: that could trigger unrelated canonical cohorts. The reviewed candidate commit has exact e980 as its source parent. `github.sha`, `github.workflow_sha`, checked-out HEAD and the initialized budget SHA must agree. Do not dispatch e980 and download an uncommitted script over it. The local source snapshot in the freeze packet is not a public commit.

```yaml
name: Mini passive compatibility (isolated proposal)
on:
  push:
    branches: [codex/mini-passive-compatibility]
permissions:
  contents: read
concurrency:
  group: mini-passive-compatibility-${{ github.ref }}
  cancel-in-progress: false
jobs:
  mini-passive-compatibility:
    runs-on: xcode-27
    timeout-minutes: 20
    env:
      DEVELOPER_DIR: /Applications/Xcode_27.app/Contents/Developer
      TOUCHCOLOR_JOB_PLATFORM: ios
      TOUCHCOLOR_JOB_LANE: mini-passive-compatibility
      TOUCHCOLOR_JOB_MINUTES: '20'
      TOUCHCOLOR_BUDGET_PHASE: work
      TOUCHCOLOR_EVIDENCE_LIMIT: '1000000'
    steps:
      - name: Start the original job clock
        shell: bash
        run: |
          python3 - <<'PY'
          import os, time
          with open(os.environ['GITHUB_ENV'], 'a') as output:
              output.write('TOUCHCOLOR_JOB_STARTED_EPOCH=' + str(time.time()) + '\n')
              output.write('TOUCHCOLOR_JOB_STARTED_MONOTONIC=' + str(time.monotonic()) + '\n')
          PY
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          persist-credentials: false
          ref: ${{ github.sha }}
      - name: Initialize the original source-bound job budget
        shell: bash
        run: |
          set -euo pipefail
          test "$GITHUB_REPOSITORY" = 100mango/ColorPicker
          test "$GITHUB_REF" = refs/heads/codex/mini-passive-compatibility
          test "$GITHUB_EVENT_NAME" = push
          test "$GITHUB_WORKFLOW_REF" = 100mango/ColorPicker/.github/workflows/mini-passive-compatibility.yml@refs/heads/codex/mini-passive-compatibility
          test "$GITHUB_WORKFLOW_SHA" = "$GITHUB_SHA"
          python3 scripts/job_budget.py initialize
      - name: Prepare exact Mini and observe the installed reader, then stop
        shell: bash
        run: python3 scripts/mini_passive_compatibility.py compatibility-only
      - name: Stage bounded existing files only
        id: stage
        timeout-minutes: 1
        if: always()
        shell: bash
        run: |
          python3 - <<'PY'
          from pathlib import Path
          import json, os, stat, sys
          sys.path.insert(0, 'scripts')
          from mini_passive_status import emit_summary
          root = Path('build')
          if root.is_symlink(): raise SystemExit('Unsafe build root')
          target = root / 'mini-passive-upload'
          target.mkdir(exist_ok=False)
          caps = {
              'iPadMini-passive-compatibility/stream.bin': 65536,
              'iPadMini-passive-compatibility/collector_stderr.bin': 4096,
              'iPadMini-passive-compatibility/help.bin': 8192,
              'iPadMini-passive-compatibility/receipt.json': 8192,
              'iPadMini-simulator.json': 8192,
              'iPadMini-runtime-command-uncertain': 4096,
              'job-budget.json': 8192,
              'job-budget-incomplete.json': 4096,
              'job-budget-cleanup-unconfirmed.json': 4096,
          }
          receipt = None
          for relative, cap in caps.items():
              source = root / relative
              if any(p.is_symlink() for p in (source, *source.parents)):
                  raise SystemExit('Linked evidence')
              if not source.exists(): continue
              info = source.stat()
              if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > cap:
                  raise SystemExit('Unbounded evidence')
              with source.open('rb') as stream: data = stream.read(cap + 1)
              if len(data) > cap: raise SystemExit('Growing evidence')
              if relative == 'iPadMini-passive-compatibility/receipt.json': receipt = data
              (target / relative.replace('/', '-')).write_bytes(data)
          summary = json.dumps(emit_summary(receipt), separators=(',', ':')).encode()
          if len(summary) > 128: raise SystemExit('Unbounded console metadata')
          (target / 'console-summary.json').write_bytes(summary)
          PY
      - name: Verify upload reserve, using local budget only
        id: upload_reserve
        timeout-minutes: 1
        if: always()
        run: python3 scripts/job_budget.py check-upload
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        timeout-minutes: 1
        if: always() && steps.stage.outcome == 'success' && steps.upload_reserve.outcome == 'success'
        with:
          name: mini-passive-compatibility-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
          path: build/mini-passive-upload
          if-no-files-found: warn
          retention-days: 7
```

Upload/setup action runtimes are bounded by the original 20-minute job deadline; no whole-VM cleanup command is issued from the job. The platform destroys the hosted VM after the job terminates. The `if: always()` tail is filesystem-only/upload-only and cannot authorize more simulator work. This is not a reusable success signal. A setup failure may leave no stream evidence; its failure/uncertainty marker and the job log remain the honest outcome.

## Smallest evidence needed next

This measurement can establish whether that exact installed help supports the proposed syntax, what bytes (if any) the reader emits in its first five seconds, output timing and exit status, and whether its owned host group/pipes terminate under the one shared reserve. It cannot establish app-log delivery because it does not launch an app, and cannot establish simulator-side reader termination by observing only host groups.

Retain the exact raw help and stream/stderr files with receipt SHA/run/UUID/runtime, the stable Xcode build from bounded setup output, launch-attempted=false, timing and cleanup fields. If the output has no documented readiness meaning, report readiness unavailable rather than interpreting a familiar banner. Any future actual launch diagnostic still needs a separately source-reviewed native readiness contract and producer-containment evidence; this compatibility job does not satisfy those gates, and does not unlock warmup.

Synchronous OS file writes or process creation can themselves stall; Python cannot preempt a kernel-blocked syscall. This code includes their elapsed time in the same absolute clocks and rejects late returns without starting another simulator command. The outer disposable-VM job deadline remains the final containment bound. No Linux fixture or fake process model proves native scheduling, simctl-daemon cancellation, or durable filesystem latency.

Primary public mechanism reference: [Apple WWDC22, Optimize your use of Core Data and CloudKit](https://developer.apple.com/videos/play/wwdc2022/10119/), application-process `log stream --predicate` example. It does not specify iOS 27 readiness text or simctl-spawn containment.

## Staging-only console fallback

The existing filesystem-only staging step emits one advisory `MINI_PASSIVE_STATUS` line from the receipt bytes it already read. The entire ASCII-encoded line, prefix and newline included, is at most 512 bytes. It is attempted once on an actual stdout pipe with a sufficient reported PIPE_BUF, using nonblocking mode; full/error/unsupported stdout is omitted without waiting or retrying. A <=128-byte `console-summary.json` stages the attempted/omitted counts when possible. Neither console acceptance nor artifact upload is guaranteed. The unchanged receipt remains primary evidence.

The fixed schema carries the current exact source SHA/run/attempt, receipt binding state, last attempted help/stream phase, allowlisted failure reason, and actual nullable owned-cleanup values. `help` and `stream` are `[persisted state, exit code, host_cleanup_confirmed]`; `cleanup` is the persisted aggregate host result. Missing fields stay null. Mismatched, invalid or missing receipts expose no phase/result/cleanup fields. Exact repository, dedicated push branch, workflow reference, job and source/run context are validated before labeling receipt fields. No arbitrary error text, argv, raw stream, app data or additional native command is printed. Reader completion remains unconfirmed and warmup acceptance is never made true.

This fallback does not modify capture/runtime code, 5-second windows, 20-second cleanup, 600-second preparation, 20-minute job, staging/upload time limits or existing byte caps. The failed 723798 run and its absent artifact remain unknown for help-versus-stream phase and actual reader cleanup; this successor cannot reconstruct that missing evidence.
