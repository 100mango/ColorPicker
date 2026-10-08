"""Reserve exact pre-audit Mac PNGs before optional verbose hierarchies.

Raw issue prefixes, API errors, ownership/proof/end records and result/source
metadata are mandatory. No image is resized/re-encoded, and omitted attachments
retain their identity/hash/reason. Incomplete requested pixels fail a separate
post-upload check so the bounded partial packet remains inspectable.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import time

from bounded_process import check_output

LIMIT = 3_000_000
RESERVE = 16_384
REPORT = 'mac-evidence-selection.json'
MAX_SOURCE = 5_000_000
MAX_PNG = 500_000
MAX_IMAGES = 16
ADMISSION_MARGIN = 8192
FOLDERS = ('screenshots', 'sandbox-screenshots', 'modal-probe-screenshots')
REQUIRED_ROOT = ('architecture.txt', 'accessibility-api.json', 'mac-unit-summary.json', 'mac-ui-summary.json',
                 'mac-sandbox-summary.json', 'mac-modal-probe-summary.json',
                 'mac-sandbox-entitlements.json', 'mac-sandbox-post-entitlements.json')
REQUESTED = {
    'empty workspace': 'testOfficialAccessibilityEmptyAndPopulatedCanvas',
    'full image and palette': 'testOfficialAccessibilityEmptyAndPopulatedCanvas',
    'camera availability': 'testOfficialAccessibilityCameraAndPrivacy',
    'offline privacy': 'testOfficialAccessibilityCameraAndPrivacy',
    'corrupt import error': 'testOfficialAccessibilityCorruptImportRetainsPreviousSource',
}
PROOF_PREFIX = 'Native Mac accessibility issue screenshot proof '
FRAME_PREFIX = 'Native Mac audit state '
SUMMARY_PREFIX = 'Native Mac accessibility issue audit summary '


def require(value, message):
    if not value: raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def digest(data): return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate JSON key')
            value[key] = item
        return value
    def invalid(value): raise ValueError('Nonfinite JSON number')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def read_file(path, limit=MAX_SOURCE):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit,
            'Unsafe or oversized evidence file: ' + str(path))
    raw = path.read_bytes()
    after = path.lstat()
    require((info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
            'Evidence changed during read')
    return raw


def oversized_image(path):
    # Do not let one unretainable image abort selection of other useful frames.
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Unsafe image file')
    facts = {'sourceBytes': info.st_size, 'sourceSHA256': None}
    if info.st_size <= 64 * 1024 * 1024:
        value = hashlib.sha256(); count = 0; start = time.monotonic()
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                count += len(chunk)
                if count > 64 * 1024 * 1024 or time.monotonic() - start > 10: break
                value.update(chunk)
        if count == info.st_size and time.monotonic() - start <= 10: facts['sourceSHA256'] = value.hexdigest()
    if facts['sourceSHA256'] is None: facts['sourceHashUnavailable'] = 'Oversized image exceeds finite hash bound; no digest claimed'
    after = path.lstat()
    require((info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns), 'Oversized image changed')
    return facts


def png_dimensions(data):
    require(data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR'
            and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'), 'Not complete native PNG bytes')
    width, height = struct.unpack('>II', data[16:24])
    require(0 < width <= 16384 and 0 < height <= 16384, 'PNG dimensions out of bounds')
    return [width, height]


def provenance(environ=os.environ):
    sha = environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Missing exact source SHA')
    require(environ.get('GITHUB_WORKFLOW_SHA') == sha, 'Workflow/source SHA mismatch')
    require(check_output(['git', 'rev-parse', 'HEAD'], timeout=10).strip() == sha, 'HEAD/source SHA mismatch')
    check_output(['git', 'diff', '--exit-code', 'HEAD', '--'], timeout=10)
    return {'sha': sha, 'tree': check_output(['git', 'rev-parse', 'HEAD^{tree}'], timeout=10).strip(),
            'workflow_sha': sha, 'run_id': environ.get('GITHUB_RUN_ID'), 'run_attempt': environ.get('GITHUB_RUN_ATTEMPT'),
            'job': environ.get('GITHUB_JOB'), 'tracked_source_clean': True,
            'workflow_file_sha256': digest(Path('.github/workflows/apple-platforms.yml').read_bytes()),
            'test_file_sha256': digest(Path('TouchColorMacUITests/TouchColorMacUITests.swift').read_bytes())}


def correlated_frame(proof_item, items, summary):
    proof = strict_json(proof_item['raw'])
    state = proof.get('state'); audit = proof.get('auditID')
    require(type(proof.get('schema')) is int and proof['schema'] == 1 and state in REQUESTED,
            'Unknown audit proof schema/state')
    require(isinstance(audit, str) and re.fullmatch('[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', audit), 'Invalid audit ID')
    require(proof_item['folder'] == 'screenshots' and proof.get('sandbox') is False
            and proof.get('capturePhase') == 'immediately before audit' and proof.get('sequential') is True,
            'Wrong audit lane or capture phase')
    identifier = 'TouchColorMacUITests/' + REQUESTED[state] + '()'
    require(proof_item['group'].get('testIdentifier') == identifier,
            'Proof test does not match its requested state')
    require(proof.get('testName') == '-[TouchColorMacUITests ' + REQUESTED[state] + ']',
            'Proof runtime test identity mismatch')
    require(proof.get('imageName') == FRAME_PREFIX + audit
            and proof_item['attachment']['suggestedHumanReadableName'].startswith(PROOF_PREFIX + audit + '_'), 'Image/audit identity mismatch')
    require(proof_item['group'].get('testIdentifierURL') == 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/' + REQUESTED[state],
            'Proof test identifier URL mismatch')
    for key in ('pngSHA256', 'appExecutableSHA256', 'appLogicSHA256'):
        require(isinstance(proof.get(key), str) and re.fullmatch('[0-9a-f]{64}', proof[key]), 'Missing image/app hash')
    require(type(proof.get('pngBytes')) is int and 0 < proof['pngBytes'] <= MAX_SOURCE, 'Invalid PNG byte count')
    rows = summary.get('devicesAndConfigurations')
    require(isinstance(rows, list) and len(rows) == 1, 'Ambiguous Mac result destination')
    device = rows[0].get('device', {})
    require(device.get('platform') == 'macOS' and device.get('architecture') == 'arm64'
            and device.get('osVersion') == '27.0', 'Unexpected Mac runtime')
    config = rows[0]['testPlanConfiguration']['configurationName']
    candidates = [item for item in items if item['folder'] == 'screenshots'
                  and item['group'].get('testIdentifier') == identifier
                  and item['attachment'].get('suggestedHumanReadableName', '').startswith(FRAME_PREFIX + audit + '_')
                  and item['path'].suffix == '.png']
    require(len(candidates) == 1, 'Missing or duplicate explicit audit frame')
    frame = candidates[0]; data = frame['raw']; metadata = frame['attachment']
    require(digest(data) == proof['pngSHA256'] and len(data) == proof['pngBytes'], 'Original PNG hash/size mismatch')
    dimensions = png_dimensions(data)
    summaries = [item for item in items if item['folder'] == 'screenshots'
                 and item['group'].get('testIdentifier') == identifier
                 and item['attachment'].get('suggestedHumanReadableName', '').startswith(SUMMARY_PREFIX + audit + '_')]
    require(len(summaries) == 1 and summaries[0]['raw'].startswith(('Audit-ID: ' + audit + '\nState: ' + state + '\n').encode()),
            'Missing exact audit-end summary')
    end = re.fullmatch(re.escape('Audit-ID: ' + audit + '\nState: ' + state)
                       + r'\nIssues: ([0-9]+)\nRecorded failures: ([0-9]+)\n?', summaries[0]['raw'].decode('utf-8'))
    require(end is not None, 'Incomplete audit-end counters')
    issue_prefix = ('State: ' + state + '\nAudit-ID: ' + audit + '\n').encode()
    issues = [item for item in items if item['folder'] == 'screenshots'
              and item['group'].get('testIdentifier') == identifier and item['raw'].startswith(issue_prefix)]
    require(len(issues) == int(end[1]), 'Raw issue inventory differs from completed audit counters')
    for item in (frame, proof_item, summaries[0]):
        attachment = item['attachment']
        require(attachment.get('deviceId') == device.get('deviceId') and attachment.get('configurationName') == config,
                'Audit attachments have mismatched destination/configuration')
    times = [summary.get('startTime'), proof.get('capturedAt'), metadata.get('timestamp'),
             proof_item['attachment'].get('timestamp'), summaries[0]['attachment'].get('timestamp'), summary.get('finishTime')]
    require(all(type(value) in (int, float) and math.isfinite(value) for value in times)
            and all(a <= b + 0.001 for a, b in zip(times, times[1:])), 'Audit capture/end timing mismatch')
    frame['correlation'] = {'auditID': audit, 'state': state, 'testIdentifier': identifier, 'lane': 'mac-ui',
                            'capturePhase': proof['capturePhase'], 'sequential': True, 'dimensions': dimensions,
                            'proof': proof_item['relative'], 'auditSummary': summaries[0]['relative'],
                            'appExecutableSHA256': proof['appExecutableSHA256'], 'appLogicSHA256': proof['appLogicSHA256']}
    return state, frame


def retain(root, source, *, limit=LIMIT):
    root = Path(root)
    require(limit == LIMIT, 'Mac evidence ceiling must remain 3000000 bytes')
    require(root.is_dir() and not root.is_symlink(), 'Unsafe evidence root')
    require(not (root / REPORT).exists(), 'Selection already exists; do not repeat mutation')
    budget = limit - RESERVE
    manifests = {}; items = []; outputs = {}; originals = {}; present = set()
    for path in root.iterdir():
        if path.is_file() or path.is_symlink():
            raw = read_file(path); outputs[path.name] = raw; originals[path.name] = digest(raw); present.add(path.name)
        else: require(path.name in FOLDERS and path.is_dir() and not path.is_symlink(), 'Unexpected Mac export directory')
    for folder in FOLDERS:
        path = root / folder / 'manifest.json'
        if not path.exists(): continue
        groups = strict_json(read_file(path, 1_000_000))
        require(isinstance(groups, list) and len(groups) <= 64, 'Unexpected attachment group inventory')
        seen = set()
        for group in groups:
            require(isinstance(group, dict) and isinstance(group.get('attachments'), list), 'Invalid attachment group')
            group['omittedAttachments'] = []
            for attachment in group['attachments']:
                name = attachment.get('exportedFileName', '')
                require(re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)', name) and name not in seen, 'Duplicate/unsafe attachment path')
                seen.add(name)
                require(attachment.get('suggestedHumanReadableName', '').startswith('Native Mac'), 'Unapproved attachment provenance')
                file = path.parent / name
                oversized = file.suffix in ('.png', '.jpg', '.jpeg') and file.lstat().st_size > MAX_SOURCE
                facts = oversized_image(file) if oversized else None
                raw = b'' if oversized else read_file(file)
                item = {'path': file, 'relative': folder + '/' + name, 'folder': folder, 'group': group,
                        'attachment': attachment, 'raw': raw, 'selected': False}
                items.append(item)
                if oversized: item['omission'] = 'Original image exceeds bounded source read; other frames retained independently'
                require(len(items) <= 512, 'Attachment inventory exceeded finite bound')
                if file.suffix == '.txt':
                    require(attachment['suggestedHumanReadableName'].startswith('Native Mac accessibility issue'), 'Unapproved Mac text')
                    prefix, marker, hierarchy = raw.partition(b'\nHierarchy:')
                    # Only the repeated hierarchy is optional. Never truncate raw
                    # issue descriptions, API errors, ownership, or proof records.
                    item['prefix'] = prefix if marker else raw
                    item['hierarchy'] = marker + hierarchy if marker else b''
                    outputs[item['relative']] = item['prefix']; item['selected'] = True
                attachment['retention'] = facts if oversized else {'sourceSHA256': digest(raw), 'sourceBytes': len(raw)}
                if file.suffix == '.txt': attachment['retention']['producerTruncated'] = b'[Producer truncated diagnostic' in raw
        unmanifested = {p.name for p in path.parent.iterdir() if p.name != 'manifest.json'} - seen
        require(not unmanifested, 'Unmanifested Mac attachment')
        manifests[folder] = groups
    result = {'schema': 1, 'source': source, 'limit': limit, 'metadataReserve': RESERVE,
              'rootFiles': {name: {'sha256': originals[name], 'bytes': len(outputs[name])} for name in sorted(present) if name != 'job-budget.json'},
              'attachmentInventory': {item['relative']: {**item['attachment']['retention'], 'mandatoryText': item['path'].suffix == '.txt'} for item in items},
              'requested': {state: {'status': 'missing', 'reason': 'No correlated pre-audit capture'} for state in REQUESTED},
              'missingMandatory': sorted(set(REQUIRED_ROOT) - present), 'complete': False,
              'policy': 'mandatory raw findings/results/source, requested original PNGs, other PNGs, optional whole hierarchies'}
    candidates = {}; summary = strict_json(outputs.get('mac-ui-summary.json', b'{}'))
    for item in items:
        if not item['attachment']['suggestedHumanReadableName'].startswith(PROOF_PREFIX): continue
        try:
            state, frame = correlated_frame(item, items, summary)
            candidates.setdefault(state, []).append(frame)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            item['attachment']['retention']['correlationError'] = str(error)[:300]
    # Re-serialize complete final metadata during selection; filenames never
    # determine state or priority. This includes all omission-record overhead.
    def materialize():
        for item in items:
            meta = item['attachment']['retention']; raw = outputs.get(item['relative'])
            if raw is not None:
                meta.update(retainedSHA256=digest(raw), retainedBytes=len(raw))
                if 'prefix' in item:
                    prefix = item['prefix']; hierarchy = item['hierarchy']
                    meta.update(rawPrefixSHA256=digest(prefix), rawPrefixBytes=len(prefix),
                                hierarchyBytes=len(hierarchy), hierarchySHA256=digest(hierarchy),
                                hierarchyRetained=raw == item['raw'])
                if item.get('correlation'): meta['auditCorrelation'] = item['correlation']
        for folder, groups in manifests.items():
            saved = copy.deepcopy(groups)
            for original, group in zip(groups, saved):
                related = [item for item in items if item['group'] is original]
                group['attachments'] = [item['attachment'] for item in related if item['relative'] in outputs]
                group['omittedAttachments'] = [dict(item['attachment'], omissionReason=item.get('omission', 'Optional image not selected within existing budget'))
                                                for item in related if item['relative'] not in outputs]
            outputs[folder + '/manifest.json'] = encoded(saved)
        outputs[REPORT] = encoded(result)
        require(len(outputs[REPORT]) <= 256_000, 'Selection metadata exceeded bounded size')
        return sum(map(len, outputs.values()))
    require(materialize() <= budget - ADMISSION_MARGIN, 'Mandatory raw findings/source/results exceed unchanged budget')
    def admit(item, reason):
        if sum(name.endswith('.png') for name in outputs) >= MAX_IMAGES:
            item['omission'] = 'Bounded 16-image subset already retained'; return False
        if item['attachment']['retention']['sourceBytes'] > MAX_PNG:
            item['omission'] = 'Original PNG exceeds 500000-byte image bound'; return False
        outputs[item['relative']] = item['raw']
        if materialize() > budget - ADMISSION_MARGIN:
            del outputs[item['relative']]; item['omission'] = reason; materialize(); return False
        return True
    for state in REQUESTED:
        matches = candidates.get(state, [])
        if len(matches) != 1:
            result['requested'][state]['reason'] = 'Missing or ambiguous explicit correlation'
            continue
        item = matches[0]
        if admit(item, 'Requested original PNG could not fit after mandatory raw evidence'):
            result['requested'][state] = {'status': 'retained', 'file': item['relative'], **item['correlation']}
        else: result['requested'][state] = {'status': 'omitted', 'reason': item['omission']}
    # General workflow pixels may help context, but never claim an audit state.
    for item in sorted(items, key=lambda item: (FOLDERS.index(item['folder']), item['attachment'].get('timestamp', 0), item['relative'])):
        if item['path'].suffix != '.png' or item['relative'] in outputs: continue
        if item['attachment']['retention']['sourceBytes'] > MAX_SOURCE: continue
        if item['attachment']['suggestedHumanReadableName'].startswith(FRAME_PREFIX):
            item.setdefault('omission', 'Requested frame lacks unique valid correlation or exceeds its budget')
            continue
        try: png_dimensions(item['raw'])
        except ValueError:
            item['omission'] = 'Invalid PNG bytes'; continue
        admit(item, 'Optional image exceeds remaining existing budget')
    for item in items:
        if not item.get('hierarchy'): continue
        outputs[item['relative']] = item['raw']
        if materialize() > budget - ADMISSION_MARGIN: outputs[item['relative']] = item['prefix']
    result['complete'] = not result['missingMandatory'] and all(row['status'] == 'retained' for row in result['requested'].values())
    # Every retained raw prefix and pixel has an exact original/retained hash.
    require(materialize() <= budget, 'Final manifest/report overhead exceeds unchanged budget')
    for item in items:
        if item['relative'] not in outputs: item['path'].unlink()
    for relative, raw in outputs.items(): (root / relative).write_bytes(raw)
    return result


def validate_selection(root, *, require_complete=False):
    root = Path(root); report = strict_json(read_file(root / REPORT, 256_000))
    require(type(report.get('schema')) is int and report['schema'] == 1 and report.get('limit') == LIMIT and report.get('metadataReserve') == RESERVE,
            'Invalid Mac selection contract')
    source = report.get('source', {})
    require(re.fullmatch('[0-9a-f]{40}', source.get('sha', '')) and source.get('workflow_sha') == source['sha']
            and source.get('tracked_source_clean') is True and re.fullmatch('[0-9a-f]{40}', source.get('tree', '')),
            'Missing exact-source provenance')
    for key in ('workflow_file_sha256', 'test_file_sha256'):
        require(re.fullmatch('[0-9a-f]{64}', source.get(key, '')), 'Missing source-file hash')
    if os.environ.get('GITHUB_SHA'): require(source['sha'] == os.environ['GITHUB_SHA'], 'Evidence belongs to another source')
    for relative, facts in report['rootFiles'].items():
        require(Path(relative).name == relative and relative != REPORT, 'Unsafe root evidence path')
        raw = read_file(root / relative)
        require(len(raw) == facts['bytes'] and digest(raw) == facts['sha256'], 'Mandatory root evidence changed')
    require(report['missingMandatory'] == sorted(set(REQUIRED_ROOT) - set(report['rootFiles'])), 'Mandatory result inventory changed')
    inventory = report.get('attachmentInventory')
    require(isinstance(inventory, dict) and len(inventory) <= 512, 'Missing original attachment inventory')
    seen = set(); items = []; frames = {}; retained_count = 0
    for folder in FOLDERS:
        path = root / folder / 'manifest.json'
        if not path.exists(): continue
        for group in strict_json(read_file(path, 1_000_000)):
            for omitted, records in ((False, group['attachments']), (True, group['omittedAttachments'])):
                for item in records:
                    name = item['exportedFileName']; require(re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)', name), 'Unsafe retained path')
                    relative = folder + '/' + name
                    require(relative not in seen and relative in inventory, 'Missing, duplicate or foreign original attachment')
                    seen.add(relative); facts = item['retention']; original = inventory[relative]
                    require(original.get('sourceSHA256') == facts.get('sourceSHA256') and original.get('sourceBytes') == facts.get('sourceBytes'),
                            'Original attachment provenance changed')
                    if omitted:
                        require(original.get('mandatoryText') is False and not (path.parent/name).exists()
                                and isinstance(item.get('omissionReason'), str) and item['omissionReason'],
                                'Mandatory text omitted or omission record contradicts files')
                        continue
                    raw = read_file(path.parent / name)
                    require(len(raw) == facts['retainedBytes'] and digest(raw) == facts['retainedSHA256'], 'Retained evidence changed')
                    if 'rawPrefixBytes' in facts:
                        require(type(facts['rawPrefixBytes']) is int and 0 <= facts['rawPrefixBytes'] <= len(raw)
                                and digest(raw[:facts['rawPrefixBytes']]) == facts['rawPrefixSHA256'], 'Raw finding prefix changed')
                    if name.endswith('.png'): retained_count += 1
                    row = {'folder': folder, 'group': group, 'attachment': item, 'raw': raw,
                           'path': path.parent/name, 'relative': relative}
                    items.append(row)
                    if 'auditCorrelation' in facts:
                        require(digest(raw) == facts['sourceSHA256'] and len(raw) == facts['sourceBytes'], 'Audit PNG was transformed')
                        require(png_dimensions(raw) == facts['auditCorrelation']['dimensions'], 'Audit PNG dimensions changed')
                        frames[relative] = facts['auditCorrelation']
    require(seen == set(inventory), 'An original finding/attachment disappeared without an omission record')
    require(retained_count <= MAX_IMAGES, 'Retained image count exceeds bound')
    summary = strict_json(read_file(root/'mac-ui-summary.json')) if (root/'mac-ui-summary.json').exists() else {}
    proven = {}; app_hashes = set()
    for item in items:
        if not item['attachment']['suggestedHumanReadableName'].startswith(PROOF_PREFIX): continue
        try:
            state, frame = correlated_frame(item, items, summary)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue # Invalid candidates may remain as mandatory diagnostic text.
        correlation = frame['correlation']; relative = frame['relative']
        require(relative in frames and frames[relative] == correlation, 'Saved correlation differs from retained proof')
        require(state not in proven, 'Duplicate retained proof for an audit state')
        proven[state] = relative; app_hashes.add((correlation['appExecutableSHA256'], correlation['appLogicSHA256']))
    require(len(app_hashes) <= 1, 'Requested frames belong to different app builds')
    require(set(report['requested']) == set(REQUESTED), 'Requested state inventory changed')
    for state, row in report['requested'].items():
        require(row.get('status') in ('retained', 'missing', 'omitted'), 'Unknown requested-state outcome')
        if row['status'] == 'retained': require(proven.get(state) == row['file'], 'Requested screenshot lacks retained exact proof/end record')
    require(set(frames) == set(proven.values()), 'A retained audit frame lacks valid original correlation')
    computed = not report['missingMandatory'] and all(row['status'] == 'retained' for row in report['requested'].values())
    require(report.get('complete') is computed, 'Contradictory completeness status')
    if require_complete: require(computed, 'Requested same-state audit evidence incomplete; inspect explicit omissions')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('root'); parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    if args.require_complete: validate_selection(args.root, require_complete=True)
    elif os.environ.get('TOUCHCOLOR_JOB_PLATFORM') == 'mac':
        require(int(os.environ['TOUCHCOLOR_EVIDENCE_LIMIT']) == LIMIT, 'Unexpected Mac evidence allocation')
        value = retain(args.root, provenance())
        print('MAC_EVIDENCE_SELECTION', json.dumps({'complete': value['complete'], 'requested': value['requested']}), flush=True)
