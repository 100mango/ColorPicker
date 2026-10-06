#!/usr/bin/env python3
"""One native platform per invocation on the existing standard runner; bounded real builds/tests."""
import datetime,json,os,signal,subprocess,sys,struct,zlib,threading,re,plistlib,time,uuid
from pathlib import Path
from capture_simulator_checkpoint import capture as capture_checkpoint, fail_cached_capture, prime_container
from watch_profiles import select_profile
from watch_runtime_pair import phone_template, device_inventory, verify_pair, verify_new_device, activate_owned_pair
from bounded_process import run_captured, check_output, stop_group
from vision_suites import CASES as VISION_CASES, needs_photo_seed
from native_resources import snapshot as resource_snapshot, require_responsive
from job_budget import enabled_budget, fail_record, BudgetExhausted, EXPECTED_MINUTES
from native_content_size import TouchSizeRunner, applicable_cases, run_largest, qualified, permits_public_trait_fallback, run_public_trait_fallback
from watch_diagnostics import ListFrameDiagnostics, summarize_editor_lifecycle, log_lookback
from watch_failure_continuation import (BUNDLE as WATCH_UI_BUNDLE, WatchCaseLifecycle,
    checkpoint as watch_checkpoint, record_failure, require_no_failures)
from vision_offline_result import pending as vision_summary_pending, confirm_shutdown as confirm_vision_shutdown, prepare_hosted as prepare_vision_hosted, prepare_normal as prepare_vision_normal
from vision_capture_format import verify_generated as verify_capture_format
from vision_diagnostic_result import begin_largest_execution, prepare_failed_largest
from native_text_rows import from_environment as text_row_from_environment, vision_roles
kind=sys.argv[1]
if kind not in ('vision','watch','tv'): raise ValueError('Unknown native platform')
name={'vision':'TouchColorVision','watch':'TouchColorWatch','tv':'TouchColorTV'}[kind]; project=name+'.xcodeproj'
platform={'vision':'visionOS','watch':'watchOS','tv':'tvOS'}[kind]
runtime_suffix={'vision':'xrOS-27-0','watch':'watchOS-27-0','tv':'tvOS-27-0'}[kind]
out=Path('build')/(kind+'-runtime');out.mkdir(parents=True,exist_ok=True)
report={'captures':[],'platform':kind,'sha':check_output(['git','rev-parse','HEAD'],text=True,timeout=10).strip(),'stages':[]}
text_row=text_row_from_environment(kind,report['sha']) if kind in ('vision','watch') else None
text_phase=text_row['phase'] if text_row else 'normal'
if text_row is not None: report['native_text_row']=text_row
watch_frames=ListFrameDiagnostics()
if kind=='watch': report['watch_list_frames']=watch_frames.report
def run(command,timeout,required=True):
    from job_budget import enabled_budget, fail_record, BudgetExhausted
    budget=enabled_budget()
    if budget is not None:
        try:
            minimum=1
            if command[:2]==['xcodebuild','test-without-building']:
                allowance=int(command[command.index('-maximum-test-execution-time-allowance')+1]) if '-maximum-test-execution-time-allowance' in command else 180
                minimum=min(timeout,max(180,allowance+60)) # Keep the whole declared case plus launch allowance.
            timeout=budget.admit(' '.join(command[:3]),timeout,minimum=minimum,cleanup=0)
        except (BudgetExhausted,ValueError) as error:
            report['budget_incomplete']={'command':command,'phase':budget.phase,'reason':str(error),'started':False}
            confirmed=getattr(error,'cleanup_confirmed',False) is True
            if not confirmed: report['cleanup_unconfirmed']=True
            report['stages'].append({'command':command,'exit':124,'started':False,'budget_incomplete':str(error),
                'process_group_gone':confirmed,'capture_reader_finished':confirmed,'elapsed_seconds':0,'wall_elapsed_seconds':0})
            fail_record(error,phase=budget.phase,cleanup_unconfirmed=not confirmed)
            if required: raise
            return 124
    if report.get('cleanup_unconfirmed'):
        if required: raise RuntimeError('Prior process exit is unconfirmed; no new work on this VM')
        return 124
    started=time.monotonic();wall_started=time.time();started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['active_command']={'command':command,'started_at':started_at,'started_monotonic':started,'timeout_seconds':timeout,'phase':'starting'}
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'RUN', ' '.join(command),flush=True)
    diagnostics=[];capture_start=len(report['captures']);runner_capture_failed=False
    watch_cases=WatchCaseLifecycle() if kind=='watch' and '-resultBundlePath' in command and command[command.index('-resultBundlePath')+1]==WATCH_UI_BUNDLE else None
    p=subprocess.Popen(command,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    report['active_command'].update(pid=p.pid,phase='running')
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    print('NATIVE_COMMAND_STARTED',json.dumps(report['active_command']),flush=True)
    reader_complete=threading.Event()
    reader_errors=[]
    def read_output():
        nonlocal runner_capture_failed
        for line in p.stdout:
            print(line,end='',flush=True)
            if kind=='watch': watch_frames.record(line)
            if watch_cases is not None: watch_cases.record(line)
            capture_failure=re.search(r'TOUCHCOLOR_VISION_CAPTURE_FAILED operation_unconfirmed=(true|false)',line)
            if capture_failure and kind=='vision':
                runner_capture_failed=True
                if capture_failure.group(1)=='true':
                    report['simulator_operation_unconfirmed']=True
                    report['cleanup_unconfirmed']=True
                record_failure(report,'vision-checkpoint','Runner rejected required simulator checkpoint')
                (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
            ready=re.search(r'TOUCHCOLOR_VISION_RUNNER_READY ([0-9A-F-]{36})',line)
            if ready and kind=='vision' and device:
                try:
                    if report.get('cleanup_unconfirmed'): raise RuntimeError('Prior owned process cleanup is unconfirmed')
                    report['runner_container_cache']=prime_container(device['udid'],report['ui_runner_identifier'],ready.group(1))
                except Exception as error:
                    report['runner_container_cache']={'success':False,'error':type(error).__name__,'detail':str(error)[:500]}
                    if isinstance(error,subprocess.TimeoutExpired):
                        report['runner_container_cache']['host_cleanup_confirmed']=getattr(error,'cleanup_confirmed',False) is True
                        report['simulator_operation_unconfirmed']=True
                        report['cleanup_unconfirmed']=True
                print('VISION_RUNNER_CONTAINER_CACHE',json.dumps(report['runner_container_cache']),flush=True)
            checkpoint=re.search(r'TOUCHCOLOR_CAPTURE_REQUEST ([0-9A-F-]{36})',line)
            if checkpoint and kind=='vision' and device and len(report['captures'])<16:
                try:
                    if report.get('cleanup_unconfirmed'):
                        result=fail_cached_capture(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),'Prior owned operation is unconfirmed; no screenshot process was started',require_primed=True)
                    else:
                        result=capture_checkpoint(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),out/'screenshots',may_start=lambda: not report.get('cleanup_unconfirmed'),require_primed=True)
                except Exception as error:
                    ambiguous=isinstance(error,subprocess.TimeoutExpired)
                    if ambiguous:
                        report['simulator_operation_unconfirmed']=True
                        report['cleanup_unconfirmed']=True
                    try:
                        result=fail_cached_capture(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),str(error),require_primed=True,
                                                   operation_unconfirmed=ambiguous or bool(report.get('cleanup_unconfirmed')))
                    except Exception as ack_error:
                        result={'id':checkpoint.group(1),'success':False,'error':str(error),'acknowledged':False,
                                'acknowledgement_error':str(ack_error)}
                    if ambiguous:
                        result.update(simulator_operation_unconfirmed=True,cleanup_unconfirmed=True,
                                      host_cleanup_confirmed=getattr(error,'cleanup_confirmed',False) is True)
                if report.get('text_size_phase')=='largest': result['system_text_size']='accessibility-extra-extra-extra-large'
                if result.get('simulator_operation_unconfirmed'):
                    report['simulator_operation_unconfirmed']=True
                    # Reuse the existing no-command fence, including final
                    # shutdown/readback. This does not assert host-group liveness.
                    report['cleanup_unconfirmed']=True
                if result.get('cleanup_unconfirmed'): report['cleanup_unconfirmed']=True
                report['captures'].append(result)
                if result.get('success') is not True:
                    record_failure(report,'vision-checkpoint',result.get('error','Required simulator checkpoint failed'))
                # Keep failure metadata using host files even when all future
                # simulator work (including capture and cleanup) is fenced.
                (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
                print('SIMULATOR_CHECKPOINT',json.dumps(result),flush=True)
            if (re.match(r'(?:/.*|xcodebuild): error: ',line) or ('app icon set' in line and 'unassigned child' in line)) and len(diagnostics)<30: diagnostics.append(line.rstrip()[:2048])
    def output():
        try:
            with p.stdout: read_output()
            reader_complete.set()
        except Exception as error:
            reader_errors.append(type(error).__name__)
    reader=threading.Thread(target=output,daemon=True);reader.start()
    cleanup_error=None;timed_out=False;raw_exit=None
    try:
        code=p.wait(timeout=timeout);raw_exit=code
    except subprocess.TimeoutExpired:
        timed_out=True
        # A stuck test process must not turn our command deadline into an
        # unbounded wait while reaping after SIGKILL. The VM job owns final cleanup.
        report['active_command'].update(phase='deadline exceeded',elapsed_seconds=round(time.monotonic()-started,3),wall_elapsed_seconds=round(time.time()-wall_started,3),observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
        print('NATIVE_COMMAND_DEADLINE_EXCEEDED',json.dumps(report['active_command']),flush=True)
        if not stop_group(p):
            cleanup_error='Owned process-group exit was not confirmed after bounded TERM/KILL waits'
            report['cleanup_unconfirmed']=True
        code=124
    process_group_gone=stop_group(p)
    if not process_group_gone:
        report['cleanup_unconfirmed']=True
        cleanup_error='Owned descendants remain after command leader exit'
        code=124
    reader.join(timeout=5)
    capture_reader_finished=reader_complete.is_set() and not reader.is_alive()
    if not capture_reader_finished:
        report['cleanup_unconfirmed']=True
        cleanup_error='Owned output/capture lifecycle did not finish cleanly'
        code=124
    if report.get('cleanup_unconfirmed'):
        code=124
        if budget is not None: fail_record('Native command or capture cleanup unconfirmed',phase=budget.phase,cleanup_unconfirmed=True)
    # actool can emit asset errors while xcodebuild incorrectly exits zero. Preserve and fail them.
    if code==0 and diagnostics: code=65
    if code==0 and (runner_capture_failed or any(value.get('success') is not True for value in report['captures'][capture_start:])): code=65
    report['stages'].append({'command':command,'exit':code,'raw_exit':raw_exit,'started':True,'timed_out':timed_out,'timeout_seconds':timeout,'compiler_errors':diagnostics,'cleanup_error':cleanup_error,'process_group_gone':process_group_gone,'capture_reader_finished':capture_reader_finished,'reader_errors':reader_errors,'started_at':started_at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-started,3),'wall_elapsed_seconds':round(time.time()-wall_started,3)})
    if watch_cases is not None: report['stages'][-1]['watch_case_lifecycle']=watch_cases.report
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
pending_vision_result=None
pending_vision_hosted=None
pending_vision_normal=None
if kind=='vision':
    report['vision_offline_case']=text_row['case']
    report['vision_offline_expected']=vision_roles(text_row)
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
    assert 'WATCH_EDITOR' not in text and 'com.mango.touchColor.WatchDiagnostics' not in text and 'TOUCHCOLOR_TEST_CASE' not in text, 'Debug Watch lifecycle diagnostics leaked into Release'
    assert 'TOUCHCOLOR_TEST_LARGEST_TRAIT' not in text and 'TOUCHCOLOR_TEST_TRAIT_PROOF' not in text, 'Debug public-trait seam leaked into Release'
    run(common+['-configuration','Debug','-destination','generic/platform='+platform+' Simulator','-derivedDataPath','build/'+kind+'-tests','ARCHS=arm64','build-for-testing'],420)
    if kind=='vision':
        report['capture_configuration']=verify_capture_format('build/vision-tests')
        print('VISION_CAPTURE_CONFIGURATION',json.dumps(report['capture_configuration']),flush=True)
        runner_info=Path('build/vision-tests/Build/Products/Debug-xrsimulator/TouchColorVisionUITests-Runner.app/Info.plist')
        report['ui_runner_identifier']=plistlib.loads(runner_info.read_bytes())['CFBundleIdentifier']
        assert report['ui_runner_identifier'].startswith('com.mango.touchColor.TouchColorVisionUITests'), 'Unexpected UI runner product'
    devices=json.loads(check_output(['xcrun','simctl','list','devices','available','-j'],timeout=30))['devices']
    candidates=[(runtime,d) for runtime,rows in devices.items() if runtime.endswith(runtime_suffix) for d in rows if d.get('isAvailable')]
    if not candidates:raise RuntimeError('No installed available '+runtime_suffix+' device')
    if kind=='vision':
        report['vision_initial_booted_devices']=[{'runtime':r,'udid':d['udid'],'name':d['name']} for r,rows in devices.items() for d in rows if d.get('state')=='Booted']
    if kind=='watch':
        size=text_row['profile']
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
        report['watch_owned_pair']['activation']=activate_owned_pair(
            actual_pairs,paired,watch_id,phone_id,original_pairs['pairs'],
            lambda identifier: run(['xcrun','simctl','pair_activate',identifier],60),
            lambda: json.loads(check_output(['xcrun','simctl','list','pairs','-j'],timeout=30)))
        print('WATCH_OWNED_PAIR_ACTIVE',json.dumps(report['watch_owned_pair']),flush=True)
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
    def seed_photos():
        global photo_seed_failed
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
    if kind!='vision': seed_photos()
    skip=[]
    if photo_seed_failed:
        # Preserve the failed prerequisite, but still execute unrelated real input, storage and UI paths.
        case={'vision':'VisionWorkflowTests/testRealPhotosImport','tv':'TVWorkflowTests/testActualPhotosRemoteSamplingZoomPaletteCodeAndPersistence'}[kind]
        skip=['-skip-testing:'+name+'UITests/'+case]
    resources('before tests')
    require_responsive(report['resources'][-1])
    # Keep build logs quiet, but retain runtime test/checkpoint output for precise failures.
    test_common=[value for value in common if value!='-quiet']
    # Actual XCTest install and launch, not a launchctl dump, establishes app readiness.
    test_arguments=['-configuration','Debug','-destination','platform='+platform+' Simulator,id='+device['udid'],
        '-derivedDataPath','build/'+kind+'-tests','-parallel-testing-enabled','NO','-collect-test-diagnostics','never',
        '-test-timeouts-enabled','YES','-default-test-execution-time-allowance','180' if kind=='vision' else '120',
        '-maximum-test-execution-time-allowance','360' if kind=='vision' else '240' if kind=='watch' else '120',
        '-maximum-concurrent-test-simulator-destinations','1','ARCHS=arm64']
    test_common=['xcodebuild','test-without-building']+test_common[1:]
    if kind=='vision':
        # Preserve a complete hosted result even if an independent spatial UI process stalls.
        hosted_command=test_common+test_arguments+['-resultBundlePath','build/vision-tests.xcresult','-only-testing:TouchColorVisionTests']
        # Outer process allowance includes measured pre-case Xcode cold start;
        # per-case180/360 limits above are unchanged.
        hosted_code=run(hosted_command,600,required=False)
        if hosted_code in (0,65):
            try:
                pending_vision_hosted=prepare_vision_hosted(hosted_command,Path.cwd(),report['sha'],device['udid'],runtime,report['stages'][-1],row_binding=text_row)
                report['vision_hosted_result']=pending_vision_hosted
            except Exception as binding_error:
                report['vision_hosted_binding_error']=str(binding_error)
                if hosted_code==0: raise
        if hosted_code: raise RuntimeError('Stage failed with exit '+str(hosted_code)+': '+' '.join(hosted_command))
        # A completed hosted launch establishes runtime readiness before the one
        # bounded Photos import. bootstatus alone preceded a real addmedia timeout.
        seed_photos()
        if photo_seed_failed:
            skip=['-skip-testing:TouchColorVisionUITests/VisionWorkflowTests/testRealPhotosImport']
        case=os.environ['TOUCHCOLOR_VISION_CASE']
        if case=='photos':
            inventory=json.loads(check_output(['xcrun','simctl','list','devices','available','-j'],timeout=15))['devices']
            booted=[{'runtime':r,'udid':d['udid'],'name':d['name']} for r,rows in inventory.items() for d in rows if d.get('state')=='Booted']
            if len(booted)>64: raise RuntimeError('Unexpected booted-device inventory size')
            report['vision_before_photos_booted_devices']=booted
            print('VISION_PHOTOS_BOOTED_INVENTORY',json.dumps(booted),flush=True)
            if len(booted)!=1 or booted[0]['udid']!=device['udid'] or booted[0]['runtime']!=runtime:
                raise RuntimeError('Photos row requires only its exact selected Vision device booted; no other device was changed')
        method=VISION_CASES[case][0]
        report['ui_scope']={'case':case,'phase':text_phase,'cases':[method],'evidence_bytes':text_row['evidence_bytes'],'fresh_vm':True}
        selected=['-only-testing:TouchColorVisionUITests/VisionWorkflowTests/'+method]
        print('VISION_UI_EXACT_SCOPE',json.dumps(report['ui_scope']),flush=True)
        resources('before isolated '+method)
        require_responsive(report['resources'][-1])
        if text_phase=='normal':
            normal_command=test_common+test_arguments+['-resultBundlePath','build/vision-ui.xcresult']+selected+skip
            normal_code=run(normal_command,600,required=False)
            if normal_code in (0,65):
                contract={'root':str(Path.cwd()),'project':project,'scheme':name,
                          'derived_data':'build/vision-tests','test_bundle':name+'UITests','platform':platform+' Simulator'}
                try:
                    pending_vision_normal=prepare_vision_normal(normal_command,contract,[method],report['sha'],device['udid'],runtime,
                                                                report['stages'][-1],row_binding=text_row)
                    report['vision_normal_result']=pending_vision_normal
                except Exception as binding_error:
                    report['vision_normal_binding_error']=str(binding_error)
                    if normal_code==0: raise
            if normal_code: raise RuntimeError('Stage failed with exit '+str(normal_code)+': '+' '.join(normal_command))
            resources('after isolated '+method)
    elif kind=='watch':
        # Preserve completed hosted evidence independently. The observed49mm cold
        # install/hosted startup consumed much of a shared840s command, so later UI
        # cases never ran. Each phase remains bounded on the same fresh VM; the
        # source-bound Watch job budget and per-case120/240s allowances remain finite.
        report['xctest_summary_scope']='hosted tests only; watch-ui-summary.json contains the separate UI result'
        run(test_common+test_arguments+['-resultBundlePath','build/watch-tests.xcresult','-only-testing:TouchColorWatchTests'],480)
        if text_phase=='normal':
            normal_command=test_common+test_arguments+['-resultBundlePath','build/watch-ui.xcresult','-only-testing:TouchColorWatchUITests',
                '-skip-testing:TouchColorWatchUITests/WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave']
            report['watch_inputs_before_normal']=watch_checkpoint(report,device=device['udid'],runtime=runtime)
            if report.get('cleanup_unconfirmed'): raise RuntimeError('Watch checkpoint cleanup unconfirmed; normal UI not started')
            normal_code=run(normal_command,840,required=False)
            report['normal_watch_ui']={'exit':normal_code,'result':'failed' if normal_code else 'passed','stage_index':len(report['stages'])-1}
            if normal_code:
                report['tests']='failed'
                record_failure(report,'watch-normal-ui','Stage failed with exit '+str(normal_code)+': '+' '.join(normal_command))
                raise RuntimeError('Stage failed with exit '+str(normal_code)+': '+' '.join(normal_command))
    else:
        run(test_common+test_arguments+['-resultBundlePath','build/'+kind+'-tests.xcresult']+skip,660)
    report['tests']='failed' if report.get('failures') else 'passed'
    largest_cases=applicable_cases(kind,text_row['case']) if text_phase=='system-largest' else ()
    if largest_cases:
        # This independent fresh-VM row never executes or reuses the normal UI phase.
        # Only the unchanged existing Chinese/layout methods run at the OS setting.
        def size_ui_runner(command,seconds):
            origin = begin_largest_execution(command,contract,largest_cases,report['sha'],device['udid'],runtime,
                                             row_binding=text_row) if kind=='vision' else None
            code=run(command,seconds,required=False)
            stage=report['stages'][-1]
            if origin is not None: stage['vision_result_origin']=origin
            return code,'',dict(stage,process_group_gone=stage.get('process_group_gone') is True and not report.get('cleanup_unconfirmed'))
        size_runner=TouchSizeRunner(size_ui_runner)
        contract={'root':str(Path.cwd()),'project':project,'scheme':name,
                  'derived_data':'build/'+kind+'-tests','test_bundle':name+'UITests',
                  'platform':platform+' Simulator'}
        command=test_common+test_arguments+['-resultBundlePath','build/'+kind+'-largest-text.xcresult']
        command+=['-only-testing:'+name+'UITests/'+('WatchWorkflowTests' if kind=='watch' else 'VisionWorkflowTests')+'/'+method for method in largest_cases]
        report['text_size_phase']='largest'
        if kind=='watch': report['largest_text_outcome']={'result':'running'}
        try:
            deferred={'defer_vision_summary':True,'source_sha':report['sha'],'row_binding':text_row} if kind=='vision' else {}
            setting=run_largest(device['udid'],out/'largest-text.json',command,contract,largest_cases,size_runner,timeout=600,**deferred)
            setting['native_text_row']=dict(text_row)
            report['largest_system_text']=setting
            print('NATIVE_SYSTEM_TEXT_SIZE',json.dumps({key:value for key,value in setting.items() if key!='operations'}),flush=True)
            if setting.get('cleanup_unconfirmed') or size_runner.cleanup_unconfirmed:
                report['cleanup_unconfirmed']=True
            if kind=='vision' and vision_summary_pending(setting):
                pending_vision_result=setting
            elif not qualified(setting):
                if kind=='vision' and setting.get('ui_executed') is True and not report.get('cleanup_unconfirmed'):
                    try:
                        prepare_failed_largest(setting,command,contract,largest_cases,report['sha'],device['udid'],runtime,
                                               report['stages'][-1],row_binding=text_row)
                    except Exception as binding_error:
                        setting['diagnostic_binding_error']=str(binding_error)[:1000]
                if kind=='watch' and permits_public_trait_fallback(setting,device['udid'],size_runner):
                    fallback=test_common+test_arguments+['-resultBundlePath','build/watch-public-trait.xcresult',
                        '-only-testing:TouchColorWatchUITests/WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave']
                    report['public_trait_layout']=run_public_trait_fallback(setting,device['udid'],fallback,contract,size_runner)
                    print('NATIVE_PUBLIC_TRAIT_LAYOUT',json.dumps(report['public_trait_layout']),flush=True)
                    if report['public_trait_layout'].get('cleanup_unconfirmed'): report['cleanup_unconfirmed']=True
                # A successful forced-layout test does not turn an unsupported
                # actual system-setting route into a qualified propagation gate.
                raise RuntimeError('Required system-largest-text gate: '+setting['status'])
            if kind=='watch': report['largest_text_outcome']={'result':'passed'}
        except Exception as error:
            if kind=='watch': report['largest_text_outcome']={'result':'failed','error':str(error)}
            record_failure(report,'largest-text',error)
            raise
        finally:
            if size_runner.cleanup_unconfirmed: report['cleanup_unconfirmed']=True
            report['text_size_phase']=None

    if photo_seed_failed: raise RuntimeError('Photos seeding timed out or failed; other native tests executed, real Photos import remains unqualified')
    require_no_failures(report)
    report['result']='pending_offline_qualification' if pending_vision_result is not None or pending_vision_hosted is not None or pending_vision_normal is not None else 'passed'
except Exception as error:
    if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
    if not any(value['error']==str(error) for value in report.get('failures',[])):
        record_failure(report,'platform',error)
    print('NATIVE_PLATFORM_FAILURE',str(error),flush=True)
finally:
    vision_diagnostic = report.get('largest_system_text',{})
    if not vision_diagnostic.get('diagnostic_result'): vision_diagnostic=None
    vision_offline_records = tuple(value for value in (pending_vision_hosted,pending_vision_normal,pending_vision_result,vision_diagnostic)
                                   if value is not None)
    if os.environ.get('TOUCHCOLOR_BUDGET_PHASE')=='work': os.environ['TOUCHCOLOR_BUDGET_PHASE']='cleanup'
    if kind=='watch' and device and any(value['udid']==device['udid'] for value in owned_watch_devices) and not report.get('cleanup_unconfirmed'):
        try:
            lookback=log_lookback(EXPECTED_MINUTES['watch'])
            lifecycle=run_captured(['xcrun','simctl','spawn',device['udid'],'log','show','--last',lookback,'--style','compact',
                '--predicate','subsystem == "com.mango.touchColor.WatchDiagnostics"'],text=True,timeout=15)
            report['watch_editor_lifecycle']={'exit':lifecycle.returncode,'lookback':lookback,**summarize_editor_lifecycle(lifecycle.stdout)}
            print('WATCH_EDITOR_LIFECYCLE',json.dumps(report['watch_editor_lifecycle']),flush=True)
        except Exception as error:
            report['watch_editor_lifecycle']={'error':type(error).__name__}
            if isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False): report['cleanup_unconfirmed']=True
    if not report.get('cleanup_unconfirmed'): resources('after platform attempt')
    result_bundle=Path('build')/(kind+'-tests.xcresult')
    if result_bundle.exists() and kind!='vision' and not report.get('cleanup_unconfirmed'):
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
        if vision_offline_records:
            report['vision_offline_shutdown']=report['stages'][-1]
    if vision_offline_records:
        def no_offline_ui(*args): raise RuntimeError('Shutdown proof cannot launch UI tests')
        shutdown_runner=size_runner if pending_vision_result is not None or vision_diagnostic is not None else TouchSizeRunner(no_offline_ui)
        try:
            confirm_vision_shutdown(report,report.get('vision_offline_shutdown'),device=device['udid'],
                runtime=runtime,runner=shutdown_runner,cleanup_unconfirmed=report.get('cleanup_unconfirmed',False))
            for pending_result in vision_offline_records:
                if pending_result is not None: pending_result['offline_shutdown_verified']=report['offline_shutdown_verified']
        except Exception as error:
            report['result']='failed';report.setdefault('error',str(error))
            report['vision_offline_qualification']={'result':'blocked','reason':str(error)}
            if shutdown_runner.cleanup_unconfirmed:
                report['cleanup_unconfirmed']=True
                fail_record('Vision shutdown readback cleanup unconfirmed',phase='cleanup',cleanup_unconfirmed=True)
        # Persist the pending ticket and shutdown proof, never mark a test pass
        # from console output. Evidence180 owns each expected30s summary once.
        if pending_vision_result is not None or vision_diagnostic is not None:
            (out/'largest-text.json').write_text(json.dumps(pending_vision_result or vision_diagnostic,indent=2)+'\n')
    if report.get('budget_incomplete') or Path('build/job-budget-phase-cleanup.json').exists():
        report['result']='failed'
        report['cleanup_budget_status']='At least one mandatory command could not finish within the reserved lifecycle budget'
    if report.get('cleanup_unconfirmed'):
        report['simulator_cleanup']='No further commands; disposable VM teardown remains authoritative'
        report['result']='failed'
    if report.get('failures'):
        report['result']='failed';report['error']=report['failures'][0]['error']
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
if report['result'] not in ('passed','pending_offline_qualification'):raise SystemExit(1)
