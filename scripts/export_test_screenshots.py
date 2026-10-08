#!/usr/bin/env python3
"""Export two named synthetic screenshots only after XCTest has finished."""
import base64
import json
import pathlib
import subprocess

def records(value):
    if isinstance(value,dict):
        if 'exportedFileName' in value: yield value
        for child in value.values(): yield from records(child)
    elif isinstance(value,list):
        for child in value: yield from records(child)

for device,name in [('iPhoneCompact','touchcolor-history-large-text'),('iPadLarge','touchcolor-ipad-native-canvas')]:
    result=pathlib.Path('build',device+'-TouchColorUITests.xcresult')
    if not (result/'Info.plist').is_file(): continue
    destination=pathlib.Path('build','test-screenshots',device)
    destination.mkdir(parents=True,exist_ok=True)
    subprocess.run(['xcrun','xcresulttool','export','attachments','--path',str(result),'--output-path',str(destination)],check=True)
    manifest=json.loads((destination/'manifest.json').read_text())
    matches=[item for item in records(manifest) if name in ' '.join(v for v in item.values() if isinstance(v,str))]
    assert len(matches)==1, f'Expected one {name}, found {len(matches)}'
    path=(destination/matches[0]['exportedFileName']).resolve()
    assert path.is_relative_to(destination.resolve())
    data=path.read_bytes()
    assert data.startswith(b'\xff\xd8') and len(data)<=500*1024
    encoded=base64.b64encode(data).decode('ascii')
    print(f'SCREENSHOT_BEGIN:{name}')
    for offset in range(0,len(encoded),4096): print('SCREENSHOT_CHUNK:'+encoded[offset:offset+4096])
    print(f'SCREENSHOT_END:{name}')
