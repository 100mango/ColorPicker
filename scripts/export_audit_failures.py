#!/usr/bin/env python3
"""Export bounded per-device evidence within one source-defined run envelope."""
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

from uikit_runtime_diagnostics import MAX_OUTPUT_BYTES, MAX_PREPARATION_OUTPUT_BYTES

# All four fresh hosts use these same checked-in allocations and exact-source proof.
# Ten images at most; include base64, metadata and bounded child diagnostics.
# Raw attachment manifests and result bundles are read locally, never emitted.
ALLOCATIONS = {'iPadMini': 2, 'iPadLarge': 4, 'iPhoneCompact': 2, 'iPhoneLarge': 2}
MAX_IMAGE_BYTES = 500 * 1024
MAX_RUN_LOG_BYTES = 20_000_000
MAX_EXPORT_DIAGNOSTIC_BYTES = 4 * 1024
MAX_ISSUE_DESCRIPTION_LOG_BYTES = 24 * 1024  # Reallocated from child diagnostics; includes framing.
MAX_ISSUE_SOURCE_BYTES = 8 * 1024
MAX_EXPORTS_PER_DEVICE = 2  # Functional and accessibility result bundles.
MAX_RUNTIME_DIAGNOSTIC_BYTES = MAX_OUTPUT_BYTES + MAX_PREPARATION_OUTPUT_BYTES
# The same 32 KiB slot now contains at most 24 KiB runtime + 8 KiB preparation.
if MAX_RUNTIME_DIAGNOSTIC_BYTES != 32 * 1024: raise ValueError('Profile diagnostic allocation changed')
RESERVED_LOG_BYTES = (sum(ALLOCATIONS.values()) * (4 * ((MAX_IMAGE_BYTES + 2) // 3) + 16 * 1024)
                      + len(ALLOCATIONS) * (MAX_EXPORTS_PER_DEVICE * (MAX_EXPORT_DIAGNOSTIC_BYTES + 512)
                                            + MAX_ISSUE_DESCRIPTION_LOG_BYTES + MAX_RUNTIME_DIAGNOSTIC_BYTES))
if RESERVED_LOG_BYTES > MAX_RUN_LOG_BYTES: raise ValueError('Whole-run evidence allocation exceeds its cap')
family = os.environ['TC_TEST_FAMILY']
if family not in ALLOCATIONS: raise ValueError('Unknown evidence family')
limit = ALLOCATIONS[family]
print('EVIDENCE_BUDGET:' + json.dumps({'family': family, 'allocations': ALLOCATIONS,
    'maximum_image_bytes': MAX_IMAGE_BYTES, 'reserved_run_log_bytes': RESERVED_LOG_BYTES,
    'maximum_run_log_bytes': MAX_RUN_LOG_BYTES}, sort_keys=True))
exports = {}
emitted_images = []


def records(value, test_identifier=None):
    if isinstance(value, dict):
        test_identifier = value.get('testIdentifier', test_identifier)
        if 'exportedFileName' in value:
            yield dict(value, _testIdentifier=test_identifier)
        for child in value.values():
            yield from records(child, test_identifier)
    elif isinstance(value, list):
        for child in value:
            yield from records(child, test_identifier)


def attachment_path(destination, record):
    name = record['exportedFileName']
    if not isinstance(name, str) or pathlib.Path(name).name != name:
        raise ValueError('Attachment filename must be local to its export')
    path = destination / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Attachment must be an ordinary file inside its export')
    return path


def emit_issue_descriptions(destination, attachments):
    remaining = MAX_ISSUE_DESCRIPTION_LOG_BYTES - 512  # Final count/framing reserve.
    manifest_digest = hashlib.sha256((destination / 'manifest.json').read_bytes()).hexdigest()
    selected = [item for item in attachments
                if item.get('isAssociatedWithFailure') is True
                and item.get('suggestedHumanReadableName') == 'Complete Issue Description.txt'
                and (item.get('_testIdentifier') or '').startswith('TouchColorAccessibilityUITests/')]
    if not selected:
        print('AUDIT_ISSUE_DESCRIPTION_SUMMARY:{"selected":0,"emitted":0,"omitted_by_limit":0}', flush=True)
        return
    commit = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Exact tested source SHA is required for issue evidence')
    emitted = 0
    for item in selected[:8]:
        path = attachment_path(destination, item)
        before = path.stat()
        with path.open('rb') as handle:
            raw = handle.read(MAX_ISSUE_SOURCE_BYTES)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns) or not raw:
            raise ValueError('Generated issue attachment was empty or changed during its bounded read')
        original_size = before.st_size
        text = raw.decode('utf-8', errors='replace')
        while True:
            encoded_text = text.encode('utf-8')
            payload = {'family': family, 'suite': 'AccessibilityAudits', 'test': item['_testIdentifier'],
                'attachment': path.name, 'tested_commit': commit, 'manifest_sha256': manifest_digest,
                'source_bytes': original_size, 'captured_prefix_bytes': len(raw),
                'captured_prefix_sha256': hashlib.sha256(raw).hexdigest(),
                'text_sha256': hashlib.sha256(encoded_text).hexdigest(),
                'truncated': original_size > len(raw) or text != raw.decode('utf-8', errors='replace'),
                'utf8_replaced': raw.decode('utf-8', errors='replace').encode('utf-8') != raw,
                'text': text}
            # Keep textual diagnostics from accidentally resembling an image envelope.
            line = 'AUDIT_ISSUE_DESCRIPTION:' + json.dumps(payload, ensure_ascii=False, sort_keys=True).replace('SCREENSHOT_', 'SCREENSHOT\\u005f') + '\n'
            cost = len(line.encode('utf-8')) + 128  # Actions timestamp/line framing.
            if cost <= min(remaining, 8 * 1024):
                print(line, end='', flush=True); remaining -= cost; emitted += 1
                break
            if len(text) < 128:
                break
            text = text[:len(text) // 2]
    print('AUDIT_ISSUE_DESCRIPTION_SUMMARY:' + json.dumps({'selected': len(selected), 'emitted': emitted,
        'omitted_by_limit': len(selected)-emitted, 'byte_budget_including_framing': MAX_ISSUE_DESCRIPTION_LOG_BYTES}, sort_keys=True), flush=True)


def paired_issue_image(record, attachments, destination):
    test = record.get('_testIdentifier')
    if not test or not test.startswith('TouchColorAccessibilityUITests/'):
        return None
    matches = [item for item in attachments if item.get('_testIdentifier') == test
               and item.get('isAssociatedWithFailure') is True
               and (item.get('suggestedHumanReadableName') or '').startswith('App Screenshot')]
    if len(matches) != 1:
        return None
    path = attachment_path(destination, matches[0])
    # Preserve the generated issue pixels losslessly. Fall back to the existing
    # bounded JPEG if its original PNG cannot fit this same image slot.
    if path.stat().st_size > MAX_IMAGE_BYTES:
        return None
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'):
        return data
    return None


def require_requested_audit_frames(attachments, emitted):
    requested = {
        'testAccessibilityLiveCameraUnavailable': 'touchcolor-audit-failure-live',
        'testAccessibilitySampledPhoto': 'touchcolor-audit-failure-photo',
        'testAccessibilitySavedPalette': 'touchcolor-audit-failure-saved',
    }
    expected = set()
    for item in attachments:
        test = item.get('_testIdentifier') or ''
        if not test.startswith('TouchColorAccessibilityUITests/') or item.get('isAssociatedWithFailure') is not True:
            continue
        method = test.split('/')[-1].removesuffix('()')
        if method in requested: expected.add(requested[method])
    missing = expected - set(emitted)
    if missing: raise ValueError('Requested audit-state pixels were omitted: '+','.join(sorted(missing)))
    return sorted(expected)


def export_named(suite, names, limit):
    if limit <= 0:
        return 0
    result = pathlib.Path('build', family + '-' + suite + '.xcresult')
    if not (result / 'Info.plist').is_file():
        return 0
    if suite not in exports:
        destination = pathlib.Path('build', 'evidence', family, suite)
        destination.mkdir(parents=True, exist_ok=True)
        # A child's stderr can split a buffered SCREENSHOT_CHUNK in the Actions
        # stream. Keep all exporter diagnostics between complete envelopes.
        sys.stdout.flush()
        exported = subprocess.run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result), '--output-path', str(destination)], capture_output=True, text=True)
        diagnostics = (exported.stdout + exported.stderr).encode('utf-8')
        if diagnostics:
            bounded = diagnostics[:MAX_EXPORT_DIAGNOSTIC_BYTES].decode('utf-8', errors='ignore')
            print(bounded, end='' if bounded.endswith('\n') else '\n', flush=True)
            if len(diagnostics) > MAX_EXPORT_DIAGNOSTIC_BYTES:
                print(f'EXPORT_DIAGNOSTICS_TRUNCATED original_bytes={len(diagnostics)} limit={MAX_EXPORT_DIAGNOSTIC_BYTES}', flush=True)
        exported.check_returncode()
        exports[suite] = destination, list(records(json.loads((destination / 'manifest.json').read_text())))
        if suite == 'AccessibilityAudits':
            emit_issue_descriptions(*exports[suite])
    destination, attachments = exports[suite]
    count = 0
    for name in names:
        if count >= limit:
            break
        exact_name = re.compile(r'(?<![A-Za-z0-9-])' + re.escape(name) + r'(?![A-Za-z0-9-])')
        matches = [item for item in attachments if any(exact_name.search(value) for value in item.values() if isinstance(value, str))]
        if not matches:
            continue
        assert len(matches) == 1, f'Expected one {name}, found {len(matches)}'
        path = attachment_path(destination, matches[0])
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('Screenshot exceeds the existing image size cap')
        data = path.read_bytes()
        assert data.startswith(b'\xff\xd8') and len(data) <= MAX_IMAGE_BYTES
        requested_name = name
        source_record = matches[0]
        provenance = 'captured screen JPEG'
        if name.startswith('touchcolor-audit-failure-'):
            generated = paired_issue_image(matches[0], attachments, destination)
            if generated is not None:
                data = generated
                source_record = next(item for item in attachments if item.get('_testIdentifier') == matches[0].get('_testIdentifier')
                    and item.get('isAssociatedWithFailure') is True
                    and (item.get('suggestedHumanReadableName') or '').startswith('App Screenshot'))
                provenance = 'unmodified XCTest issue PNG'
                name += '-xctest-issue'
        commit = os.environ.get('GITHUB_SHA', '')
        if not re.fullmatch('[0-9a-f]{40}', commit): raise ValueError('Exact tested source SHA is required for frame evidence')
        encoded = base64.b64encode(data).decode('ascii')
        metadata = {'name':family+'-'+name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'tested_commit':commit,'suite':suite,'test':source_record.get('_testIdentifier'),
            'attachment':source_record['exportedFileName'],'provenance':provenance,
            'device_id':source_record.get('deviceId'),'timestamp':source_record.get('timestamp'),
            'manifest_sha256':hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()}
        print('SCREENSHOT_META:' + json.dumps(metadata,sort_keys=True))
        print(f'SCREENSHOT_BEGIN:{family}-{name}')
        for offset in range(0, len(encoded), 4096):
            print('SCREENSHOT_CHUNK:' + encoded[offset:offset + 4096])
        print(f'SCREENSHOT_END:{family}-{name}')
        sys.stdout.flush()
        emitted_images.append(requested_name)
        count += 1
    return count


