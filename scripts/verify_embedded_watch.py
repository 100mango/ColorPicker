#!/usr/bin/env python3
"""Inspect real built phone/embedded Watch products; no signing or account changes."""
import hashlib
import json
from pathlib import Path
import plistlib
import sys
from bounded_process import check_output


def require(condition, message):
    if not condition: raise ValueError(message)


def verify(phone, mode='device', release=True, *, build_for_testing=False):
    phone=Path(phone); watch=phone/'Watch/TouchColor.app'
    require(mode in ('device','simulator'), 'Invalid packaging mode')
    require(not build_for_testing or (mode=='simulator' and not release), 'Build-for-testing mode requires a Debug simulator product')
    require(watch.is_dir(), 'Actual embedded Watch app missing from phone Watch directory')
    require(sorted(p.name for p in (phone/'Watch').iterdir()) == ['TouchColor.app'], 'Unexpected Watch content')
    values={}
    for role,app,identifier,minimum,platform in [
        ('phone',phone,'com.mango.touchColor','15.0','iPhoneOS' if mode=='device' else 'iPhoneSimulator'),
        ('watch',watch,'com.mango.touchColor.watchkitapp','9.0','WatchOS' if mode=='device' else 'WatchSimulator')]:
        info=plistlib.loads((app/'Info.plist').read_bytes())
        require(info.get('CFBundleIdentifier')==identifier,role+' identifier mismatch')
        require(info.get('CFBundleExecutable')=='TouchColor',role+' executable mismatch')
        require(info.get('CFBundleShortVersionString')=='2.0' and info.get('CFBundleVersion')=='20001',role+' version mismatch')
        require(info.get('MinimumOSVersion')==minimum,role+' deployment floor mismatch')
        require(info.get('CFBundleSupportedPlatforms')==[platform],role+' actual SDK product mismatch')
        require((app/'Assets.car').is_file(),role+' compiled icon assets missing')
        require((app/'PrivacyInfo.xcprivacy').is_file(),role+' privacy manifest missing')
        if role=='watch':
            require(info.get('WKApplication') is True,'Native single-target Watch application flag missing')
            require(info.get('WKCompanionAppBundleIdentifier')=='com.mango.touchColor','Watch companion identifier mismatch')
            require(info.get('WKRunsIndependentlyOfCompanionApp') is True,'Watch independent local workflow missing')
        executable=app/'TouchColor'
        require(executable.is_file(),role+' real executable missing')
        if release:
            content=check_output(['strings',str(executable)],timeout=30)
            require(not any(token in content for token in ('--ui-test-reset','TOUCHCOLOR_TEST_DEFAULTS','TOUCHCOLOR_PAIRED_E2E','TOUCHCOLOR_PAIRED_BARRIER','WATCH_EDITOR')),role+' Debug fixture leaked into Release')
        values[role]={key:info.get(key) for key in ('CFBundleIdentifier','CFBundleShortVersionString','CFBundleVersion','MinimumOSVersion','CFBundleSupportedPlatforms','WKCompanionAppBundleIdentifier')}
        with executable.open('rb') as stream:
            values[role]['executable_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
    require(not list(phone.rglob('PaletteFixtures.app')), 'Files fixture embedded in app product')
    test_bundles=sorted(phone.rglob('*.xctest'))
    if build_for_testing:
        # Xcode embeds this registered hosted unit target in the Debug test host.
        # The external paired UI tests still run separately. Release permits none.
        expected=phone/'PlugIns/TouchColorTests.xctest'
        require(test_bundles==[expected] and expected.is_dir() and not expected.is_symlink(),
                'Debug test host must contain exactly its registered test bundle: '+str([str(path.relative_to(phone)) for path in test_bundles]))
        for path in test_bundles:
            info=plistlib.loads((path/'Info.plist').read_bytes())
            require(info.get('CFBundleIdentifier')=='com.mango.touchColor.TouchColorTests' and
                    info.get('CFBundleExecutable')=='TouchColorTests' and info.get('CFBundlePackageType')=='BNDL',
                    'Debug hosted test bundle identity mismatch')
            require((path/'TouchColorTests').is_file() and not (path/'TouchColorTests').is_symlink(),
                    'Debug hosted test bundle executable missing')
        values['debug_test_host_bundles']=[str(path.relative_to(phone)) for path in test_bundles]
    else:
        require(not test_bundles, 'Test product embedded in shipping app')
    return values

if __name__=='__main__':
    print(json.dumps(verify(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'device','--debug' not in sys.argv,
                            build_for_testing='--build-for-testing' in sys.argv),indent=2))
