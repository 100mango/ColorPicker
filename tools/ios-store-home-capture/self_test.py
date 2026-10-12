"""Fixed self-expiring prerequisite for a future root-admitted Mac job.

Never launched by portable tests. No app, simulator, TCC or external target.
Failure poisons the caller's same Session before any product command can start.
"""
import json
import signal
import sys
import time

CHILD = r'''
import json,os,signal
signal.alarm(2)
fds=[]
for name in os.listdir('/dev/fd'):
    try: os.fstat(int(name))
    except OSError as error:
        if error.errno != 9: os._exit(126)
        continue
    fds.append(int(name))
print(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp(),'sid':os.getsid(0),
                  'mask':[int(v) for v in signal.pthread_sigmask(signal.SIG_BLOCK,[])],
                  'fds':sorted(fds)}))
'''


def run(session, *, work_deadline, cleanup_deadline):
    """Use the controller's existing Session and absolute setup allocation."""
    result = session.run([sys.executable, '-I', '-S', '-c', CHILD],
                         work_deadline=work_deadline, cleanup_deadline=cleanup_deadline,
                         maximum_bytes=4096, text=True)
    try:
        if result.returncode != 0 or result.stderr:
            raise ValueError('Launcher self-test did not exit cleanly')
        value = json.loads(result.stdout)
        if set(value) != {'pid', 'pgid', 'sid', 'mask', 'fds'}:
            raise ValueError('Invalid launcher self-test output')
        if not all(type(value[k]) is int and value[k] > 0 for k in ('pid', 'pgid', 'sid')):
            raise ValueError('Invalid exact child identity')
        if not value['pid'] == value['pgid'] == value['sid'] == result.owned_receipt['pid']:
            raise ValueError('New session identity mismatch')
        if (value['mask'] != [] or value['fds'] != [0, 1, 2] or
            any(type(fd) is not int for fd in value['fds'])):
            raise ValueError('Child inherited unexpected masks or descriptors')
        proof = result.owned_receipt
        if (proof['state'] != 'REAPED' or type(proof['reap_calls']) is not int or proof['reap_calls'] != 1 or
            type(proof['lease_calls']) is not int or proof['lease_calls'] < 2 or
            type(proof['group_calls']) is not int or proof['group_calls'] < 1 or
            proof['owned_group_cleanup_confirmed'] is not True):
            raise ValueError('Missing exact cleanup/reap proof')
        return {'scope': 'fixed_launcher_prerequisite_only', 'complete': True,
                'child': value, 'owned': proof, 'product_qualified': False}
    except BaseException as error:
        session.fault = error
        raise
