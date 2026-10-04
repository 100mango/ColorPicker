#!/usr/bin/env python3
"""Fail-closed final upload guard, independent from xcresult export/attachment trimming."""
import json, os, re, stat, sys
from pathlib import Path
root = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/evidence')
maximum_total = int(sys.argv[2]) if len(sys.argv) > 2 else 8000000
if not 0 < maximum_total <= 8000000:
    raise RuntimeError('Invalid evidence limit')
if not (root.is_dir() and (not root.is_symlink())):
    raise RuntimeError('Missing or symlink evidence root')
allowed_root = {'architecture.txt', 'accessibility-api.json', 'mac-sandbox-entitlements.json', 'mac-sandbox-post-entitlements.json', 'vision-ui-summary.json', 'watch-ui-summary.json', 'mac-unit-summary.json', 'mac-ui-summary.json', 'mac-sandbox-summary.json', 'ios-equivalence-summary.json'}
allowed_root.update((f'{p}-{suffix}.json' for p in ('vision', 'watch', 'tv') for suffix in ('summary', 'runtime')))
allowed_root.add('mac-modal-probe-summary.json')
allowed_dirs = {'screenshots', 'vision-checkpoints', 'sandbox-screenshots', 'vision-ui-screenshots', 'vision-screenshots', 'watch-screenshots', 'watch-ui-screenshots', 'tv-screenshots'}
allowed_dirs.add('modal-probe-screenshots')
allowed_dirs.update({'paired-phone-screenshots','paired-watch-screenshots'})
allowed_root.update({'paired-runtime.json','paired-phone-summary.json','paired-watch-summary.json'})
total = 0
count = 0
text_files = set()
approved_text_files = set()
for folder, dirs, files in os.walk(root, followlinks=False):
    directory = Path(folder)
    for name in dirs:
        path = directory / name
        if not (directory == root and name in allowed_dirs and (not path.is_symlink())):
            raise RuntimeError(f'Unexpected evidence directory: {path}')
    for name in files:
        path = directory / name
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            raise RuntimeError(f'Not an independent regular file: {path}')
        if directory == root:
            if not name in allowed_root:
                raise RuntimeError(f'Unexpected evidence file: {path}')
        elif not (name == 'manifest.json' or re.fullmatch('[0-9A-Fa-f-]{36}\\.(png|jpg|jpeg|txt)', name)):
            raise RuntimeError(f'Unexpected attachment: {path}')
        if directory != root and path.suffix == '.txt':
            if not info.st_size <= 256000:
                raise RuntimeError('Oversize accessibility diagnostic')
            text_files.add(path)
        if not info.st_size <= 5000000:
            raise RuntimeError(f'Oversize evidence file: {path}')
        total += info.st_size
        count += 1
        if not total <= maximum_total:
            raise RuntimeError('Evidence exceeds total byte budget')
        if name == 'manifest.json':
            for group in json.loads(path.read_text()):
                for item in group.get('attachments', []):
                    exported = item['exportedFileName']
                    if not re.fullmatch('[0-9A-Fa-f-]{36}\\.(png|jpg|jpeg|txt)', exported):
                        raise RuntimeError('Invalid manifest path')
                    if not (directory / exported).is_file():
                        raise RuntimeError('Manifest references missing evidence')
                    if exported.endswith('.txt'):
                        if not item.get('suggestedHumanReadableName', '').startswith('Native Mac accessibility issue'):
                            raise RuntimeError('Unexpected text attachment provenance')
                        approved_text_files.add(directory / exported)
                    if not item.get('suggestedHumanReadableName', '').startswith(('Native Mac', 'Native Vision', 'Native Watch', 'Native TV', 'touchcolor-paired-phone')):
                        raise RuntimeError('Unexpected attachment provenance')
if not text_files == approved_text_files:
    raise RuntimeError('Unmanifested accessibility text attachment')
if not count:
    raise RuntimeError('No bounded evidence to retain')
print(f'Final evidence guard passed: {count} files, {total} bytes (including final manifests)')
