# One Watch Edit-a-Copy observation candidate

This is a local diagnostic candidate on sole parent
`74ccaa93ae3f0cb5d0a63f6957460e9e8e576add`. This successor has not run natively.
It does not fix or qualify Watch behavior, and it does not affect the separately
qualified original iOS signing candidate.

## Question and retained evidence

In run 37385172706, both Watch sizes reached the saved color and entered Edit a
Copy. The 40 mm case then waited for XCTest's idle notification from test time
31.67 to 91.71 seconds; the 49 mm case waited from 59.25 to 119.28 seconds. Both
ended at the existing 120-second test limit. A main-thread deadlock, continuing
framework activity and an automation idle-notification failure are not
distinguished. The first editor exhausted the process-wide visible-focus log
bucket before the copy editor appeared.

This candidate asks what the real application's stacks and screen show during
that one interval. It selects SE 3 / 40 mm on watchOS 27.0, where the historical
copy appearance occurred earlier. It does not repeat Home Crown calibration,
the full Watch suite, other sizes, paired transfer or the platform matrix.

## App and test preservation

Only the existing DEBUG diagnostic implementation in WatchViews.swift changes.
Each of the existing 16-event visible/hidden focus buckets is divided into
eight observations for the first editor and eight for the second. At most two
IDs and four focus counters are retained. Reappearance of an existing ID does
not reset its allowance; third and later IDs receive no focus allocation.
Lifecycle32 and visible/hidden writeback16 limits remain unchanged. Dropped
counts reflect actual omitted events.

The entire WatchWorkflowTests.swift file is byte-identical to the parent.
Production bindings, focus requests, visibility, selection, save/delete,
navigation, quiescence, interruption handling and the 120-second case allowance
are unchanged. Everything outside that DEBUG diagnostic block in WatchViews
is byte-identical too. No project or dependency change is needed.

## Fixed observation sequence

The controller continuously drains XCTest stdout and stderr using a selector;
it does not stop draining the test while another command executes.

1. Run the existing touch Edit-a-Copy case exactly once. No warmup test or second
   launch is added. Cold startup can therefore prevent reaching Copy; that is
   reported as an observation gap rather than retried.
2. Observe the existing XCTest `Tap watch.edit.copy` output. Wait five seconds
   only to admit observation of a persisting action window. This delay is not
   app settling logic and cannot make a test pass. If the subsequent component
   button action or case end is already observed, do not start observation.
3. Make one case/subsystem-filtered log query on the newly created owned Watch.
   Require two distinct editor appearances, the first editor's intervening
   disappearance, active count one and a single actual app PID, within this
   test's time window. Appearance is not proof of rendering or responsiveness.
4. Read that exact PID with `ps`. Require its executable path inside this owned
   Watch's app container. Compare installed Info.plist, executable and optional
   Debug dylib bytes with this run's built product. Never select by process name
   alone, use a PID from a previous run, or fall back to another process.
5. Invoke `/usr/bin/sample` once for one second at a 10 ms interval. Its report
   goes to a bounded stdout pipe. Require its reported PID and executable path
   to match. Re-read PID/start-time/path/product bytes afterwards; changed or
   missing identity makes the sample inconclusive and prevents its retention.
6. Capture one PNG into an exclusive, newly owned temporary directory, using the
   explicit file-path form already used by capture_simulator_checkpoint.py.
   Do not interpret `-` as stdout or use help text as execution evidence. Only
   after exit0, closed pipes and confirmed producer-group exit, read a regular
   single-link file without following symlinks, at most300,001 bytes. Require
   stable directory/file identity and size, complete CRC-checked PNG structure
   and the324 ×394 display size. Retain at most300,000 actual bytes. Remove the
   owned temporary file only after retention and another live-state guard;
   uncertain output remains outside the artifact for disposable-VM teardown.
   Pixels still need review; capture success does not prove the expected editor.

No observer sends UI input, performs an AX query, changes focus, injects code,
pauses/resumes the app, changes a security setting or uses elevated privileges.
The PID-only sampling API cannot make process identity atomic; pre/post identity
checks and the report header detect observed disagreement, not an impossible
guarantee against all PID-reuse races. Permission denial is a stop, not a reason
to change security or use another route.

## Time, output and ownership bounds

One standard `xcode-27` job, 35-minute ceiling, no matrix or retry. Its immutable
monotonic clock starts before checkout. The work ceiling is 1,620 seconds after
reserving startup30, cleanup130, evidence180, validation60, upload60 and
overhead20 seconds. Phase ceilings are preflight60, build420, setup600 and
test300, totaling 1,380 seconds; preceding checkout/portable checks consume the
remaining work headroom. These ceilings are admission limits, not promised
completion times.

Preparation on a new disposable host keeps the phone's now-observed direct
`simctl bootstatus UUID -b` route (200 seconds), then uses the historical Watch
sequence: one `simctl boot UUID` (180 seconds), followed by one
`simctl bootstatus UUID -b` (180 seconds). One final20-second device inventory
must show both exact UUIDs, runtimes and device types available and Booted.