# Every device retains its first functional failure and first distinct audit
# failure before filling a spare slot with another failure or a passing state.
functional_prefix = 'touchcolor-ipad-functional-failure-' if family.startswith('iPad') else 'touchcolor-phone-functional-failure-'
count = export_named('TouchColorUITests', [functional_prefix + '1'], 1)
count += export_named('AccessibilityAudits', [
    'touchcolor-audit-failure-live', 'touchcolor-audit-failure-photo', 'touchcolor-audit-failure-saved',
    'touchcolor-audit-failure-empty-compact', 'touchcolor-audit-failure-empty',
    'touchcolor-audit-failure-policy-error', 'touchcolor-audit-failure-policy-local-body',
    'touchcolor-audit-failure-import', 'touchcolor-audit-failure-import-help',
], limit - count)
if count < limit:
    count += export_named('TouchColorUITests', [functional_prefix + '2'], limit - count)
if family == 'iPadMini' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-review', 'touchcolor-palette-import-help'], limit - count)
if family == 'iPadMini' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-mini-audit-photo-state', 'touchcolor-mini-audit-saved-state'], limit - count)
if family == 'iPhoneCompact' and count < limit:
    count += export_named('TouchColorUITests', ['touchcolor-largest-paste-control-landscape'], limit - count)
if family in ('iPhoneCompact', 'iPadLarge') and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-review'], limit - count)
if family == 'iPhoneLarge' and count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-palette-import-help'], limit - count)
if family == 'iPadLarge' and 'AccessibilityAudits' in exports:
    required = require_requested_audit_frames(exports['AccessibilityAudits'][1], emitted_images)
    print('REQUESTED_AUDIT_FRAMES:' + json.dumps({'required':required,'all_emitted':True},sort_keys=True))
if count < limit:
    count += export_named('AccessibilityAudits', ['touchcolor-policy-local-body'], limit - count)
if count > limit: raise ValueError('Device image allocation exceeded')
print('EVIDENCE_IMAGES:' + json.dumps({'family': family, 'count': count, 'allocation': limit}))
