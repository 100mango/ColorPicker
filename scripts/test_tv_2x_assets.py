"""Local mechanical-asset tests. Never invoke Xcode or change original artwork."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from PIL import Image
import materialize_tv_2x_assets as assets

class AssetTests(unittest.TestCase):
    def test_checked_in_assets_and_exact_existing_layout(self):
        result=assets.verify()
        self.assertEqual(len(result['assets']),10)
        self.assertFalse(result['vector_source_available'])
        self.assertEqual(result['small_2x']['artwork_rectangle'],[160,0,480,480])
        self.assertEqual(result['wide_top_shelf_2x']['scale_from_original'],1.40625)

    def test_regeneration_is_deterministic_and_preserves_every_original_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src=root/assets.SOURCE;src.parent.mkdir(parents=True);shutil.copyfile(assets.ROOT/assets.SOURCE,src)
            shutil.copytree(assets.ROOT/assets.CATALOG,root/assets.CATALOG)
            old={str(p.relative_to(root)):p.read_bytes() for p in (root/assets.CATALOG).rglob('*.png') if '-2x' not in p.name}
            before=assets.verify(root)
            self.assertEqual(assets.materialize(root),before)
            self.assertEqual(assets.materialize(root),before)
            for name,raw in old.items():self.assertEqual((root/name).read_bytes(),raw)
            self.assertEqual(src.read_bytes(),(assets.ROOT/assets.SOURCE).read_bytes())

    def test_bad_source_bad_one_x_and_bad_two_x_fail_closed(self):
        for target in ('source','1x','2x','slot'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);src=root/assets.SOURCE;src.parent.mkdir(parents=True);shutil.copyfile(assets.ROOT/assets.SOURCE,src)
                shutil.copytree(assets.ROOT/assets.CATALOG,root/assets.CATALOG)
                directory=root/assets.CATALOG/next(iter(assets.SLOTS))
                if target=='source':src.write_bytes(b'changed')
                elif target=='slot':
                    p=directory/'Contents.json';v=json.loads(p.read_text());v['images']=v['images'][:1];p.write_text(json.dumps(v))
                else:
                    p=directory/('Icon.png' if target=='1x' else 'Icon-2x.png')
                    im=Image.open(p);im.putpixel((0,0),(0,0,0));im.save(p)
                with self.assertRaises(ValueError):assets.verify(root)

if __name__=='__main__':unittest.main()
