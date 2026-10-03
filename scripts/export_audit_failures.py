#!/usr/bin/env python3
"""Export bounded per-device evidence within one source-defined run envelope."""
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess

# All four fresh hosts use these same checked-in allocations and exact-source proof.
# Five JPEGs at most; reserve base64 and chunk/metadata overhead within 20 MiB.
ALLOCATIONS = {'iPadMini': 2, 'iPadLarge': 1, 'iPhoneCompact': 1, 'iPhoneLarge': 1}
MAX_IMAGE_BYTES = 500 * 1024
MAX_RUN_LOG_BYTES = 20 * 1024 * 1024
RESERVED_LOG_BYTES = sum(ALLOCATIONS.values()) * (4 * ((MAX_IMAGE_BYTES + 2) // 3) + 16 * 1024)
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
        subprocess.run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result), '--output-path', str(destination)], check=True)
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
        count += 1
    return count


# One first failure per non-mini row. Mini retains a distinct audit failure
# alongside a functional failure before filling spare slots with passing states.
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
    count += export_named('AccessibilityAudits', ['touchcolor-mini-audit-photo-state', 'touchcolor-mini-audit-saved-state'], limit - count)
if family in ('iPhoneCompact', 'iPadLarge') and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-review'], limit - count)
if family == 'iPhoneLarge' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-watch-inbox-status'], limit - count)
assert count <= limit
print('EVIDENCE_IMAGES:' + json.dumps({'family': family, 'count': count, 'allocation': limit}))