Every call must admit its complete allowance plus four seconds for owned
cleanup against the same absolute setup600-second deadline. Creation and pair
operations have150 seconds of nominal allowances; startup/inventory has580.
The nominal total730 exceeds600, so these are not all independently consumable:
only an early return leaves room to admit the next full call. No deadline is
reset and no later phase is borrowed. If a full window cannot fit, the route
stops before that command. No loop, alternate route or timeout retry is added.

The retained historical 40 mm run37385172706 had separate Watch boot55.588
seconds and bootstatus73.268 seconds, both exit0; the49 mm row took78.639 and
95.258 seconds. Its Watch boot cap was180 seconds. The predecessor run37555464740
successfully built, created and paired devices, and completed the phone's
direct bootstatus in57.497 seconds. Inventory/create/pair preparation took
about2.879 seconds. Its direct Watch bootstatus did not close in200 seconds;
the host group was cleaned up, simulator completion stayed unknown and no
final inventory or UI case ran. That host is never reused.

Combining the measured preparation/phone durations with the historical40 mm
Watch durations and20 seconds for inventory totals about209.2 seconds. This
cross-run arithmetic supports admission inside600 seconds; it is not proof that
this new host will complete. The new complete sequence remains untested
natively. Every timeout, nonzero exit, cancellation or failed final identity
check still prevents subsequent simulator commands and cleanup.

The selected case keeps its 120-second allowance. The Xcode command cap is 280
seconds inside the 300-second phase, permitting cold installation/startup while
not increasing the case limit. The observer chain has one 35-second ceiling
inside that same phase: log query5, PID3, sample6, PID3, screenshot8. Admission
also requires all35 seconds plus four seconds of owned cleanup before the
earliest of three boundaries: the existing absolute `Start Test at` timestamp
mapped to host monotonic time, the latest emitted XCTest relative elapsed time,
and the host-observed case-start boundary. The retained native log contains the
absolute timestamp, so this adds no application/test instrumentation. Missing,
future or unbound timestamps and wall/monotonic disagreement beyond50ms refuse
observation; the50ms margin is subtracted, never added to the allowance. A
buffered t=110 event cannot receive a fresh35-second window. A late Copy action
produces an explicit no-observation result. XCTest independently enforces its
actual120-second timer. Every new
observer also requires four seconds of remaining owned-process cleanup time.
The original Xcode producer's280-second command deadline is also an admission
ceiling, even when the outer300-second phase has more time left. No incomplete
allowance is silently shortened to start work.

At most XCTest and one observer are active together. Each is a separately
created host process group. On a timeout, cancellation, byte cap, missing
identity, parse failure, unclosed case or ambiguous completion, a persistent
stop record is written and only these owned host groups are cleaned up, with
two two-second TERM/KILL stages each. Repeated cancellation remains deferred
through that cleanup. The sampled app PID and simulator daemon are never
signalled. No new simulator, sample, PID, result-reader or cleanup command is
launched after uncertainty. The disposable VM then owns final teardown.

Every observer handoff drains currently readable XCTest events and polls the
original Xcode process before admission, then repeats those checks after
durable persistence and immediately before Popen. A dead Xcode process cannot
start observation while a descendant still holds its output pipe open. A
cancellation during persistence cannot start a producer. Cancellation state is
shared with the owning controller through session close, so later device
cleanup is also prohibited even if the last signal arrives during final save.

After an ordinary, fully closed command/case, cleanup may shut down, unpair and
delete only this invocation's two created devices/pair. Any cleanup failure
sets the same stop barrier before the next command. The source does not claim
that killing a host client cancels a simulator-side operation. A kernel-blocked
process creation or filesystem syscall is not a hard real-time guarantee;
the outer disposable-job deadline remains the final bound.

The artifact limit is 1,200,000 bytes. Test output is capped jointly at256KiB;
log query64KiB; sample256KiB; each PID read4KiB; screenshot diagnostics4KiB and
its separately bounded PNG file300,000 bytes. Metadata
and manifest have separate bounds. Pipes are capped while reading, not only
after a producer exits. Uncertain or unbound samples are not retained as valid
stack evidence. Subsequent artifact preparation uses local files only.

## Interpretation and native gaps

External sampling, screenshots and even logging have nonzero overhead. This is
bounded low-interference observation, never a zero-perturbation claim. A case
that passes while observed does not qualify the original unobserved flow.
The driver always returns a diagnostic-only nonzero exit and acceptance=false.

Portable tests cover the fixed case/clock, unchanged UI source and Release
projection, bounded focus allocation source contract, exact lifecycle/PID/
product binding, image structure, no-following-command barriers, and real Python
child-process multiplexing, late/buffered case time, exited-process open pipes,
SIGTERM during admission persistence/session close, readable case-end during
handoff, output floods, terminal file capture and owned cleanup.
They do not execute Swift, Apple tools, a simulator or the product. No targetless
sample/help probe precedes the real flow; the only sample invocation is bound to
the observed application PID and must return0 under its existing limits. The DEBUG
Swift change, installed-product byte comparison, sample report
format and actual native file capture still require the one separately
approved native job. No automatic alternative or repeat is provided if they
differ.

Apple's sample documentation describes statistical stack observations and their
interpretation limits: [Diagnosing Slow Operations](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/CodeSpeed/Articles/DiagnosingSlowness.html).
