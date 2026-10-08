#!/usr/bin/env python3
"""Export at most two synthetic mini images, preferring actual functional failures."""
import base64
import json
import pathlib
import re
import subprocess

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
    result = pathlib.Path('build', 'iPadMini-' + suite + '.xcresult')
    if not (result / 'Info.plist').is_file():
        return 0
    if suite not in exports:
        destination = pathlib.Path('build', 'mini-evidence', suite)
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
        assert data.startswith(b'\xff\xd8') and len(data) <= 500 * 1024
        encoded = base64.b64encode(data).decode('ascii')
        print(f'SCREENSHOT_BEGIN:{name}')
        for offset in range(0, len(encoded), 4096):
            print('SCREENSHOT_CHUNK:' + encoded[offset:offset + 4096])
        print(f'SCREENSHOT_END:{name}')
        count += 1
    return count


# Keep one functional failure and the first distinct audit failure when both occur.
# Never let one suite consume both slots before the other suite's failure is checked.
count = export_named('TouchColorUITests', ['touchcolor-ipad-functional-failure-1'], 1)
count += export_named('AccessibilityAudits', [
    'touchcolor-audit-failure-empty-compact', 'touchcolor-audit-failure-empty',
    'touchcolor-audit-failure-live', 'touchcolor-audit-failure-policy',
    'touchcolor-audit-failure-photo', 'touchcolor-audit-failure-saved',
], 2 - count)
if count < 2:
    count += export_named('TouchColorUITests', ['touchcolor-ipad-functional-failure-2'], 2 - count)
if count < 2:
    export_named('AccessibilityAudits', ['touchcolor-mini-audit-photo-state', 'touchcolor-mini-audit-saved-state'], 2 - count)
