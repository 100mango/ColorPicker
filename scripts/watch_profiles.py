"""Choose an observed, available watchOS profile; never manufacture a device ID."""
import re


def select_profile(devices, runtime_suffix, size):
    if size not in ('smallest', 'largest'):
        raise ValueError('Watch coverage must name smallest or largest')
    candidates = []
    for runtime, rows in devices.items():
        if not runtime.endswith(runtime_suffix):
            continue
        for device in rows:
            match = re.search(r'\((\d+)mm\)', device.get('name', ''))
            if device.get('isAvailable') and match:
                candidates.append((int(match.group(1)), runtime, device))
    if not candidates:
        raise ValueError('No available, measured Watch profile for ' + runtime_suffix)
    candidates.sort(key=lambda item: (item[0], item[2]['name'], item[2]['udid']))
    selected = candidates[0] if size == 'smallest' else candidates[-1]
    inventory = [{**device, 'runtime': runtime, 'millimeters': mm} for mm, runtime, device in candidates]
    return selected[1], selected[2], inventory
