#!/usr/bin/env python3
"""Fail-closed final upload guard, independent from xcresult export/attachment trimming."""
import json,os,re,stat,sys
from pathlib import Path
root=Path(sys.argv[1] if len(sys.argv)>1 else 'build/evidence')
maximum_total=int(sys.argv[2]) if len(sys.argv)>2 else 8_000_000
assert 0<maximum_total<=8_000_000, 'Invalid evidence limit'
assert root.is_dir() and not root.is_symlink(), 'Missing or symlink evidence root'
allowed_root={'architecture.txt','accessibility-api.json','mac-sandbox-entitlements.json','mac-sandbox-post-entitlements.json','vision-ui-summary.json','mac-unit-summary.json','mac-ui-summary.json','mac-sandbox-summary.json','ios-equivalence-summary.json'}
allowed_root.update(f'{p}-{suffix}.json' for p in ('vision','watch','tv') for suffix in ('summary','runtime'))
allowed_dirs={'screenshots','vision-checkpoints','sandbox-screenshots','vision-ui-screenshots','vision-screenshots','watch-screenshots','tv-screenshots'}
total=0;count=0
text_files=set(); approved_text_files=set()
for folder,dirs,files in os.walk(root,followlinks=False):
    directory=Path(folder)
    for name in dirs:
        path=directory/name
        assert directory==root and name in allowed_dirs and not path.is_symlink(), f'Unexpected evidence directory: {path}'
    for name in files:
        path=directory/name; info=path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink==1, f'Not an independent regular file: {path}'
        if directory==root: assert name in allowed_root, f'Unexpected evidence file: {path}'
        else: assert name=='manifest.json' or re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)',name), f'Unexpected attachment: {path}'
        if directory!=root and path.suffix=='.txt':
            assert info.st_size<=256_000, 'Oversize accessibility diagnostic'
            text_files.add(path)
        assert info.st_size<=5_000_000, f'Oversize evidence file: {path}'
        total+=info.st_size;count+=1
        assert total<=maximum_total, 'Evidence exceeds total byte budget'
        if name=='manifest.json':
            for group in json.loads(path.read_text()):
                for item in group.get('attachments',[]):
                    exported=item['exportedFileName']
                    assert re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)',exported), 'Invalid manifest path'
                    assert (directory/exported).is_file(), 'Manifest references missing evidence'
                    if exported.endswith('.txt'):
                        assert item.get('suggestedHumanReadableName','').startswith('Native Mac accessibility issue'), 'Unexpected text attachment provenance'
                        approved_text_files.add(directory/exported)
                    assert item.get('suggestedHumanReadableName','').startswith(('Native Mac','Native Vision','Native Watch','Native TV')), 'Unexpected attachment provenance'
assert text_files==approved_text_files, 'Unmanifested accessibility text attachment'
assert count, 'No bounded evidence to retain'
print(f'Final evidence guard passed: {count} files, {total} bytes (including final manifests)')
