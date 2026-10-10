"""Filesystem-only precompile closure and exact new-route source admission."""
import hashlib
import math
import json
import os
from pathlib import Path
import re
import stat
import time

import io_boundary as io
from io_boundary import REPO, read, json_read

BASE = '84da71d3526426a6e630887dc88fed59e1edc055'
PRODUCT = '7c671f04e4d69884741a411851ae26083361c7f7'
BRANCH = 'touchcolor-mac-secondary-qualification'
WORKFLOW = '.github/workflows/mac-secondary-qualification.yml'
TOOLS = 'tools/mac-secondary-qualification'


def require(value, message):
    if not value:
        raise ValueError(message)


def environment(lane):
    require(lane in ('normal', 'sandbox'), 'Unknown Mac job')
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': 'refs/heads/' + BRANCH,
                'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@refs/heads/' + BRANCH,
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'mac-' + lane,
                'TOUCHCOLOR_JOB_PLATFORM': 'mac', 'TOUCHCOLOR_JOB_LANE': lane,
                'TOUCHCOLOR_JOB_MINUTES': '40', 'TOUCHCOLOR_EVIDENCE_LIMIT': '3000000',
                'DEVELOPER_DIR': '/Applications/Xcode_27.app/Contents/Developer'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'Exact Mac route/environment differs')
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
            'Actual control/workflow SHA mismatch')
    require(Path.cwd().resolve(strict=True) == REPO and REPO.resolve(strict=True) == REPO, 'Controller cwd must be the verified repository root')
    return sha


def protected():
    rows = json_read(REPO / TOOLS / 'base-manifest.json', 256_000)
    require(isinstance(rows, list) and len(rows) == 476, 'Missing exact protected476 inventory')
    seen = set()
    end = time.monotonic() + 15
    for row in rows:
        path = row['path']
        require(path not in seen and not Path(path).is_absolute() and '..' not in Path(path).parts, 'Unsafe source inventory')
        seen.add(path)
        raw = read(REPO / path, max(row['bytes'], 1), deadline=end)
        mode = '100755' if (REPO / path).stat().st_mode & 0o111 else '100644'
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'] and mode == row['mode'],
                'Frozen original source changed: ' + path)
    return seen


def tools_manifest():
    value = json_read(REPO / TOOLS / 'control-manifest.json', 256_000)
    require(value.get('base_commit') == BASE and value.get('product_commit') == PRODUCT and type(value.get('READY')) is bool,
            'CLOSED control manifest binding differs')
    require(type(value.get('files')) is list and len(value['files']) <= 40, 'Invalid control source inventory')
    listed = set()
    for row in value['files']:
        path = row['path']
        require(path not in listed and not Path(path).is_absolute() and '..' not in Path(path).parts, 'Duplicate/unsafe added path')
        listed.add(path)
        require(path == WORKFLOW or path.startswith(TOOLS + '/'), 'Unapproved added path')
        raw = read(REPO / path, max(row['bytes'], 1))
        mode = '100755' if (REPO / path).stat().st_mode & 0o111 else '100644'
        require(len(raw) == row['bytes'] and mode == row['mode'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
                'New controller source changed: ' + path)
    actual = set()
    for item in (REPO / TOOLS).iterdir():
        require(not item.is_symlink() and item.is_file(), 'Unexpected directory/alias in flat controller source')
        actual.add(item.relative_to(REPO).as_posix())
        require(len(actual) <= 40, 'Unbounded controller source directory')
    require(actual == {path for path in listed if path.startswith(TOOLS + '/')} | {TOOLS + '/control-manifest.json'},
            'Unlisted controller source/import file')
    return value


def check(lane):
    start = float(os.environ['TOUCHCOLOR_JOB_STARTED_MONOTONIC'])
    epoch = float(os.environ['TOUCHCOLOR_JOB_STARTED_EPOCH'])
    now, wall = time.monotonic(), time.time()
    require(all(math.isfinite(x) for x in (start, epoch)) and start <= now and epoch <= wall + 2, 'Invalid original setup clock')
    hard = min(start + 2370, now + max(0, epoch + 2370 - wall))
    later = 1280 if lane == 'normal' else 1400
    end = min(start + 300, hard - 450 - later)
    require(now < end, 'Original setup/source clock expired')
    previous = io.DEADLINE
    io.DEADLINE = min(end, previous if previous is not None else end)
    try:
        sha = environment(lane)
        original = protected()
        added = tools_manifest()
        require(not original.intersection(row['path'] for row in added['files']), 'New controller overlaps protected source')
        return {'source_sha': sha, 'product_sha': PRODUCT, 'base_commit': BASE, 'protected_files': 476,
                'added_paths': sorted([row['path'] for row in added['files']] + [TOOLS + '/control-manifest.json'])}
    finally:
        io.DEADLINE = previous


if __name__ == '__main__':
    import sys
    print(json.dumps(check(sys.argv[1]), sort_keys=True))
