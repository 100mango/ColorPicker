#!/usr/bin/env python3
"""One native platform per invocation on the existing standard runner; bounded real builds/tests."""
import datetime,json,os,signal,subprocess,sys,struct,zlib,threading,re,plistlib
from pathlib import Path
kind=sys.argv[1]; assert kind in ('vision','watch','tv')
name={'vision':'TouchColorVision','watch':'TouchColorWatch','tv':'TouchColorTV'}[kind]; project=name+'.xcodeproj'
platform={'vision':'visionOS','watch':'watchOS','tv':'tvOS'}[kind]
runtime_suffix={'vision':'xrOS-27-0','watch':'watchOS-27-0','tv':'tvOS-27-0'}[kind]
out=Path('build')/(kind+'-runtime');out.mkdir(parents=True,exist_ok=True)
report={'platform':kind,'sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'stages':[]}
def run(command,timeout,required=True):
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'RUN', ' '.join(command),flush=True)
    diagnostics=[]
    p=subprocess.Popen(command,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def output():
        for line in p.stdout:
            print(line,end='',flush=True)
            if re.match(r'(?:/.*|xcodebuild): error: ',line) and len(diagnostics)<30: diagnostics.append(line.rstrip()[:2048])
    reader=threading.Thread(target=output,daemon=True);reader.start()
    try:code=p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        code=124
    reader.join(timeout=5)
    # actool can emit asset errors while xcodebuild incorrectly exits zero. Preserve and fail them.
    if code==0 and diagnostics: code=65
    report['stages'].append({'command':command,'exit':code,'compiler_errors':diagnostics})
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    if required and code:raise RuntimeError('Stage failed with exit '+str(code)+': '+' '.join(command))
    return code
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
    assert (bundle/'Assets.car').is_file(), 'Release compiled icon assets missing'
    report['release_bundle']={key:info.get(key) for key in ['CFBundleIdentifier','CFBundleName','CFBundleDisplayName','CFBundleExecutable','CFBundleShortVersionString','CFBundleVersion','MinimumOSVersion','CFBundleSupportedPlatforms','CFBundleIcons','CFBundleIconName']}
    report['release_bundle'].update(privacy_manifest=True,compiled_assets=True,unsigned=True)
    print('RELEASE_BUNDLE',json.dumps(report['release_bundle']),flush=True)
    run(['file',str(binary)],30)
    load_commands=subprocess.check_output(['otool','-l',str(binary)],text=True,timeout=30).splitlines()
    summary=[]
    for index,line in enumerate(load_commands):
        if 'LC_BUILD_VERSION' in line: summary.extend(load_commands[index:index+8])
    report['binary_platform_minimum']=summary;print('\n'.join(summary),flush=True)
    text=subprocess.check_output(['strings',str(binary)],text=True)
    assert 'TOUCHCOLOR_TEST_DEFAULTS' not in text and '--ui-test-reset' not in text, 'Debug seam leaked into Release'
    run(common+['-configuration','Debug','-destination','generic/platform='+platform+' Simulator','-derivedDataPath','build/'+kind+'-tests','ARCHS=arm64','build-for-testing'],420)
    devices=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','available','-j'],timeout=30))['devices']
    candidates=[(runtime,d) for runtime,rows in devices.items() if runtime.endswith(runtime_suffix) for d in rows if d.get('isAvailable')]
    if not candidates:raise RuntimeError('No installed available '+runtime_suffix+' device')
    runtime,device=next((v for v in candidates if '46mm' in v[1]['name']),candidates[0])
    report.update(runtime=runtime,device=device)
    run(['xcrun','simctl','boot',device['udid']],180,required=False)
    run(['xcrun','simctl','bootstatus',device['udid'],'-b'],420)
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
    # Actual XCTest install and launch, not a launchctl dump, establishes app readiness.
    run(common+['-configuration','Debug','-destination','platform='+platform+' Simulator,id='+device['udid'],
        '-derivedDataPath','build/'+kind+'-tests','-resultBundlePath','build/'+kind+'-tests.xcresult',
        '-parallel-testing-enabled','NO','-collect-test-diagnostics','never','-test-timeouts-enabled','YES',
        '-maximum-test-execution-time-allowance','120','ARCHS=arm64','test-without-building']+skip,660)
    report['tests']='passed'
    if photo_seed_failed: raise RuntimeError('Photos seeding timed out or failed; other native tests executed, real Photos import remains unqualified')
    report['result']='passed'
except Exception as error:
    report['result']='failed';report['error']=str(error);print('NATIVE_PLATFORM_FAILURE',str(error),flush=True)
finally:
    if device:run(['xcrun','simctl','shutdown',device['udid']],60,required=False)
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
if report['result']!='passed':raise SystemExit(1)
