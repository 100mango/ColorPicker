#!/usr/bin/env python3
"""Fixed, bounded unsigned TouchColor archive proof; never a signing handoff.

The retained JSON describes this observation interval. Host capture/owned-group
cleanup does not establish the lifetime of Xcode's independent system daemons.
"""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import sys
import time
import xml.etree.ElementTree as ET

import tv_release_package as package
from tv_archive_capture import capture, CaptureStopped

ROOT = Path(__file__).resolve().parents[1]
BASE = '74ccaa93ae3f0cb5d0a63f6957460e9e8e576add'
BASE_TREE = 'c6bb5466a57dfd919b5dbd0edb3b58b7bf5a8683'
BRANCH = 'refs/heads/codex/tv-release-archive'
WORKFLOW = '.github/workflows/tv-release-archive.yml'
CATALOG = 'TouchColorTV/Assets.xcassets/AppIcon.brandassets/'
SCALED = ('Small.imagestack/Back.imagestacklayer/Content.imageset/',
          'Small.imagestack/Front.imagestacklayer/Content.imageset/',
          'TopShelf.imageset/', 'TopShelfWide.imageset/')
MODIFIED_PATHS = tuple(CATALOG + p + 'Contents.json' for p in SCALED)
NEW_PATHS = (WORKFLOW, 'scripts/tv_release_archive.py', 'scripts/test_tv_release_archive.py',
             'scripts/tv_release_package.py', 'scripts/tv_release_contract.json',
             'scripts/tv_archive_capture.py', 'scripts/test_tv_archive_capture.py',
             'scripts/materialize_tv_2x_assets.py', 'scripts/test_tv_2x_assets.py') + tuple(
             CATALOG + p + ('Transparent-2x.png' if '/Front.' in p else 'Icon-2x.png') for p in SCALED)
ARCHIVE = Path('build/TouchColor.xcarchive')
APP = 'Products/Applications/TouchColor.app'
DSYM = 'dSYMs/TouchColor.app.dSYM'
DWARF = DSYM + '/Contents/Resources/DWARF/TouchColor'
APP_FILES = package.APP_FILES
MAX_ENTRIES, MAX_BYTES, SCAN_SECONDS = 8192, 1024 ** 3, 30
MAX_REPORT = 2 * 1024 ** 2
ARCHIVE_COMMAND = ['xcodebuild', '-quiet', '-project', 'TouchColorTV.xcodeproj',
    '-scheme', 'TouchColorTV', '-configuration', 'Release', '-destination',
    'generic/platform=tvOS', '-archivePath', str(ARCHIVE), '-derivedDataPath',
    'build/ArchiveDerived', 'CODE_SIGNING_ALLOWED=NO', 'archive']
PHASE_END = {'prepare': 180, 'archive': 800, 'proof': 910, 'final_source_pack': 940,
             'evidence': 1000, 'finalization': 1020}
MACH_MAGICS = package.MACH_MAGICS + (b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce',
                                     b'\xbe\xba\xfe\xca', b'\xbf\xba\xfe\xca')


