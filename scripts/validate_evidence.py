#!/usr/bin/env python3
"""Fail-closed final upload guard, independent from xcresult export/attachment trimming."""
import hashlib, json, os, re, stat, sys
from vision_photos_evidence import METHOD as PHOTOS_METHOD, PREFIX as PHOTOS_PREFIX, source_kind, MAX_TEXT, MAX_TOTAL
from pathlib import Path
root = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/evidence')
maximum_total = int(sys.argv[2]) if len(sys.argv) > 2 else 8000000
if not 0 < maximum_total <= 8000000:
    raise RuntimeError('Invalid evidence limit')
if not (root.is_dir() and (not root.is_symlink())):
    raise RuntimeError('Missing or symlink evidence root')
allowed_root = {'architecture.txt', 'accessibility-api.json', 'mac-sandbox-entitlements.json', 'mac-sandbox-post-entitlements.json', 'vision-ui-summary.json', 'watch-ui-summary.json', 'mac-unit-summary.json', 'mac-ui-summary.json', 'mac-sandbox-summary.json', 'ios-equivalence-summary.json'}
allowed_root.update((f'{p}-{suffix}.json' for p in ('vision', 'watch', 'tv') for suffix in ('summary', 'runtime')))
allowed_root.add('mac-modal-probe-summary.json')
allowed_root.add('job-budget.json')
allowed_root.add('mac-evidence-selection.json')
# This optional projection requires the existing exact Mac selection/source proof.
if (root/'mac-passive-lifecycle.json').exists():
    if os.environ.get('TOUCHCOLOR_JOB_PLATFORM')!='mac' or maximum_total!=3000000 or not (root/'mac-evidence-selection.json').is_file():
        raise RuntimeError('Unbound passive Mac projection')
    if (root/'mac-passive-lifecycle.json').lstat().st_size>128*1024:
        raise RuntimeError('Oversize passive Mac projection')
    allowed_root.add('mac-passive-lifecycle.json')
