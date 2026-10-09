"""Bound source-bound Vision/Watch packets without silently losing required proof.

This is a filesystem-only selector and independent completeness check. Safe
partial packets retain explicit omissions; they can never qualify a native row.
No result, screenshot, system setting, or native execution proof is synthesized.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from native_text_rows import from_environment, report_binding, validate
from simulator_content_size import LARGEST

REPORT = 'native-text-evidence.json'
RESERVE = 16_384
MAX_FILE = 5_000_000
MAX_REPORT = 256_000
MAX_FILES = 256
MAX_INPUT_BYTES = 64 * 1024 * 1024
IMAGE = re.compile(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg)')
ATTACHMENT = re.compile(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)')
WATCH_PIXELS = (
    ('testChineseColorEditorSave', 'Native Watch Chinese color editor'),
    ('testOfficialAccessibilitySavedListSendAndCancel', 'Native Watch device-sized saved palette'),
    ('testOfficialAccessibilitySavedListSendAndCancel', 'Native Watch device-sized Send and Cancel'),
)
VISION_PIXELS = {
    'chinese': ('Native Vision Chinese pasted image and precision controls',),
    'paste-relaunch': ('Native Vision pasted image with precision sampling and zoom', 'Native Vision ordered palette after relaunch'),
    'png-export': ('Native Vision actual exported PNG reopened',),
    'json-export': ('Native Vision changed-color JSON export reopened with duplicates',),
    'photos': ('Native Vision actual system Photos import',),
    'files-select': ('Native Vision actual Files picker selected exported PNG',),
    # The current audit/cancel methods declare no explicit pixel checkpoint.
    'canvas-audit': (), 'corrupt-audit': (), 'cancel': (),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate evidence JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('Nonfinite evidence JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def facts(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read_file(path, maximum=MAX_FILE):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'Unsafe evidence file: ' + str(path))
    require(before.st_size <= maximum, 'Evidence file exceeds bounded read: ' + str(path))
    raw = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Evidence changed during read')
    return raw


def allowed(binding):
    platform = binding['platform']
    roots = {'architecture.txt', 'job-budget.json', REPORT,
             'secondary-about-evidence.json',
             platform + '-runtime.json', platform + '-summary.json',
             platform + '-ui-summary.json', platform + '-largest-text-summary.json'}
    folders = {platform + suffix for suffix in ('-screenshots', '-ui-screenshots', '-largest-text-screenshots')}
    if platform == 'vision':
        folders.add('vision-checkpoints')
    else:
        roots.add('watch-public-trait-summary.json')
        folders.add('watch-public-trait-screenshots')
    return roots, folders


def check_path(relative, binding):
    require(isinstance(relative, str), 'Non-string evidence path')
    parts = relative.split('/')
    roots, folders = allowed(binding)
    good = len(parts) == 1 and parts[0] in roots
    good = good or (len(parts) == 2 and parts[0] in folders and
                    (parts[1] == 'manifest.json' or ATTACHMENT.fullmatch(parts[1])))
    require(good, 'Unexpected evidence path: ' + relative)
    return relative


def scan(root, binding):
    require(root.is_dir() and not root.is_symlink(), 'Unsafe evidence root')
    roots, folders = allowed(binding)
    result = {}; source_bytes = 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            require(path.parent == root and path.name in folders, 'Unexpected evidence directory')
            continue
        check_path(relative, binding)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Unsafe evidence node: ' + relative)
        result[relative] = path
        source_bytes += info.st_size
        require(len(result) <= MAX_FILES, 'Evidence inventory exceeds finite bound')
        require(source_bytes <= MAX_INPUT_BYTES, 'Evidence source bytes exceed finite bound')
    return result


def discover(root):
    platform = os.environ.get('TOUCHCOLOR_JOB_PLATFORM')
    paths = [root / (name + '-runtime.json') for name in ('vision', 'watch')
             if (root / (name + '-runtime.json')).exists() or (root / (name + '-runtime.json')).is_symlink()]
    require(len(paths) <= 1, 'Ambiguous native evidence platform')
    if paths:
        runtime = strict_json(read_file(paths[0]))
        binding = report_binding(runtime)
        require(paths[0].name == binding['platform'] + '-runtime.json' and runtime.get('platform') == binding['platform'],
                'Runtime platform differs from exact row')
        return binding, runtime
    if platform in ('vision', 'watch'):
        return from_environment(platform, os.environ.get('GITHUB_SHA')), {}
    return None, {}


def attachment_rows(manifests, binding):
    rows = []
    seen = set()
    for relative, groups in manifests.items():
        check_path(relative, binding)
        require(relative.endswith('/manifest.json') and isinstance(groups, list), 'Invalid attachment manifest')
        for group in groups:
            require(isinstance(group, dict) and isinstance(group.get('attachments'), list), 'Invalid attachment group')
            require('omittedAttachments' not in group, 'Selection cannot hide earlier attachment omissions')
            for item in group['attachments']:
                require(isinstance(item, dict) and isinstance(item.get('exportedFileName'), str), 'Invalid attachment identity')
                name = item['exportedFileName']
                require(ATTACHMENT.fullmatch(name), 'Unsafe attachment filename')
                path = str(Path(relative).parent / name)
                require(path not in seen, 'Duplicate attachment identity')
                seen.add(path)
                require(len(seen) <= MAX_FILES, 'Attachment inventory exceeds finite bound')
                title = item.get('suggestedHumanReadableName', '')
                require(isinstance(title, str) and title.startswith('Native ' + binding['platform'].title()),
                        'Attachment has another platform provenance')
                rows.append((path, group, item))
    return rows


def requirements(binding, runtime, manifests, inventory):
    """Reconstruct mandatory identities from the closed row and original records."""
    platform = binding['platform']
    phase = binding['phase']
    required = {platform + '-runtime.json', platform + '-summary.json',
                platform + ('-ui-summary.json' if phase == 'normal' else '-largest-text-summary.json')}
    # Raw diagnostic/result JSON is never quietly discarded just because it is
    # not the currently selected result. Fallback proof remains a failed gate.
    required.update(name for name in inventory if '/' not in name and name != 'job-budget.json')
    if platform == 'watch' and (runtime.get('public_trait_layout') is not None or
            any(name.startswith('watch-public-trait-') for name in inventory)):
        required.add('watch-public-trait-summary.json')
    rows = attachment_rows(manifests, binding)
    missing = []
    if platform == 'watch':
        folder = 'watch-ui-screenshots' if phase == 'normal' else 'watch-largest-text-screenshots'
        for method, title in WATCH_PIXELS:
            matches = [path for path, group, item in rows if str(Path(path).parent) == folder
                       and group.get('testIdentifier') == 'WatchWorkflowTests/' + method + '()'
                       and (item['suggestedHumanReadableName'] == title or item['suggestedHumanReadableName'].startswith(title + '_'))
                       and item.get('deviceId') == runtime.get('device', {}).get('udid') and IMAGE.fullmatch(Path(path).name)]
            if len(matches) != 1:
                missing.append('Missing or ambiguous pixel: ' + title)
            required.update(matches)
        # Preserve every already-exported normal screenshot and failure image,
        # including the other workflow methods; no pathname-priority eviction.
        required.update(path for path, _, _ in rows if IMAGE.fullmatch(Path(path).name))
    else:
        captures = runtime.get('captures', [])
        require(isinstance(captures, list) and len(captures) <= 16, 'Invalid bounded capture inventory')
        for title in VISION_PIXELS[binding['case']]:
            matches = [capture for capture in captures if isinstance(capture, dict) and capture.get('name') == title
                       and capture.get('success') is True and
                       ((capture.get('system_text_size') == LARGEST) if phase == 'system-largest' else not capture.get('system_text_size'))]
            if len(matches) != 1:
                missing.append('Missing or ambiguous checkpoint: ' + title)
        for capture in captures:
            if not isinstance(capture, dict) or capture.get('success') is not True:
                continue
            name = capture.get('file', '')
            require(isinstance(name, str) and IMAGE.fullmatch(name), 'Unsafe capture identity')
            matches = [path for path, _, item in rows if str(Path(path).parent) == 'vision-checkpoints'
                       and Path(path).stem == Path(name).stem and IMAGE.fullmatch(Path(path).name)
                       and item['suggestedHumanReadableName'] == capture.get('name')]
            if len(matches) != 1:
                missing.append('Missing or ambiguous captured file: ' + name)
            required.update(matches)
        required.update(path for path, _, _ in rows if IMAGE.fullmatch(Path(path).name))
    # Preserve already-bounded raw diagnostics (e.g. Photos text); omissions
    # remain visible and fail completeness, including failure-only artifacts.
    required.update(path for path, _, _ in rows if path.endswith('.txt'))
    return sorted(required), sorted(set(missing))


def materialize(binding, inventory, manifests, required, missing, selected, raw):
    omitted = {name: {'reason': 'Missing at collection' if item.get('missing') else
                    'Source file exceeds upload file bound' if item['bytes'] > MAX_FILE else 'Does not fit exact row cap',
                    'mandatory': name in required, **item}
               for name, item in inventory.items() if name not in selected and not name.endswith('/manifest.json')}
    outputs = {name: raw[name] for name in selected}
    for name, groups in manifests.items():
        groups = copy.deepcopy(groups)
        for group in groups:
            original = group['attachments']
            group['attachments'] = [item for item in original if str(Path(name).parent / item['exportedFileName']) in selected]
            group['omittedAttachments'] = [dict(item, omission=omitted[str(Path(name).parent / item['exportedFileName'])])
                                          for item in original if str(Path(name).parent / item['exportedFileName']) not in selected]
        outputs[name] = encoded(groups)
    record = {'schema': 1, 'row': binding, 'metadataReserve': RESERVE,
              'originalFiles': inventory, 'originalManifests': manifests,
              'requiredFiles': required, 'missingProof': missing, 'omissions': omitted,
              'retainedFiles': {name: facts(value) for name, value in outputs.items()}}
    outputs[REPORT] = encoded(record)
    require(len(outputs[REPORT]) <= MAX_REPORT, 'Evidence selection report exceeds bounded metadata size')
    return record, outputs


def retain(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Unsafe evidence root')
    if (root / REPORT).exists() or (root / REPORT).is_symlink():
        result = strict_json(read_file(root / REPORT, MAX_REPORT))
        result['complete'] = evidence_complete(root)
        return result
    binding, runtime = discover(root)
    if binding is None:
        return None
    paths = scan(root, binding)
    raw = {}; inventory = {}; manifests = {}; source_bytes = 0
    for name, path in paths.items():
        if name == 'job-budget.json':
            value = read_file(path, min(RESERVE, MAX_INPUT_BYTES - source_bytes))
            source_bytes += len(value)  # Controller may refresh this after selection.
            continue
        # Reapply the aggregate bound at read time; a source growing after the
        # initial stat scan must not make many individually bounded reads OOM.
        value = read_file(path, MAX_INPUT_BYTES - source_bytes)
        source_bytes += len(value)
        inventory[name] = facts(value)
        if len(value) <= MAX_FILE:
            raw[name] = value
        if name.endswith('/manifest.json'):
            require(len(value) <= MAX_REPORT, 'Oversized source manifest')
            manifests[name] = strict_json(value)
    for name, _, _ in attachment_rows(manifests, binding):
        if name not in inventory:
            inventory[name] = {'bytes': 0, 'sha256': None, 'missing': True}
    require(len(inventory) <= MAX_FILES, 'Evidence inventory including missing files exceeds finite bound')
    # Reject unmanifested pixels/text instead of quietly adopting unknown files.
    attached = {name for name, _, _ in attachment_rows(manifests, binding)}
    require(all('/' not in name or name.endswith('/manifest.json') or name in attached for name in inventory),
            'Unmanifested evidence attachment')
    required, missing = requirements(binding, runtime, manifests, inventory)
    missing += ['Missing required file: ' + name for name in required if name not in inventory]
    selected = set()
    budget = binding['evidence_bytes'] - RESERVE
    record, outputs = materialize(binding, inventory, manifests, required, sorted(set(missing)), selected, raw)
    require(sum(map(len, outputs.values())) <= budget, 'Omission/provenance metadata cannot fit exact row cap')
    def priority(name):
        if name == binding['platform'] + '-runtime.json': return (0, name)
        if '/' not in name and name in required: return (1, name)
        return (2 if name in required else 3, name)
    for name in sorted(raw, key=priority):
        if name.endswith('/manifest.json'):
            continue
        selected.add(name)
        trial, trial_outputs = materialize(binding, inventory, manifests, required, sorted(set(missing)), selected, raw)
        if sum(map(len, trial_outputs.values())) <= budget:
            record, outputs = trial, trial_outputs
        else:
            selected.remove(name)
    # Recheck original hashes immediately before any destructive selection.
    for name, path in paths.items():
        if name != 'job-budget.json':
            require(facts(read_file(path, MAX_INPUT_BYTES)) == inventory[name], 'Source evidence changed during selection')
    for name, path in paths.items():
        if name != 'job-budget.json' and name not in outputs:
            path.unlink()
    for name, value in outputs.items():
        (root / name).write_bytes(value)
    result = dict(record)
    result['complete'] = evidence_complete(root)
    return result


def summary_counts(summary, device, total, skipped=0):
    expected = {'totalTestCount': total, 'passedTests': total - skipped, 'failedTests': 0,
                'skippedTests': skipped, 'expectedFailures': 0}
    if (summary.get('result') != 'Passed' or summary.get('testFailures') != [] or
            any(type(summary.get(k)) is not int or summary[k] != v for k, v in expected.items())):
        return False
    rows = summary.get('devicesAndConfigurations')
    if not isinstance(rows, list) or len(rows) != 1:
        return False
    row = rows[0]
    if any(type(row.get(k)) is not int or row[k] != v for k, v in expected.items() if k != 'totalTestCount'):
        return False
    target = row.get('device', {})
    return (target.get('deviceId') == device and target.get('platform') == 'watchOS Simulator'
            and target.get('architecture') == 'arm64' and target.get('osVersion') == '27.0')


def successful_stage(runtime, bundle, selectors, summary):
    device = runtime.get('device', {}).get('udid')
    matches = []
    for stage in runtime.get('stages', []):
        command = stage.get('command', [])
        if '-resultBundlePath' in command and command.count('-resultBundlePath') == 1 and command[command.index('-resultBundlePath') + 1] == bundle:
            matches.append(stage)
    if len(matches) != 1:
        return False
    stage = matches[0]; command = stage['command']
    if (command[:2] != ['xcodebuild', 'test-without-building'] or command.count('-destination') != 1 or
            command[command.index('-destination') + 1] != 'platform=watchOS Simulator,id=' + str(device) or
            sorted(x for x in command if x.startswith(('-only-testing:', '-skip-testing:'))) != sorted(selectors) or
            type(stage.get('exit')) is not int or stage['exit'] != 0 or stage.get('started') is not True or
            stage.get('process_group_gone') is not True or stage.get('capture_reader_finished') is not True or
            stage.get('reader_errors') != [] or stage.get('cleanup_error') is not None or
            stage.get('budget_incomplete') or stage.get('timed_out')):
        return False
    try:
        start = datetime.datetime.fromisoformat(stage['started_at'])
        finish = datetime.datetime.fromisoformat(stage['finished_at'])
        return (start.tzinfo is not None and finish.tzinfo is not None and
                type(summary.get('startTime')) in (int, float) and type(summary.get('finishTime')) in (int, float) and
                start.timestamp() - .001 <= summary['startTime'] < summary['finishTime'] <= finish.timestamp() + .001)
    except (KeyError, TypeError, ValueError):
        return False


def probe_proven(setting, runtime, binding):
    """Require the recorded owned setter/readback/UI/restoration sequence."""
    from simulator_content_size import supported_syntax
    if setting.get('native_text_row') != binding or setting.get('runtime') != runtime.get('runtime'):
        return False
    operations = setting.get('operations')
    if not isinstance(operations, list) or not 7 <= len(operations) <= 9:
        return False
    labels = [item.get('label') for item in operations if isinstance(item, dict)]
    if len(labels) != len(operations) or len(labels) != len(set(labels)):
        return False
    by_label = {item['label']: item for item in operations}
    original = setting.get('observed_original')
    base = ['xcrun', 'simctl', 'ui', setting['device'], 'content_size']
    expected = ['help', 'device_inventory', 'read_original']
    if original != LARGEST:
        expected.append('set_largest')
    expected += ['read_largest', 'actual_ui', 'read_before_restore']
    before = by_label.get('read_before_restore', {}).get('output')
    if not isinstance(before, str):
        return False
    before_exit = by_label.get('read_before_restore', {}).get('operation', {}).get('exit')
    if before_exit != 0 or before.strip() != original:
        expected.append('restore_original')
    expected.append('read_restored')
    if labels != expected:
        return False
    commands = {'help': ['xcrun', 'simctl', 'help', 'ui'],
                'device_inventory': ['xcrun', 'simctl', 'list', 'devices', '-j'],
                'read_original': base, 'set_largest': base + [LARGEST],
                'read_largest': base, 'read_before_restore': base,
                'restore_original': base + [original], 'read_restored': base}
    ui = [stage['command'] for stage in runtime.get('stages', [])
          if 'build/watch-largest-text.xcresult' in stage.get('command', [])]
    if len(ui) != 1:
        return False
    commands['actual_ui'] = ui[0]
    for item in operations:
        operation = item.get('operation', {})
        label = item['label']
        # The actual probe deliberately reconciles a completed setter failure
        # using its following successful readback. Preserve that behavior;
        # unknown cleanup is never reconcilable. A failed pre-restore read
        # likewise requires an explicit restore followed by a verified read.
        reconciled = label in ('set_largest', 'restore_original', 'read_before_restore')
        if (operation.get('command') != commands[label] or type(operation.get('exit')) is not int or (operation['exit'] != 0 and not reconciled)
                or operation.get('cleanup_confirmed') is not True or operation.get('command_started') is False
                or operation.get('output_limit_exceeded') or not isinstance(item.get('output'), str)):
            return False
        if label == 'actual_ui':
            if (operation.get('process_group_gone') is not True or operation.get('capture_reader_finished') is not True
                    or operation.get('timeout_seconds') != 600):
                return False
        elif operation.get('state') != 'completed' or operation.get('timeout_seconds') != 15:
            return False
    # probe.run retains raw diagnostic output but returns text.strip() to the
    # caller, which is the exact value hashed by simulator_content_size.probe.
    help_text = by_label['help']['output'].strip()
    choices = supported_syntax(help_text)
    if (not choices or original not in choices or setting.get('help_advertised_sizes') != sorted(choices)
            or setting.get('help_sha256') != hashlib.sha256(help_text.encode()).hexdigest()):
        return False
    return (by_label['read_original']['output'].strip() == original
            and by_label['read_largest']['output'].strip() == LARGEST
            and by_label['read_restored']['output'].strip() == original)


def accepted(root, binding, runtime):
    if (runtime.get('result') != 'passed' or runtime.get('tests') != 'passed' or
            any(runtime.get(key) for key in ('error', 'failures', 'summary_error', 'cleanup_unconfirmed', 'budget_incomplete'))):
        return False
    if binding['platform'] == 'vision':
        from vision_offline_result import evidence_complete as vision_complete
        return vision_complete(root)
    from native_content_size import qualified, verify_summary, WATCH_CASES
    from watch_failure_continuation import NORMAL_CASES
    if runtime.get('watch_profile') != binding['profile']:
        return False
    forbidden_bundle = 'build/watch-largest-text.xcresult' if binding['phase'] == 'normal' else 'build/watch-ui.xcresult'
    if any(forbidden_bundle in stage.get('command', []) for stage in runtime.get('stages', [])):
        return False
    device = runtime.get('device', {}).get('udid')
    hosted = strict_json(read_file(root / 'watch-summary.json'))
    hosted_skipped = hosted.get('skippedTests')
    # One existing ImageIO encoder test may legitimately skip on this runtime;
    # an all-52-pass result is stronger and must remain accepted.
    if type(hosted_skipped) is not int or hosted_skipped not in (0, 1) or not summary_counts(hosted, device, 52, hosted_skipped):
        return False
    recorded = runtime.get('xctest_summary', {})
    if (any(recorded.get(key) != hosted.get(key) for key in ('result', 'passedTests', 'failedTests', 'skippedTests', 'totalTestCount'))
            or recorded.get('failures') != [] or not successful_stage(runtime, 'build/watch-tests.xcresult',
            ['-only-testing:TouchColorWatchTests'], hosted)):
        return False
    if binding['phase'] == 'normal':
        summary = strict_json(read_file(root / 'watch-ui-summary.json'))
        normal = runtime.get('normal_watch_ui', {})
        return (normal.get('result') == 'passed' and type(normal.get('exit')) is int and normal['exit'] == 0 and
                not runtime.get('largest_system_text') and not runtime.get('public_trait_layout') and
                summary_counts(summary, device, len(NORMAL_CASES), 1) and successful_stage(runtime, 'build/watch-ui.xcresult',
                ['-only-testing:TouchColorWatchUITests', '-skip-testing:TouchColorWatchUITests/WatchWorkflowTests/testPublicLargestTraitChineseColorEditorSave'], summary))
    setting = runtime.get('largest_system_text', {})
    if (not qualified(setting) or setting.get('device') != device or runtime.get('public_trait_layout') is not None
            or runtime.get('normal_watch_ui') is not None or setting.get('requested_largest') != LARGEST
            or type(setting.get('ui_exit')) is not int or runtime.get('largest_text_outcome') != {'result': 'passed'}
            or not probe_proven(setting, runtime, binding)):
        return False
    summary = strict_json(read_file(root / 'watch-largest-text-summary.json'))
    if not summary_counts(summary, device, len(WATCH_CASES)):
        return False
    if (setting.get('observed_original') != setting.get('observed_restored') or not setting.get('observed_original') or
            setting.get('verified_results') != verify_summary(summary, device, 'watchOS Simulator', len(WATCH_CASES))):
        return False
    operation = setting.get('summary_operation', {})
    if (operation.get('command') != ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', 'build/watch-largest-text.xcresult'] or
            type(operation.get('exit')) is not int or operation['exit'] != 0 or operation.get('cleanup_confirmed') is not True
            or operation.get('timeout_seconds') != 30 or operation.get('state') != 'completed'):
        return False
    return successful_stage(runtime, 'build/watch-largest-text.xcresult',
                            ['-only-testing:TouchColorWatchUITests/WatchWorkflowTests/' + name for name in WATCH_CASES], summary)


def evidence_complete(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Unsafe evidence root')
    if not (root / REPORT).exists() and not (root / REPORT).is_symlink():
        if os.environ.get('TOUCHCOLOR_JOB_PLATFORM') in ('vision', 'watch'):
            return False  # Early safe/fallback packet; it has no selection proof.
        binding, _ = discover(root)
        return binding is None
    record = strict_json(read_file(root / REPORT, MAX_REPORT))
    require(type(record.get('schema')) is int and record['schema'] == 1 and record.get('metadataReserve') == RESERVE,
            'Invalid native evidence selection contract')
    binding = validate(record.get('row'))
    if os.environ.get('TOUCHCOLOR_JOB_PLATFORM') in ('vision', 'watch'):
        require(binding == from_environment(binding['platform'], binding['source_sha']), 'Evidence row differs from current job')
    paths = scan(root, binding)
    require(sum(path.stat().st_size for path in paths.values()) <= binding['evidence_bytes'], 'Native evidence exceeds exact row cap')
    require(sum(path.stat().st_size for name, path in paths.items() if name != 'job-budget.json') <= binding['evidence_bytes'] - RESERVE,
            'Native evidence consumes metadata reserve')
    budget_failed = False
    if 'job-budget.json' in paths:
        budget = strict_json(read_file(paths['job-budget.json'], RESERVE))
        require(isinstance(budget, dict), 'Invalid budget diagnostic metadata')
        require(('sha' not in budget or budget['sha'] == binding['source_sha']) and
                ('platform' not in budget or budget['platform'] == binding['platform']), 'Budget metadata belongs to another row source')
        budget_failed = (budget.get('result') in ('failed_or_incomplete', 'incomplete') or
                         any(budget.get(key) for key in ('failure', 'cleanup_failure', 'phase_failures', 'cleanup_unconfirmed')))
    inventory = record.get('originalFiles'); manifests = record.get('originalManifests'); retained = record.get('retainedFiles')
    require(isinstance(inventory, dict) and len(inventory) <= MAX_FILES and isinstance(manifests, dict) and isinstance(retained, dict),
            'Invalid original evidence inventory')
    for name, item in inventory.items():
        check_path(name, binding)
        require(name not in (REPORT, 'job-budget.json') and isinstance(item, dict) and type(item.get('bytes')) is int and 0 <= item['bytes'] <= MAX_INPUT_BYTES,
                'Invalid original file identity')
        require((item.get('missing') is True and item['bytes'] == 0 and item.get('sha256') is None) or
                (not item.get('missing') and isinstance(item.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', item['sha256'])),
                'Missing original file hash')
    attachment_rows(manifests, binding)
    require(set(manifests) == {name for name in inventory if name.endswith('/manifest.json')}, 'Original manifest inventory changed')
    require(set(paths) - {REPORT, 'job-budget.json'} <= set(retained), 'Uninventoried retained evidence')
    missing_paths = set(retained) - set(paths)
    for name, item in retained.items():
        check_path(name, binding)
        require(name in inventory and isinstance(item, dict), 'Retained file lacks original identity')
        if name in paths:
            require(facts(read_file(paths[name])) == item, 'Retained evidence hash/bytes changed: ' + name)
        if not name.endswith('/manifest.json'):
            require(item == inventory[name], 'Original mandatory evidence mutated: ' + name)
    runtime_name = binding['platform'] + '-runtime.json'
    runtime = strict_json(read_file(paths[runtime_name])) if runtime_name in paths else {}
    if runtime:
        require(report_binding(runtime) == binding and runtime.get('platform') == binding['platform'], 'Retained runtime row changed')
    required, missing = requirements(binding, runtime, manifests, inventory)
    # An omitted runtime prevents reconstruction of captures/fallback details;
    # nevertheless its original required set cannot make the packet complete.
    if runtime:
        require(record.get('requiredFiles') == required, 'Required proof inventory changed')
        expected_missing = sorted(set(missing + ['Missing required file: ' + name for name in required if name not in inventory]))
        require(record.get('missingProof') == expected_missing, 'Missing proof inventory changed')
    selected = set(retained) - set(manifests)
    raw = {name: read_file(paths[name]) for name in selected if name in paths}
    # Reconstruct omission/manifests from the original inventory, independently
    # of the stored final manifest references and their self-reported hashes.
    if not missing_paths:
        expected_record, expected_outputs = materialize(binding, inventory, manifests, record['requiredFiles'], record['missingProof'], selected, raw)
        require(record == expected_record, 'Selection/omission provenance changed')
        require(all(read_file(paths[name]) == value for name, value in expected_outputs.items() if name.endswith('/manifest.json')),
                'Attachment omission manifest changed')
    if (budget_failed or missing_paths or not runtime or record.get('missingProof') or
            any(name not in paths for name in required) or any(value.get('mandatory') for value in record['omissions'].values())):
        return False
    return accepted(root, binding, runtime)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['retain'])
    parser.add_argument('root', nargs='?', default='build/evidence')
    args = parser.parse_args()
    result = retain(args.root)
    print(json.dumps({'platform': result['row']['platform'], 'complete': result['complete']} if result else {'applicable': False}))