class Rejected(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def need(ok, reason):
    if not ok:
        raise Rejected(reason)


def timely(deadline, clock=time.monotonic):
    need(math.isfinite(deadline) and clock() < deadline, 'deadline-exceeded')


def command(argv, *, deadline, seconds, cap, receipts, clock=time.monotonic,
            runner=capture, cleanup=2):
    """One command grant with the existing helper's two cleanup phases reserved."""
    start = clock()
    grant = min(seconds, deadline - start - 2 * cleanup)
    need(math.isfinite(grant) and grant > 0, 'command-cleanup-admission-expired')
    receipt = {'command': argv, 'start': start, 'grant_seconds': grant,
               'cleanup_reserve_seconds': 2 * cleanup, 'complete': False}
    receipts.append(receipt)
    try:
        result = runner(argv, seconds=grant, cap=cap, cleanup_grace=cleanup)
    except CaptureStopped as error:
        stdout = getattr(error, 'stdout_prefix', b'')[:cap]
        stderr = getattr(error, 'stderr_capture', b'')[:max(0, cap-len(stdout))]
        receipt.update(reason=str(error), owned_cleanup_confirmed=error.cleanup_confirmed,
                       cancelled_signal=error.cancelled_signal,
                       stdout=stdout.decode('utf-8', 'replace'),
                       stderr=stderr.decode('utf-8', 'replace'))
        raise Rejected('capture-stopped') from error
    finally:
        receipt['end'] = clock()
    receipt.update(returncode=result.returncode, stdout=result.stdout.decode('utf-8', 'replace'),
                   stderr=result.stderr.decode('utf-8', 'replace'),
                   owned_host_observation='client-reaped-pipes-closed-group-absent-at-return')
    need(len(result.stdout) + len(result.stderr) <= cap, 'command-byte-limit')
    need(receipt['end'] < start + grant and receipt['end'] < deadline, 'command-late-return')
    need(result.returncode == 0, 'command-failed')
    if argv == ARCHIVE_COMMAND:
        need(re.search(rb'(?im)(?:^|[ :])(?:fatal )?error:', result.stdout + b'\n' + result.stderr) is None, 'archive-reported-error')
    receipt['complete'] = True
    return result.stdout


def environment(env):
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': BRANCH,
        'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH,
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'archive',
        'DEVELOPER_DIR': '/Applications/Xcode_27.app/Contents/Developer'}
    need(all(env.get(k) == v for k, v in expected.items()), 'job-identity-mismatch')
    need(env.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'event-mismatch')
    sha = env.get('GITHUB_SHA', '')
    need(re.fullmatch('[0-9a-f]{40}', sha) is not None and env.get('GITHUB_WORKFLOW_SHA') == sha,
         'source-workflow-sha-mismatch')
    need(re.fullmatch('[1-9][0-9]{0,19}', env.get('GITHUB_RUN_ID', '')) is not None, 'run-identity-mismatch')
    return {k: env[k] for k in (*expected, 'GITHUB_EVENT_NAME', 'GITHUB_SHA',
                               'GITHUB_WORKFLOW_SHA', 'GITHUB_RUN_ID')}


