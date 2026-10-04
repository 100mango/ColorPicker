#!/usr/bin/env python3
"""One native platform per invocation on the existing standard runner; bounded real builds/tests."""
import datetime,json,os,signal,subprocess,sys,struct,zlib,threading,re,plistlib,time,uuid
from pathlib import Path
from capture_simulator_checkpoint import capture as capture_checkpoint, fail_cached_capture
from watch_profiles import select_profile
from watch_runtime_pair import phone_template, device_inventory, verify_pair, verify_new_device
from bounded_process import run_captured, check_output, stop_group
from vision_suites import CASES as VISION_CASES, needs_photo_seed
from native_resources import snapshot as resource_snapshot
kind=sys.argv[1]; assert kind in ('vision','watch','tv')
name={'vision':'TouchColorVision','watch':'TouchColorWatch','tv':'TouchColorTV'}[kind]; project=name+'.xcodeproj'
platform={'vision':'visionOS','watch':'watchOS','tv':'tvOS'}[kind]
runtime_suffix={'vision':'xrOS-27-0','watch':'watchOS-27-0','tv':'tvOS-27-0'}[kind]
out=Path('build')/(kind+'-runtime');out.mkdir(parents=True,exist_ok=True)
report={'captures':[],'platform':kind,'sha':check_output(['git','rev-parse','HEAD'],text=True,timeout=10).strip(),'stages':[]}
def run(command,timeout,required=True):
    if report.get('cleanup_unconfirmed'):
        if required: raise RuntimeError('Prior process exit is unconfirmed; no new work on this VM')
        return 124
    started=time.monotonic();wall_started=time.time();started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['active_command']={'command':command,'started_at':started_at,'started_monotonic':started,'timeout_seconds':timeout,'phase':'starting'}
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'RUN', ' '.join(command),flush=True)
    diagnostics=[]
    p=subprocess.Popen(command,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    report['active_command'].update(pid=p.pid,phase='running')
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    print('NATIVE_COMMAND_STARTED',json.dumps(report['active_command']),flush=True)
    def output():
        for line in p.stdout:
            print(line,end='',flush=True)
            checkpoint=re.search(r'TOUCHCOLOR_CAPTURE_REQUEST ([0-9A-F-]{36})',line)
            if checkpoint and kind=='vision' and device and len(report['captures'])<16:
                try:
                    if report.get('cleanup_unconfirmed'):
                        result=fail_cached_capture(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),'Host diagnostic process exit was unconfirmed; no screenshot process was started')
                    else:
                        result=capture_checkpoint(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),out/'screenshots')
                    if result.get('cleanup_unconfirmed'): report['cleanup_unconfirmed']=True
                    report['captures'].append(result);print('SIMULATOR_CHECKPOINT',json.dumps(result),flush=True)
                except Exception as error:
                    failure=fail_cached_capture(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),str(error))
                    if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
                    report['captures'].append(failure);print('SIMULATOR_CHECKPOINT_FAILURE',json.dumps(failure),flush=True)
            if (re.match(r'(?:/.*|xcodebuild): error: ',line) or ('app icon set' in line and 'unassigned child' in line)) and len(diagnostics)<30: diagnostics.append(line.rstrip()[:2048])
    reader=threading.Thread(target=output,daemon=True);reader.start()
    cleanup_error=None
    try:code=p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # A stuck test process must not turn our command deadline into an
        # unbounded wait while reaping after SIGKILL. The VM job owns final cleanup.
        report['active_command'].update(phase='deadline exceeded',elapsed_seconds=round(time.monotonic()-started,3),wall_elapsed_seconds=round(time.time()-wall_started,3),observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
        print('NATIVE_COMMAND_DEADLINE_EXCEEDED',json.dumps(report['active_command']),flush=True)
        if not stop_group(p):
            cleanup_error='Owned process-group exit was not confirmed after bounded TERM/KILL waits'
            report['cleanup_unconfirmed']=True
        code=124
    if not stop_group(p):
        report['cleanup_unconfirmed']=True
        cleanup_error='Owned descendants remain after command leader exit'
        code=124
    reader.join(timeout=5)
    # actool can emit asset errors while xcodebuild incorrectly exits zero. Preserve and fail them.
    if code==0 and diagnostics: code=65
    report['stages'].append({'command':command,'exit':code,'compiler_errors':diagnostics,'cleanup_error':cleanup_error,'started_at':started_at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-started,3),'wall_elapsed_seconds':round(time.time()-wall_started,3)})
    report['active_command']=None
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    if required and code:raise RuntimeError('Stage failed with exit '+str(code)+': '+' '.join(command))
    return code
