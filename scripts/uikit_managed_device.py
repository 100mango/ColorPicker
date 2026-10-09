"""Closed canonical UIKit destination ownership; configuration is not installation.

Only the four existing compatibility profiles are supported. Warmup.command owns
every simulator process, its absolute preparation clock and its uncertainty latch.
This module never boots, installs, launches, selects a template, or changes tests.
The caller separately verifies the checkout and built test-product fingerprints.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import time

from atomic_json import write_json
from palette_lifecycle_diagnostics import require, strict_json, valid_uuid
from uikit_runtime_diagnostics import read_identity, validate_identity

REPOSITORY = '100mango/ColorPicker'
REF = 'refs/heads/ios-original-release'
WORKFLOW = REPOSITORY + '/.github/workflows/ios.yml@' + REF
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
PROFILES = {'iPadMini': 'iPad mini (A17 Pro)',
            'iPadLarge': 'iPad Pro 13-inch (M5)',
            'iPhoneCompact': 'iPhone SE (3rd generation)',
            'iPhoneLarge': 'iPhone 18 Pro Max'}
CONTRACT = 'canonical-uikit-managed-device-v1'
INVENTORY = ['xcrun', 'simctl', 'list', '-j']
READBACK = ['xcrun', 'simctl', 'list', 'devices', 'available', '-j']
RECEIPT_LIMIT = 16384


def require_job(family):
    """Host-only current canonical context. This does not verify checkout bytes."""
    require(family in PROFILES, 'Unknown canonical UIKit family')
    ref = os.environ.get('GITHUB_REF')
    from uikit_completion import completion_group, REF as COMPLETION_REF, WORKFLOW as COMPLETION_WORKFLOW
    selected = completion_group(family)
    require(ref == (COMPLETION_REF if selected else REF), 'Unknown staged iOS qualification branch')
    workflow = COMPLETION_WORKFLOW if selected else WORKFLOW
    job = 'completion' if selected else 'compatibility'
    expected = {'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_REF': ref,
                'GITHUB_WORKFLOW_REF': workflow, 'GITHUB_ACTIONS': 'true',
                'GITHUB_JOB': job, 'RUNNER_OS': 'macOS',
                'TC_TEST_FAMILY': family}
    require(all(os.environ.get(key) == value for key, value in expected.items()),
            'Exact canonical UIKit compatibility job required')
    event = os.environ.get('GITHUB_EVENT_NAME')
    require(event in ('push', 'workflow_dispatch'), 'Unexpected canonical workflow event')
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and os.environ.get('GITHUB_WORKFLOW_SHA') == sha,
            'Exact workflow/source binding required')
    run, attempt = (os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
    require(all(re.fullmatch('[1-9][0-9]{0,19}', value) for value in (run, attempt)),
            'Exact run/attempt identity required')
    return {'repository': REPOSITORY, 'ref': ref, 'workflow_ref': workflow,
            'sha': sha, 'workflow_sha': sha, 'run_id': run, 'run_attempt': attempt,
            'event': event, 'job': job, 'family': family,
            **({'completion_group': selected['id'], 'full_original_row': False} if selected else {})}


def owned_name(context):
    # Full SHA avoids abbreviated-source collisions. No name is accepted by prefix.
    return ('TouchColor UIKit ' + context['family'] + ' ' + context['sha'] + ' ' +
            context['run_id'] + '-' + context['run_attempt'] +
            (' ' + context['completion_group'] if 'completion_group' in context else ''))


def _paths(family):
    require(family in PROFILES, 'Unknown canonical UIKit family')
    return (Path('build') / (family + '-simulator.json'),
            Path('build') / (family + '-managed-device.json'))


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_file(path, limit):
    """Bounded trusted-FD read of one closed build filename, without aliases."""
    require(path.parent == Path('build'), 'Unexpected ownership file parent')
    directory = os.open('build', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                0 < before.st_size <= limit, 'Unsafe or oversized ownership file')
        data = bytearray()
        while len(data) <= limit:
            part = os.read(descriptor, min(4096, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        after = os.fstat(descriptor)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        require(len(data) == before.st_size and all(getattr(before, key) == getattr(after, key)
                for key in fields), 'Ownership file changed during bounded read')
        return bytes(data)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _type_identifier(value):
    return (type(value) is str and re.fullmatch(
        r'com\.apple\.CoreSimulator\.SimDeviceType\.[A-Za-z0-9-]{1,100}', value))


def _json_inventory(raw):
    require(type(raw) is str and 0 < len(raw.encode('utf-8')) <= 1_000_000,
            'Missing or oversized simulator inventory')
    value = strict_json(raw)
    require(type(value) is dict, 'Invalid simulator inventory')
    return value


def _device_rows(value):
    devices = value.get('devices')
    require(type(devices) is dict and len(devices) <= 128, 'Invalid device runtime inventory')
    rows = []
    for runtime, entries in devices.items():
        require(type(runtime) is str and type(entries) is list and len(entries) <= 512,
                'Invalid device inventory rows')
        for device in entries:
            require(type(device) is dict and valid_uuid(device.get('udid')) and
                    type(device.get('name')) is str, 'Invalid canonical device identity')
            rows.append((runtime, device))
    require(len(rows) <= 4096, 'Device inventory entry bound')
    identifiers = [device['udid'] for _, device in rows]
    require(len(set(identifiers)) == len(identifiers), 'Ambiguous inventory UUID')
    return rows


def _owned_readback(value, identity, name, device_type, *, creation=False):
    rows = _device_rows(value)
    matches = [(runtime, device) for runtime, device in rows
               if device['udid'] == identity['udid'] or device['name'] == name]
    require(len(matches) == 1, 'Owned device readback is missing or ambiguous')
    runtime, device = matches[0]
    states = ('Shutdown',) if creation else ('Shutdown', 'Booted')
    require(runtime == identity['runtime'] and device['udid'] == identity['udid'] and
            device['name'] == name and device.get('deviceTypeIdentifier') == device_type and
            device.get('isAvailable') is True and device.get('state') in states,
            'Owned device configuration differs')
    return device['state']


def _no_existing_binding(family):
    require(all(not path.exists() and not path.is_symlink() for path in _paths(family)),
            'Managed device configuration cannot be retried or rebound')


def create_owned_device(warmup):
    """Create one fresh, exact Shutdown device; return the original identity schema.

    The durable receipt first records creation intent, then the returned UUID,
    then exact readback. A partial receipt cannot authorize continuation or retry.
    """
    family = warmup.family
    context = require_job(family)
    require(warmup.build == Path('build'), 'Unexpected UIKit build root')
    warmup.require_time()
    _no_existing_binding(family)
    raw = warmup.command(INVENTORY.copy(), 30)
    require(require_job(family) == context, 'Canonical job changed during inventory')
    inventory = _json_inventory(raw)
    require(type(inventory.get('runtimes')) is list and len(inventory['runtimes']) <= 128 and
            type(inventory.get('devicetypes')) is list and len(inventory['devicetypes']) <= 1024,
            'Missing installed runtime/type inventory')
    runtimes = [row for row in inventory['runtimes'] if type(row) is dict and
                row.get('identifier') == RUNTIME]
    types = [row for row in inventory['devicetypes'] if type(row) is dict and
             row.get('name') == PROFILES[family]]
    require(len(runtimes) == 1 and runtimes[0].get('isAvailable') is True and len(types) == 1,
            'Exact stable iOS 27 profile runtime/type required')
    device_type = types[0].get('identifier')
    require(_type_identifier(device_type), 'Invalid installed profile type identifier')
    require(sum(type(row) is dict and row.get('identifier') == device_type
                for row in inventory['devicetypes']) == 1, 'Ambiguous installed profile type identifier')
    rows = _device_rows(inventory)
    initial_ids = {device['udid'] for _, device in rows}
    name = owned_name(context)
    require(not any(device['name'] == name for _, device in rows), 'Existing owned name cannot be reused')
    identity_path, receipt_path = _paths(family)
    receipt = {'schema': 1, 'contract': CONTRACT, 'context': context,
               'profile_name': PROFILES[family], 'requested_name': name, 'runtime': RUNTIME,
               'device_type': device_type, 'initial_inventory_sha256': _digest(raw.encode()),
               'initial_device_count': len(initial_ids), 'status': 'creation_pending',
               'deployment_owner': 'xcodebuild', 'pretest_boot_completion': 'not_requested',
               'pretest_installed_bytes': 'not_observed'}
    warmup.require_time()
    _no_existing_binding(family)
    write_json(receipt_path, receipt, limit=RECEIPT_LIMIT)
    pending_bytes = _read_file(receipt_path, RECEIPT_LIMIT)
    device = warmup.command(['xcrun', 'simctl', 'create', name, device_type, RUNTIME], 60).strip()
    require(require_job(family) == context, 'Canonical job changed during creation')
    require(_read_file(receipt_path, RECEIPT_LIMIT) == pending_bytes, 'Creation receipt changed')
    require(not identity_path.exists() and not identity_path.is_symlink(), 'Owned identity appeared during creation')
    require(valid_uuid(device) and device not in initial_ids, 'Created UUID invalid or already existed')
    receipt.update(returned_uuid=device, absent_from_initial_inventory=True, status='readback_pending')
    write_json(receipt_path, receipt, limit=RECEIPT_LIMIT)
    pending_bytes = _read_file(receipt_path, RECEIPT_LIMIT)
    raw = warmup.command(READBACK.copy(), 30)
    require(require_job(family) == context, 'Canonical job changed during readback')
    require(_read_file(receipt_path, RECEIPT_LIMIT) == pending_bytes, 'Creation receipt changed')
    identity = {'family': family, 'udid': device, 'runtime': RUNTIME, 'started': time.time()}
    _owned_readback(_json_inventory(raw), identity, name, device_type, creation=True)
    warmup.require_time()
    require(not identity_path.exists() and not identity_path.is_symlink(), 'Owned identity appeared during creation')
    write_json(identity_path, identity, limit=8192)
    require(read_identity(family) == identity, 'Created identity persistence differs')
    identity_bytes = _read_file(identity_path, 8192)
    receipt.update(identity=identity, identity_sha256=_digest(identity_bytes),
                   status='configured_shutdown_device_only', readback_state='Shutdown',
                   readback_sha256=_digest(raw.encode()))
    write_json(receipt_path, receipt, limit=RECEIPT_LIMIT)
    require(read_binding(family)['identity'] == identity, 'Created ownership binding differs')
    warmup.require_time()
    return identity


def read_binding(family):
    """Host-only strict binding read; no simulator command, selection or write.

    Return identity, receipt, current context, and exact file SHA-256 values. A
    caller can retain and compare the complete result for byte-level immutability.
    This is configured destination evidence, never installed-byte or boot proof.
    """
    context = require_job(family)
    identity_path, receipt_path = _paths(family)
    identity_bytes = _read_file(identity_path, 8192)
    identity = read_identity(family)  # Preserve the original strict four-field reader.
    require(strict_json(identity_bytes) == identity, 'Owned identity changed during read')
    receipt_bytes = _read_file(receipt_path, RECEIPT_LIMIT)
    receipt = strict_json(receipt_bytes)
    fields = {'schema', 'contract', 'context', 'profile_name', 'requested_name', 'runtime',
              'device_type', 'initial_inventory_sha256', 'initial_device_count', 'status',
              'deployment_owner', 'pretest_boot_completion', 'pretest_installed_bytes',
              'returned_uuid', 'absent_from_initial_inventory', 'identity', 'identity_sha256',
              'readback_state', 'readback_sha256'}
    require(type(receipt) is dict and set(receipt) == fields, 'Invalid managed ownership receipt schema')
    require(type(receipt['schema']) is int and receipt['schema'] == 1 and receipt['contract'] == CONTRACT,
            'Unsupported managed ownership contract')
    require(receipt['context'] == context, 'Foreign source/workflow/run/attempt/family binding')
    require(receipt['profile_name'] == PROFILES[family] and receipt['requested_name'] == owned_name(context)
            and receipt['runtime'] == RUNTIME and _type_identifier(receipt['device_type']),
            'Invalid managed profile binding')
    require(receipt['status'] == 'configured_shutdown_device_only' and receipt['readback_state'] == 'Shutdown'
            and receipt['deployment_owner'] == 'xcodebuild' and receipt['pretest_boot_completion'] == 'not_requested'
            and receipt['pretest_installed_bytes'] == 'not_observed', 'Incomplete or overstated device configuration')
    require(receipt['absent_from_initial_inventory'] is True and receipt['returned_uuid'] == identity['udid']
            and validate_identity(receipt['identity'], family) == identity, 'Managed identity differs')
    require(type(receipt['initial_device_count']) is int and 0 <= receipt['initial_device_count'] <= 4096,
            'Invalid initial device count')
    for key in ('initial_inventory_sha256', 'readback_sha256', 'identity_sha256'):
        require(type(receipt[key]) is str and re.fullmatch('[0-9a-f]{64}', receipt[key]),
                'Invalid managed inventory/identity digest')
    require(receipt['identity_sha256'] == _digest(identity_bytes), 'Owned identity bytes changed')
    require(_read_file(identity_path, 8192) == identity_bytes and
            _read_file(receipt_path, RECEIPT_LIMIT) == receipt_bytes and require_job(family) == context,
            'Managed binding changed during read')
    return {'identity': identity, 'receipt': receipt, 'context': context,
            'identity_sha256': _digest(identity_bytes), 'receipt_sha256': _digest(receipt_bytes)}


def read_managed_device_state(family, command, require_time):
    """Return explicit current state after the unchanged strict ownership checks."""
    require_time()
    binding = read_binding(family)
    raw = command(READBACK.copy(), 30)
    state = _owned_readback(_json_inventory(raw), binding['identity'], binding['receipt']['requested_name'],
                            binding['receipt']['device_type'])
    require(read_binding(family) == binding, 'Managed binding changed during inventory')
    require_time()
    return {'binding': binding, 'state': state}


def read_managed_device(family, command, require_time):
    """Preserve the original binding-only reader; never select/rebind."""
    return read_managed_device_state(family, command, require_time)['binding']
