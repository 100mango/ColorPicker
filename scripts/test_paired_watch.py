#!/usr/bin/env python3
"""Real paired foreground UI flow; host coordinates lifetimes, never app data."""
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import queue
import re
import stat
import subprocess
import threading
import time
import uuid
from bounded_process import run_captured, stop_group
from capture_simulator_checkpoint import publish_acknowledgement
from verify_embedded_watch import verify as verify_embedded_watch
from watch_runtime_pair import phone_template, device_inventory, verify_new_device, verify_pair, activate_owned_pair
from native_resources import snapshot as resource_snapshot

OUT = Path('build/paired-runtime')
report = {}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save_report():
    OUT.mkdir(parents=True, exist_ok=True)
    publish_acknowledgement(OUT/'runtime.json', report)


def run(command, timeout):
    require(not report.get('cleanup_unconfirmed'), 'Prior process group cleanup unconfirmed; refusing further commands')
    start = time.monotonic(); wall = time.time()
    active = {'command': command, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'timeout_seconds': timeout}
    def checkpoint(phase):
        active.update(phase=phase, monotonic_elapsed=round(time.monotonic()-start, 3), wall_elapsed=round(time.time()-wall, 3))
        report['active_command'] = active; save_report()
        print('PAIRED_COMMAND_CHECKPOINT', json.dumps(active), flush=True)
    checkpoint('starting')
    try:
        result = run_captured(command, timeout, checkpoint=checkpoint)
        output, code, diagnostic = result.stdout, result.returncode, (result.stdout+result.stderr)[-6000:]
    except subprocess.TimeoutExpired as error:
        confirmed = bool(getattr(error, 'cleanup_confirmed', False))
        if not confirmed: report['cleanup_unconfirmed'] = True
        output, code, diagnostic = '', 124, 'Timeout; owned process group exit confirmed: '+str(confirmed)
    report['stages'].append({'command': command, 'exit': code, 'seconds': round(time.monotonic()-start, 3), 'wall_seconds': round(time.time()-wall, 3), 'diagnostic': diagnostic})
    report['active_command'] = None; save_report()
    require(code == 0, 'Paired command failed: '+' '.join(command))
    return output.strip()


def product_record(app, role):
    app=Path(app);info=plistlib.loads((app/'Info.plist').read_bytes())
    expected='com.mango.touchColor' if role=='phone' else 'com.mango.touchColor.watchkitapp'
    require(info.get('CFBundleIdentifier')==expected and info.get('CFBundleExecutable')=='TouchColor','Actual installed product identity mismatch')
    require(info.get('CFBundleShortVersionString')=='2.0' and info.get('CFBundleVersion')=='20001','Installed product version mismatch')
    require(info.get('CFBundleSupportedPlatforms')==(['iPhoneSimulator'] if role=='phone' else ['WatchSimulator']),'Installed simulator platform mismatch')
    if role=='watch': require(info.get('WKCompanionAppBundleIdentifier')=='com.mango.touchColor','Installed companion linkage mismatch')
    payloads=[app/'TouchColor']+sorted(app.glob('*.debug.dylib'))
    result={'identifier':expected,'version':info['CFBundleVersion'],'code':{}}
    for path in payloads:
        require(path.is_file() and not path.is_symlink(),'Missing actual owned code payload')
        with path.open('rb') as stream: result['code'][path.name]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result


def product_size(app, maximum_entries=10000, maximum_seconds=0.25):
    """Bounded metadata only, without following links or reading app contents."""
    root=Path(app); require(root.is_dir() and not root.is_symlink(), 'Built app missing')
    started=time.monotonic(); pending=[root]; entries=files=total=0; partial=False
    while pending and not partial:
        with os.scandir(pending.pop()) as children:
            for child in children:
                if entries >= maximum_entries or time.monotonic()-started >= maximum_seconds:
                    partial=True; break
                entries+=1; info=child.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode): pending.append(Path(child.path))
                elif stat.S_ISREG(info.st_mode): files+=1; total+=info.st_size
    return {'bytes_observed':total,'files_observed':files,'entries_observed':entries,'partial':partial}