def resources(label):
    if report.get('cleanup_unconfirmed'): return
    sample=resource_snapshot(label)
    report.setdefault('resources',[]).append(sample)
    if sample.get('cleanup_unconfirmed'): report['cleanup_unconfirmed']=True
    print('NATIVE_RESOURCE_STATE',json.dumps(sample),flush=True)
device=None
owned_watch_devices=[]
owned_watch_pair=None
photo_seed_failed=False
try:
    common=['xcodebuild','-quiet','-project',project,'-scheme',name,'CODE_SIGNING_ALLOWED=NO']
    run(common+['-configuration','Release','-destination','generic/platform='+platform,'-derivedDataPath','build/'+kind+'-device','build'],420)
    binary=Path('build')/(kind+'-device')/'Build/Products'/{'vision':'Release-xros','watch':'Release-watchos','tv':'Release-appletvos'}[kind]/'TouchColor.app/TouchColor'
    bundle=binary.parent
    info=plistlib.loads((bundle/'Info.plist').read_bytes())
    expected_id='com.mango.touchColor.watchkitapp' if kind=='watch' else 'com.mango.touchColor'
    expected_minimum={'watch':'9.0','tv':'17.0','vision':'1.0'}[kind]
    assert info['CFBundleIdentifier']==expected_id, info.get('CFBundleIdentifier')
    assert info['MinimumOSVersion']==expected_minimum, info.get('MinimumOSVersion')
    assert info['CFBundleShortVersionString']=='2.0' and info['CFBundleVersion']=='20001'
    assert info['CFBundleExecutable']=='TouchColor'
    privacy=bundle/'PrivacyInfo.xcprivacy';assert privacy.is_file(), 'Release privacy manifest missing'
    privacy_value=plistlib.loads(privacy.read_bytes())
    check_output([sys.executable,'scripts/verify_privacy_manifest.py',str(privacy),'container' if kind=='tv' else 'selected'],timeout=30)
    report['release_resource_files']=[p.name for p in bundle.iterdir() if p.is_file()]
    assert (bundle/'Assets.car').is_file(), 'Release compiled icon assets missing'
    report['release_bundle']={key:info.get(key) for key in ['CFBundleIdentifier','CFBundleName','CFBundleDisplayName','CFBundleExecutable','CFBundleShortVersionString','CFBundleVersion','MinimumOSVersion','CFBundleSupportedPlatforms','CFBundleIcons','CFBundleIconName']}
    report['release_bundle'].update(privacy_manifest=True,compiled_assets=True,unsigned=True)
    report['release_bundle']['required_api_reasons']=privacy_value['NSPrivacyAccessedAPITypes']
    print('RELEASE_BUNDLE',json.dumps(report['release_bundle']),flush=True)
    run(['file',str(binary)],30)
    linked_libraries=check_output(['otool','-L',str(binary)],text=True,timeout=30).splitlines()[1:]
    report['release_linked_libraries']=[line.strip() for line in linked_libraries]
    assert not any(name in line for line in linked_libraries for name in ('Pods/','GPUImage','Masonry')), 'Retired dependency linked into native Release'
    print('NATIVE_RELEASE_LINKED_LIBRARIES',json.dumps(report['release_linked_libraries']),flush=True)
    load_commands=check_output(['otool','-l',str(binary)],text=True,timeout=30).splitlines()
    summary=[]
    for index,line in enumerate(load_commands):
        if 'LC_BUILD_VERSION' in line: summary.extend(load_commands[index:index+8])
    report['binary_platform_minimum']=summary;print('\n'.join(summary),flush=True)
    text=check_output(['strings',str(binary)],text=True,timeout=30)
    assert 'TOUCHCOLOR_PAIRED_E2E' not in text and 'TOUCHCOLOR_TEST_DEFAULTS' not in text and '--ui-test-reset' not in text, 'Debug seam leaked into Release'
    assert 'WATCH_EDITOR' not in text and 'com.mango.touchColor.WatchDiagnostics' not in text, 'Debug Watch lifecycle diagnostics leaked into Release'
    run(common+['-configuration','Debug','-destination','generic/platform='+platform+' Simulator','-derivedDataPath','build/'+kind+'-tests','ARCHS=arm64','build-for-testing'],420)
    if kind=='vision':
        runner_info=Path('build/vision-tests/Build/Products/Debug-xrsimulator/TouchColorVisionUITests-Runner.app/Info.plist')
        report['ui_runner_identifier']=plistlib.loads(runner_info.read_bytes())['CFBundleIdentifier']
        assert report['ui_runner_identifier'].startswith('com.mango.touchColor.TouchColorVisionUITests'), 'Unexpected UI runner product'
    devices=json.loads(check_output(['xcrun','simctl','list','devices','available','-j'],timeout=30))['devices']
    candidates=[(runtime,d) for runtime,rows in devices.items() if runtime.endswith(runtime_suffix) for d in rows if d.get('isAvailable')]
    if not candidates:raise RuntimeError('No installed available '+runtime_suffix+' device')
    if kind=='watch':
        size=os.environ.get('TOUCHCOLOR_WATCH_PROFILE','largest')
        runtime,device,inventory=select_profile(devices,runtime_suffix,size)
        report['watch_profile']=size;report['watch_available_inventory']=inventory
        print('WATCH_AVAILABLE_PROFILE_INVENTORY',json.dumps(inventory),flush=True)
        runtimes=json.loads(check_output(['xcrun','simctl','list','runtimes','-j'],timeout=30))['runtimes']
        installed=next(value for value in runtimes if value['identifier']==runtime)
        report['watch_runtime_supported_device_types']=installed.get('supportedDeviceTypes',[])
        print('WATCH_RUNTIME_SUPPORTED_DEVICE_TYPES',json.dumps(report['watch_runtime_supported_device_types']),flush=True)
        report['watch_template']=device.copy()
        report['watch_phone_device_inventory']=device_inventory(devices)
        original_pairs=json.loads(check_output(['xcrun','simctl','list','pairs','-j'],timeout=30))
        assert isinstance(original_pairs.get('pairs'),dict) and len(original_pairs['pairs'])<=64, 'Unexpected initial pair inventory'
        report['watch_pair_inventory_before']=original_pairs
        print('WATCH_PAIR_PREREQUISITE_INVENTORY',json.dumps({'devices':report['watch_phone_device_inventory'],'pairs':original_pairs}),flush=True)
        phone_runtime,phone=phone_template(devices)
        # Default devices are templates only. All boot/pair/cleanup mutations use
        # new UUIDs created by this invocation, also suitable for later transport E2E.
        for role,template,target_runtime in [('phone',phone,phone_runtime),('watch',device,runtime)]:
            created=check_output(['xcrun','simctl','create','TouchColor-owned-'+role+'-'+str(uuid.uuid4())[:8],template['deviceTypeIdentifier'],target_runtime],text=True,timeout=60).strip()
            verify_new_device(created,devices,owned_watch_devices)
            owned_watch_devices.append({'role':role,'udid':created,'runtime':target_runtime,'deviceTypeIdentifier':template['deviceTypeIdentifier']})
            report['owned_watch_devices']=owned_watch_devices
            print('WATCH_OWNED_DEVICE_CREATED',json.dumps(owned_watch_devices[-1]),flush=True)
        phone_id,watch_id=[value['udid'] for value in owned_watch_devices]
        paired=check_output(['xcrun','simctl','pair',watch_id,phone_id],text=True,timeout=60).strip()
        uuid.UUID(paired)
        actual_pairs=json.loads(check_output(['xcrun','simctl','list','pairs','-j'],timeout=30))
        record=verify_pair(actual_pairs,paired,watch_id,phone_id,original_pairs['pairs'])
        owned_watch_pair=paired
        report['watch_owned_pair']={'id':paired,'record':record}
        print('WATCH_OWNED_PAIR_VERIFIED',json.dumps(report['watch_owned_pair']),flush=True)
        run(['xcrun','simctl','pair_activate',paired],60)
        resources('before owned phone boot')
        run(['xcrun','simctl','boot',phone_id],180)
        run(['xcrun','simctl','bootstatus',phone_id,'-b'],420)
        device={**device,'udid':watch_id,'name':device['name']+' (owned test pair)'}
    else: runtime,device=candidates[0]
    report.update(runtime=runtime,device=device)
    resources('before boot')
    run(['xcrun','simctl','boot',device['udid']],180,required=False)
    run(['xcrun','simctl','bootstatus',device['udid'],'-b'],420)
    if kind=='vision':
        # This runner may ship SDKs/CoreSimulator without the graphical Simulator app.
        # Discover an actual Apple bundle first; absence never gates app XCTest execution.
        developer=Path(os.environ['DEVELOPER_DIR'])
        candidates=[developer/'Applications/Simulator.app',developer.parent/'Applications/Simulator.app',Path('/Applications/Simulator.app')]
        candidates+=list(Path('/Applications').glob('*.app/Contents/Developer/Applications/Simulator.app'))[:12]
        discovered=[];checked=[]
        for candidate in dict.fromkeys(candidates):
            info=candidate/'Contents/Info.plist';checked.append({'path':str(candidate),'exists':candidate.is_dir()})
            if info.is_file():
                try:
                    if plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')=='com.apple.iphonesimulator': discovered.append(candidate)
                except (ValueError, OSError, plistlib.InvalidFileException): pass
        report['simulator_window_discovery']={'checked':checked,'matching_bundles':[str(p) for p in discovered]}
        print('SIMULATOR_WINDOW_DISCOVERY',json.dumps(report['simulator_window_discovery']),flush=True)
        if discovered: run(['open','-a',str(discovered[0]),'--args','-CurrentDeviceUDID',device['udid']],30,required=False)
        else: report['simulator_window']='No graphical Simulator bundle found in bounded standard locations; supported headless runtime tests continue'
    if needs_photo_seed(kind, os.environ.get('TOUCHCOLOR_VISION_CASE')):
        w,h=300,200
        palette=[bytes(v) for v in [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]]
        rows=b''.join(b'\0'+b''.join(palette[(y//100)*3+x//100] for x in range(w)) for y in range(h))
        chunk=lambda n,d:struct.pack('>I',len(d))+n+d+struct.pack('>I',zlib.crc32(n+d)&0xffffffff)
        fixture=out/'asymmetric.png';fixture.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
        photo_seed_failed = run(['xcrun','simctl','addmedia',device['udid'],str(fixture)],120,required=False) != 0
        report['photos_seed']='failed' if photo_seed_failed else 'passed'
    else:
        report['photos_seed']='not required by this exact case'
    skip=[]
    if photo_seed_failed:
        # Preserve the failed prerequisite, but still execute unrelated real input, storage and UI paths.
        case={'vision':'VisionWorkflowTests/testRealPhotosImport','tv':'TVWorkflowTests/testActualPhotosRemoteSamplingZoomPaletteCodeAndPersistence'}[kind]
        skip=['-skip-testing:'+name+'UITests/'+case]
    resources('before tests')
    # Keep build logs quiet, but retain runtime test/checkpoint output for precise failures.
    test_common=[value for value in common if value!='-quiet']
    # Actual XCTest install and launch, not a launchctl dump, establishes app readiness.
    test_arguments=['-configuration','Debug','-destination','platform='+platform+' Simulator,id='+device['udid'],
        '-derivedDataPath','build/'+kind+'-tests','-parallel-testing-enabled','NO','-collect-test-diagnostics','never',
        '-test-timeouts-enabled','YES','-default-test-execution-time-allowance','180' if kind=='vision' else '120',
        '-maximum-test-execution-time-allowance','360' if kind=='vision' else '240' if kind=='watch' else '120','ARCHS=arm64','test-without-building']
    if kind=='vision':
        # Preserve a complete hosted result even if an independent spatial UI process stalls.
        run(test_common+test_arguments+['-resultBundlePath','build/vision-tests.xcresult','-only-testing:TouchColorVisionTests'],360)
        case=os.environ['TOUCHCOLOR_VISION_CASE']
        assert case in VISION_CASES, 'Unknown isolated Vision case'
        method,budget=VISION_CASES[case]
        assert int(os.environ['TOUCHCOLOR_EVIDENCE_LIMIT'])==budget, 'Vision evidence allocation differs from exact inventory'
        report['ui_scope']={'case':case,'cases':[method],'evidence_bytes':budget,'fresh_vm':True}
        selected=['-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+method]
        print('VISION_UI_EXACT_SCOPE',json.dumps(report['ui_scope']),flush=True)
        resources('before isolated '+method)
        try:
            run(test_common+test_arguments+['-resultBundlePath','build/vision-ui.xcresult']+selected+skip,600)
        finally:
            resources('after isolated '+method)
    elif kind=='watch':
        # Preserve completed hosted evidence independently. The observed49mm cold
        # install/hosted startup consumed much of a shared840s command, so later UI
        # cases never ran. Each phase remains bounded on the same fresh VM; the
        # outer25-minute job and per-case120/240s allowances are unchanged.
        report['xctest_summary_scope']='hosted tests only; watch-ui-summary.json contains the separate UI result'
        run(test_common+test_arguments+['-resultBundlePath','build/watch-tests.xcresult','-only-testing:TouchColorWatchTests'],480)
        run(test_common+test_arguments+['-resultBundlePath','build/watch-ui.xcresult','-only-testing:TouchColorWatchUITests'],840)
    else:
        run(test_common+test_arguments+['-resultBundlePath','build/'+kind+'-tests.xcresult']+skip,660)
    report['tests']='passed'
    if photo_seed_failed: raise RuntimeError('Photos seeding timed out or failed; other native tests executed, real Photos import remains unqualified')
    report['result']='passed'
except Exception as error:
    if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
    report['result']='failed';report['error']=str(error);print('NATIVE_PLATFORM_FAILURE',str(error),flush=True)
finally:
    if kind=='watch' and device and any(value['udid']==device['udid'] for value in owned_watch_devices) and not report.get('cleanup_unconfirmed'):
        try:
            lifecycle=run_captured(['xcrun','simctl','spawn',device['udid'],'log','show','--last','20m','--style','compact',
                '--predicate','subsystem == "com.mango.touchColor.WatchDiagnostics"'],text=True,timeout=15)
            lines=[line[:400] for line in lifecycle.stdout.splitlines() if 'WATCH_EDITOR' in line]
            retained=(lines[:16]+lines[-64:]) if len(lines)>80 else lines
            report['watch_editor_lifecycle']={'exit':lifecycle.returncode,'matched_events':len(lines),'events':retained}
            print('WATCH_EDITOR_LIFECYCLE',json.dumps(report['watch_editor_lifecycle']),flush=True)
        except Exception as error:
            report['watch_editor_lifecycle']={'error':type(error).__name__}
            if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
    if not report.get('cleanup_unconfirmed'): resources('after platform attempt')
    result_bundle=Path('build')/(kind+'-tests.xcresult')
    if result_bundle.exists() and not report.get('cleanup_unconfirmed'):
        try:
            summary_run=run_captured(['xcrun','xcresulttool','get','test-results','summary','--path',str(result_bundle)],text=True,timeout=30)
            if summary_run.returncode==0:
                summary=json.loads(summary_run.stdout)
                report['xctest_summary']={key:summary.get(key) for key in ['result','passedTests','failedTests','skippedTests','totalTestCount']}
                report['xctest_summary']['failures']=[{'test':f.get('testIdentifierString'),'message':f.get('failureText','')[:1600]} for f in summary.get('testFailures',[])[:12]]
                print('NATIVE_XCTEST_SUMMARY',json.dumps(report['xctest_summary']),flush=True)
            else: report['summary_error']=(summary_run.stdout+summary_run.stderr)[-2000:]
        except Exception as error:
            report['summary_error']=str(error)
            if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
    if owned_watch_devices and not report.get('cleanup_unconfirmed'):
        for owned in reversed(owned_watch_devices): run(['xcrun','simctl','shutdown',owned['udid']],60,required=False)
        if owned_watch_pair and not report.get('cleanup_unconfirmed'): run(['xcrun','simctl','unpair',owned_watch_pair],60,required=False)
        for owned in reversed(owned_watch_devices):
            if not report.get('cleanup_unconfirmed'): run(['xcrun','simctl','delete',owned['udid']],60,required=False)
    elif device and kind!='watch' and not report.get('cleanup_unconfirmed'):
        run(['xcrun','simctl','shutdown',device['udid']],60,required=False)
    if report.get('cleanup_unconfirmed'): report['simulator_cleanup']='No further commands; disposable VM teardown remains authoritative'
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
if report['result']!='passed':raise SystemExit(1)
