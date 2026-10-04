#!/usr/bin/env python3
"""Export bounded per-device evidence within one source-defined run envelope."""
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

# All four fresh hosts use these same checked-in allocations and exact-source proof.
# Eight JPEGs at most; include base64, metadata and bounded child diagnostics.
# Raw attachment manifests and result bundles are read locally, never emitted.
ALLOCATIONS = {'iPadMini': 2, 'iPadLarge': 2, 'iPhoneCompact': 2, 'iPhoneLarge': 2}
MAX_IMAGE_BYTES = 500 * 1024
MAX_RUN_LOG_BYTES = 20_000_000
MAX_EXPORT_DIAGNOSTIC_BYTES = 16 * 1024
MAX_EXPORTS_PER_DEVICE = 2  # Functional and accessibility result bundles.
MAX_RUNTIME_DIAGNOSTIC_BYTES = 32 * 1024  # One framed metadata record per device.
RESERVED_LOG_BYTES = (sum(ALLOCATIONS.values()) * (4 * ((MAX_IMAGE_BYTES + 2) // 3) + 16 * 1024)
                      + len(ALLOCATIONS) * (MAX_EXPORTS_PER_DEVICE * (MAX_EXPORT_DIAGNOSTIC_BYTES + 512)
                                            + MAX_RUNTIME_DIAGNOSTIC_BYTES))
assert RESERVED_LOG_BYTES <= MAX_RUN_LOG_BYTES
family = os.environ['TC_TEST_FAMILY']
assert family in ALLOCATIONS
limit = ALLOCATIONS[family]
print('EVIDENCE_BUDGET:' + json.dumps({'family': family, 'allocations': ALLOCATIONS,
    'maximum_image_bytes': MAX_IMAGE_BYTES, 'reserved_run_log_bytes': RESERVED_LOG_BYTES,
    'maximum_run_log_bytes': MAX_RUN_LOG_BYTES}, sort_keys=True))
exports = {}


def records(value):
    if isinstance(value, dict):
        if 'exportedFileName' in value:
            yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def export_named(suite, names, limit):
    if limit <= 0:
        return 0
    result = pathlib.Path('build', family + '-' + suite + '.xcresult')
    if not (result / 'Info.plist').is_file():
        return 0
    if suite not in exports:
        destination = pathlib.Path('build', 'evidence', family, suite)
        destination.mkdir(parents=True, exist_ok=True)
        # A child's stderr can split a buffered SCREENSHOT_CHUNK in the Actions
        # stream. Keep all exporter diagnostics between complete envelopes.
        sys.stdout.flush()
        exported = subprocess.run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result), '--output-path', str(destination)], capture_output=True, text=True)
        diagnostics = (exported.stdout + exported.stderr).encode('utf-8')
        if diagnostics:
            bounded = diagnostics[:MAX_EXPORT_DIAGNOSTIC_BYTES].decode('utf-8', errors='ignore')
            print(bounded, end='' if bounded.endswith('\n') else '\n', flush=True)
            if len(diagnostics) > MAX_EXPORT_DIAGNOSTIC_BYTES:
                print(f'EXPORT_DIAGNOSTICS_TRUNCATED original_bytes={len(diagnostics)} limit={MAX_EXPORT_DIAGNOSTIC_BYTES}', flush=True)
        exported.check_returncode()
        exports[suite] = destination, list(records(json.loads((destination / 'manifest.json').read_text())))
    destination, attachments = exports[suite]
    count = 0
    for name in names:
        if count >= limit:
            break
        exact_name = re.compile(r'(?<![A-Za-z0-9-])' + re.escape(name) + r'(?![A-Za-z0-9-])')
        matches = [item for item in attachments if any(exact_name.search(value) for value in item.values() if isinstance(value, str))]
        if not matches:
            continue
        assert len(matches) == 1, f'Expected one {name}, found {len(matches)}'
        path = (destination / matches[0]['exportedFileName']).resolve()
        assert path.is_relative_to(destination.resolve())
        data = path.read_bytes()
        assert data.startswith(b'\xff\xd8') and len(data) <= MAX_IMAGE_BYTES
        encoded = base64.b64encode(data).decode('ascii')
        print('SCREENSHOT_META:' + json.dumps({'name':family+'-'+name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()},sort_keys=True))
        print(f'SCREENSHOT_BEGIN:{family}-{name}')
        for offset in range(0, len(encoded), 4096):
            print('SCREENSHOT_CHUNK:' + encoded[offset:offset + 4096])
        print(f'SCREENSHOT_END:{family}-{name}')
        sys.stdout.flush()
        count += 1
    return count


# Every device retains its first functional failure and first distinct audit
# failure before filling a spare slot with another failure or a passing state.
functional_prefix = 'touchcolor-ipad-functional-failure-' if family.startswith('iPad') else 'touchcolor-phone-functional-failure-'
count = export_named('TouchColorUITests', [functional_prefix + '1'], 1)
count += export_named('AccessibilityAudits', [
    'touchcolor-audit-failure-empty-compact', 'touchcolor-audit-failure-empty',
    'touchcolor-audit-failure-live', 'touchcolor-audit-failure-policy',
    'touchcolor-audit-failure-photo', 'touchcolor-audit-failure-saved',
    'touchcolor-audit-failure-import', 'touchcolor-audit-failure-inbox',
], limit - count)
if count < limit:
    count += export_named('TouchColorUITests', [functional_prefix + '2'], limit - count)
if family == 'iPadMini' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-review', 'touchcolor-watch-inbox-status'], limit - count)
if family == 'iPadMini' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-mini-audit-photo-state', 'touchcolor-mini-audit-saved-state'], limit - count)
if family == 'iPhoneCompact' and count < limit:
    count += export_named('TouchColorUITests', ['touchcolor-largest-paste-control-landscape'], limit - count)
if family in ('iPhoneCompact', 'iPadLarge') and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-review'], limit - count)
if family == 'iPhoneLarge' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-watch-inbox-status'], limit - count)
assert count <= limit
print('EVIDENCE_IMAGES:' + json.dumps({'family': family, 'count': count, 'allocation': limit}))
