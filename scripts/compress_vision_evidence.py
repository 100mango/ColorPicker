#!/usr/bin/env python3
"""Encode manifested Vision evidence before final trimming/independent safety guard."""
import json
import re
from pathlib import Path
import sys
from checkpoint_image import retain_image

root = Path(sys.argv[1])
for folder in ('vision-checkpoints', 'vision-ui-screenshots', 'vision-screenshots'):
    manifest = root/folder/'manifest.json'
    if not manifest.is_file(): continue
    assert not manifest.is_symlink() and not manifest.parent.is_symlink(), 'Symlink evidence manifest'
    groups = json.loads(manifest.read_text())
    for group in groups:
        for attachment in group.get('attachments', []):
            name = attachment['exportedFileName']
            assert re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)', name), 'Unexpected evidence path'
            source = manifest.parent/name
            # The independent final guard still validates every path and file.
            if source.parent != manifest.parent or source.suffix.lower() not in ('.png', '.jpg', '.jpeg'): continue
            if not source.is_file(): continue
            try:
                retained, provenance = retain_image(source)
                attachment['exportedFileName'] = retained.name
                attachment['evidenceEncoding'] = provenance
                print('VISION_EVIDENCE_ENCODING', json.dumps({'file': retained.name, **provenance}), flush=True)
            except Exception as error:
                # Missing pixels stay explicitly missing. Never upload an oversize
                # or partial output as if it were a successful capture.
                attachment['evidenceEncoding'] = {'omitted': type(error).__name__, 'reason': str(error)[:180]}
                source.unlink(missing_ok=True)
                print('VISION_EVIDENCE_OMITTED', json.dumps(attachment['evidenceEncoding']), flush=True)
                if getattr(error, 'cleanup_confirmed', True) is False: raise
    manifest.write_text(json.dumps(groups, ensure_ascii=False, indent=2)+'\n')
