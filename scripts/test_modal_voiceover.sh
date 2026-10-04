#!/bin/bash
set -euo pipefail
phase="${1:?Provide audits or voiceover}"
case "$phase" in audits|voiceover) ;; *) exit 2;; esac
xcrun simctl list devices available -j > /tmp/touchcolor-modal-devices.json
device=$(python3 - <<'PY'
import json
devices=json.load(open('/tmp/touchcolor-modal-devices.json'))['devices']
runtime=next(key for key in devices if key.endswith('.iOS-27-0'))
matches=[d for d in devices[runtime] if d.get('isAvailable') and d['name']=='iPad mini (A17 Pro)' and d['state']=='Booted']
assert len(matches)==1,matches
print(matches[0]['udid'])
PY
)
if [[ "$phase" == audits ]]; then
  result=AccessibilityAudits
  selections=(-only-testing:TouchColorUITests/TouchColorAccessibilityUITests/testAccessibilityPaletteImportReview -only-testing:TouchColorUITests/TouchColorAccessibilityUITests/testAccessibilityWatchInboxStatus)
else
  result=ModalVoiceOver
  selections=(-only-testing:TouchColorUITests/TCModalVoiceOverUITests)
fi
xcodebuild -project TouchColor.xcodeproj -scheme TouchColor -configuration Debug \
  -destination "platform=iOS Simulator,id=$device" -derivedDataPath build/simulator \
  -resultBundlePath "build/iPadMini-$result.xcresult" -parallel-testing-enabled NO \
  -collect-test-diagnostics never -test-timeouts-enabled YES \
  -default-test-execution-time-allowance 180 -maximum-test-execution-time-allowance 240 \
  "${selections[@]}" test-without-building
