# Corrected TouchColor unsigned platform qualification

## Current local proposal: TV missing-screenshot diagnostic

The sections below preserve the original closed-overlay design history. The current
proposal is a separately reviewed control-only child of actual control
`e5d10fb1949f6483c807ef91d8f7f2850fae9738`, bound to product
`7c671f04e4d69884741a411851ae26083361c7f7` / tree
`f477c19b8181c4e3eb2142beaef4dea742cca0cd`. Root alone may publish or activate it.
The active proposal selects only `tv-secondary-missing-screens`; its separate
closed template has READY=false and a literal false job. Neither local template
has run. The original19-row inventory is unchanged; this explicit diagnostic
alias reuses the TV25-minute/2,000,000-byte row without changing any reserve.

The source-derived full TV inventory is45 tests (40 hosted,5 UI), not9. Run
37941182061 passed all45 with zero failures/skips/expected failures, but CI failed:
the old9-count oracle was wrong and four required images were removed by generic
retention. All8 original images alone total2,490,411 bytes. That historical run
stays failed; its four retained original images and four audits remain separate
immutable evidence.

The diagnostic selects exactly these existing UI methods and no hosted tests:
- TouchColorTVUITests/TVWorkflowTests/testRemoteColorEditorAndMenuReturn
- TouchColorTVUITests/TVWorkflowTests/testChineseRemoteColorEditor

It retains the new raw Privacy-empty, About-populated, About-zh-normal and
Privacy-zh-normal images plus all four strict About audit receipts. Duplicate
states and primary screenshots are explicitly optional only in this diagnostic;
all omissions retain their original hash/size/name/method in the runtime receipt.
No image transformation or ceiling increase is allowed. If mandatory proof does
not fit, it fails without deleting mandatory files. Full qualification continues
to require all45 tests and all8 images; the diagnostic cannot satisfy that gate.

The workflow derives two ignored build scripts from exact frozen source hashes.
The native driver changes only its TV test selection/report statement; the budget
wrapper changes only its exact allowed cleanup-driver body. Exact derived byte
checks run before execution. Release/build-for-testing, cleanup, Photos seed,
1320-second outer declaration,660-second test cap,120-second per-test cap and all
original job-clock reserves remain. The host/runtime gate requires either full45
with no selector or diagnostic2 with the exact two selectors, matching runtime,
source, actual host pair and summary/device counts. Separate post-upload gates
require runtime completeness and all four raw images/four audits. A composed
review joins per-run/product/source/hash provenance; it is not one green full run.

---

This is a local-only, deliberately closed workflow overlay. It has not been pushed,
registered, dispatched, or run on Apple hardware. A disabled/skipped workflow is
not a successful qualification. The starting snapshot is the corrected Run 6
candidate tree `48f2ca5afaee461ae43a5c083b9aeea311b36089`; this is background, not
an activation binding. The final corrected product parent must include the owner's
subsequent iOS fixes. No historical product commit is selected by default.

## Closed admission

- New branch: `touchcolor-platform-qualification`.
- New workflow: `.github/workflows/platform-qualification.yml`. Its only trigger
  is a push to that exact branch changing `.github/platform-qualification.json`.
  No workflow-dispatch connector, browser, token, or default-branch workaround is
  needed or used.
- Two independent local locks: literal `if: ${{ false }}` in the sole native job and
  `READY: false` in that JSON configuration. A closed/skipped run is not a pass.
- The JSON product SHA/tree are `UNBOUND` and `selected_lane` is `unselected`.
  Root must fill the final corrected product bindings and one lane, check runner
  capacity, and explicitly set READY true before authorized publication. The
  final control commit SHA/tree are never put into their own checked-in config.
- The actual workflow SHA, event SHA and checkout SHA must agree. The runtime
  records actual control SHA/tree alongside the exact product root SHA/tree.
  Root separately verifies the published control SHA.
- A bounded linear chain of at most 32 control commits must lead to the exact
  product root. Checkout uses fixed depth 64 and never fetches arbitrary history.
  Every transition rejects merges and product changes, including an edit later
  reverted. Aggregate differences must be exactly the seven overlay paths. The only
  allowed existing-code change is the exact new push-route identity in Mac
  evidence admission. Every control commit must retain that exact edit and
  ordinary 100644 control-file modes. The exact existing workflow-identity count
  regression is updated from two to three, with its old event checks preserved. Historical assertions, retention budgets,
  app/project/version/signing files and workflows remain untouched.
- There is exactly one job on `xcode-27`. Source admission is its first
  post-checkout step, inside the unchanged native-row timeout. No extra queued
  admission job consumes a public/private capacity slot.
- After filling the JSON, root runs `python3 scripts/platform_qualification.py
  prepare` locally. It replaces only the marked selector block with exactly one
  original inventory row and its exact budget. READY=false renders a literal
  false job and an unselected placeholder, so it cannot allocate a native runner.
  Admission independently compares that baked selector against the JSON before
  any native build or test. No separate admission job is created.
- The 19-row inventory is read from unchanged `apple-platforms.yml`. One of 17
  eligible rows is emitted, with original timeout/evidence budgets. The legacy
  iOS and paired rows are preserved in that inventory but rejected by admission.
- No GITHUB_* identity variable is overwritten. Runtime evidence identifies the
  current control commit; logs and the job summary record its exact corrected
  product root/tree. Product bytes are identical to that root.

