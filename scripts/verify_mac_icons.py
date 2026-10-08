#!/usr/bin/env python3
"""Check all native macOS icon slots and preserve the original 1024 artwork bytes."""
from pathlib import Path
import json, struct, hashlib
root=Path(__file__).resolve().parents[1]
catalog=root/'TouchColorMac/Assets.xcassets/AppIcon.appiconset'
items=json.loads((catalog/'Contents.json').read_text())['images']
expected={(size,scale) for size in (16,32,128,256,512) for scale in (1,2)}
actual=set()
for entry in items:
    size=int(entry['size'].split('x')[0]); scale=int(entry['scale'][:-1]); actual.add((size,scale))
    data=(catalog/entry['filename']).read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II',data[16:24])==(size*scale,size*scale)
assert actual==expected and len(items)==10
original=root/'ColorPicker/Images.xcassets/AppIcon.appiconset/Icon-1024.png'
# The source asset's location is resolved from the original app catalog.
if not original.exists():
    originals=[p for p in (root/'ColorPicker').rglob('*.png') if p.read_bytes()==(catalog/'Icon-1024.png').read_bytes()]
    assert originals, 'Original marketing artwork changed'
else: assert original.read_bytes()==(catalog/'Icon-1024.png').read_bytes()
print('Ten native icon slots verified; unchanged original SHA256:',hashlib.sha256((catalog/'Icon-1024.png').read_bytes()).hexdigest())
