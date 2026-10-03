#!/usr/bin/env python3
"""Check source-owned SwiftUI literals and NSLocalizedString keys against Chinese catalogs."""
import re
from pathlib import Path
literal=r'"((?:\\.|[^"\\])*)"'
api=re.compile(r'(?:Text|Button|NavigationLink|Section|Picker|Label|NSLocalizedString|accessibilityLabel|navigationTitle)\s*\(\s*'+literal)
for folder in ('TouchColorMac','TouchColorWatch','TouchColorTV','TouchColorVision'):
    catalog=(Path(folder)/'zh-Hans.lproj/Localizable.strings').read_text()
    keys=re.findall(r'^'+literal+r'\s*=',catalog,re.M)
    assert len(keys)==len(set(keys)), f'Duplicate localization keys: {folder}'
    missing=[]
    for path in Path(folder).glob('*.swift'):
        for text in api.findall(path.read_text()):
            # Numeric/RGB symbols and the deliberate bilingual offline policy need no lookup.
            if not re.search('[A-Za-z]',text) or text in ('TouchColor','R','G','B') or re.fullmatch(r'[RGB] [−+]',text) or text.startswith(('https://','Celluloid、QRCatcher 和 TouchColor','Celluloid, QRCatcher, and TouchColor')) or (text.startswith('\\(') and text.endswith(')')):continue
            key=re.sub(r'\\\((?:[^()]|\([^()]*\))*\)', '%lld',text)
            if key not in keys:missing.append((str(path),key))
    assert not missing, f'Missing Chinese source keys: {missing}'
    print(folder+': source-owned visible strings covered')
