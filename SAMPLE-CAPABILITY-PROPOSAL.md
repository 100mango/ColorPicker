# Owned `sample` capability probe: source-only v2

## Status and evidence

Base: public `a6ea406d51e38319b76d19a5a5417b72cec857f4`, exact tree
`a7bd3221991f9212094dda27ad5ff595624c5b9a`. The isolated copy preserves tracked
ignored files and has its own object database; the original `.git` pointer was
not copied. The original index and working contents remain unchanged.

**No Mac execution admission.** This packet was neither integrated nor run on a
Mac. It changes no workflow, ref, concurrency, job allowance, assertion, Watch
code, or existing 2,000,000-byte Watch evidence cap. Portable tests use only owned
synthetic producers. There is no Watch PID interface, name discovery, system
inventory, `sudo`, permission prompt, security/entitlement change or fallback tool.

Primary sources, reviewed on 2026-10-04:
- [Apple: Diagnosing Slow Operations](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/CodeSpeed/Articles/DiagnosingSlowness.html)
  describes process-specific periodic sampling and textual call-stack reports.
- [Apple: Gathering Launch Time Metrics](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/LaunchTime/Articles/MeasuringLaunch.html)
  gives historical seconds/milliseconds argument order and explains `-mayDie`.
  Both performance guides are retired. They do not prove current syntax, access,
  authorization-UI behavior, or output grammar; their examples are not executed.
- [Apple: getrlimit(2)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrlimit.2.html)
  documents inherited limits and failed writes/`SIGXFSZ` at the regular-file limit.
  The launcher sets and verifies soft+hard limits before exec. Actual Darwin
  enforcement still requires the synthetic boundary tests on the selected Mac.

## Implemented phase and strict bounds

The only opt-in operation invokes fixed `/usr/bin/sample` with **zero arguments**:
no guessed help flag, PID, name, sampling flag, or variant. The source-owned
Python launcher uses `-I -S`, a minimal environment and no shell or `preexec_fn`.
Closed stdin/no terminal/no `sudo` are safeguards, not proof of noninteractive
capture. Every current report keeps live capture unavailable; there is no override.

- Hard+soft `RLIMIT_FSIZE`: 64,000 bytes per regular file; core-file limit zero.
  This does not bound pipes, file count, total disk usage or internal memory.
- Combined stdout/stderr reader: 32,000 retained bytes; <=4,096-byte reads and at
  most one discarded overflow byte. Limit acknowledgement: 13 bytes, separately
  bounded. Five-second producer deadline; cleanup adds 0.1-second TERM grace
  and at most one second for KILL/reap/absence checks. No `communicate` is used.
- Help retention: entire exact UTF-8 text, <=12,000 input bytes. It requires
  complete/identity/limit/cleanup gates, a usage response on the first nonblank
  line, and printable text plus tabs/newlines/CRLF. Invalid UTF-8, controls,
  unknown, oversized or partial help is wholly omitted with an explicit reason.
- Serialized JSON: <=32,000 bytes including Unicode escaping. If full text cannot
  fit, omit it entirely. Never promote a prefix as complete. Only this report is
  retained by phase 0; any later packet remains <=128,000 retained bytes without
  expanding or borrowing from the unchanged Watch allowance.
- Tool binaries and launcher source reject symlink ancestors, aliases, hard links,
  special files, unsafe ownership, writable ancestors, group/world write and
  setid modes. Launcher source need not have an executable bit. The work directory
  must be canonical, current-owned and private. Identities are held by descriptor
  and checked before launch/after cleanup; the launcher rechecks before exec.
- The session leader stays unreaped while TERM/KILL signals are sent, preserving
  PID/PGID identity. After reap only absence is observed; no more signals. Unknown
  cleanup blocks success. Approved producers must not escape their owned group.
- Complete-source size/hash is emitted only after all completeness gates. Partial
  streams have `sha256: null`; exactly-at-pipe-cap input is incomplete. A complete
  source too large/unknown to retain may still have its complete hash, while
  `textComplete: false` explicitly records whole-text omission.

This is groundwork for the fixed Apple tool, not an adversarial-executable
sandbox. Source/tool files must not be concurrently modified. No actual installed
syntax, no-prompt capture path, authentic stack format or Watch cause is verified.

## Separate later gates

1. **Capture gate:** review actual bounded installed help and relevant installed
   documentation. Require one supported syntax adapter and a documented
   noninteractive same-user capture path. If either is unproved, stop before
   creating/targeting a fixture. Do not try variants or answer authorization UI.
2. After that gate, a separately reviewed adapter may create exactly one fresh
   source-owned synthetic child with verified executable identity, private
   readiness pipe and fixed bounded work. Only its still-live direct-child PID
   may be used; no caller PID/name lookup. Keep it alive until sampling completes.
   This first safe capture may provide the authentic specimen; there is no
   circular requirement to have that specimen before the first capture.
3. **Extraction gate:** complete-main-thread extraction needs that authentic,
   matching specimen and independent validation. Initially retain only capability
   metadata and, if validated, the fixture symbol allowlist (`tc_probe_root`,
   `tc_probe_branch`, `tc_probe_leaf`); otherwise explicit format unavailable.
   Omit raw stacks, addresses, binary images, runtime paths and unrelated symbols.
   Unknown, ambiguous, missing or truncated stacks never count as an empty success.

No future fixture, capture adapter, stack parser or raw-file receipt helper is
implemented. A later adapter must constrain output to one private bounded report
file and reject side files. The fixture must have no file/network/fork/app APIs.

## Verification and possible later operator step

From `scripts`, run `python3 -m unittest -v test_sample_capability_probe` and
`python3 -O -m unittest -v test_sample_capability_probe`. The cloud Python runtime
is a read-only mount owned by UID 65534; tests explicitly admit that test-only
owner while the Mac CLI retains root/current-owner checks. Linux tests do not
prove Darwin limits, Apple tool behavior, capture access, format or Watch results.

Only after independent review and separate Mac-run authorization, the proposed
CLI is `python3 scripts/sample_capability_probe.py --inspect-installed-help
PRIVATE_DIRECTORY` on one line. Use an already verified canonical interpreter
and private directory; aliases are rejected rather than silently resolved.
Preserve omission/identity/cleanup fields and retain no output beyond the gated
report. This packet authorizes no CI launch, workflow addition or capture.
