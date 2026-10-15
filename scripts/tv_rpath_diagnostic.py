"""One fixed unsigned TV archive using existing bounded capture; no release actions."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time

from original_ios_archive import command, scan
from palette_lifecycle_diagnostics import capture, CaptureStopped
from atomic_json import write_json
import tv_rpath_contract as contract

ROOT = Path(__file__).resolve().parents[1]
BASE = '7c671f04e4d69884741a411851ae26083361c7f7'
BASE_TREE = 'f477c19b8181c4e3eb2142beaef4dea742cca0cd'
BRANCH = 'refs/heads/touchcolor-tv-raw-facts-20261015'
WORKFLOW = '.github/workflows/platform-qualification.yml'
ADDITIONS = (WORKFLOW, 'scripts/tv_rpath_contract.py', 'scripts/tv_rpath_diagnostic.py',
             'scripts/test_tv_rpath_contract.py')
WORK = ROOT / 'build/tv-rpath-diagnostic'
ARCHIVE = WORK / 'TouchColor.xcarchive'
APP = ARCHIVE / 'Products/Applications/TouchColor.app'
DEVELOPER = '/Applications/Xcode_27.app/Contents/Developer'
need = contract.need


def observe_macho_bytes(raw):
    """Bounded facts, never qualification. Unrelated payload faults cannot hide
    later rpaths while the next load-command boundary is structurally safe.
    """
    result = {'status': 'RAW_MAIN_IMAGE_OBSERVATION_ONLY', 'bytes': len(raw),
              'executable_sha256': hashlib.sha256(raw).hexdigest(), 'header_hex': raw[:32].hex(),
              'rpaths': [], 'build_versions': [], 'signature_commands': [], 'libraries': [],
              'parse_errors': [], 'parse_error_count': 0, 'rpaths_complete': True,
              'release_qualification': False}
    def note(reason, index=None):
        result['parse_error_count'] += 1
        if len(result['parse_errors']) < 16:
            result['parse_errors'].append({'reason': str(reason), 'command_index': index})
    def keep_path(bucket, value, command, index):
        limit = 16384 if bucket == 'rpaths' else 8192
        row = {'command_index': index, 'command': command, 'path_hex': value.hex()}
        try: row['path_utf8'] = value.decode('utf-8', 'strict')
        except UnicodeError: row.update(path_utf8=None, utf8_valid=False)
        if len(value) > 256 or len(result[bucket]) >= 32 or len(json.dumps(result[bucket] + [row])) > limit:
            result[bucket + '_omitted_count'] = result.get(bucket + '_omitted_count', 0) + 1
            if bucket == 'rpaths': result['rpaths_complete'] = False
            note('observation_' + bucket + '_report_limit', index)
            return
        result[bucket].append(row)
    try:
        need(len(raw) >= 32, 'observation_truncated_header')
        endian = '<' if raw[:4] == b'\xcf\xfa\xed\xfe' else '>' if raw[:4] == b'\xfe\xed\xfa\xcf' else None
        need(endian is not None, 'observation_unsupported_magic')
        values = struct.unpack_from(endian + '8I', raw)
        result['header'] = dict(zip(('magic', 'cpu', 'subtype', 'filetype', 'command_count',
                                     'command_bytes', 'flags', 'reserved'), values))
        count, size = values[4:6]
        need(0 <= count <= 2048 and count * 8 <= size <= 4 * 1024 * 1024 and 32 + size <= len(raw),
             'observation_command_bounds')
        result['load_commands_sha256'] = hashlib.sha256(raw[32:32+size]).hexdigest()
        pos = 32
        for index in range(count):
            need(pos + 8 <= 32 + size, 'observation_truncated_command')
            command, length = struct.unpack_from(endian + 'II', raw, pos)
            need(length >= 8 and length % 8 == 0 and pos + length <= 32 + size,
                 'observation_command_size')
            bucket = None
            try:
                if command in (0x8000001c, 0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023):
                    bucket = 'rpaths' if command == 0x8000001c else 'libraries'
                    result[bucket + '_seen'] = result.get(bucket + '_seen', 0) + 1
                    minimum = 12 if bucket == 'rpaths' else 24
                    need(length > minimum, 'observation_short_path_command')
                    offset = struct.unpack_from(endian + 'I', raw, pos + 8)[0]
                    need(minimum <= offset < length, 'observation_path_offset')
                    tail = raw[pos+offset:pos+length]
                    need(b'\0' in tail, 'observation_unterminated_path')
                    keep_path(bucket, tail.split(b'\0', 1)[0], command, index)
                elif command == 0x32:
                    need(length >= 24 and len(result['build_versions']) < 16, 'observation_build_bounds')
                    platform, minimum, sdk, tools = struct.unpack_from(endian + '4I', raw, pos + 8)
                    result['build_versions'].append({'platform': platform, 'minimum_raw': minimum,
                                                     'sdk_raw': sdk, 'tool_count': tools})
                    need(length == 24 + tools * 8, 'observation_build_tools_bounds')
                elif command == 0x1d:
                    need(length >= 16 and len(result['signature_commands']) < 16, 'observation_signature_bounds')
                    offset, size_bytes = struct.unpack_from(endian + 'II', raw, pos + 8)
                    result['signature_commands'].append({'offset': offset, 'bytes': size_bytes})
            except (contract.Blocked, struct.error) as error:
                if bucket == 'rpaths': result['rpaths_complete'] = False
                note(error, index)
            pos += length
        need(pos == 32 + size, 'observation_command_consumption')
        result['commands_consumed'] = True
    except (contract.Blocked, struct.error) as error:
        result.update(commands_consumed=False, rpaths_complete=False)
        note(error)
    result['parse_complete'] = result['parse_error_count'] == 0
    return result


def observe_owned_main():
    """Read only the fixed main app through no-follow, owned directory fds.

    This is diagnostic evidence, never whole-archive acceptance. No directory is
    enumerated and no app code runs. The original strict scan still follows.
    """
    descriptors = []
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    def read_at(directory, name, maximum):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                 before.st_nlink == 1 and not before.st_mode & 0o7000 and
                 0 < before.st_size <= maximum, 'main_observation_file_shape')
            raw = bytearray()
            while block := os.read(fd, min(65536, maximum + 1 - len(raw))):
                raw.extend(block)
                need(len(raw) <= before.st_size, 'main_observation_file_grew')
            need(identity(before) == identity(os.fstat(fd)) ==
                 identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) and
                 len(raw) == before.st_size, 'main_observation_file_changed')
            return bytes(raw)
        finally:
            os.close(fd)
    try:
        for name in (str(ROOT), 'build', 'tv-rpath-diagnostic', 'TouchColor.xcarchive',
                     'Products', 'Applications', 'TouchColor.app'):
            parent = descriptors[-1][0] if descriptors else None
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent)
            before = os.fstat(fd)
            descriptors.append((fd, parent, name, before))
            need(stat.S_ISDIR(before.st_mode) and before.st_uid == os.geteuid(),
                 'main_observation_directory_shape')
        app_fd = descriptors[-1][0]
        info_raw = read_at(app_fd, 'Info.plist', 1024 * 1024)
        info = contract.load_plist(info_raw)
        expected = {'CFBundleIdentifier': 'com.mango.touchColor', 'CFBundleExecutable': 'TouchColor',
                    'CFBundleShortVersionString': '2.0.1', 'CFBundleVersion': '20002'}
        need(all(type(info.get(k)) is str and info[k] == value for k, value in expected.items()),
             'main_observation_identity_mismatch')
        # Bundle identity locates the target. Platform/signature/release policy
        # is deliberately evaluated only after its raw facts have been emitted.
        raw = read_at(app_fd, 'TouchColor', 64 * 1024 * 1024)
        actual = observe_macho_bytes(raw)
        fields = ('CFBundleIdentifier', 'CFBundleExecutable', 'CFBundleShortVersionString',
                  'CFBundleVersion', 'CFBundlePackageType', 'DTPlatformName', 'DTSDKName',
                  'CFBundleSupportedPlatforms', 'UIDeviceFamily', 'MinimumOSVersion',
                  'NSExtension', 'WKWatchKitApp', 'LSRequiresIPhoneOS')
        selected = {key: {'present': key in info, 'value': info.get(key),
                          'python_type': type(info.get(key)).__name__} for key in fields}
        actual['info_plist'] = {'bytes': len(info_raw), 'sha256': hashlib.sha256(info_raw).hexdigest(),
                               'fields': selected}
        # Generated Info values here should be scalar/list/dictionary property
        # list data. Bound non-JSON or oversized values without losing main-image
        # evidence; the strict validator still independently rejects as needed.
        for key, value in selected.items():
            try:
                encoded = json.dumps(value, sort_keys=True).encode()
                if len(encoded) > 1024: raise ValueError('field limit')
            except (TypeError, ValueError):
                selected[key] = {'present': key in info, 'python_type': type(info.get(key)).__name__,
                                 'value_omitted': True, 'omission_reason': 'non_json_or_over_1024_bytes',
                                 'raw_plist_sha256': hashlib.sha256(info_raw).hexdigest()}
        for fd, parent, name, before in descriptors:
            need(identity(before) == identity(os.fstat(fd)) ==
                 identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                 'main_observation_directory_changed')
        return raw, actual, info
    finally:
        for fd, _, _, _ in reversed(descriptors):
            os.close(fd)


def scan_with_evidence(archive, deadline, report):
    """Keep the original scan and verdict; retain its rejecting entry metadata.

    The exact original scan frame supplies its already-lstat'ed entry. We do not
    follow/read the rejected path or infer an offender from a later filesystem.
    """
    try:
        return scan(archive, deadline)
    except Exception as error:
        detail = {'reason': str(error)[:256], 'entry_metadata_available': False}
        entry_reasons = {'archive-linked-or-nonregular', 'archive-hardlink',
                         'unexpected-code-or-signature', 'unexpected-product',
                         'unexpected-archive-entry', 'unexpected-executable', 'unexpected-mach-o'}
        trace = error.__traceback__ if str(error) in entry_reasons else None
        while trace is not None:
            if trace.tb_frame.f_code is getattr(scan, '__code__', None):
                values = trace.tb_frame.f_locals
                key, value = values.get('key'), values.get('value')
                if isinstance(key, str) and 0 < len(key) <= 1024 and isinstance(value, os.stat_result):
                    kind = ('directory' if stat.S_ISDIR(value.st_mode) else
                            'regular' if stat.S_ISREG(value.st_mode) else
                            'symlink' if stat.S_ISLNK(value.st_mode) else 'other')
                    detail.update(entry_metadata_available=True, relative_path=key,
                                  file_type=kind, bytes=value.st_size,
                                  mode=oct(stat.S_IMODE(value.st_mode)), links=value.st_nlink)
                break
            trace = trace.tb_next
        report['archive_scan_rejection'] = detail
        raise


def identity():
    expected = {'GITHUB_REPOSITORY': '100mango/ColorPicker', 'GITHUB_REF': BRANCH,
                'GITHUB_WORKFLOW_REF': '100mango/ColorPicker/' + WORKFLOW + '@' + BRANCH,
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'archive',
                'GITHUB_ACTOR': '100mango', 'GITHUB_TRIGGERING_ACTOR': '100mango',
                'DEVELOPER_DIR': DEVELOPER}
    need(all(os.environ.get(k) == v for k, v in expected.items()), 'diagnostic_job_binding')
    sha = os.environ.get('GITHUB_SHA', '')
    need(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
         'diagnostic_control_binding')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    need(re.fullmatch('[1-9][0-9]{0,19}', run_id), 'diagnostic_run_binding')
    need(not any(k in os.environ for k in ('APP_STORE_CONNECT_PRIVATE_KEY', 'ASC_PRIVATE_KEY',
                                         'APPLE_API_KEY', 'APPLE_ID_PASSWORD')), 'credentials_forbidden')
    return {'schema': 1, 'control_sha': sha, 'run_id': run_id, 'run_attempt': 1,
            'product_sha': BASE, 'product_tree': BASE_TREE, 'branch': BRANCH}


def safe_command(argv):
    # Preserve the existing capture implementation while ensuring no inherited
    # GitHub token, key, signing setting, hook or login HOME reaches a child.
    return ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin:/usr/sbin:/sbin',
            'HOME=' + str(WORK / 'home'), 'CFFIXED_USER_HOME=' + str(WORK / 'home'),
            'TMPDIR=' + str(WORK / 'tmp'), 'DEVELOPER_DIR=' + DEVELOPER,
            'LANG=en_US.UTF-8', 'LC_ALL=en_US.UTF-8', *argv]


def source_identity(binding, run):
    def git(*args): return run(['/usr/bin/git', *args], seconds=10, cap=262144).decode().strip()
    need(git('rev-parse', 'HEAD') == binding['control_sha'], 'diagnostic_head_changed')
    need(git('rev-parse', BASE + '^{tree}') == BASE_TREE, 'diagnostic_product_tree')
    need(git('rev-list', '--parents', '-n', '1', 'HEAD').split() == [binding['control_sha'], BASE],
         'diagnostic_sole_parent')
    need(sorted(git('diff', '--name-status', BASE, 'HEAD', '--').splitlines()) ==
         sorted('A\t' + p for p in ADDITIONS), 'diagnostic_product_modified')
    need(git('status', '--porcelain', '--untracked-files=all') == '', 'diagnostic_dirty_source')
    for path, expected in (('TouchColorTV.xcodeproj/project.pbxproj', '87372c3ab2056ec4fac4ef603e96e0c0bf28e875'),
                           ('TouchColorTV.xcodeproj/xcshareddata/xcschemes/TouchColorTV.xcscheme', '60ac5c8f058f07543844cb72b132903b4b27b69f')):
        need(git('hash-object', path) == expected, 'diagnostic_product_blob')
    return {'control_tree': git('rev-parse', 'HEAD^{tree}'), 'product_unchanged': True}


def cleanup(binding):
    need(not (ROOT / 'build').is_symlink() and not WORK.is_symlink(), 'cleanup_path_link')
    if not WORK.exists(): return True
    marker = WORK / '.owned.json'
    need(marker.is_file() and not marker.is_symlink() and marker.stat().st_uid == os.geteuid(), 'cleanup_marker')
    need(json.loads(contract.read_regular(marker, 4096)) == binding, 'cleanup_owner_mismatch')
    state = json.loads(contract.read_regular(WORK / '.process-state.json', 4096))
    need(state.get('binding') == binding and state.get('state') in
         ('not_started', 'completed', 'stopped_confirmed'), 'cleanup_process_ownership_uncertain')
    shutil.rmtree(WORK)
    need(not WORK.exists(), 'cleanup_incomplete')
    return True


def archive_argv():
    # The successful TV archive lane's Release/appletvos/arm64 command, with
    # the existing stricter unsigned package-resolution/profile empty controls.
    return ['/usr/bin/xcodebuild', 'archive', '-quiet', '-project', 'TouchColorTV.xcodeproj',
            '-scheme', 'TouchColorTV', '-configuration', 'Release', '-sdk', 'appletvos',
            '-destination', 'generic/platform=tvOS', '-derivedDataPath', str(WORK / 'DerivedData'),
            '-archivePath', str(ARCHIVE), '-disableAutomaticPackageResolution',
            '-onlyUsePackageVersionsFromResolvedFile', 'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=NO',
            'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY=',
            'CODE_SIGN_STYLE=Manual', 'DEVELOPMENT_TEAM=', 'PROVISIONING_PROFILE=',
            'PROVISIONING_PROFILE_SPECIFIER=', 'OTHER_CODE_SIGN_FLAGS=']


def main():
    os.chdir(ROOT)
    binding = identity()
    if sys.argv[1:] == ['cleanup']:
        result = {'binding': binding, 'confirmed': False}
        try: result['confirmed'] = cleanup(binding)
        except Exception as error: result.update(reason=str(error)[:256], failure_type=type(error).__name__)
        print('TV_RPATH_CLEANUP ' + json.dumps(result, sort_keys=True), flush=True)
        return 0 if result['confirmed'] else 1
    need(not sys.argv[1:], 'diagnostic_unknown_action')
    started = float(os.environ.get('TV_RPATH_STARTED_MONOTONIC', 'nan'))
    need(math.isfinite(started) and 0 <= time.monotonic() - started < 25 * 60, 'diagnostic_original_clock')
    deadline = started + 25 * 60 - 150  # Always leave cleanup and final reporting time.
    receipts = []
    report = {**binding, 'status': 'incomplete', 'signed_export': False, 'upload_invoked': False,
              'release_qualification': False, 'archive_attempts': 0, 'archive_execution': 'not_started',
              'cleanup_confirmed': False, 'process_state': 'not_started'}
    def state(value):
        report['process_state'] = value
        write_json(WORK / '.process-state.json', {'binding': binding, 'state': value}, limit=4096)
    def tracked_capture(argv, **kwargs):
        need(report['process_state'] in ('not_started', 'completed', 'stopped_confirmed'),
             'further_command_after_uncertain_ownership')
        is_archive = '/usr/bin/xcodebuild' in argv and 'archive' in argv
        state('in_flight')  # A crash leaves this durable latch for the always step.
        if is_archive: report['archive_execution'] = 'launch_outcome_unknown'
        try:
            result = capture(argv, **kwargs)
        except CaptureStopped as error:
            known = error.cleanup_confirmed is True
            before_spawn = known and str(error) == 'interrupted-before-spawn'
            state('not_started' if before_spawn else 'stopped_confirmed' if known else 'uncertain')
            if is_archive:
                report['archive_execution'] = 'not_started' if before_spawn else 'stopped_confirmed' if known else 'cleanup_unknown'
            raise
        except BaseException:
            # No proven lifecycle receipt is never treated as pre-spawn success.
            state('uncertain')
            if is_archive: report['archive_execution'] = 'launch_outcome_unknown'
            raise
        state('completed')
        if is_archive: report.update(archive_execution='completed', archive_exit=result.returncode)
        return result
    def run(argv, seconds=30, cap=262144):
        need(report['process_state'] in ('not_started', 'completed', 'stopped_confirmed'),
             'further_command_after_uncertain_ownership')
        return command(safe_command(argv), deadline=deadline, seconds=seconds, cap=cap,
                       receipts=receipts, runner=tracked_capture)
    code = 1
    try:
        need(not (ROOT / 'build').is_symlink() and not WORK.exists() and not WORK.is_symlink(), 'fresh_owned_work_required')
        WORK.mkdir(parents=True, mode=0o700)
        (WORK / '.owned.json').write_text(json.dumps(binding, sort_keys=True))
        state('not_started')
        for name in ('home', 'tmp'): (WORK / name).mkdir(mode=0o700)
        report['source_before'] = source_identity(binding, run)
        xcode = run(['/usr/bin/xcodebuild', '-version']).decode().strip()
        need(xcode == 'Xcode 27.0\nBuild version 27A266a', 'exact_xcode_required')
        need(run(['/usr/bin/uname', '-m']).strip() == b'arm64', 'exact_host_arch_required')
        host_version = run(['/usr/bin/sw_vers', '-productVersion']).decode().strip()
        host_build = run(['/usr/bin/sw_vers', '-buildVersion']).decode().strip()
        need((host_version, host_build) in {('27.0', '26A428'), ('27.0.1', '26A434')}, 'exact_host_pair_required')
        report['toolchain'] = {'xcode': xcode, 'host_version': host_version, 'host_build': host_build, 'architecture': 'arm64'}
        need(b'appletvos27.0' in run(['/usr/bin/xcodebuild', '-showsdks']), 'exact_tvos_sdk_required')
        # The pinned TV project is already materialized. No generator or product
        # source update is needed for this archive-only observation.
        report['archive_attempts'] = 1
        run(archive_argv(), seconds=420, cap=16 * 1024 * 1024)
        need(report['archive_execution'] == 'completed' and report.get('archive_exit') == 0,
             'archive_completion_unproven')
        report['source_after'] = source_identity(binding, run)
        # Preserve the purpose of this one-shot run even when an unrelated full
        # archive-layout gate rejects. Only fixed owned main-image bytes can be
        # observed here; all original layout and app safety gates remain below.
        raw, report['actual_rpaths'], observed_info = observe_owned_main()
        print('TV_RPATH_ACTUAL ' + json.dumps(report['actual_rpaths'], sort_keys=True), flush=True)
        comparison = {'scope': 'same_bounded_named_main_file_bytes_only',
                      'validator_expectation': 'unsigned touch-tv main MH_EXECUTE',
                      'original_validator_sha256': contract.ORIGINAL_VALIDATOR_SHA256,
                      'fixed_validator_sha256': contract.FIXED_VALIDATOR_SHA256}
        for name, validator in (('original', contract.inspect_macho_original), ('fixed', contract.inspect_macho)):
            try:
                validator('touch-tv', raw, False)
                comparison[name] = 'passed'
            except contract.Blocked as error:
                comparison[name] = str(error)
        try:
            contract.validate_info('touch-tv', observed_info)
            comparison['info_policy'] = 'passed'
        except contract.Blocked as error:
            comparison['info_policy'] = str(error)
        report['main_verifier_comparison'] = comparison
        print('TV_RPATH_MAIN_COMPARISON ' + json.dumps(comparison, sort_keys=True), flush=True)
        archive_before = scan_with_evidence(ARCHIVE, deadline, report)
        need(set((ARCHIVE / 'Products/Applications').iterdir()) == {APP} and
             set(ARCHIVE.rglob('*.app')) == {APP} and not list(ARCHIVE.rglob('*.appex')),
             'archive_app_inventory_invalid')
        props = contract.load_plist(contract.read_regular(ARCHIVE / 'Info.plist', 65536)).get('ApplicationProperties', {})
        need(props.get('ApplicationPath') == 'Applications/TouchColor.app' and
             props.get('CFBundleIdentifier') == 'com.mango.touchColor' and
             str(props.get('CFBundleShortVersionString')) == '2.0.1' and
             str(props.get('CFBundleVersion')) == '20002', 'archive_metadata_mismatch')
        binary = APP / 'TouchColor'
        need(contract.read_regular(binary) == raw, 'image_changed_since_observation')
        need(report['actual_rpaths']['executable_sha256'] == hashlib.sha256(raw).hexdigest(), 'image_changed')
        otool = run(['/usr/bin/otool', '-l', str(binary)], seconds=20, cap=262144).decode('utf-8', 'strict')
        report['otool_l_sha256'] = hashlib.sha256(otool.encode()).hexdigest()
        report['otool_rpaths'] = re.findall(r'cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.+?) \(offset \d+\)', otool)
        need(report['otool_rpaths'] == [r['path_utf8'] for r in report['actual_rpaths']['rpaths']], 'otool_rpath_disagreement')
        try:
            contract.inspect_macho_original('touch-tv', raw, False)
            report['old_verifier'] = 'passed'
        except contract.Blocked as error:
            report['old_verifier'] = str(error)
        try:
            checked = contract.inspect_app('touch-tv', APP, signed=False)
            report['fixed_verifier'] = 'passed'
            report['fixed_rpath_classes'] = checked['executable_contract']['rpath_classes']
        except contract.Blocked as error:
            report['fixed_verifier'] = str(error)
            raise
        report['validator_sha256'] = {'original': contract.ORIGINAL_VALIDATOR_SHA256, 'fixed': contract.FIXED_VALIDATOR_SHA256}
        need(report['old_verifier'] == 'rpath_not_allowlisted', 'expected_old_rejection_not_reproduced')
        need('touch_main_loader_frameworks' in report['fixed_rpath_classes'], 'exact_new_path_not_observed')
        need(contract.read_regular(binary) == raw, 'image_changed_after_validation')
        grant = min(20, deadline - time.monotonic() - 4)
        need(grant > 0, 'unsigned_check_deadline')
        unsigned = tracked_capture(safe_command(['/usr/bin/codesign', '-d', str(APP)]), seconds=grant, cap=65536)
        need(unsigned.returncode != 0 and b'not signed at all' in (unsigned.stdout + unsigned.stderr).lower(),
             'unsigned_archive_unproven')
        report['unsigned_codesign_proven'] = True
        need(scan_with_evidence(ARCHIVE, deadline, report) == archive_before, 'archive_changed_during_diagnostic')
        report['archive_snapshot_unchanged'] = True
        report['source_final'] = source_identity(binding, run)
        report['status'] = 'unsigned_rpath_diagnosis_passed'
        code = 0
    except BaseException as error:
        # Only bounded reason text from a fixed diagnostic; never dump environment.
        report['failure_type'] = type(error).__name__
        report['failure_reason'] = str(error)[:256]
    finally:
        try: report['cleanup_confirmed'] = cleanup(binding)
        except Exception as error:
            report['cleanup_failure'] = type(error).__name__
            report['cleanup_reason'] = str(error)[:256]
            code = 1
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['commands_completed'] = sum(r.get('complete') is True for r in receipts)
        report['bounded_command_count'] = len(receipts)
        need(len(json.dumps(report)) <= 65536, 'diagnostic_report_limit')
        print('TV_RPATH_DIAGNOSTIC ' + json.dumps(report, sort_keys=True), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
