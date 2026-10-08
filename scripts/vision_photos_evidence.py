"""Retain a small, explicit subset of finalized Photos failure evidence.

No simulator/app action, recording or spindump is read. The existing row budget
and one retained custom Photos image remain unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

METHOD = 'VisionWorkflowTests/testRealPhotosImport()'
PREFIX = 'Native Vision Photos diagnostic'
SOURCE_PREFIXES = ('Debug description for `"PXGGridLayout-Info" Image`_',
                   'Debug description for `"Photos" NavigationBar`_')
MAX_SOURCE = 5_000_000
MAX_TEXT = 16_000
MAX_TOTAL = 48_000


def source_kind(name):
    return next((index for index,prefix in enumerate(SOURCE_PREFIXES) if name.startswith(prefix)),None)


def checked_file(folder,name):
    if folder.is_symlink() or not re.fullmatch(r'[0-9A-Fa-f-]{36}\.(txt|png|jpg|jpeg)',name):
        raise ValueError('Unexpected Photos evidence path')
    path=folder/name
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1:
        raise ValueError('Photos evidence must be an independent regular file')
    return path


def retain_text(path,name):
    digest=hashlib.sha256();size=0;prefix=bytearray()
    with path.open('rb') as stream:
        while chunk:=stream.read(65536):
            size+=len(chunk)
            if size>MAX_SOURCE:raise ValueError('Photos diagnostic source exceeds bounded read')
            digest.update(chunk)
            if len(prefix)<MAX_TEXT:prefix.extend(chunk[:MAX_TEXT-len(prefix)])
    header=('Source: '+name[:400]+'\nSource SHA256: '+digest.hexdigest()+'\nSource bytes: '+str(size)+'\n')
    budget=MAX_TEXT-len(header.encode())-100
    body=bytes(prefix).decode('utf-8',errors='replace').encode()[:budget].decode('utf-8',errors='ignore')
    truncated=len(body.encode())<size
    marker='\n[Truncated bounded UTF-8 prefix]\n' if truncated else '\n[Complete diagnostic text]\n'
    retained=(header+'Truncated: '+str(truncated).lower()+'\n\n'+body+marker).encode()
    if len(retained)>MAX_TEXT:raise ValueError('Photos retained diagnostic exceeds its bound')
    path.write_bytes(retained)
    return {'sourceSHA256':digest.hexdigest(),'sourceBytes':size,'retainedSHA256':hashlib.sha256(retained).hexdigest(),
            'retainedBytes':len(retained),'truncated':truncated}


def retain(root,photos):
    if not photos:return
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Invalid evidence root')
    manifest=root/'vision-ui-screenshots/manifest.json'
    summary=root/'vision-ui-summary.json'
    failed=False
    if summary.is_file():
        if summary.is_symlink(): raise ValueError('Symlink result summary')
        outcome=json.loads(summary.read_text())
        failed=outcome.get('result')!='Passed'
    if failed and manifest.is_file():
        if manifest.is_symlink() or manifest.parent.is_symlink():raise ValueError('Symlink evidence manifest')
        groups=json.loads(manifest.read_text());total=0
        for group in groups:
            if group.get('testIdentifier')!=METHOD:continue
            candidates=[a for a in group.get('attachments',[]) if source_kind(a.get('suggestedHumanReadableName','')) is not None]
            # One grid description and the two latest observed navigation checks.
            chosen=[]
            for kind,limit in [(0,1),(1,2)]:
                chosen.extend([a for a in candidates if source_kind(a['suggestedHumanReadableName'])==kind][-limit:])
            for item in chosen:
                original=item['suggestedHumanReadableName']
                path=checked_file(manifest.parent,item['exportedFileName'])
                if path.suffix!='.txt':raise ValueError('Expected automatic Photos text diagnostic')
                facts=retain_text(path,original);total+=facts['retainedBytes']
                if total>MAX_TOTAL:raise ValueError('Photos text diagnostics exceed aggregate cap')
                item.update(suggestedHumanReadableName=PREFIX+' '+path.name,
                            originalSuggestedHumanReadableName=original,boundedText=facts)
                print('VISION_PHOTOS_RETAINED_TEXT',json.dumps({'file':path.name,'source':original,**facts}),flush=True)
        manifest.write_text(json.dumps(groups,ensure_ascii=False,indent=2)+'\n')
    manifest=root/'vision-checkpoints/manifest.json'
    if manifest.is_file():
        if manifest.is_symlink() or manifest.parent.is_symlink():raise ValueError('Symlink capture manifest')
        groups=json.loads(manifest.read_text())
        items=[(group,item) for group in groups for item in group.get('attachments',[])]
        selected=[pair for pair in items if pair[1].get('suggestedHumanReadableName','').startswith('Native Vision actual system Photos import')]
        pregrid=[pair for pair in items if pair[1].get('suggestedHumanReadableName','').startswith('Native Vision Photos grid before selection diagnostic')]
        # A successful selected-image proof wins. On failure replace the former
        # failure screenshot with the pre-grid still; never add a second image.
        retained=(selected or pregrid or items)[-1:] if items else []
        keep={item['exportedFileName'] for _,item in retained}
        for group,item in items:
            if item['exportedFileName'] not in keep:
                checked_file(manifest.parent,item['exportedFileName']).unlink()
        for group in groups:
            group['attachments']=[a for a in group.get('attachments',[]) if a['exportedFileName'] in keep]
        manifest.write_text(json.dumps(groups,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    retain(Path(sys.argv[1]),os.environ.get('TOUCHCOLOR_VISION_CASE')=='photos')
