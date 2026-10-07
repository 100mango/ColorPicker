"""Closed Photos-only completion scope with explicit historical hosted evidence.

No historical test is represented as executed in the current job. Input hashes
cover the generated project/generator, complete app/shared sources/resources,
all hosted tests and the local package. Unknown/mutated inputs reject reuse.
"""
import hashlib
import json
from pathlib import Path

SCOPE = 'photos-only'
ENV = 'TOUCHCOLOR_VISION_COMPLETION_SCOPE'
REFERENCE_SHA256 = 'fb6b640c8d60a5daf1b10c51fe0a00ff7f7e4562466a68daae26b81e6a8515e2'
REFERENCE_NAME = 'scripts/vision_photos_hosted_reference.json'


def reference(root=None):
    root=Path(root).resolve(strict=True) if root is not None else Path(__file__).resolve().parents[1]
    path=root/REFERENCE_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size>100000:
        raise ValueError('Missing or unsafe hosted reference')
    with path.open('rb') as stream:raw=stream.read(100001)
    if len(raw)>100000:raise ValueError('Hosted reference grew beyond its bound')
    if hashlib.sha256(raw).hexdigest()!=REFERENCE_SHA256:raise ValueError('Hosted reference changed')
    return json.loads(raw)


def verify_reuse(root=None):
    root=Path(root).resolve(strict=True) if root is not None else Path(__file__).resolve().parents[1]
    value=reference(root);observed=set(value['source_files'])
    for name in value['source_roots']:
        folder=root/name
        if folder.is_symlink() or not folder.is_dir():raise ValueError('Unsafe hosted source root')
        for path in folder.rglob('*'):
            if path.is_symlink():raise ValueError('Symlink hosted source')
            if path.is_file():observed.add(path.relative_to(root).as_posix())
    if observed!={item['path'] for item in value['inputs']}:raise ValueError('Hosted source inventory changed')
    for item in value['inputs']:
        path=root/item['path']
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=item['bytes']:
            raise ValueError('Hosted source size/type changed: '+item['path'])
        with path.open('rb') as stream:raw=stream.read(item['bytes']+1)
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ValueError('Hosted source bytes changed: '+item['path'])
    return {'schema':1,'executed_this_job':False,'source_inputs_verified':True,
            'reference_manifest_sha256':REFERENCE_SHA256,
            'reference':{key:value[key] for key in ('source_sha','run','job','artifact','artifact_sha256',
                          'hosted_summary_sha256','runtime_sha256','hosted_count','hosted_qualified')}}


def validate_reuse_report(report):
    if report.get('hosted_reuse')!=verify_reuse():raise ValueError('Missing or changed historical hosted reuse proof')
    if report.get('vision_hosted_result') or report.get('xctest_summary'):
        raise ValueError('Photos completion cannot claim a current hosted result')
    for stage in report.get('stages',[]):
        if '-only-testing:TouchColorVisionTests' in stage.get('command',[]):
            raise ValueError('Photos completion unexpectedly executed hosted tests')


if __name__ == '__main__':
    print(json.dumps(verify_reuse(), sort_keys=True))
