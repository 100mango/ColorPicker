"""Exact inverse of the reviewed About navigation delta for historical source guards.

This does not qualify new navigation. Current-source regression tests exercise the
new routes separately, and native execution must be repeated for the new product.
Historical hashes and all original assertions remain unchanged.
"""
from pathlib import Path
import json

DELTAS = json.loads(Path(__file__).with_name('secondary_privacy_navigation_delta.json').read_text())

def before_secondary_privacy(path, source):
    if path not in DELTAS:
        return source
    for edit in reversed(DELTAS[path]):
        old, new = edit['before'], edit['after']
        if not new or source.count(new) != 1:
            raise ValueError('Exact About navigation delta missing or ambiguous: ' + path)
        source = source.replace(new, old, 1)
    return source