allowed_root.add('native-text-evidence.json')
allowed_root.add('secondary-about-evidence.json')
allowed_dirs = {'screenshots', 'vision-checkpoints', 'sandbox-screenshots', 'vision-ui-screenshots', 'vision-screenshots', 'watch-screenshots', 'watch-ui-screenshots', 'tv-screenshots'}
allowed_dirs.add('modal-probe-screenshots')
allowed_root.update({'vision-largest-text-summary.json','watch-largest-text-summary.json'})
allowed_dirs.update({'vision-largest-text-screenshots','watch-largest-text-screenshots'})
allowed_root.add('watch-public-trait-summary.json')
allowed_dirs.add('watch-public-trait-screenshots')
allowed_dirs.update({'paired-phone-screenshots','paired-watch-screenshots'})
allowed_root.update({'paired-runtime.json','paired-phone-summary.json','paired-watch-summary.json'})
total = 0
count = 0
text_files = set()
approved_text_files = set()
photos_text_count = photos_text_bytes = 0
for folder, dirs, files in os.walk(root, followlinks=False):
    directory = Path(folder)
    for name in dirs:
        path = directory / name
        if not (directory == root and name in allowed_dirs and (not path.is_symlink())):
            raise RuntimeError(f'Unexpected evidence directory: {path}')
    for name in files:
        path = directory / name
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            raise RuntimeError(f'Not an independent regular file: {path}')
        if directory == root:
            if not name in allowed_root:
                raise RuntimeError(f'Unexpected evidence file: {path}')
        elif not (name == 'manifest.json' or re.fullmatch('[0-9A-Fa-f-]{36}\\.(png|jpg|jpeg|txt)', name)):
            raise RuntimeError(f'Unexpected attachment: {path}')
        if directory != root and path.suffix == '.txt':
            if not info.st_size <= 256000:
                raise RuntimeError('Oversize accessibility diagnostic')
            text_files.add(path)
        if not info.st_size <= 5000000:
            raise RuntimeError(f'Oversize evidence file: {path}')
        total += info.st_size
        count += 1
        if not total <= maximum_total:
            raise RuntimeError('Evidence exceeds total byte budget')
        if name == 'manifest.json':
            for group in json.loads(path.read_text()):
                for item in group.get('attachments', []):
                    exported = item['exportedFileName']
                    if not re.fullmatch('[0-9A-Fa-f-]{36}\\.(png|jpg|jpeg|txt)', exported):
                        raise RuntimeError('Invalid manifest path')
                    if not (directory / exported).is_file():
                        raise RuntimeError('Manifest references missing evidence')
                    if exported.endswith('.txt'):
                        title=item.get('suggestedHumanReadableName','')
                        if title.startswith(PHOTOS_PREFIX):
                            facts=item.get('boundedText',{})
                            actual=directory/exported
                            if directory.name!='vision-ui-screenshots' or group.get('testIdentifier')!=PHOTOS_METHOD or source_kind(item.get('originalSuggestedHumanReadableName','')) is None:
                                raise RuntimeError('Unexpected automatic Photos diagnostic provenance')
                            text_info=actual.lstat()
                            if not stat.S_ISREG(text_info.st_mode) or text_info.st_nlink!=1:raise RuntimeError('Unsafe Photos diagnostic file')
                            if text_info.st_size>MAX_TEXT or facts.get('retainedBytes')!=text_info.st_size or hashlib.sha256(actual.read_bytes()).hexdigest()!=facts.get('retainedSHA256'):
                                raise RuntimeError('Photos diagnostic retained bytes/hash mismatch')
                            if not re.fullmatch('[0-9a-f]{64}',facts.get('sourceSHA256','')) or type(facts.get('sourceBytes')) is not int or not 0<=facts['sourceBytes']<=5000000 or type(facts.get('truncated')) is not bool:
                                raise RuntimeError('Invalid Photos diagnostic source record')
                            photos_text_count+=1;photos_text_bytes+=actual.stat().st_size
                            if photos_text_count>3 or photos_text_bytes>MAX_TOTAL:raise RuntimeError('Photos diagnostic aggregate exceeded')
                        elif title.startswith(('Native TV secondary audit ', 'Native Watch secondary audit ', 'Native Vision secondary audit ')):
                            from secondary_about_evidence import is_audit_title, MAX_AUDIT
                            if not is_audit_title(title) or (directory / exported).lstat().st_size > MAX_AUDIT:
                                raise RuntimeError('Unknown or oversized secondary About audit receipt')
                        elif not title.startswith('Native Mac accessibility issue'):
                            raise RuntimeError('Unexpected text attachment provenance')
                        approved_text_files.add(directory / exported)
                    if not item.get('suggestedHumanReadableName', '').startswith(('Native Mac', 'Native Vision', 'Native Watch', 'Native TV', 'touchcolor-paired-phone')):
                        raise RuntimeError('Unexpected attachment provenance')
if not text_files == approved_text_files:
    raise RuntimeError('Unmanifested accessibility text attachment')
mac_evidence_complete = None
if (root/'mac-evidence-selection.json').exists():
    from retain_mac_evidence import validate_selection
    mac_evidence_complete = validate_selection(root)['complete'] # Safety/integrity first; preserve safe partial packets.
from native_text_evidence import REPORT as TEXT_SELECTION, evidence_complete as native_text_complete
text_complete=native_text_complete(root)
from vision_offline_result import evidence_complete
# A validated explicit omission packet remains uploadable but cannot qualify.
# Legacy controller-only fallback still requires its exact authenticated provenance.
vision_complete=False if (root/TEXT_SELECTION).is_file() and not text_complete else evidence_complete(root)
from secondary_about_evidence import complete as secondary_complete
secondary_evidence_complete = secondary_complete(root)
if not count:
    raise RuntimeError('No bounded evidence to retain')
print(f'Final evidence guard passed: {count} files, {total} bytes (including final manifests)')

# Publish only a fixed boolean after every byte/path/provenance check succeeded.
# The post-upload step is a shell builtin, not a second unreserved file scan.
if mac_evidence_complete is not None and os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("mac_evidence_complete=" + ("true" if mac_evidence_complete else "false") + "\n")

if os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'],'a') as output: output.write('vision_offline_qualified='+str(vision_complete).lower()+'\n')

if os.environ.get('GITHUB_OUTPUT') and os.environ.get('TOUCHCOLOR_JOB_PLATFORM') in ('vision','watch'):
    with open(os.environ['GITHUB_OUTPUT'],'a') as output: output.write('native_text_evidence_complete='+str(text_complete).lower()+'\n')

if secondary_evidence_complete is not None and os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        output.write('secondary_evidence_complete='+str(secondary_evidence_complete).lower()+'\n')
