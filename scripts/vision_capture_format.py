"""Read back the documented screenshot/video preference; never edit xctestrun."""
import hashlib
import json
from pathlib import Path
import plistlib
import time

from job_budget import enabled_budget


def verify_generated(directory, *, clock=time.monotonic):
    budget = enabled_budget()
    if budget is not None:
        budget.admit('Vision generated capture-format readback', 5, minimum=5, cleanup=0)
    start = clock()

    def require(value, message):
        if not value: raise ValueError(message)

    def deadline():
        require(clock() - start <= 5, 'Vision capture-format readback exceeded its finite bound')

    root = Path(directory)
    products = root/'Build/Products'
    require(root.is_dir() and not root.is_symlink() and products.is_dir() and not products.is_symlink(),
            'Missing or symlink Vision build products')
    candidates = []
    for index, path in enumerate(products.iterdir()):
        deadline(); require(index < 128, 'Too many generated product entries')
        if path.suffix == '.xctestrun': candidates.append(path)
    require(len(candidates) == 1, 'Expected one compiler-produced Vision xctestrun')
    source = candidates[0]
    require(not source.is_symlink() and source.is_file(), 'Unsafe generated xctestrun')
    before = source.stat()
    require(before.st_nlink == 1 and 0 < before.st_size <= 2_000_000, 'Invalid generated xctestrun size/link count')
    with source.open('rb') as stream: raw = stream.read(2_000_001)
    after = source.stat(); deadline()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
            'Generated xctestrun changed during readback')
    pending = [plistlib.loads(raw)]; visited = 0; targets = []
    while pending:
        deadline(); visited += 1; require(visited <= 4096, 'Generated configuration structure exceeds bound')
        value = pending.pop()
        if isinstance(value, dict):
            path = value.get('TestBundlePath')
            if isinstance(path, str) and Path(path).name == 'TouchColorVisionUITests.xctest': targets.append(value)
            pending.extend(value.values())
        elif isinstance(value, list): pending.extend(value)
    require(len(targets) == 1, 'Expected one exact generated Vision UI target')
    target = targets[0]
    # This first compiler readback is a bounded configuration probe, not a runtime claim.
    # Emit only known, nonsecret preference fields even if the compiler schema differs.
    observed = {key: target.get(key) if isinstance(target.get(key), (str, bool, type(None)))
                else '<unexpected type>' for key in
                ('IsUITestBundle', 'PreferredScreenCaptureFormat', 'SystemAttachmentLifetime')}
    observed = {key: value[:96] if isinstance(value, str) else value for key, value in observed.items()}
    print('VISION_CAPTURE_CONFIGURATION_PROBE', json.dumps(observed, sort_keys=True), flush=True)
    require(target.get('IsUITestBundle') is True, 'Generated target is not a UI test bundle')
    require(target.get('PreferredScreenCaptureFormat') == 'screenshots',
            'Compiler-produced Vision UI capture format is missing or not screenshots')
    lifetime = target.get('SystemAttachmentLifetime')
    require(lifetime in (None, 'deleteOnSuccess', 'keepAlways'), 'Automatic failure captures are disabled or unknown')
    product = target.get('UITargetAppPath')
    require(isinstance(product, str), 'Generated Vision app linkage is absent')
    actual = Path(product.replace('__TESTROOT__', str(products.resolve()))).resolve()
    expected = (products/'Debug-xrsimulator/TouchColor.app').resolve()
    require(actual == expected and actual.is_dir(), 'Generated UI configuration points to another app product')
    deadline()
    return {'file': source.name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'target': 'TouchColorVisionUITests', 'preferred_capture_format': 'screenshots',
            'system_attachment_lifetime': lifetime, 'app': str(expected),
            'scope': 'compiler-produced configuration readback; runtime media/resource behavior still requires verification'}


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2: raise SystemExit('Expected the exact Vision derived-data directory')
    print('VISION_CAPTURE_CONFIGURATION', json.dumps(verify_generated(sys.argv[1]), sort_keys=True))
