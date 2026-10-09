#!/usr/bin/env python3
"""Check real unsigned Mac Release settings, sandbox and built-app version."""
import json
from pathlib import Path
import plistlib
import sys

EXPECTED_VERSION = '2.0.1'
EXPECTED_BUILD = '20002'
EXPECTED_SANDBOX = {'com.apple.security.app-sandbox': True,
                    'com.apple.security.files.user-selected.read-write': True,
                    'com.apple.security.device.camera': True}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plist(path, maximum_bytes):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or linked metadata: ' + str(path))
    require(0 < path.stat().st_size <= maximum_bytes, 'Invalid metadata size: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(maximum_bytes + 1)
    require(len(data) <= maximum_bytes, 'Metadata grew beyond limit')
    value = plistlib.loads(data)
    require(isinstance(value, dict), 'Metadata is not a dictionary')
    return value


def verify(settings_path):
    records = json.loads(Path(settings_path).read_text())
    require(isinstance(records, list) and all(isinstance(row, dict) for row in records), 'Invalid settings records')
    apps = [row.get('buildSettings') for row in records if row.get('target') == 'TouchColorMac']
    require(len(apps) == 1 and isinstance(apps[0], dict), 'Expected one native Mac app target')
    settings = apps[0]
    expected = {'CONFIGURATION': 'Release', 'PRODUCT_BUNDLE_IDENTIFIER': 'com.mango.touchColor',
                'PRODUCT_NAME': 'TouchColor', 'MACOSX_DEPLOYMENT_TARGET': '13.0',
                'TOUCHCOLOR_ENABLE_SANDBOX': 'YES', 'ENABLE_APP_SANDBOX': 'YES',
                'CODE_SIGNING_ALLOWED': 'NO', 'MARKETING_VERSION': EXPECTED_VERSION,
                'CURRENT_PROJECT_VERSION': EXPECTED_BUILD, 'FULL_PRODUCT_NAME': 'TouchColor.app'}
    for key, value in expected.items():
        require(settings.get(key) == value, 'Release setting mismatch: ' + key)
    for key in ('SRCROOT', 'TARGET_BUILD_DIR'):
        require(isinstance(settings.get(key), str) and Path(settings[key]).is_absolute(), 'Missing absolute path: ' + key)
    root = Path(settings['SRCROOT']).resolve()
    raw_entitlements = settings.get('CODE_SIGN_ENTITLEMENTS')
    require(isinstance(raw_entitlements, str) and bool(raw_entitlements), 'Missing entitlement source')
    entitlement_source = root / 'TouchColorMac/TouchColorMac.entitlements'
    require((root / raw_entitlements).resolve() == entitlement_source.resolve(), 'Unexpected entitlement source')
    entitlements = plist(entitlement_source, 64 * 1024)
    require(entitlements == EXPECTED_SANDBOX and all(type(value) is bool for value in entitlements.values()),
            'Shipping sandbox entitlement contract changed')
    app = Path(settings['TARGET_BUILD_DIR']).resolve() / settings['FULL_PRODUCT_NAME']
    require(app.is_dir() and not app.is_symlink(), 'Missing or linked built app')
    contents = app / 'Contents'
    require(contents.is_dir() and not contents.is_symlink(), 'Missing or linked app Contents')
    info = plist(contents / 'Info.plist', 1024 * 1024)
    for key, value in {'CFBundleIdentifier': 'com.mango.touchColor', 'CFBundlePackageType': 'APPL',
                       'CFBundleExecutable': 'TouchColor', 'CFBundleShortVersionString': EXPECTED_VERSION,
                       'CFBundleVersion': EXPECTED_BUILD}.items():
        require(info.get(key) == value, 'Built app metadata mismatch: ' + key)
    return {'version': EXPECTED_VERSION, 'build': EXPECTED_BUILD, 'app': str(app),
            'unsigned_release_settings': True, 'sandbox_source_verified': True,
            'scope': 'Real build-settings and built Info.plist only; no signature or archive qualification'}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: verify_mac_release_settings.py BUILD_SETTINGS_JSON')
    print(json.dumps(verify(sys.argv[1]), indent=2))
