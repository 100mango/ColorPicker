"""Positive products and malformed/contaminated packaging regressions, no native commands."""
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch
import verify_original_ios_package as package


def macho(platform=2, minimum=15, kind=2, cpu=0x100000c, payload=b'TCPaletteImportController', links=()):
    commands = [struct.pack('<6I', 0x32, 24, platform, minimum << 16, 27 << 16, 0)]
    for link in links:
        text = link.encode() + b'\0'; size = (24 + len(text) + 7) // 8 * 8
        commands.append(struct.pack('<6I', 0xc, size, 24, 0, 0, 0) + text + b'\0' * (size - 24 - len(text)))
    commands = b''.join(commands)
    return struct.pack('<8I', 0xfeedfacf, cpu, 0, kind, 1 + len(links), len(commands), 0, 0) + commands + payload


def serialize(value):
    if isinstance(value, dict):
        return '{' + ''.join(json.dumps(k) + '=' + serialize(v) + ';' for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '(' + ''.join(serialize(v) + ',' for v in value) + ')'
    return json.dumps(value)


class Fixture:
    def __init__(self, parent, debug=False):
        self.root = parent / 'source'; self.root.mkdir()
        self.app = parent / 'products/TouchColor.app'; self.app.mkdir(parents=True)
        self.debug = debug
        self.project = {'objects': {
            'app': {'isa': 'PBXNativeTarget', 'name': 'TouchColor', 'buildPhases': ['sources']},
            'unit': {'isa': 'PBXNativeTarget', 'name': 'TouchColorTests'},
            'ui': {'isa': 'PBXNativeTarget', 'name': 'TouchColorUITests'},
            'sources': {'isa': 'PBXSourcesBuildPhase', 'files': ['build']},
            'build': {'isa': 'PBXBuildFile', 'fileRef': 'import'},
            'import': {'isa': 'PBXFileReference', 'path': 'TouchColorPhoneCompanion/PhonePaletteImportController.swift'}}}
        self.project['objects']['sources']['files'] = []
        for i, name in enumerate(package.APP_SOURCES):
            self.project['objects']['sources']['files'].append('build' + str(i))
            self.project['objects']['build' + str(i)] = {'isa': 'PBXBuildFile', 'fileRef': 'file' + str(i)}
            self.project['objects']['file' + str(i)] = {'isa': 'PBXFileReference', 'path': name}
        self.write_project()
        source_import = package.ROOT / 'TouchColorPhoneCompanion/PhonePaletteImportController.swift'
        p = self.root / 'TouchColorPhoneCompanion/PhonePaletteImportController.swift'; p.parent.mkdir(); p.write_bytes(source_import.read_bytes())
        color = self.root / 'ColorPicker'; color.mkdir()
        for name in ('ColorAppDelegate.m', 'ColorMainViewController.h', 'ColorMainViewController.m', 'TCWorkspaceViewController.m'):
            (color / name).write_text('// synthetic original-iOS product\n')
        for name in ('TouchColor-Info.plist', 'PrivacyInfo.xcprivacy'):
            (color / name).write_bytes((package.ROOT / 'ColorPicker' / name).read_bytes())
        self.metadata = plistlib.loads((color / 'TouchColor-Info.plist').read_bytes())
        self.metadata.update(CFBundleIdentifier='com.mango.touchColor', CFBundleExecutable='TouchColor',
                             CFBundleName='TouchColor', CFBundleDisplayName='TouchColor',
                             CFBundleShortVersionString='2.0', CFBundleVersion='20001', MinimumOSVersion='15.0',
                             CFBundleSupportedPlatforms=['iPhoneSimulator' if debug else 'iPhoneOS'], UIDeviceFamily=[1, 2],
                             CFBundleIcons={'CFBundlePrimaryIcon': {'CFBundleIconName': 'AppIcon'}})
        self.write_info()
        (self.app / 'Assets.car').write_bytes(b'synthetic compiled icon')
        (self.app / 'PrivacyInfo.xcprivacy').write_bytes((color / 'PrivacyInfo.xcprivacy').read_bytes())
        for language in ('en', 'zh-Hans'):
            directory = self.app / (language + '.lproj'); directory.mkdir()
            for name in ('Localizable.strings', 'InfoPlist.strings'):
                (directory / name).write_text('"test"="test";')
        (self.app / 'TouchColor').write_bytes(macho(platform=7 if debug else 2))
        if debug:
            self.bundle(self.app / 'PlugIns/TouchColorTests.xctest', 'TouchColorTests')
            self.runner = self.app.parent / 'TouchColorUITests-Runner.app'; self.runner.mkdir()
            (self.runner / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.mango.touchColor.TouchColorUITests.xctrunner',
                'CFBundleExecutable': 'TouchColorUITests-Runner', 'CFBundlePackageType': 'APPL'}))
            (self.runner / 'TouchColorUITests-Runner').write_bytes(macho(platform=7, minimum=17, payload=b'runner'))
            self.bundle(self.runner / 'PlugIns/TouchColorUITests.xctest', 'TouchColorUITests')

    def bundle(self, path, target):
        path.mkdir(parents=True)
        (path / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.mango.touchColor.' + target,
            'CFBundleExecutable': target, 'CFBundlePackageType': 'BNDL'}))
        (path / target).write_bytes(macho(platform=7, minimum=17, kind=8, payload=b'tests'))

    def write_info(self):
        (self.app / 'Info.plist').write_bytes(plistlib.dumps(self.metadata))

    def write_project(self):
        p = self.root / 'TouchColor.xcodeproj/project.pbxproj'; p.parent.mkdir(exist_ok=True)
        p.write_text('// !$*UTF8*$!\n' + serialize(self.project) + '\n')

    def verify(self, **kwargs):
        return package.verify(self.app, 'simulator' if self.debug else 'device', not self.debug,
                              build_for_testing=self.debug, root=self.root, **kwargs)


