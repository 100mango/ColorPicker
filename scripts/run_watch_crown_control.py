#!/usr/bin/env python3
"""One owned, source-bound Watch diagnostic. No retries and never product acceptance.

Phase ceilings share the ORIGINAL job clock. The 600s setup ceiling shares the same1020s work pool;
no phase resets that original clock or reserves all later worst-case ceilings. Every subprocess owns a bounded process group.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import stat
import sys
import threading
import time
import uuid

from atomic_json import write_json
from bounded_process import stop_group
from job_budget import JobBudget, create_record, RESERVES, STATE, fail_record
from watch_crown_contract import (binding, require, test_command, method_scheduling_status, METHODS, PHASES, WORKFLOW, CAP, DIAGNOSTIC_SCOPE, EXCLUDED_CASES)
from watch_crown_setup_events import SCHEMA, PROTOCOL, BOOT_OUTPUT_LIMIT, validate_setup_events
from watch_profiles import select_profile
from watch_runtime_pair import phone_template, verify_new_device, verify_pair, activate_owned_pair
from watch_failure_continuation import recorded_timeout, strict_json

ROOT = Path('build/evidence')
SIMULATOR_STOP = Path('build/crown-simulator-uncertain.json')
# Canonical Watch maxima, checked against its source without importing the
# imperative runner. These are caps, clipped to the existing setup/work clocks.
SETUP_COMMAND_CAPS = {'list':30,'create':60,'pair':60,'pair_activate':60,'boot':180,'bootstatus':420}

def device_facing(command):
    # These are the only device-facing tool families used by this driver.
    return (isinstance(command,list) and (command[:2]==['xcrun','simctl'] or
            (command[:1]==['xcodebuild'] and any(v in command for v in ('test','test-without-building')))))


def reported_device_timeout(output):
    # Actual timeout words, not xcodebuild's echoed -test-timeouts-enabled flag.
    # This is a conservative stop signal, never a positive failure classifier.
    return bool(re.search(r'\b(?:timed? out|time-out|timeout)\b|exceeded execution time allowance|execution time.*exceeded|test may have hung',output,re.I))


def digest(raw): return hashlib.sha256(raw).hexdigest()


# Console mirrors are advisory subsets of already-persisted receipts. They are
# never consumed by the validator and add no commands or acceptance evidence.
CONSOLE_RECORD_BYTES = 512
CONSOLE_RECORDS = 9  # Preserve the original 4,608-byte ceiling; only seven boundaries are eligible.
CONSOLE_TOTAL_BYTES = CONSOLE_RECORD_BYTES * CONSOLE_RECORDS
CONSOLE_BOUNDARIES = tuple(PHASES) + ('cleanup', 'evidence', 'final')


def _console_bool(value): return value if type(value) is bool else None


def _console_int(value, maximum=1_000_000_000):
    return value if type(value) is int and -255 <= value <= maximum else None


def _console_operation(command):
    if not isinstance(command,list) or not command: return None
    if command[0]=='git': return 'source'
    if command[0] in ('sw_vers','uname') or command==['xcodebuild','-version']: return 'toolchain'
    if command[:2]==['xcodebuild','test-without-building']: return 'xctest'
    if command[0]=='xcodebuild': return 'build'
    if command[:2]==['xcrun','xcresulttool']: return 'result-extraction'
    if command[:2]==['xcrun','simctl'] and len(command)>2:
        if command[2] in ('create','pair','pair_activate','boot','bootstatus','list','terminate','shutdown','unpair','delete'): return command[2]
        if command[2]=='spawn': return 'simulator-observation'
    if len(command)>1 and command[1] == 'scripts/generate_watch_crown_control_project.py': return 'generator'
    return None


def _console_record(report, boundary, omitted):
    """Fixed allowlist only: never include errors, argv, paths or native output."""
    if boundary not in CONSOLE_BOUNDARIES or not isinstance(report,dict): return None
    source=report.get('source',{});budget=report.get('budget',{})
    if not isinstance(source,dict) or not isinstance(budget,dict): return None
    sha=source.get('sha');run=source.get('run_id');attempt=source.get('attempt')
    if not (isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha) and sha==budget.get('sha')
            and isinstance(run,str) and re.fullmatch('[1-9][0-9]{0,23}',run) and run==report.get('run_id')==budget.get('run_id')
            and isinstance(attempt,str) and re.fullmatch('[1-9][0-9]{0,5}',attempt) and attempt==report.get('attempt')): return None
    phases=report.get('phases',[]);stages=report.get('stages',[]);cases=report.get('cases',[])
    if not all(isinstance(value,list) for value in (phases,stages,cases)): return None
    if len(phases)>7 or len(stages)>192 or len(cases)>1: return None
    matching=[v for v in phases if isinstance(v,dict) and v.get('name')==boundary]
    phase=matching[0] if len(matching)==1 else {}
    last=stages[-1] if stages and isinstance(stages[-1],dict) else {}
    # Schema 1 uses fixed-position tuples to fit Darwin's 512-byte PIPE_BUF.
    # last=[phase,operation,exit,raw_exit,timed_out,group_gone,reader_finished]
    # cases.static=[started,stored_result,raw_exit,cleanup_confirmed]
    if type(omitted) is not int or not 0<=omitted<=CONSOLE_RECORDS: return None
    summaries={}
    for name,method in (('static',METHODS[0]),):
        matches=[v for v in cases if isinstance(v,dict) and v.get('name')==method['key']]
        case=matches[0] if len(matches)==1 else {}
        index=case.get('stage_index')
        stage=stages[index] if type(index) is int and 0<=index<len(stages) and isinstance(stages[index],dict) else {}
        status=case.get('observed_command_result')
        summaries[name]=[_console_bool(stage.get('started')),
            status if status in ('passed','failed') else None,_console_int(stage.get('raw_exit')),
            _console_bool(case.get('cleanup_confirmed'))]
    errors=report.get('errors');cleanup=report.get('cleanup',{})
    value={'v':1,'sha':sha,'run':run,'try':attempt,'phase':boundary,
        'done':_console_bool(phase.get('completed')),'stages':len(stages),
        'last':[last.get('phase') if last.get('phase') in CONSOLE_BOUNDARIES else None,
                _console_operation(last.get('command')),_console_int(last.get('exit')),
                _console_int(last.get('raw_exit')),_console_bool(last.get('timed_out')),
                _console_bool(last.get('process_group_gone')),_console_bool(last.get('capture_reader_finished'))],
        'cases':summaries,'cleanup':_console_bool(cleanup.get('confirmed')) if isinstance(cleanup,dict) else None,
        'errors':len(errors) if isinstance(errors,list) and len(errors)<=192 else None,
        'acceptance':_console_bool(report.get('acceptance')),'omitted':omitted,'delivery':'best_effort'}
    raw=('WATCH_CROWN_STATUS '+json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode()
    return raw if len(raw)<=CONSOLE_RECORD_BYTES else None


def _write_console_nonblocking(raw):
    """At most one atomic pipe write. Full/unsupported stdout is dropped, never waited on."""
    previous=None
    try:
        # O_NONBLOCK does not bound regular-file or terminal writes. Only use an
        # actual pipe and its observed PIPE_BUF atomic-write allowance.
        if not stat.S_ISFIFO(os.fstat(1).st_mode) or len(raw)>os.fpathconf(1,'PC_PIPE_BUF'): return False
        previous=os.get_blocking(1)
        if previous: os.set_blocking(1,False)
        return os.write(1,raw)==len(raw)
    except (OSError,ValueError):
        return False
    finally:
        if previous:
            try: os.set_blocking(1,True)
            except OSError: pass


class Driver:
    def __init__(self, env=os.environ, *, clock=time.monotonic, wall=time.time, process_factory=subprocess.Popen):
        self.env, self.clock, self.wall, self.process_factory = env, clock, wall, process_factory
        self.budget = JobBudget(create_record(env, wall, clock), wall=wall, monotonic=clock)
        self.report = {'schema': SCHEMA, 'protocol': PROTOCOL, 'source': binding(env), 'run_id': env['GITHUB_RUN_ID'],
                       'attempt': env['GITHUB_RUN_ATTEMPT'], 'source_verified': False,
                       'diagnostic_scope': DIAGNOSTIC_SCOPE, 'excluded_cases': list(EXCLUDED_CASES),
                       'toolchain': {}, 'stages': [], 'phases': [], 'cases': [], 'evidence': [],
                       'owned_devices': [], 'cleanup': {'confirmed': False}, 'errors': [],
                       'acceptance': False, 'result': 'incomplete'}
        self.current = None
        self.phase_kind = 'work'
        self.device = None
        self.pair = None
        self.owned = self.report['owned_devices']
        self.runners = {}
        self.stdout_limit = 262_144
        self.work_stopped = False
        self.console_seen=set();self.console_bytes=0;self.console_omitted=0
        self.simulator_uncertain=False
        self._stop_write_attempted=False
        self._device_activity=False
        self._host_cleanup_pending=False
        # A fresh Driver may never resume an old invocation. Even if writing a
        # stop marker failed, its pre-spawn report/initial budget blocks reload.
        try:
            prior=any(path.exists() or path.is_symlink() for path in (SIMULATOR_STOP,ROOT/'report.json',STATE))
        except OSError: prior=True
        if prior:
            self.simulator_uncertain=True;self.work_stopped=True;self.budget.latch_cleanup_failure()
            self.report['simulator_uncertainty']={'reason':'prior_run_state_requires_vm_disposal',
                'device_commands_forbidden':True,'vm_disposal_required':True,'marker_durability':'unknown'}

    def simulator_blocked(self):
        if self.simulator_uncertain: return True
        try: return SIMULATOR_STOP.exists() or SIMULATOR_STOP.is_symlink()
        except OSError: return True

    def latch_simulator_uncertainty(self, row, reason, *, durable=True):
        # Memory barrier first. Local marker failures must NEVER interrupt the
        # already-owned host process-group/reader cleanup or allow new commands.
        self.simulator_uncertain=True;self.work_stopped=True;self.budget.latch_cleanup_failure()
        row['simulator_command_completion']='unconfirmed'
        value=self.report.setdefault('simulator_uncertainty',{'schema':1,'source_sha':self.report['source']['sha'],
            'run_id':self.report['run_id'],'attempt':self.report['attempt'],
            'stage_index':len(self.report['stages'])-1,'reason':reason,
            'device_commands_forbidden':True,'vm_disposal_required':True,'marker_durability':'unknown'})
        if not durable or self._stop_write_attempted: return
        self._stop_write_attempted=True
        try:
            SIMULATOR_STOP.parent.mkdir(parents=True,exist_ok=True)
            require(not SIMULATOR_STOP.parent.is_symlink() and not SIMULATOR_STOP.is_symlink(),'Unsafe simulator stop destination')
            raw=json.dumps(value,separators=(',',':')).encode()
            require(len(raw)<=4096,'Simulator stop metadata bound')
            with SIMULATOR_STOP.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            # File contents and its newly created directory entry are both
            # flushed. Failure leaves explicit durability unknown and a fence.
            directory=os.open(SIMULATOR_STOP.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(directory)
            finally:os.close(directory)
            value['marker_durability']='fsync_confirmed'
        except FileExistsError:
            value['marker_durability']='existing_barrier_unverified'
        except BaseException as error:
            value['marker_durability']='unknown'
            value['marker_error']=type(error).__name__

    def persist(self):
        self.report['budget'] = self.budget.snapshot()
        write_json(ROOT/'report.json', self.report, limit=300_000)

    def persist_guarded(self):
        try:self.persist()
        except BaseException:
            if self._device_activity or self.owned:
                row=self.report['stages'][-1] if self.report['stages'] else {}
                self.latch_simulator_uncertainty(row,'receipt_persistence_failed_after_device_activity',
                    durable=not self._host_cleanup_pending)
            raise

    def console_summary(self, boundary):
        # Called only after persist() succeeded. No verdict, report or clock is
        # modified; serialization/write time still consumes the original clock.
        if boundary not in CONSOLE_BOUNDARIES or boundary in self.console_seen or len(self.console_seen)>=CONSOLE_RECORDS: return
        self.console_seen.add(boundary)
        try:
            raw=_console_record(self.report,boundary,self.console_omitted)
            if raw is None or self.console_bytes+len(raw)>CONSOLE_TOTAL_BYTES:
                self.console_omitted+=1;return
            self.console_bytes+=len(raw) # Charge attempted bytes even if stdout drops them.
            if not _write_console_nonblocking(raw): self.console_omitted+=1
        except Exception:
            self.console_omitted+=1 # Logging cannot turn a failure into a pass or interrupt cleanup.

    def retain(self, name, raw, kind, case=None, limit=150_000):
        if isinstance(raw, str): raw = raw.encode()
        require('/' not in name and name not in ('.', '..'), 'Unsafe evidence name')
        require(len(raw) <= limit, 'Required evidence exceeds its unchanged bound: '+name)
        require(not (ROOT/name).exists(), 'Evidence is immutable; duplicate '+name)
        total = sum(p.stat().st_size for p in ROOT.iterdir() if p.is_file())
        require(total+len(raw)+300_000 <= CAP, 'Required evidence does not fit unchanged cap')
        (ROOT/name).write_bytes(raw)
        self.report['evidence'].append({'path': name, 'sha256': digest(raw), 'bytes': len(raw), 'kind': kind, 'case': case})
        return name

    @contextlib.contextmanager
    def phase(self, name, seconds, *, kind='work'):
        require(not self.simulator_blocked(),'Simulator uncertainty forbids further phases; dispose VM')
        seconds = self.budget.admit(name, seconds, minimum=1 if kind=='cleanup' else seconds, cleanup=0, phase=kind)
        row = {'name': name, 'limit_seconds': seconds, 'started_monotonic': self.clock(),
               'started_epoch': self.wall(), 'completed': False}
        self.current, self.phase_kind = row, kind
        self.report['phases'].append(row)
        try:
            yield
            require(self.clock()-row['started_monotonic'] <= seconds, 'Whole phase exceeded: '+name)
            row['completed'] = True
        finally:
            row.update(finished_monotonic=self.clock(), finished_epoch=self.wall())
            self.current = None
            self.persist_guarded()
            self.console_summary(name)

    def run(self, command, seconds, *, required=True, first=False, clip_setup=False):
        require(not self.simulator_blocked(), 'Simulator uncertainty forbids all further commands; dispose VM')
        require(self.current is not None, 'Every command needs a bounded phase')
        require(not self.budget.cleanup_unconfirmed, 'Prior process cleanup is unconfirmed')
        require(not (self.phase_kind=='work' and self.work_stopped), 'Prior operation expired; no further work')
        if first:
            require(not any(s['phase']==self.current['name'] for s in self.report['stages']), 'Phase can start only at its first command')
            self.current.update(started_monotonic=self.clock(), started_epoch=self.wall())
        left=self.current['limit_seconds']-(self.clock()-self.current['started_monotonic'])
        declared=seconds
        if clip_setup:
            cap=SETUP_COMMAND_CAPS.get(command[2] if len(command)>2 else '')
            require(self.current['name']=='setup' and self.phase_kind=='work' and command[:2]==['xcrun','simctl']
                    and cap==seconds,'Only source-admitted setup command families may clip')
            seconds=min(seconds,left,self.budget.remaining('work'))
            require(seconds>=1,'No bounded setup allowance remains')
        else:require(left+0.01>=seconds,'Full command allowance unavailable in '+self.current['name'])
        seconds=self.budget.admit(' '.join(command[:4]),seconds,minimum=1 if clip_setup else seconds,cleanup=0,phase=self.phase_kind)
        row={'command':command,'phase':self.current['name'],'budget_phase':self.phase_kind,
             'source_sha':self.report['source']['sha'],'started':False,'started_epoch':self.wall(),'started_monotonic':self.clock(),
             'timeout_seconds':seconds,'exit':None,'raw_exit':None,'timed_out':False,
             'process_group_gone':False,'capture_reader_finished':False,'stdout_truncated':False}
        if clip_setup:row['setup_command_cap_seconds']=declared
        self.report['stages'].append(row)
        deadline=min(row['started_monotonic']+seconds,self.current['started_monotonic']+self.current['limit_seconds'],
                     self.clock()+self.budget.remaining(self.phase_kind))
        row['deadline_monotonic']=deadline
        output=bytearray();errors=[];p=None;thread=None;cleanup_attempted=False;spawn_attempted=False
        facing=device_facing(command)
        def ambiguous():
            return (row['timed_out'] or row['raw_exit'] is None or not row['process_group_gone']
                    or not row['capture_reader_finished'] or self.clock()>=deadline)
        def expired():
            if self.clock()>=deadline:row.update(exit=124,timed_out=True)
            if row['timed_out'] and self.phase_kind=='work':
                self.work_stopped=True
                self.report['work_stop']={'reason':'operation_deadline_expired','stage_index':len(self.report['stages'])-1,
                    'cleanup_confirmed':row['process_group_gone'] and row['capture_reader_finished']}
        def host_cleanup():
            nonlocal cleanup_attempted
            if p is None:
                self._host_cleanup_pending=False;return
            if cleanup_attempted:return
            cleanup_attempted=True
            try:row['process_group_gone']=stop_group(p,grace=min(5,max(0,self.budget.remaining('cleanup')/2)))
            except BaseException as error:
                row['cleanup_error']=type(error).__name__;row['process_group_gone']=False
            if thread is not None:
                try:thread.join(timeout=min(2,max(0,self.budget.remaining('cleanup'))))
                except BaseException as error:errors.append(type(error).__name__)
                row['capture_reader_finished']=not thread.is_alive() and not errors
            else:row['capture_reader_finished']=True # No reader was ever started.
            row['reader_errors']=errors
            self._host_cleanup_pending=False
        try:
            if facing:
                # Durable run intent precedes device-facing spawn. If this
                # persistence fails, nothing starts; any reload sees old state.
                self.persist_guarded()
                expired()
                require(not row['timed_out'],'Device command not started: receipt consumed its allowance')
            spawn_attempted=True
            self._host_cleanup_pending=True
            if facing:self._device_activity=True
            p=self.process_factory(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,env=dict(self.env))
            row.update(started=True,pid=p.pid)
            self.persist_guarded()
            def drain():
                try:
                    while True:
                        chunk=p.stdout.read(8192)
                        if not chunk:break
                        room=self.stdout_limit-len(output);output.extend(chunk[:max(0,room)])
                        if len(chunk)>room:row['stdout_truncated']=True
                except Exception as error:errors.append(type(error).__name__)
            thread=threading.Thread(target=drain,daemon=True);thread.start()
            try:
                row['raw_exit']=p.wait(timeout=max(0,deadline-self.clock()));row['exit']=row['raw_exit']
            except subprocess.TimeoutExpired:row.update(exit=124,timed_out=True)
            expired()
            if facing and row['timed_out']:self.latch_simulator_uncertainty(row,'device_deadline_expired',durable=False)
            host_cleanup();expired()
            if facing and ambiguous():self.latch_simulator_uncertainty(row,'device_deadline_or_host_cleanup_unconfirmed',durable=False)
            if not row['process_group_gone'] or not row['capture_reader_finished']:
                self.budget.latch_cleanup_failure()
                fail_record('Crown owned process/read cleanup unconfirmed',phase=self.phase_kind,cleanup_unconfirmed=True)
            row['stdout_sha256']=digest(bytes(output));row['stdout_bytes']=len(output)
            text=bytes(output).decode('utf-8',errors='replace')
            if facing and reported_device_timeout(text):
                row['reported_device_timeout']=True
                self.latch_simulator_uncertainty(row,'native_output_reports_timeout',durable=False)
            if row['timed_out'] or self.budget.cleanup_unconfirmed:
                if required:raise RuntimeError('Crown command timed out or cleanup was unconfirmed')
                return row,text
            require(self.clock()<=self.current['started_monotonic']+self.current['limit_seconds'],'Whole phase deadline reached')
            if required:require(row['exit']==0 and not row['stdout_truncated'],'Command failed or output incomplete: '+' '.join(command[:4]))
            return row,text
        except BaseException:
            # An ordinary timely terminal failure is not simulator uncertainty.
            # Interruptions/no terminal receipt/unknown cleanup are different.
            if facing and spawn_attempted and ambiguous():
                self.latch_simulator_uncertainty(row,'device_operation_interrupted_or_unconfirmed',durable=False)
            host_cleanup();expired()
            if facing and spawn_attempted and ambiguous():
                self.latch_simulator_uncertainty(row,'device_finalization_unconfirmed',durable=False)
            if p is not None and (not row['process_group_gone'] or not row['capture_reader_finished']):self.budget.latch_cleanup_failure()
            raise
        finally:
            # Host cleanup precedes every potentially failing durable stop write.
            host_cleanup();expired()
            if p is not None and row['capture_reader_finished'] and p.stdout is not None:
                try:p.stdout.close()
                except BaseException as error:
                    row['capture_reader_finished']=False;row['cleanup_error']=type(error).__name__
                    if facing:self.latch_simulator_uncertainty(row,'device_capture_close_unconfirmed',durable=False)
            if command[:1]==['xcodebuild'] and 'test-without-building' not in command and row.get('exit')!=0:
                row['failure_output_tail']=bytes(output[-4096:]).decode('utf-8',errors='replace')
            row.update(finished_epoch=self.wall(),finished_monotonic=self.clock())
            if facing and spawn_attempted and (ambiguous() or self.simulator_uncertain):
                self.latch_simulator_uncertainty(row,'device_finalization_ambiguous')
            try:self.persist_guarded()
            except BaseException:
                if facing and spawn_attempted:self.latch_simulator_uncertainty(row,'device_receipt_persistence_failed')
                raise
            expired()
            if facing and spawn_attempted and ambiguous() and not self.simulator_uncertain:
                row.update(finished_epoch=self.wall(),finished_monotonic=self.clock())
                self.latch_simulator_uncertainty(row,'device_receipt_returned_after_deadline')
                self.persist_guarded() # Filesystem-only; never restart a simulator/reader.

    def text(self, command, seconds=5, **kw): return self.run(command, seconds, **kw)[1].strip()
    def value(self, command, seconds=5, **kw): return strict_json(self.text(command, seconds, **kw))

    def setup_text(self, command):
        require(command[:2]==['xcrun','simctl'] and len(command)>2 and command[2] in SETUP_COMMAND_CAPS,
                'Unknown setup command family')
        return self.text(command,SETUP_COMMAND_CAPS[command[2]],clip_setup=True)

    def setup_value(self, command): return strict_json(self.setup_text(command))

    def source(self):
        source = self.report['source']
        observed = {'sha': self.text(['git', 'rev-parse', 'HEAD'], 2),
                    'tree': self.text(['git', 'rev-parse', 'HEAD^{tree}'], 2),
                    'workflow_sha256': digest(Path(WORKFLOW).read_bytes())}
        require(all(observed[k] == source[k] for k in observed if k in source), 'Exact source mismatch')
        require(re.fullmatch('[0-9a-f]{40}',observed['tree']), 'Invalid observed source tree')
        source.update(observed)
        require(not self.text(['git', 'status', '--porcelain', '--untracked-files=all'], 2), 'Source checkout is dirty')
        return observed

    def preflight(self):
        with self.phase('preflight', PHASES['preflight']):
            self.report['source_before'] = self.source()
            toolchain = {'xcode': self.text(['xcodebuild', '-version'], 4),
                         'macos': self.text(['sw_vers', '-buildVersion'], 2),
                         'architecture': self.text(['uname', '-m'], 2)}
            require(toolchain == {'xcode': 'Xcode 27.0\nBuild version 27A266a', 'macos': '26A428', 'architecture': 'arm64'}, 'Unadmitted toolchain')
            self.report['toolchain'] = toolchain
            self.run([sys.executable, 'scripts/generate_watch_crown_control_project.py'], 3)
            require(self.source() == self.report['source_before'], 'Generator drift')

    def fingerprints(self):
        require(not self.simulator_blocked(),'Simulator uncertainty forbids further evidence work')
        start = self.clock(); result = {}
        for method in METHODS:
            root = Path(method['derived_data'])/'Build/Products'
            require(root.is_dir() and not root.is_symlink() and any(root.glob('*.xctestrun')), 'Missing build-for-testing products')
            sha = hashlib.sha256(); count = size = 0
            for path in sorted(root.rglob('*')):
                require(self.clock()-start < 10, 'Product fingerprint time bound')
                require(not path.is_symlink(), 'Unexpected product symlink')
                if not path.is_file(): continue
                info=path.stat(); count+=1; size+=info.st_size
                require(count<=8192 and size<=1024**3, 'Product inventory bound')
                sha.update(path.relative_to(root).as_posix().encode()+b'\0')
                with path.open('rb') as stream:
                    while chunk:=stream.read(1024*1024):
                        require(self.clock()-start < 10, 'Product hash time bound'); sha.update(chunk)
                after=path.stat(); require((info.st_ino, info.st_size, info.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns), 'Products changed while reading')
            result[method['key']]={'sha256':sha.hexdigest(),'files':count,'bytes':size}
        return result

    def builds(self):
        with self.phase('builds', PHASES['builds']):
            for method in METHODS:
                name=method['project']
                command=['xcodebuild','-quiet','-project',name+'.xcodeproj','-scheme',name,'-configuration','Debug',
                         '-destination','generic/platform=watchOS Simulator','-derivedDataPath',method['derived_data'],
                         'ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','build-for-testing']
                stage, output=self.run(command, 110)
                self.retain(method['key']+'-build.log', output, 'build', method['key'], limit=262_144)
                products=Path(method['derived_data'])/'Build/Products/Debug-watchsimulator'
                runner=products/(method['target']+'-Runner.app')/'Info.plist'
                value=plistlib.loads(runner.read_bytes())['CFBundleIdentifier']
                require(value == 'com.mango.touchColor.watchCrownControl.uitests.xctrunner', 'Unexpected built runner identity')
                self.runners[method['key']]=value
            self.report['runner_bundle_ids']=self.runners
            self.report['products_before']=self.fingerprints()

    def setup(self):
        with self.phase('setup', PHASES['setup']):
            devices=self.setup_value(['xcrun','simctl','list','devices','available','-j'])['devices']
            runtime, watch, inventory=select_profile(devices,'watchOS-27-0','smallest')
            chosen=next(v for v in inventory if v['udid']==watch['udid'])
            require(chosen['millimeters']==40 and watch.get('deviceTypeIdentifier'), 'Only observed smallest 40mm Watch admitted')
            before=self.setup_value(['xcrun','simctl','list','pairs','-j'])
            require(isinstance(before.get('pairs'),dict) and len(before['pairs'])<=64, 'Invalid initial pair inventory')
            phone_runtime, phone=phone_template(devices)
            self.report['initial_inventory']={'devices':devices,'pairs':before}
            for role, template, selected_runtime in [('phone',phone,phone_runtime),('watch',watch,runtime)]:
                identifier=self.setup_text(['xcrun','simctl','create','TouchColor-Crown-'+role+'-'+str(uuid.uuid4())[:8],template['deviceTypeIdentifier'],selected_runtime])
                verify_new_device(identifier,devices,self.owned)
                self.owned.append({'role':role,'udid':identifier,'runtime':selected_runtime,'deviceTypeIdentifier':template['deviceTypeIdentifier']}); self.persist_guarded()
            phone_id, watch_id=[v['udid'] for v in self.owned]
            pair=self.setup_text(['xcrun','simctl','pair',watch_id,phone_id]);uuid.UUID(pair)
            require(pair not in before['pairs'], 'Pair ownership ambiguous')
            self.pair=pair # Exact new pair is tracked even if readback fails.
            pairs=self.setup_value(['xcrun','simctl','list','pairs','-j'])
            record=verify_pair(pairs,pair,watch_id,phone_id,before['pairs'])
            active=activate_owned_pair(pairs,pair,watch_id,phone_id,before['pairs'],
                 lambda identifier:self.setup_text(['xcrun','simctl','pair_activate',identifier]),
                 lambda:self.setup_value(['xcrun','simctl','list','pairs','-j']))
            self.report['pair']={'id':pair,'record':record,'activation':active}
            self.device=watch_id
            self.report['device']={'udid':watch_id,'runtime':runtime,'profile':'smallest','millimeters':40,
                    'deviceTypeIdentifier':watch['deviceTypeIdentifier'],'text_phase':'normal','owned':True}
            events=[]; event_bytes={}
            for owned in self.owned:
                identifier=owned['udid']; boot_index=len(self.report['stages'])
                self.setup_text(['xcrun','simctl','boot',identifier])
                status_index=len(self.report['stages'])
                stage, output=self.run(['xcrun','simctl','bootstatus',identifier,'-b'],
                    SETUP_COMMAND_CAPS['bootstatus'],clip_setup=True)
                raw=output.encode('utf-8')
                require(len(raw)<=BOOT_OUTPUT_LIMIT and len(raw)==stage['stdout_bytes'] and
                        digest(raw)==stage['stdout_sha256'], 'Bootstatus evidence cannot be retained exactly')
                name=self.retain('setup-'+owned['role']+'-bootstatus.log',raw,'setup_bootstatus',
                                 owned['role'],limit=BOOT_OUTPUT_LIMIT)
                event_bytes[name]=raw
                events.append({**{key:owned[key] for key in ('role','udid','runtime','deviceTypeIdentifier')},
                    'source_sha':self.report['source']['sha'],'run_id':self.report['run_id'],'attempt':self.report['attempt'],
                    'boot_stage_index':boot_index,'bootstatus_stage_index':status_index,'bootstatus_file':name,
                    'completed_epoch':stage['finished_epoch'],'completed_monotonic':stage['finished_monotonic']})
            # Versioned event-only admission. No post-boot inventory is requested,
            # and no simultaneous/current Booted state or connectivity is claimed.
            self.report['setup_proof']={'kind':PROTOCOL,'inventory':'not_requested','simultaneous_state':'unobserved',
                'connectivity':'unobserved','continued_readiness':'unobserved','events':events}
            validate_setup_events(self.report,event_bytes,{v['path']:v for v in self.report['evidence']})

    def stop_apps(self, method):
        require(method == METHODS[0], 'Only static app cleanup is admitted')
        key='isolated_static'
        identities=(method['bundle_id'],self.runners[key])
        for identifier in identities:
            # Terminate can return an already-stopped error. Only the subsequent
            # exact owned-device service inventory establishes absence.
            require(self.current is not None and self.current['limit_seconds']-(self.clock()-self.current['started_monotonic']) >= 30,
                    'Full termination allowance unavailable in original phase')
            termination,_=self.run(['xcrun','simctl','terminate',self.device,identifier],30,required=False)
            if termination['timed_out']:
                self.budget.latch_cleanup_failure()
                fail_record('Timed-out app termination has unknown simulator daemon completion',phase=self.phase_kind,cleanup_unconfirmed=True)
                raise RuntimeError('Timed-out app termination; no inventory or new UI may start')
        stage, raw=self.run(['xcrun','simctl','spawn',self.device,'launchctl','list'],5)
        lines=raw.splitlines()
        require(lines and lines[0].split()==['PID','Status','Label'], 'Unexpected launchctl inventory format')
        require(all(not any(identifier in line for identifier in identities) for line in lines[1:]), 'App or runner still registered/running')
        inventory_file=self.retain(method['key']+'-cleanup-services.log',raw,'case_cleanup',method['key'],limit=65_536)
        return {'confirmed':True,'inventory_file':inventory_file,'identifiers':list(identities),'inventory_stage_index':len(self.report['stages'])-1,
                'inventory_sha256':digest(raw.encode()),'entries':len(lines)-1}

    def method(self, method):
        require(not self.simulator_blocked(),'Simulator uncertainty forbids static execution; dispose VM')
        require(method == METHODS[0] and not self.report['cases'], 'Exactly one fixed static invocation is admitted')
        name=method['key']
        case={'name':name,'identifier':method['target']+'/'+method['case'],'project':method['project']+'.xcodeproj',
              'scheme':method['project'],'result_bundle':'build/watch-crown-'+name+'.xcresult','cleanup_confirmed':False}
        self.report['cases'].append(case)
        with self.phase(name, PHASES[name]):
            require(not Path(case['result_bundle']).exists(), 'Result bundle already exists; reruns forbidden')
            case['stage_index']=len(self.report['stages'])
            stage, output=self.run(test_command(method,self.device),180,required=False,first=True)
            lifecycle='\n'.join(line for line in output.splitlines() if line.startswith('Test Case '))+'\n'
            case['lifecycle_file']=self.retain(name+'-lifecycle.log',lifecycle,'lifecycle',name,limit=4096)
            ordinary=[]; static=[]
            for line in output.splitlines():
                if line.startswith('WATCH_STATIC_CROWN_'): static.append(line)
                else: ordinary.append(line)
            case['diagnostics_file']=self.retain(name+'-console.log','\n'.join(ordinary)+'\n','diagnostics',name,limit=65_536)
            if static: self.retain('static-observations.log','\n'.join(static)+'\n','observation_static',name,limit=16_384)
            # Attest this source-controlled split while the actual captured text
            # is still owned in memory. The files do not reconstruct original
            # interleaving; their digest/counts are derived here from this capture.
            capture=output.encode('utf-8')
            require(type(stage.get('stdout_bytes')) is int and 0 < stage['stdout_bytes'] <= self.stdout_limit and
                    len(capture)==stage['stdout_bytes'] and digest(capture)==stage.get('stdout_sha256'),
                    'Original static capture digest/count is missing or cannot be represented exactly')
            paths=[case['lifecycle_file'],case['diagnostics_file']]+(['static-observations.log'] if static else [])
            files=[]
            for path in paths:
                entries=[v for v in self.report['evidence'] if v['path']==path]
                require(len(entries)==1,'Static extraction needs exactly one immutable evidence entry')
                files.append({k:entries[0][k] for k in ('path','sha256','bytes')})
            case['capture_extraction']={'schema':1,'policy':'watch-static-crown-split-lines-v1',
                'provenance':'source-controlled extraction; original interleaving is not reconstructed',
                'source_sha':self.report['source']['sha'],'run_id':self.report['run_id'],'attempt':self.report['attempt'],
                'case':'isolated_static','stage_index':case['stage_index'],
                'capture':{'sha256':stage['stdout_sha256'],'bytes':stage['stdout_bytes']},'files':files}
            self.persist_guarded() # Receipt exists before summary extraction or app cleanup.
            if reported_device_timeout(output):
                self.latch_simulator_uncertainty(stage,'xctest_console_reports_timeout')
            require(not stage['timed_out'] and not self.budget.cleanup_unconfirmed and not self.simulator_blocked(), 'Timed-out or unclean command; no further operations')
            # Capture finalized structured summary once within the SAME method
            # phase. It cannot steal the later evidence reserve or reset a clock.
            summary_stage, raw=self.run(['xcrun','xcresulttool','get','test-results','summary','--path',case['result_bundle']],15)
            case['summary_file']=self.retain(name+'-summary.json',raw,'summary',name,limit=100_000)
            summary=strict_json(raw)
            case['summary_stage_index']=len(self.report['stages'])-1
            if recorded_timeout(summary):
                self.latch_simulator_uncertainty(stage,'structured_xctest_result_reports_timeout')
                raise ValueError('Recorded XCTest timeout; VM disposal required')
            # Reconcile the sole case before app cleanup. Final validation cannot
            # repair contradictory or unfinished native evidence.
            status=method_scheduling_status(method,self.device,self.budget.record['sha'],stage,summary,lifecycle)
            case['scheduling_status']=status
            case['observed_command_result']=status
            cleanup=self.stop_apps(method);case['process_cleanup']=cleanup;case['cleanup_confirmed']=True

    def cleanup(self):
        if self.simulator_blocked() or self.budget.cleanup_unconfirmed or not self.owned: return
        with self.phase('cleanup', 130,kind='cleanup'):
            for owned in reversed(self.owned): self.run(['xcrun','simctl','shutdown',owned['udid']],10,required=False)
            inventory=self.value(['xcrun','simctl','list','devices','-j'])['devices']
            rows={row['udid']:row for values in inventory.values() for row in values}
            require(all(rows.get(v['udid'],{}).get('state')=='Shutdown' for v in self.owned), 'Owned device shutdown unconfirmed')
            if self.pair: self.run(['xcrun','simctl','unpair',self.pair],10)
            for owned in reversed(self.owned): self.run(['xcrun','simctl','delete',owned['udid']],10)
            _,device_raw=self.run(['xcrun','simctl','list','devices','-j'],5)
            device_index=len(self.report['stages'])-1
            after=strict_json(device_raw)['devices']
            _,pair_raw=self.run(['xcrun','simctl','list','pairs','-j'],5)
            pair_index=len(self.report['stages'])-1
            pairs=strict_json(pair_raw)['pairs']
            ids={row['udid'] for values in after.values() for row in values}
            require(all(v['udid'] not in ids for v in self.owned) and self.pair not in pairs, 'Owned cleanup absence unconfirmed')
            self.retain('cleanup-devices.json',device_raw,'cleanup_devices',limit=100_000)
            self.retain('cleanup-pairs.json',pair_raw,'cleanup_pairs',limit=100_000)
            self.report['cleanup']={'confirmed':True,'device_absence_verified':True,'pair_absence_verified':True,
                'owned_device_ids':[v['udid'] for v in self.owned], 'pair_id':self.pair,
                'device_inventory_sha256':digest(device_raw.encode()),'device_stage_index':device_index,
                'pair_inventory_sha256':digest(pair_raw.encode()),'pair_stage_index':pair_index}

    def evidence(self):
        if self.simulator_blocked() or self.budget.cleanup_unconfirmed: return
        with self.phase('evidence', 180,kind='evidence'):
            self.report['source_after']=self.source()
            self.report['source_verified']=self.report.get('source_before')==self.report['source_after']
            if 'products_before' in self.report:
                self.report['products_after']=self.fingerprints()
                require(self.report['products_after']==self.report['products_before'],'Static products changed during diagnostic')
            for case in self.report['cases']:
                if not Path(case['result_bundle']).exists(): continue
                stage, raw=self.run(['xcrun','xcresulttool','get','test-results','tests','--path',case['result_bundle']],20)
                case['tests_file']=self.retain(case['name']+'-tests.json',raw,'tests',case['name'],limit=150_000)
                case['tests_stage_index']=len(self.report['stages'])-1

    def execute(self):
        require(not self.simulator_blocked(),'Prior simulator uncertainty; fresh VM required')
        require(not ROOT.exists() and not ROOT.is_symlink(), 'Fresh evidence root required')
        ROOT.mkdir(parents=True)
        write_json(STATE,self.budget.record)
        self.persist_guarded()
        try:
            self.preflight(); self.builds(); self.setup()
            for method in METHODS: self.method(method)
        except Exception as error:
            self.report['errors'].append(type(error).__name__+': '+str(error)[:1000])
        finally:
            self.report['work_finished_monotonic']=self.clock()
            self.report['work_elapsed_from_original_seconds']=self.clock()-self.budget.record['started_monotonic']
            for function in (self.cleanup,self.evidence):
                try: function()
                except Exception as error: self.report['errors'].append(type(error).__name__+': '+str(error)[:1000])
            self.persist_guarded()
            self.console_summary('final')
        return 0 # Workflow's independent validator, not this controller, reports the diagnostic verdict.


def main():
    try: return Driver().execute()
    except Exception as error:
        print('WATCH_CROWN_INCOMPLETE '+type(error).__name__+': '+str(error),file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
