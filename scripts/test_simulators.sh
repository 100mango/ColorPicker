#!/bin/bash
set -euo pipefail
xcrun simctl list devices available -j > /tmp/touchcolor-devices.json
python3 - <<'PY' > /tmp/touchcolor-selected.txt
import json
all_devices=json.load(open('/tmp/touchcolor-devices.json'))['devices']
runtimes=[key for key in all_devices if key.endswith('.iOS-27-0')]
if not runtimes: raise SystemExit('BLOCKED: stable iOS 27.0 simulator runtime is unavailable')
devices=all_devices[runtimes[0]]
for family in ('iPhone','iPad'):
    candidates=[d for d in devices if d.get('isAvailable') and family in d['name']]
    if not candidates: raise SystemExit('BLOCKED: missing '+family+' simulator')
    # Prefer the smallest phone to catch constrained layouts.
    selected=next((d for d in candidates if 'SE' in d['name']),candidates[0])
    print(selected['udid'])
    print('Selected '+selected['name']+' '+selected['udid'],file=__import__('sys').stderr)
PY
while IFS= read -r device; do
  xcrun simctl boot "$device" || true
  xcrun simctl bootstatus "$device" -b
  python3 - <<'PYPNG'
import struct,zlib
w=h=200
chunk=lambda name,data: struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*w)*h))+chunk(b'IEND',b'')
open('/tmp/touchcolor-red.png','wb').write(png)
PYPNG
  xcrun simctl addmedia "$device" /tmp/touchcolor-red.png
  xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
    -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
    -resultBundlePath "build/Tests-$device.xcresult" -parallel-testing-enabled NO \
    CODE_SIGNING_ALLOWED=NO test
  xcrun simctl shutdown "$device"
done < /tmp/touchcolor-selected.txt
