#!/usr/bin/env python3
"""One native platform per invocation on the existing standard runner; bounded real builds/tests."""
import datetime,json,os,signal,subprocess,sys,struct,zlib,threading,re,plistlib,time
from pathlib import Path
from capture_simulator_checkpoint import capture as capture_checkpoint
kind=sys.argv[1]; assert kind in ('vision','watch','tv')
name={'vision':'TouchColorVision','watch':'TouchColorWatch','tv':'TouchColorTV'}[kind]; project=name+'.xcodeproj'
platform={'vision':'visionOS','watch':'watchOS','tv':'tvOS'}[kind]
runtime_suffix={'vision':'xrOS-27-0','watch':'watchOS-27-0','tv':'tvOS-27-0'}[kind]
out=Path('build')/(kind+'-runtime');out.mkdir(parents=True,exist_ok=True)
report={'captures':[],'platform':kind,'sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'stages':[]}
def run(command,timeout,required=True):
    started=time.monotonic();started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'RUN', ' '.join(command),flush=True)
    diagnostics=[]
    p=subprocess.Popen(command,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def output():
        for line in p.stdout:
            print(line,end='',flush=True)
            checkpoint=re.search(r'TOUCHCOLOR_CAPTURE_REQUEST ([0-9A-F-]{36})',line)
            if checkpoint and kind=='vision' and device and len(report['captures'])<16:
                try:
                    result=capture_checkpoint(device['udid'],report['ui_runner_identifier'],checkpoint.group(1),out/'screenshots')
                    report['captures'].append(result);print('SIMULATOR_CHECKPOINT',json.dumps(result),flush=True)
                except Exception as error:
                    failure={'success':False,'error':str(error)}
                    report['captures'].append(failure);print('SIMULATOR_CHECKPOINT_FAILURE',json.dumps(failure),flush=True)
            if (re.match(r'(?:/.*|xcodebuild): error: ',line) or ('app icon set' in line and 'unassigned child' in line)) and len(diagnostics)<30: diagnostics.append(line.rstrip()[:2048])
    reader=threading.Thread(target=output,daemon=True);reader.start()
    cleanup_error=None
    try:code=p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # A stuck test process must not turn our command deadline into an
        # unbounded wait while reaping after SIGKILL. The VM job owns final cleanup.
        for stop_signal in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(p.pid,stop_signal)
            except ProcessLookupError:break
            try:p.wait(timeout=10);break
            except subprocess.TimeoutExpired:continue
        if p.poll() is None:cleanup_error='Process exit was not confirmed after bounded TERM/KILL waits'
        code=124
    reader.join(timeout=5)
    # actool can emit asset errors while xcodebuild incorrectly exits zero. Preserve and fail them.
    if code==0 and diagnostics: code=65
    report['stages'].append({'command':command,'exit':code,'compiler_errors':diagnostics,'cleanup_error':cleanup_error,'started_at':started_at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-started,3)})
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    if required and code:raise RuntimeError('Stage failed with exit '+str(code)+': '+' '.join(command))
    return code
