#!/bin/bash
set -euo pipefail
family="${1:?Provide iPhoneCompact, iPhoneLarge or iPadLarge}"
suite="${2:?Provide prepare, shutdown, TouchColorTests or TouchColorUITests}"
case "$family" in iPhoneCompact|iPhoneLarge|iPadLarge) ;; *) exit 2;; esac
case "$suite" in prepare|shutdown|TouchColorTests|TouchColorUITests) ;; *) exit 2;; esac
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
  xcrun simctl boot "$device" || true
  xcrun simctl bootstatus "$device" -b
  xcrun simctl spawn "$device" launchctl print system >/dev/null
  xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -showdestinations
  exit 0
fi
if [[ "$suite" == shutdown ]]; then
  xcrun simctl shutdown "$device" || true
  exit 0
fi
if [[ "$suite" == TouchColorUITests ]]; then
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
fi
selection="$suite"
if [[ "$suite" == TouchColorUITests ]]; then
  if [[ "$family" == iPadLarge ]]; then selection="TouchColorUITests/TouchColorIPadUITests"; else selection="TouchColorUITests/TouchColorUITests"; fi
fi
xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
  -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
  -resultBundlePath "build/$family-$suite.xcresult" -parallel-testing-enabled NO \
  -collect-test-diagnostics never -test-timeouts-enabled YES -default-test-execution-time-allowance 180 \
  -maximum-test-execution-time-allowance 240 -only-testing:"$selection" \
  test-without-building
