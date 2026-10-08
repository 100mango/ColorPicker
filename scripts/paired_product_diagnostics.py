"""Read-only, bounded identities for the six source-owned paired app products.

Identity collection launches no commands. Registration runs only through an
explicitly injected executor; ``run_inspection`` is an optional bounded capture
primitive for that owner. The lifecycle owner supplies exact product paths and
trusted source roots (installed paths must come from the owned
simulator's app container lookup, never its data container). It must admit this
work to its existing budget and confirm XCTest process-group cleanup before a
post-test read. Receipts are observations, not an acceptance gate: differing
hashes, especially for separately built products, do not establish a defect.

Registration is optional and fail-closed. Its injected executor must enforce the
provided timeout/output cap while capturing, suppress all raw output from logs,
and return CommandResult only after confirming its owned process group exited.
No private commands, guessed flags, listapps inventory, or signing are used.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import stat
import subprocess
import time

from bounded_process import stop_group


PHONE_ID = 'com.mango.touchColor'
WATCH_ID = PHONE_ID + '.watchkitapp'
PRODUCT_ROLES = {
    'builtPhone': PHONE_ID,
    'embeddedWatch': WATCH_ID,
    'standaloneWatch': WATCH_ID,
    'installedPhone': PHONE_ID,
    'installedEmbeddedWatch': WATCH_ID,
    'installedWatch': WATCH_ID,
}
PLIST_KEYS = (
    'CFBundleIdentifier', 'CFBundleExecutable', 'CFBundlePackageType',
    'CFBundleShortVersionString', 'CFBundleVersion', 'CFBundleSupportedPlatforms',
    'MinimumOSVersion', 'DTPlatformName', 'DTSDKName', 'UIDeviceFamily',
    'WKApplication', 'WKWatchKitApp', 'WKWatchOnly',
    'WKRunsIndependentlyOfCompanionApp', 'WKCompanionAppBundleIdentifier',
)
REGISTRATION_KEYS = ('CFBundleIdentifier', 'CFBundleExecutable',
                     'CFBundleVersion', 'ApplicationType')


@dataclass(frozen=True)
class Limits:
    plist_bytes: int = 65_536
    binary_bytes: int = 33_554_432
    total_hash_bytes: int = 134_217_728
    app_entries: int = 128
    command_bytes: int = 65_536
    command_timeout: float = 10.0
    filesystem_seconds: float = 10.0


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    # Combined stdout/stderr bytes for compatibility with runtime-help streams.
    # These bytes are transient parser input and must not be logged or retained.
    stdout: bytes
    cleanup_confirmed: bool
    output_truncated: bool = False
    timed_out: bool = False


def run_inspection(argv, timeout, max_output_bytes):
    """Capture both streams in one bounded pipe and clean the owned group.

    The caller owns command authorization, budget admission, and cleanup-failure
    latching. This primitive constructs no commands, prints nothing, writes no
    files, and never uses unbounded ``communicate``. Its cleanup allowance is the
    existing ``stop_group`` allowance, additional to the command timeout.
    ``CommandResult.stdout`` contains combined stdout/stderr. Help may arrive on
    either stream; mixed app/path output must pass its strict structured parser.
    """
    if (type(max_output_bytes) is not int or not 0 < max_output_bytes <= 65_536 or
            type(timeout) not in (int, float) or not 0 < timeout <= 30):
        raise ValueError('Invalid bounded inspection limits')
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    output = bytearray()
    truncated = timed_out = cleanup_confirmed = False
    poller = None
    try:
        poller = selectors.DefaultSelector()
        os.set_blocking(process.stdout.fileno(), False)
        poller.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in poller.select(min(remaining, 0.05)):
                try:
                    chunk = os.read(key.fd, min(65_536, max_output_bytes - len(output) + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    poller.unregister(key.fileobj)
                elif len(chunk) > max_output_bytes - len(output):
                    output.extend(chunk[:max_output_bytes - len(output)])
                    truncated = True
                    break
                else:
                    output.extend(chunk)
            if truncated or (not poller.get_map() and process.poll() is not None):
                break
        cleanup_confirmed = stop_group(process)
    except BaseException as error:
        try:
            confirmed = stop_group(process)
        except BaseException:
            confirmed = False
        # The owner must be able to latch cleanup uncertainty even when a pipe
        # operation, cancellation, or cleanup implementation raised unexpectedly.
        error.cleanup_confirmed = confirmed
        raise
    finally:
        if poller is not None:
            poller.close()
        process.stdout.close()
    code = process.returncode if type(process.returncode) is int else 125
    return CommandResult(code, bytes(output), cleanup_confirmed, truncated, timed_out)


class _Incomplete(Exception):
    pass


def _limits_valid(limits):
    # Callers may lower bounds, never expand this diagnostic's retention scope.
    defaults = Limits()
    return isinstance(limits, Limits) and all(
        type(getattr(limits, key)) in (int, float) and
        0 < getattr(limits, key) <= getattr(defaults, key)
        for key in defaults.__dataclass_fields__
    ) and all(type(getattr(limits, key)) is int for key in
              ('plist_bytes', 'binary_bytes', 'total_hash_bytes',
               'app_entries', 'command_bytes'))


def _absolute(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise _Incomplete('unsafe_path')
    return path


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise _Incomplete('filesystem_time_limit')


def _open_app(path, roots, owner_uid, limits, deadline):
    _check_deadline(deadline)
    path = _absolute(path)
    if path.name != 'TouchColor.app':
        raise _Incomplete('unexpected_app_name')
    matches = [root for root in roots if root == path or root in path.parents]
    if not matches:
        raise _Incomplete('outside_source_roots')
    root = max(matches, key=lambda value: len(value.parts))
    # Descriptor-relative traversal rejects symlinks at every component, not
    # merely the final pathname, and keeps later reads bound to this directory.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open('/', flags)
    try:
        for depth, component in enumerate(path.parts[1:], start=2):
            _check_deadline(deadline)
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if depth >= len(root.parts) and os.fstat(descriptor).st_uid != owner_uid:
                raise _Incomplete('foreign_owner')
        with os.scandir(descriptor) as entries:
            for count, _ in enumerate(entries, start=1):
                _check_deadline(deadline)
                if count > limits.app_entries:
                    raise _Incomplete('app_entry_limit')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _file_receipt(directory, name, owner_uid, byte_limit, *, hash_only=False,
                  remaining=None, deadline):
    _check_deadline(deadline)
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _Incomplete('not_regular_file')
        if before.st_uid != owner_uid:
            raise _Incomplete('foreign_owner')
        if before.st_nlink != 1:
            raise _Incomplete('hardlinked_file')
        if before.st_size > byte_limit:
            raise _Incomplete('file_size_limit')
        if remaining is not None and before.st_size > remaining[0]:
            raise _Incomplete('total_hash_limit')
        digest = hashlib.sha256() if hash_only else None
        chunks, total = [], 0
        while True:
            _check_deadline(deadline)
            read_size = min(65_536, byte_limit - total + 1)
            if remaining is not None:
                read_size = min(read_size, remaining[0] + 1)
            raw = os.read(descriptor, read_size)
            if not raw:
                break
            total += len(raw)
            if remaining is not None:
                remaining[0] -= len(raw)
            if remaining is not None and remaining[0] < 0:
                raise _Incomplete('total_hash_limit')
            if total > byte_limit:
                raise _Incomplete('file_size_limit')
            if digest is not None:
                digest.update(raw)
            else:
                chunks.append(raw)
        after = os.fstat(descriptor)
        _check_deadline(deadline)
        if total != before.st_size or (before.st_size, before.st_mtime_ns,
                                      before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise _Incomplete('file_changed_during_read')
        return ({'status': 'observed', 'file': name, 'bytes': total, 'sha256': digest.hexdigest()}
                if digest is not None else b''.join(chunks))
    finally:
        os.close(descriptor)


def _small_value(value):
    if type(value) is bool or (type(value) is int and -(2 ** 63) <= value < 2 ** 63):
        return True
    if type(value) is str:
        return len(value) <= 256 and not any(ord(char) < 32 for char in value)
    if type(value) is list:
        return len(value) <= 8 and all(type(item) in (str, int, bool) and
                                     _small_value(item) for item in value)
    return False


def _selected_fields(info, keys):
    values, invalid = {}, []
    for key in keys:
        if key in info:
            if _small_value(info[key]):
                values[key] = info[key]
            else:
                invalid.append(key)
    return {'values': values, 'absent': [key for key in keys if key not in info],
            'invalid': invalid}


def _identity(path, expected, roots, owner_uid, limits, remaining, deadline):
    descriptor = None
    result = {'status': 'incomplete', 'expectedBundleIdentifier': expected}
    try:
        descriptor = _open_app(path, roots, owner_uid, limits, deadline)
        raw = _file_receipt(descriptor, 'Info.plist', owner_uid, limits.plist_bytes,
                            deadline=deadline)
        info = plistlib.loads(raw)
        if not isinstance(info, dict) or len(info) > limits.app_entries:
            raise _Incomplete('invalid_plist_shape')
        result['info'] = _selected_fields(info, PLIST_KEYS)
        result['bundleIdentifierMatchesExpected'] = info.get('CFBundleIdentifier') == expected
        if not result['bundleIdentifierMatchesExpected']:
            raise _Incomplete('unexpected_bundle_identifier')
        if info.get('CFBundleExecutable') != 'TouchColor':
            raise _Incomplete('unexpected_executable')
        result['executable'] = _file_receipt(
            descriptor, 'TouchColor', owner_uid, limits.binary_bytes,
            hash_only=True, remaining=remaining, deadline=deadline)
        try:
            result['debugDylib'] = _file_receipt(
                descriptor, 'TouchColor.debug.dylib', owner_uid,
                limits.binary_bytes, hash_only=True, remaining=remaining,
                deadline=deadline)
        except FileNotFoundError:
            result['debugDylib'] = {'status': 'absent'}
        result['status'] = 'observed' if not result['info']['invalid'] else 'incomplete'
        if result['info']['invalid']:
            result['reason'] = 'invalid_whitelisted_field'
    except _Incomplete as error:
        result['reason'] = str(error)
    except Exception:
        result['reason'] = 'unreadable_or_invalid_product'
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result


def collect_product_identities(products, allowed_roots, *, owner_uid=None,
                               limits=Limits()):
    """Return fixed-role product observations; do not resolve or scan app data.

    ``allowed_roots`` must be exact build-product/owned installed-app roots, not
    broad home, device-data, or filesystem roots. Paths must be absolute with no
    symlink components. Unknown roles are not read. Paths are never retained.
    """
    started = time.monotonic()
    result = {'schema': 1, 'status': 'incomplete', 'products': {},
              'hashInterpretation': 'observations_only_no_defect_inference'}
    if not _limits_valid(limits) or not isinstance(products, dict) or len(products) > 6:
        result['reason'] = 'invalid_arguments'
        return result
    try:
        # Read at most six explicitly supplied boundaries. A generator is not
        # accepted: consuming an unbounded source would defeat these limits.
        if not isinstance(allowed_roots, (list, tuple)) or not 1 <= len(allowed_roots) <= 6:
            raise _Incomplete('invalid_source_roots')
        roots = [_absolute(root) for root in allowed_roots]
        if any(root == Path('/') for root in roots):
            raise _Incomplete('invalid_source_roots')
        uid = os.getuid() if owner_uid is None else owner_uid
        if type(uid) is not int or uid < 0:
            raise _Incomplete('invalid_owner')
    except (_Incomplete, TypeError, ValueError):
        result['reason'] = 'invalid_source_roots_or_owner'
        return result
    remaining = [limits.total_hash_bytes]
    deadline = started + limits.filesystem_seconds
    for role, expected in PRODUCT_ROLES.items():
        result['products'][role] = (
            _identity(products[role], expected, roots, uid, limits, remaining, deadline)
            if role in products else {'status': 'incomplete', 'reason': 'path_unavailable'})
    result['unexpectedRolesIgnored'] = any(role not in PRODUCT_ROLES for role in products)
    result['status'] = ('observed' if all(item['status'] == 'observed'
                        for item in result['products'].values()) else 'incomplete')
    result['elapsedSeconds'] = round(time.monotonic() - started, 3)
    result['hashBytesRead'] = limits.total_hash_bytes - remaining[0]
    return result


def _command(execute, command, stage, limits, receipt):
    try:
        result = execute(command, timeout=limits.command_timeout,
                         max_output_bytes=limits.command_bytes)
    except Exception as error:
        if getattr(error, 'cleanup_confirmed', None) is False:
            receipt['cleanupUnconfirmed'] = True
        raise _Incomplete(stage + '_executor_failed') from None
    if not isinstance(result, CommandResult):
        raise _Incomplete(stage + '_invalid_executor_receipt')
    if type(result.returncode) is not int or not -255 <= result.returncode <= 255:
        raise _Incomplete(stage + '_invalid_exit')
    if not isinstance(result.stdout, bytes):
        raise _Incomplete(stage + '_invalid_output')
    receipt['attempts'].append({'stage': stage, 'exit': result.returncode,
                                'bytes': len(result.stdout),
                                'truncated': result.output_truncated is not False,
                                'timedOut': result.timed_out is not False,
                                'cleanupConfirmed': result.cleanup_confirmed is True})
    if result.cleanup_confirmed is not True:
        receipt['cleanupUnconfirmed'] = True
        raise _Incomplete(stage + '_cleanup_unconfirmed')
    if result.output_truncated is not False or len(result.stdout) > limits.command_bytes:
        raise _Incomplete(stage + '_output_limit')
    if result.timed_out is not False:
        raise _Incomplete(stage + '_timeout')
    if result.returncode != 0:
        raise _Incomplete(stage + '_failed')
    return result.stdout


def collect_registration_receipt(device_udid, bundle_id, execute=None, *, limits=Limits()):
    """Observe one exact owned app only after actual runtime help proves syntax.

    The owner must verify ``device_udid`` belongs to its test pair. There is no
    default executor. Unknown help/output formats stay explicitly unavailable.
    The supported grammar has only device and bundle-identifier arguments.
    """
    receipt = {'schema': 1, 'status': 'unavailable', 'attempts': [],
               'capability': {'appinfoListed': False, 'usageVerified': False}}
    if (not _limits_valid(limits) or type(device_udid) is not str or
            not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', device_udid)
            or bundle_id not in (PHONE_ID, WATCH_ID)):
        receipt['reason'] = 'invalid_owned_target_or_limits'
        return receipt
    receipt['bundleIdentifier'] = bundle_id
    if execute is None:
        receipt['reason'] = 'runtime_capability_not_verified'
        return receipt
    try:
        raw = _command(execute, ['xcrun', 'simctl', 'help'], 'help', limits, receipt)
        help_text = raw.decode('utf-8')
        # An actual command-table entry, not a prose mention or a private alias.
        if not re.search(r'^\s+appinfo[ \t]{2,}\S[^\n]*$', help_text, re.MULTILINE):
            raise _Incomplete('appinfo_not_listed')
        receipt['capability']['appinfoListed'] = True
        receipt['capability']['topLevelHelpSHA256'] = hashlib.sha256(raw).hexdigest()
        raw = _command(execute, ['xcrun', 'simctl', 'help', 'appinfo'],
                       'appinfo_help', limits, receipt)
        usage = raw.decode('utf-8')
        usages = re.findall(r'^\s*Usage:\s*(.*?)\s*$', usage, re.MULTILINE)
        if len(usages) != 1 or not re.fullmatch(
                r'simctl appinfo <device> <(?:app bundle identifier|app-bundle-identifier|bundle identifier|bundle-identifier)>',
                usages[0]):
            raise _Incomplete('appinfo_usage_unverified')
        receipt['capability']['usageVerified'] = True
        receipt['capability']['appinfoHelpSHA256'] = hashlib.sha256(raw).hexdigest()
        receipt['capability']['verifiedUsage'] = 'Usage: ' + usages[0]
        raw = _command(execute, ['xcrun', 'simctl', 'appinfo', device_udid, bundle_id],
                       'appinfo', limits, receipt)
        # Accept only structurally parsed dictionary formats. Unsupported
        # OpenStep/prose output is incomplete, not a reason to invoke plutil or
        # guess an output flag or broaden to a device-wide inventory.
        try:
            info = plistlib.loads(raw)
        except (ValueError, plistlib.InvalidFileException):
            info = json.loads(raw)
        if not isinstance(info, dict) or len(info) > limits.app_entries:
            raise _Incomplete('appinfo_shape_unverified')
        if info.get('CFBundleIdentifier') != bundle_id:
            raise _Incomplete('appinfo_identity_unverified')
        receipt['info'] = _selected_fields(info, REGISTRATION_KEYS)
        if receipt['info']['invalid']:
            raise _Incomplete('appinfo_invalid_whitelisted_field')
        receipt['status'] = 'observed'
    except _Incomplete as error:
        receipt['reason'] = str(error)
    except Exception:
        receipt['reason'] = 'appinfo_output_unverified'
    return receipt
