"""Pure selection/identity checks for disposable native Watch simulator pairs."""
import uuid


def verify_new_device(identifier, original_devices, created_devices):
    value = uuid.UUID(identifier)
    existing = {uuid.UUID(row['udid']) for rows in original_devices.values() for row in rows}
    existing.update(uuid.UUID(row['udid']) for row in created_devices)
    if value in existing: raise ValueError('simctl create returned an existing device; ownership is unconfirmed')
    return identifier


def phone_template(devices):
    candidates = [(runtime, value) for runtime, rows in devices.items() if runtime.endswith('iOS-27-0')
                  for value in rows if value.get('isAvailable') and value.get('name', '').startswith('iPhone')]
    if not candidates: raise ValueError('No installed available iOS27 phone profile for the owned Watch pair')
    # Prefer the compact profile already used in the qualified UIKit lane.
    candidates.sort(key=lambda item: (0 if 'SE (3rd generation)' in item[1]['name'] else 1, item[1]['name']))
    runtime, value = candidates[0]
    if not value.get('deviceTypeIdentifier'): raise ValueError('Phone template has no observed device type')
    return runtime, value


def device_inventory(devices):
    values = []
    for runtime, rows in devices.items():
        if not runtime.endswith(('iOS-27-0', 'watchOS-27-0')): continue
        for row in rows:
            values.append({'runtime': runtime, **{key: row.get(key) for key in ('name', 'udid', 'state', 'deviceTypeIdentifier', 'isAvailable')}})
    if len(values) > 64: raise ValueError('Unexpected simulator inventory size')
    return values


def verify_pair(value, pair_id, watch_id, phone_id, original_pairs=None):
    if original_pairs and pair_id in original_pairs:
        raise ValueError('simctl pair returned an existing pair; ownership is unconfirmed')
    pairs = value.get('pairs')
    if not isinstance(pairs, dict) or len(pairs) > 64: raise ValueError('Unexpected simctl pair inventory')
    pair = pairs.get(pair_id)
    if not isinstance(pair, dict): raise ValueError('Created pair missing from real simctl inventory')
    if pair.get('watch', {}).get('udid') != watch_id or pair.get('phone', {}).get('udid') != phone_id:
        raise ValueError('Created pair does not match both owned device UUIDs')
    return pair


def activate_owned_pair(value, pair_id, watch_id, phone_id, original_pairs, activate, read_pairs):
    """Avoid reactivating an already-active new pair, with exact identity readback."""
    def active(record):
        state = record.get('state')
        if state in ('(active, connected)', '(active, disconnected)'): return True
        if state in ('(inactive, connected)', '(inactive, disconnected)'): return False
        raise ValueError('Unrecognized owned pair activation state: '+str(state))
    before = verify_pair(value, pair_id, watch_id, phone_id, original_pairs)
    requested = not active(before)
    if requested: activate(pair_id)
    after = verify_pair(read_pairs(), pair_id, watch_id, phone_id, original_pairs)
    if not active(after): raise ValueError('Owned pair activation was not confirmed')
    return {'activation_requested': requested, 'record': after}