class PackageTests(unittest.TestCase):
    def fixture(self, debug=False):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        return Fixture(Path(directory.name), debug)

    def test_release_real_macho_inventory_and_preserved_importer(self):
        f = self.fixture(); result = f.verify()
        self.assertEqual(result['test_bundles'], [])
        self.assertEqual(result['binaries']['app/TouchColor']['slices'][0]['minimum'], [15, 0, 0])
        self.assertEqual(result['source']['importer_sha256'], package.IMPORT_SHA)
        self.assertEqual(result['files']['app/TouchColor']['sha256'], hashlib.sha256((f.app / 'TouchColor').read_bytes()).hexdigest())
        self.assertIn('signature', result['not_qualified'])

    def test_debug_embeds_only_registered_hosted_bundle_and_separate_ui_runner(self):
        f = self.fixture(True); result = f.verify()
        self.assertEqual(result['test_bundles'], ['app/PlugIns/TouchColorTests.xctest', 'runner/PlugIns/TouchColorUITests.xctest'])

    def test_debug_dylib_contains_real_importer_while_stub_does_not(self):
        f = self.fixture(True)
        (f.app / 'TouchColor').write_bytes(macho(platform=7, payload=b'stub'))
        (f.app / 'TouchColor.debug.dylib').write_bytes(macho(platform=7, kind=6))
        self.assertTrue(f.verify()['binaries']['app/TouchColor.debug.dylib']['importer_marker'])

    def test_test_absence_string_and_dormant_localization_are_not_product_implementation(self):
        f = self.fixture(True)
        (f.app / 'en.lproj/Localizable.strings').write_text('"Watch Inbox"="Watch Inbox";')
        (f.app / 'PlugIns/TouchColorTests.xctest/TouchColorTests').write_bytes(macho(platform=7, minimum=17, kind=8, payload=b'TCWatchPaletteInbox'))
        f.verify()

    def test_watch_nested_apps_extensions_fixtures_and_symlinks_reject(self):
        for name in ('Watch', 'Other.app', 'Example.appex', 'PaletteFixtures.bundle', 'linked'):
            with self.subTest(name=name):
                f = self.fixture(); p = f.app / name
                if name == 'linked': p.symlink_to(f.app / 'TouchColor')
                elif name == 'PaletteFixtures.bundle': p.write_bytes(b'fixture')
                else: p.mkdir()
                with self.assertRaises(ValueError): f.verify()

    def test_release_test_and_debug_bundles_reject(self):
        f = self.fixture(); f.bundle(f.app / 'PlugIns/TouchColorTests.xctest', 'TouchColorTests')
        with self.assertRaises(ValueError): f.verify()
        f = self.fixture(); (f.app / 'TouchColor.debug.dylib').write_bytes(macho(kind=6))
        with self.assertRaises(ValueError): f.verify()

    def test_missing_extra_or_wrong_test_identity_reject(self):
        f = self.fixture(True); (f.runner / 'PlugIns/TouchColorUITests.xctest/TouchColorUITests').unlink()
        with self.assertRaises(ValueError): f.verify()
        f = self.fixture(True); f.bundle(f.app / 'PlugIns/Extra.xctest', 'Extra')
        with self.assertRaises(ValueError): f.verify()
        f = self.fixture(True); p = f.app / 'PlugIns/TouchColorTests.xctest/Info.plist'
        value = plistlib.loads(p.read_bytes()); value['CFBundleIdentifier'] += '.wrong'; p.write_bytes(plistlib.dumps(value))
        with self.assertRaises(ValueError): f.verify()

    def test_no_companion_paired_code_or_release_debug_seams(self):
        for token in package.COMPANION + package.PAIRED + package.SEAMS:
            with self.subTest(token=token):
                f = self.fixture(); (f.app / 'TouchColor').write_bytes(macho(payload=b'TCPaletteImportController' + token))
                with self.assertRaises(ValueError): f.verify()
        for framework in ('WatchKit', 'WatchConnectivity'):
            f = self.fixture(); (f.app / 'TouchColor').write_bytes(macho(links=['/System/Library/Frameworks/' + framework + '.framework/' + framework]))
            with self.assertRaises(ValueError): f.verify()

    def test_missing_importer_or_changed_source_reject(self):
        f = self.fixture(); (f.app / 'TouchColor').write_bytes(macho(payload=b'not the importer'))
        with self.assertRaises(ValueError): f.verify()
        f = self.fixture(); (f.root / 'TouchColorPhoneCompanion/PhonePaletteImportController.swift').write_text('altered')
        with self.assertRaises(ValueError): f.verify()

    def test_graph_and_activation_and_both_ui_entries_reject(self):
        f = self.fixture(); f.project['objects']['extra'] = {'isa': 'PBXFileReference', 'path': 'TouchColorWatch.xcodeproj'}; f.write_project()
        with self.assertRaises(ValueError): f.verify()
        for name, text in [('ColorAppDelegate.m', '[[TCWatchPaletteInbox sharedInbox] activate];'),
                           ('ColorMainViewController.m', 'openWatchInbox'), ('TCWorkspaceViewController.m', 'watch.inbox.open')]:
            f = self.fixture(); (f.root / 'ColorPicker' / name).write_text(text)
            with self.assertRaises(ValueError): f.verify()

    def test_metadata_privacy_camera_scene_and_resources_reject(self):
        for key, wrong in [('CFBundleIdentifier', 'foreign'), ('CFBundleVersion', '1'), ('MinimumOSVersion', '17.0'),
                           ('UIDeviceFamily', [1]), ('CFBundleSupportedPlatforms', ['WatchOS']),
                           ('UIFileSharingEnabled', True), ('NSPhotoLibraryUsageDescription', 'extra'),
                           ('NSCameraUsageDescription', 'changed'), ('UIApplicationSceneManifest', {})]:
            f = self.fixture(); f.metadata[key] = wrong; f.write_info()
            with self.subTest(key=key), self.assertRaises(ValueError): f.verify()
        f = self.fixture(); (f.app / 'PrivacyInfo.xcprivacy').write_bytes(plistlib.dumps({}))
        with self.assertRaises(ValueError): f.verify()
        f = self.fixture(); (f.app / 'zh-Hans.lproj/Localizable.strings').unlink()
        with self.assertRaises(ValueError): f.verify()

    def test_wrong_architecture_platform_type_and_floor_reject(self):
        for change in ({'cpu': 0x1000007}, {'platform': 4}, {'platform': 7}, {'minimum': 17}, {'kind': 6}):
            f = self.fixture(); (f.app / 'TouchColor').write_bytes(macho(**change))
            with self.subTest(change=change), self.assertRaises(ValueError): f.verify()

    def test_malformed_real_binary_rejects(self):
        for raw in (b'not an executable', b'\xcf\xfa\xed\xfe' + b'\0' * 20,
                    macho()[:35], macho()[:52] + b'\xff' * 4):
            f = self.fixture(); (f.app / 'TouchColor').write_bytes(raw)
            with self.subTest(raw=raw[:8]), self.assertRaises(ValueError): f.verify()

    def test_invalid_modes_and_bounds_reject(self):
        f = self.fixture()
        with self.assertRaises(ValueError): package.verify(f.app, 'simulator', True, root=f.root)
        with patch.object(package, 'MAX_BYTES', 1), self.assertRaises(ValueError): f.verify()
        with patch.object(package, 'MAX_ENTRIES', 1), self.assertRaises(ValueError): f.verify()
        tick = iter([0, 30])
        with self.assertRaises(ValueError): f.verify(clock=lambda: next(tick))

    def test_late_read_is_not_success(self):
        f = self.fixture(); tick = [0]
        original = Path.open
        class Delayed:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def read(self, *args):
                result = self.stream.read(*args); tick[0] = 31; return result
        def opened(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return Delayed(stream) if path == f.app / 'TouchColor' else stream
        with patch.object(Path, 'open', opened), self.assertRaises(ValueError):
            f.verify(clock=lambda: tick[0])

    def test_fat_slices_and_load_command_reconstruction(self):
        first = macho(platform=7); second = macho(platform=7, cpu=0x1000007)
        raw = struct.pack('>II', 0xcafebabe, 2)
        raw += struct.pack('>5I', 0x100000c, 0, 48, len(first), 0)
        raw += struct.pack('>5I', 0x1000007, 0, 48 + len(first), len(second), 0) + first + second
        self.assertEqual([s['cpu'] for s in package.mach_info(raw)], [0x100000c, 0x1000007])
        wrong = bytearray(raw); struct.pack_into('>I', wrong, 28, 0x100000c)
        with self.assertRaises(ValueError): package.mach_info(wrong)
        wrong = bytearray(macho()); struct.pack_into('<I', wrong, 36, 80)
        with self.assertRaises(ValueError): package.mach_info(wrong)

    def test_actual_staged_graph_and_product_surface_are_checked(self):
        graph = package.source_graph(package.ROOT)
        self.assertEqual(graph['source_paths'].count('TouchColorPhoneCompanion/PhonePaletteImportController.swift'), 1)
        self.assertFalse(any('Inbox' in p for p in graph['source_paths']))

    def test_renamed_foreign_platform_binary_is_rejected(self):
        f = self.fixture(); (f.app / 'unexpected.dylib').write_bytes(macho(platform=4, kind=6, payload=b'foreign'))
        with self.assertRaises(ValueError): f.verify()

    def test_added_or_duplicate_consumed_source_and_dependency_reject(self):
        for name in ('TouchColorMac/PrivacyView.swift', 'TestFixtures/PaletteFixtures/FixtureHost.swift', package.APP_SOURCES[0]):
            f = self.fixture()
            f.project['objects']['sources']['files'].append('foreign-build')
            f.project['objects']['foreign-build'] = {'isa': 'PBXBuildFile', 'fileRef': 'foreign-file'}
            f.project['objects']['foreign-file'] = {'isa': 'PBXFileReference', 'path': name}
            f.write_project()
            with self.assertRaises(ValueError): f.verify()
        f = self.fixture(); f.project['objects']['app']['dependencies'] = ['foreign-target']; f.write_project()
        with self.assertRaises(ValueError): f.verify()

    def test_missing_icon_identity_rejects(self):
        f = self.fixture(); f.metadata.pop('CFBundleIcons'); f.write_info()
        with self.assertRaises(ValueError): f.verify()

    def test_product_mutation_after_read_rejects(self):
        f = self.fixture(); original = Path.stat; calls = [0]
        def changed(path, *args, **kwargs):
            if path == f.app / 'TouchColor':
                calls[0] += 1
                if calls[0] == 2:
                    with path.open('ab') as stream: stream.write(b'changed')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'stat', changed), self.assertRaises(ValueError): f.verify()

    def test_fat_device_with_simulator_slice_and_duplicate_build_version_reject(self):
        a = macho(); b = macho(platform=7, cpu=0x1000007)
        raw = struct.pack('>II', 0xcafebabe, 2)
        raw += struct.pack('>5I', 0x100000c, 0, 48, len(a), 0)
        raw += struct.pack('>5I', 0x1000007, 0, 48 + len(a), len(b), 0) + a + b
        f = self.fixture(); (f.app / 'TouchColor').write_bytes(raw)
        with self.assertRaises(ValueError): f.verify()
        raw = bytearray(macho()); command = raw[32:56]
        struct.pack_into('<I', raw, 16, 2); struct.pack_into('<I', raw, 20, 48)
        raw = raw[:56] + command + raw[56:]
        with self.assertRaises(ValueError): package.mach_info(raw)

    def test_generated_project_exact_format_rejects_duplicate_and_trailing(self):
        project = {'objects': {'a': {'isa': 'PBXNativeTarget', 'name': 'TouchColor'}}, 'array': [1, 'x']}
        raw = ('// !$*UTF8*$!\n' + serialize(project)).encode()
        self.assertEqual(package.generated_project(raw), project)
        for raw in (b'// !$*UTF8*$!\n{"a"=1;"a"=2;}', b'// !$*UTF8*$!\n{}{}', b'// !$*UTF8*$!\n{"a"=', b'garbage'):
            with self.assertRaises(ValueError): package.generated_project(raw)


if __name__ == '__main__':
    unittest.main()
