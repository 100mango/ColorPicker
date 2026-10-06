#!/usr/bin/env python3
"""Inspect the fixed original-iOS app graph and actual unsigned products.

Read-only, no simulator/signing action. Mach-O fields follow Apple's public
cctools include/mach-o/{loader,fat}.h. This checks package identity, not a
signature, Store eligibility, older-OS runtime, or historical installed upgrade.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_ENTRIES, MAX_BYTES, MAX_SECONDS = 8192, 1024 * 1024 * 1024, 30
IMPORT_SHA = "32de83ef1894d1f2c73f1976a380f2295bf542eb99e16efd41e3ad84960248f1"
POLICY_SOURCE = 'ColorPicker/PrivacyPolicy.html'
POLICY_PRODUCT = 'app/PrivacyPolicy.html'
POLICY_SHA256 = '09af166e63987e02cb3722eacf4d4aa2ab6bccf55a5b43839ca4009826865cc2'
APP_SOURCES = sorted(['ColorPicker/' + name for name in (
    'main.m', 'ColorAppDelegate.m', 'ColorSceneDelegate.m', 'ColorMainViewController.m',
    'ColorViewController.m', 'ColorRealTimeViewController.m', 'ColorDetectView.m',
    'TCColorUtilities.m', 'TCPrivacyViewController.m', 'TCWorkspaceViewController.m',
    'TCPhotoImportTask.swift')] + ['TouchColorPhoneCompanion/PhonePaletteImportController.swift'])
COMPANION = (b"TCWatchPaletteInbox", b"PhonePaletteInboxController", b"PhonePaletteInbox")
PAIRED = (b"PhonePairedTransferTests", b"PairedReceiptBarrier")
SEAMS = (b"--ui-test-", b"TOUCHCOLOR_TEST_DEFAULTS", b"TOUCHCOLOR_PAIRED_E2E", b"TOUCHCOLOR_PAIRED_BARRIER", b"WATCH_EDITOR")
MACH_MAGICS = (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def version(number):
    return [number >> 16, (number >> 8) & 255, number & 255]


def mach_info(raw):
    """Read bounded 64-bit thin/fat headers and load commands, never execute."""
    require(len(raw) >= 32, 'Truncated Mach-O')
    magic = raw[:4]
    if magic in MACH_MAGICS[2:]:
        count = struct.unpack_from('>I', raw, 4)[0]
        width = 32 if magic == MACH_MAGICS[3] else 20
        require(0 < count <= 8 and 8 + width * count <= len(raw), 'Invalid fat architecture table')
        result, intervals, cpus = [], [], set()
        for i in range(count):
            pos = 8 + i * width
            cpu, subtype = struct.unpack_from('>II', raw, pos)
            if width == 32:
                offset, size, align, reserved = struct.unpack_from('>QQII', raw, pos + 8)
                require(reserved == 0, 'Invalid fat reserved value')
            else:
                offset, size, align = struct.unpack_from('>III', raw, pos + 8)
            require(cpu not in cpus and align <= 30 and offset % (1 << align) == 0,
                    'Duplicate or misaligned fat slice')
            require(offset >= 8 + width * count and size >= 32 and offset + size <= len(raw), 'Invalid fat slice bounds')
            require(all(offset + size <= a or offset >= b for a, b in intervals), 'Overlapping fat slices')
            require(raw[offset:offset + 4] in MACH_MAGICS[:2], 'Nested or unsupported Mach-O slice')
            slices = mach_info(raw[offset:offset + size])
            require(len(slices) == 1 and slices[0]['cpu'] == cpu and slices[0]['subtype'] == subtype, 'Fat slice identity mismatch')
            cpus.add(cpu); intervals.append((offset, offset + size)); result.extend(slices)
        return result
    require(magic in MACH_MAGICS[:2], 'Expected a 64-bit Mach-O product')
    endian = '<' if magic == MACH_MAGICS[0] else '>'
    _, cpu, subtype, kind, count, size, _, reserved = struct.unpack_from(endian + '8I', raw)
    require(reserved == 0 and kind in (2, 6, 8), 'Unsupported Mach-O type')
    require(0 < count <= 4096 and 32 + size <= len(raw), 'Invalid Mach-O command bounds')
    position, builds, links = 32, [], []
    for _ in range(count):
        require(position + 8 <= 32 + size, 'Truncated load command')
        command, length = struct.unpack_from(endian + 'II', raw, position)
        require(length >= 8 and length % 8 == 0 and position + length <= 32 + size, 'Invalid load command size')
        if command == 0x32:  # LC_BUILD_VERSION
            require(length >= 24, 'Short build version')
            platform, minimum, sdk, tools = struct.unpack_from(endian + '4I', raw, position + 8)
            require(length == 24 + tools * 8, 'Malformed build tool table')
            builds.append({'platform': platform, 'minimum': version(minimum), 'sdk': version(sdk)})
        if command in (0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023):
            require(length >= 24, 'Short dylib command')
            offset = struct.unpack_from(endian + 'I', raw, position + 8)[0]
            require(24 <= offset < length, 'Invalid dylib name offset')
            name = raw[position + offset:position + length]
            require(b'\0' in name, 'Unterminated dylib path')
            links.append(name.split(b'\0', 1)[0].decode('utf-8'))
        position += length
    require(position == 32 + size and len(builds) == 1, 'Missing, duplicate or inconsistent build version')
    return [{'cpu': cpu, 'subtype': subtype, 'kind': kind, **builds[0], 'libraries': links}]


def generated_project(raw):
    """Parse only our deterministic quoted-key OpenStep serialization."""
    text = raw.decode('utf-8')
    require(text.startswith('// !$*UTF8*$!\n'), 'Unexpected generated project format')
    text = text.split('\n', 1)[1]
    token = re.compile(r'\s*("(?:\\.|[^"\\])*"|[{}()=;,]|[0-9]+)')
    tokens, at = [], 0
    while at < len(text) and text[at:].strip():
        found = token.match(text, at)
        require(found is not None, 'Invalid generated project token')
        tokens.append(found.group(1)); at = found.end()
    cursor = 0
    def take():
        nonlocal cursor
        require(cursor < len(tokens), 'Truncated generated project')
        item = tokens[cursor]; cursor += 1; return item
    def value(depth=0):
        require(depth < 32, 'Generated project nesting too deep')
        item = take()
        if item == '{':
            result = {}
            while tokens[cursor] != '}':
                key = json.loads(take()); require(key not in result, 'Duplicate project key')
                require(take() == '=', 'Missing project assignment')
                result[key] = value(depth + 1); require(take() == ';', 'Missing project terminator')
            take(); return result
        if item == '(':
            result = []
            while tokens[cursor] != ')':
                result.append(value(depth + 1))
                require(cursor < len(tokens), 'Truncated project array')
                if tokens[cursor] != ')':
                    require(take() == ',', 'Missing project separator')
            take(); return result
        return json.loads(item)
    try:
        result = value()
    except (IndexError, json.JSONDecodeError) as error:
        raise ValueError('Malformed generated project') from error
    require(cursor == len(tokens), 'Trailing generated project tokens')
    return result


def source_graph(root):
    project = generated_project((root / 'TouchColor.xcodeproj/project.pbxproj').read_bytes())
    objects = project['objects']
    targets = {x['name']: x for x in objects.values() if x.get('isa') == 'PBXNativeTarget'}
    require(set(targets) == {'TouchColor', 'TouchColorTests', 'TouchColorUITests'}, 'Unexpected iOS target graph')
    require(not any(x.get('isa') in ('PBXReferenceProxy', 'PBXContainerItemProxy') and 'Watch' in str(x) for x in objects.values()), 'Watch target proxy retained')
    require(not any('Watch' in str(x) or 'PairedTests/' in str(x) for x in objects.values()), 'Watch/paired project reference retained')
    target = targets['TouchColor']
    memberships, resource_refs = [], []
    for phase_id in target['buildPhases']:
        phase = objects[phase_id]
        require(phase['isa'] != 'PBXCopyFilesBuildPhase', 'Unexpected app copy/embed phase')
        if phase['isa'] == 'PBXSourcesBuildPhase':
            memberships += [objects[objects[b]['fileRef']]['path'] for b in phase['files']]
        if phase['isa'] == 'PBXResourcesBuildPhase':
            resource_refs += [objects[objects[b]['fileRef']] for b in phase['files']]
    require(sorted(memberships) == APP_SOURCES, 'App source membership differs from reviewed twelve-file graph')
    policies = [ref for ref in resource_refs if Path(ref.get('path', '')).name == 'PrivacyPolicy.html']
    require(len(policies) == 1 and policies[0].get('path') == POLICY_SOURCE and
            policies[0].get('isa') == 'PBXFileReference' and policies[0].get('sourceTree') == '<group>' and
            policies[0].get('lastKnownFileType') == 'text.html',
            'Bundled privacy policy must occur exactly once in app resources')
    policy_path = root / POLICY_SOURCE
    require(policy_path.is_file() and not policy_path.is_symlink(), 'Missing or linked reviewed privacy policy source')
    policy = policy_path.read_bytes()
    require(hashlib.sha256(policy).hexdigest() == POLICY_SHA256, 'Reviewed privacy policy source bytes changed')
    require(target.get('dependencies', []) == [], 'Unexpected app target dependency')
    require(not any('PhonePaletteInbox' in p for p in memberships), 'Companion source retained')
    require(hashlib.sha256((root / 'TouchColorPhoneCompanion/PhonePaletteImportController.swift').read_bytes()).hexdigest() == IMPORT_SHA, 'Independent importer bytes changed')
    delegate = (root / 'ColorPicker/ColorAppDelegate.m').read_text()
    require('TCWatchPaletteInbox' not in delegate and 'activate]' not in delegate, 'Companion activation retained')
    for name in ('ColorMainViewController.h', 'ColorMainViewController.m', 'TCWorkspaceViewController.m'):
        text = (root / 'ColorPicker' / name).read_text()
        require('openWatchInbox' not in text and 'watch.inbox.open' not in text, 'Companion entry retained')
    return {'source_paths': sorted(memberships), 'importer_sha256': IMPORT_SHA,
            'resource_paths': sorted(ref.get('path', ref.get('name', '')) for ref in resource_refs),
            'privacy_policy': {'path': POLICY_SOURCE, 'bytes': len(policy), 'sha256': POLICY_SHA256},
            'project_sha256': hashlib.sha256((root / 'TouchColor.xcodeproj/project.pbxproj').read_bytes()).hexdigest()}


def verify(app, mode='device', release=True, *, build_for_testing=False, root=ROOT, clock=time.monotonic):
    app, root = Path(app), Path(root)
    require(app.name == 'TouchColor.app', 'Unexpected app product name')
    require(mode in ('device', 'simulator'), 'Invalid packaging mode')
    require((release and mode == 'device' and not build_for_testing) or
            (not release and mode == 'simulator' and build_for_testing), 'Expected Release device or Debug simulator test host')
    started = clock(); deadline = started + MAX_SECONDS
    def timely():
        require(clock() < deadline, 'Package inspection exceeded original 30-second deadline')
    graph = source_graph(root); timely()
    policy = (root / POLICY_SOURCE).read_bytes()
    require(hashlib.sha256(policy).hexdigest() == graph['privacy_policy']['sha256'],
            'Reviewed privacy policy source changed during inspection')
    timely()
    directories, files, binaries, plists, identities, total, count = {}, {}, {}, {}, {}, 0, 0
    roots = [('app', app)]
    if build_for_testing:
        roots.append(('runner', app.parent / 'TouchColorUITests-Runner.app'))
    for label, directory in roots:
        require(directory.is_dir() and not directory.is_symlink(), 'Missing or linked product: ' + label)
        pending = [directory]
        while pending:
            folder = pending.pop(); timely()
            with os.scandir(folder) as entries:
                for entry in entries:
                    timely(); count += 1
                    require(count <= MAX_ENTRIES, 'Package entry bound exceeded')
                    path = Path(entry.path); relative = path.relative_to(directory).as_posix(); key = label + '/' + relative
                    before = path.lstat()
                    require(not stat.S_ISLNK(before.st_mode), 'Linked package entry: ' + key)
                    if stat.S_ISDIR(before.st_mode):
                        require(path.name != 'Watch' and path.suffix not in ('.app', '.appex'), 'Unexpected nested app/extension: ' + key)
                        directories[key] = True; pending.append(path); continue
                    require(stat.S_ISREG(before.st_mode), 'Nonregular package entry: ' + key)
                    total += before.st_size
                    require(total <= MAX_BYTES, 'Package byte bound exceeded')
                    h = hashlib.sha256(); data = bytearray()
                    with path.open('rb') as stream:
                        while chunk := stream.read(1024 * 1024):
                            timely(); h.update(chunk); data.extend(chunk)
                    timely(); after = path.stat()
                    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(data) == before.st_size,
                            'Product changed during inspection: ' + key)
                    files[key] = {'bytes': before.st_size, 'sha256': h.hexdigest()}
                    identities[path] = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    if key == POLICY_PRODUCT:
                        require(bytes(data) == policy, 'Bundled privacy policy differs from reviewed source bytes')
                    if path.suffix in ('.plist', '.xcprivacy'):
                        plists[key] = plistlib.loads(data)
                    require('PaletteFixtures' not in relative, 'Fixture product embedded')
                    if bytes(data[:4]) in MACH_MAGICS:
                        raw = bytes(data); slices = mach_info(raw)
                        require(all(x['platform'] == (2 if mode == 'device' else 7) for x in slices), 'Foreign platform binary embedded: ' + key)
                        require(not any('/WatchConnectivity.framework/' in link or '/WatchKit.framework/' in link
                                        for s in slices for link in s['libraries']), 'Companion framework linked: ' + key)
                        require(not any(t in raw for t in PAIRED), 'Paired test code embedded: ' + key)
                        production = label == 'app' and not relative.startswith('PlugIns/')
                        if production:
                            require(not any(t in raw for t in COMPANION), 'Companion implementation embedded: ' + key)
                            if release:
                                require(not any(t in raw for t in SEAMS), 'Debug fixture leaked into Release: ' + key)
                        binaries[key] = {'slices': slices, 'importer_marker': b'TCPaletteImportController' in raw}
    def info(label, relative=''):
        return plists[label + '/' + (relative + '/' if relative else '') + 'Info.plist']
    metadata = info('app'); expected_platform = 'iPhoneOS' if mode == 'device' else 'iPhoneSimulator'
    for key, value in {'CFBundleIdentifier': 'com.mango.touchColor', 'CFBundleExecutable': 'TouchColor',
                       'CFBundlePackageType': 'APPL', 'CFBundleName': 'TouchColor', 'CFBundleDisplayName': 'TouchColor',
                       'CFBundleShortVersionString': '2.0', 'CFBundleVersion': '20001', 'MinimumOSVersion': '15.0',
                       'CFBundleSupportedPlatforms': [expected_platform], 'UIDeviceFamily': [1, 2],
                       'UIRequiredDeviceCapabilities': ['arm64']}.items():
        require(metadata.get(key) == value, 'App metadata mismatch: ' + key)
    require(metadata.get('CFBundleIcons', {}).get('CFBundlePrimaryIcon', {}).get('CFBundleIconName') == 'AppIcon', 'Compiled app icon identity missing')
    require(not any(metadata.get(k) for k in ('UIFileSharingEnabled', 'LSSupportsOpeningDocumentsInPlace',
                'NSPhotoLibraryUsageDescription', 'NSPhotoLibraryAddUsageDescription')), 'Privacy/document policy changed')
    original = plistlib.loads((root / 'ColorPicker/TouchColor-Info.plist').read_bytes())
    for key in ('NSCameraUsageDescription', 'UIApplicationSceneManifest', 'UILaunchScreen',
                'UISupportedInterfaceOrientations', 'UISupportedInterfaceOrientations~ipad'):
        require(metadata.get(key) == original.get(key), 'Original metadata changed: ' + key)
    for path in ('Assets.car', 'PrivacyInfo.xcprivacy', 'PrivacyPolicy.html', 'en.lproj/Localizable.strings', 'zh-Hans.lproj/Localizable.strings',
                 'en.lproj/InfoPlist.strings', 'zh-Hans.lproj/InfoPlist.strings'):
        require('app/' + path in files and files['app/' + path]['bytes'] > 0, 'Missing compiled resource: ' + path)
    require(plists['app/PrivacyInfo.xcprivacy'] ==
            plistlib.loads((root / 'ColorPicker/PrivacyInfo.xcprivacy').read_bytes()), 'Privacy manifest differs from reviewed source')
    bundles = sorted(k for k in directories if k.endswith('.xctest'))
    expected = ['app/PlugIns/TouchColorTests.xctest', 'runner/PlugIns/TouchColorUITests.xctest'] if build_for_testing else []
    require(bundles == expected, 'Unexpected test bundle inventory')
    platform = 2 if mode == 'device' else 7
    own = [('app/TouchColor', 2, [15, 0, 0])]
    if build_for_testing:
        for label, relative, target in (('app', 'PlugIns/TouchColorTests.xctest', 'TouchColorTests'),
                                        ('runner', 'PlugIns/TouchColorUITests.xctest', 'TouchColorUITests')):
            value = info(label, relative)
            require(value.get('CFBundleIdentifier') == 'com.mango.touchColor.' + target and
                    value.get('CFBundleExecutable') == target and value.get('CFBundlePackageType') == 'BNDL', 'Test bundle identity mismatch')
            own.append((label + '/' + relative + '/' + target, 8, [17, 0, 0]))
        runner = info('runner')
        require(runner.get('CFBundleIdentifier') == 'com.mango.touchColor.TouchColorUITests.xctrunner' and
                runner.get('CFBundleExecutable') == 'TouchColorUITests-Runner' and runner.get('CFBundlePackageType') == 'APPL', 'UI runner identity mismatch')
        own.append(('runner/TouchColorUITests-Runner', 2, None))
    if 'app/TouchColor.debug.dylib' in binaries:
        require(not release, 'Debug dylib in Release')
        own.append(('app/TouchColor.debug.dylib', 6, [15, 0, 0]))
    for key, kind, minimum in own:
        require(key in binaries, 'Missing real Mach-O executable: ' + key)
        slices = binaries[key]['slices']; cpus = {x['cpu'] for x in slices}
        require(0x100000c in cpus and cpus <= ({0x100000c} if mode == 'device' else {0x100000c, 0x1000007}), 'Unexpected architecture: ' + key)
        require(all(x['platform'] == platform and x['kind'] == kind and (minimum is None or x['minimum'] == minimum)
                    for x in slices), 'Wrong Mach-O platform/type/deployment: ' + key)
    require(any(v['importer_marker'] for k, v in binaries.items() if k.startswith('app/') and not k.startswith('app/PlugIns/')), 'Independent importer implementation missing')
    for path, identity in identities.items():
        timely(); now = path.lstat()
        require(stat.S_ISREG(now.st_mode) and identity == (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns), 'Product changed before completion')
    finished = clock()
    require(finished < deadline, 'Package inspection exceeded original 30-second deadline')
    return {'schema': 1, 'scope': 'original-iPhone-iPad-unsigned-package', 'mode': mode, 'release': release,
            'build_for_testing': build_for_testing, 'source': graph, 'metadata': metadata,
            'files': files, 'binaries': binaries, 'test_bundles': bundles, 'entries': count,
            'bytes': total, 'elapsed_seconds': finished - started,
            'limits': {'seconds': MAX_SECONDS, 'entries': MAX_ENTRIES, 'bytes': MAX_BYTES},
            'not_qualified': ['signature', 'Store processing', 'older-OS execution', 'published-binary upgrade']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app'); parser.add_argument('mode', choices=('device', 'simulator'))
    parser.add_argument('--debug', action='store_true'); parser.add_argument('--build-for-testing', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args.app, args.mode, not args.debug, build_for_testing=args.build_for_testing)
    payload = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(payload)
    print(payload)


if __name__ == '__main__':
    main()
