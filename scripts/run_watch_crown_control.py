#!/usr/bin/env python3
"""One owned, source-bound Watch diagnostic. No retries and never product acceptance.

Phase ceilings share the ORIGINAL job clock. A 120s setup phase does not give
120s to each simulator operation. Every subprocess owns a bounded process group.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import threading
import time
import uuid

from atomic_json import write_json
from bounded_process import stop_group
from job_budget import JobBudget, create_record, RESERVES, STATE, fail_record
from watch_crown_contract import (binding, require, test_command, method_scheduling_status, METHODS, PHASES, WORKFLOW, CAP)
from watch_profiles import select_profile
from watch_runtime_pair import phone_template, verify_new_device, verify_pair, activate_owned_pair
from watch_home_diagnostics import summarize_home_notifications
from watch_diagnostics import ListFrameDiagnostics
from watch_failure_continuation import recorded_timeout, strict_json

ROOT = Path('build/evidence')


def digest(raw): return hashlib.sha256(raw).hexdigest()


class Driver:
    def __init__(self, env=os.environ, *, clock=time.monotonic, wall=time.time, process_factory=subprocess.Popen):
        self.env, self.clock, self.wall, self.process_factory = env, clock, wall, process_factory
        self.budget = JobBudget(create_record(env, wall, clock), wall=wall, monotonic=clock)
        self.report = {'schema': 1, 'source': binding(env), 'run_id': env['GITHUB_RUN_ID'],
                       'attempt': env['GITHUB_RUN_ATTEMPT'], 'source_verified': False,
                       'toolchain': {}, 'stages': [], 'phases': [], 'cases': [], 'evidence': [],
                       'owned_devices': [], 'cleanup': {'confirmed': False}, 'errors': [],
                       'acceptance': False, 'result': 'incomplete'}
        self.current = None
        self.phase_kind = 'work'
        self.frames = ListFrameDiagnostics()
        self.device = None
        self.pair = None
        self.owned = self.report['owned_devices']
        self.runners = {}
        self.stdout_limit = 262_144
        self.work_stopped = False

    def persist(self):
        self.report['budget'] = self.budget.snapshot()
        write_json(ROOT/'report.json', self.report, limit=300_000)

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
            self.persist()

    def run(self, command, seconds, *, required=True, first=False):
        require(self.current is not None, 'Every command needs a bounded phase')
        require(not self.budget.cleanup_unconfirmed, 'Prior process cleanup is unconfirmed')
        require(not (self.phase_kind=='work' and self.work_stopped), 'Prior operation expired; no further work')
        if first:
            require(not any(s['phase']==self.current['name'] for s in self.report['stages']), 'Phase can start only at its first command')
            # First operation defines this phase's start; the original job clock
            # remains authoritative and has already paid for Python setup time.
            self.current.update(started_monotonic=self.clock(), started_epoch=self.wall())
        left = self.current['limit_seconds']-(self.clock()-self.current['started_monotonic'])
        require(left+0.01 >= seconds, 'Full command allowance unavailable in '+self.current['name'])
        self.budget.admit(' '.join(command[:4]), seconds, minimum=seconds, cleanup=0, phase=self.phase_kind)
        row = {'command': command, 'phase': self.current['name'], 'budget_phase': self.phase_kind,
               'source_sha': self.report['source']['sha'],
               'started': False, 'started_epoch': self.wall(), 'started_monotonic': self.clock(),
               'timeout_seconds': seconds, 'exit': None, 'raw_exit': None, 'timed_out': False,
               'process_group_gone': False, 'capture_reader_finished': False, 'stdout_truncated': False}
        self.report['stages'].append(row)
        operation_deadline = min(row['started_monotonic']+seconds, self.current['started_monotonic']+self.current['limit_seconds'])
        row['deadline_monotonic'] = operation_deadline
        output = bytearray(); errors = []
        p = None; thread = None; cleanup_attempted = False
        try:
            p = self.process_factory(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True, env=dict(self.env))
            row.update(started=True, pid=p.pid)
            self.persist()
            def drain():
                try:
                    while True:
                        chunk = p.stdout.read(8192)
                        if not chunk: break
                        room = self.stdout_limit-len(output)
                        output.extend(chunk[:max(0, room)])
                        if len(chunk)>room: row['stdout_truncated'] = True
                except Exception as error: errors.append(type(error).__name__)
            thread = threading.Thread(target=drain, daemon=True); thread.start()
            try:
                row['raw_exit'] = p.wait(timeout=max(0,operation_deadline-self.clock()))
                row['exit'] = row['raw_exit']
                if self.clock()>=operation_deadline: row.update(exit=124,timed_out=True)
            except subprocess.TimeoutExpired:
                row.update(exit=124, timed_out=True)
            # A timeout leaves the work phase, preserving the cleanup tail.
            # No independent UI follows a timed-out command.
            grace = min(5, max(0, self.budget.remaining('cleanup')/2))
            cleanup_attempted = True
            row['process_group_gone'] = stop_group(p, grace=grace)
            thread.join(timeout=min(2, max(0, self.budget.remaining('cleanup'))))
            row['capture_reader_finished'] = not thread.is_alive() and not errors
            row['reader_errors'] = errors
            # The absolute operation includes descendant and capture cleanup.
            # Confirmed cleanup can consume its reserved tail, but an expired
            # operation still prohibits every later work command.
            if self.clock()>=operation_deadline:
                row.update(exit=124,timed_out=True)
            if row['timed_out'] and self.phase_kind=='work':
                self.work_stopped=True
                self.report['work_stop']={'reason':'operation_deadline_expired','stage_index':len(self.report['stages'])-1,
                    'cleanup_confirmed':row['process_group_gone'] and row['capture_reader_finished']}
            if not row['process_group_gone'] or not row['capture_reader_finished']:
                self.budget.latch_cleanup_failure()
                fail_record('Crown owned process/read cleanup unconfirmed', phase=self.phase_kind, cleanup_unconfirmed=True)
            row['stdout_sha256'] = digest(bytes(output)); row['stdout_bytes'] = len(output)
            text = bytes(output).decode('utf-8', errors='replace')
            if row['timed_out'] or self.budget.cleanup_unconfirmed:
                if required: raise RuntimeError('Crown command timed out or cleanup was unconfirmed')
                return row, text
            require(self.clock() <= self.current['started_monotonic']+self.current['limit_seconds'], 'Whole phase deadline reached')
            if required: require(row['exit'] == 0 and not row['stdout_truncated'], 'Command failed or output incomplete: '+' '.join(command[:4]))
            return row, text
        except BaseException:
            if p is not None and not cleanup_attempted:
                cleanup_attempted = True
                row['process_group_gone'] = stop_group(p, grace=min(5,max(0,self.budget.remaining('cleanup')/2)))
                if thread is not None:
                    thread.join(timeout=min(2,max(0,self.budget.remaining('cleanup'))))
                    row['capture_reader_finished'] = not thread.is_alive() and not errors
            if p is not None and (not row['process_group_gone'] or not row['capture_reader_finished']):
                self.budget.latch_cleanup_failure()
            raise
        finally:
            if p is not None and row['capture_reader_finished'] and p.stdout is not None: p.stdout.close()
            if command[:1]==['xcodebuild'] and 'test-without-building' not in command and row.get('exit')!=0:
                row['failure_output_tail']=bytes(output[-4096:]).decode('utf-8',errors='replace')
            row.update(finished_epoch=self.wall(), finished_monotonic=self.clock())
            self.persist()

    def text(self, command, seconds=5, **kw): return self.run(command, seconds, **kw)[1].strip()
    def value(self, command, seconds=5, **kw): return strict_json(self.text(command, seconds, **kw))

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
            for name in ('generate_watch_project.py', 'generate_watch_crown_control_project.py'):
                self.run([sys.executable, 'scripts/'+name], 3)
            require(self.source() == self.report['source_before'], 'Generator drift')

    def fingerprints(self):
        start = self.clock(); result = {}
        for method in METHODS[:2]:
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
            for method in METHODS[:2]:
                name=method['project']
                command=['xcodebuild','-quiet','-project',name+'.xcodeproj','-scheme',name,'-configuration','Debug',
                         '-destination','generic/platform=watchOS Simulator','-derivedDataPath',method['derived_data'],
                         'ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','build-for-testing']
                stage, output=self.run(command, 110)
                self.retain(method['key']+'-build.log', output, 'build', method['key'], limit=262_144)
                products=Path(method['derived_data'])/'Build/Products/Debug-watchsimulator'
                runner=products/(method['target']+'-Runner.app')/'Info.plist'
                value=plistlib.loads(runner.read_bytes())['CFBundleIdentifier']
                require(value == ('com.mango.touchColor.watchCrownControl.uitests.xctrunner' if method['key']=='isolated_static'
                                  else 'com.mango.touchColor.TouchColorWatchUITests.xctrunner'), 'Unexpected built runner identity')
                self.runners[method['key']]=value
            self.report['runner_bundle_ids']=self.runners
            self.report['products_before']=self.fingerprints()

    def setup(self):
        with self.phase('setup', PHASES['setup']):
            devices=self.value(['xcrun','simctl','list','devices','available','-j'])['devices']
            runtime, watch, inventory=select_profile(devices,'watchOS-27-0','smallest')
            chosen=next(v for v in inventory if v['udid']==watch['udid'])
            require(chosen['millimeters']==40 and watch.get('deviceTypeIdentifier'), 'Only observed smallest 40mm Watch admitted')
            before=self.value(['xcrun','simctl','list','pairs','-j'])
            require(isinstance(before.get('pairs'),dict) and len(before['pairs'])<=64, 'Invalid initial pair inventory')
            phone_runtime, phone=phone_template(devices)
            self.report['initial_inventory']={'devices':devices,'pairs':before}
            for role, template, selected_runtime in [('phone',phone,phone_runtime),('watch',watch,runtime)]:
                identifier=self.text(['xcrun','simctl','create','TouchColor-Crown-'+role+'-'+str(uuid.uuid4())[:8],template['deviceTypeIdentifier'],selected_runtime],10)
                verify_new_device(identifier,devices,self.owned)
                self.owned.append({'role':role,'udid':identifier,'runtime':selected_runtime,'deviceTypeIdentifier':template['deviceTypeIdentifier']}); self.persist()
            phone_id, watch_id=[v['udid'] for v in self.owned]
            pair=self.text(['xcrun','simctl','pair',watch_id,phone_id],10);uuid.UUID(pair)
            require(pair not in before['pairs'], 'Pair ownership ambiguous')
            self.pair=pair # Exact new pair is tracked even if readback fails.
            pairs=self.value(['xcrun','simctl','list','pairs','-j'])
            record=verify_pair(pairs,pair,watch_id,phone_id,before['pairs'])
            active=activate_owned_pair(pairs,pair,watch_id,phone_id,before['pairs'],
                 lambda identifier:self.run(['xcrun','simctl','pair_activate',identifier],5),
                 lambda:self.value(['xcrun','simctl','list','pairs','-j']))
            self.report['pair']={'id':pair,'record':record,'activation':active}
            self.device=watch_id
            self.report['device']={'udid':watch_id,'runtime':runtime,'profile':'smallest','millimeters':40,
                    'deviceTypeIdentifier':watch['deviceTypeIdentifier'],'text_phase':'normal','owned':True}
            for identifier in (phone_id,watch_id):
                self.run(['xcrun','simctl','boot',identifier],5)
                self.run(['xcrun','simctl','bootstatus',identifier,'-b'],25)
            inventory=self.value(['xcrun','simctl','list','devices','available','-j'])['devices']
            rows=[v for group in inventory.values() for v in group if v['udid'] in (phone_id,watch_id)]
            require(len(rows)==2 and all(v['state']=='Booted' for v in rows), 'Owned pair readiness unconfirmed')
            self.report['setup_readback']=rows

    def stop_apps(self, method):
        key='isolated_static' if method['key']=='isolated_static' else 'actual_cold'
        identities=(method['bundle_id'],self.runners[key])
        for identifier in identities:
            # Terminate can return an already-stopped error. Only the subsequent
            # exact owned-device service inventory establishes absence.
            termination,_=self.run(['xcrun','simctl','terminate',self.device,identifier],3,required=False)
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
                if 'WATCH_LIST_FRAME ' in line: self.frames.record(line)
                elif line.startswith('WATCH_STATIC_CROWN_'): static.append(line)
                else: ordinary.append(line)
            case['diagnostics_file']=self.retain(name+'-console.log','\n'.join(ordinary)+'\n','diagnostics',name,limit=65_536)
            if static: self.retain('static-observations.log','\n'.join(static)+'\n','observation_static',name,limit=16_384)
            require(not stage['timed_out'] and not self.budget.cleanup_unconfirmed, 'Timed-out or unclean command; no further operations')
            # Capture finalized structured summary once within the SAME method
            # phase. It cannot steal the later evidence reserve or reset a clock.
            summary_stage, raw=self.run(['xcrun','xcresulttool','get','test-results','summary','--path',case['result_bundle']],15)
            case['summary_file']=self.retain(name+'-summary.json',raw,'summary',name,limit=100_000)
            summary=strict_json(raw)
            case['summary_stage_index']=len(self.report['stages'])-1
            require(not recorded_timeout(summary) and not recorded_timeout(output), 'Recorded XCTest timeout; stop new UI')
            # Final evidence validation cannot retroactively authorize a control
            # that has already started. Reconcile exact finalized evidence here.
            status=method_scheduling_status(method,self.device,self.budget.record['sha'],stage,summary,lifecycle)
            case['scheduling_status']=status
            cleanup=self.stop_apps(method);case['process_cleanup']=cleanup;case['cleanup_confirmed']=True
            case['observed_command_result']=status

    def cleanup(self):
        if self.budget.cleanup_unconfirmed or not self.owned: return
        with self.phase('cleanup', 130,kind='cleanup'):
            if self.device:
                stage, output=self.run(['xcrun','simctl','spawn',self.device,'log','show','--last','27m','--style','compact',
                    '--predicate','subsystem == "com.mango.touchColor.WatchDiagnostics"'],10,required=False)
                if stage['exit']==0 and not stage['stdout_truncated']:
                    home=summarize_home_notifications(output)
                    self.retain('home-observations.json',json.dumps(home,separators=(',',':')),'observation_home','actual_cold',limit=16_384)
                else: self.report['errors'].append('Home OSLog extraction unavailable or incomplete')
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
        if self.budget.cleanup_unconfirmed: return
        with self.phase('evidence', 180,kind='evidence'):
            self.report['source_after']=self.source()
            self.report['source_verified']=self.report.get('source_before')==self.report['source_after']
            if 'products_before' in self.report:
                self.report['products_after']=self.fingerprints()
                require(self.report['products_after']==self.report['products_before'],'Products changed between controls')
            for case in self.report['cases']:
                if not Path(case['result_bundle']).exists(): continue
                stage, raw=self.run(['xcrun','xcresulttool','get','test-results','tests','--path',case['result_bundle']],20)
                case['tests_file']=self.retain(case['name']+'-tests.json',raw,'tests',case['name'],limit=150_000)
                case['tests_stage_index']=len(self.report['stages'])-1
            self.retain('cold-list-frames.json',json.dumps(self.frames.report,separators=(',',':')),'cold_frames','actual_cold',limit=150_000)

    def execute(self):
        require(not ROOT.exists() and not ROOT.is_symlink(), 'Fresh evidence root required')
        ROOT.mkdir(parents=True)
        write_json(STATE,self.budget.record)
        self.persist()
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
            self.persist()
        return 0 # Workflow's independent validator, not this controller, reports the diagnostic verdict.


def main():
    try: return Driver().execute()
    except Exception as error:
        print('WATCH_CROWN_INCOMPLETE '+type(error).__name__+': '+str(error),file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
