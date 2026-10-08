"""Synthetic encoder contract tests; actual sips output is verified on the Mac VM."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from checkpoint_image import retain_image


class ImageRetentionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'00000000-0000-0000-0000-000000000001.png'
        self.path.write_bytes(b'a'*500001)

    def test_quality_is_bounded_and_dimensions_and_both_hashes_are_retained(self):
        qualities = []
        def run(command, **kwargs):
            if '-g' in command:
                return subprocess.CompletedProcess(command, 0, stdout='pixelWidth: 3840\npixelHeight: 2160\n')
            quality = int(command[6]); qualities.append(quality)
            Path(command[-1]).write_bytes(b'b'*(460000 if quality==65 else 420000))
            return subprocess.CompletedProcess(command, 0, stdout='')
        output, result = retain_image(self.path, run)
        self.assertEqual(qualities, [65,45]); self.assertEqual(result['quality'],45)
        self.assertEqual(result['dimensions'],[3840,2160]); self.assertEqual(result['retained_bytes'],420000)
        self.assertNotEqual(result['source_sha256'], result['retained_sha256'])
        self.assertTrue(output.exists()); self.assertFalse(self.path.exists())
        self.assertEqual(list(output.parent.glob('*.tmp.jpeg')), [])

    def test_changed_dimensions_never_replace_source(self):
        original = self.path.read_bytes()
        def run(command, **kwargs):
            if '-g' in command:
                dims = '3840\npixelHeight: 2160' if Path(command[-1])==self.path else '1920\npixelHeight: 1080'
                return subprocess.CompletedProcess(command,0,stdout='pixelWidth: '+dims)
            Path(command[-1]).write_bytes(b'b'*100)
            return subprocess.CompletedProcess(command,0,stdout='')
        with self.assertRaisesRegex(ValueError,'dimensions'): retain_image(self.path,run)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(list(self.path.parent.glob('*.tmp.jpeg')), [])

    def test_nonzero_encoder_is_not_retried_or_accepted(self):
        calls = []
        def run(command, **kwargs):
            if '-g' in command: return subprocess.CompletedProcess(command,0,stdout='pixelWidth: 3840\npixelHeight: 2160')
            calls.append(command); return subprocess.CompletedProcess(command,13,stdout='')
        with self.assertRaisesRegex(ValueError,'encoding failed'): retain_image(self.path,run)
        self.assertEqual(len(calls),1); self.assertTrue(self.path.exists())

    def test_small_image_keeps_exact_bytes_and_needs_no_reencoding(self):
        self.path.write_bytes(b'synthetic tiny image')
        calls=[]
        def run(command,**kwargs):
            calls.append(command);return subprocess.CompletedProcess(command,0,stdout='pixelWidth: 3840\npixelHeight: 2160')
        output,result=retain_image(self.path,run)
        self.assertEqual(output,self.path);self.assertEqual(len(calls),1)
        self.assertEqual(result['source_sha256'],result['retained_sha256'])


if __name__=='__main__': unittest.main()
