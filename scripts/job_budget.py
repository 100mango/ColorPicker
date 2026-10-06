"""Source-bound native job clock. Free runner memory is evidence, never an admission rule."""
import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from atomic_json import write_json as write_json_atomic

EXPECTED_MINUTES = {'vision': 35, 'watch': 45, 'tv': 25, 'mac': 40, 'ios': 20, 'paired': 45}
# Work stops early enough for owned process/capture cleanup, bounded extraction,
# validation and a real artifact upload. The runner's cancellation grace is not work time.
RESERVES = {'cleanup': 130, 'evidence': 180, 'validation': 60, 'upload': 60, 'overhead': 20}
VISION_RESERVES = {**RESERVES, 'evidence': 300}

def reserves_for(platform):
    # Closed Vision policy; all other platform reserves remain byte-equivalent.
    return dict(VISION_RESERVES if platform == 'vision' else RESERVES)

STARTUP_MARGIN = 30
METADATA_RESERVE = 16_384
STATE = Path('build/job-budget.json')

class BudgetExhausted(RuntimeError):
    def __init__(self, message, *, cleanup_confirmed=True):
        super().__init__(message)
        self.command_started = False
        self.cleanup_confirmed = cleanup_confirmed

class JobBudget:
    def __init__(self, record, *, wall=time.time, monotonic=time.monotonic):
        self.record = dict(record)
        self.wall, self.monotonic = wall, monotonic
        self.validate()
        mono_deadline = self.record['started_monotonic'] + self.record['minutes'] * 60 - STARTUP_MARGIN
        # A persisted, VM-wide monotonic start cannot be reset by a later process
        # or a backward wall-clock adjustment. A gross forward wall-clock jump
        # may only shorten the budget, matching the server-side hard limit.
        wall_remaining = self.record['started_epoch'] + self.record['minutes'] * 60 - wall() - STARTUP_MARGIN
        self.hard_deadline = min(mono_deadline, monotonic() + max(0, wall_remaining))
        self.cleanup_unconfirmed = False
        self.phase = 'work'
        self.events = []

    def validate(self):
        r = self.record
        if r.get('schema') != 1 or r.get('platform') not in EXPECTED_MINUTES:
            raise ValueError('Unknown native budget identity')
        if r.get('minutes') != EXPECTED_MINUTES[r['platform']]:
            raise ValueError('Job timeout differs from its exact source-owned row')
        if type(r.get('started_epoch')) not in (int, float) or not math.isfinite(r['started_epoch']):
            raise ValueError('Invalid job clock')
        if type(r.get('started_monotonic')) not in (int,float) or not math.isfinite(r['started_monotonic']) or r['started_monotonic']>self.monotonic()+2:
            raise ValueError('Invalid monotonic job start')
        if r['started_epoch'] > self.wall() + 2:
            raise ValueError('Job clock is in the future')
        if not re.fullmatch('[0-9a-f]{40}', r.get('sha', '')):
            raise ValueError('Missing exact tested source')
        if r.get('reserves') != reserves_for(r['platform']) or r.get('startup_margin') != STARTUP_MARGIN:
            raise ValueError('Budget reserve contract differs from source')

    def remaining(self, phase=None):
        phase = phase or self.phase
        reserves = self.record['reserves']
        tail = {
            'work': sum(reserves.values()),
            'cleanup': reserves['evidence'] + reserves['validation'] + reserves['upload'] + reserves['overhead'],
            'evidence': reserves['validation'] + reserves['upload'] + reserves['overhead'],
            'validation': reserves['upload'] + reserves['overhead'],
            'upload': reserves['overhead'],
        }
        if phase not in tail: raise ValueError('Unknown budget phase')
        return max(0, self.hard_deadline - self.monotonic() - tail[phase])

    def admit(self, label, requested, *, minimum=1, cleanup=20, phase=None):
        phase = phase or self.phase
        if self.cleanup_unconfirmed:
            raise BudgetExhausted('Owned process cleanup is unconfirmed; no further command', cleanup_confirmed=False)
        if not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (requested, minimum, cleanup)) or requested <= 0 or minimum <= 0 or minimum > requested:
            raise ValueError('Invalid phase budget request')
        available = self.remaining(phase) - cleanup
        granted = min(requested, max(0, available))
        event = {'phase': phase, 'label': str(label)[:160], 'requested_seconds': requested,
                 'minimum_seconds': minimum, 'cleanup_reserve_seconds': cleanup,
                 'granted_seconds': round(granted, 3), 'remaining_seconds': round(self.remaining(phase), 3)}
        event['admitted'] = granted >= minimum
        self.events.append(event)
        self.events = self.events[-64:]
        if not event['admitted']:
            event['result'] = 'not_started_insufficient_budget'
            raise BudgetExhausted('Mandatory phase not started within job reserve: '+str(label)[:160])
        return granted

    def latch_cleanup_failure(self):
        self.cleanup_unconfirmed = True

    @contextlib.contextmanager
    def using_phase(self, phase):
        self.remaining(phase) # Validate before changing state.
        old = self.phase
        self.phase = phase
        try: yield self
        finally: self.phase = old

    def snapshot(self):
        return {**self.record, 'phase': self.phase, 'remaining_seconds': round(self.remaining(), 3),
                'cleanup_unconfirmed': self.cleanup_unconfirmed, 'events': self.events,
                'result': 'incomplete' if any(not e['admitted'] for e in self.events) or self.cleanup_unconfirmed else 'budget_only_not_test_acceptance'}


