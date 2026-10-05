"""One disposable Mini reader+original-launch diagnostic; never warmup acceptance."""
import time
STARTED = time.monotonic()  # Includes every import and preparation operation.
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys

from mini_passive_compatibility import (CompatibilityCapture, HeadTail, CaptureFailed, require,
    _bounded_plist, APP_PLIST, APP, EXECUTABLE)
from mini_passive_status import _write_nonblocking
from bounded_process import group_exists
from job_budget import enabled_budget, fail_record
from uikit_runtime_diagnostics import read_identity
from uikit_warmup import Warmup

PREPARATION_SECONDS = 600
SPAWN_SECONDS, LAUNCH_SECONDS, CLEANUP_SECONDS = 5, 60, 20
JOINT_SECONDS = SPAWN_SECONDS + LAUNCH_SECONDS + CLEANUP_SECONDS
REF = 'refs/heads/codex/mini-passive-launch'
WORKFLOW = '100mango/ColorPicker/.github/workflows/mini-passive-launch.yml@' + REF
BUILD = ['xcodebuild','-quiet','-project','TouchColor.xcodeproj','-scheme','TouchColor',
    '-configuration','Debug','-destination','generic/platform=iOS Simulator',
    '-derivedDataPath','build/simulator','CODE_SIGNING_ALLOWED=NO','build']
CODE_BYTES = 16 * 1024 * 1024


def require_disposable_job():
    require(os.environ.get('GITHUB_REPOSITORY') == '100mango/ColorPicker' and
        os.environ.get('GITHUB_REF') == REF and os.environ.get('GITHUB_EVENT_NAME') == 'push' and
        os.environ.get('GITHUB_WORKFLOW_REF') == WORKFLOW, 'Dedicated push identity required')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'macOS' and
        os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and
        os.environ.get('GITHUB_JOB') == 'mini-passive-launch', 'Disposable hosted Mini job required')


