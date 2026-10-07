#!/usr/bin/env python3
"""Mechanical TV scale-slot adaptation of unchanged recovered raster artwork.

No vector source is present. This reproduces every existing opaque 1x image's
DECODED pixels before adding 2x slots; it never rewrites existing PNGs. LANCZOS
resampling is not lossless and top-shelf enlargement adds no source detail.
"""
from pathlib import Path
import hashlib
import json
import sys
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'ColorPicker/Images.xcassets/AppIcon.appiconset/Icon-1024.png'
SOURCE_SHA256 = 'b866d4ca66a2b3bc82e9375e613ca09fe3c1823c7177ec0d0ad17f465001cc18'
CATALOG = 'TouchColorTV/Assets.xcassets/AppIcon.brandassets'
SLOTS = {
    'Small.imagestack/Back.imagestacklayer/Content.imageset': (800, 480, False),
    'Small.imagestack/Front.imagestacklayer/Content.imageset': (800, 480, True),
    'TopShelf.imageset': (3840, 1440, False),
    'TopShelfWide.imageset': (4640, 1440, False),
}
OPAQUE_1X = {
    'Small.imagestack/Back.imagestacklayer/Content.imageset/Icon.png': (400, 240),
    'Large.imagestack/Back.imagestacklayer/Content.imageset/Icon.png': (1280, 768),
    'TopShelf.imageset/Icon.png': (1920, 720),
    'TopShelfWide.imageset/Icon.png': (2320, 720),
}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root=ROOT):
    path = root / SOURCE
    need(digest(path) == SOURCE_SHA256, 'Original brand source changed')
    image = Image.open(path); image.load()
    need(image.size == (1024, 1024) and image.mode == 'RGB', 'Unexpected original raster')
    return image


def render(image, size, transparent=False):
    if transparent:
        return Image.new('RGBA', size, (0, 0, 0, 0))
    width, height = size
    result = Image.new('RGB', size, image.getpixel((0, 0)))
    result.paste(image.resize((height, height), Image.Resampling.LANCZOS), ((width-height)//2, 0))
    return result


def verify_existing(root=ROOT):
    image = source(root)
    for path, size in OPAQUE_1X.items():
        with Image.open(root / CATALOG / path) as existing:
            need(existing.size == size and existing.mode == 'RGB', 'Unexpected 1x image')
            need(ImageChops.difference(existing, render(image, size)).getbbox() is None,
                 'Recovered mechanical layout does not reproduce existing artwork')
    for role, size in [('Small', (400, 240)), ('Large', (1280, 768))]:
        path = f'{role}.imagestack/Front.imagestacklayer/Content.imageset/Transparent.png'
        with Image.open(root / CATALOG / path) as existing:
            need(existing.size == size and existing.mode == 'RGBA' and
                 existing.getextrema() == ((0, 0),) * 4, 'Existing foreground is not transparent')
    return image


def materialize(root=ROOT):
    image = verify_existing(root)
    for path, (width, height, transparent) in SLOTS.items():
        directory = root / CATALOG / path
        filename = 'Transparent-2x.png' if transparent else 'Icon-2x.png'
        render(image, (width, height), transparent).save(directory / filename, 'PNG')
        contents = directory / 'Contents.json'
        value = json.loads(contents.read_text())
        existing = [item for item in value['images'] if item.get('scale') != '2x']
        need(len(existing) == 1 and existing[0].get('scale') == '1x', 'Unexpected existing scale slots')
        value['images'] = existing + [{'filename': filename, 'idiom': 'tv', 'scale': '2x'}]
        contents.write_text(json.dumps(value, indent=2) + '\n')
    return verify(root)


def verify(root=ROOT):
    image = verify_existing(root)
    for path, (width, height, transparent) in SLOTS.items():
        directory = root / CATALOG / path
        values = json.loads((directory / 'Contents.json').read_text())['images']
        need(len(values) == 2 and {v['scale'] for v in values} == {'1x', '2x'}, 'Incomplete scale slots')
        filename = 'Transparent-2x.png' if transparent else 'Icon-2x.png'
        two = next(v for v in values if v['scale'] == '2x')
        need(two == {'filename': filename, 'idiom': 'tv', 'scale': '2x'}, 'Wrong scale-slot identity')
        with Image.open(directory / filename) as output:
            expected = render(image, (width, height), transparent)
            need(output.size == expected.size and output.mode == expected.mode and
                 output.tobytes() == expected.tobytes(), '2x raster is not exact mechanical adaptation')
    assets = []
    for path in sorted((root / CATALOG).rglob('*.png')):
        with Image.open(path) as im:
            assets.append({'path': path.relative_to(root).as_posix(), 'width': im.width, 'height': im.height,
                           'mode': im.mode, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    return {'source': SOURCE, 'source_sha256': SOURCE_SHA256, 'source_dimensions': [1024, 1024],
            'vector_source_available': False, 'existing_1x_decoded_pixels_reproduced': True,
            'existing_png_bytes_rewritten': False, 'method': 'LANCZOS from original 1024px raster, centered square on original corner-color background; transparent front stays zero RGBA',
            'small_2x': {'canvas': [800, 480], 'artwork_rectangle': [160, 0, 480, 480], 'fraction_width': 0.6, 'fraction_height': 1, 'scale_from_original': 0.46875},
            'top_shelf_2x': {'canvas': [3840, 1440], 'artwork_rectangle': [1200, 0, 1440, 1440], 'fraction_width': 0.375, 'fraction_height': 1, 'scale_from_original': 1.40625},
            'wide_top_shelf_2x': {'canvas': [4640, 1440], 'artwork_rectangle': [1600, 0, 1440, 1440], 'fraction_width': 1440/4640, 'fraction_height': 1, 'scale_from_original': 1.40625},
            'resampling_limit': 'Top-shelf artwork is enlarged 1.40625x from a 1024px raster, not lossless or newly detailed. PNG encoding is lossless; that does not make resampling lossless.',
            'assets': assets, 'total_png_bytes': sum(x['bytes'] for x in assets)}


if __name__ == '__main__':
    need(sys.argv[1:] in ([], ['--check']), 'Only --check is supported')
    print(json.dumps(verify() if sys.argv[1:] else materialize(), indent=2))
