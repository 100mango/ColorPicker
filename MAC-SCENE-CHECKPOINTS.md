# Mac scene checkpoint candidate, local review only

This document records the original checkpoint-only f221 snapshot. The later local
composite adds its separate fixed single-case driver/workflow, described in
MAC-SCENE-DIAGNOSTIC.md; the four reviewed checkpoint implementations are unchanged.

## Exact base and scope

Parent commit: ea9da854f4658b36a28a3b80f6f48e06185cfedb.
Parent tree: 141bcec9a89e74ebf519b513a7042a2503fe84d4.
The independent local snapshot was reconstructed from all 381 frozen tracked
files, including three paths ignored by the current ignore file, and its Git tree
was verified before edits. It does not modify canonical 74cc or either frozen
original-iOS/archive source.

This change adds four process-wide first-hit checkpoints inside the existing
DEBUG, valid UUID token, synthetic defaults-suite and --ui-test-reset gate:

- sceneBody: the app's Scene body was evaluated.
- windowContentEntered: SwiftUI entered the existing WindowGroup content closure.
- windowContentReturned: the existing root view value and its modifiers were
  constructed, immediately before the result builder yields that value. This
  name does not mean the closure's caller returned or a native view was laid out.
- colorWindowBody: the ColorWindow body was evaluated.

The SwiftUI content expression is bound to a local let only in DEBUG, then yielded
in the same position with the same concrete type. No Group, AnyView, extra View,
scene ID, SceneBuilder change, explicit builder return, or StateObject change is
introduced. In a DEBUG process without the existing enabled observer, the optional
calls stop at the nil shared instance; no checkpoint state, log record, clock,
window/property query, timer or task is created by these hooks. The original
existing DEBUG view expression is preserved modulo its equivalent local binding.
The two edited Swift files' Release projections are byte-identical to ea9.
These are source-level equivalence checks, not a native binary-equivalence claim.

## Bounds and evidence

Each enum value is inserted into a private first-hit set before recording, so
an omitted/late checkpoint cannot be retried. The four rows contain only the
existing identity, sequence, elapsed/epoch and omission fields. They deliberately
omit the app census: no additional NSApp.windows or other AppKit/AX query runs
while evaluating the Scene or View. Only those four names may omit app before
the deadline. Old event payload rules, source/run/PID/token/product/time binding,
and the late-final rule remain unchanged. Duplicate checkpoint names for one
PID/token are invalid evidence, even if their sequence numbers differ.

Existing limits are not increased: 23 non-final plus one final record per launch,
4,096 bytes per record, 8,192 pre-final/12,288 total producer bytes, observation
through ten seconds with the same 1/5/final-10 callbacks, 512-KiB raw/128-KiB
projected log capture, 30-second query and 3,000,000-byte retained packet.
The extra rows consume existing headroom; later records can be omitted. First-hit
means once per process, not per WindowGroup instance or scene generation.
A missing checkpoint, omitted prefix or missing final record is unknown.
Checkpoint presence alone never establishes a visible workspace or contact pass.

ColorWindow.swift is added to the existing diagnostic source-file hash binding.
The original workflow, controller, XCTest file, build settings, model ownership,
locale/reset arguments, launch order, original contact assertions, budgets and
acceptance guards are unchanged. The closed passive parser recognizes the four
metadata-only records, and the source contract's whole-file hash is updated for
this intentional DEBUG-only instrumentation. A separate fixture pins original
Release/debug projections and protected source bytes.

## Proposed one-case native diagnostic, not implemented or authorized here

The sole proposed runtime question is which content-evaluation boundary is
positively observed in the unchanged English contact failure. On one disposable
standard xcode-27 arm64 runner, pin macOS 27.0/26A428 and Xcode 27.0/27A266a,
build the original Debug scheme for testing, then execute exactly the existing
English contact method once. Reuse its exact-product setup, valid token/suite,
English/reset arguments, teardown, no parallel testing, 120-second case allowance,
and existing 300-second command plus 20-second owned host-cleanup reserve. Retain
the same bounded original passive log interval and original assertions. No new
AppKit delegate, forced activation/window, retry, locale change, restoration
mutation, extra launch, AX query, screenshot, or longer wait is proposed.

The command shape is the unchanged base_command() plus test_command() from
scripts/mac_launch_comparison.py, with the sole -only-testing selection:
TouchColorMacUITests/TouchColorMacUITests/testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail.
Preparation, compilation, exact product identity, source/receipt hash binding,
known cleanup and evidence admission must all remain prerequisites. Stop after
that one case and its owned cleanup/bounded historical evidence. Unknown or late
operations keep their stop fences; they do not permit recovery launches.

Important: no single-case workflow/driver is added by this packet. The unchanged
mac-launch-comparison workflow and coordinator still run XCTest then NSWorkspace;
invoking or pushing to that branch would therefore exceed this new one-case plan.
A separately reviewed fixed single-case entrypoint and exact job identity are
required before any publication/native admission. Do not run the old coordinator
as a substitute, and do not repurpose canonical release acceptance.

Interpretation is limited:
- Positive sceneBody without later retained checkpoints narrows the observed
  boundary but, by itself, does not prove that the later work never happened.
- Positive windowContentReturned proves construction of the value, not body
  evaluation, layout, native attachment, presentation or a source repair.
- Positive colorWindowBody plus no existing markerMapped/window census leaves
  native attachment unresolved.
- If instrumentation makes the original failure disappear, the causal result is
  inconclusive. Keep the actual case result honestly, but do not call this a fix
  or release qualification. Existing Mac audits and other blockers remain open.

## Local verification

The focused suite contains source projection/invariant checks and synthetic
producer/parser cases. Those model first-hit repetition, no enabled observer,
stopped observer, exact/late deadlines, record/byte exhaustion, duplicate records,
closed event payloads, PID/token/path/time mismatch, missing historical records,
and no inferred readiness or acceptance. The related original diagnostic,
scheduling, cleanup, retention and budget suites must also pass normally and with
Python optimization, followed by clean patch replay and exact tree verification.

There is no Swift compiler/AppKit SDK in this executor. Native SwiftUI result-
builder compilation, actual macOS logging and runtime behavior remain unrun.
No workflow, remote ref, release artifact or user computer is changed by the
local review. This file is a proposal, not permission to execute it.
