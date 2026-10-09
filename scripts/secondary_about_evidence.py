"""Closed, source-bound About proof, independent of original qualification gates.

Prepare an immutable receipt after actual attachment export and image encoding,
BEFORE the existing selectors hash root files. The final reader never mutates it.
Safe omissions remain downloadable and cannot qualify this additional gate.
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

REPORT = 'secondary-about-evidence.json'
MAX_REPORT = 256_000
MAX_AUDIT = 8192
MAX_FILE = 5_000_000
IMAGE = re.compile(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg)')
LABELS = {'mac': 'Mac', 'tv': 'TV', 'watch': 'Watch', 'vision': 'Vision'}
TEST_TARGETS = {'tv': 'TouchColorTVUITests', 'watch': 'TouchColorWatchUITests', 'vision': 'TouchColorVisionUITests'}
FILE = re.compile(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)')
CONTEXTS = {'mac': ('en app-menu', 'zh-Hans app-menu', 'en settings', 'zh-Hans settings'),
            'tv': ('empty', 'populated', 'zh-normal', 'zh-public-largest'),
            'watch': ('cold', 'zh', 'audit', 'zh-public-largest'),
            'vision': ('zh', 'audit')}



def require(ok, message):
    if not ok: raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def strict(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate secondary evidence key')
            result[key] = value
        return result
    def invalid(_): raise ValueError('Nonfinite secondary evidence value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def read(path, maximum=MAX_FILE):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum,
            'Unsafe or oversized secondary evidence file')
    raw = path.read_bytes(); after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Secondary evidence changed during read')
    return raw


def facts(raw): return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def title_matches(actual, title):
    return isinstance(actual, str) and (actual == title or actual.startswith(title + '_'))


def binding(environ=None):
    env = os.environ if environ is None else environ
    platform = env.get('TOUCHCOLOR_JOB_PLATFORM')
    require(platform in CONTEXTS, 'Unknown secondary evidence platform')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and env.get('GITHUB_WORKFLOW_SHA', sha) == sha,
            'Missing/mismatched secondary source SHA')
    if platform in ('vision', 'watch'):
        from native_text_rows import from_environment
        return from_environment(platform, sha, env)
    limit = 3_000_000 if platform == 'mac' else 2_000_000
    require(env.get('TOUCHCOLOR_EVIDENCE_LIMIT') == str(limit), 'Secondary evidence ceiling changed')
    return {'schema': 1, 'platform': platform, 'phase': 'normal', 'case': '', 'profile': '',
            'source_sha': sha, 'evidence_bytes': limit}


def validate_binding(value):
    require(isinstance(value, dict), 'Missing secondary binding')
    p = value.get('platform')
    if p in ('vision', 'watch'):
        from native_text_rows import validate
        validate(value)
    else:
        expected = {'schema': 1, 'platform': p, 'phase': 'normal', 'case': '', 'profile': '',
                    'source_sha': value.get('source_sha'), 'evidence_bytes': 3_000_000 if p == 'mac' else 2_000_000}
        require(p in ('mac', 'tv') and value == expected and type(value['schema']) is int
                and type(value['evidence_bytes']) is int and re.fullmatch('[0-9a-f]{40}', value.get('source_sha', '')),
                'Secondary binding contract changed')
    if os.environ.get('TOUCHCOLOR_SECONDARY_EVIDENCE_REQUIRED') == '1':
        require(value == binding(), 'Secondary evidence belongs to another row/source')


def requirements(bound, fallback=False):
    validate_binding(bound)
    p = bound['platform']; phase = bound['phase']; rows = []
    def add(method, context, folder, summary, screens=('About', 'Privacy')):
        for screen in screens:
            rows.append({'method': method, 'context': context, 'folder': folder, 'summary': summary,
                         'title': 'Native ' + LABELS[p] + ' secondary ' + screen + ' ' + context,
                         'audit': screen == 'About'})
    if p == 'mac':
        for locale, word in [('en', 'English'), ('zh-Hans', 'SimplifiedChinese')]:
            method = 'TouchColorMacUITests/testExplicitPrivacyContactHas' + word + 'LinkSemanticsWithoutOpeningMail()'
            add(method, locale + ' app-menu', 'screenshots', 'mac-ui-summary.json', ('About',))
            add(method, locale + ' settings', 'screenshots', 'mac-ui-summary.json')
    elif p == 'tv':
        for context in CONTEXTS[p]:
            method = 'testRemoteColorEditorAndMenuReturn' if context in ('empty', 'populated') else 'testChineseRemoteColorEditor'
            add('TVWorkflowTests/' + method + '()', context, 'tv-screenshots', 'tv-summary.json')
    elif p == 'watch':
        folder = 'watch-ui-screenshots' if phase == 'normal' else 'watch-largest-text-screenshots'
        summary = 'watch-ui-summary.json' if phase == 'normal' else 'watch-largest-text-summary.json'
        if phase == 'normal': add('WatchWorkflowTests/testHomeListDigitalCrownFromColdLaunch()', 'cold', folder, summary)
        add('WatchWorkflowTests/testChineseColorEditorSave()', 'zh', folder, summary)
        add('WatchWorkflowTests/testOfficialAccessibilityHomeAndColorEditor()', 'audit', folder, summary)
        if fallback:
            add('WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave()', 'zh-public-largest',
                'watch-public-trait-screenshots', 'watch-public-trait-summary.json')
    elif bound['case'] in ('chinese', 'canvas-audit'):
        method, context = (('testChinesePasteAndPrecisionControls', 'zh') if bound['case'] == 'chinese'
                           else ('testOfficialAccessibilityEmptyAndPastedCanvas', 'audit'))
        summary = 'vision-ui-summary.json' if phase == 'normal' else 'vision-largest-text-summary.json'
        add('VisionWorkflowTests/' + method + '()', context, 'vision-checkpoints', summary)
    return rows


def audit_title(platform, context): return 'Native ' + LABELS[platform] + ' secondary audit ' + context


def is_audit_title(title):
    return any(title_matches(title, audit_title(p, c)) for p in ('tv', 'watch', 'vision') for c in CONTEXTS[p])


def manifests(root):
    result = {}; count = total = 0
    for path in sorted(root.glob('*/manifest.json')):
        require(not path.parent.is_symlink(), 'Symlink secondary evidence directory')
        raw = read(path, MAX_REPORT); total += len(raw)
        groups = strict(raw); require(isinstance(groups, list) and len(groups) <= 64, 'Unbounded attachment groups')
        for group in groups:
            require(isinstance(group, dict) and isinstance(group.get('attachments'), list), 'Invalid attachment group')
            require(not group.get('omittedAttachments'), 'Secondary receipt must precede destructive retention')
            for item in group['attachments']:
                require(isinstance(item, dict) and FILE.fullmatch(item.get('exportedFileName', '')), 'Unsafe secondary attachment identity')
                count += 1
        result[path.parent.name] = groups
    require(count <= 512 and total <= 64 * 1024 * 1024, 'Unbounded secondary evidence inventory')
    return result


def runtime(root, platform):
    path = root / (platform + '-runtime.json')
    return strict(read(path)) if path.exists() else {}


def fallback_present(root, run):
    return run.get('public_trait_layout') is not None or any(root.glob('watch-public-trait-*'))


def candidates(root, groups, spec, platform, *, audit=False):
    folder = spec['folder']
    if audit and platform == 'vision':
        folder = 'vision-largest-text-screenshots' if 'largest-text' in spec['summary'] else 'vision-ui-screenshots'
    matches = []
    for group in groups.get(folder, []):
        # simctl's held checkpoints are bound to the single actual row method by runtime captures.
        if folder != 'vision-checkpoints' and group.get('testIdentifier') != spec['method']: continue
        for item in group['attachments']:
            title = item.get('suggestedHumanReadableName', '')
            if audit:
                match = (title.startswith('Native Mac accessibility issue audit summary ') if platform == 'mac'
                         else title_matches(title, audit_title(platform, spec['context'])))
                suffix = '.txt'
            else:
                match = title == spec['title'] if platform == 'vision' else title_matches(title, spec['title'])
                suffix = None
            name = item['exportedFileName']
            if not match or (suffix is not None and not name.endswith(suffix)) or (suffix is None and not IMAGE.fullmatch(name)): continue
            path = root / folder / name
            if not path.exists(): continue
            raw = read(path, MAX_AUDIT if audit else MAX_FILE)
            if audit and platform == 'mac' and ('\nState: secondary About ' + spec['context'] + '\n').encode() not in raw: continue
            matches.append({'path': folder + '/' + name, 'file': facts(raw), 'group': {key: group[key] for key in
                            ('testIdentifier', 'testIdentifierURL') if key in group}, 'attachment': copy.deepcopy(item)})
    return matches


def prepare(root, bound=None):
    root = Path(root); require(root.is_dir() and not root.is_symlink(), 'Unsafe secondary evidence root')
    bound = binding() if bound is None else bound; validate_binding(bound)
    require(not (root / REPORT).exists(), 'Secondary receipt already exists; no repeated collection')
    run = runtime(root, bound['platform'])
    fallback = bound['platform'] == 'watch' and fallback_present(root, run)
    expected = requirements(bound, fallback)
    if not expected: return None
    groups = manifests(root)
    entries = []
    for spec in expected:
        entries.append({'required': spec, 'images': candidates(root, groups, spec, bound['platform']),
                        'audits': candidates(root, groups, spec, bound['platform'], audit=True) if spec['audit'] else []})
    root_names = sorted({spec['summary'] for spec in expected} | ({bound['platform'] + '-runtime.json'} if bound['platform'] != 'mac' else set()))
    outcomes = {name: facts(read(root / name)) if (root / name).is_file() else None for name in root_names}
    record = {'schema': 1, 'binding': bound, 'fallback': fallback, 'entries': entries, 'outcomes': outcomes,
              'meaning': 'Original collection receipt only; final retained files and audit/test outcomes must independently validate'}
    raw = encoded(record); require(len(raw) <= MAX_REPORT, 'Secondary receipt exceeds metadata ceiling')
    (root / REPORT).write_bytes(raw)
    return record


def selected_paths(root):
    path = Path(root) / REPORT
    if not path.exists(): return set()
    record = strict(read(path, MAX_REPORT)); validate_binding(record.get('binding'))
    require([item['required'] for item in record.get('entries', [])] == requirements(record['binding'], record.get('fallback')),
            'Secondary receipt requirement inventory changed')
    return {item['path'] for entry in record['entries'] for kind in ('images', 'audits') for item in entry[kind]}


def finite(value): return type(value) in (int, float) and math.isfinite(value)


def current_item(root, item):
    relative = item.get('path', ''); parts = relative.split('/')
    require(len(parts) == 2 and parts[0] in ('screenshots', 'tv-screenshots', 'watch-ui-screenshots',
            'watch-largest-text-screenshots', 'watch-public-trait-screenshots', 'vision-checkpoints',
            'vision-ui-screenshots', 'vision-largest-text-screenshots') and FILE.fullmatch(parts[1]), 'Unsafe secondary receipt path')
    path = root / relative
    if not path.is_file(): return None
    raw = read(path)
    require(facts(raw) == item['file'], 'Secondary retained bytes/hash changed')
    manifest = root / parts[0] / 'manifest.json'
    require(manifest.is_file(), 'Missing secondary retained manifest')
    rows = [(group, a) for group in strict(read(manifest, MAX_REPORT)) for a in group.get('attachments', [])
            if a.get('exportedFileName') == parts[1]]
    require(len(rows) == 1, 'Missing/duplicate secondary manifest reference')
    group, attachment = rows[0]
    require(all(group.get(key) == value for key, value in item['group'].items()) and
            all(attachment.get(key) == value for key, value in item['attachment'].items()), 'Secondary manifest identity changed')
    return raw


def summary_passed(raw, item, platform):
    summary = strict(raw)
    if summary.get('result') != 'Passed' or summary.get('failedTests') != 0 or summary.get('testFailures') != []: return False
    rows = summary.get('devicesAndConfigurations')
    if not isinstance(rows, list) or len(rows) != 1: return False
    device = rows[0].get('device', {})
    expected_platform = {'mac': 'macOS', 'tv': 'tvOS Simulator', 'watch': 'watchOS Simulator', 'vision': 'visionOS Simulator'}[platform]
    if device.get('platform') != expected_platform or device.get('architecture') != 'arm64' or device.get('osVersion') != '27.0': return False
    held = item['path'].startswith('vision-checkpoints/')
    if not held and item['attachment'].get('deviceId') != device.get('deviceId'): return False
    timestamp = item['attachment'].get('timestamp')
    if not held and not (finite(timestamp) and finite(summary.get('startTime')) and finite(summary.get('finishTime'))
                                   and summary['startTime'] <= timestamp <= summary['finishTime']): return False
    return True


def complete(root):
    root = Path(root); path = root / REPORT
    if not path.exists():
        if os.environ.get('TOUCHCOLOR_SECONDARY_EVIDENCE_REQUIRED') != '1': return None
        return not requirements(binding())
    record = strict(read(path, MAX_REPORT)); require(record.get('schema') == 1, 'Unknown secondary receipt schema')
    bound = record['binding']; validate_binding(bound); p = bound['platform']
    require(type(record.get('fallback')) is bool, 'Unknown secondary fallback scope')
    expected = requirements(bound, record['fallback'])
    require([entry['required'] for entry in record['entries']] == expected, 'Secondary receipt requirement inventory changed')
    run = runtime(root, p) if p != 'mac' else {}
    if p != 'mac' and (run.get('sha') != bound['source_sha'] or run.get('platform') != p): return False
    if p == 'watch' and fallback_present(root, run) != record['fallback']: return False
    if bound['phase'] == 'system-largest':
        # Fallback pixels are diagnostic. Reuse the established actual setting,
        # readback/restoration, selected-method and result gate independently.
        from native_text_evidence import accepted
        try:
            if not accepted(root, bound, run): return False
        except (ValueError, OSError, TypeError, KeyError):
            return False
    outcome_names = {spec['summary'] for spec in expected} | ({p + '-runtime.json'} if p != 'mac' else set())
    require(set(record['outcomes']) == outcome_names, 'Secondary outcome inventory changed')
    result = True
    for name, original in record['outcomes'].items():
        require('/' not in name and name in {s['summary'] for s in expected} | {p + '-runtime.json'}, 'Foreign secondary outcome')
        if original is None or not (root / name).is_file(): result = False; continue
        require(facts(read(root / name)) == original, 'Secondary test outcome bytes changed')
    for entry in record['entries']:
        spec = entry['required']
        if len(entry['images']) != 1: result = False; continue
        item = entry['images'][0]; raw = current_item(root, item)
        if raw is None: result = False; continue
        require(IMAGE.fullmatch(Path(item['path']).name), 'Secondary screenshot is not an image attachment')
        png = raw.startswith(b'\x89PNG\r\n\x1a\n') and raw.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82')
        jpeg = raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9')
        if not (png or jpeg): result = False
        summary = root / spec['summary']
        if not summary.is_file(): result = False; continue
        if not summary_passed(read(summary), item, p): result = False
        if p == 'vision':
            from simulator_content_size import LARGEST
            captures = [c for c in run.get('captures', []) if c.get('name') == spec['title'] and c.get('success') is True
                        and Path(c.get('file', '')).stem == Path(item['path']).stem
                        and ((c.get('system_text_size') == LARGEST) if bound['phase'] == 'system-largest'
                             else not c.get('system_text_size'))]
            if len(captures) != 1: result = False
        if not spec['audit']: continue
        if len(entry['audits']) != 1: result = False; continue
        audit = entry['audits'][0]; audit_raw = current_item(root, audit)
        if audit_raw is None: result = False; continue
        require(len(audit_raw) <= MAX_AUDIT, 'Secondary audit exceeds bounded text')
        if p == 'mac':
            pattern = rb'Audit-ID: [0-9A-F-]{36}\nState: ' + re.escape(('secondary About ' + spec['context']).encode()) + rb'\nIssues: 0\nRecorded failures: 0\n?'
            if re.fullmatch(pattern, audit_raw) is None: result = False
        else:
            value = strict(audit_raw)
            klass, method = spec['method'].removesuffix('()').split('/')
            names = {'-[' + klass + ' ' + method + ']', '-[' + TEST_TARGETS[p] + '.' + klass + ' ' + method + ']'}
            expected_audit = {'schema': 1, 'state': 'secondary About ' + spec['context'], 'imageName': spec['title'],
                              'testName': value.get('testName'), 'outcome': 'passed'}
            if value != expected_audit or type(value.get('schema')) is not int or value.get('testName') not in names: result = False
        # XCTest exports bind the receipt to the same device and configuration.
        if not summary_passed(read(summary), audit, p): result = False
        if p != 'vision':
            a = item['attachment']; b = audit['attachment']
            if (a.get('deviceId') != b.get('deviceId') or a.get('configurationName') != b.get('configurationName')
                    or not finite(b.get('timestamp')) or a.get('timestamp', float('inf')) > b['timestamp']): result = False
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare', 'check'])
    parser.add_argument('root', nargs='?', default='build/evidence'); args = parser.parse_args()
    if args.action == 'prepare': value = prepare(args.root)
    else: value = {'complete': complete(args.root)}
    print(json.dumps({'applicable': value is not None, 'result': value if args.action == 'check' else 'collected'}))
