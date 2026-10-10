"""Exact two-row Mac command ledger; no execution or optional suites here."""
import json
from pathlib import Path

PROJECT = 'TouchColorMac.xcodeproj'
DIAGNOSTICS = ('testDiagnosticStandardAppKitSheetAudit', 'testDiagnosticStandardAppKitAlertAudit')
PHOTOS = 'testSystemPhotosImportSamplesActualImageInsideSandbox'
ROOT = Path(__file__).resolve().parent


def contract():
    value = json.loads((ROOT / 'mac-source-census.json').read_text())
    return {'hosted': [x['identifier'] for x in value['targets']['TouchColorMacTests']['tests']],
            'normal': value['proposed_normal_ui_methods'], 'sandbox': value['sandbox_ui_methods']}


def command(name, seconds, cleanup=0, argv=None, action=None, role=None, output=None):
    return dict(id=name, seconds=seconds, cleanup=cleanup, argv=argv, action=action, role=role, output=output)


def xcode(scheme, configuration, derived, *, sandbox=False, quiet=False):
    args = ['/usr/bin/xcodebuild'] + (['-quiet'] if quiet else [])
    args += ['-project', PROJECT, '-scheme', scheme, '-configuration', configuration,
             '-destination', 'generic/platform=macOS' if configuration == 'Release' else 'platform=macOS,arch=arm64',
             '-derivedDataPath', derived]
    if configuration == 'Debug':
        args += ['-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never']
    return args


def settings(sandbox=False):
    if sandbox:
        return ['ARCHS=arm64', 'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_STYLE=Manual',
                'CODE_SIGN_IDENTITY=-', 'DEVELOPMENT_TEAM=', 'TOUCHCOLOR_ENABLE_SANDBOX=YES',
                'TOUCHCOLOR_SANDBOX_ENTITLEMENTS=TouchColorMac/TouchColorMac.entitlements']
    return ['ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO']


def ui(sandbox=False, build=False):
    args = xcode('TouchColorMacSandbox' if sandbox else 'TouchColorMac', 'Debug',
                 'build/mac-sandbox' if sandbox else 'build/mac-tests', quiet=build)
    args += ['-maximum-test-execution-time-allowance', '150' if sandbox else '120',
             '-only-testing:TouchColorMacUITests']
    for method in (*DIAGNOSTICS, *((PHOTOS,) if not sandbox else ())):
        args += ['-skip-testing:TouchColorMacUITests/TouchColorMacUITests/' + method]
    if not build:
        args += ['-resultBundlePath', 'build/mac-sandbox.xcresult' if sandbox else 'build/mac-ui.xcresult']
    return args + settings(sandbox) + ['build-for-testing' if build else 'test-without-building']


