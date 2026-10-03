#!/bin/bash
set -euo pipefail
# Ephemeral local ad-hoc identity only. No Apple account, provisioning update,
# certificate import, keychain setup, Store capability or distribution is requested.
xcodebuild -project TouchColorMac.xcodeproj -scheme TouchColorMacSandbox -configuration Debug \
  -destination 'platform=macOS,arch=arm64' -derivedDataPath build/mac-sandbox \
  -parallel-testing-enabled NO \
  -collect-test-diagnostics never -maximum-test-execution-time-allowance 150 \
  -only-testing:TouchColorMacUITests ARCHS=arm64 CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= TOUCHCOLOR_ENABLE_SANDBOX=YES \
  TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements build-for-testing
app=build/mac-sandbox/Build/Products/Debug/TouchColor.app
codesign --verify --deep --strict --verbose=2 "$app"
codesign -d --entitlements :- "$app" > build/mac-sandbox-entitlements.plist
python3 - <<'PY'
import plistlib
from pathlib import Path
p=plistlib.loads(Path('build/mac-sandbox-entitlements.plist').read_bytes())
assert p['com.apple.security.app-sandbox'] is True
assert p['com.apple.security.files.user-selected.read-write'] is True
assert p['com.apple.security.device.camera'] is True
for name in ['com.apple.security.network.client','com.apple.security.network.server','com.apple.security.application-groups','com.apple.developer.icloud-container-identifiers']:
    assert not p.get(name), name
assert not any('temporary-exception' in name for name in p), p
print('Minimal sandbox entitlements verified. No distribution identity or network/cloud/app-group entitlement.')
PY

xcodebuild -project TouchColorMac.xcodeproj -scheme TouchColorMacSandbox -configuration Debug \
  -destination 'platform=macOS,arch=arm64' -derivedDataPath build/mac-sandbox \
  -resultBundlePath build/mac-sandbox.xcresult -parallel-testing-enabled NO \
  -collect-test-diagnostics never -maximum-test-execution-time-allowance 150 \
  -only-testing:TouchColorMacUITests ARCHS=arm64 CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= TOUCHCOLOR_ENABLE_SANDBOX=YES \
  TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements test-without-building