def create_record(environ=os.environ, wall=time.time, monotonic=time.monotonic):
    platform = environ.get('TOUCHCOLOR_JOB_PLATFORM')
    minutes = int(environ.get('TOUCHCOLOR_JOB_MINUTES', '0'))
    started = float(environ.get('TOUCHCOLOR_JOB_STARTED_EPOCH', 'nan'))
    mono=float(environ.get('TOUCHCOLOR_JOB_STARTED_MONOTONIC','nan'))
    record = {'schema': 1, 'platform': platform, 'minutes': minutes, 'started_epoch': started, 'started_monotonic':mono,
              'lane': environ.get('TOUCHCOLOR_JOB_LANE', ''), 'sha': environ.get('GITHUB_SHA', ''),
              'run_id': environ.get('GITHUB_RUN_ID', ''), 'reserves': reserves_for(platform), 'startup_margin': STARTUP_MARGIN}
    JobBudget(record, wall=wall, monotonic=monotonic)
    return record


def load(path=STATE):
    path = Path(path)
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError('Missing or invalid exact job budget')
    record = json.loads(path.read_text())
    if record.get('sha') != os.environ.get('GITHUB_SHA') or record.get('run_id') != os.environ.get('GITHUB_RUN_ID'):
        raise ValueError('Job budget belongs to another run or source')
    return JobBudget(record)


INCOMPLETE = Path('build/job-budget-incomplete.json')
UNCLEAN = Path('build/job-budget-cleanup-unconfirmed.json')


def fail_record(reason, *, phase='work', cleanup_unconfirmed=False):
    """First failure wins; a cleanup failure is a separate persistent stop latch."""
    value = {'schema': 1, 'sha': os.environ.get('GITHUB_SHA', ''),
             'run_id': os.environ.get('GITHUB_RUN_ID', ''), 'phase': phase,
             'result': 'failed_or_incomplete', 'reason': str(reason)[:1000],
             'cleanup_unconfirmed': cleanup_unconfirmed}
    if phase not in ('work','cleanup','evidence','validation','upload'): raise ValueError('Unknown failure phase')
    paths=[INCOMPLETE,Path('build/job-budget-phase-'+phase+'.json')]
    if cleanup_unconfirmed: paths.append(UNCLEAN)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink(): raise ValueError('Unsafe failure record destination')
        try:
            with path.open('x') as stream: json.dump(value, stream)
        except FileExistsError: pass


