#!/usr/bin/env python3
"""Synthetic regression checks for the independent, fail-closed upload allowlist."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from bounded_process import run_captured

guard = Path(__file__).with_name('validate_evidence.py')
checked = 0
def check(prepare, expected, limit=4_000_000):
    global checked
    with tempfile.TemporaryDirectory(prefix='touchcolor-evidence-guard-') as directory:
        root = Path(directory)/'evidence'; root.mkdir()
        prepare(root)
        result = run_captured([sys.executable, str(guard), str(root), str(limit)], timeout=10, text=True)
        assert (result.returncode == 0) == expected, (prepare.__name__, result.stdout, result.stderr)
        checked += 1
def valid(root):
    (root/'architecture.txt').write_text('arm64 synthetic check')
    (root/'mac-sandbox-post-entitlements.json').write_text('{}')
    directory = root/'screenshots'; directory.mkdir()
    name = str(uuid.uuid4()).upper()+'.txt'
    (directory/name).write_text('Synthetic accessibility issue, no user data')
    (directory/'manifest.json').write_text(json.dumps([{'attachments': [{'exportedFileName': name, 'suggestedHumanReadableName': 'Native Mac accessibility issue_0.txt'}]}]))
def unknown(root): (root/'unapproved.txt').write_text('synthetic')
def oversize(root): (root/'architecture.txt').write_bytes(b'x'*5_000_001)
def aggregate(root):
    (root/'architecture.txt').write_bytes(b'x'*3000)
    (root/'mac-ui-summary.json').write_bytes(b'x'*3000)
def symlink(root): (root/'architecture.txt').symlink_to(root.parent/'outside')
def directory_link(root): (root/'screenshots').symlink_to(root.parent, target_is_directory=True)
def hardlink(root):
    outside=root.parent/'outside'; outside.write_text('synthetic')
    (root/'architecture.txt').hardlink_to(outside)
def bad_manifest(root):
    directory=root/'screenshots'; directory.mkdir()
    (directory/'manifest.json').write_text(json.dumps([{'attachments': [{'exportedFileName': '../outside.txt'}]}]))
def unapproved_text(root):
    valid(root)
    manifest=root/'screenshots/manifest.json'; data=json.loads(manifest.read_text())
    data[0]['attachments'][0]['suggestedHumanReadableName']='Unapproved text'
    manifest.write_text(json.dumps(data))
def orphan_text(root):
    valid(root); (root/'screenshots/manifest.json').unlink()
def oversize_text(root):
    valid(root)
    next((root/'screenshots').glob('*.txt')).write_bytes(b'x'*256_001)
check(valid, True)
check(lambda root: None, False)
for prepare in [unknown, oversize, symlink, directory_link, hardlink, bad_manifest, unapproved_text, oversize_text, orphan_text]: check(prepare, False)
check(aggregate, False, 5000)
print(f'{checked} synthetic evidence-boundary checks passed')
