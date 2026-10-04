"""Full-resolution evidence encoding after XCTest, outside held UI checkpoints.

Only disposable, synthetic test screenshots are handled. Original app photos are
never passed here. Every retained transform records source/retained hashes and
identical dimensions; failed encoding leaves no partial replacement.
"""
import hashlib
import os
from pathlib import Path
import re
import uuid
from bounded_process import run_captured

MAX_SOURCE_BYTES = 5_000_000
MAX_RETAINED_BYTES = 450_000


def metadata(path, command_runner):
    result = command_runner(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(path)], text=True, timeout=5)
    if result.returncode: raise ValueError('Screenshot dimensions could not be decoded')
    width = re.search(r'pixelWidth:\s*(\d+)', result.stdout)
    height = re.search(r'pixelHeight:\s*(\d+)', result.stdout)
    if not width or not height: raise ValueError('Screenshot has no decoded dimensions')
    dimensions = [int(width[1]), int(height[1])]
    if min(dimensions) <= 0 or max(dimensions) > 16384: raise ValueError('Screenshot dimensions outside evidence policy')
    return dimensions


def digest(path):
    value = hashlib.sha256(); count = 0
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > MAX_SOURCE_BYTES: raise ValueError('Screenshot exceeds source evidence bound')
            value.update(chunk)
    return value.hexdigest(), count


def retain_image(path, command_runner=run_captured):
    path = Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('Screenshot must be a regular file')
    source_hash, source_bytes = digest(path)
    dimensions = metadata(path, command_runner)
    result = {'source_sha256': source_hash, 'source_bytes': source_bytes, 'dimensions': dimensions,
              'retained_sha256': source_hash, 'retained_bytes': source_bytes, 'encoding': 'original'}
    if source_bytes <= MAX_RETAINED_BYTES: return path, result
    destination = path.with_suffix('.jpeg')
    if destination != path and destination.exists(): raise ValueError('Evidence filename collision')
    temporary = destination.with_name(str(uuid.uuid4()).upper()+'.tmp.jpeg')
    try:
        for quality in (65, 45, 30):
            temporary.unlink(missing_ok=True)
            encoded = command_runner(['/usr/bin/sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', str(quality), str(path), '--out', str(temporary)], text=True, timeout=10)
            if encoded.returncode or not temporary.is_file(): raise ValueError('Full-resolution JPEG encoding failed')
            retained_hash, retained_bytes = digest(temporary)
            if retained_bytes > MAX_RETAINED_BYTES: continue
            if metadata(temporary, command_runner) != dimensions: raise ValueError('Evidence encoder changed image dimensions')
            os.replace(temporary, destination)
            if path != destination: path.unlink()
            result.update(retained_sha256=retained_hash, retained_bytes=retained_bytes,
                          encoding='sips JPEG', quality=quality)
            return destination, result
        raise ValueError('Full-resolution screenshot could not fit its evidence cap')
    finally:
        temporary.unlink(missing_ok=True)
