#!/bin/bash
set -euo pipefail
family="${1:?Provide iPhone or iPad}"
suite="${2:?Provide TouchColorTests or TouchColorUITests}"
case "$family" in iPhone|iPad) ;; *) exit 2;; esac
case "$suite" in TouchColorTests|TouchColorUITests) ;; *) exit 2;; esac
xcrun simctl list devices available -j > /tmp/touchcolor-devices.json
device=$(python3 - "$family" <<'PY'
import json,sys
all_devices=json.load(open('/tmp/touchcolor-devices.json'))['devices']
runtimes=[key for key in all_devices if key.endswith('.iOS-27-0')]
if not runtimes: raise SystemExit('BLOCKED: stable iOS 27.0 simulator runtime is unavailable')
family=sys.argv[1]
candidates=[d for d in all_devices[runtimes[0]] if d.get('isAvailable') and family in d['name']]
if not candidates: raise SystemExit('BLOCKED: missing '+family+' simulator')
preferred='17e' if family=='iPhone' else 'mini'
selected=next((d for d in candidates if preferred in d['name']),candidates[0])
print(selected['udid'])
print('Selected '+selected['name']+' '+selected['udid'],file=sys.stderr)
PY
)
# Teardown also runs after failed tests, so the next family never competes with an active simulator.
trap 'xcrun simctl shutdown "$device" || true' EXIT
xcrun simctl boot "$device" || true
xcrun simctl bootstatus "$device" -b
if [[ "$suite" == TouchColorUITests ]]; then
  python3 - <<'PYPNG'
import struct,zlib
w=h=200
chunk=lambda name,data: struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*w)*h))+chunk(b'IEND',b'')
open('/tmp/touchcolor-red.png','wb').write(png)
PYPNG
  xcrun simctl addmedia "$device" /tmp/touchcolor-red.png
fi
xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
  -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
  -resultBundlePath "build/$family-$suite.xcresult" -parallel-testing-enabled NO \
  -test-timeouts-enabled YES -default-test-execution-time-allowance 180 \
  -maximum-test-execution-time-allowance 240 -only-testing:"$suite" \
  test-without-building