def resources(label):
    require(not report.get('cleanup_unconfirmed'), 'Prior cleanup unknown; no resource command')
    value=resource_snapshot(label)
    report.setdefault('resources',[]).append(value)
    if value.get('cleanup_unconfirmed'): report['cleanup_unconfirmed']=True
    save_report(); print('PAIRED_RESOURCE_STATE',json.dumps(value),flush=True)
    require(not report.get('cleanup_unconfirmed'), 'Resource command cleanup unknown')


def prepare_owned_pair(selected, booted, original_devices, original_pairs, pair):
    # The prior failed attempt installed the embedded-Watch phone product while
    # its counterpart was still shut down. Match the successfully exercised
    # standalone Watch sequence: boot both owned devices before either install.
    # This is a sequencing hypothesis, not a proven simulator-service diagnosis.
    resources('before owned pair boot')
    for role in ('phone','watch'):
        run(['xcrun','simctl','boot',selected[role]],120); booted.append(selected[role])
        run(['xcrun','simctl','bootstatus',selected[role],'-b'],420)
    inventory=runtime_inventory('both owned devices booted before install',selected,original_devices,original_pairs,pair)
    actual={row['udid'] for rows in inventory.values() for row in rows if row.get('state')=='Booted'}
    require(actual==set(selected.values()), 'Exact owned pair must be the only booted devices before install')
    report['booted_before_install']=sorted(actual); resources('after owned pair boot before install')
    for role in ('phone','watch'):
        product='Debug-iphonesimulator' if role=='phone' else 'Debug-watchsimulator'
        app=Path('build/paired-'+role)/'Build/Products'/product/'TouchColor.app'
        run(['xcrun','simctl','install',selected[role],str(app)],120)
        resources('after '+role+' install')


def installed_products(label, selected):
    values={}
    for role in ('phone','watch'):
        product='Debug-iphonesimulator' if role=='phone' else 'Debug-watchsimulator'
        built=Path('build/paired-'+role)/'Build/Products'/product/'TouchColor.app'
        expected=product_record(built,role)
        path=Path(run(['xcrun','simctl','get_app_container',selected[role],expected['identifier'],'app'],30))
        require(path.is_absolute() and path.is_dir(),'Installed app container missing')
        actual=product_record(path,role)
        require(actual==expected,'Installed code payload differs from the exact built product')
        values[role]=actual
    report.setdefault('installed_products',{})[label]=values;save_report()


def configured_test_run(directory, role, run_id):
    candidates = [p for p in (Path(directory)/'Build/Products').glob('*.xctestrun') if not p.stem.endswith('-paired')]
    require(len(candidates) == 1, 'Expected exactly one generated xctestrun')
    source = candidates[0]; value = plistlib.loads(source.read_bytes()); matched = []
    target = 'TouchColorUITests' if role == 'phone' else 'TouchColorWatchUITests'
    def visit(node):
        if isinstance(node, dict):
            if 'TestBundlePath' in node and target+'.xctest' in node['TestBundlePath']:
                require(node.get('IsUITestBundle') is True, 'Expected generated UI test bundle')
                node.setdefault('EnvironmentVariables', {}).update(TOUCHCOLOR_PAIRED_E2E='1', TOUCHCOLOR_PAIRED_RUN_ID=run_id)
                matched.append({k: node[k] for k in ('TestBundlePath', 'TestHostPath', 'UITargetAppPath', 'IsUITestBundle') if k in node})
            for child in list(node.values()): visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    visit(value)
    require(len(matched) == 1, 'Expected one exact generated UI target')
    require(all(key in matched[0] for key in ('TestHostPath', 'UITargetAppPath')), 'Generated app/runner linkage missing')
    expected_product=Path(directory)/'Build/Products'/('Debug-iphonesimulator' if role=='phone' else 'Debug-watchsimulator')/'TouchColor.app'
    actual_product=Path(matched[0]['UITargetAppPath'].replace('__TESTROOT__',str(source.parent)))
    require(actual_product.resolve()==expected_product.resolve(),'Generated UI target does not reference the verified product')
    report.setdefault('xctestrun', {})[role] = matched[0]
    destination = source.with_name(source.stem+'-paired.xctestrun'); destination.write_bytes(plistlib.dumps(value))
    return destination


