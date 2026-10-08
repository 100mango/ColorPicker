#!/usr/bin/env python3
"""Assert actual Xcode Release settings use the existing shipping sandbox contract."""
import json
from pathlib import Path
import plistlib
import sys

records=json.loads(Path(sys.argv[1]).read_text())
apps=[item['buildSettings'] for item in records if item.get('target')=='TouchColorMac']
assert len(apps)==1, 'Expected one native Mac app target'
settings=apps[0]
for key,expected in {'CONFIGURATION':'Release','PRODUCT_BUNDLE_IDENTIFIER':'com.mango.touchColor',
                     'PRODUCT_NAME':'TouchColor','MACOSX_DEPLOYMENT_TARGET':'13.0',
                     'TOUCHCOLOR_ENABLE_SANDBOX':'YES','ENABLE_APP_SANDBOX':'YES',
                     'CODE_SIGNING_ALLOWED':'NO'}.items():
    assert settings.get(key)==expected, (key,settings.get(key),expected)
root=Path(settings['SRCROOT'])
entitlements=(root/settings['CODE_SIGN_ENTITLEMENTS']).resolve()
assert entitlements==(root/'TouchColorMac/TouchColorMac.entitlements').resolve()
expected={'com.apple.security.app-sandbox':True,'com.apple.security.files.user-selected.read-write':True,'com.apple.security.device.camera':True}
assert plistlib.loads(entitlements.read_bytes())==expected
print('Actual unsigned Release settings use the three-key sandbox entitlement source by default; no distribution identity was used')
