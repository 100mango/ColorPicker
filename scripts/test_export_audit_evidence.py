"""Synthetic exporter tests; never substitute these bytes for app evidence."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class GeneratedIssueEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).with_name('export_audit_failures.py').resolve()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                with patch.dict(os.environ, {'TC_TEST_FAMILY': 'iPadLarge'}), contextlib.redirect_stdout(io.StringIO()):
                    cls.module = runpy.run_path(str(script))
            finally:
                os.chdir(previous)

    def description(self, name='issue.txt', test='TouchColorAccessibilityUITests/testAccessibilityLiveCameraUnavailable'):
        return {'exportedFileName': name, '_testIdentifier': test,
                'suggestedHumanReadableName': 'Complete Issue Description.txt', 'isAssociatedWithFailure': True}

    def emit(self, folder, records):
        (folder / 'manifest.json').write_text(json.dumps(records))
        output = io.StringIO()
        with patch.dict(os.environ, {'GITHUB_SHA': 'a'*40}), contextlib.redirect_stdout(output):
            self.module['emit_issue_descriptions'](folder, records)
        return output.getvalue()

    def test_descriptions_keep_test_source_digest_and_explicit_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            raw = ('界\nSCREENSHOT_BEGIN:untrusted\n' * 10000).encode()
            (folder / 'issue.txt').write_bytes(raw)
            text = self.emit(folder, [self.description()])
            payload = json.loads(next(line.split(':', 1)[1] for line in text.splitlines() if line.startswith('AUDIT_ISSUE_DESCRIPTION:')))
            self.assertTrue(payload['truncated'])
            self.assertEqual(payload['source_bytes'], len(raw))
            self.assertEqual(payload['captured_prefix_sha256'], hashlib.sha256(raw[:8192]).hexdigest())
            self.assertEqual(payload['text_sha256'], hashlib.sha256(payload['text'].encode()).hexdigest())
            self.assertEqual(payload['tested_commit'], 'a'*40)
            self.assertNotIn('SCREENSHOT_BEGIN:', text)

    def test_only_failure_descriptions_and_aggregate_bytes_are_emitted(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); records=[]
            for index in range(12):
                name=f'issue-{index}.txt'; (folder/name).write_text('x'*9000)
                records.append(self.description(name))
            records += [dict(self.description(), isAssociatedWithFailure=False), self.description(test='OtherTests/testUnrelated')]
            text = self.emit(folder, records)
            self.assertLessEqual(len(text.encode())+128*len(text.splitlines()), 24*1024)
            summary=json.loads(text.split('AUDIT_ISSUE_DESCRIPTION_SUMMARY:')[1])
            self.assertEqual(summary['selected'],12)
            self.assertGreater(summary['omitted_by_limit'],0)
            self.assertEqual(self.module['RESERVED_LOG_BYTES'],5_858_656)

    def test_paths_and_missing_exact_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); (folder/'issue.txt').write_text('synthetic')
            (folder/'link.txt').symlink_to(folder/'issue.txt')
            for name in ('../issue.txt','link.txt'):
                with self.assertRaises(ValueError): self.module['attachment_path'](folder,self.description(name))
            (folder/'manifest.json').write_text('[]')
            with patch.dict(os.environ, {'GITHUB_SHA':'not-a-commit'}), self.assertRaises(ValueError):
                self.module['emit_issue_descriptions'](folder,[self.description()])

    def test_generated_png_must_be_same_test_failure_and_fit_existing_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); original=self.description()
            generated=dict(original,exportedFileName='issue.png',suggestedHumanReadableName='App Screenshot_0_test.png')
            png=b'\x89PNG\r\n\x1a\n'+b'synthetic'+b'\x00\x00\x00\x00IEND\xaeB`\x82'
            (folder/'issue.png').write_bytes(png)
            self.assertEqual(self.module['paired_issue_image'](original,[generated],folder),png)
            self.assertIsNone(self.module['paired_issue_image'](original,[dict(generated,_testIdentifier='OtherTests/testOther')],folder))
            self.assertIsNone(self.module['paired_issue_image'](original,[dict(generated,isAssociatedWithFailure=False)],folder))
            (folder/'issue.png').write_bytes(png[:-1])
            self.assertIsNone(self.module['paired_issue_image'](original,[generated],folder))
            (folder/'issue.png').write_bytes(png+b'x'*(500*1024))
            self.assertIsNone(self.module['paired_issue_image'](original,[generated],folder))

    def test_empty_missing_or_truncated_during_read_issue_attachment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); path=folder/'issue.txt'
            with self.assertRaises(ValueError): self.emit(folder,[self.description()])
            path.write_bytes(b'')
            with self.assertRaises(ValueError): self.emit(folder,[self.description()])
            path.write_bytes(b'complete synthetic issue')
            original_open=Path.open
            @contextlib.contextmanager
            def changing_open(current, *args, **kwargs):
                with original_open(current,*args,**kwargs) as handle:
                    yield handle
                if current == path and args == ('rb',):
                    with original_open(current,'wb') as handle: handle.write(b'cut')
            with patch.object(Path,'open',changing_open), self.assertRaisesRegex(ValueError,'changed'):
                self.emit(folder,[self.description()])

    def test_nested_manifest_preserves_test_membership(self):
        result=list(self.module['records']([{'testIdentifier':'TouchColorAccessibilityUITests/testA','attachments':[{'exportedFileName':'one.txt'}]}]))
        self.assertEqual(result[0]['_testIdentifier'],'TouchColorAccessibilityUITests/testA')


if __name__ == '__main__': unittest.main()
