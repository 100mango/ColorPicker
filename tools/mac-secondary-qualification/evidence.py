"""Per-row adaptation of frozen Mac selectors; exact two-job composition only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import types
import uuid

import io_boundary as io
import runtime_contract
import source_guard as source

LIMIT = 3_000_000
ROOT = io.REPO / 'build/evidence'
HASHES = {
 'retain_mac_evidence': 'eaf7ef9c2b908d435134b0ed161fa7813eb98110f83679b44403bb7ac51dcfce',
 'secondary_about_evidence': '32fa7f09bebf77874e5de0f45fde51358d03278d9882fcb7dad0667d1171fa3a',
 'palette_lifecycle_diagnostics': 'cc0a0afbdfd447ac46a4c996f03466d949cf4b907423c61858ff860802485cfa',
 'mac_passive_lifecycle': '0d136a2f9b793cceedaf43c823e488f0a79578d859eb3934de12cdd9ee93ce30',
}
SANDBOX_IMAGES = {
 'Native Mac actual Photos imported source and green pixel': 'TouchColorMacUITests/testSystemPhotosImportSamplesActualImageInsideSandbox()',
 'Native Mac actual sandbox process proof': 'TouchColorMacUITests/testSandboxBoundaryMatchesExactAppConfiguration()',
}
STATES = {
 'empty workspace': 'testOfficialAccessibilityEmptyAndPopulatedCanvas',
 'full image and palette': 'testOfficialAccessibilityEmptyAndPopulatedCanvas',
 'camera availability': 'testOfficialAccessibilityCameraAndPrivacy',
 'offline privacy': 'testOfficialAccessibilityCameraAndPrivacy',
 'corrupt import error': 'testOfficialAccessibilityCorruptImportRetainsPreviousSource',
 'secondary About en app-menu': 'testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail',
 'secondary About en settings': 'testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail',
 'secondary About zh-Hans app-menu': 'testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail',
 'secondary About zh-Hans settings': 'testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail'}


def require(value, message):
    if not value:
        raise ValueError(message)


def put(name, value):
    io.write(ROOT / name, io.encoded(value), replace=(ROOT / name).exists())


def checked_source(name):
    raw = io.read(io.REPO / 'scripts' / (name + '.py'), 256_000)
    require(hashlib.sha256(raw).hexdigest() == HASHES[name], 'Frozen evidence reader changed: ' + name)
    return raw.decode('utf-8')


def replace_one(text, old, new):
    require(text.count(old) == 1, 'Evidence derivation hunk changed')
    return text.replace(old, new, 1)


def load_derived(name, text, namespace):
    module = types.ModuleType('mac_derived_' + name)
    module.__file__ = str(io.REPO / 'scripts' / (name + '.py'))
    module.__dict__.update(namespace)
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


def readers(controller):
    def actual_mac_device(device):
        h = controller.host
        return (isinstance(device, dict) and device.get('platform') == 'macOS' and device.get('architecture') == 'arm64'
                and (device.get('osVersion'), device.get('osBuildNumber'), device.get('deviceId')) ==
                (h['version'], h['build'], h['destination_id']))
    text = checked_source('secondary_about_evidence')
    text = replace_one(text, "device.get('osVersion') != '27.0'", "not actual_mac_device(device)")
    text = replace_one(text, "    held = item['path'].startswith('vision-checkpoints/')", "    if item['attachment'].get('configurationName') != rows[0].get('testPlanConfiguration', {}).get('configurationName'): return False\n    held = item['path'].startswith('vision-checkpoints/')")
    text = replace_one(text, '(root / REPORT).write_bytes(raw)', 'safe_write(root / REPORT, raw)')
    secondary = load_derived('secondary_about_evidence', text, {'actual_mac_device': actual_mac_device, 'safe_write': io.write})
    secondary.read = lambda path, maximum=5_000_000: io.read(path, maximum)
    text = checked_source('retain_mac_evidence')
    text = replace_one(text, 'from bounded_process import check_output', 'check_output = forbidden_native_provenance')
    text = replace_one(text, "and device.get('osVersion') == '27.0'", 'and actual_mac_device(device)')
    # The frozen combined selector is never told missing summaries exist. Each
    # separately labelled row uses only its actual required root outcomes.
    text = replace_one(text, "for name in sorted(present) if name != 'job-budget.json'", 'for name in sorted(present)')
    start = text.index('REQUIRED_ROOT = ')
    end = text.index('\nREQUESTED = ', start)
    roots = ['architecture.txt', 'accessibility-api.json', 'mac-command-receipts.json', 'mac-host.json',
             'job-budget.json', 'mac-row-native-binding.json']
    roots += ['mac-unit-summary.json', 'mac-ui-summary.json'] if controller.lane == 'normal' else [
        'mac-sandbox-summary.json', 'mac-sandbox-entitlements.json', 'mac-sandbox-post-entitlements.json', 'mac-sandbox-boundary.json']
    text = text[:start] + 'REQUIRED_ROOT = ' + repr(tuple(roots)) + text[end:]
    if controller.lane == 'sandbox':
        start = text.index('REQUESTED = ')
        end = text.index('\nPROOF_PREFIX = ', start)
        text = text[:start] + 'REQUESTED = {}\n' + text[end:]
        text = replace_one(text, '    for state in REQUESTED:\n',
            "    for item in items:\n        if item['relative'] in mandatory_sandbox:\n            admit(item, 'Mandatory sandbox original image cannot fit unchanged cap')\n    for state in REQUESTED:\n")
    text = replace_one(text, "    '100mango/ColorPicker',", "    '100mango/ColorPicker',") if False else text
    def no_native(*args, **kwargs):
        raise ValueError('All provenance commands must use the owning controller before pure retention')
    text = replace_one(text, "if item['relative'] not in outputs: item['path'].unlink()", "if item['relative'] not in outputs: safe_unlink(item['path'])")
    text = replace_one(text, "(root / LIFECYCLE_FILE).unlink()", "safe_unlink(root / LIFECYCLE_FILE)")
    text = replace_one(text, "for relative, raw in outputs.items(): (root / relative).write_bytes(raw)", "for relative, raw in outputs.items(): safe_write(root / relative, raw, replace=True)")
    require(text.count("Path(identity['workflow_file']).read_bytes()") == 2, "Workflow read derivation differs")
    text = text.replace("Path(identity['workflow_file']).read_bytes()", "read_file(Path(identity['workflow_file']))")
    derived = {'retain_mac_evidence': hashlib.sha256(text.encode()).hexdigest()}
    module = load_derived('retain_mac_evidence', text, {'actual_mac_device': actual_mac_device,
             'safe_unlink': io.unlink_owned, 'safe_write': io.write,
             'forbidden_native_provenance': no_native, 'mandatory_sandbox': set()})
    module.WORKFLOW_IDENTITIES[('100mango/ColorPicker', 'refs/heads/' + source.BRANCH,
          '100mango/ColorPicker/' + source.WORKFLOW + '@refs/heads/' + source.BRANCH)] = (source.WORKFLOW, ('push',))
    module.read_file = lambda path, limit=5_000_000: io.read(path, limit)
    pure = checked_source('palette_lifecycle_diagnostics')
    names = {'valid_uuid', 'CaptureStopped'}
    nodes = [node for node in ast.parse(pure).body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    require({node.name for node in nodes} == names, 'Passive pure dependency shape changed')
    ns = {'re': re, 'uuid': uuid, 'capture': no_native, 'actual_mac_device': actual_mac_device,
          'read_file': module.read_file, 'strict_json': module.strict_json, 'workflow_identity': module.workflow_identity}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'source_bound_lifecycle_pure', 'exec'), ns)
    text = checked_source('mac_passive_lifecycle')
    text = replace_one(text, 'from palette_lifecycle_diagnostics import capture, CaptureStopped, valid_uuid', '# Explicit source-bound pure dependencies; native capture is forbidden.')
    text = replace_one(text, 'from retain_mac_evidence import read_file, strict_json, workflow_identity', '# Exact derived descriptor reader supplied by controller.')
    text = replace_one(text, "all(device.get(k)==v for k,v in {'platform':'macOS','architecture':'arm64','osVersion':'27.0'}.items())", 'actual_mac_device(device)')
    lifecycle = load_derived('mac_passive_lifecycle', text, ns)
    derived['mac_passive_lifecycle'] = hashlib.sha256(text.encode()).hexdigest()
    # Explicit imported identities, rather than relying on PYTHONPATH precedence.
    previous = {key: sys.modules.get(key) for key in ('secondary_about_evidence', 'mac_passive_lifecycle')}
    sys.modules['secondary_about_evidence'] = secondary
    sys.modules['mac_passive_lifecycle'] = lifecycle
    return module, secondary, previous, derived


def restore_modules(previous):
    for key, value in previous.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value


def exported_inventory(folder):
    manifest = io.json_read(ROOT / folder / 'manifest.json', 1_000_000)
    require(isinstance(manifest, list) and len(manifest) <= 64, 'Unbounded attachment group inventory')
    expected = set()
    items = []
    omissions = []
    for group in manifest:
        keep = []
        for attachment in group['attachments']:
            name = attachment['exportedFileName']
            require(re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)', name), 'Unsafe exported attachment path')
            require(name not in expected, 'Duplicate exported attachment')
            expected.add(name)
            path = ROOT / folder / name
            raw = io.read(path, 5_000_000)
            title = attachment.get('suggestedHumanReadableName', '')
            record = {'folder': folder, 'path': path, 'relative': folder + '/' + name, 'group': group,
                      'attachment': attachment, 'raw': raw}
            if not title.startswith('Native Mac'):
                omissions.append({'file': record['relative'], 'bytes': len(raw), 'sha256': io.digest(raw),
                                  'reason': 'Unselected non-product diagnostic attachment'})
                io.unlink_owned(path)
                continue
            keep.append(attachment)
            items.append(record)
        group['attachments'] = keep
    actual = {p.name for p in (ROOT / folder).iterdir() if p.name != 'manifest.json'}
    require(actual == {item['path'].name for item in items}, 'Unexpected/unmanifested export path')
    io.write(ROOT / folder / 'manifest.json', io.encoded(manifest), replace=True)
    return items, omissions


def passed_audits(items, summary):
    device = summary['devicesAndConfigurations'][0]['device']
    configuration = summary['devicesAndConfigurations'][0]['testPlanConfiguration']['configurationName']
    found = {}
    for item in items:
        if not item['attachment'].get('suggestedHumanReadableName', '').startswith('Native Mac accessibility issue audit summary '):
            continue
        raw = item['raw']
        match = re.fullmatch(rb'Audit-ID: ([0-9A-F-]{36})\nState: ([^\n]+)\nIssues: ([0-9]+)\nRecorded failures: ([0-9]+)\n?', raw)
        require(match is not None, 'Malformed audit ending')
        state = match[2].decode('utf-8')
        if state not in STATES:
            continue
        audit_id = match[1].decode()
        method = STATES[state]
        metadata = item['attachment']
        require(item['group'].get('testIdentifier') == 'TouchColorMacUITests/' + method + '()' and
                item['group'].get('testIdentifierURL') == 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/' + method,
                'Audit belongs to another test')
        require(metadata.get('suggestedHumanReadableName', '').startswith('Native Mac accessibility issue audit summary ' + audit_id + '_') and
                metadata.get('deviceId') == device['deviceId'] and metadata.get('configurationName') == configuration and
                runtime_contract.finite(metadata.get('timestamp')) and summary['startTime'] <= metadata['timestamp'] <= summary['finishTime'],
                'Audit source destination/configuration/time/UUID differs')
        require(re.fullmatch(r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', audit_id) and
                audit_id not in {x['audit_id'] for x in found.values()}, 'Malformed/reused audit UUID')
        require(state not in found and match[3] == b'0' and match[4] == b'0', 'Required audit duplicated or failed')
        found[state] = {'path': item['relative'], 'bytes': len(raw), 'sha256': io.digest(raw), 'audit_id': match[1].decode()}
    require(set(found) == set(STATES), 'Required five original/four About audit endings missing')
    return found


def image_shape(raw, suffix):
    """Bounded original-format structure check; never resize or re-encode."""
    import struct
    if suffix == '.png':
        require(len(raw) >= 45 and raw.startswith(b'\x89PNG\r\n\x1a\n') and raw[12:16] == b'IHDR' and
                raw.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'), 'Incomplete PNG bytes')
        width, height = struct.unpack('>II', raw[16:24])
    else:
        require(suffix in ('.jpg', '.jpeg') and raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'), 'Incomplete JPEG bytes')
        at, dimensions = 2, None
        while at < len(raw) - 2:
            require(raw[at] == 255 and at + 4 <= len(raw), 'Malformed JPEG marker')
            while at < len(raw) and raw[at] == 255:
                at += 1
            marker = raw[at]; at += 1
            if marker == 0xda:
                break
            require(marker not in (0, 0xd8, 0xd9), 'Invalid JPEG segment')
            length = int.from_bytes(raw[at:at + 2], 'big')
            require(length >= 2 and at + length <= len(raw), 'Truncated JPEG segment')
            if marker in (0xc0, 0xc1, 0xc2):
                require(length >= 8, 'Short JPEG dimensions')
                dimensions = (int.from_bytes(raw[at + 5:at + 7], 'big'), int.from_bytes(raw[at + 3:at + 5], 'big'))
            at += length
        require(dimensions is not None and at < len(raw) and marker == 0xda, 'Missing JPEG frame/scan')
        width, height = dimensions
    require(0 < width <= 16384 and 0 < height <= 16384, 'Image dimensions outside original bound')
    return [width, height]


def log_subset(raw):
    # Exact original lines, offsets and full stream fingerprint; not a full log.
    pattern = re.compile(rb'Test (?:Case|Suite)|MAC_|SECONDARY_|error|fatal|abort|killed|terminated|fail|deni(?:ed|al)|EPERM|EACCES|ownership|owned|cleanup|exception|assert|timeout|timed out|skip|API', re.I)
    parts, lines, offset = [], [], 0
    for line in raw.splitlines(keepends=True):
        if pattern.search(line):
            parts.append(line)
            lines.append({'offset': offset, 'bytes': len(line), 'sha256': io.digest(line)})
        offset += len(line)
    selected = b''.join(parts)
    require(len(selected) <= 250_000 and len(lines) <= 2048, 'Required raw log findings exceed finite allowance')
    return selected, {'scope': 'Original census/audit/failure/API/ownership lines, exact bytes and offsets; full stream remains official job log',
                      'source_bytes': len(raw), 'source_sha256': io.digest(raw), 'retained_bytes': len(selected),
                      'retained_sha256': io.digest(selected), 'lines': lines}


def retain_logs(controller):
    reports = {}
    for role in ('hosted', 'normal', 'sandbox'):
        if role not in controller.records:
            continue
        raw = controller.memory_logs.get(role)
        if raw is None:
            raw = io.read(io.REPO / ('build/mac-control/' + role + '.log'), 2_000_000)
        record = controller.records[role]
        require(record['stdout']['bytes'] == len(raw) and record['stdout']['sha256'] == io.digest(raw), 'Native original stream changed')
        selected, facts = log_subset(raw)
        io.write(ROOT / ('mac-' + role + '-raw-lines.log'), selected)
        reports[role] = facts
    put('mac-log-subsets.json', reports)


def complete_audit_console(controller):
    role = 'normal' if controller.lane == 'normal' else 'sandbox'
    raw = io.read(io.REPO / ('build/mac-control/' + role + '.log'), 2_000_000)
    for state in STATES:
        begin = ('MAC_ACCESSIBILITY_AUDIT_BEGIN: ' + state).encode()
        end = ('MAC_ACCESSIBILITY_AUDIT_END: ' + state + '; issues=0; recordedFailures=0').encode()
        lines = raw.splitlines()
        require(lines.count(begin) == 1 and lines.count(end) == 1 and lines.index(begin) < lines.index(end),
                'Missing/failed/duplicate native audit console ending: ' + state)


def sandbox_images(items, summary):
    selected = {}
    device = summary['devicesAndConfigurations'][0]['device']
    configuration = summary['devicesAndConfigurations'][0]['testPlanConfiguration']['configurationName']
    for title, method in SANDBOX_IMAGES.items():
        matches = [item for item in items if item['group'].get('testIdentifier') == method and
                   (item['attachment'].get('suggestedHumanReadableName') == title or
                    item['attachment'].get('suggestedHumanReadableName', '').startswith(title + '_')) and
                   item['path'].suffix in ('.png', '.jpg', '.jpeg')]
        require(len(matches) == 1, 'Missing/ambiguous required sandbox image: ' + title)
        item = matches[0]
        image_shape(item['raw'], item['path'].suffix)
        require(len(item['raw']) <= 500_000 and item['attachment'].get('deviceId') == device['deviceId'] and
                item['attachment'].get('configurationName') == configuration and
                item['group'].get('testIdentifierURL') == 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/' + method.removesuffix('()') and
                runtime_contract.finite(item['attachment'].get('timestamp')) and summary['startTime'] <= item['attachment'].get('timestamp', -1) <= summary['finishTime'], 'Sandbox raw image binding differs')
        selected[title] = {'path': item['relative'], 'bytes': len(item['raw']), 'sha256': io.digest(item['raw']),
                           'method': method, 'device_id': device['deviceId'], 'configuration': configuration}
    return selected


def native_extract(controller):
    requested = [('hosted', 'unit'), ('normal', 'ui')] if controller.lane == 'normal' else [('sandbox', 'sandbox')]
    roles = [(role, name) for role, name in requested if role in controller.records and
             (controller.records[role].get('owned') or {}).get('owned_group_cleanup_confirmed') is True and
             (io.REPO / ('build/mac-' + name + '.xcresult')).is_dir()]
    folder = 'screenshots' if controller.lane == 'normal' else 'sandbox-screenshots'
    jobs = [('summary-' + name, 40, ['/usr/bin/xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', 'build/mac-' + name + '.xcresult'], name)
            for role, name in roles]
    if ('normal' if controller.lane == 'normal' else 'sandbox') in {role for role, _ in roles}:
        jobs.append(('attachment-export', 40, ['/usr/bin/xcrun', 'xcresulttool', 'export', 'attachments', '--path',
                 'build/mac-ui.xcresult' if controller.lane == 'normal' else 'build/mac-sandbox.xcresult',
                 '--output-path', 'build/evidence/' + folder], None))
    jobs += [('post-source-head', 10, ['/usr/bin/git', 'rev-parse', 'HEAD'], None),
             ('post-source-tree', 10, ['/usr/bin/git', 'rev-parse', 'HEAD^{tree}'], None),
             ('post-source-clean', 10, ['/usr/bin/git', 'status', '--porcelain', '--untracked-files=all'], None)]
    results = {}
    for index, (name, seconds, argv, summary_name) in enumerate(jobs):
        later = sum(row[1] for row in jobs[index + 1:]) + 20
        # Small provenance queries use5s work+5s cleanup; xcresult keeps20+20.
        cleanup = 20 if seconds == 40 else 5
        now, wall = controller.clock(), controller.wall()
        work, end = controller.ledger.evidence_bounds(seconds, later, cleanup=cleanup)
        result = controller.session.run(argv, work_deadline=work,
                      cleanup_deadline=end, maximum_bytes=500_000, text=True)
        controller.records[name] = {'argv': argv, 'source_sha': os.environ['GITHUB_SHA'], 'lane': controller.lane,
            'started_monotonic': now, 'finished_monotonic': controller.clock(), 'started_epoch': wall, 'finished_epoch': controller.wall(),
            'work_deadline': work, 'cleanup_deadline': end, 'exit': result.returncode, 'owned': result.owned_receipt,
            'stdout': {'bytes': len(result.stdout.encode()), 'sha256': io.digest(result.stdout.encode())}}
        require(controller.clock() < min(controller.ledger.evidence_end, controller.ledger.phase_end('evidence')), 'Evidence stage expired')
        require(result.returncode == 0, 'Required evidence command failed: ' + name)
        results[name] = result.stdout
        if summary_name:
            io.write(ROOT / ('mac-' + summary_name + '-summary.json'), result.stdout.encode())
    require(results['post-source-head'].strip() == os.environ['GITHUB_SHA'] and results['post-source-tree'].strip() == controller.host['control_tree'] and results['post-source-clean'] == '', 'Post-runtime exact source changed')
    io.DEADLINE = min(controller.clock() + 20, controller.ledger.evidence_end, controller.ledger.phase_end('evidence'))
    source.protected()
    return roles, folder


WORK_END_OFFSET = 1920 + 130 + 180


def finish(controller, failure):
    io.mkdir(ROOT)
    result = {'schema': 1, 'complete': False, 'lane': controller.lane, 'source_sha': os.environ['GITHUB_SHA'],
              'product_sha': source.PRODUCT, 'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'job': os.environ['GITHUB_JOB'], 'failure': failure, 'primary_failure': failure,
              'native_failures': controller.failures, 'composition_required': ['normal', 'sandbox']}
    previous = None
    original_deadline = io.DEADLINE
    try:
        controller.ledger.evidence_bounds(0, 0, cleanup=0)
        io.DEADLINE = controller.ledger.evidence_end
        # Preserve failure context before any strict outcome reader can reject it.
        put('mac-command-receipts.json', controller.records)
        put('mac-host.json', controller.host)
        retain_logs(controller)
        require(controller.session.fault is None and not controller.ledger.poisoned, 'Native/evidence admission poisoned')
        roles, folder = native_extract(controller)
        # The reserved20 seconds covers all pure readers, retention, final scan.
        # native_extract starts this same20s window before source.protected.
        bindings = {}
        items, omissions = exported_inventory(folder) if (ROOT / folder / 'manifest.json').is_file() else ([], [])
        put('unselected-export-omissions.json', omissions)
        # Selection always runs on failed native outcomes too. It can retain real
        # partial evidence without making a failed strict summary pass.
        binding_failure = None
        for role, name in roles:
            summary = io.json_read(ROOT / ('mac-' + name + '-summary.json'), 500_000)
            try:
                device = runtime_contract.bind_summary(summary, controller.records[role], controller.host, controller.expected[role])
            except (ValueError, KeyError, TypeError) as error:
                binding_failure = {'error': type(error).__name__, 'reason': str(error)[:512]}
                device = None
            bindings[role] = {'summary': 'mac-' + name + '-summary.json', 'device': device,
                              'source_sha': os.environ['GITHUB_SHA'], 'command_id': role, 'expected_count': len(controller.expected[role])}
        put('mac-row-native-binding.json', bindings)
        put('mac-command-receipts.json', controller.records)
        put('mac-host.json', controller.host)
        io.write(ROOT / 'accessibility-api.json', io.read(io.REPO / 'build/accessibility-api/results.json', 65536))
        put('mac-launcher-prerequisite.json', io.json_read(io.REPO / 'build/mac-control/launcher-self-test.json', 8192))
        if controller.lane == 'normal':
            put('mac-normal-built-test-plan.json', io.json_read(io.REPO / 'build/mac-control/normal-built-test-plan.json', 65536))
        else:
            put('mac-release-validation.json', io.json_read(io.REPO / 'build/mac-control/release-validation.json', 65536))
            io.write(ROOT / 'mac-release-settings.json', io.read(io.REPO / 'build/mac-release-settings.json', 1_000_000))
            for name in ('release-file', 'release-lipo', 'release-linkage', 'release-build-version'):
                io.write(ROOT / (name + '.txt'), controller.results[name].encode())
        io.write(ROOT / 'architecture.txt', b'Exact current arm64 Mac row. Intel and optional calibration not selected.\n')
        put('job-budget.json', {'original': io.json_read(io.REPO / 'build/job-budget.json', 8192),
                               'events': controller.ledger.events, 'cleanup_unconfirmed': False})
        if controller.lane == 'sandbox':
            for moment, path in [('before', 'mac-sandbox-entitlements'), ('after', 'mac-sandbox-post-entitlements')]:
                put(path + '.json', controller.check_entitlements('build/' + path + '.plist'))
            put('mac-sandbox-boundary.json', io.json_read(io.REPO / 'build/mac-control/sandbox-host-boundary.json', 8192))
        audits = None
        audit_failure = None
        try:
            audits = passed_audits(items, io.json_read(ROOT / ('mac-ui-summary.json' if controller.lane == 'normal' else 'mac-sandbox-summary.json'), 500_000))
            complete_audit_console(controller)
        except (ValueError, KeyError, TypeError) as error:
            audit_failure = {'error': type(error).__name__, 'reason': str(error)[:512]}
        put('mac-required-audits.json', {'complete': audits is not None and audit_failure is None, 'audits': audits, 'failure': audit_failure})
        selector, secondary, previous, derived = readers(controller)
        required_images = {}
        if controller.lane == 'normal':
            secondary.prepare(ROOT)
        else:
            required_images = sandbox_images(items, io.json_read(ROOT / 'mac-sandbox-summary.json', 500_000))
            selector.mandatory_sandbox = {x['path'] for x in required_images.values()}
        identity = {'repository': '100mango/ColorPicker', 'ref': 'refs/heads/' + source.BRANCH,
                    'workflow_ref': '100mango/ColorPicker/' + source.WORKFLOW + '@refs/heads/' + source.BRANCH,
                    'workflow_file': source.WORKFLOW, 'event_name': 'push', 'sha': os.environ['GITHUB_SHA'],
                    'tree': controller.host['control_tree'], 'workflow_sha': os.environ['GITHUB_SHA'],
                    'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
                    'job': os.environ['GITHUB_JOB'], 'tracked_source_clean': True,
                    'workflow_file_sha256': io.digest(io.read(io.REPO / source.WORKFLOW, 256_000)),
                    'test_file_sha256': io.digest(io.read(io.REPO / 'TouchColorMacUITests/TouchColorMacUITests.swift', 256_000))}
        selection = selector.retain(ROOT, identity)
        selector.validate_selection(ROOT, require_complete=True)
        if controller.lane == 'normal':
            require(secondary.complete(ROOT) is True, 'Six required About images/audits incomplete')
            required_images = {'original_five': selection['requested'], 'secondary_six': sorted(secondary.selected_paths(ROOT))}
        else:
            for value in required_images.values():
                raw = io.read(ROOT / value['path'], 500_000)
                require(len(raw) == value['bytes'] and io.digest(raw) == value['sha256'], 'Required sandbox original image lost/transformed')
        require(not failure and not controller.failures and binding_failure is None and audit_failure is None and
                {role for role, _ in roles} == ({'hosted', 'normal'} if controller.lane == 'normal' else {'sandbox'}), 'Required native stage/audit binding failed')
        result.update(complete=True, host=controller.host, expected_counts={role: len(controller.expected[role]) for role, _ in roles},
                      required_images=required_images, required_audits=audits, derived_reader_sha256=derived,
                      evidence_scope='One exact Mac row; overall Mac requires both rows', no_image_transformation=True)
    except BaseException as error:
        if controller.session.fault is not None:
            controller.poison(error)
        result['evidence_failure'] = {'error': type(error).__name__, 'reason': str(error)[:512], 'owned': getattr(error, 'owned_receipt', None)}
        if result['primary_failure'] is None:
            result['failure'] = result['evidence_failure']
    finally:
        if previous is not None:
            restore_modules(previous)
        io.DEADLINE = original_deadline
    # Validation reserve is distinct from evidence, never starts new native work.
    io.DEADLINE = min(controller.clock() + 60, controller.ledger.phase_end('validation'))
    try:
        # Unknown/timeout never launches another child; existing memory/files can
        # still be copied within the separate original validation reserve.
        put('mac-command-receipts.json', controller.records)
        put('mac-host.json', controller.host)
        if not (ROOT / 'mac-log-subsets.json').exists():
            try:
                retain_logs(controller)
            except (OSError, ValueError, KeyError) as error:
                result['log_retention_failure'] = {'error': type(error).__name__, 'reason': str(error)[:300]}
        marker = io.REPO / 'build/job-budget-cleanup-unconfirmed.json'
        if marker.exists():
            io.write(ROOT / 'job-budget-cleanup-unconfirmed.json', io.read(marker, 8192), replace=True)
        put('mac-row-result.json', result)
        ready = publish_bounded(controller, result)
    finally:
        io.DEADLINE = original_deadline
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('evidence_ready=' + str(ready).lower() + '\ncomplete=' + str(result['complete']).lower() + '\n')
    return result['complete']


def publish_bounded(controller, result):
    """Copy bounded upload bytes; failed partial original exports stay untouched."""
    upload = io.REPO / 'build/mac-upload'
    io.mkdir(upload)
    files = sorted((p for p in ROOT.rglob('*') if p.is_file()), key=lambda p: p.relative_to(ROOT).as_posix())
    require(len(files) <= 600, 'Unbounded final evidence census')
    for path in ROOT.rglob('*'):
        require(not path.is_symlink(), 'Alias in evidence tree')
    total = sum(path.stat().st_size for path in files)
    if result['complete']:
        require(total <= LIMIT, 'Complete evidence exceeds unchanged3MB')
        copied = {}
        for path in files:
            raw = io.read(path, 5_000_000)
            relative = path.relative_to(ROOT)
            io.write(upload / relative, raw)
            require(io.read(upload / relative, 5_000_000) == raw, 'Uploaded copy bytes changed')
            copied[relative.as_posix()] = len(raw)
        require(sum(copied.values()) <= LIMIT and {x.relative_to(upload).as_posix() for x in upload.rglob('*') if x.is_file()} == set(copied), 'Final upload inventory/bytes changed')
        verify_upload(upload, controller.lane)
        return True
    # Failure-first metadata/raw texts, then original mandatory-looking pixels;
    # no transformed bytes. Every omitted item is explicitly incomplete.
    remaining = LIMIT - 65_536
    inventory = []
    files.sort(key=lambda p: (0 if p.name == 'mac-row-result.json' else 1 if p.suffix in ('.json', '.log', '.txt') else 2, p.as_posix()))
    for path in files:
        io.bounded_end()
        size = path.stat().st_size
        relative = path.relative_to(ROOT)
        facts = {'path': relative.as_posix(), 'bytes': size, 'retained': False}
        if size <= min(remaining, 5_000_000):
            raw = io.read(path, 5_000_000)
            facts['sha256'] = io.digest(raw)
            io.write(upload / relative, raw)
            facts['retained'] = True
            remaining -= len(raw)
        else:
            facts['reason'] = 'Incomplete partial export cannot fit unchanged artifact cap; original remains runner-local'
        inventory.append(facts)
    raw = io.encoded({'complete': False, 'source_sha': os.environ['GITHUB_SHA'], 'lane': controller.lane,
                      'original_export_bytes': total, 'limit': LIMIT, 'files': inventory})
    require(len(raw) <= 65_536, 'Failure inventory exceeds reserve')
    io.write(upload / 'incomplete-retention.json', raw)
    require(sum(x.stat().st_size for x in upload.rglob('*') if x.is_file()) <= LIMIT, 'Partial artifact overflow')
    return True


def retained_items(root, folder):
    groups = io.json_read(root / folder / 'manifest.json', 1_000_000)
    require(type(groups) is list and len(groups) <= 64, 'Retained group inventory differs')
    items = []
    for group in groups:
        for attachment in group['attachments']:
            name = attachment['exportedFileName']
            require(re.fullmatch(r'[0-9A-Fa-f-]{36}\.(png|jpg|jpeg|txt)', name), 'Unsafe retained attachment')
            path = root / folder / name
            items.append({'raw': io.read(path, 5_000_000), 'path': path, 'relative': folder + '/' + name,
                          'folder': folder, 'group': group, 'attachment': attachment})
            require(len(items) <= 512, 'Retained attachment census exceeds bound')
    return items


def verify_upload(root, lane):
    """Read-only final requalification of exact copied bytes, including deletions."""
    import commands
    root = Path(root)
    row = io.json_read(root / 'mac-row-result.json', 65536)
    require(row.get('complete') is True and row.get('lane') == lane and row.get('product_sha') == source.PRODUCT,
            'Row lacks complete exact product binding')
    host = io.json_read(root / 'mac-host.json', 65536)
    require(row.get('host') == host and all(row.get(key) == host.get(key) for key in ('source_sha', 'run_id', 'run_attempt')),
            'Row actual host/source/run differs')
    require(row.get('job') == 'mac-' + lane and row.get('run_attempt') == '1' and
            re.fullmatch('[0-9a-f]{40}', host.get('control_tree', '')) and row.get('primary_failure') is None and not row.get('native_failures'),
            'Wrong job/attempt/control/failure binding')
    require(not (root / 'job-budget-cleanup-unconfirmed.json').exists(), 'Unconfirmed cleanup cannot qualify')
    clock = io.json_read(root / 'job-budget.json', 65536)
    require(clock.get('cleanup_unconfirmed') is False, 'Missing exact cleanup budget record')
    prerequisite = io.json_read(root / 'mac-launcher-prerequisite.json', 8192)
    require(prerequisite.get('complete') is True and prerequisite.get('product_qualified') is False and
            prerequisite.get('scope') == 'fixed_launcher_prerequisite_only' and
            prerequisite.get('owned', {}).get('state') == 'REAPED' and prerequisite['owned'].get('reap_calls') == 1 and
            prerequisite['owned'].get('owned_group_cleanup_confirmed') is True, 'Actual launcher prerequisite missing')
    records = io.json_read(root / 'mac-command-receipts.json', 500_000)
    logs = io.json_read(root / 'mac-log-subsets.json', 500_000)
    roles = [('hosted', 'unit'), ('normal', 'ui')] if lane == 'normal' else [('sandbox', 'sandbox')]
    expected = commands.contract()
    require(row.get('expected_counts') == {role:len(expected[role]) for role, _ in roles}, 'Row test count metadata differs')
    for role, name in roles:
        summary = io.json_read(root / ('mac-' + name + '-summary.json'), 500_000)
        runtime_contract.bind_summary(summary, records[role], host, expected[role])
        raw = io.read(root / ('mac-' + role + '-raw-lines.log'), 250_000)
        facts = logs[role]
        require(facts['retained_sha256'] == io.digest(raw) and facts['retained_bytes'] == len(raw) and
                facts['source_sha256'] == records[role]['stdout']['sha256'] and facts['source_bytes'] == records[role]['stdout']['bytes'],
                'Retained console/full-stream binding changed')
        cases = runtime_contract.Cases(expected[role]); cases.consume(0, raw); actual = cases.finish()
        require(actual['complete'] is True and all(actual[k] == records[role]['cases'][k] for k in
                ('expected', 'events', 'ordered_events', 'foreign_lines', 'sequence_error')), 'Retained actual test identities differ')
        if role != 'hosted':
            lines = raw.splitlines()
            for state in STATES:
                begin = ('MAC_ACCESSIBILITY_AUDIT_BEGIN: ' + state).encode()
                end = ('MAC_ACCESSIBILITY_AUDIT_END: ' + state + '; issues=0; recordedFailures=0').encode()
                require(lines.count(begin) == lines.count(end) == 1 and lines.index(begin) < lines.index(end), 'Retained audit console incomplete')
    view = types.SimpleNamespace(host=host, lane=lane)
    selector, secondary, previous, _ = readers(view)
    try:
        selector.validate_selection(root, require_complete=True)
        selection = io.json_read(root / selector.REPORT, 256_000)
        saved = selection['source']
        require(all(saved.get(key) == row.get(other) for key, other in
                    [('sha','source_sha'),('run_id','run_id'),('run_attempt','run_attempt'),('job','job')]) and
                saved.get('tree') == host['control_tree'], 'Retained selector belongs to another source/run')
        folder = 'screenshots' if lane == 'normal' else 'sandbox-screenshots'
        items = retained_items(root, folder)
        summary = io.json_read(root / ('mac-ui-summary.json' if lane == 'normal' else 'mac-sandbox-summary.json'), 500_000)
        audits = passed_audits(items, summary)
        require(audits == row.get('required_audits'), 'Copied audit identity changed')
        if lane == 'normal':
            require(secondary.complete(root) is True, 'Copied required About/Privacy image absent or changed')
            require(row.get('required_images') == {'original_five':selection['requested'], 'secondary_six':sorted(secondary.selected_paths(root))}, 'Row normal image metadata differs')
            io.json_read(root / 'mac-normal-built-test-plan.json', 65536)
        else:
            require(sandbox_images(items, summary) == row.get('required_images'), 'Copied sandbox original image absent or changed')
            require(io.json_read(root / 'mac-sandbox-boundary.json', 8192).get('complete') is True, 'Sandbox host boundary missing')
            io.json_read(root / 'mac-release-validation.json', 65536)
    finally:
        restore_modules(previous)
    return row
