#!/usr/bin/env python3
"""One finite Watch UI observation; no sampler, result export, or system diagnostics."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

from ios_watch_archive_capture import capture, CaptureStopped
from owned_process_group import stop_group
from watch_profiles import select_profile
from watch_runtime_pair import phone_template, verify_new_device, verify_pair, activate_owned_pair
from watch_heartbeat_evidence import summarize

CASE='TouchColorWatchUITests/WatchWorkflowTests/testTouchCopyEntryTouchAndCrownRemainResponsive'
CASE_LOG='TouchColorWatchUITests.WatchWorkflowTests testTouchCopyEntryTouchAndCrownRemainResponsive'
BASE='9c377452c9bba89fb4919e224491a2cd5d8c29a7'
WATCH_TYPE='com.apple.CoreSimulator.SimDeviceType.Apple-Watch-SE-3-40mm'
OUTPUT='watch-heartbeat-evidence.json'
EVIDENCE_CAP=65536
NATIVE_CAP=262144
OSLOG_CAP=65536
WORK_SECONDS=900
TOTAL_SECONDS=1020
NATIVE_SECONDS=300
CHANGES=['M\t.github/workflows/watch-focused-case.yml','M\tTouchColorWatch/WatchViews.swift',
         'M\tTouchColorWatchUITests/WatchWorkflowTests.swift','A\tscripts/test_watch_heartbeat_case.py',
         'A\tscripts/test_watch_heartbeat_evidence.py','A\tscripts/watch_heartbeat_case.py',
         'A\tscripts/watch_heartbeat_evidence.py']
CHANGES.sort()

class ObservationFailed(RuntimeError):pass

def need(value,reason):
    if not value:raise ObservationFailed(reason)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

class LogObserver:
    """One Apple log stream. Nonblocking pipe, fixed bytes/lifetime, no reader thread."""
    def __init__(self,command,seconds,cancel_check):
        self.command=command;self.deadline=time.monotonic()+seconds;self.cancel_check=cancel_check
        self.process=None;self.spawn_attempted=False;self.output=bytearray();self.eof=False;self.record={'started':False,'complete':False,
            'process_group_gone':False,'pipe_closed':False,'byte_limit':OSLOG_CAP,'seconds_limit':seconds,
            'timed_out':False,'byte_limit_hit':False,'phases':[]}
    def phase(self,name):
        if len(self.record['phases'])<8:self.record['phases'].append({'phase':name,'at':now()})
    def start(self):
        self.cancel_check();self.phase('spawn_begin');self.spawn_attempted=True
        self.process=subprocess.Popen(self.command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        self.record.update(started=True,started_at=now());self.phase('spawn_returned')
        os.set_blocking(self.process.stdout.fileno(),False)
        self.cancel_check()
    def drain(self,require_running=True):
        self.cancel_check()
        if time.monotonic()>=self.deadline:
            self.record['timed_out']=True;raise RuntimeError('oslog-duration-limit')
        if self.process is None:raise RuntimeError('oslog-not-started')
        # A guard call cannot monopolize the native deadline loop.
        for _ in range(8):
            try:data=os.read(self.process.stdout.fileno(),min(4096,OSLOG_CAP+1-len(self.output)))
            except BlockingIOError:break
            if not data:self.eof=True;break
            remaining=OSLOG_CAP-len(self.output);self.output.extend(data[:remaining])
            if len(data)>remaining:
                self.record['byte_limit_hit']=True;raise RuntimeError('oslog-byte-limit')
        if require_running and (self.eof or self.process.poll() is not None):
            raise RuntimeError('oslog-ended-before-case')
    def finish(self):
        self.phase('stop_begin')
        if self.process is None:
            self.record.update(process_group_gone=not self.spawn_attempted,pipe_closed=True);self.phase('stop_returned');return
        # Stop before any synchronous evidence write. Record-only outer signal
        # handlers remain active; don't start further device work after cancel.
        try:self.record['process_group_gone']=stop_group(self.process,grace=2)
        except BaseException:self.record['process_group_gone']=False
        self.phase('stop_returned')
        try:
            # Only bytes already delivered to this nonblocking pipe are read.
            # Never wait for a descendant that retained an fd.
            for _ in range(17):
                try:data=os.read(self.process.stdout.fileno(),min(4096,OSLOG_CAP+1-len(self.output)))
                except BlockingIOError:break
                if not data:self.eof=True;break
                remaining=OSLOG_CAP-len(self.output);self.output.extend(data[:remaining])
                if len(data)>remaining:self.record['byte_limit_hit']=True;break
        finally:
            self.process.stdout.close();self.record['pipe_closed']=True
        self.record.update(raw_exit=self.process.poll(),bytes=len(self.output),eof=self.eof,finished_at=now(),
            complete=self.record['process_group_gone'] and self.eof and not self.record['byte_limit_hit'] and not self.record['timed_out'])
        self.phase('pipe_closed')

class Controller:
    def __init__(self):
        self.out=Path(os.environ['RUNNER_TEMP'])/'watch-heartbeat-evidence'
        self.path=self.out/OUTPUT
        need(self.out.is_dir() and not self.out.is_symlink(),'evidence-directory-unavailable')
        need(self.path.is_file() and not self.path.is_symlink() and self.path.stat().st_size<=EVIDENCE_CAP,'bootstrap-unavailable')
        self.report=json.loads(self.path.read_bytes());self.started=self.report['started_monotonic']
        need(self.report.get('run_id')==os.environ['GITHUB_RUN_ID'] and self.report.get('run_attempt')==os.environ['GITHUB_RUN_ATTEMPT'] and self.report.get('requested_sha')==os.environ['GITHUB_SHA'],'bootstrap-identity-mismatch')
        need(type(self.started) in (float,int) and 0<=time.monotonic()-self.started<=1200,'invalid-original-clock')
        self.work_deadline=self.started+WORK_SECONDS;self.deadline=self.started+TOTAL_SECONDS
        self.cancelled=None;self.previous={};self.unknown=False;self.owned=[];self.pair=None;self.observer=None
        self.native=b'';self.native_exit=None;self.devices_uncertain=False
        self.report.update(schema=1,state='incomplete',case=CASE,diagnostics_mode='never',product_qualified=False,
            live_sampler_enabled=False,export_calls=0,stages=[],owned_devices=[],device_cleanup=[],
            limits={'native_seconds':300,'work_seconds_from_original_clock':900,'controller_seconds_from_original_clock':1020,
                    'workflow_minutes':20,'external_cancel_minutes':18,'public_files':1,'public_bytes':EVIDENCE_CAP},
            cancellation=None,cleanup_unconfirmed=False)
    def interrupt(self,signum,frame):
        if self.cancelled is None:self.cancelled=signum
    def check(self):
        if self.cancelled is not None:raise ObservationFailed('cancelled')
    def run(self,label,args,seconds=30,cap=65536,*,cleanup=False,allow_nonzero=False,guard=None):
        self.check();need(not self.unknown,'prior-owned-process-unconfirmed')
        deadline=self.deadline if cleanup else self.work_deadline
        available=deadline-time.monotonic()-4
        need(available>0,'original-clock-exhausted')
        seconds=min(seconds,available)
        stage={'label':label,'started_at':now(),'seconds_limit':round(seconds,3),'started':'unknown',
               'exit':None,'timed_out':False,'process_group_gone':False,'capture_finished':False,'output_complete':False}
        self.report['stages'].append(stage);need(len(self.report['stages'])<=32,'stage-count-limit')
        begin=time.monotonic()
        try:
            value=capture(args,seconds=seconds,cap=cap,cleanup_grace=2,guard=guard)
            stage.update(started=True,exit=value.returncode,raw_exit=value.returncode,process_group_gone=True,
                         capture_finished=True,output_complete=True,stdout_bytes=len(value.stdout),stderr_bytes=len(value.stderr))
            if not allow_nonzero:need(value.returncode==0,'command-returned-failure')
            return value.stdout+value.stderr,value.returncode
        except CaptureStopped as error:
            reason=str(error)
            stage.update(started=reason!='interrupted-before-spawn',exit=124,raw_exit=None,timed_out=reason in ('duration-limit','late-exit'),
                process_group_gone=error.cleanup_confirmed,capture_finished=True,output_complete=False,
                byte_limit_hit=reason=='byte-limit',stop_reason=reason if reason in ('duration-limit','late-exit','byte-limit',
                    'descendant-exit-unconfirmed','oslog-duration-limit','oslog-byte-limit','oslog-ended-before-case') else 'capture-stopped',
                cancelled_signal=error.cancelled_signal)
            if error.cancelled_signal is not None:self.cancelled=error.cancelled_signal
            if not error.cleanup_confirmed:self.unknown=True
            if label=='native-case':self.native=error.stdout_prefix+error.stderr_capture;self.native_exit=124
            raise ObservationFailed(stage['stop_reason']) from None
        except BaseException:
            # An error after confirmed capture may be semantic rather than an
            # ownership failure. An unknown spawn must never authorize more work.
            if not stage['process_group_gone']:self.unknown=True
            raise
        finally:
            stage.update(finished_at=now(),elapsed_seconds=round(time.monotonic()-begin,6))
    def text(self,label,args,seconds=30,**kwargs):
        value,_=self.run(label,args,seconds,**kwargs);return value.decode('utf8','strict').strip()
    def source(self,after=False):
        opts={'cleanup':after}
        sha=self.text('source-after' if after else 'source-before',['git','rev-parse','HEAD'],10,**opts)
        need(re.fullmatch('[0-9a-f]{40}',sha) is not None and sha==os.environ['GITHUB_SHA'],'source-sha-mismatch')
        dirty=self.text('source-clean-after' if after else 'source-clean-before',['git','status','--porcelain=v1','--untracked-files=all'],10,**opts)
        need(not dirty,'source-dirty')
        self.report['source_after' if after else 'source_before']={'sha':sha,'clean':True}
    def prepare(self):
        self.source()
        help_text=self.text('xcode-help',['xcodebuild','-help'],15,allow_nonzero=True)
        need('-collect-test-diagnostics' in help_text and 'never' in help_text,'never-mode-not-supported')
        self.report['never_help_verified']=True
        self.derived=Path(os.environ['RUNNER_TEMP'])/'watch-heartbeat-derived'
        need(not self.derived.exists(),'derived-directory-already-exists')
        build=['xcodebuild','-quiet','-project','TouchColorWatch.xcodeproj','-scheme','TouchColorWatch',
            'CODE_SIGNING_ALLOWED=NO','-configuration','Debug','-destination','generic/platform=watchOS Simulator',
            '-derivedDataPath',str(self.derived),'ARCHS=arm64','build-for-testing']
        self.run('debug-build-for-testing',build,420,262144)
        # No Release archive or non-UI suite in this diagnostic invocation.
        inventory=json.loads(self.text('available-devices',['xcrun','simctl','list','devices','available','-j'],30,cap=262144))['devices']
        wr,watch,_=select_profile(inventory,'watchOS-27-0','smallest');need(watch.get('deviceTypeIdentifier')==WATCH_TYPE,'wrong-watch-template')
        pr,phone=phone_template(inventory)
        pairs=json.loads(self.text('initial-pairs',['xcrun','simctl','list','pairs','-j']))
        need(isinstance(pairs.get('pairs'),dict) and len(pairs['pairs'])<=64,'invalid-pair-inventory')
        for role,template,runtime in [('phone',phone,pr),('watch',watch,wr)]:
            self.devices_uncertain=True
            udid=self.text('create-'+role,['xcrun','simctl','create','TouchColor-heartbeat-'+role+'-'+uuid.uuid4().hex[:8],template['deviceTypeIdentifier'],runtime],30)
            verify_new_device(udid,inventory,self.owned)
            self.owned.append({'role':role,'udid':udid});self.report['owned_devices']=list(self.owned)
            self.devices_uncertain=False
        phone_id,watch_id=[x['udid'] for x in self.owned]
        self.devices_uncertain=True
        pair=self.text('pair',['xcrun','simctl','pair',watch_id,phone_id]);uuid.UUID(pair)
        actual=json.loads(self.text('pair-readback',['xcrun','simctl','list','pairs','-j']))
        verify_pair(actual,pair,watch_id,phone_id,pairs['pairs']);self.pair=pair;self.devices_uncertain=False
        activate_owned_pair(actual,pair,watch_id,phone_id,pairs['pairs'],
            lambda key:self.run('activate-pair',['xcrun','simctl','pair_activate',key],30),
            lambda:json.loads(self.text('active-pair-readback',['xcrun','simctl','list','pairs','-j'])))
        for item in self.owned:
            self.run('boot-'+item['role'],['xcrun','simctl','boot',item['udid']],30,allow_nonzero=True)
            self.run('bootstatus-'+item['role'],['xcrun','simctl','bootstatus',item['udid'],'-b'],120)
        self.watch=watch_id
        stream_help=self.text('log-stream-help',['xcrun','simctl','spawn',watch_id,'log','stream','--help'],10,allow_nonzero=True)
        need('--style' in stream_help and 'compact' in stream_help and '--predicate' in stream_help,'log-stream-cli-not-supported')
        self.report['log_stream_help_verified']=True
    def observe(self):
        need(self.work_deadline-time.monotonic()>=NATIVE_SECONDS+8,'full-native-window-unavailable')
        command=['xcrun','simctl','spawn',self.watch,'log','stream','--style','compact','--predicate',
                 'subsystem == "com.mango.touchColor.WatchDiagnostics"']
        self.observer=LogObserver(command,NATIVE_SECONDS+8,self.check)
        self.observer.record.update(device=self.watch,subsystem='com.mango.touchColor.WatchDiagnostics',intended_app_bundle='com.mango.touchColor.watchkitapp')
        self.observer.start()
        need(self.work_deadline-time.monotonic()>=NATIVE_SECONDS+8,'full-native-window-unavailable')
        result=Path(os.environ['RUNNER_TEMP'])/'watch-heartbeat-ui.xcresult'
        need(not result.exists(),'result-bundle-already-exists')
        native=['xcodebuild','test-without-building','-project','TouchColorWatch.xcodeproj','-scheme','TouchColorWatch',
            'CODE_SIGNING_ALLOWED=NO','-configuration','Debug','-destination','platform=watchOS Simulator,id='+self.watch,
            '-derivedDataPath',str(self.derived),'-parallel-testing-enabled','NO',
            '-maximum-concurrent-test-simulator-destinations','1','ARCHS=arm64',
            '-collect-test-diagnostics','never','-test-timeouts-enabled','YES',
            '-default-test-execution-time-allowance','120','-maximum-test-execution-time-allowance','240',
            '-resultBundlePath',str(result),'-only-testing:'+CASE]
        self.report['native_started_at']=now()
        self.native,self.native_exit=self.run('native-case',native,NATIVE_SECONDS,NATIVE_CAP,allow_nonzero=True,guard=self.observer.drain)
    def cleanup(self):
        if self.observer is not None:
            self.observer.finish();self.report['oslog_capture']=self.observer.record
            if not self.observer.record['process_group_gone']:self.unknown=True
        if self.cancelled is not None or self.unknown or self.devices_uncertain:
            self.report['device_cleanup_skipped']='cancelled-or-owned-state-unconfirmed';return
        actions=[['shutdown',x['udid']] for x in reversed(self.owned)]
        if self.pair:actions.append(['unpair',self.pair])
        actions += [['delete',x['udid']] for x in reversed(self.owned)]
        for action,identifier in actions:
            try:
                self.run('cleanup-'+action,['xcrun','simctl',action,identifier],20,cleanup=True)
                self.report['device_cleanup'].append({'action':action,'udid':identifier,'confirmed':True})
            except BaseException:
                self.devices_uncertain=True
                self.report['device_cleanup'].append({'action':action,'udid':identifier,'confirmed':False});break
    def write(self):
        self.report.update(finished_at=now(),elapsed_seconds=round(time.monotonic()-self.started,3),
            cancellation=self.cancelled,cleanup_unconfirmed=self.unknown,device_cleanup_unconfirmed=self.devices_uncertain)
        self.report['native_case_exit']=self.native_exit
        try:
            text=self.native.decode('utf8','strict')
            records=re.findall(r"^Test Case '-\[([^]]+)\]' (started\.|(?:passed|failed|skipped) \([^\n]+ seconds\)\.)$",text,re.M)
            native_stage=next((x for x in self.report['stages'] if x['label']=='native-case'),{})
            complete=native_stage.get('output_complete') is True
            valid=(complete and len(records)==2 and records[0]==(CASE_LOG,'started.') and records[1][0]==CASE_LOG)
            case_state='passed' if valid and records[1][1].startswith('passed (') else 'failed' if valid and records[1][1].startswith('failed (') else 'unconfirmed'
            self.report['case_state']=case_state
            self.report['xctest_idle_wait_logged']='Wait for' in text and 'to idle' in text
            self.report['xctest_idle_notification_missing']='App event loop idle notification not received' in text
            tap=re.findall(r'^\s*t =\s*([0-9.]+)s\s+Tap "watch.edit.copy" Button$',text,re.M)
            idle=re.findall(r'^\s*t =\s*([0-9.]+)s\s+App event loop idle notification not received, will attempt to continue\.$',text,re.M)
            self.report['xctest_copy_tap_seconds']=[float(x) for x in tap[:2]]
            self.report['xctest_idle_notification_missing_seconds']=[float(x) for x in idle[:4]]
            self.report['xctest_allowance_exceeded']='exceeded execution time allowance' in text
            self.report['native_terminal_success']=complete and text.count('** TEST EXECUTE SUCCEEDED **')==1 and '** TEST EXECUTE FAILED **' not in text
            # Retain no arbitrary Xcode/app text. Native capture identity is useful
            # even on failure without uploading its raw bytes.
            self.report['native_output']={'bytes':len(self.native),'sha256':hashlib.sha256(self.native).hexdigest(),'complete':complete}
            if self.observer is not None and self.observer.record['complete']:
                self.report['heartbeat']=summarize(self.native,bytes(self.observer.output))
            else:self.report['heartbeat']={'state':'unavailable','reason':'oslog-capture-not-complete','deadlock_established':False}
        except (UnicodeError,ValueError,TypeError):
            self.report['case_state']='unconfirmed';self.report['heartbeat']={'state':'unavailable','reason':'unsupported-native-output'}
        clean=(not self.unknown and not self.devices_uncertain and self.cancelled is None
               and self.report.get('source_before')==self.report.get('source_after')
               and self.report.get('heartbeat',{}).get('state')=='observed'
               and self.report.get('oslog_capture',{}).get('complete') is True)
        passed=(self.native_exit==0 and self.report.get('case_state')=='passed' and self.report.get('native_terminal_success') is True)
        self.report['state']='case-passed-observation-retained' if clean and passed else 'failed-or-incomplete'
        self.report['product_qualified']=False
        data=(json.dumps(self.report,indent=2)+'\n').encode()
        need(len(data)<=EVIDENCE_CAP,'final-evidence-byte-limit')
        need(list(self.out.iterdir())==[self.path] and self.path.stat().st_nlink==1,'unexpected-evidence-files')
        self.path.write_bytes(data)
        return 0 if clean and passed else 1
    def execute(self):
        for s in (signal.SIGTERM,signal.SIGINT):self.previous[s]=signal.signal(s,self.interrupt)
        try:
            self.prepare();self.observe()
        except BaseException as error:
            self.report['failure_type']=type(error).__name__
            if isinstance(error,ObservationFailed):
                safe={'cancelled','source-sha-mismatch','source-dirty','never-mode-not-supported','wrong-watch-template',
                    'invalid-pair-inventory','log-stream-cli-not-supported','full-native-window-unavailable','command-returned-failure',
                    'original-clock-exhausted','duration-limit','late-exit','byte-limit','capture-stopped','oslog-byte-limit',
                    'oslog-duration-limit','oslog-ended-before-case','descendant-exit-unconfirmed'}
                if str(error) in safe:self.report['failure_reason']=str(error)
        finally:
            try:
                try:self.cleanup()
                except BaseException as error:
                    self.unknown=True;self.report['cleanup_error_type']=type(error).__name__
                if not self.unknown and self.cancelled is None:
                    try:self.source(after=True)
                    except BaseException:self.report['source_after']={'available':False}
                result=self.write()
            finally:
                for s,h in self.previous.items():signal.signal(s,h)
        return 1 if self.cancelled is not None else result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args()
    need(os.environ.get('GITHUB_REPOSITORY')=='100mango/ColorPicker','wrong-repository')
    need(os.environ.get('GITHUB_REF')=='refs/heads/watch-copy-singlecase','wrong-ref')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','wrong-attempt')
    return Controller().execute()

if __name__=='__main__':
    try:raise SystemExit(main())
    except ObservationFailed as error:
        # No raw exception payload/environment enters the console on bootstrap errors.
        print('Watch heartbeat setup unavailable: '+type(error).__name__)
        raise SystemExit(1)
