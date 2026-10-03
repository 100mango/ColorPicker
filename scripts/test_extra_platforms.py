#!/usr/bin/env python3
"""One native platform per invocation on the existing standard runner; bounded real builds/tests."""
import datetime,json,os,signal,subprocess,sys,struct,zlib
from pathlib import Path
kind=sys.argv[1]; assert kind in ('vision','watch')
name='TouchColor'+kind.title(); project=name+'.xcodeproj'
platform='visionOS' if kind=='vision' else 'watchOS'
runtime_suffix='xrOS-27-0' if kind=='vision' else 'watchOS-27-0'
out=Path('build')/(kind+'-runtime');out.mkdir(parents=True,exist_ok=True)
report={'platform':kind,'sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'stages':[]}
def run(command,timeout,required=True):
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'RUN', ' '.join(command),flush=True)
    p=subprocess.Popen(command,start_new_session=True)
    try:code=p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        code=124
    report['stages'].append({'command':command,'exit':code})
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
    if required and code:raise RuntimeError('Stage failed with exit '+str(code)+': '+' '.join(command))
    return code
device=None
try:
    common=['xcodebuild','-project',project,'-scheme',name,'CODE_SIGNING_ALLOWED=NO']
    run(common+['-configuration','Release','-destination','generic/platform='+platform,'-derivedDataPath','build/'+kind+'-device','build'],420)
    binary=Path('build')/(kind+'-device')/'Build/Products'/('Release-xros' if kind=='vision' else 'Release-watchos')/'TouchColor.app/TouchColor'
    run(['file',str(binary)],30);run(['otool','-l',str(binary)],30)
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
    if kind=='vision':
        w,h=300,200
        palette=[bytes(v) for v in [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]]
        rows=b''.join(b'\0'+b''.join(palette[(y//100)*3+x//100] for x in range(w)) for y in range(h))
        chunk=lambda n,d:struct.pack('>I',len(d))+n+d+struct.pack('>I',zlib.crc32(n+d)&0xffffffff)
        fixture=out/'asymmetric.png';fixture.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
        run(['xcrun','simctl','addmedia',device['udid'],str(fixture)],120)
    # Actual XCTest install and launch, not a launchctl dump, establishes app readiness.
    run(common+['-configuration','Debug','-destination','platform='+platform+' Simulator,id='+device['udid'],
        '-derivedDataPath','build/'+kind+'-tests','-resultBundlePath','build/'+kind+'-tests.xcresult',
        '-parallel-testing-enabled','NO','-collect-test-diagnostics','never','-test-timeouts-enabled','YES',
        '-maximum-test-execution-time-allowance','120','ARCHS=arm64','test-without-building'],660)
    report['result']='passed'
except Exception as error:
    report['result']='failed';report['error']=str(error);print('NATIVE_PLATFORM_FAILURE',str(error),flush=True)
finally:
    if device:run(['xcrun','simctl','shutdown',device['udid']],60,required=False)
    (out/'runtime.json').write_text(json.dumps(report,indent=2)+'\n')
if report['result']!='passed':raise SystemExit(1)
