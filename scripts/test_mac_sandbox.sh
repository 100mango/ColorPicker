#!/bin/bash
set -euo pipefail
# Ephemeral local ad-hoc identity only. No Apple account, provisioning update,
# certificate import, keychain setup, Store capability or distribution is requested.
python3 scripts/prepare_sandbox_probe.py build/mac-sandbox/probe-info.json
xcodebuild -quiet -project TouchColorMac.xcodeproj -scheme TouchColorMacSandbox -configuration Debug \
  -destination 'platform=macOS,arch=arm64' -derivedDataPath build/mac-sandbox \
  -parallel-testing-enabled NO \
  -collect-test-diagnostics never -maximum-test-execution-time-allowance 150 \
  -only-testing:TouchColorMacUITests ARCHS=arm64 CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= TOUCHCOLOR_ENABLE_SANDBOX=YES \
  TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements build-for-testing
app=build/mac-sandbox/Build/Products/Debug/TouchColor.app
# Xcode's test build may add broad test-host exceptions even to a UI-only scheme.
# Replace only our disposable app's ad-hoc signature with the exact intended sandbox
# permissions plus Debug task access; the external XCUI runner keeps its own signature.
python3 - <<'PYSIGN'
import plistlib
from pathlib import Path
p=plistlib.loads(Path('TouchColorMac/TouchColorMac.entitlements').read_bytes())
p['com.apple.security.get-task-allow']=True
Path('build/mac-sandbox-minimal.entitlements').write_bytes(plistlib.dumps(p))
PYSIGN
codesign --force --sign - --entitlements build/mac-sandbox-minimal.entitlements "$app"
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
assert set(p)=={'com.apple.security.app-sandbox','com.apple.security.files.user-selected.read-write','com.apple.security.device.camera','com.apple.security.get-task-allow'}, p
assert not any('temporary-exception' in name for name in p), p
print('Minimal sandbox entitlements verified. No distribution identity or network/cloud/app-group entitlement.')
PY

set +e
xcodebuild -project TouchColorMac.xcodeproj -scheme TouchColorMacSandbox -configuration Debug \
  -destination 'platform=macOS,arch=arm64' -derivedDataPath build/mac-sandbox \
  -resultBundlePath build/mac-sandbox.xcresult -parallel-testing-enabled NO \
  -collect-test-diagnostics never -maximum-test-execution-time-allowance 150 \
  -only-testing:TouchColorMacUITests ARCHS=arm64 CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= TOUCHCOLOR_ENABLE_SANDBOX=YES \
  TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements test-without-building
runtime_test_status=$?
set -e

# Runtime XCTest must not silently replace the app's verified signature or permissions.
codesign --verify --deep --strict --verbose=2 "$app"
codesign -d --entitlements :- "$app" > build/mac-sandbox-post-entitlements.plist
python3 - <<'PYVERIFY'
import plistlib
from pathlib import Path
before=plistlib.loads(Path('build/mac-sandbox-entitlements.plist').read_bytes())
after=plistlib.loads(Path('build/mac-sandbox-post-entitlements.plist').read_bytes())
assert before==after, (before,after)
print('Post-runtime signature and exact sandbox entitlement set remain unchanged')
PYVERIFY
python3 - <<'PYBOUNDARY'
import json,os
from pathlib import Path
record=json.loads(Path('build/mac-sandbox/probe-info.json').read_text())
file=Path(record['file'])
assert record['uid']==os.geteuid() and file.stat().st_uid==os.geteuid()
assert file.read_bytes()==b'TouchColor synthetic host write control'
assert (file.stat().st_mode&0o777)==0o600 and (file.parent.stat().st_mode&0o777)==0o700
print('Post-runtime same-user host control confirms unselected file was not changed')
file.unlink();file.parent.rmdir()
PYBOUNDARY

exit "$runtime_test_status"