def resources(label):
    sample={'label':label,'time':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    for name,command in [('memory',['sysctl','hw.memsize','vm.swapusage']),('vm',['vm_stat'])]:
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            sample[name]={'exit':result.returncode,'text':(result.stdout+result.stderr)[-5000:]}
        except Exception as error:sample[name]={'error':str(error)}
    report.setdefault('resources',[]).append(sample)
    print('NATIVE_RESOURCE_STATE',json.dumps(sample),flush=True)
device=None
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
    plistlib.loads(privacy.read_bytes())
    report['release_resource_files']=[p.name for p in bundle.iterdir() if p.is_file()]
    assert (bundle/'Assets.car').is_file(), 'Release compiled icon assets missing'
    report['release_bundle']={key:info.get(key) for key in ['CFBundleIdentifier','CFBundleName','CFBundleDisplayName','CFBundleExecutable','CFBundleShortVersionString','CFBundleVersion','MinimumOSVersion','CFBundleSupportedPlatforms','CFBundleIcons','CFBundleIconName']}
    report['release_bundle'].update(privacy_manifest=True,compiled_assets=True,unsigned=True)
    print('RELEASE_BUNDLE',json.dumps(report['release_bundle']),flush=True)
    run(['file',str(binary)],30)
    linked_libraries=subprocess.check_output(['otool','-L',str(binary)],text=True,timeout=30).splitlines()[1:]
    report['release_linked_libraries']=[line.strip() for line in linked_libraries]
    assert not any(name in line for line in linked_libraries for name in ('Pods/','GPUImage','Masonry')), 'Retired dependency linked into native Release'
    print('NATIVE_RELEASE_LINKED_LIBRARIES',json.dumps(report['release_linked_libraries']),flush=True)
    load_commands=subprocess.check_output(['otool','-l',str(binary)],text=True,timeout=30).splitlines()
    summary=[]
    for index,line in enumerate(load_commands):
        if 'LC_BUILD_VERSION' in line: summary.extend(load_commands[index:index+8])
    report['binary_platform_minimum']=summary;print('\n'.join(summary),flush=True)
    text=subprocess.check_output(['strings',str(binary)],text=True)
    assert 'TOUCHCOLOR_TEST_DEFAULTS' not in text and '--ui-test-reset' not in text, 'Debug seam leaked into Release'
    run(common+['-configuration','Debug','-destination','generic/platform='+platform+' Simulator','-derivedDataPath','build/'+kind+'-tests','ARCHS=arm64','build-for-testing'],420)
    if kind=='vision':
        runner_info=Path('build/vision-tests/Build/Products/Debug-xrsimulator/TouchColorVisionUITests-Runner.app/Info.plist')
        report['ui_runner_identifier']=plistlib.loads(runner_info.read_bytes())['CFBundleIdentifier']
        assert report['ui_runner_identifier'].startswith('com.mango.touchColor.TouchColorVisionUITests'), 'Unexpected UI runner product'
    devices=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','available','-j'],timeout=30))['devices']
    candidates=[(runtime,d) for runtime,rows in devices.items() if runtime.endswith(runtime_suffix) for d in rows if d.get('isAvailable')]
    if not candidates:raise RuntimeError('No installed available '+runtime_suffix+' device')
    runtime,device=next((v for v in candidates if '46mm' in v[1]['name']),candidates[0])
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
    if kind in ('vision','tv'):
        w,h=300,200
        palette=[bytes(v) for v in [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]]
        rows=b''.join(b'\0'+b''.join(palette[(y//100)*3+x//100] for x in range(w)) for y in range(h))
        chunk=lambda n,d:struct.pack('>I',len(d))+n+d+struct.pack('>I',zlib.crc32(n+d)&0xffffffff)
        fixture=out/'asymmetric.png';fixture.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
        photo_seed_failed = run(['xcrun','simctl','addmedia',device['udid'],str(fixture)],120,required=False) != 0
        report['photos_seed']='failed' if photo_seed_failed else 'passed'
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
        '-maximum-test-execution-time-allowance','360' if kind=='vision' else '120','ARCHS=arm64','test-without-building']
    if kind=='vision':
        # Preserve a complete hosted result even if an independent spatial UI process stalls.
        run(test_common+test_arguments+['-resultBundlePath','build/vision-tests.xcresult','-only-testing:TouchColorVisionTests'],360)
        report['ui_scope']='Full native UI suite: Files/Photos cancellation, Photos import, paste/sample/save/relaunch, PNG export/reopen, Chinese UI and strict accessibility audits'
        run(test_common+test_arguments+['-resultBundlePath','build/vision-ui.xcresult','-only-testing:TouchColorVisionUITests']+skip,1200)
    else:
        run(test_common+test_arguments+['-resultBundlePath','build/'+kind+'-tests.xcresult']+skip,660)
    report['tests']='passed'
    if photo_seed_failed: raise RuntimeError('Photos seeding timed out or failed; other native tests executed, real Photos import remains unqualified')
    report['result']='passed'
except Exception as error:
    report['result']='failed';report['error']=str(error);print('NATIVE_PLATFORM_FAILURE',str(error),flush=True)
finally:
    resources('after platform attempt')
    result_bundle=Path('build')/(kind+'-tests.xcresult')
    if result_bundle.exists():
        try:
            summary_run=subprocess.run(['xcrun','xcresulttool','get','test-results','summary','--path',str(result_bundle)],capture_output=True,text=True,timeout=30)
            if summary_run.returncode==0:
                summary=json.loads(summary_run.stdout)
                report['xctest_summary']={key:summary.get(key) for key in ['result','passedTests','failedTests','skippedTests','totalTestCount']}
                report['xctest_summary']['failures']=[{'test':f.get('testIdentifierString'),'message':f.get('failureText','')[:1600]} for f in summary.get('testFailures',[])[:12]]
                print('NATIVE_XCTEST_SUMMARY',json.dumps(report['xctest_summary']),flush=True)
            else: report['summary_error']=(summary_run.stdout+summary_run.stderr)[-2000:]
        except Exception as error:report['summary_error']=str(error)
    if device:run(['xcrun','simctl','shutdown',device['udid']],60,required=False)
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
if report['result']!='passed':raise SystemExit(1)
