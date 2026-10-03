#!/usr/bin/env python3
"""Decode bounded screenshot envelopes, including BOM-prefixed GitHub log lines.

Always verify the producer's length and digest before creating an image file.
Legacy logs without metadata require an explicit flag and stay marked unverified.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

MAX_IMAGE_BYTES = 500 * 1024
MAX_IMAGES = 5


def decode_screenshots(log, allow_unverified_legacy=False):
    metadata = {}
    for match in re.finditer(r'SCREENSHOT_META:(\{[^\r\n]+\})', log):
        item = json.loads(match.group(1))
        if item['name'] in metadata:
            raise ValueError('Duplicate screenshot metadata')
        metadata[item['name']] = item
    envelopes = list(re.finditer(r'SCREENSHOT_BEGIN:([^\r\n]+)[\r\n]+([\s\S]*?)SCREENSHOT_END:\1', log))
    if len(envelopes) != len(re.findall(r'SCREENSHOT_BEGIN:', log)) or len(envelopes) > MAX_IMAGES:
        raise ValueError('Incomplete or excessive screenshot envelopes')
    results = []
    names = set()
    for envelope in envelopes:
        name, body = envelope.groups()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}', name) or name in names:
            raise ValueError('Unsafe or duplicate screenshot name')
        names.add(name)
        # Do not require the marker at line start: GitHub can insert a BOM before
        # an otherwise ordinary timestamp, including in the middle of an image.
        chunks = re.findall(r'SCREENSHOT_CHUNK:([A-Za-z0-9+/=]+)', body)
        if not chunks or any(len(chunk) > 4096 for chunk in chunks):
            raise ValueError('Invalid screenshot chunks')
        data = base64.b64decode(''.join(chunks), validate=True)
        if len(data) > MAX_IMAGE_BYTES or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise ValueError('Invalid or oversized JPEG envelope')
        digest = hashlib.sha256(data).hexdigest()
        producer = metadata.get(name)
        if producer is None:
            if not allow_unverified_legacy:
                raise ValueError('Producer byte count and SHA256 are required')
        elif producer.get('bytes') != len(data) or producer.get('sha256') != digest:
            raise ValueError('Screenshot integrity mismatch')
        results.append((dict(name=name, bytes=len(data), sha256=digest,
                             producer_integrity_verified=producer is not None), data))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--allow-unverified-legacy', action='store_true')
    args = parser.parse_args()
    decoded = decode_screenshots(args.log.read_text(encoding='utf-8'), args.allow_unverified_legacy)
    args.output.mkdir(parents=True, exist_ok=True)
    for metadata, data in decoded:
        path = args.output / (metadata['name'] + '.jpg')
        if path.exists() and path.read_bytes() != data:
            raise FileExistsError('Refusing to replace a different evidence image: ' + str(path))
        path.write_bytes(data)
        print(json.dumps(dict(metadata, path=str(path)), sort_keys=True))


if __name__ == '__main__':
    main()
