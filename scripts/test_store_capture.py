"""Focused local checks only. No Xcode, simulator, network, or publication."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import subprocess
import os
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import store_capture as capture


def png(width=2, height=3, color=2):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    channels = 4 if color == 6 else 3
    raster = (b'\0' + b'\0' * (width * channels)) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raster)) + chunk(b'IEND', b''))


def fixtures():
    runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'isAvailable': True,
               'version': '27.0', 'buildversion': '24A434'}
    types = [{'name': t['model'], 'identifier': 'com.apple.CoreSimulator.SimDeviceType.' + t['row']}
             for t in capture.TARGETS]
    return {'runtimes': [runtime]}, {'devicetypes': types}, {'devices': {runtime['identifier']: []}}


class StoreCaptureTests(unittest.TestCase):
    def test_source_is_exactly_reversible(self):
        result = capture.verify_source()
        self.assertEqual(result['unchanged_files'], 381)
        self.assertFalse(result['physical_camera_scan_proven'])
        self.assertFalse(result['shipping_release_qualification'])
        self.assertEqual(capture.PUBLIC_PARENT, '459c70bf616e5bb488b2140bc79c72745704a8b4')
        self.assertEqual(capture.PUBLIC_PARENT_TREE, 'bd59eff3932b1dd1d5a055e7d7153870ba2802fd')
        self.assertEqual(capture.CHANGED, {capture.UI_PATH, capture.APP_PATH, capture.DISPLAY_PATH, 'scripts/store_capture.py',
            'scripts/store_capture_process.py', 'scripts/store_capture_source.json',
            'scripts/test_store_capture.py', '.github/workflows/ios-store-screenshots.yml', 'docs/STORE_SCREENSHOTS.md'})

    def test_original_methods_and_projects_unchanged(self):
        contract = json.loads((ROOT / 'scripts/store_capture_source.json').read_text())
        raw = (ROOT / capture.UI_PATH).read_bytes()
        include = raw[raw.index(capture.BEGIN):raw.index(capture.END) + len(capture.END)]
        block = (ROOT / capture.DISPLAY_PATH).read_bytes()
        self.assertEqual(re.findall(rb'- \(void\)(test\w+)', block),
                         [b'testStoreNormalPhotoScreenshot', b'testStoreNormalHistoryScreenshot'])
        self.assertIn(b'@implementation TouchColorStoreCaptureUITests', block)
        self.assertTrue(raw.endswith(include))
        self.assertNotIn(b'testStoreNormal', raw[:-len(include)])
        self.assertIn(b'XCUIScreen.mainScreen.screenshot.PNGRepresentation', block)
        self.assertNotIn(b'UIImageJPEGRepresentation', block)
        self.assertNotIn(b'UIImagePNGRepresentation', block)
        self.assertIn(b'@"(zh-Hans)"', block)
        self.assertIn(b'@"--ui-test-asymmetric"', block)
        self.assertIn(b'@"--ui-test-store-capture"', block)
        self.assertEqual(len(contract['files']), 383)

    def test_fixed_owned_models_and_dimensions(self):
        selected = capture.select_devices(*fixtures())
        self.assertEqual([t['model'] for t in selected], ['iPhone 17 Pro', 'iPad Pro 13-inch (M5)'])
        self.assertEqual([t['pixels'] for t in selected], [[1206, 2622], [2064, 2752]])
        self.assertEqual([t['capture_labels'] for t in selected], [['photo', 'history'], ['photo', 'history']])
        self.assertEqual(sum(len(t['capture_labels']) for t in selected), 4)

    def test_missing_model_or_ambiguous_runtime_fails(self):
        r, t, d = fixtures()
        t['devicetypes'].pop()
        with self.assertRaises(ValueError): capture.select_devices(r, t, d)
        r, t, d = fixtures()
        r['runtimes'].append(dict(r['runtimes'][0]))
        with self.assertRaises(ValueError): capture.select_devices(r, t, d)

    def test_wrong_runtime_or_busy_host_fails(self):
        r, t, d = fixtures()
        r['runtimes'][0]['buildversion'] = 'unknown'
        with self.assertRaises(ValueError): capture.select_devices(r, t, d)
        r, t, d = fixtures()
        next(iter(d['devices'].values())).append({'state': 'Booted'})
        with self.assertRaises(ValueError): capture.select_devices(r, t, d)

    def test_png_original_rgb_and_alpha_reported(self):
        metadata = capture.png_metadata(png())
        self.assertFalse(metadata['has_alpha_channel_or_transparency'])
        self.assertFalse(metadata['resized'])
        self.assertFalse(metadata['reencoded'])
        self.assertTrue(capture.png_metadata(png(color=6))['has_alpha_channel_or_transparency'])

    def test_png_crc_truncation_trailing_data_fail(self):
        data = png()
        broken = bytearray(data); broken[40] ^= 1
        for value in (bytes(broken), data[:-3], data + b'bad', b'JPEG'):
            with self.subTest(value=value[:8]), self.assertRaises(ValueError): capture.png_metadata(value)

    def attachment(self, directory, target, owner=None, duplicate=False):
        data = png(*target['pixels'])
        (directory / 'raw.png').write_bytes(data)
        item = {'suggestedHumanReadableName': 'touchcolor-store-photo', 'exportedFileName': 'raw.png',
                'deviceId': target['udid']}
        row = {'testIdentifier': owner or 'TouchColorStoreCaptureUITests/testStoreNormalPhotoScreenshot()',
               'attachments': [item, item] if duplicate else [item]}
        (directory / 'manifest.json').write_text(json.dumps([row]))
        return data

    def test_exact_attachment_raw_bytes_and_owner(self):
        target = {**capture.TARGETS[0], 'udid': '11111111-1111-1111-1111-111111111111'}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); data = self.attachment(folder, target)
            (selected, metadata), _ = capture.select_png(folder, target, 'photo')
            self.assertEqual(selected, data)
            self.assertEqual(metadata['sha256'], capture.sha(data))
            self.attachment(folder, target, owner='TouchColorUITests/testScannedTextPersistsAcrossRelaunchAndBackground()')
            with self.assertRaises(ValueError): capture.select_png(folder, target, 'photo')

    def test_attachment_duplicate_foreign_device_path_and_dimensions_reject(self):
        target = {**capture.TARGETS[0], 'udid': '11111111-1111-1111-1111-111111111111'}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.attachment(folder, target, duplicate=True)
            with self.assertRaises(ValueError): capture.select_png(folder, target, 'photo')
            self.attachment(folder, target)
            with self.assertRaises(ValueError): capture.select_png(folder, {**target, 'udid': 'foreign'}, 'photo')
            with self.assertRaises(ValueError): capture.select_png(folder, {**target, 'pixels': [1179, 2556]}, 'photo')
            value = json.loads((folder / 'manifest.json').read_text())
            value[0]['attachments'][0]['exportedFileName'] = '../raw.png'
            (folder / 'manifest.json').write_text(json.dumps(value))
            with self.assertRaises(ValueError): capture.select_png(folder, target, 'photo')

    def test_strict_json_duplicate_nonfinite_reject(self):
        for raw in ('{"x": 1, "x": 2}', '{"x": NaN}'):
            with self.assertRaises(ValueError): capture.load_json(raw)

    def test_prior_png_survives_later_failure_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = capture.Capture.__new__(capture.Capture); runner.packet = Path(tmp)
            data = png(); runner.retain('iphone-17-pro-photo.png', data)
            runner.retain_json('failure.json', {'error': 'later stage failed'})
            with self.assertRaises(FileExistsError): runner.retain('iphone-17-pro-photo.png', b'replacement')
            with patch.object(capture, 'MAX_PACKET', len(data)):
                with self.assertRaises(ValueError): runner.retain('later.log', b'new')
            self.assertEqual((runner.packet / 'iphone-17-pro-photo.png').read_bytes(), data)

    def test_upload_accepts_real_retained_empty_command_log_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = capture.Capture.__new__(capture.Capture)
            runner.packet = Path(tmp) / 'touchcolor-store-evidence'
            runner.packet.mkdir()
            runner.retain('source-clean.log', b'')
            runner.retain_json('source-clean-command.json', {'state': 'completed', 'exit': 0, 'output_bytes': 0})
            self.assertEqual((runner.packet / 'source-clean.log').stat().st_size, 0)
            with patch.dict(capture.os.environ, {'RUNNER_TEMP': tmp}):
                capture.upload_admission()
                for name in ('empty.json', 'manifest.json', 'iphone-17-pro-photo.png'):
                    with self.subTest(name=name):
                        runner.retain(name, b'')
                        with self.assertRaises(ValueError): capture.upload_admission()
                        (runner.packet / name).unlink()
                (runner.packet / 'unsafe.log').symlink_to(runner.packet / 'source-clean.log')
                with self.assertRaises(ValueError): capture.upload_admission()

    def test_full_allowance_and_uncertainty_prevent_dispatch(self):
        runner = capture.Capture.__new__(capture.Capture); runner.clock = {'started': 1}
        with patch.object(capture, 'blocked', return_value=False), patch.object(capture.time, 'monotonic', return_value=2690), patch.object(capture, 'execute') as execute:
            with self.assertRaises(ValueError): runner.command('denied', ['xcrun'], 30)
            execute.assert_not_called()
        with patch.object(capture, 'blocked', return_value=True), patch.object(capture, 'execute') as execute:
            with self.assertRaises(ValueError): runner.command('denied', ['xcrun'], 30)
            execute.assert_not_called()

    def test_summary_is_one_case_exact_device_and_window(self):
        target = {**capture.TARGETS[0], 'udid': '11111111-1111-1111-1111-111111111111'}
        value = {'result': 'Passed', 'totalTestCount': 1, 'passedTests': 1, 'failedTests': 0,
                 'skippedTests': 0, 'expectedFailures': 0, 'testFailures': [], 'runtimeWarnings': [],
                 'startTime': 10.1, 'finishTime': 11.1, 'devicesAndConfigurations': [{'device': {
                    'deviceId': target['udid'], 'modelName': target['model'], 'osVersion': '27.0',
                    'osBuildNumber': '24A434', 'architecture': 'arm64', 'platform': 'iOS Simulator'}}]}
        capture.verify_summary(value, target, 10, 12)
        for key, bad in [('totalTestCount', True), ('passedTests', 2), ('startTime', 9), ('finishTime', float('nan'))]:
            other = copy.deepcopy(value); other[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): capture.verify_summary(other, target, 10, 12)

    def test_workflow_one_mac_job_and_no_store_operation(self):
        import yaml
        value = yaml.safe_load((ROOT / '.github/workflows/ios-store-screenshots.yml').read_text())
        self.assertEqual(list(value['jobs']), ['capture'])
        job = value['jobs']['capture']
        self.assertEqual(job['runs-on'], 'xcode-27')
        self.assertNotIn('strategy', job)
        self.assertEqual(value['permissions'], {'contents': 'read'})
        text = (ROOT / 'scripts/store_capture.py').read_text()
        self.assertNotIn('sips', text)
        self.assertNotIn('altool', text)
        self.assertNotIn('notarytool', text)
        self.assertNotIn('git push', text)
        self.assertIn("600 if index == 0 else 420", text)
        self.assertIn("['git', 'diff', '--name-only', PUBLIC_PARENT, 'HEAD']", text)
        self.assertIn("(2940 if tail else 2700)", text)
        self.assertIn("time.monotonic() + cap + 20 < endpoint", text)
        self.assertIn("'-maximum-test-execution-time-allowance', '240'", text)
        ui = (ROOT / capture.DISPLAY_PATH).read_text()
        result_body = ui.split('- (void)testStoreNormalPhotoScreenshot {', 1)[1].split('\n}', 1)[0]
        self.assertIn('self.executionTimeAllowance = 180;', result_body)
        self.assertEqual(job['timeout-minutes'], 60)

    def test_debug_only_button_removal_and_exact_restoration(self):
        raw = (ROOT / capture.APP_PATH).read_bytes()
        start, end = raw.index(capture.APP_BEGIN), raw.index(capture.APP_END) + len(capture.APP_END)
        block = raw[start:end]
        self.assertIn(b'@"--ui-test-store-capture"', block)
        self.assertIn(b'self.navigationItem.leftBarButtonItem = nil;', block)
        self.assertNotIn(b'showImage:', block)
        self.assertNotIn(b'NSUserDefaults', block)
        original = raw[:start] + raw[end:]
        row = next(row for row in json.loads((ROOT / 'scripts/store_capture_source.json').read_text())['files'] if row['path'] == capture.APP_PATH)
        self.assertEqual(capture.sha(original), row['sha256'])
        self.assertEqual(raw[end:].splitlines()[0], b'    [self showImage:image];')
        self.assertGreater(raw[:start].rfind(b'#if DEBUG'), raw[:start].rfind(b'#endif'))

    def test_release_cpp_projection_identical_ignoring_only_blank_physical_lines(self):
        raw = (ROOT / capture.APP_PATH).read_bytes()
        start, end = raw.index(capture.APP_BEGIN), raw.index(capture.APP_END) + len(capture.APP_END)
        original = raw[:start] + raw[end:]
        # Actual host C preprocessor, with header directives removed identically
        # from both inputs because this portable check has no Apple SDK. No string
        # content, nonblank line or nonblank token normalization is permitted.
        def preprocess(source, debug):
            prepared = re.sub(rb'^#import [^\n]+$', b'', source, flags=re.M)
            result = subprocess.run(['cc','-E','-P','-x','c','-DDEBUG='+str(debug),'-'],
                input=prepared, capture_output=True, timeout=10, check=True).stdout
            return b'\n'.join(line for line in result.splitlines() if line.strip())
        self.assertEqual(preprocess(original,0), preprocess(raw,0))
        self.assertNotIn(b'--ui-test-store-capture', preprocess(raw,0))
        self.assertNotIn(b'openFixture', preprocess(raw,0))
        self.assertIn(b'--ui-test-store-capture', preprocess(raw,1))

    def test_existing_real_sampling_save_and_chinese_normal_ui(self):
        block = (ROOT / capture.DISPLAY_PATH).read_text()
        self.assertIn('coordinateWithNormalizedOffset:CGVectorMake(x,y)', block)
        self.assertIn('XCTAssertEqualObjects(self.app.staticTexts[@"sampledColor"].label', block)
        self.assertIn('XCTAssertEqualWithAccuracy(CGRectGetMidX(position)', block)
        self.assertIn('XCTAssertEqualWithAccuracy(CGRectGetMidY(position)', block)
        self.assertIn('XCTAssertEqual(history.cells.count, 3);', block)
        self.assertIn('@"#ff0000, R 255   G 0   B 0"', block)
        self.assertIn('@"#0000ff, R 0   G 0   B 255"', block)
        self.assertIn('@"#ff00ff, R 255   G 0   B 255"', block)
        self.assertEqual(block.count('[self storeSave];'), 3)
        self.assertIn('@"UICTContentSizeCategoryL"', block)
        self.assertIn('@"中心取色"', block)
        self.assertIn('XCTAssertEqual(XCUIDevice.sharedDevice.orientation, UIDeviceOrientationPortrait);', block)
        self.assertIn('XCTAssertFalse(self.app.buttons[@"Sample Fixture"].exists);', block)
        for forbidden in ('UIPasteboard', 'NSUserDefaults', 'setValue:', 'sampleCenter"] tap', 'Photos', 'Largest'):
            self.assertNotIn(forbidden, block)

    def test_exif_orientation_is_read_not_rewritten(self):
        def exif(value):
            return b'II' + struct.pack('<HIH',42,8,1) + struct.pack('<HHIH',274,3,1,value) + b'\0\0' + struct.pack('<I',0)
        def with_exif(data, payload):
            kind = b'eXIf'
            chunk = struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
            return data[:33]+chunk+data[33:]
        for orientation in (1,6,8):
            data = with_exif(png(),exif(orientation))
            self.assertEqual(capture.png_metadata(data)['exif_orientation'],orientation)
            self.assertEqual(capture.png_metadata(data)['sha256'],capture.sha(data))
        for bad in (b'',b'garbage',exif(1)[:-3]):
            with self.assertRaises(ValueError): capture.png_metadata(with_exif(png(),bad))

    def test_file_read_rejects_hardlinks_symlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);path=folder/'input';path.write_bytes(b'bytes')
            self.assertEqual(capture.read_file(path,5),b'bytes')
            with self.assertRaises(ValueError): capture.read_file(path,4)
            link=folder/'linked';link.symlink_to(path)
            with self.assertRaises(ValueError): capture.read_file(link,5)
            link.unlink();os.link(path,link)
            with self.assertRaises(ValueError): capture.read_file(path,5)

    def test_capture_retained_before_summary_and_rgb_upright_admission(self):
        source=(ROOT/'scripts/store_capture.py').read_text()
        retained=source.index("self.retain(stem + '.png', data)")
        summarized=source.index("summary = self.json_command(stem + '-summary'")
        admission=source.index("metadata['color_type'] == 2")
        self.assertLess(retained,summarized)
        self.assertLess(summarized,admission)
        self.assertIn("metadata['bit_depth'] == 8",source)
        self.assertIn("metadata['exif_orientation'] in (None, 1)",source)
        self.assertIn("os.environ['TEST_RUNNER_TOUCHCOLOR_STORE_CAPTURE'] = '1'",source)
        self.assertNotIn('QRCATCHER',source)
        self.assertNotIn('materialize_qr',source)
        self.assertNotIn('addmedia',source)

    def test_exact_product_identity_and_bytes(self):
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/'TouchColor.app';app.mkdir()
            info={'CFBundleIdentifier':'com.mango.touchColor','CFBundleShortVersionString':'2.0',
                'CFBundleVersion':'20001','DTPlatformName':'iphonesimulator','UIDeviceFamily':[1,2]}
            (app/'Info.plist').write_bytes(plistlib.dumps(info));(app/'TouchColor').write_bytes(b'test-product')
            manifest=capture.product_manifest(app)
            self.assertEqual(manifest['bundle_id'],'com.mango.touchColor')
            self.assertEqual(manifest['version'],'2.0')
            (app/'TouchColor').write_bytes(b'changed')
            self.assertNotEqual(capture.product_manifest(app),manifest)
            info['CFBundleVersion']='other';(app/'Info.plist').write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError): capture.product_manifest(app)

    def test_process_failure_marks_durable_barrier(self):
        import store_capture_process as process
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'GITHUB_WORKSPACE':tmp},clear=False):
            os.environ.pop('TOUCHCOLOR_STORE_STOP',None)
            self.assertFalse(process.blocked())
            process.mark_unconfirmed({'cleanup_confirmed':False,'state':'cleanup_unconfirmed'})
            self.assertTrue(process.blocked())
            os.environ.pop('TOUCHCOLOR_STORE_STOP',None)
            self.assertTrue(process.blocked())
            self.assertTrue(process.barrier_path().is_file())

    def test_capture_class_is_compile_time_isolated_and_assertions_preprocess(self):
        from test_ios_offline_privacy import assertion_calls, preprocess_assertion_arguments
        block=(ROOT/capture.DISPLAY_PATH).read_text()
        calls=assertion_calls(block)
        self.assertEqual(len(calls),39)
        self.assertEqual(len(preprocess_assertion_arguments(calls)),len(calls))
        source=(ROOT/capture.UI_PATH).read_text()
        include=source[source.index(capture.BEGIN.decode()):]
        self.assertIn('#if defined(TOUCHCOLOR_STORE_CAPTURE) && TOUCHCOLOR_STORE_CAPTURE',include)
        def preprocess(enabled):
            flags=['-DTOUCHCOLOR_STORE_CAPTURE=1'] if enabled else []
            return subprocess.run(['cc','-E','-P','-x','c','-I',str(ROOT/'TouchColorUITests'),*flags,'-'],
                input=include,text=True,capture_output=True,timeout=10,check=True).stdout
        self.assertNotIn('TouchColorStoreCaptureUITests',preprocess(False))
        self.assertIn('@implementation TouchColorStoreCaptureUITests',preprocess(True))
        self.assertEqual(len(re.findall(r'-\s*\(void\)\s*(test\w+)\s*\{',source)),17)
        self.assertIn('GCC_PREPROCESSOR_DEFINITIONS=$(inherited) TOUCHCOLOR_STORE_CAPTURE=1',
            (ROOT/'scripts/store_capture.py').read_text())


if __name__ == '__main__':
    unittest.main()
