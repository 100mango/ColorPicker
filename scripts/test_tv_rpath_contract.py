"""Synthetic main-image rpath regression; no native, network, or credentials.

These fixtures demonstrate policy behavior, not the contents of a real archive.
"""
import os
import plistlib
from types import SimpleNamespace
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tv_rpath_contract as ipa
policy = ipa.policy
p = policy
def binary(route,signed=False,platform=None,minimum=None,sdk=None,cpu=0x100000c,kind=2):
    s=p.spec(route)
    build=struct.pack("<6I",0x32,24,platform or s["macho_platform"],minimum or int(s["minimum_os"].split('.')[0])<<16,sdk or 27<<16,0)
    section=struct.pack("<16s16sQQIIIIIIII",b"__text",b"__TEXT",512,16,512,2,0,0,0x80000400,0,0,0)
    text=struct.pack("<II16sQQQQiiII",0x19,152,b"__TEXT",0,4096,0,528,5,5,1,0)+section
    link=struct.pack("<II16sQQQQiiII",0x19,72,b"__LINKEDIT",4096,4096,528,32 if signed else 16,1,1,0,0)
    commands=build+text+link
    if signed:commands+=struct.pack("<4I",0x1d,16,544,16)
    header=struct.pack("<8I",0xfeedfacf,cpu,0,kind,4 if signed else 3,len(commands),0,0)
    return (header+commands).ljust(512,b"\0")+b"C"*16+b"L"*16+(b"S"*16 if signed else b"")


def info(route):
    s=p.spec(route)
    return {"CFBundleIdentifier":s["bundle_id"],"CFBundleExecutable":s["executable"],
        "CFBundleShortVersionString":s["version"],"CFBundleVersion":s["build"],"CFBundlePackageType":"APPL",
        "DTPlatformName":s["sdk"],"CFBundleSupportedPlatforms":[s["supported_platform"]],
        "UIDeviceFamily":[s["device_family"]],"MinimumOSVersion":s["minimum_os"],"DTSDKName":s["sdk"]+"27.0"}


def payload(route,signed=False):
    s=p.spec(route)
    files={"Info.plist":plistlib.dumps(info(route)),"PkgInfo":b"APPL????","Assets.car":b"SYNTHETIC-ASSETS",
           s["executable"]:binary(route,signed),"PrivacyInfo.xcprivacy":plistlib.dumps({"NSPrivacyTracking":False})}
    for name in s["resource_bundles"]:
        files[name+"/Info.plist"]=plistlib.dumps({"CFBundlePackageType":"BNDL"})
        files[name+"/data.txt"]=b"SYNTHETIC-RESOURCE"
    if signed:files.update({"embedded.mobileprovision":b"SYNTHETIC-UNTRUSTED-PROFILE","_CodeSignature/CodeResources":b"SYNTHETIC-SEAL"})
    return files


def make_app(parent,route,signed=False,mutate=None):
    s=p.spec(route);files=payload(route,signed)
    if mutate:mutate(files)
    app=parent/(s["product"]+".app");app.mkdir(parents=True)
    for name,data in files.items():
        path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        path.chmod(0o755 if name==s["executable"] else 0o644)
    return app

fixtures = SimpleNamespace(binary=binary, make_app=make_app)

LOADER = b"@loader_path/Frameworks"
EXECUTABLE = b"@executable_path/Frameworks"


def rpath_command(path):
    size = (12 + len(path) + 1 + 7) & ~7
    return (struct.pack("<III", 0x8000001c, size, 12) + path + b"\0").ljust(size, b"\0")


def append_commands(raw, *commands):
    """Fill the fixture's reserved header padding; never move code/linkedit."""
    value = bytearray(raw)
    count, size = struct.unpack_from("<II", value, 16)
    addition = b"".join(commands)
    if 32 + size + len(addition) > 512:
        raise ValueError("synthetic header padding exhausted")
    value[32 + size:32 + size + len(addition)] = addition
    struct.pack_into("<II", value, 16, count + len(commands), size + len(addition))
    return bytes(value)


def image(route="touch-tv", signed=False, path=LOADER, **kwargs):
    return append_commands(fixtures.binary(route, signed, **kwargs), rpath_command(path))


class TouchTVRpathTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        self.native = mock.patch("subprocess.Popen", side_effect=AssertionError("NO NATIVE")).start()
        self.network = mock.patch("socket.socket", side_effect=AssertionError("NO NETWORK")).start()
        mock.patch("socket.create_connection", side_effect=AssertionError("NO NETWORK")).start()
        mock.patch.dict(os.environ, {}, clear=True).start()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def blocked(self, raw, reason, route="touch-tv", signed=False):
        with self.assertRaisesRegex(policy.Blocked, "^" + reason + "$"):
            ipa.inspect_macho(route, raw, signed)

    def test_exact_touch_main_loader_path_unsigned_signed_continuity(self):
        unsigned = ipa.inspect_macho("touch-tv", image(), False)
        signed = ipa.inspect_macho("touch-tv", image(signed=True), True)
        self.assertEqual(unsigned, signed)
        self.assertEqual(unsigned["rpath_classes"], ["touch_main_loader_frameworks"])
        self.assertEqual(unsigned["metadata"]["kind"], 2)
        self.native.assert_not_called()
        self.network.assert_not_called()

    def test_exact_touch_loader_and_executable_paths_can_coexist(self):
        raw = append_commands(fixtures.binary("touch-tv"), rpath_command(EXECUTABLE), rpath_command(LOADER))
        self.assertEqual(ipa.inspect_macho("touch-tv", raw, False)["rpath_classes"],
                         ["executable_frameworks", "touch_main_loader_frameworks"])

    def test_existing_qr_specific_category_and_continuity_preserved(self):
        unsigned = ipa.inspect_macho("qr-tv", image("qr-tv"), False)
        self.assertEqual(unsigned["rpath_classes"], ["qr_main_loader_frameworks"])
        self.assertEqual(unsigned, ipa.inspect_macho("qr-tv", image("qr-tv", True), True))

    def test_no_other_route_gains_loader_path(self):
        for route in ("touch-vision", "cell-tv", "cell-vision", "qr-vision"):
            for signed in (False, True):
                with self.subTest(route=route, signed=signed):
                    self.blocked(image(route, signed), "rpath_not_allowlisted", route, signed)

    def test_existing_exact_categories_preserved_on_all_routes(self):
        for route in policy.ROUTES:
            for path, category in ((EXECUTABLE, "executable_frameworks"),
                                   (b"@executable_path/../Frameworks", "executable_parent_frameworks"),
                                   (b"/usr/lib/swift", "system_swift")):
                with self.subTest(route=route, path=path):
                    self.assertEqual(ipa.inspect_macho(route, image(route, path=path), False)["rpath_classes"], [category])

    def test_loader_near_matches_traversal_and_nonexact_bytes_rejected(self):
        paths = (b"@loader_path", b"@loader_path/Frameworks/", b"@loader_path/../Frameworks",
                 b"@loader_path/./Frameworks", b"@loader_path//Frameworks", b"@loader_path/Frameworks/..",
                 b"@loader_path/Frameworks/../../outside", b"@loader_path/frameworks",
                 b"@loader_path/Frameworks.evil", b"@loader_path/Frameworks\\..\\outside",
                 b"@loader_path/%46rameworks", b"@loader_path/%2e%2e/Frameworks",
                 b"@loader_path/Frameworks\n", b"@loader_path/Frameworks\xff",
                 b"@rpath/Frameworks", b"/tmp/Frameworks", b"Frameworks", b"")
        for route in ("touch-tv", "qr-tv"):
            for path in paths:
                with self.subTest(route=route, path=path):
                    self.blocked(image(route, path=path), "rpath_not_allowlisted", route)

    def test_dylib_and_bundle_filetypes_remain_rejected_before_rpath(self):
        for route in ("touch-tv", "qr-tv"):
            for kind in (6, 8):
                with self.subTest(route=route, kind=kind):
                    self.blocked(image(route, kind=kind), "macho_platform_mismatch", route)

    def test_architecture_platform_and_versions_remain_exact(self):
        for override in (dict(cpu=0x1000007), dict(platform=2), dict(platform=8),
                         dict(minimum=16 << 16), dict(sdk=26 << 16)):
            with self.subTest(override=override):
                self.blocked(image(**override), "macho_platform_mismatch")

    def test_rpath_offset_boundaries_remain_rejected(self):
        for offset in (0, 8, 11, len(rpath_command(LOADER)), 0xffffffff):
            command = bytearray(rpath_command(LOADER))
            struct.pack_into("<I", command, 8, offset)
            with self.subTest(offset=offset):
                self.blocked(append_commands(fixtures.binary("touch-tv"), bytes(command)), "rpath_invalid")

    def test_rpath_unterminated_command_remains_rejected(self):
        command = bytearray(rpath_command(LOADER))
        command[12:] = b"A" * (len(command) - 12)
        self.blocked(append_commands(fixtures.binary("touch-tv"), bytes(command)), "rpath_invalid")

    def test_rpath_short_command_remains_rejected(self):
        self.blocked(append_commands(fixtures.binary("touch-tv"), struct.pack("<II", 0x8000001c, 8)),
                     "rpath_command_invalid")

    def test_unapproved_rpath_still_rejects_when_approved_path_is_present(self):
        raw = append_commands(fixtures.binary("touch-tv"), rpath_command(LOADER), rpath_command(b"/tmp/evil"))
        self.blocked(raw, "rpath_not_allowlisted")

    def test_signature_states_remain_enforced(self):
        self.blocked(image(signed=True), "unsigned_signature_placeholder_invalid")
        self.blocked(image(), "macho_signature_state_invalid", signed=True)

    def test_non_system_dylib_load_remains_rejected(self):
        name = b"@rpath/Untrusted.dylib\0"
        size = (24 + len(name) + 7) & ~7
        command = (struct.pack("<6I", 0xc, size, 24, 0, 0, 0) + name).ljust(size, b"\0")
        self.blocked(append_commands(image(), command), "non_system_library")

    def test_main_app_inspection_accepts_exact_path(self):
        app = fixtures.make_app(self.root, "touch-tv", mutate=lambda files: files.update(TouchColor=image()))
        observed = ipa.inspect_app("touch-tv", app)
        self.assertEqual(observed["executable_contract"]["rpath_classes"], ["touch_main_loader_frameworks"])
        self.assertFalse(observed["signature_verified"])

    def test_hidden_secondary_executable_remains_rejected(self):
        app = fixtures.make_app(self.root, "touch-tv", mutate=lambda files: files.update({"resource.bin": image()}))
        with self.assertRaisesRegex(policy.Blocked, "hidden_executable_payload"):
            ipa.inspect_app("touch-tv", app)

    def test_nested_framework_remains_rejected(self):
        app = fixtures.make_app(self.root, "touch-tv", mutate=lambda files: files.update({"Frameworks/Evil": image()}))
        with self.assertRaisesRegex(policy.Blocked, "unexpected_code_payload"):
            ipa.inspect_app("touch-tv", app)

    def test_semantically_similar_rpath_change_still_breaks_continuity(self):
        unsigned = ipa.inspect_app("touch-tv", fixtures.make_app(self.root / "u", "touch-tv",
                                  mutate=lambda files: files.update(TouchColor=image())))
        signed = ipa.inspect_app("touch-tv", fixtures.make_app(self.root / "s", "touch-tv", True,
                                mutate=lambda files: files.update(TouchColor=image(signed=True, path=EXECUTABLE))), signed=True)
        self.assertNotEqual(unsigned['executable_contract'], signed['executable_contract'])

    def test_original_load_command_bytes_remain_in_continuity_hash(self):
        original = image()
        changed = bytearray(original)
        _, size = struct.unpack_from("<II", changed, 16)
        changed[32 + size - 1] ^= 1  # Rpath command padding, after its NUL.
        before = ipa.inspect_macho("touch-tv", original, False)
        after = ipa.inspect_macho("touch-tv", bytes(changed), False)
        self.assertEqual(before["rpath_classes"], after["rpath_classes"])
        self.assertNotEqual(before["load_commands"], after["load_commands"])
        self.assertNotEqual(before["image_prefix_sha256"], after["image_prefix_sha256"])



class RunnerTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        import types
        self.addCleanup(mock.patch.stopall)
        mock.patch('subprocess.Popen', side_effect=AssertionError('NO NATIVE')).start()
        mock.patch('socket.socket', side_effect=AssertionError('NO NETWORK')).start()
        self.fake_command = mock.Mock(side_effect=AssertionError('UNMOCKED COMMAND'))
        self.fake_capture = mock.Mock(side_effect=AssertionError('UNMOCKED CAPTURE'))
        self.fake_scan = mock.Mock(return_value={'paths': {}, 'entries': 0, 'bytes': 0})
        originals = types.ModuleType('original_ios_archive')
        originals.command, originals.scan = self.fake_command, self.fake_scan
        capture_module = types.ModuleType('palette_lifecycle_diagnostics')
        capture_module.capture = self.fake_capture
        class CaptureStopped(RuntimeError):
            def __init__(self, reason, cleanup_confirmed):
                super().__init__(reason)
                self.cleanup_confirmed = cleanup_confirmed
        capture_module.CaptureStopped = CaptureStopped
        self.capture_stopped = CaptureStopped
        atomic = types.ModuleType('atomic_json')
        atomic.write_json = lambda path, value, **kwargs: Path(path).write_text(__import__('json').dumps(value))
        with mock.patch.dict(sys.modules, {'original_ios_archive': originals, 'palette_lifecycle_diagnostics': capture_module, 'atomic_json':atomic}):
            spec = importlib.util.spec_from_file_location('tv_rpath_diagnostic_test', Path(__file__).with_name('tv_rpath_diagnostic.py'))
            self.runner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.runner)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        r = self.runner
        r.ROOT, r.WORK = self.root, self.root / 'build/tv-rpath-diagnostic'
        r.ARCHIVE = r.WORK / 'TouchColor.xcarchive'
        r.APP = r.ARCHIVE / 'Products/Applications/TouchColor.app'
        self.env = {'GITHUB_REPOSITORY':'100mango/ColorPicker', 'GITHUB_REF':r.BRANCH,
                    'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/'+r.WORKFLOW+'@'+r.BRANCH,
                    'GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'archive',
                    'GITHUB_ACTOR':'100mango','GITHUB_TRIGGERING_ACTOR':'100mango',
                    'DEVELOPER_DIR':r.DEVELOPER,'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,
                    'GITHUB_RUN_ID':'12345','TV_RPATH_STARTED_MONOTONIC':str(r.time.monotonic())}
        mock.patch.dict(os.environ, self.env, clear=True).start()

    def test_identity_rejects_other_route_attempt_event_and_credentials(self):
        r = self.runner
        self.assertEqual(r.identity()['product_sha'], r.BASE)
        for key, value in (('GITHUB_RUN_ATTEMPT','2'),('GITHUB_REF','refs/heads/main'),
                           ('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_WORKFLOW_SHA','b'*40),
                           ('GITHUB_ACTOR','other'),('APP_STORE_CONNECT_PRIVATE_KEY','SYNTHETIC')):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key:value}):
                with self.assertRaises(ipa.Blocked): r.identity()
        self.fake_command.assert_not_called()
        self.fake_capture.assert_not_called()

    def test_archive_and_child_environment_cannot_sign_or_inherit_secrets(self):
        args = self.runner.archive_argv()
        self.assertEqual(args.count('archive'),1)
        for item in ('CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','CODE_SIGN_IDENTITY=',
                     'DEVELOPMENT_TEAM=','PROVISIONING_PROFILE=','PROVISIONING_PROFILE_SPECIFIER='):
            self.assertIn(item,args)
        for item in ('-exportArchive','-allowProvisioningUpdates','-authenticationKeyPath','-upload-app'):
            self.assertNotIn(item,args)
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN':'SYNTHETIC','DYLD_INSERT_LIBRARIES':'SYNTHETIC'}):
            env = self.runner.safe_command(args)
            self.assertEqual(env[:2],['/usr/bin/env','-i'])
            self.assertFalse(any('SYNTHETIC' in x or 'GITHUB_TOKEN' in x or 'DYLD_INSERT' in x for x in env))

    def test_cleanup_requires_exact_owner_and_rejects_symlink(self):
        r = self.runner
        r.WORK.mkdir(parents=True)
        marker = r.WORK / '.owned.json'
        marker.write_text('{}')
        with self.assertRaisesRegex(ipa.Blocked,'cleanup_owner_mismatch'): r.cleanup(r.identity())
        self.assertTrue(r.WORK.exists())
        marker.write_text(r.json.dumps(r.identity()))
        (r.WORK / '.process-state.json').write_text(r.json.dumps({'binding':r.identity(),'state':'completed'}))
        self.assertTrue(r.cleanup(r.identity()))
        r.WORK.symlink_to(self.root / 'unowned')
        with self.assertRaisesRegex(ipa.Blocked,'cleanup_path_link'): r.cleanup(r.identity())

    def test_source_identity_requires_only_four_new_control_files(self):
        r = self.runner; binding = r.identity()
        values = {('rev-parse','HEAD'):binding['control_sha'], ('rev-parse',r.BASE+'^{tree}'):r.BASE_TREE,
                  ('rev-list','--parents','-n','1','HEAD'):binding['control_sha']+' '+r.BASE,
                  ('diff','--name-status',r.BASE,'HEAD','--'):'\n'.join('A\t'+p for p in r.ADDITIONS),
                  ('status','--porcelain','--untracked-files=all'):'',
                  ('hash-object','TouchColorTV.xcodeproj/project.pbxproj'):'87372c3ab2056ec4fac4ef603e96e0c0bf28e875',
                  ('hash-object','TouchColorTV.xcodeproj/xcshareddata/xcschemes/TouchColorTV.xcscheme'):'60ac5c8f058f07543844cb72b132903b4b27b69f',
                  ('rev-parse','HEAD^{tree}'):'c'*40}
        def run(args,**kwargs): return values[tuple(args[1:])].encode()
        self.assertTrue(r.source_identity(binding,run)['product_unchanged'])
        values[('diff','--name-status',r.BASE,'HEAD','--')]+='\nM\tTouchColorTV.xcodeproj/project.pbxproj'
        with self.assertRaisesRegex(ipa.Blocked,'diagnostic_product_modified'): r.source_identity(binding,run)

    def execute_synthetic(self, path=LOADER, archive_fail=False, uncertain=None, before_spawn=False, no_grant=False):
        import contextlib
        import io
        r=self.runner
        original_cwd=Path.cwd()
        self.addCleanup(os.chdir, original_cwd)
        calls=[]
        def actual_capture(args, **kwargs):
            calls.append(args)
            if '/usr/bin/codesign' in args:
                if uncertain == 'codesign': raise self.capture_stopped('SYNTHETIC_UNCERTAIN',False)
                return SimpleNamespace(returncode=1,stdout=b'',stderr=b'code object is not signed at all')
            output=b'';rc=0
            if '/usr/bin/xcodebuild' in args:
                if '-version' in args: output=b'Xcode 27.0\nBuild version 27A266a\n'
                elif '-showsdks' in args: output=b'appletvos27.0\n'
                else:
                    self.assertIn('archive',args)
                    self.assertEqual(kwargs['seconds'],420)
                    if uncertain == 'archive': raise self.capture_stopped('SYNTHETIC_UNCERTAIN',False)
                    if before_spawn: raise self.capture_stopped('interrupted-before-spawn',True)
                    if archive_fail: rc=1
                    else:
                        make_app(r.ARCHIVE/'Products/Applications','touch-tv',mutate=lambda files:files.update(TouchColor=image(path=path)))
                        (r.ARCHIVE/'Info.plist').write_bytes(plistlib.dumps({'ApplicationProperties':{
                            'ApplicationPath':'Applications/TouchColor.app','CFBundleIdentifier':'com.mango.touchColor',
                            'CFBundleShortVersionString':'2.0.1','CFBundleVersion':'20002'}}))
            elif '/usr/bin/uname' in args: output=b'arm64\n'
            elif '/usr/bin/sw_vers' in args: output=b'27.0\n' if '-productVersion' in args else b'26A428\n'
            elif '/usr/bin/otool' in args: output=('cmd LC_RPATH\n cmdsize 40\n path '+path.decode()+' (offset 12)\n').encode()
            else: raise AssertionError('Unexpected synthetic command')
            return SimpleNamespace(returncode=rc,stdout=output,stderr=b'')
        def checked(args, **kwargs):
            if no_grant and 'archive' in args: raise RuntimeError('SYNTHETIC_ADMISSION_FAILED')
            result=kwargs['runner'](args,seconds=kwargs['seconds'],cap=kwargs['cap'],cleanup_grace=2)
            kwargs['receipts'].append({'complete':result.returncode==0})
            if result.returncode: raise RuntimeError('SYNTHETIC_COMMAND_FAILED')
            return result.stdout
        self.fake_command.side_effect=checked
        self.fake_capture.side_effect=actual_capture
        stream=io.StringIO()
        source=mock.Mock(return_value={'control_tree':'c'*40,'product_unchanged':True})
        with mock.patch.object(r,'source_identity',source), mock.patch.object(sys,'argv',['tv_rpath_diagnostic.py']), contextlib.redirect_stdout(stream):
            code=r.main()
        lines=stream.getvalue().splitlines()
        report=r.json.loads(next(line[len('TV_RPATH_DIAGNOSTIC '):] for line in lines if line.startswith('TV_RPATH_DIAGNOSTIC ')))
        self.assertEqual(r.WORK.exists(),bool(uncertain))
        self.assertEqual(report['cleanup_confirmed'],not bool(uncertain))
        for field in ('signed_export','upload_invoked','release_qualification'): self.assertFalse(report[field])
        return code,report,lines,calls,source

    def test_synthetic_success_records_completed_archive_paths_and_cleanup(self):
        code,report,lines,calls,source=self.execute_synthetic()
        self.assertEqual(code,0)
        self.assertEqual(report['old_verifier'],'rpath_not_allowlisted')
        self.assertEqual(report['fixed_verifier'],'passed')
        self.assertEqual(report['actual_rpaths']['rpaths'][0]['path_utf8'],LOADER.decode())
        self.assertEqual(report['otool_rpaths'],[LOADER.decode()])
        self.assertEqual(report['archive_attempts'],1)
        self.assertEqual(report['archive_execution'],'completed')
        self.assertEqual(report['archive_exit'],0)
        self.assertTrue(any(line.startswith('TV_RPATH_ACTUAL ') for line in lines))

    def test_unapproved_path_remains_visible_and_fails_without_retry(self):
        code,report,lines,calls,source=self.execute_synthetic(path=b'@loader_path/../Frameworks')
        self.assertEqual(code,1)
        self.assertEqual(report['fixed_verifier'],'rpath_not_allowlisted')
        self.assertEqual(report['actual_rpaths']['rpaths'][0]['path_utf8'],'@loader_path/../Frameworks')
        self.assertEqual(report['archive_attempts'],1)
        self.assertFalse(any('/usr/bin/codesign' in args for args in calls))

    def test_completed_nonzero_archive_cleans_without_fabricated_rpaths(self):
        code,report,lines,calls,source=self.execute_synthetic(archive_fail=True)
        self.assertEqual(code,1)
        self.assertNotIn('actual_rpaths',report)
        self.assertEqual(report['archive_exit'],1)
        self.assertEqual(report['archive_execution'],'completed')
        self.assertEqual(source.call_count,1)

    def test_admission_failure_never_claims_archive_started(self):
        code,report,lines,calls,source=self.execute_synthetic(no_grant=True)
        self.assertEqual(code,1)
        self.assertEqual(report['archive_execution'],'not_started')
        self.assertNotIn('archive_exit',report)
        self.assertFalse(any('archive' in args for args in calls))

    def test_capture_before_spawn_is_explicit_and_safely_cleaned(self):
        code,report,lines,calls,source=self.execute_synthetic(before_spawn=True)
        self.assertEqual(code,1)
        self.assertEqual(report['archive_execution'],'not_started')
        self.assertEqual(report['process_state'],'not_started')
        self.assertNotIn('archive_exit',report)
        self.assertEqual(source.call_count,1)

    def check_durable_unknown(self, phase):
        import contextlib,io
        code,report,lines,calls,source=self.execute_synthetic(uncertain=phase)
        self.assertEqual(code,1)
        self.assertEqual(report['process_state'],'uncertain')
        self.assertIn('cleanup_process_ownership_uncertain',report['cleanup_reason'])
        self.assertEqual(source.call_count,1 if phase=='archive' else 2)
        self.assertIn('/usr/bin/xcodebuild' if phase=='archive' else '/usr/bin/codesign',calls[-1])
        state=self.runner.json.loads((self.runner.WORK/'.process-state.json').read_text())
        self.assertEqual(state['state'],'uncertain')
        with mock.patch.object(self.runner.shutil,'rmtree',side_effect=AssertionError('NO CLEANUP')), \
             self.assertRaisesRegex(ipa.Blocked,'cleanup_process_ownership_uncertain'):
            self.runner.cleanup(self.runner.identity())
        out=io.StringIO()
        with mock.patch.object(sys,'argv',['tv_rpath_diagnostic.py','cleanup']), contextlib.redirect_stdout(out), \
             mock.patch.object(self.runner.shutil,'rmtree',side_effect=AssertionError('NO CLEANUP')):
            self.assertEqual(self.runner.main(),1)
        self.assertIn('"confirmed": false',out.getvalue())
        self.assertTrue(self.runner.WORK.exists())
        return report

    def test_uncertain_archive_blocks_cleanup_source_recheck_and_next_step(self):
        report=self.check_durable_unknown('archive')
        self.assertEqual(report['archive_execution'],'cleanup_unknown')
        self.assertNotIn('archive_exit',report)

    def test_uncertain_codesign_blocks_cleanup_final_source_and_next_step(self):
        report=self.check_durable_unknown('codesign')
        self.assertEqual(report['archive_execution'],'completed')
        self.assertNotIn('source_final',report)
if __name__ == "__main__":
    unittest.main(verbosity=2)