def enabled_budget():
    if os.environ.get('TOUCHCOLOR_BUDGET_PHASE') not in ('work', 'cleanup', 'evidence'):
        return None
    budget = load()
    budget.phase = os.environ['TOUCHCOLOR_BUDGET_PHASE']
    if UNCLEAN.exists(): budget.latch_cleanup_failure()
    return budget


def retain_metadata(fallback_reason=None):
    """Filesystem-only fallback: safe even when further simulator work is forbidden."""
    build=Path('build')
    if build.is_symlink(): raise ValueError('Unsafe build root')
    root=build/'evidence'; root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink(): raise ValueError('Unsafe evidence root')
    value=load().snapshot()
    if fallback_reason is not None:
        archive=build/'evidence-incomplete'
        if archive.exists() or archive.is_symlink(): raise ValueError('Partial evidence archive already exists')
        # Keep partial output on the disposable runner, outside the approved
        # upload root. Never describe interrupted exports as complete evidence.
        root.rename(archive);root.mkdir()
        value['unpublished_partial_evidence']={'reason':str(fallback_reason)[:1000],
            'retention':'Incomplete export remains runner-local; this artifact contains bounded metadata only'}
    for key,path in [('failure',INCOMPLETE),('cleanup_failure',UNCLEAN)]:
        if path.exists():
            if path.is_symlink() or path.stat().st_size>4096: raise ValueError('Unsafe budget failure record')
            value[key]=json.loads(path.read_text())
            if value[key].get('sha')!=value['sha'] or value[key].get('run_id')!=value['run_id']:
                raise ValueError('Failure record belongs to another source or run')
            value['result']='failed_or_incomplete'
    value['phase_failures']={}
    for phase in ('work','cleanup','evidence','validation','upload'):
        path=Path('build/job-budget-phase-'+phase+'.json')
        if path.is_file() and not path.is_symlink() and path.stat().st_size<=4096:
            value['phase_failures'][phase]=json.loads(path.read_text())
    value['runtime_retention']=[]
    limit=int(os.environ.get('TOUCHCOLOR_EVIDENCE_LIMIT','650000'))
    if not METADATA_RESERVE < limit <= 8_000_000: raise ValueError('Invalid row evidence cap')
    for platform in ('vision','watch','tv','paired'):
        source=Path('build')/(platform+'-runtime')/'runtime.json'
        if source.parent.is_symlink() or not source.is_file() or source.is_symlink(): continue
        info=source.stat()
        if info.st_nlink!=1 or info.st_size>1_000_000: continue
        raw=source.read_bytes()
        try: parsed=json.loads(raw)
        except (ValueError,UnicodeDecodeError): continue
        if not isinstance(parsed,dict) or parsed.get('sha')!=value['sha']: continue
        target=root/(platform+'-runtime.json')
        if target.is_symlink(): raise ValueError('Unsafe runtime evidence destination')
        if target.exists(): continue # Preserve already filtered exact-source evidence.
        total=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        detail={'platform':platform,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        if total+len(raw)+METADATA_RESERVE<=limit:
            target.write_bytes(raw);detail['retained']=True
        else:
            detail.update(retained=False,reason='Exact runtime record does not fit unchanged row cap')
        value['runtime_retention'].append(detail)
    write_json_atomic(root/'job-budget.json',value,limit=METADATA_RESERVE)
    return value

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['initialize', 'check', 'retain', 'check-upload'])
    args = parser.parse_args()
    if args.action == 'initialize':
        record = create_record()
        STATE.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(STATE, record)
        print(json.dumps(record, sort_keys=True))
    elif args.action == 'retain':
        print(json.dumps(retain_metadata(), sort_keys=True))
    elif args.action == 'check-upload':
        budget=load()
        if budget.remaining('upload')<RESERVES['upload']:
            fail_record('Artifact upload reserve exhausted',phase='upload')
            raise SystemExit(1)
        print('A full artifact upload reserve remains')
    else:
        print(json.dumps(load().snapshot(), sort_keys=True))
