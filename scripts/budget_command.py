#!/usr/bin/env python3
"""A bounded evidence command; diagnostics go to stderr, preserving JSON stdout."""
import argparse
import subprocess
import sys
from job_budget import load, BudgetExhausted, fail_record, UNCLEAN
from bounded_process import run_captured


def execute(command, seconds):
    command_attempted=False;command_completed=False
    def uncertain(error):
        return command_attempted and not command_completed and getattr(error,'cleanup_confirmed',False) is not True
    try:
        budget=load();budget.phase='evidence'
        if UNCLEAN.exists():budget.latch_cleanup_failure()
        granted=budget.admit(' '.join(command[:3]),seconds,minimum=min(3,seconds),cleanup=20,phase='evidence')
        command_attempted=True
        result=run_captured(command,timeout=granted,text=True)
        command_completed=True
        if len((result.stdout or '').encode())>500_000:
            fail_record('Evidence command output exceeded500000bytes',phase='evidence')
            return 1
        sys.stdout.write(result.stdout or '');sys.stdout.flush()
        sys.stderr.write((result.stderr or '')[-4096:]);sys.stderr.flush()
        if result.returncode:fail_record('Evidence command failed: '+' '.join(command[:3]),phase='evidence')
        return result.returncode
    except subprocess.TimeoutExpired as error:
        fail_record('Evidence command timed out: '+' '.join(command[:3]),phase='evidence',cleanup_unconfirmed=not getattr(error,'cleanup_confirmed',False))
        return 124
    except (BudgetExhausted,ValueError) as error:
        fail_record(error,phase='evidence',cleanup_unconfirmed=uncertain(error))
        print('EVIDENCE_INCOMPLETE '+str(error),file=sys.stderr,flush=True)
        return 1
    except Exception as error:
        # A failed launch or unexpected capture exception cannot disappear behind
        # the workflow's diagnostic || true. No cleanup proof means stop further work.
        fail_record('Evidence command error '+type(error).__name__+': '+' '.join(command[:3]),
                    phase='evidence',cleanup_unconfirmed=uncertain(error))
        print('EVIDENCE_INCOMPLETE '+type(error).__name__,file=sys.stderr,flush=True)
        return 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=20)
    parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:raise SystemExit('Missing evidence command')
    raise SystemExit(execute(command,args.seconds))
