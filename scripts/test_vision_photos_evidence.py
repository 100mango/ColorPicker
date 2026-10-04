"""Synthetic finalized-attachment selection checks; not actual UI evidence."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from vision_photos_evidence import retain, METHOD, PREFIX, MAX_TEXT

class PhotosEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'vision-ui-summary.json').write_text(json.dumps({'result':'Failed'}))
        self.text=self.root/'vision-ui-screenshots';self.text.mkdir()
        self.images=self.root/'vision-checkpoints';self.images.mkdir()
    def attachment(self,folder,name,content=b'synthetic',suffix='.txt'):
        filename=str(uuid.uuid4()).upper()+suffix;(folder/filename).write_bytes(content)
        return {'exportedFileName':filename,'suggestedHumanReadableName':name}
    def run_retention(self):
        with contextlib.redirect_stdout(io.StringIO()):retain(self.root,True)
    def finalize_like_workflow(self):
        # Existing source filter removes unselected generated attachments. The
        # independent final validator still rejects every invalid retained path.
        for p in self.root.glob('*/manifest.json'):
            groups=json.loads(p.read_text());keep=set()
            for g in groups:
                g['attachments']=[a for a in g['attachments'] if a['suggestedHumanReadableName'].startswith('Native Vision')]
                keep.update(a['exportedFileName'] for a in g['attachments'])
            for file in p.parent.iterdir():
                if file.is_file() and file.name!='manifest.json' and file.name not in keep:file.unlink()
            p.write_text(json.dumps(groups))
    def guard(self,success=True):
        result=subprocess.run([sys.executable,'-O',str(Path(__file__).with_name('validate_evidence.py')),str(self.root),'950000'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)
    def test_exact_grid_and_two_latest_navigation_texts_keep_hashes_and_truncation(self):
        grid=self.attachment(self.text,'Debug description for `"PXGGridLayout-Info" Image`_0_fixture',b'x'*40000)
        navigation=[self.attachment(self.text,'Debug description for `"Photos" NavigationBar`_0_fixture',('snapshot'+str(i)).encode()) for i in range(4)]
        unrelated=self.attachment(self.text,'2026-spindump',b'never retain this')
        (self.text/'manifest.json').write_text(json.dumps([{'testIdentifier':METHOD,'attachments':[grid,*navigation,unrelated]}]))
        self.run_retention();self.finalize_like_workflow()
        values=json.loads((self.text/'manifest.json').read_text())[0]['attachments']
        self.assertEqual({a['exportedFileName'] for a in values},{grid['exportedFileName'],navigation[-1]['exportedFileName'],navigation[-2]['exportedFileName']})
        self.assertLessEqual(sum((self.text/a['exportedFileName']).stat().st_size for a in values),48000)
        for a in values:
            raw=(self.text/a['exportedFileName']).read_bytes()
            self.assertLessEqual(len(raw),MAX_TEXT)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),a['boundedText']['retainedSHA256'])
        retained_grid=next(a for a in values if a['exportedFileName']==grid['exportedFileName'])
        self.assertTrue(retained_grid['boundedText']['truncated'])
        self.assertEqual(retained_grid['boundedText']['sourceSHA256'],hashlib.sha256(b'x'*40000).hexdigest())
        self.guard()
        (self.text/retained_grid['exportedFileName']).write_text('tampered')
        self.guard(False)
    def test_other_method_or_successful_case_does_not_relabel_automatic_text(self):
        for passed,method in [(False,'OtherTests/testOther()'),(True,METHOD)]:
            (self.root/'vision-ui-summary.json').write_text(json.dumps({'result':'Passed' if passed else 'Failed'}))
            a=self.attachment(self.text,'Debug description for `"Photos" NavigationBar`_0_fixture')
            (self.text/'manifest.json').write_text(json.dumps([{'testIdentifier':method,'attachments':[a]}]))
            self.run_retention()
            actual=json.loads((self.text/'manifest.json').read_text())[0]['attachments'][0]
            self.assertEqual(actual,a)
    def test_selected_import_proof_wins_and_failure_pregrid_replaces_other_image(self):
        for successful in (True,False):
            names=['Native Vision Photos grid before selection diagnostic','Native Vision failure']
            if successful:names.append('Native Vision actual system Photos import')
            values=[self.attachment(self.images,n,b'synthetic pixels','.jpeg') for n in names]
            (self.images/'manifest.json').write_text(json.dumps([{'attachments':values}]))
            self.run_retention()
            kept=json.loads((self.images/'manifest.json').read_text())[0]['attachments']
            self.assertEqual(len(kept),1)
            self.assertEqual(kept[0]['suggestedHumanReadableName'],names[-1] if successful else names[0])
            for p in self.images.iterdir():p.unlink()
    def test_symlink_source_is_not_read_or_rewritten(self):
        a=self.attachment(self.text,'Debug description for `"Photos" NavigationBar`_0_fixture')
        source=self.text/a['exportedFileName'];source.unlink()
        outside=self.root/'outside';outside.write_text('unchanged');source.symlink_to(outside)
        (self.text/'manifest.json').write_text(json.dumps([{'testIdentifier':METHOD,'attachments':[a]}]))
        with self.assertRaises(ValueError):self.run_retention()
        self.assertEqual(outside.read_text(),'unchanged')
    def test_claimed_prefix_without_exact_source_record_fails_guard(self):
        a=self.attachment(self.text,PREFIX+' forged')
        (self.text/'manifest.json').write_text(json.dumps([{'testIdentifier':METHOD,'attachments':[a]}]))
        self.guard(False)
    def test_other_rows_are_byte_unchanged(self):
        a=self.attachment(self.text,'Debug description for `"Photos" NavigationBar`_0_fixture')
        manifest=self.text/'manifest.json';manifest.write_text(json.dumps([{'testIdentifier':METHOD,'attachments':[a]}]));before=manifest.read_bytes()
        retain(self.root,False)
        self.assertEqual(manifest.read_bytes(),before)

if __name__=='__main__':unittest.main()