## Existing checks reused

Exactly one job definition exists. No real lane is selected in this delivered
READY=false packet. Local preparation preserves the original selected row's
limits: Mac 40 minutes / 3,000,000 bytes; TV 25 minutes / 2,000,000 bytes;
Vision 25 minutes / its existing 650,000–1,300,000-byte row allowance (700,000 for
system-largest rows); Watch 45 minutes / 1,200,000 bytes normal or 600,000 bytes
system-largest. The complete exact inventory is recorded in the receipt. The
closed placeholder's one-minute/zero-byte values never authorize execution.

TV, Vision, and Watch each run the original command, under the original bounded
job driver and budgets:

- `python3 scripts/test_extra_platforms.py tv`
- `python3 scripts/test_extra_platforms.py vision`
- `python3 scripts/test_extra_platforms.py watch`

Each existing command performs generic-device Release build, actual package
identity/version/minimum-OS/privacy/assets checks, linked-library and Release
seam checks, simulator build-for-testing, hosted unit tests, and the native UI
case(s) belonging to that exact row. It passes `CODE_SIGNING_ALLOWED=NO`. No UI
case, text-size/profile row, screenshot assertion, timeout, or evidence ceiling is
relaxed. The Watch harness's owned simulator pairing is a runtime prerequisite;
it is not proof of corrected iOS embedding or actual app transport.

Mac reuses the existing commands and assertions verbatim:

- `swift test --package-path Packages/ColorCore --scratch-path build/package`
- Generic macOS arm64 Release build with `ARCHS=arm64 CODE_SIGNING_ALLOWED=NO`,
  resolved Release-setting, privacy, bundle identity, binary and test-seam checks.
- Existing optional x86_64 Release compile; failure remains separately visible and
  never proves Intel runtime.
- `TouchColorMacTests` hosted Debug tests and `TouchColorMacUITests` native UI tests
  with `CODE_SIGNING_ALLOWED=NO`; existing separate standard AppKit diagnostic
  tests retain their diagnostic-only status.
- Existing evidence retention, path/byte validation, five original correlated
  audit PNG requirements, source provenance, and final complete-evidence gate.

The new workflow copies the current native job's control steps because the old
workflow is not a reusable workflow. Historical workflows remain byte-for-byte
unchanged and are never invoked by this route. It does not run the old all-platform
prerequisite job, whose paired-phone embedding check cannot certify the corrected
product. Each selected native command still compiles its own real prerequisites.

## Explicitly deferred or blocked

- Mac ad-hoc sandbox execution, in-process container/read-write boundaries, and
  pre/post sandbox entitlement proof are not run in strict unsigned scope.
  `test_mac_sandbox.sh` is not called. The original full Mac evidence gate is
  intentionally unchanged and remains incomplete because its three sandbox
  records are missing. A successful build/unit/UI stage is only that narrower
  stage's result, never a green full Mac qualification. No substitute completeness
  validator is introduced.
- Corrected iOS Watch-container packaging and paired foreground transport are
  not established here. Legacy iOS/paired rows cannot launch. Physical background
  Watch transport and real Photos/camera/radio coverage remain separate gates.
- No archive/export, real signing, identity/capability registration, notarization,
  Store release, or version bump occurs. Standalone unsigned package checks are
  not release/distribution approval.
- The existing toolchain assertion requires runner `xcode-27`, macOS build
  `26A428`, Xcode `27.0` / `27A266a`, and arm64. Availability has not been checked by
  this local preparation. Apple builds/runtime tests were not run on Linux.

## Root activation plan (not performed)

1. Finish and validate the corrected product, record its actual commit SHA/tree,
   and create `touchcolor-platform-qualification` from that exact commit.
2. Apply this seven-file overlay. Fill the config with that root SHA/tree and exactly
   one lane. Review every control-only diff and remaining native blocker, and
   check the public active-plus-queued cap of four, keeping the private slot reserved.
3. Only with activation authorization, set JSON READY true and run
   `python3 scripts/platform_qualification.py prepare` locally. Verify that only
   the intended row is baked, with its original timeout/evidence budget. Commit
   the complete overlay as a direct child of the product root, then publish this exact branch. The exact branch/config-path push launches
   only the selected row. Root verifies the remote publication SHA against the
   intended local/control commit and the workflow's reported SHA/tree.
4. Wait for the run's terminal result. Review the exact native stage outcomes,
   small artifact, omission records and original acceptance gates. Workflow-level
   concurrency serializes runs, but do not prequeue the whole matrix.
5. A later explicit lane selection updates the config and reruns the local
   prepare command before committing those two control files on the same branch. It is allowed only while the same verified product root remains
   in the bounded 32-commit chain. No rebase, force-push or alternate old product
   is needed. All 11 Vision and four Watch rows remain in the required inventory.
6. Keep Mac's full sandbox-inclusive gate and corrected Watch container/transport
   blocked until their separately authorized evidence exists. If app source needs
   a repair, stop this control-only chain and rebind a new reviewed product root;
   do not smuggle product changes into a lane-selector commit.

The local preparation repository contains synthetic snapshot/control commits for
portable checks only. They are not remotely published product provenance. Native
execution is still not run, and READY remains false in the delivered files.