def source_identity(env, run, root=ROOT):
    identity = environment(env)
    def git(*args):
        return run(['git', *args], seconds=5, cap=256 * 1024).decode().strip()
    need(git('rev-parse', 'HEAD') == identity['GITHUB_SHA'], 'head-mismatch')
    need(git('rev-parse', BASE + '^{tree}') == BASE_TREE, 'base-tree-mismatch')
    lineage = git('rev-list', '--parents', '-n', '1', 'HEAD').split()
    need(lineage == [identity['GITHUB_SHA'], BASE], 'source-sole-parent-mismatch')
    identity['parents'] = lineage[1:]
    need(git('status', '--porcelain', '--untracked-files=all') == '', 'source-not-clean')
    differences = git('diff', '--name-status', BASE, 'HEAD', '--').splitlines()
    need(sorted(differences) == sorted(['A\t' + p for p in NEW_PATHS] + ['M\t' + p for p in MODIFIED_PATHS]), 'source-scope-mismatch')
    identity.update(tree=git('rev-parse', 'HEAD^{tree}'), base=BASE, base_tree=BASE_TREE)
    graph = package.source_graph(root)
    scheme = root / 'TouchColorTV.xcodeproj/xcshareddata/xcschemes/TouchColorTV.xcscheme'
    parsed = ET.fromstring(scheme.read_bytes())
    need(parsed.find('ArchiveAction').get('buildConfiguration') == 'Release', 'archive-configuration-mismatch')
    entries = parsed.findall('./BuildAction/BuildActionEntries/BuildActionEntry')
    archived = [e.find('BuildableReference') for e in entries if e.get('buildForArchiving') == 'YES']
    need(len(archived) == 1 and archived[0].get('BuildableName') == 'TouchColor.app'
         and archived[0].get('BlueprintName') == 'TouchColorTV'
         and archived[0].get('ReferencedContainer') == 'container:TouchColorTV.xcodeproj', 'archive-scheme-mismatch')
    paths = sorted(set(NEW_PATHS) | set(MODIFIED_PATHS) | set(package.contract(root)['unchanged_inputs']) | set(graph['resource_files']) | {
        'TouchColorTV.xcodeproj/project.pbxproj', scheme.relative_to(root).as_posix()})
    identity['files'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    identity['app_graph'] = graph
    return identity


def file_identity(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def scan(archive, deadline, *, clock=time.monotonic, hash_files=True):
    """One bounded walk. Rechecking all directory identities detects new entries."""
    deadline = min(deadline, clock() + SCAN_SECONDS)
    root_stat = archive.lstat()
    need(stat.S_ISDIR(root_stat.st_mode), 'archive-missing-or-linked')
    paths, pending, total = {'.': {'identity': file_identity(root_stat)}}, [archive], 0
    while pending:
        folder = pending.pop()
        timely(deadline, clock)
        with os.scandir(folder) as entries:
            for entry in entries:
                timely(deadline, clock)
                need(len(paths) <= MAX_ENTRIES, 'archive-entry-limit')
                path = Path(entry.path); key = path.relative_to(archive).as_posix()
                need(len(key) <= 1024, 'archive-path-limit')
                value = path.lstat(); mode = value.st_mode
                need(stat.S_ISDIR(mode) or stat.S_ISREG(mode), 'archive-linked-or-nonregular')
                need(not stat.S_ISREG(mode) or value.st_nlink == 1, 'archive-hardlink')
                need(path.name not in ('Watch', '_CodeSignature', 'CodeResources', 'embedded.mobileprovision')
                     and path.suffix.lower() not in ('.appex', '.framework', '.xctest', '.dylib', '.mobileprovision')
                     and 'PaletteFixtures' not in key, 'unexpected-code-or-signature')
                need(path.suffix not in ('.app', '.dSYM') or key in (APP, DSYM), 'unexpected-product')
                allowed = key in ('Info.plist', 'Products', 'Products/Applications', APP, 'dSYMs', DSYM)
                allowed = allowed or key.startswith(APP + '/') or key.startswith(DSYM + '/')
                need(allowed, 'unexpected-archive-entry')
                receipt = {'identity': file_identity(value)}; paths[key] = receipt
                if stat.S_ISDIR(mode):
                    pending.append(path); continue
                total += value.st_size
                need(total <= MAX_BYTES, 'archive-byte-limit')
                need(key in (APP + '/TouchColor', DWARF) or not mode & 0o111, 'unexpected-executable')
                if hash_files:
                    h = hashlib.sha256(); count = 0; prefix = b''
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    with os.fdopen(os.open(path, flags), 'rb') as stream:
                        need(file_identity(os.fstat(stream.fileno())) == receipt['identity'], 'archive-file-changed')
                        while chunk := stream.read(1024 * 1024):
                            timely(deadline, clock); count += len(chunk)
                            need(count <= value.st_size, 'archive-file-grew')
                            if not prefix: prefix = chunk[:4]
                            h.update(chunk)
                        need(file_identity(os.fstat(stream.fileno())) == receipt['identity'], 'archive-file-changed')
                    need(count == value.st_size, 'archive-file-changed')
                    need(prefix not in MACH_MAGICS or key in (APP + '/TouchColor', DWARF), 'unexpected-mach-o')
                    receipt.update(bytes=count, sha256=h.hexdigest())
    for key, receipt in paths.items():
        timely(deadline, clock)
        need(file_identity((archive / key).lstat()) == receipt['identity'], 'archive-snapshot-changed')
    timely(deadline, clock)
    return {'paths': paths, 'entries': len(paths) - 1, 'bytes': total}


def matching_uuid(raw, executable, dwarf):
    rows = raw.decode('utf-8').splitlines(); found = {}
    pattern = r'UUID: ([0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}) \(arm64\) (.+)'
    for line in rows:
        match = re.fullmatch(pattern, line)
        need(match is not None, 'uuid-output-invalid')
        uuid, path = match.groups()
        need(path in (str(executable), str(dwarf)) and path not in found, 'uuid-product-mismatch')
        need(uuid.replace('-', '').strip('0'), 'uuid-zero')
        found[path] = uuid.upper()
    need(len(found) == 2 and len(set(found.values())) == 1, 'uuid-mismatch')
    return next(iter(found.values()))


def read_metadata(path, deadline, clock):
    timely(deadline, clock)
    need(path.lstat().st_size <= 1024 * 1024, 'metadata-byte-limit')
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    need(len(raw) <= 1024 * 1024, 'metadata-byte-limit')
    result = plistlib.loads(raw)
    timely(deadline, clock)
    need(isinstance(result, dict), 'metadata-not-dictionary')
    return result


def compiled_asset_dimensions(raw):
    """Use Apple's native CAR decoder, rather than treating any nonempty file as assets."""
    values = json.loads(raw)
    need(isinstance(values, list) and 0 < len(values) <= 2048, 'compiled-asset-inventory-invalid')
    observed = []
    for value in values:
        need(isinstance(value, dict), 'compiled-asset-record-invalid')
        width, height = value.get('PixelWidth'), value.get('PixelHeight')
        if width is not None or height is not None:
            need(type(width) is int and type(height) is int and width > 0 and height > 0,
                 'compiled-asset-dimensions-invalid')
            observed.append({'name': value.get('Name'), 'rendition': value.get('RenditionName'),
                             'width': width, 'height': height, 'scale': value.get('Scale')})
    sizes = {(x['width'], x['height']) for x in observed}
    required = {(400, 240), (800, 480), (1280, 768), (1920, 720), (3840, 1440), (2320, 720), (4640, 1440)}
    need(required <= sizes, 'compiled-asset-scale-coverage-missing')
    return {'required_dimensions': [list(v) for v in sorted(required)], 'observed': observed,
            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw)}


def verify_archive(archive, run, deadline, *, root=ROOT, clock=time.monotonic):
    started = clock()
    before = scan(archive, deadline, clock=clock)
    app = archive / APP; executable = app / 'TouchColor'; dwarf = archive / DWARF
    need({k[len(APP)+1:] for k,v in before['paths'].items() if k.startswith(APP+'/') and 'sha256' in v} == APP_FILES, 'app-resource-inventory-mismatch')
    metadata = read_metadata(archive / 'Info.plist', deadline, clock)
    need(type(metadata.get('ArchiveVersion')) is int and metadata['ArchiveVersion'] == 2
         and metadata.get('SchemeName') == 'TouchColorTV', 'archive-metadata-mismatch')
    need(isinstance(metadata.get('CreationDate'), datetime.datetime), 'archive-creation-metadata-missing')
    result = package.verify(app, 'device', True, root=root, clock=clock)
    timely(deadline, clock)
    compiled_assets = compiled_asset_dimensions(run(['xcrun', 'assetutil', '--info', str(app/'Assets.car')], seconds=15, cap=256*1024, cleanup=10))
    timely(deadline, clock)
    need(set(result['files']) == {'app/' + p for p in APP_FILES}, 'app-resource-inventory-mismatch')
    need(set(result['binaries']) == {'app/TouchColor'}, 'app-code-inventory-mismatch')
    properties = metadata.get('ApplicationProperties', {})
    need(properties.get('ApplicationPath') == 'Applications/TouchColor.app', 'archive-application-path-mismatch')
    for key in ('CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion'):
        need(properties.get(key) == result['metadata'][key], 'archive-application-identity-mismatch')
    need(not any(properties.get(k) for k in ('SigningIdentity', 'Team')), 'archive-signing-identity-present')
    dsym_info = read_metadata(archive / DSYM / 'Contents/Info.plist', deadline, clock)
    need(dsym_info.get('CFBundleIdentifier') == 'com.apple.xcode.dsym.com.mango.touchColor'
         and dsym_info.get('CFBundlePackageType') == 'dSYM', 'dsym-metadata-mismatch')
    # dsymutil may emit default or missing versions. Preserve and compare the
    # observed values without treating them as a qualification gate.
    dsym_versions = {key: {'observed': dsym_info.get(key),
        'comparison': ('missing' if key not in dsym_info else
                       'same' if dsym_info[key] == result['metadata'][key] else 'different')}
        for key in ('CFBundleVersion', 'CFBundleShortVersionString')}
    # UUID matching alone must not turn an arbitrary file into a DWARF object.
    with dwarf.open('rb') as stream:
        header = stream.read(32)
    need(len(header) == 32 and header[:4] == b'\xcf\xfa\xed\xfe', 'dsym-mach-o-missing')
    values = struct.unpack('<8I', header)
    need(values[1] == 0x100000c and values[3] == 10 and values[7] == 0, 'dsym-mach-o-identity-mismatch')
    uuid = matching_uuid(run(['xcrun', 'dwarfdump', '--uuid', str(executable), str(dwarf)],
        seconds=10, cap=8192, cleanup=10), executable, dwarf)
    after = scan(archive, deadline, clock=clock, hash_files=False)
    need(before['entries'] == after['entries'] and before['bytes'] == after['bytes']
         and {k: v['identity'] for k, v in before['paths'].items()} ==
             {k: v['identity'] for k, v in after['paths'].items()}, 'archive-changed-during-proof')
    for key, receipt in result['files'].items():
        observed = before['paths'][APP + '/' + key[4:]]
        need(receipt == {k: observed[k] for k in ('bytes', 'sha256')}, 'app-snapshot-mismatch')
    timely(deadline, clock)
    return {'archive': before, 'metadata': metadata, 'dsym_metadata': dsym_info,
            'app': result, 'compiled_assets': compiled_assets, 'dsym_version_observations': dsym_versions,
            'arm64_uuid': uuid, 'elapsed_seconds': clock() - started,
            'limits': {'entries': MAX_ENTRIES, 'bytes': MAX_BYTES, 'scan_seconds': SCAN_SECONDS},
            'observation': 'stable-file-identities-around-package-and-uuid-inspection'}


def json_value(value):
    if isinstance(value, datetime.datetime):
        return {'plist_date': value.isoformat()}
    if isinstance(value, bytes):
        return {'plist_data_hex': value.hex()}
    raise TypeError(type(value).__name__)


def report_bytes(report):
    raw = (json.dumps(report, sort_keys=True, default=json_value, allow_nan=False, separators=(',', ':')) + '\n').encode()
    if len(raw) > MAX_REPORT:
        report = {k: report[k] for k in ('schema', 'qualified', 'signing_qualified', 'store_qualified',
                    'older_os_qualified', 'ui_qualification_separate')}
        report.update(qualified=False, failure={'type': 'Rejected', 'reason': 'report-byte-limit'})
        raw = (json.dumps(report, sort_keys=True) + '\n').encode()
    return raw


def execute(*, env=None, root=ROOT, clock=time.monotonic, runner=capture):
    env = os.environ if env is None else env
    began = clock(); receipts = []; phase = 'prepare'; phase_deadline = began + 180
    report = {'schema': 1, 'scope': 'tv-release-unsigned-archive-observation', 'qualified': False,
        'signing_qualified': False, 'store_qualified': False, 'older_os_qualified': False,
        'ui_qualification_separate': True, 'binary_handoff': False, 'commands': receipts,
        'functional_evidence_reused': {'source': BASE, 'run': 37385172706, 'job': 112018810966, 'hosted': 40, 'ui': 5, 'resources_changed': True, 'new_runtime_run': False},
        'upload_qualified': False, 'qualification_scope': 'archive-observation-before-retention',
        'clock': {'started_monotonic': began, 'phase_end_seconds': PHASE_END,
                  'report_ready_deadline': began + PHASE_END['final_source_pack']},
        'host_scope': 'owned-client-and-process-group-observation; no independent-daemon lifetime claim'}
    def run(argv, **kwargs):
        return command(argv, deadline=phase_deadline, receipts=receipts,
                       clock=clock, runner=runner, **kwargs)
    try:
        need(not (root / 'build').exists() and not (root / 'build').is_symlink(), 'output-not-fresh')
        (root / 'build').mkdir()
        report['owned_output'] = file_identity((root / 'build').lstat())[:2]
        report['source_before'] = source_identity(env, run, root)
        report['toolchain'] = {
            'os': run(['sw_vers'], seconds=5, cap=4096).decode(),
            'xcode': run(['xcodebuild', '-version'], seconds=10, cap=4096).decode(),
            'sdks': run(['xcodebuild', '-showsdks'], seconds=15, cap=16384).decode()}
        need(report['toolchain']['xcode'].strip().splitlines() == ['Xcode 27.0', 'Build version 27A266a'], 'toolchain-mismatch')
        need('appletvos27.0' in report['toolchain']['sdks'], 'sdk-mismatch')
        for optimize in ([], ['-O']):
            for test_file in ('test_tv_archive_capture.py', 'test_tv_release_archive.py'):
                run([sys.executable, *optimize, '-m', 'unittest', 'discover', '-s', 'scripts',
                     '-p', test_file], seconds=40, cap=65536)
        timely(began + PHASE_END['prepare'], clock)
        phase = 'archive'; phase_deadline = min(began + PHASE_END[phase], clock() + 620)
        run(ARCHIVE_COMMAND, seconds=600, cap=512 * 1024, cleanup=10)
        phase = 'proof'; phase_deadline = min(began + PHASE_END[phase], clock() + 110)
        report['proof'] = verify_archive(root / ARCHIVE, run, phase_deadline, root=root, clock=clock)
        phase = 'final_source_pack'; phase_deadline = min(began + PHASE_END[phase], clock() + 30)
        report['clock']['report_ready_deadline'] = phase_deadline
        report['source_after'] = source_identity(env, run, root)
        need(report['source_after'] == report['source_before'], 'source-changed')
        timely(phase_deadline, clock)
        report['qualified'] = True
    except (Exception, KeyboardInterrupt) as error:
        report['clock']['report_ready_deadline'] = min(report['clock']['report_ready_deadline'], clock() + 30)
        report['failure'] = {'phase': phase, 'type': type(error).__name__,
                             'reason': str(error)[:4096]}
    report['clock']['elapsed_seconds'] = clock() - began
    return report


def retain_report(result, output, marker, *, clock=time.monotonic):
    """Finish every report/marker write against the original final phase clock."""
    deadline = result['clock']['report_ready_deadline']
    offset = None
    try:
        timely(deadline, clock)
        output.mkdir(exist_ok=False)
        payload = report_bytes(result)
        timely(deadline, clock)
        (output / 'report.json').write_bytes(payload)
        timely(deadline, clock)
        # This is the current step's owned output file. Roll back this append if
        # it returns late, so a late artifact cannot gain upload admission.
        with marker.open('a+', encoding='utf-8') as stream:
            stream.seek(0, os.SEEK_END); offset = stream.tell()
            stream.write('evidence_ready=true\n'); stream.flush()
            if clock() >= deadline:
                stream.truncate(offset)
                raise Rejected('deadline-exceeded')
        timely(deadline, clock)
        return json.loads(payload)
    except Rejected as error:
        if offset is not None:
            with marker.open('r+', encoding='utf-8') as stream:
                stream.truncate(offset)
        result['qualified'] = False
        result['failure'] = {'phase': 'final_source_pack', 'type': type(error).__name__, 'reason': str(error)}
        # Local typed failure only: no new command and no upload admission.
        if output.is_dir() and not output.is_symlink():
            (output / 'report.json').write_bytes(report_bytes(result))
        return result


def upload_ceiling(result):
    value = result.get('clock', {})
    began = value.get('started_monotonic')
    need(type(began) in (int, float) and math.isfinite(began) and began >= 0
         and value.get('phase_end_seconds') == PHASE_END, 'upload-clock-identity-mismatch')
    return began, began + PHASE_END['evidence'], began + PHASE_END['finalization']


def admit_upload(result, *, clock=time.monotonic):
    began, evidence_end, global_end = upload_ceiling(result)
    now = clock()
    # Full action timeout plus the original finalization reserve. No fresh clock.
    need(began <= now and now + 60 < evidence_end and now + 80 < global_end,
         'upload-full-admission-expired')
    return {'status': 'admitted', 'admitted_monotonic': now,
        'elapsed_at_admission': now - began, 'evidence_deadline': evidence_end,
        'global_deadline': global_end, 'action_timeout_seconds': 60,
        'finalization_reserve_seconds': 20, 'upload_qualified': False,
        'interval_scope': 'admission-through-post-action-observation-including-step-delays'}


def finish_upload(result, outcome, *, clock=time.monotonic):
    began, evidence_end, global_end = upload_ceiling(result)
    admission = result.get('upload_observation', {})
    started = admission.get('admitted_monotonic')
    now = clock()
    receipt = {'scope': 'post-upload-clock-gate', 'upload_qualified': False,
        'archive_qualified': result.get('qualified') is True,
        'action_outcome': outcome, 'started_monotonic': started,
        'observed_finished_monotonic': now, 'elapsed_since_original_start': now - began,
        'evidence_deadline': evidence_end, 'global_deadline': global_end,
        'interval_scope': 'includes-action-setup-and-inter-step-delay'}
    if (type(started) not in (int, float) or not math.isfinite(started)
            or admission.get('status') != 'admitted' or started < began
            or started + 60 >= evidence_end or started + 80 >= global_end
            or admission.get('evidence_deadline') != evidence_end
            or admission.get('global_deadline') != global_end or not math.isfinite(now) or now < started):
        receipt['failure'] = 'upload-admission-identity-mismatch'
    elif outcome != 'success':
        receipt['failure'] = 'upload-action-not-successful'
    elif now >= global_end:
        receipt['failure'] = 'upload-global-deadline-exceeded'
    elif now >= evidence_end:
        receipt['failure'] = 'upload-evidence-deadline-exceeded'
    elif now >= started + 60:
        receipt['failure'] = 'upload-admitted-phase-exceeded'
    else:
        receipt['upload_qualified'] = True
    return receipt


def upload_gate(mode, *, root=ROOT, env=None, clock=time.monotonic):
    env = os.environ if env is None else env
    identity = environment(env)
    path = root / 'build/archive-proof/report.json'
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_REPORT, 'upload-report-invalid')
    with path.open('rb') as stream:
        payload = stream.read(MAX_REPORT + 1)
    need(len(payload) <= MAX_REPORT and file_identity(path.lstat()) == file_identity(before),
         'upload-report-changed')
    result = json.loads(payload)
    need(all(result.get('source_before', {}).get(k) == v for k, v in identity.items()),
         'upload-source-run-mismatch')
    if mode == 'finish-upload':
        receipt = finish_upload(result, env.get('TC_ARCHIVE_UPLOAD_OUTCOME', ''), clock=clock)
        # The uploaded proof explicitly leaves upload_qualified=false. This
        # final workflow log receipt is the separate retention qualification.
        print(json.dumps(receipt, sort_keys=True))
        _, _, global_end = upload_ceiling(result)
        admitted = result['upload_observation']['admitted_monotonic']
        timely(min(global_end, admitted + 80), clock)
        return 0 if receipt['upload_qualified'] else 1
    need(mode == 'admit-upload', 'unknown-upload-gate')
    result['upload_observation'] = admit_upload(result, clock=clock)
    payload = report_bytes(result)
    need(json.loads(payload).get('upload_observation') == result['upload_observation'], 'upload-report-byte-limit')
    path.write_bytes(payload)
    admit_upload(result, clock=clock)  # Report packing must not consume admission.
    marker = Path(env['GITHUB_OUTPUT']); offset = None
    try:
        with marker.open('a+', encoding='utf-8') as stream:
            stream.seek(0, os.SEEK_END); offset = stream.tell()
            stream.write('upload_admitted=true\n'); stream.flush()
            admit_upload(result, clock=clock)
        admit_upload(result, clock=clock)
        print(json.dumps(result['upload_observation'], sort_keys=True))
        admit_upload(result, clock=clock)
    except Rejected:
        if offset is not None:
            with marker.open('r+', encoding='utf-8') as stream:
                stream.truncate(offset)
        raise
    return 0


def main():
    os.chdir(ROOT)
    if len(sys.argv) == 2 and sys.argv[1] in ('admit-upload', 'finish-upload'):
        return upload_gate(sys.argv[1])
    need(len(sys.argv) == 1, 'no-input-selectors')
    result = execute()
    output = ROOT / 'build/archive-proof'
    # Never follow an existing output path after a failed freshness check.
    if 'owned_output' not in result:
        print(json.dumps(result, default=json_value)); return 1
    need(stat.S_ISDIR((ROOT / 'build').lstat().st_mode) and
         file_identity((ROOT / 'build').lstat())[:2] == result['owned_output'], 'output-ownership-changed')
    decoded = retain_report(result, output, Path(os.environ['GITHUB_OUTPUT']))
    print(json.dumps({'qualified': decoded['qualified'], 'failure': decoded.get('failure')}))
    return 0 if decoded['qualified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