class RunningTests:
    def __init__(self, label, command):
        self.label = label; self.ready = threading.Event(); self.markers = []; self.barriers = queue.Queue()
        self.tail = collections.deque(maxlen=1000); self.lock = threading.Lock()
        self.started = time.monotonic(); self.wall_started = time.time(); self.cleanup_confirmed = None
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        self.reader = threading.Thread(target=self.read, daemon=True); self.reader.start()
    def read(self):
        for line in self.process.stdout:
            with self.lock: self.tail.append(line[-4000:])
            found = re.search(r'TOUCHCOLOR_PAIRED_[A-Z_]+(?: [0-9A-F-]{36})?', line)
            if found:
                self.markers.append(found.group(0)); print(found.group(0), flush=True)
                if found.group(0) == 'TOUCHCOLOR_PAIRED_PHONE_READY': self.ready.set()
            if 'TOUCHCOLOR_PAIRED_BARRIER ' in line:
                try: self.barriers.put(json.loads(line.split('TOUCHCOLOR_PAIRED_BARRIER ', 1)[1]))
                except ValueError: self.barriers.put({'invalid': True})
    def stop(self):
        if self.cleanup_confirmed is None:
            self.cleanup_confirmed = stop_group(self.process)
            if not self.cleanup_confirmed: report['cleanup_unconfirmed'] = True
        return self.cleanup_confirmed
    def finish(self, timeout):
        try: code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired: code = 124
        if not self.stop(): code = 124
        self.reader.join(timeout=2)
        with self.lock: tail = ''.join(self.tail)[-96_000:]
        (OUT/(self.label+'-test-tail.log')).write_text(tail)
        report[self.label] = {'exit': code, 'markers': self.markers, 'cleanup_confirmed': self.cleanup_confirmed, 'monotonic_seconds': round(time.monotonic()-self.started, 3), 'wall_seconds': round(time.time()-self.wall_started, 3)}
        return code


def validate_outcome(phone, watch, phone_exit, watch_exit):
    require(phone_exit == 0 and watch_exit == 0, 'Paired XCTest failed')
    for role, process in [('phone', phone), ('watch', watch)]:
        require('TOUCHCOLOR_PAIRED_'+role.upper()+'_RELAUNCH_VERIFIED' in process.markers, role+' relaunch marker missing')
        require(process.cleanup_confirmed is True, role+' process-group cleanup unconfirmed')
    require(report.get('receipt_barrier') == 'acknowledged', 'Matching actual receipt barrier missing')


