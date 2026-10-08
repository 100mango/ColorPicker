#!/bin/bash
set -euo pipefail
family="${1:?Provide iPhoneCompact, iPhoneLarge, iPadLarge or iPadMini}"
suite="${2:?Provide prepare, seed, shutdown, TouchColorTests, TouchColorUITests or AccessibilityAudits}"
case "$family" in iPhoneCompact|iPhoneLarge|iPadLarge|iPadMini) ;; *) exit 2;; esac
case "$suite" in prepare|seed|shutdown|TouchColorTests|TouchColorUITests|AccessibilityAudits) ;; *) exit 2;; esac
xcrun simctl list devices available -j > /tmp/touchcolor-devices.json
device=$(python3 - "$family" "$suite" <<'PY'
import json,sys,subprocess
all_devices=json.load(open('/tmp/touchcolor-devices.json'))['devices']
runtimes=[key for key in all_devices if key.endswith('.iOS-27-0')]
if not runtimes: raise SystemExit('BLOCKED: stable iOS 27.0 simulator runtime is unavailable')
family=sys.argv[1]
if family=='iPhoneCompact':
    types=json.loads(subprocess.check_output(['xcrun','simctl','list','devicetypes','-j']))['devicetypes']
    device_type=next((t for t in types if t['name']=='iPhone SE (3rd generation)'),None)
    if not device_type: raise SystemExit('BLOCKED: required iPhone SE (3rd generation) device type is unavailable')
    name='TouchColor Compact SE3'
    candidates=[d for d in all_devices[runtimes[0]] if d.get('isAvailable') and d['name']==name]
    if not candidates and sys.argv[2]=='prepare':
        udid=subprocess.check_output(['xcrun','simctl','create',name,device_type['identifier'],runtimes[0]],text=True).strip()
        candidates=[{'udid':udid,'name':name}]
        print('Created '+str(device_type)+' runtime '+runtimes[0],file=sys.stderr)
elif family=='iPadMini':
    name='iPad mini (A17 Pro)'
    candidates=[d for d in all_devices[runtimes[0]] if d.get('isAvailable') and d['name']==name]
elif family=='iPadLarge':
    candidates=[d for d in all_devices[runtimes[0]] if d.get('isAvailable') and d['name'].startswith('iPad Pro 13-inch')]
    if not candidates: raise SystemExit('BLOCKED: required native 13-inch iPad simulator is unavailable')
    name=candidates[0]['name']
else:
    name='iPhone 18 Pro Max'
    candidates=[d for d in all_devices[runtimes[0]] if d.get('isAvailable') and d['name']==name]
if not candidates: raise SystemExit('BLOCKED: missing required '+name+' simulator')
selected=candidates[0]
print(selected['udid'])
print('Selected '+selected['name']+' '+selected['udid'],file=sys.stderr)
PY
)
# Cold CoreSimulator startup has a separate budget; unit and UI suites share the warm device.
if [[ "$suite" == prepare ]]; then
  echo "[$(date -u +%FT%TZ)] Booting $family $device"
  xcrun simctl boot "$device" || true
  xcrun simctl bootstatus "$device" -b
  echo "[$(date -u +%FT%TZ)] Boot completed; installing the exact test app"
  xcrun simctl install "$device" build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app
  echo "[$(date -u +%FT%TZ)] Launching the app for readiness"
  xcrun simctl launch --terminate-running-process "$device" com.mango.touchColor
  echo "[$(date -u +%FT%TZ)] App launch returned successfully; stopping the readiness process"
  xcrun simctl terminate "$device" com.mango.touchColor
  echo "[$(date -u +%FT%TZ)] App launch completed; collecting optional bounded inventories"
  python3 - "$device" <<'PYDIAGNOSTICS'
import datetime,subprocess,sys
commands=[(['xcrun','simctl','spawn',sys.argv[1],'launchctl','print','system'],20,subprocess.DEVNULL),
          (['xcodebuild','-project','TouchColor.xcodeproj','-scheme','TouchColor','-showdestinations'],30,None)]
for command,seconds,output in commands:
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), 'Optional diagnostic:', ' '.join(command), flush=True)
    try:
        result=subprocess.run(command,timeout=seconds,stdout=output,check=False)
        print('Optional diagnostic exit:',result.returncode,flush=True)
    except subprocess.TimeoutExpired:
        print(f'Optional diagnostic exceeded {seconds}s; continuing to the actual XCTest gates',flush=True)
PYDIAGNOSTICS
  echo "[$(date -u +%FT%TZ)] Simulator preparation complete"
  exit 0
fi
if [[ "$suite" == shutdown ]]; then
  xcrun simctl shutdown "$device" || true
  exit 0
fi
if [[ "$suite" == seed || "$suite" == TouchColorUITests || "$suite" == AccessibilityAudits ]] && [[ ! -f "build/$family-fixture-seeded" ]]; then
  python3 - <<'PYPNG'
import struct,zlib
w,h=300,200
chunk=lambda name,data: struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
palette=[bytes(c) for c in [(255,0,0),(0,255,0),(0,0,255),(0,255,255),(255,0,255),(255,255,0)]]
rows=b''.join(b'\0'+b''.join(palette[(y//100)*3+x//100] for x in range(w)) for y in range(h))
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
open('/tmp/touchcolor-asymmetric.png','wb').write(png)
PYPNG
  xcrun simctl addmedia "$device" /tmp/touchcolor-asymmetric.png
  touch "build/$family-fixture-seeded"
fi
if [[ "$suite" == seed ]]; then exit 0; fi
selection="$suite"
if [[ "$suite" == TouchColorUITests ]]; then
  if [[ "$family" == iPadLarge || "$family" == iPadMini ]]; then selection="TouchColorUITests/TouchColorIPadUITests"; else selection="TouchColorUITests/TouchColorUITests"; fi
fi
if [[ "$suite" == AccessibilityAudits ]]; then selection="TouchColorUITests/TouchColorAccessibilityUITests"; fi
xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
  -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
  -resultBundlePath "build/$family-$suite.xcresult" -parallel-testing-enabled NO \
  -collect-test-diagnostics never -test-timeouts-enabled YES -default-test-execution-time-allowance 180 \
  -maximum-test-execution-time-allowance 240 -only-testing:"$selection" \
  test-without-building
