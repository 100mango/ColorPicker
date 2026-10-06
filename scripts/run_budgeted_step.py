#!/usr/bin/env python3
"""Run an unchanged native workflow body without spending its evidence reserve."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from bounded_process import stop_group
from job_budget import load, BudgetExhausted, fail_record, retain_metadata, UNCLEAN, RESERVES, STARTUP_MARGIN


def execute(body, *, label, seconds, phase, process_factory=subprocess.Popen, cleanup_driver=False):
    budget=load(); budget.phase=phase
    code=1; timed_out=False; cleanup=False; process=None
    try:
        if cleanup_driver:
            expected='python3 scripts/test_paired_watch.py' if budget.record['platform']=='paired' else 'python3 scripts/test_extra_platforms.py '+budget.record['platform']
            whole_work=budget.record['minutes']*60-STARTUP_MARGIN-sum(budget.record['reserves'].values())
            if phase!='work' or budget.record['platform'] not in ('vision','watch','tv','paired') or body.strip()!=expected or seconds<whole_work:
                raise ValueError('Cleanup tail requires an exact aggregate-budget-aware native driver and full work cap')
        if UNCLEAN.exists():
            budget.latch_cleanup_failure()
        timeout=budget.admit(label,seconds,minimum=min(seconds,10),cleanup=0 if phase=='work' else 20,phase=phase)
        environment={**os.environ,'TOUCHCOLOR_BUDGET_PHASE':phase}
        # The exact source body is read from a quoted heredoc; no user text is interpolated.
        started=budget.monotonic()
        if phase=='evidence':
            environment['TOUCHCOLOR_EVIDENCE_DEADLINE_MONOTONIC']=str(started+timeout)
        process=process_factory(['bash','-euo','pipefail','-c',body],env=environment,start_new_session=True)
        wait_remaining=max(0,timeout+(RESERVES['cleanup'] if cleanup_driver else 0)-(budget.monotonic()-started))
        try: code=process.wait(timeout=wait_remaining)
        except subprocess.TimeoutExpired:
            timed_out=True;code=124
        finished=budget.monotonic()
        cleanup=stop_group(process)
        if phase=='work' and (finished-started>timeout or budget.remaining('work')<=0) and code==0:
            code=124
            fail_record('Workflow body completed after its admitted work deadline: '+label,phase=phase)
        # Inner drivers can own separate process sessions. On an outer timeout
        # their cleanup is unproven even when this shell's own group disappeared.
        if timed_out or not cleanup:
            code=124
            fail_record('Workflow body deadline or cleanup failure: '+label,phase=phase,cleanup_unconfirmed=True)
        elif code:
            fail_record('Workflow body returned '+str(code)+': '+label,phase=phase)
    except (BudgetExhausted,ValueError) as error:
        fail_record(error,phase=phase)
        print('JOB_BUDGET_INCOMPLETE '+str(error),file=sys.stderr,flush=True)
    except Exception as error:
        if process is not None:
            try: cleanup=stop_group(process)
            except Exception: cleanup=False
        fail_record('Workflow controller error: '+type(error).__name__,phase=phase,
                    cleanup_unconfirmed=process is not None and not cleanup)
        code=1
    finally:
        print('JOB_BUDGET_STEP '+json.dumps({'label':label,'phase':phase,'exit':code,'timed_out':timed_out,'shell_group_gone':cleanup}),file=sys.stderr,flush=True)
        if phase=='evidence':
            if code and budget.record['platform']=='vision':
                from vision_offline_result import fence_incomplete_reads
                try: unconfirmed=fence_incomplete_reads()
                except Exception: unconfirmed=True
                if unconfirmed:
                    fail_record('Interrupted Vision reader or snapshot cleanup is unconfirmed',phase=phase,cleanup_unconfirmed=True)
            if Path('build/job-budget-phase-evidence.json').exists() and code==0:
                code=1 # A swallowed exporter error is still incomplete.
            retain_metadata(fallback_reason='Evidence phase failed or exceeded its reserved deadline' if code else None) # Filesystem only.
    return code


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    parser.add_argument('--seconds',required=True,type=int)
    parser.add_argument('--cleanup-driver',action='store_true')
    parser.add_argument('--phase',choices=['work','cleanup','evidence'],default='work')
    args=parser.parse_args()
    body=sys.stdin.read()
    if len(body.encode())>100_000: raise SystemExit('Workflow body exceeds its source bound')
    raise SystemExit(execute(body,label=args.label,seconds=args.seconds,phase=args.phase,cleanup_driver=args.cleanup_driver))
