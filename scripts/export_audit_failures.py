#!/usr/bin/env python3
"""Export at most two synthetic mini images, preferring actual functional failures."""
import base64
import json
import pathlib
import subprocess


def records(value):
    if isinstance(value, dict):
        if 'exportedFileName' in value:
            yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def export_named(suite, names):
    result = pathlib.Path('build', 'iPadMini-' + suite + '.xcresult')
    if not (result / 'Info.plist').is_file():
        return 0
    destination = pathlib.Path('build', 'mini-evidence', suite)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result), '--output-path', str(destination)], check=True)
    manifest = json.loads((destination / 'manifest.json').read_text())
    count = 0
    for name in names:
        matches = [item for item in records(manifest) if name in ' '.join(v for v in item.values() if isinstance(v, str))]
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


failures = export_named('TouchColorUITests', ['touchcolor-ipad-functional-failure-1', 'touchcolor-ipad-functional-failure-2'])
if not failures:
    export_named('AccessibilityAudits', ['touchcolor-mini-audit-photo-state', 'touchcolor-mini-audit-saved-state'])
