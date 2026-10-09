"""Portable byte/provenance/selection tests; no native screenshot execution claim."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib
from unittest.mock import patch

import retain_mac_evidence as keep

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {'sha': 'a' * 40, 'tree': 'b' * 40, 'workflow_sha': 'a' * 40, 'run_id': '1',
          'run_attempt': '1', 'job': 'native-platform', 'tracked_source_clean': True,
          'workflow_file_sha256': 'c' * 64, 'test_file_sha256': 'd' * 64,
          'repository': '100mango/ColorPicker', 'ref': 'refs/heads/platform-integration',
          'workflow_ref': '100mango/ColorPicker/.github/workflows/apple-platforms.yml@refs/heads/platform-integration',
          'workflow_file': '.github/workflows/apple-platforms.yml', 'event_name': 'push'}
DEVICE = 'actual-mac-device'


def png(size=1000):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'tEXt', b'fixture\0' + b'x' * size) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b''))


class Fixture:
    def __init__(self, root, *, image_size=1000, hierarchy_size=1000):
        self.root = root; self.groups = {folder: [] for folder in keep.FOLDERS}; self.images = {}; self.raw = {}
        summary = {'result': 'Failed', 'passedTests': 6, 'failedTests': 3, 'skippedTests': 1, 'totalTestCount': 10,
                   'startTime': 0, 'finishTime': 1000,
                   'devicesAndConfigurations': [{'device': {'deviceId': DEVICE, 'platform': 'macOS', 'architecture': 'arm64', 'osVersion': '27.0'},
                                                 'testPlanConfiguration': {'configurationName': 'Test Scheme Action'}}],
                   'testFailures': [{'failureText': 'Raw contrast failure remains failed'}]}
        for name in keep.REQUIRED_ROOT:
            (root / name).write_bytes(json.dumps(summary).encode() if name.endswith('.json') else b'Original architecture result')
        for folder in keep.FOLDERS: (root / folder).mkdir()
        for index, (state, method) in enumerate(keep.REQUESTED.items()):
            audit = str(uuid.uuid4()).upper(); group = {'testIdentifier': 'TouchColorMacUITests/' + method + '()',
                'testIdentifierURL': 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/' + method, 'attachments': []}
            self.groups['screenshots'].append(group)
            image = png(image_size); when = index * 30 + 10
            name = self.add(group, keep.FRAME_PREFIX + audit, image, '.png', when + 1)
            self.images[state] = name
            proof = {'schema': 1, 'auditID': audit, 'state': state, 'testName': '-[TouchColorMacUITests ' + method + ']',
                     'capturePhase': 'immediately before audit', 'sequential': True, 'sandbox': False,
                     'imageName': keep.FRAME_PREFIX + audit, 'pngSHA256': keep.digest(image), 'pngBytes': len(image),
                     'capturedAt': when, 'appExecutableSHA256': 'e' * 64, 'appLogicSHA256': 'f' * 64}
            self.add(group, keep.PROOF_PREFIX + audit, json.dumps(proof).encode(), '.txt', when + 2)
            prefix = ('State: ' + state + '\nAudit-ID: ' + audit + '\nIssue: Contrast failed\nElement: actual identifier and frame').encode()
            self.add(group, 'Native Mac accessibility issue', prefix + b'\nHierarchy:' + b'h' * hierarchy_size, '.txt', when + 4)
            self.add(group, keep.SUMMARY_PREFIX + audit, ('Audit-ID: ' + audit + '\nState: ' + state + '\nIssues: 1\nRecorded failures: 1').encode(), '.txt', when + 5)
        self.save()

    def add(self, group, title, data, suffix, when, folder='screenshots'):
        name = str(uuid.uuid4()).upper() + suffix
        meta = {'configurationName': 'Test Scheme Action', 'deviceId': DEVICE, 'deviceName': 'My Mac',
                'exportedFileName': name, 'isAssociatedWithFailure': False,
                'suggestedHumanReadableName': title + '_0_' + str(uuid.uuid4()).upper() + suffix, 'timestamp': when}
        group['attachments'].append(meta); (self.root / folder / name).write_bytes(data)
        self.raw[folder + '/' + name] = data
        return folder + '/' + name

    def save(self):
        for folder, groups in self.groups.items(): (self.root / folder / 'manifest.json').write_text(json.dumps(groups))

    def proof(self, state):
        index = list(keep.REQUESTED).index(state); group = self.groups['screenshots'][index]
        record = next(item for item in group['attachments'] if item['suggestedHumanReadableName'].startswith(keep.PROOF_PREFIX))
        path = self.root / 'screenshots' / record['exportedFileName']
        return group, record, path, json.loads(path.read_bytes())


class RetentionTests(unittest.TestCase):
    def setUp(self):
        # Portable fixtures are synthetic even when CI exports a real source SHA.
        environment = patch.dict(os.environ, {'GITHUB_SHA': '', 'GITHUB_OUTPUT': '',
                                             'TOUCHCOLOR_JOB_PLATFORM': 'mac', 'TOUCHCOLOR_VISION_CASE': ''})
        environment.start(); self.addCleanup(environment.stop)

    def test_guard_rejects_a_packet_from_another_ci_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); Fixture(root); keep.retain(root, SOURCE)
            with patch.dict(os.environ, {'GITHUB_SHA': '0' * 40}):
                with self.assertRaisesRegex(ValueError, 'another source'): keep.validate_selection(root)

    def test_original_requested_pngs_precede_optional_hierarchy_and_other_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root, image_size=350000, hierarchy_size=220000)
            for i in range(8):
                group = {'testIdentifier': 'context' + str(i), 'attachments': []}; fixture.groups['sandbox-screenshots'].append(group)
                fixture.add(group, 'Native Mac contextual screen', png(300000), '.png', 300+i, 'sandbox-screenshots')
            fixture.save(); outcomes = (root / 'mac-ui-summary.json').read_bytes()
            result = keep.retain(root, SOURCE)
            self.assertTrue(result['complete']); keep.validate_selection(root, require_complete=True)
            for name in fixture.images.values(): self.assertEqual((root / name).read_bytes(), fixture.raw[name])
            self.assertEqual((root / 'mac-ui-summary.json').read_bytes(), outcomes)
            self.assertLessEqual(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()), keep.LIMIT - keep.RESERVE)
            texts = [name for name, data in fixture.raw.items() if b'\nHierarchy:' in data]
            self.assertTrue(any((root/name).read_bytes() != fixture.raw[name] for name in texts))
            for name in texts: self.assertTrue((root/name).read_bytes().startswith(fixture.raw[name].partition(b'\nHierarchy:')[0]))

    def test_oversized_one_does_not_delete_other_four_and_completeness_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root); state = next(iter(keep.REQUESTED))
            group, meta, path, proof = fixture.proof(state)
            image = png(keep.MAX_PNG); (root / fixture.images[state]).write_bytes(image)
            proof.update(pngBytes=len(image), pngSHA256=keep.digest(image)); path.write_text(json.dumps(proof))
            result = keep.retain(root, SOURCE)
            self.assertFalse(result['complete']); self.assertEqual(result['requested'][state]['status'], 'omitted')
            self.assertEqual(len(list((root/'screenshots').glob('*.png'))), 4)
            keep.validate_selection(root)
            with self.assertRaises(ValueError): keep.validate_selection(root, require_complete=True)
            omitted = [a for g in json.loads((root/'screenshots/manifest.json').read_bytes()) for a in g['omittedAttachments']]
            self.assertEqual(len(omitted), 1); self.assertIn('500000', omitted[0]['omissionReason'])
            self.assertEqual(omitted[0]['retention']['sourceSHA256'], keep.digest(image))

    def test_missing_invalid_or_duplicate_correlation_never_infers_state_from_filename(self):
        for kind in ('hash', 'test', 'lane', 'time', 'device', 'missing-frame', 'duplicate'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); state = next(iter(keep.REQUESTED))
                group, meta, path, proof = fixture.proof(state)
                if kind == 'hash': proof['pngSHA256'] = '0' * 64
                elif kind == 'test': proof['testName'] = 'foreign'
                elif kind == 'lane': proof['sandbox'] = True
                elif kind == 'time': proof['capturedAt'] = 900
                elif kind == 'device': meta['deviceId'] = 'foreign'
                elif kind == 'missing-frame':
                    filename=fixture.images[state].split('/',1)[1]
                    group['attachments']=[item for item in group['attachments'] if item['exportedFileName']!=filename]
                    (root/fixture.images[state]).unlink()
                else: fixture.add(group, meta['suggestedHumanReadableName'], json.dumps(proof).encode(), '.txt', meta['timestamp'])
                path.write_text(json.dumps(proof)); fixture.save()
                result = keep.retain(root, SOURCE)
                self.assertFalse(result['complete']); self.assertNotEqual(result['requested'][state]['status'], 'retained')
                self.assertFalse((root / fixture.images[state]).exists())

    def test_runtime_identity_requires_observed_exact_class_and_method(self):
        state='empty workspace';method=keep.REQUESTED[state]
        wrong_names=[
            '-[TouchColorMacUITests.TouchColorMacUITests '+method+']',
            '-[ForeignModule.TouchColorMacUITests '+method+']',
            '-[ForeignClass '+method+']',
            '-[TouchColorMacUITests testOfficialAccessibilityCameraAndPrivacy]',
            'prefix-[TouchColorMacUITests '+method+']',
            '-[TouchColorMacUITests '+method+']suffix',
        ]
        for name in wrong_names:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);fixture=Fixture(root);_,_,proof_path,proof=fixture.proof(state)
                self.assertEqual(proof['testName'],'-[TouchColorMacUITests '+method+']')
                proof['testName']=name;proof_path.write_text(json.dumps(proof))
                result=keep.retain(root,SOURCE)
                self.assertFalse(result['complete'])
                self.assertNotEqual(result['requested'][state]['status'],'retained')
        # The positive fixture uses the exact runtime string observed in f977,
        # while existing tests independently bind URL, method, source, device,
        # timestamp, image hash, and complete audit counters.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fixture=Fixture(root)
            for observed_state,observed_method in keep.REQUESTED.items():
                self.assertEqual(fixture.proof(observed_state)[3]['testName'],
                                 '-[TouchColorMacUITests '+observed_method+']')
            self.assertTrue(keep.retain(root,SOURCE)['complete'])
            keep.validate_selection(root,require_complete=True)

    def test_raw_prefix_hashes_and_full_original_hashes_survive_hierarchy_omission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root, image_size=480000, hierarchy_size=240000)
            keep.retain(root, SOURCE)
            for group in json.loads((root/'screenshots/manifest.json').read_bytes()):
                for item in group['attachments']:
                    name = 'screenshots/' + item['exportedFileName']; original = fixture.raw[name]; facts = item['retention']
                    self.assertEqual(facts['sourceSHA256'], keep.digest(original))
                    self.assertEqual(facts['sourceBytes'], len(original))
                    if b'\nHierarchy:' in original:
                        prefix, marker, hierarchy = original.partition(b'\nHierarchy:')
                        self.assertEqual(facts['rawPrefixSHA256'], keep.digest(prefix))
                        self.assertEqual(facts['hierarchySHA256'], keep.digest(marker+hierarchy))
                        self.assertEqual((root/name).read_bytes()[:len(prefix)], prefix)
            keep.validate_selection(root, require_complete=True)

    def test_missing_root_result_is_explicit_and_cannot_claim_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); Fixture(root); (root/'mac-sandbox-summary.json').unlink()
            result = keep.retain(root, SOURCE)
            self.assertEqual(result['missingMandatory'], ['mac-sandbox-summary.json'])
            self.assertFalse(result['complete'])
            self.assertEqual(len(list((root/'screenshots').glob('*.png'))), 5)

    def test_mandatory_overflow_fails_before_deleting_any_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root); (root/'architecture.txt').write_bytes(b'x' * 2_980_000)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError, 'Mandatory'): keep.retain(root, SOURCE)
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_unsafe_paths_symlinks_duplicates_and_unmanifested_files_fail(self):
        for kind in ('traversal', 'symlink', 'duplicate', 'unmanifested'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); group = fixture.groups['screenshots'][0]
                if kind == 'traversal': group['attachments'][0]['exportedFileName'] = '../outside.png'; fixture.save()
                elif kind == 'symlink':
                    p = root / fixture.images[next(iter(keep.REQUESTED))]; p.unlink(); p.symlink_to('/tmp')
                elif kind == 'duplicate': group['attachments'].append(copy.deepcopy(group['attachments'][0])); fixture.save()
                else: (root/'screenshots'/str(uuid.uuid4())).write_text('unmanifested')
                with self.assertRaises(ValueError): keep.retain(root, SOURCE)

    def test_missing_referenced_proof_or_raw_issue_cannot_pass_either_guard(self):
        for title in (keep.PROOF_PREFIX, 'Native Mac accessibility issue_0_'):
            with self.subTest(title=title), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); Fixture(root); keep.retain(root, SOURCE)
                manifest = root/'screenshots/manifest.json'; groups = json.loads(manifest.read_bytes())
                victim = next(item for item in groups[0]['attachments'] if item['suggestedHumanReadableName'].startswith(title))
                (root/'screenshots'/victim['exportedFileName']).unlink(); groups[0]['attachments'].remove(victim)
                manifest.write_text(json.dumps(groups))
                with self.assertRaises(ValueError): keep.validate_selection(root, require_complete=True)
                outcome = subprocess.run([sys.executable, str(ROOT/'scripts/validate_evidence.py'), str(root), str(keep.LIMIT)], capture_output=True)
                self.assertNotEqual(outcome.returncode, 0)

    def test_millisecond_export_rounding_is_accepted_but_large_skew_is_not(self):
        for fraction, expected in ((0.0004, True), (0.1, False)):
            with self.subTest(fraction=fraction), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); state = next(iter(keep.REQUESTED))
                _, _, path, proof = fixture.proof(state); proof['capturedAt'] += 1 + fraction; path.write_text(json.dumps(proof))
                result = keep.retain(root, SOURCE)
                self.assertEqual(result['complete'], expected)

    def test_over_five_megabyte_optional_image_is_omitted_without_aborting_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root)
            group = {'testIdentifier': 'context', 'attachments': []}; fixture.groups['sandbox-screenshots'].append(group)
            data = png(keep.MAX_SOURCE + 1)
            name = fixture.add(group, 'Native Mac optional oversized context', data, '.png', 999, 'sandbox-screenshots'); fixture.save()
            result = keep.retain(root, SOURCE)
            self.assertTrue(result['complete']); keep.validate_selection(root, require_complete=True)
            self.assertFalse((root/name).exists()); self.assertEqual(len(list((root/'screenshots').glob('*.png'))), 5)
            self.assertEqual(result['attachmentInventory'][name]['sourceSHA256'], keep.digest(data))
            omitted = json.loads((root/'sandbox-screenshots/manifest.json').read_bytes())[0]['omittedAttachments'][0]
            self.assertIn('bounded source', omitted['omissionReason'])

    def test_pixel_root_and_prefix_tampering_rejected(self):
        for kind in ('pixel', 'root', 'prefix'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); fixture = Fixture(root); keep.retain(root, SOURCE)
                if kind == 'pixel': path = root / next(iter(fixture.images.values()))
                elif kind == 'root': path = root / 'mac-ui-summary.json'
                else: path = next(p for p in (root/'screenshots').glob('*.txt') if p.read_bytes().startswith(b'State:'))
                path.write_bytes(path.read_bytes() + b'changed')
                with self.assertRaises(ValueError): keep.validate_selection(root)

    def test_independent_upload_guard_accepts_safe_incomplete_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture = Fixture(root)
            group, meta, path, proof = fixture.proof(next(iter(keep.REQUESTED))); proof['pngSHA256'] = '0' * 64; path.write_text(json.dumps(proof))
            keep.retain(root, SOURCE)
            result = subprocess.run([sys.executable, str(ROOT/'scripts/validate_evidence.py'), str(root), str(keep.LIMIT)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, str(ROOT/'scripts/retain_mac_evidence.py'), str(root), '--require-complete'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(list((root/'screenshots').glob('*.png'))), 4)

    def test_guard_emits_boolean_only_after_all_checks_and_builtin_fails_missing(self):
        workflow = (ROOT/'.github/workflows/apple-platforms.yml').read_text()
        post = workflow.split('- name: Require requested Mac audit pixels', 1)[1].split('\n      - name:', 1)[0]
        self.assertIn('MAC_EVIDENCE_COMPLETE: ${{ steps.evidence_guard.outputs.mac_evidence_complete }}', post)
        self.assertNotIn('python3', post)
        command = post.split('run: ', 1)[1].strip()
        self.assertEqual(command, 'test "$MAC_EVIDENCE_COMPLETE" = true')
        for value, expected in [('true', 0), ('false', 1), ('', 1), ('true\nexit 0', 1)]:
            result = subprocess.run(['bash', '-c', command], env={**os.environ, 'MAC_EVIDENCE_COMPLETE': value}, timeout=2)
            self.assertEqual(result.returncode, expected)
        for state in ('complete', 'incomplete', 'tampered', 'absent'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); root = base/'evidence'; root.mkdir(); output = base/'step-output'
                fixture = Fixture(root)
                if state == 'incomplete':
                    _, _, path, proof = fixture.proof(next(iter(keep.REQUESTED)))
                    proof['pngSHA256'] = '0' * 64; path.write_text(json.dumps(proof))
                if state != 'absent': keep.retain(root, SOURCE)
                else:
                    shutil.rmtree(root); root.mkdir(); (root/'architecture.txt').write_text('bounded fallback metadata')
                if state == 'tampered': (root/'mac-ui-summary.json').write_text('changed')
                result = subprocess.run([sys.executable, str(ROOT/'scripts/validate_evidence.py'), str(root), str(keep.LIMIT)],
                                        env={**os.environ, 'GITHUB_OUTPUT': str(output)}, capture_output=True, text=True, timeout=5)
                if state == 'tampered':
                    self.assertNotEqual(result.returncode, 0); self.assertFalse(output.exists())
                elif state == 'absent':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), 'vision_offline_qualified=true\n') # No Mac completeness output.
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), 'mac_evidence_complete=' + ('true' if state == 'complete' else 'false') + '\nvision_offline_qualified=true\n')

    def test_synthetic_mac_scope_isolated_from_all_live_lane_environments(self):
        for platform in ('mac','ios','watch','tv','paired','vision'):
            with self.subTest(platform=platform), patch.dict(os.environ, {
                    'TOUCHCOLOR_JOB_PLATFORM':platform,'TOUCHCOLOR_VISION_CASE':'canvas-audit'}):
                nested=RetentionTests('test_guard_emits_boolean_only_after_all_checks_and_builtin_fails_missing')
                try:
                    nested.setUp()
                    self.assertEqual(os.environ['TOUCHCOLOR_JOB_PLATFORM'],'mac')
                    self.assertEqual(os.environ['TOUCHCOLOR_VISION_CASE'],'')
                    nested.test_guard_emits_boolean_only_after_all_checks_and_builtin_fails_missing()
                finally:
                    nested.doCleanups()
                self.assertEqual(os.environ['TOUCHCOLOR_JOB_PLATFORM'],platform)
                self.assertEqual(os.environ['TOUCHCOLOR_VISION_CASE'],'canvas-audit')

    def test_real_vision_lane_still_marks_missing_vision_result_unqualified(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'evidence';root.mkdir();Fixture(root);keep.retain(root,SOURCE)
            output=base/'step-output'
            env={**os.environ,'GITHUB_OUTPUT':str(output),'GITHUB_ENV':str(base/'fixture-env'),
                 'TOUCHCOLOR_JOB_PLATFORM':'vision','TOUCHCOLOR_VISION_CASE':'canvas-audit'}
            result=subprocess.run([sys.executable,str(ROOT/'scripts/validate_evidence.py'),str(root),str(keep.LIMIT)],
                                  env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr) # Safe partial evidence may be uploaded.
            self.assertEqual(output.read_text(),'mac_evidence_complete=true\nvision_offline_qualified=false\nnative_text_evidence_complete=false\n')
            gate=subprocess.run(['bash','-c','test "$VISION_OFFLINE_QUALIFIED" = true'],
                                env={**os.environ,'VISION_OFFLINE_QUALIFIED':'false'},timeout=2)
            self.assertNotEqual(gate.returncode,0) # It cannot qualify the real Vision row.

    def test_native_source_keeps_audit_failure_behavior_and_limits_helper_edit(self):
        source = (ROOT/'TouchColorMacUITests/TouchColorMacUITests.swift').read_text()
        helper = source.split('private func audit(', 1)[1].split('    private func recordAuditOwnership', 1)[0]
        self.assertIn('app.screenshot().pngRepresentation', helper)
        self.assertIn('XCTAttachment(data: png', helper)
        self.assertLess(helper.index('app.screenshot()'), helper.index('try app.performAccessibilityAudit(for: .all)'))
        self.assertIn('return false', helper)
        self.assertIn('if !expectsSandbox && requestedStates.contains(state)', helper)
        self.assertIn('Producer truncated diagnostic', helper)
        self.assertNotIn('jpeg', helper.lower())
        capture = helper.split('var issueCount', 1)[0]
        self.assertNotIn('XCTFail(', capture)
        self.assertNotIn('XCTUnwrap(', capture)
        workflow = (ROOT/'.github/workflows/apple-platforms.yml').read_text()
        self.assertLess(workflow.index('Retain small test evidence for review'), workflow.index('Require requested Mac audit pixels'))
        self.assertIn("if os.environ.get('TOUCHCOLOR_JOB_PLATFORM')=='mac': sys.exit(0)", workflow)
        self.assertIn('- platform: mac\n            minutes: 40\n            evidence_bytes: 3000000', workflow)
        self.assertEqual(workflow.count('evidence_bytes: 3000000'), 1)


class WorkflowIdentityTests(unittest.TestCase):
    def environment(self, dedicated=False, event='push'):
        branch = 'mac-watch-repair' if dedicated else 'platform-integration'
        path = '.github/workflows/mac-watch-repair.yml' if dedicated else '.github/workflows/apple-platforms.yml'
        return {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': 'refs/heads/' + branch,
                'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + path + '@refs/heads/' + branch,
                'GITHUB_EVENT_NAME': event, 'GITHUB_SHA': SOURCE['sha'],
                'GITHUB_WORKFLOW_SHA': SOURCE['sha'], 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_JOB': 'native-platform'}

    def source(self, dedicated=False):
        env = self.environment(dedicated)
        identity = keep.workflow_identity(env)
        return {**SOURCE, **identity, 'workflow_file_sha256': keep.digest((ROOT / identity['workflow_file']).read_bytes()),
                'test_file_sha256': keep.digest((ROOT / 'TouchColorMacUITests/TouchColorMacUITests.swift').read_bytes())}

    def test_only_two_exact_workflow_identities_and_original_events_are_admitted(self):
        self.assertEqual(len(keep.WORKFLOW_IDENTITIES), 2)
        for dedicated, event in [(False, 'push'), (False, 'workflow_dispatch'), (True, 'push')]:
            with self.subTest(dedicated=dedicated, event=event):
                value = keep.workflow_identity(self.environment(dedicated, event))
                self.assertEqual(value['workflow_file'], '.github/workflows/' + ('mac-watch-repair.yml' if dedicated else 'apple-platforms.yml'))
                self.assertEqual(value['event_name'], event)
        for dedicated in (False, True):
            for field in ('GITHUB_REPOSITORY', 'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_EVENT_NAME'):
                for value in ('', 'other', self.environment(not dedicated)[field] + '-suffix'):
                    with self.subTest(dedicated=dedicated, field=field, value=value), self.assertRaises(ValueError):
                        keep.workflow_identity({**self.environment(dedicated), field: value})
        for event in ('workflow_dispatch', 'pull_request', 'workflow_run', 'schedule'):
            with self.subTest(event=event), self.assertRaises(ValueError):
                keep.workflow_identity(self.environment(True, event))

    def test_former_prefixed_mac_refs_and_workflows_are_rejected(self):
        historical = (
            (False, 'refs/heads/codex/platform-integration',
             '100mango/ColorPicker/.github/workflows/apple-platforms.yml@refs/heads/codex/platform-integration'),
            (True, 'refs/heads/codex/mac-watch-repair',
             '100mango/ColorPicker/.github/workflows/mac-watch-repair.yml@refs/heads/codex/mac-watch-repair'),
        )
        for dedicated, old_ref, old_workflow in historical:
            env = self.environment(dedicated)
            expected_ref = 'refs/heads/mac-watch-repair' if dedicated else 'refs/heads/platform-integration'
            self.assertEqual(keep.workflow_identity(env)['ref'], expected_ref)
            for changed in ({'GITHUB_REF': old_ref}, {'GITHUB_WORKFLOW_REF': old_workflow},
                            {'GITHUB_REF': old_ref, 'GITHUB_WORKFLOW_REF': old_workflow}):
                with self.subTest(dedicated=dedicated, changed=changed), self.assertRaises(ValueError):
                    keep.workflow_identity({**env, **changed})

    def test_crossed_repository_branch_workflow_and_paths_are_rejected(self):
        for dedicated in (False, True):
            for field in ('GITHUB_REF', 'GITHUB_WORKFLOW_REF'):
                with self.subTest(dedicated=dedicated, field=field), self.assertRaises(ValueError):
                    keep.workflow_identity({**self.environment(dedicated), field: self.environment(not dedicated)[field]})
            for ref in ('100mango/ColorPicker/.github/workflows/../workflows/mac-watch-repair.yml@refs/heads/mac-watch-repair',
                        'other/ColorPicker/.github/workflows/mac-watch-repair.yml@refs/heads/mac-watch-repair',
                        self.environment(dedicated)['GITHUB_WORKFLOW_REF'].replace('@refs/heads/', '@refs/tags/')):
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    keep.workflow_identity({**self.environment(dedicated), 'GITHUB_WORKFLOW_REF': ref})

    def test_provenance_hashes_actual_selected_workflow_and_preserves_sha_clean_guards(self):
        def command(args, **kwargs):
            self.assertEqual(kwargs, {'timeout': 10})
            return {('git', 'rev-parse', 'HEAD'): SOURCE['sha'],
                    ('git', 'diff', '--exit-code', 'HEAD', '--'): '',
                    ('git', 'rev-parse', 'HEAD^{tree}'): SOURCE['tree']}[tuple(args)]
        original = Path.read_bytes
        def read(path): return original(ROOT / path)
        for dedicated in (False, True):
            with self.subTest(dedicated=dedicated), patch.object(keep, 'check_output', side_effect=command) as run, patch.object(Path, 'read_bytes', read):
                result = keep.provenance(self.environment(dedicated))
                expected = self.source(dedicated)
                for key, value in expected.items(): self.assertEqual(result[key], value, key)
                self.assertEqual(run.call_count, 3)
                for update in ({'GITHUB_SHA': ''}, {'GITHUB_WORKFLOW_SHA': '0' * 40},
                               {'GITHUB_SHA': '0' * 40, 'GITHUB_WORKFLOW_SHA': '0' * 40}):
                    with self.assertRaises(ValueError): keep.provenance({**self.environment(dedicated), **update})
        with patch.object(keep, 'check_output', side_effect=subprocess.CalledProcessError(1, 'git diff')):
            with self.assertRaises(subprocess.CalledProcessError): keep.provenance(self.environment(True))
        with patch.object(keep, 'check_output') as run:
            with self.assertRaises(ValueError): keep.provenance({**self.environment(True), 'GITHUB_REF': 'refs/heads/arbitrary'})
            run.assert_not_called()

    def test_retained_packet_requires_consistent_exact_workflow_metadata(self):
        for dedicated in (False, True):
            with self.subTest(dedicated=dedicated), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GITHUB_SHA': ''}):
                root = Path(tmp); Fixture(root); source = self.source(dedicated)
                keep.retain(root, source)
                self.assertTrue(keep.validate_selection(root, require_complete=True)['complete'])
                original = (root / keep.REPORT).read_bytes()
                for key in ('repository', 'ref', 'workflow_ref', 'workflow_file', 'event_name'):
                    report = json.loads(original); report['source'][key] += '-changed'
                    (root / keep.REPORT).write_text(json.dumps(report))
                    with self.subTest(key=key), self.assertRaises(ValueError): keep.validate_selection(root)
                (root / keep.REPORT).write_bytes(original)

    def test_live_validation_rejects_cross_workflow_and_changed_workflow_hash(self):
        original = Path.read_bytes
        def read(path): return original(path if path.is_absolute() else ROOT / path)
        for dedicated in (False, True):
            with self.subTest(dedicated=dedicated), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); Fixture(root); source = self.source(dedicated); keep.retain(root, source)
                with patch.dict(os.environ, self.environment(dedicated)), patch.object(Path, 'read_bytes', read):
                    self.assertTrue(keep.validate_selection(root, require_complete=True)['complete'])
                with patch.dict(os.environ, self.environment(not dedicated)):
                    with self.assertRaisesRegex(ValueError, 'another workflow'): keep.validate_selection(root)
                report = json.loads((root / keep.REPORT).read_bytes()); report['source']['workflow_file_sha256'] = '0' * 64
                (root / keep.REPORT).write_text(json.dumps(report))
                with patch.dict(os.environ, self.environment(dedicated)), patch.object(Path, 'read_bytes', read):
                    with self.assertRaisesRegex(ValueError, 'workflow file hash changed'): keep.validate_selection(root)


if __name__ == '__main__': unittest.main()