def code_identity(path):
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Linked product path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                0 < before.st_size <= CODE_BYTES, 'Unbounded product code')
        sha = hashlib.sha256(); count = 0
        while count <= CODE_BYTES:
            data = os.read(fd, min(65536, CODE_BYTES + 1 - count))
            if not data: break
            count += len(data); sha.update(data)
        after = os.fstat(fd)
        require(count == before.st_size and count <= CODE_BYTES and
                all(getattr(before,k) == getattr(after,k) for k in
                    ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')), 'Product code changed')
        return {'bytes':count, 'sha256':sha.hexdigest()}
    finally:
        os.close(fd)


def product_identity():
    result = _bounded_plist()
    result['code'] = {EXECUTABLE:code_identity(APP_PLIST.parent / EXECUTABLE)}
    dylib = APP_PLIST.parent / (EXECUTABLE + '.debug.dylib')
    require(not dylib.is_symlink(), 'Linked debug code')
    result['debug_dylib'] = code_identity(dylib) if dylib.exists() else None
    return result


def setup_runner(command, *, timeout):
    # Reuse the existing finite single-command capture for setup only. It stops
    # on >64 KiB total output; no partial inventory or build is accepted.
    from palette_lifecycle_diagnostics import capture
    budget = enabled_budget()
    now = time.monotonic()
    deadline = STARTED + PREPARATION_SECONDS - CLEANUP_SECONDS
    if budget is not None:
        deadline = min(deadline, now + budget.remaining() - CLEANUP_SECONDS)
    allowance = min(timeout, deadline - now)
    require(allowance > 0, 'Original setup deadline exhausted')
    result = capture(command, seconds=allowance, cap=64 * 1024, cleanup_grace=10)
    require(time.monotonic() < deadline, 'Setup returned after original absolute deadline')
    result.stdout = result.stdout.decode('utf-8', errors='strict')
    result.stderr = result.stderr.decode('utf-8', errors='strict')
    return result


def prepare_joint(controller):
    require_disposable_job()
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
            'Source/workflow binding unavailable')
    budget = controller.budget
    require(budget is not None and not budget.cleanup_unconfirmed and
            budget.record.get('sha') == sha and budget.record.get('run_id') == os.environ.get('GITHUB_RUN_ID') and
            budget.record.get('platform') == 'ios' and budget.record.get('lane') == 'mini-passive-launch' and
            budget.record.get('minutes') == 20, 'Original source-bound budget unavailable')
    require(controller.command(['git','rev-parse','HEAD'],3,simulator=False).strip() == sha, 'Checkout differs')
    controller.command(['git','diff','--quiet','HEAD','--'],3,simulator=False)
    toolchain = controller.command(['xcodebuild','-version'],5,simulator=False)
    require(toolchain.splitlines() == ['Xcode 27.0','Build version 27A266a'], 'Wrong installed toolchain')
    controller.command(BUILD,300,simulator=False)
    device = controller.select()
    selected = read_identity('iPadMini')
    require(selected['udid'] == device, 'Selected UUID differs from retained binding')
    controller.mini_joint_identity = selected
    controller.command(['xcrun','simctl','boot',device],180,optional=True)
    controller.command(['xcrun','simctl','bootstatus',device,'-b'],240)
    before = product_identity()
    require(read_identity('iPadMini') == selected, 'Selected device binding changed before install')
    controller.mini_joint_product = before
    controller.command(['xcrun','simctl','install',device,str(APP_PLIST.parent)],300)
    require(read_identity('iPadMini') == selected and product_identity() == before,
            'Installed source/device binding changed')
    return toolchain


class ReaderStderr(HeadTail):
    """Only POSIX permission-denial text is a semantic stop signal.

    Other stderr, including informational text, remains unclassified evidence.
    Process/read/spawn status independently detects every nonzero/early exit.
    """
    def __init__(self, limit):
        super().__init__(limit); self.suffix = b''; self.denial = None
        self.indicators = {os.strerror(code).encode('utf-8').lower():name
                           for code,name in ((errno.EACCES,'EACCES'),(errno.EPERM,'EPERM'))}
    def feed(self, data):
        combined = self.suffix + data.lower()
        for text,name in self.indicators.items():
            if text in combined: self.denial = name
        self.suffix = combined[-max(map(len,self.indicators)):]
        super().feed(data)


def emit_joint_summary(receipt):
    # Advisory and memory-only; no raw output, extra process, file read or retry.
    try:
        require_disposable_job()
        source = receipt.get('source_sha'); run = receipt.get('run_id'); attempt = receipt.get('run_attempt')
        if not (isinstance(source,str) and re.fullmatch('[0-9a-f]{40}',source) and source == os.environ.get('GITHUB_SHA') == os.environ.get('GITHUB_WORKFLOW_SHA') and
                isinstance(run,str) and re.fullmatch('[1-9][0-9]{0,19}',run) and run == os.environ.get('GITHUB_RUN_ID') and
                isinstance(attempt,str) and re.fullmatch('[1-9][0-9]{0,19}',attempt) and attempt == os.environ.get('GITHUB_RUN_ATTEMPT')):
            source = run = attempt = None
        def row(name):
            value = receipt.get('processes',{}).get(name,{})
            def exit_value(key):
                value2=value.get(key)
                return value2 if type(value2) is int and -255 <= value2 <= 255 else None
            cleanup=value.get('host_cleanup_confirmed')
            return [value.get('state') if value.get('state') in ('attempted','owned') else None,
                    exit_value('observed_work_exit'),exit_value('exit'),cleanup if type(cleanup) is bool else None]
        allowed = ('launch-observed','launch-nonzero','launch-deadline','reader-exited','reader-permission',
                   'reader-pipes-closed','launch-permission','cancelled','absolute-deadline','failed-or-incomplete')
        reason=receipt.get('reason')
        value={'v':1,'sha':source,'run':run,'try':attempt,'reason':reason if reason in allowed else None,
               'reader':row('collector'),'launch':row('launcher'),'readiness':None,
               'phase':'launch' if receipt.get('app_launch_attempted') else 'reader' if 'collector' in receipt.get('processes',{}) else None,
               'cleanup':receipt.get('host_cleanup_confirmed') if type(receipt.get('host_cleanup_confirmed')) is bool else None,
               'state':receipt.get('status') if receipt.get('status') in ('not_started','failed_or_incomplete','command_outcome_observed') else None,
               'source':'memory','durability':'unconfirmed','daemon':'unconfirmed','acceptance':False,'delivery':'best_effort'}
        raw=('MINI_JOINT_STATUS '+json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')
        if len(raw)<=512: return _write_nonblocking(raw)
    except Exception:
        pass
    return False


class JointCapture(CompatibilityCapture):
    """Exactly two admitted initial spawns, one permanent marker and cleanup tail."""
    def __init__(self, warmup, *, preparation_started):
        super().__init__(warmup, preparation_started=preparation_started)
        self.folder = Path('build/iPadMini-passive-launch')
        self.buffers = {'stream':HeadTail(65536),'collector_stderr':ReaderStderr(4096),'launcher':ReaderStderr(8192)}
        self.receipt = {'schema':1,'purpose':'isolated-reader-launch-only','status':'not_started',
            'warmup_admitted':False,'app_launch_attempted':False,'tests_executed':False,
            'readiness':'unknown','reader_completion':'unconfirmed','simulator_command_completion':'unconfirmed',
            'vm_disposal_required':True,'preparation_started':preparation_started,'preparation_deadline':warmup.deadline,
            'preparation_seconds':600,'joint_seconds':85,'launcher_seconds':60,'shared_cleanup_seconds':20,
            'events':{},'processes':{},'output_observed_at':{},'cleanup_discarded_bytes':{}}
        self.envelope_end = None

    def _binding(self):
        require(self.warmup.family == 'iPadMini', 'Mini only')
        started = self.receipt['preparation_started']
        require(type(started) in (int, float) and math.isfinite(started) and
                math.isfinite(self.warmup.deadline) and started <= self.clock() and
                self.warmup.deadline - started == PREPARATION_SECONDS, 'Original 600-second clock required')
        # This is a fixed isolated job, not an opt-in on the existing warmup job.
        require_disposable_job()
        self.identity = read_identity('iPadMini')
        require(self.identity == getattr(self.warmup,'mini_joint_identity',None),
                'Joint UUID differs from original selected/installed device')
        sha = os.environ.get('GITHUB_SHA', '')
        run, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
        require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
                'Source/workflow binding unavailable')
        require(all(re.fullmatch('[1-9][0-9]{0,19}', part) for part in (run, attempt)), 'Run binding unavailable')
        budget = self.warmup.budget
        require(budget is not None and not budget.cleanup_unconfirmed and budget.record.get('sha') == sha and
                budget.record.get('run_id') == run and budget.record.get('platform') == 'ios',
                'Original source-bound iOS budget unavailable')
        product = product_identity()
        require(product == getattr(self.warmup,'mini_joint_product',None),
                'Joint product differs from original installed source')
        self.receipt.update({'source_sha': sha, 'workflow_sha': sha, 'run_id': run,
                             'run_attempt': attempt, 'device': self.identity, 'app': product})
        device = self.identity['udid']
        self.collector = ['xcrun', 'simctl', 'spawn', device, 'log', 'stream',
                          '--info', '--debug', '--predicate', 'process == "TouchColor"']
        self.launcher = ['xcrun','simctl','launch','--terminate-running-process',device,APP]
        self.receipt.update({'collector_argv': self.collector, 'launcher_argv': self.launcher,
                             'build_argv': BUILD, 'install_argv': ['xcrun','simctl','install',device,str(APP_PLIST.parent)]})

    def _same_binding(self):
        require_disposable_job()
        require(read_identity('iPadMini') == self.identity, 'Device binding changed')
        require(product_identity() == self.receipt['app'], 'Built app binding changed')
        require(os.environ.get('GITHUB_SHA') == self.receipt['source_sha'] and
                os.environ.get('GITHUB_WORKFLOW_SHA') == self.receipt['source_sha'] and
                os.environ.get('GITHUB_RUN_ID') == self.receipt['run_id'] and
                os.environ.get('GITHUB_RUN_ATTEMPT') == self.receipt['run_attempt'], 'Source/run binding changed')

    def _check(self, deadline):
        require(self.cancelled is None, 'cancelled')
        require(self.clock() < deadline and self.warmup.remaining() > CLEANUP_SECONDS,
                'absolute-deadline')

    def _spawn(self, name, argv, deadline):
        require(name in ('collector','launcher') and name not in self.processes and
                argv == (self.collector if name == 'collector' else self.launcher), 'Unplanned joint spawn')
        require(name == 'collector' or set(self.processes) == {'collector'}, 'Joint spawn order changed')
        self._check(deadline)
        self.receipt['processes'][name] = {'state':'attempted','argv':argv,'observed_work_exit':None}
        self._event(name+'_attempt'); self._persist(); self._check(deadline)
        if name == 'launcher': self.receipt['app_launch_attempted'] = True
        process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        self.processes[name] = process
        self.receipt['processes'][name].update(state='owned',pid=process.pid,pgid=process.pid)
        self._event(name+'_owned')
        for pipe, stream in ((process.stdout,'stream' if name == 'collector' else 'launcher'),
                             (process.stderr,'collector_stderr' if name == 'collector' else 'launcher')):
            os.set_blocking(pipe.fileno(),False)
            self.selector.register(pipe,selectors.EVENT_READ,(name,stream))
        self._persist(); self._check(deadline)
        return process

    def _reader_ok(self):
        reader = self.processes['collector']
        status = reader.poll()
        if status is not None:
            self.receipt['processes']['collector']['observed_work_exit'] = status
            raise CaptureFailed('reader-exited')
        denial = self.buffers['collector_stderr'].denial
        if denial is not None:
            self.receipt['reader_permission_indicator'] = denial
            raise CaptureFailed('reader-permission')
        denial = self.buffers['launcher'].denial
        if denial is not None:
            self.receipt['launch_permission_indicator'] = denial
            raise CaptureFailed('launch-permission')
        require(not self._closed('collector'), 'reader-pipes-closed')

    def _cleanup(self):
        # Both groups share the same two signal phases, never serial allowances.
        started = self.clock()
        deadline = min(started+CLEANUP_SECONDS,self.envelope_end,self.warmup.deadline,
                       started+self.warmup.remaining())
        self.receipt['cleanup_deadline'] = deadline
        self._event('cleanup_started')
        def gone(name,process):
            try: return process.poll() is not None and not group_exists(process.pid)
            except Exception as error:
                self.receipt['processes'][name]['cleanup_error'] = type(error).__name__
                return False
        for seconds,signum in ((10,signal.SIGTERM),(20,signal.SIGKILL)):
            until = min(started+seconds,deadline)
            for name,process in self.processes.items():
                try:
                    require(process.pid > 0 and process.pid != os.getpgrp(), 'Refusing caller group')
                    if not gone(name,process): os.killpg(process.pid,signum)
                except ProcessLookupError:
                    pass
                except Exception as error:
                    self.receipt['processes'][name]['signal_error'] = type(error).__name__
            while self.clock() < until:
                if all(gone(name,process) for name,process in self.processes.items()) and not self.selector.get_map():
                    break
                self._drain(until,cleanup=True)
                if not self.selector.get_map():
                    self.warmup.sleep(min(.025,max(0,until-self.clock())))
            if all(gone(name,process) for name,process in self.processes.items()) and not self.selector.get_map():
                break
        confirmations=[False for row in self.receipt['processes'].values() if row.get('state') != 'owned']
        for name,process in self.processes.items():
            row=self.receipt['processes'][name]
            confirmed=gone(name,process) and self._closed(name) and name not in self.pipe_failures and not row.get('cleanup_error')
            confirmations.append(confirmed)
            row.update(exit=process.poll(),host_cleanup_confirmed=confirmed)
        self.receipt['host_cleanup_confirmed']=all(confirmations)
        self._event('cleanup_finished')

    def _close_owned_pipes(self):
        for name,process in self.processes.items():
            for pipe in (process.stdout,process.stderr):
                try: pipe.close()
                except Exception as error:
                    self.receipt['processes'][name]['close_error']=type(error).__name__
                    self.receipt['processes'][name]['host_cleanup_confirmed']=False
                    self.receipt['host_cleanup_confirmed']=False
        try: self.selector.close()
        except Exception as error:
            self.receipt['selector_close_error']=type(error).__name__
            self.receipt['host_cleanup_confirmed']=False

    def run(self):
        previous={}; marker_owned=False; folder_created=False; failure=None
        def interrupted(signum,frame):
            if self.cancelled is None: self.cancelled=signum
        try:
            self._binding()
            require(self.warmup.budget.record.get('lane') == 'mini-passive-launch' and
                    self.warmup.budget.record.get('minutes') == 20, 'Wrong joint budget identity')
            require(not self.folder.exists() and not self.folder.is_symlink(), 'Prior joint evidence exists')
            self.folder.mkdir();folder_created=True
            require(self.warmup.remaining() >= JOINT_SECONDS, 'Insufficient original 85-second remainder')
            self.warmup.budget.admit('Mini fixed joint operation',65,minimum=65,cleanup=20)
            started=self.clock()
            self.envelope_end=min(started+JOINT_SECONDS,self.warmup.deadline,started+self.warmup.remaining())
            work_deadline=self.envelope_end-CLEANUP_SECONDS
            spawn_deadline=min(started+SPAWN_SECONDS,work_deadline-LAUNCH_SECONDS)
            self.receipt.update(joint_started=started,joint_deadline=self.envelope_end,
                                work_deadline=work_deadline,spawn_deadline=spawn_deadline)
            for signum in (signal.SIGTERM,signal.SIGINT):previous[signum]=signal.signal(signum,interrupted)
            with self.warmup.pending.open('x') as marker:
                marker_owned=True
                marker.write('Joint Mini simulator completion unconfirmed. No later device command; dispose VM.\n')
                marker.flush();os.fsync(marker.fileno())
            self.receipt['uncertainty_marker']=str(self.warmup.pending)
            self._event('ownership_acquired');self._persist()
            self._spawn('collector',self.collector,spawn_deadline)
            self._drain(spawn_deadline);self._reader_ok()
            self._same_binding();self._check(spawn_deadline);self._reader_ok()
            require(work_deadline-self.clock() >= LAUNCH_SECONDS, 'Insufficient full launch allowance')
            self.warmup.budget.admit('Original Mini launch',60,minimum=60,cleanup=20)
            launch_deadline=min(self.clock()+LAUNCH_SECONDS,work_deadline)
            self.receipt['launch_deadline']=launch_deadline
            launcher=self._spawn('launcher',self.launcher,launch_deadline)
            self._event('launch_supervision_started')
            while True:
                if self.clock() >= launch_deadline: raise CaptureFailed('launch-deadline')
                self._check(work_deadline)
                self._drain(launch_deadline)
                self._reader_ok()  # Observed reader failure wins over launcher completion.
                status=launcher.poll()
                if status is not None:
                    self.receipt['processes']['launcher']['observed_work_exit']=status
                    self._check(launch_deadline);self._reader_ok()
                    self.receipt['reason']='launch-observed' if status == 0 else 'launch-nonzero'
                    self.receipt['status']='command_outcome_observed'
                    if status: raise CaptureFailed('launch-nonzero')
                    break
        except BaseException as error:
            failure=error;self.receipt['status']='failed_or_incomplete'
            reason=str(error)
            self.receipt['reason']=reason if reason in ('launch-nonzero','launch-deadline','reader-exited',
                'reader-permission','reader-pipes-closed','launch-permission','cancelled','absolute-deadline') else 'failed-or-incomplete'
            self.receipt['failure']=type(error).__name__+': '+reason[:200]
        finally:
            try:
                if marker_owned:
                    try:self._cleanup()
                    except BaseException as error:
                        if failure is None:failure=error
                        self.receipt['host_cleanup_confirmed']=False
                        self.receipt['cleanup_failure']=type(error).__name__
                        # Best-effort owned host kills only. No device operation can follow.
                        for name,process in self.processes.items():
                            try:
                                if process.pid > 0 and process.pid != os.getpgrp():os.killpg(process.pid,signal.SIGKILL)
                            except (OSError,ValueError):pass
                self._close_owned_pipes()
                if self.cancelled is not None or (marker_owned and
                       (self.clock() >= self.receipt.get('cleanup_deadline',self.clock()) or
                        self.receipt.get('host_cleanup_confirmed') is not True)):
                    if failure is None:failure=CaptureFailed('Owned joint cleanup incomplete or deadline reached')
                    self.receipt['status']='failed_or_incomplete'
                self.receipt['cancelled_signal']=self.cancelled
                for signum,handler in previous.items():signal.signal(signum,handler)
                emit_joint_summary(self.receipt)
                if folder_created:
                    if marker_owned:require(self.clock() < self.receipt['cleanup_deadline'],'Output deadline exhausted')
                    for name,buffer in self.buffers.items():
                        if marker_owned:require(self.clock() < self.receipt['cleanup_deadline'],'Output deadline exhausted')
                        with (self.folder/(name+'.bin')).open('xb') as output:output.write(buffer.data())
                        if marker_owned:require(self.clock() < self.receipt['cleanup_deadline'],'Output returned late')
                    self.receipt['persistence']='attempted; completion unconfirmed'
                    self._persist()
                    if marker_owned:require(self.clock() < self.receipt['cleanup_deadline'],'Receipt returned late')
            except BaseException as error:
                if failure is None:failure=error
        if failure is not None:raise failure
        return self.receipt


def main():
    controller=None
    try:
        require(sys.argv[1:] == ['launch-once'],'Only launch-once is supported')
        controller=Warmup('iPadMini',started=STARTED,budget=enabled_budget(),runner=setup_runner)
        toolchain=prepare_joint(controller)
        print('MINI_JOINT_TOOLCHAIN: '+toolchain.replace('\n','; '),flush=True)
        JointCapture(controller,preparation_started=STARTED).run()
    except BaseException as error:
        print('MINI_JOINT_FAILURE: '+type(error).__name__+': '+str(error)[:200],file=sys.stderr,flush=True)
    finally:
        if controller is not None and controller.pending.exists():
            fail_record('Joint Mini diagnostic stopped; dispose VM; no warmup acceptance',cleanup_unconfirmed=True)
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
