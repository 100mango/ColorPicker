"""File-only admission/final gate. Compiler execution belongs to Actions step."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import os
import time

import io_boundary as io
import source_guard as source
from budget import Ledger
import commands


def require(value, message):
    if not value:
        raise ValueError(message)


def ledger():
    lane = os.environ['TOUCHCOLOR_JOB_LANE']
    return Ledger(float(os.environ['TOUCHCOLOR_JOB_STARTED_MONOTONIC']), commands.stages(lane),
                  epoch=float(os.environ['TOUCHCOLOR_JOB_STARTED_EPOCH']))


def verify_source():
    value = source.check(os.environ['TOUCHCOLOR_JOB_LANE'])
    require(source.tools_manifest()['READY'] is True, 'CLOSED Mac control cannot execute')
    return value


def compile_admission():
    verify_source()
    clock = ledger()
    required = sum(step['seconds'] for step in clock.plan[0]['commands'])
    later = sum(stage['seconds'] for stage in clock.plan[1:])
    end = min(clock.start + 300, clock.phase_end('work') - later)
    require(time.monotonic() + 60 + required <= end,
            'Compilation lacks full60s plus every remaining required setup command')
    io.mkdir(io.REPO / 'build')
    # No Popen/run/kill/poll/wait. The following workflow shell exec is sole compiler route.
    io.write(io.REPO / 'build/mac-bootstrap.json', io.encoded({'source_sha': os.environ['GITHUB_SHA'],
        'started_monotonic': clock.start, 'started_epoch': clock.epoch, 'setup_deadline': end,
        'compile_seconds': 60, 'remaining_setup_seconds': required,
        'owner': 'Standard Actions exec compiler step; compiler descendant cleanup is not core-proven'}))


def validate_upload(*, reserve_upload=True):
    clock = ledger()
    io.DEADLINE = min(time.monotonic() + 15, clock.phase_end('validation') if reserve_upload else clock.hard_deadline)
    root = io.REPO / 'build/mac-upload'
    require(root.is_dir() and not root.is_symlink(), 'Missing bounded upload')
    files = list(root.rglob('*'))
    require(len(files) <= 650 and all(not p.is_symlink() for p in files), 'Unsafe upload inventory')
    total = 0
    for path in files:
        if path.is_file():
            total += len(io.read(path, 3_000_000))
    require(total <= 3_000_000, 'Actual retained Mac evidence exceeds3MB')
    result = io.json_read(root / 'mac-row-result.json', 65536)
    expected = {'source_sha': os.environ['GITHUB_SHA'], 'lane': os.environ['TOUCHCOLOR_JOB_LANE'],
                'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'job': os.environ['GITHUB_JOB']}
    require(all(result.get(k) == v for k, v in expected.items()), 'Upload source/lane/run identity differs')
    if result.get('complete') is True:
        import evidence
        evidence.verify_upload(root, os.environ['TOUCHCOLOR_JOB_LANE'])
    if reserve_upload:
        require(time.monotonic() + 60 <= clock.phase_end('upload'), 'No complete60s upload reserve')
    return result


def gate():
    result = validate_upload(reserve_upload=False)
    clock = ledger()
    require(time.monotonic() < clock.hard_deadline, 'Original job clock expired')
    expected = {'BOOTSTRAP_OUTCOME': 'success', 'COMPILE_OUTCOME': 'success', 'COMPILE_EXIT': '0',
                'CONTROLLER_OUTCOME': 'success', 'CONTROLLER_EXIT': '0', 'UPLOAD_OUTCOME': 'success'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'Actual compile/controller/upload outcome or exit failed')
    require(result.get('complete') is True, 'Mac row evidence incomplete')
    return result


def main():
    action = sys.argv[1]
    if action == 'compile-admission':
        compile_admission()
    elif action == 'source':
        print(json.dumps(verify_source(), sort_keys=True))
    elif action == 'upload':
        print(json.dumps(validate_upload(), sort_keys=True))
    elif action == 'gate':
        print(json.dumps(gate(), sort_keys=True))
    else:
        raise ValueError('Unknown file-only bootstrap action')


if __name__ == '__main__':
    main()