def stages(lane, *, platform_path='$SDK_PLATFORM', sdk_path='$SDK_PATH'):
    if lane not in ('normal', 'sandbox'):
        raise ValueError('Only normal/sandbox Mac rows')
    api = [command('sdk-platform', 40, 20, ['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-platform-path']),
           command('sdk-path', 40, 20, ['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path']),
           command('api-typecheck', 110, 20, ['/usr/bin/xcrun', '--sdk', 'macosx', 'swiftc', '-typecheck',
                    '-sdk', sdk_path, '-target', 'arm64-apple-macosx27.0', '-F', platform_path + '/Developer/Library/Frameworks',
                    '-I', platform_path + '/Developer/usr/lib', '-module-cache-path', 'build/accessibility-api/macosx',
                    'build/accessibility-api/AuditProbe.swift']),
           command('api-record', 2, action='api-record')]
    setup = [command('launcher-self-test', 10, 5, action='launcher-self-test'),
             command('source-head', 7, 4, ['/usr/bin/git', 'rev-parse', 'HEAD']),
             command('source-parent', 7, 4, ['/usr/bin/git', 'rev-list', '--parents', '-n', '1', 'HEAD']),
             command('source-tree', 7, 4, ['/usr/bin/git', 'rev-parse', 'HEAD^{tree}']),
             command('source-clean', 7, 4, ['/usr/bin/git', 'status', '--porcelain', '--untracked-files=all']),
             command('source-changes', 7, 4, ['/usr/bin/git', 'diff', '--name-only', '--no-renames',
                       '84da71d3526426a6e630887dc88fed59e1edc055', 'HEAD', '--']),
             command('host-version', 7, 4, ['/usr/bin/sw_vers', '-productVersion']),
             command('host-build', 7, 4, ['/usr/bin/sw_vers', '-buildVersion']),
             command('host-architecture', 7, 4, ['/usr/bin/uname', '-m']),
             command('xcode-version', 10, 5, ['/usr/bin/xcodebuild', '-version']),
             command('xcode-sdks', 15, 5, ['/usr/bin/xcodebuild', '-showsdks']),
             command('scheme-list', 15, 5, ['/usr/bin/xcodebuild', '-list', '-json', '-project', PROJECT]),
             command('actual-destination', 15, 5, ['/usr/bin/xcodebuild', '-showdestinations', '-project', PROJECT, '-scheme', 'TouchColorMac']),
             command('source-host-contract', 20, action='source-host-contract')]
    common = [{'id': 'setup', 'seconds': 300, 'commands': setup}, {'id': 'api', 'seconds': 200, 'commands': api}]
    if lane == 'normal':
        build = xcode('TouchColorMac', 'Debug', 'build/mac-tests', quiet=True) + settings() + ['build-for-testing']
        hosted = xcode('TouchColorMac', 'Debug', 'build/mac-tests') + ['-resultBundlePath', 'build/mac-unit.xcresult',
                  '-only-testing:TouchColorMacTests'] + settings() + ['test-without-building']
        return common + [
            {'id': 'normal-build-hosted', 'seconds': 480, 'commands': [command('normal-build', 300, 20, build),
                command('hosted', 160, 20, hosted, role='hosted'), command('normal-build-record', 10, action='normal-build-record')]},
            {'id': 'normal-ui', 'seconds': 600, 'commands': [command('normal-fixture', 10, action='normal-fixture'),
                command('normal', 580, 20, ui(), role='normal'),
                command('normal-fixture-after', 5, action='normal-fixture-after')]}]
    release_app = 'build/mac-arm64/Build/Products/Release/TouchColor.app/Contents'
    executable = release_app + '/MacOS/TouchColor'
    release_base = xcode('TouchColorMac', 'Release', 'build/mac-arm64')
    release = [command('release-build', 420, 20, xcode('TouchColorMac', 'Release', 'build/mac-arm64', quiet=True) + settings() + ['build']),
               command('release-settings', 20, 5, release_base + settings() + ['-showBuildSettings', '-json'], output='build/mac-release-settings.json'),
               command('release-file', 5, 2, ['/usr/bin/file', executable]),
               command('release-lipo', 5, 2, ['/usr/bin/lipo', '-info', executable]),
               command('release-linkage', 5, 2, ['/usr/bin/otool', '-L', executable]),
               command('release-build-version', 5, 2, ['/usr/bin/otool', '-l', executable]),
               command('release-strings', 10, 3, ['/usr/bin/strings', executable]),
               command('release-validate', 5, action='release-validate')]
    app = 'build/mac-sandbox/Build/Products/Debug/TouchColor.app'
    sandbox = [command('sandbox-fixture', 5, action='sandbox-fixture'), command('sandbox-build', 120, 20, ui(True, True)),
               command('sandbox-resign', 10, 3, ['/usr/bin/codesign', '--force', '--sign', '-', '--entitlements', 'build/mac-sandbox-minimal.entitlements', app]),
               command('sandbox-signature-before', 10, 3, ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', app]),
               command('sandbox-entitlements-before', 10, 3, ['/usr/bin/codesign', '-d', '--entitlements', ':-', app], output='build/mac-sandbox-entitlements.plist'),
               command('sandbox', 530, 20, ui(True), role='sandbox'),
               command('sandbox-signature-after', 10, 3, ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', app]),
               command('sandbox-entitlements-after', 10, 3, ['/usr/bin/codesign', '-d', '--entitlements', ':-', app], output='build/mac-sandbox-post-entitlements.plist'),
               command('sandbox-boundary-after', 5, action='sandbox-boundary-after')]
    return common + [{'id': 'release', 'seconds': 480, 'commands': release},
                     {'id': 'sandbox', 'seconds': 720, 'commands': sandbox}]


def validate():
    expected = contract()
    if [len(expected[k]) for k in ('hosted', 'normal', 'sandbox')] != [61, 11, 12]:
        raise ValueError('Mac compiled test inventory changed')
    for lane in ('normal', 'sandbox'):
        plan = stages(lane)
        if sum(s['seconds'] for s in plan) != (1580 if lane == 'normal' else 1700):
            raise ValueError('Two-job budget maxima changed')
        for stage in plan:
            if sum(c['seconds'] for c in stage['commands']) > stage['seconds']:
                raise ValueError('Subcommands exceed stage budget')
            for step in stage['commands']:
                if not 0 <= step['cleanup'] <= 20 or step['seconds'] <= step['cleanup']:
                    raise ValueError('Invalid finite command budget')
                if (step['argv'] is None) == (step['action'] is None):
                    raise ValueError('A command is exactly one native argv or local action')
    return expected