def verify_result_summary(summary, device_id, role):
    expected={'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}
    require(summary.get('result')=='Passed' and summary.get('totalTestCount')==1, 'Paired result must execute exactly one successful case')
    for key,value in expected.items(): require(summary.get(key)==value, 'Paired result '+key+' mismatch')
    rows=summary.get('devicesAndConfigurations')
    require(isinstance(rows,list) and len(rows)==1,'Expected one actual XCTest destination/configuration')
    row=rows[0]
    for key,value in expected.items(): require(row.get(key)==value, 'Destination '+key+' mismatch')
    device=row.get('device',{})
    require(device.get('deviceId')==device_id,'XCTest executed on a different device or clone')
    require(device.get('platform')==('iOS Simulator' if role=='phone' else 'watchOS Simulator'),'Actual test platform mismatch')
    require(device.get('osVersion')=='27.0' and device.get('architecture')=='arm64','Actual test runtime/architecture mismatch')
    require(not summary.get('testFailures'), 'Unexpected test failure details')
    return {'totalTestCount':1, **expected, 'device':device}


def require_actual_results(selected):
    for role in ('phone','watch'):
        raw=run(['xcrun','xcresulttool','get','test-results','summary','--path','build/paired-'+role+'.xcresult'],45)
        require(len(raw.encode())<=500_000,'Paired summary exceeds bounded evidence limit')
        summary=json.loads(raw)
        (OUT/(role+'-summary.json')).write_text(raw+'\n')
        report.setdefault('verified_results',{})[role]=verify_result_summary(summary,selected[role],role)


def validate_receipt_observations(observations, run_id):
    require(set(observations) == {'phone','watch'}, 'Both receipt observations required')
    request_id=observations['phone']['requestID']
    expected=hashlib.sha256(json.dumps({'version':1,'id':request_id,'colors':['#fe0000']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for role,value in observations.items():
        require(value.get('role')==role and value.get('runID')==run_id, 'Barrier role/run mismatch')
        require(value.get('requestID')==request_id, 'Phone and Watch request UUID mismatch')
        for key,wanted in {'requestProtocol':'touchColorPaletteV1','receiptProtocol':'touchColorReceiptV1','version':'1','outcome':'accepted','receiveChannel':'sendMessage','fingerprint':expected}.items():
            require(value.get(key)==wanted, 'Actual '+role+' receipt '+key+' mismatch')
    return request_id,expected


def runtime_inventory(label, selected, original_devices, original_pairs, pair):
    devices=json.loads(run(['xcrun','simctl','list','devices','-j'],30))['devices']
    pairs=json.loads(run(['xcrun','simctl','list','pairs','-j'],30))
    observed=verify_pair(pairs,pair,selected['watch'],selected['phone'],original_pairs)
    old={d['udid'] for rows in original_devices.values() for d in rows}
    current={d['udid'] for rows in devices.values() for d in rows}
    extra=current-old-set(selected.values())
    report.setdefault('pair_inventory',[]).append({'phase':label,'devices':device_inventory(devices),'owned_pair':observed,'unexpected_new_devices':sorted(extra)})
    require(not extra,'Unexpected simulator creation or XCTest clone; original pair execution unconfirmed')
    require(set(selected.values()).issubset(current),'An owned destination disappeared')
    save_report()
    return devices


def receipt_barrier(processes, selected, runner_ids, run_id, timeout=150):
    deadline = time.monotonic()+timeout; observations = {}
    while len(observations) < 2 and time.monotonic() < deadline:
        for role, process in processes.items():
            require(process.process.poll() is None, role+' exited before actual receipt barrier')
            if role in observations: continue
            try: value = process.barriers.get_nowait()
            except queue.Empty: continue
            require(value.get('role') == role and value.get('runID') == run_id, 'Uncorrelated test barrier')
            require(str(uuid.UUID(value['requestID'])).upper() == value['requestID'], 'Invalid request UUID')
            observations[role] = value
        time.sleep(0.05)
    require(len(observations) == 2, 'Both actual UI receipt observations were not received')
    request_id, fingerprint = validate_receipt_observations(observations, run_id)
    report['receipt_observations'] = observations
    report['expected_payload_fingerprint'] = fingerprint
    require('TOUCHCOLOR_PAIRED_PHONE_REVIEW_CANCELLED '+request_id in processes['phone'].markers, 'Actual review Cancel marker missing')
    require('TOUCHCOLOR_PAIRED_WATCH_ACCEPTED '+request_id in processes['watch'].markers, 'Actual Watch receipt marker missing')
    paths = []
    for role in ('phone', 'watch'):
        container = Path(run(['xcrun', 'simctl', 'get_app_container', selected[role], runner_ids[role], 'data'], 15))
        require(container.is_absolute() and container.is_dir(), 'Missing actual XCTest runner container')
        request = container/'tmp'/('TouchColor-paired-'+run_id+'.json')
        require(request.is_file() and not request.is_symlink() and request.stat().st_size <= 1024, 'Runner barrier request missing or invalid')
        require(json.loads(request.read_text()) == observations[role], 'Runner barrier content mismatch')
        paths.append(request.with_name(request.name+'.ack'))
    # These files acknowledge test lifetime only, in the test runner containers.
    # Neither app container nor WatchConnectivity payload is written by the host.
    for path in paths:
        publish_acknowledgement(path, {'runID': run_id, 'requestID': request_id, 'fingerprint': fingerprint, 'requestProtocol': 'touchColorPaletteV1', 'receiptProtocol': 'touchColorReceiptV1', 'version': '1', 'phase': 'both-observed-receipt'})
    report.update(receipt_barrier='acknowledged', request_id=request_id); save_report()


def cleanup(processes, created, pair, selected, original_devices, original_pairs, booted):
    errors = []
    for process in processes.values():
        if not process.stop(): errors.append(process.label+' process group remains')
        if process.label not in report: process.finish(1)
    if report.get('cleanup_unconfirmed'):
        errors.append('No further commands on unhealthy VM; teardown remains unconfirmed')
    else:
        try:
            # Reconfirm ownership against immutable initial inventories before mutation.
            for identifier in created: verify_new_device(identifier, original_devices, [])
            if pair:
                verify_pair(json.loads(run(['xcrun','simctl','list','pairs','-j'],30)), pair, selected['watch'], selected['phone'], original_pairs)
            for identifier in reversed(booted): run(['xcrun','simctl','shutdown',identifier],60)
            if pair: run(['xcrun','simctl','unpair',pair],60)
            for identifier in reversed(created): run(['xcrun','simctl','delete',identifier],60)
            remaining = json.loads(run(['xcrun','simctl','list','devices','-j'],30))['devices']
            ids = {row['udid'] for rows in remaining.values() for row in rows}
            require(not set(created).intersection(ids), 'Owned device deletion unconfirmed')
            pairs = json.loads(run(['xcrun','simctl','list','pairs','-j'],30))['pairs']
            require(pair is None or pair not in pairs, 'Owned pair deletion unconfirmed')
        except Exception as error: errors.append(str(error))
    report['cleanup_errors'] = errors
    if errors: report['result'] = 'failed'
    return not errors


def main():
    report.update(result='not run', stages=[], transport='production foreground sendMessage', devices=[])
    OUT.mkdir(parents=True, exist_ok=True)
    created=[]; pair=None; processes={}; selected={}; booted=[]; original_devices={}; original_pairs={}
    run_id=str(uuid.uuid4()).upper()
    try:
        for project, marker in [('TouchColor.xcodeproj/project.pbxproj','PhonePairedTransferTests.swift'),('TouchColorWatch.xcodeproj/project.pbxproj','WatchPairedTransferTests.swift')]:
            require(marker in Path(project).read_text(), 'UI target registration missing: '+marker)
        report['sha']=run(['git','rev-parse','HEAD'],10)
        for target, platform, directory in [('TouchColor','iOS','paired-phone'),('TouchColorWatch','watchOS','paired-watch')]:
            run(['xcodebuild','-quiet','-project',target+'.xcodeproj','-scheme',target,'-configuration','Debug','-destination','generic/platform='+platform+' Simulator','-derivedDataPath','build/'+directory,'ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','build-for-testing'],420)
        report['embedded_simulator_product']=verify_embedded_watch('build/paired-phone/Build/Products/Debug-iphonesimulator/TouchColor.app','simulator',False,build_for_testing=True)
        report['built_product_sizes']={role:product_size(Path('build/paired-'+role)/'Build/Products'/platform/'TouchColor.app')
            for role,platform in [('phone','Debug-iphonesimulator'),('watch','Debug-watchsimulator')]}
        original_devices=json.loads(run(['xcrun','simctl','list','devices','-j'],30))['devices']
        original_pairs=json.loads(run(['xcrun','simctl','list','pairs','-j'],30))['pairs']
        report['original_devices']=device_inventory(original_devices); report['original_pairs']=original_pairs
        phone=phone_template(original_devices)
        watches=[(r,d) for r,rows in original_devices.items() if r.endswith('watchOS-27-0') for d in rows if d.get('isAvailable') and d.get('name','').startswith('Apple Watch')]
        require(bool(watches),'No installed watchOS27 template')
        for role,(runtime,template) in [('phone',phone),('watch',watches[0])]:
            identifier=run(['xcrun','simctl','create','TouchColor-paired-'+role+'-'+run_id[:8],template['deviceTypeIdentifier'],runtime],60)
            verify_new_device(identifier,original_devices,[{'udid':x} for x in created]); created.append(identifier); selected[role]=identifier
            report['devices'].append({'role':role,'id':identifier,'runtime':runtime,'type':template['deviceTypeIdentifier']})
        candidate=run(['xcrun','simctl','pair',selected['watch'],selected['phone']],60); uuid.UUID(candidate)
        pair_inventory=json.loads(run(['xcrun','simctl','list','pairs','-j'],30))
        verify_pair(pair_inventory,candidate,selected['watch'],selected['phone'],original_pairs)
        pair=candidate
        report['active_pair']=activate_owned_pair(pair_inventory,pair,selected['watch'],selected['phone'],original_pairs,
            lambda identifier: run(['xcrun','simctl','pair_activate',identifier],60),
            lambda: json.loads(run(['xcrun','simctl','list','pairs','-j'],30)))
        runner_ids={}; paths={}
        prepare_owned_pair(selected,booted,original_devices,original_pairs,pair)
        for role in ('phone','watch'):
            product='Debug-iphonesimulator' if role=='phone' else 'Debug-watchsimulator'
            directory=Path('build/paired-'+role)/'Build/Products'/product
            target='TouchColorUITests' if role=='phone' else 'TouchColorWatchUITests'
            runner_ids[role]=plistlib.loads((directory/(target+'-Runner.app/Info.plist')).read_bytes())['CFBundleIdentifier']
            require(runner_ids[role].startswith('com.mango.touchColor.'+target), 'Unexpected actual runner product')
            paths[role]=configured_test_run('build/paired-'+role,role,run_id)
        def command(role,test):
            platform='iOS' if role=='phone' else 'watchOS'
            return ['xcodebuild','-xctestrun',str(paths[role]),'-destination','platform='+platform+' Simulator,id='+selected[role],'-resultBundlePath','build/paired-'+role+'.xcresult','-parallel-testing-enabled','NO','-collect-test-diagnostics','never','-test-timeouts-enabled','YES','-maximum-test-execution-time-allowance','240','-only-testing:'+test,'test-without-building']
        installed_products('before XCTest',selected)
        runtime_inventory('before XCTest',selected,original_devices,original_pairs,pair)
        processes['phone']=RunningTests('phone',command('phone','TouchColorUITests/PhonePairedTransferTests/testIncomingForegroundTransferReviewAcceptAndRelaunch'))
        require(processes['phone'].ready.wait(timeout=120),'Phone actual inbox readiness missing')
        processes['watch']=RunningTests('watch',command('watch','TouchColorWatchUITests/WatchPairedTransferTests/testForegroundSendAcceptReceiptAndBothLocalStatesAfterRelaunch'))
        receipt_barrier(processes,selected,runner_ids,run_id)
        watch_exit=processes['watch'].finish(90); phone_exit=processes['phone'].finish(90)
        validate_outcome(processes['phone'],processes['watch'],phone_exit,watch_exit)
        require_actual_results(selected)
        installed_products('after XCTest',selected)
        runtime_inventory('after XCTest before owned cleanup',selected,original_devices,original_pairs,pair)
        report['result']='passed'
    except Exception as error:
        report['result']='failed'; report['error']=str(error)
    finally:
        cleanup(processes,created,pair,selected,original_devices,original_pairs,booted)
        save_report(); print('PAIRED_RESULT',json.dumps(report),flush=True)
    return 0 if report['result']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
