#!/usr/bin/env python3
"""Portable original-design source guards. Does not claim native or visual acceptance."""
from pathlib import Path
import contextlib, hashlib, io, json, runpy

ROOT = Path(__file__).resolve().parents[1]
def require(condition, message):
    if not condition:
        raise RuntimeError(message)
def digest(value):
    return hashlib.sha256(value).hexdigest()
def method(source, signature):
    start = source.index(signature)
    end = source.find('\n- (', start + len(signature))
    return source[start:end if end >= 0 else source.index('\n@end', start)].strip()

def main():
    contract = json.loads((ROOT / 'scripts/fixtures/original-design-preservation.json').read_text())
    for key, expected in contract['protected_methods'].items():
        name, signature = key.split(':', 1)
        source = (ROOT / 'ColorPicker' / name).read_text()
        require(digest(method(source, signature).encode()) == expected, 'Changed protected method: ' + key)
    for category in ['original_pngs', 'unchanged_core_and_metadata']:
        for path, expected in contract[category].items():
            require(digest((ROOT / path).read_bytes()) == expected, 'Changed ' + category + ': ' + path)
    for path in (ROOT / 'ColorPicker/Images.xcassets/OriginalDesign').rglob('Contents.json'):
        for item in json.loads(path.read_text())['images']:
            if item.get('filename'):
                require((path.parent / item['filename']).is_file(), 'Missing original artwork in ' + str(path))
    observed = {p: p.read_bytes() for p in (ROOT / 'TouchColor.xcodeproj').rglob('*') if p.is_file()}
    with contextlib.redirect_stdout(io.StringIO()):
        scope = runpy.run_path(str(ROOT / 'scripts/generate_project.py'))
    require(all(p.read_bytes() == value for p, value in observed.items()), 'Project/scheme/workspace regeneration changed tracked inputs')
    objects = scope['objects']
    targets = {value['name']: value for value in objects.values() if value['isa'] == 'PBXNativeTarget'}
    def members(name):
        phases = [objects[p] for p in targets[name]['buildPhases']]
        builds = next(p['files'] for p in phases if p['isa'] == 'PBXSourcesBuildPhase')
        return [objects[objects[b]['fileRef']]['path'] for b in builds]
    require(members('TouchColor').count('ColorPicker/TCOriginalDesign.m') == 1, 'Original presentation source must join app exactly once')
    require(members('TouchColorUITests').count('TouchColorUITests/TouchColorOriginalDesignUITests.m') == 1, 'Original-design UI regression source missing or duplicated')
    require(members('TouchColorTests').count('ColorPickerTests/TCPhotoImportLifecycleTests.m') == 1, 'Photo import lifecycle regression source missing or duplicated')
    for name in targets:
        sources = members(name)
        require(len(sources) == len(set(sources)), 'Duplicate source member in ' + name)
        require(all((ROOT / p).is_file() for p in sources), 'Missing source member in ' + name)
    for value in objects.values():
        if value['isa'] == 'PBXFileReference' and value.get('sourceTree') == '<group>':
            require((ROOT / value['path']).exists(), 'Missing project reference: ' + value['path'])
    def configurations(value):
        return [objects[p]['buildSettings'] for p in objects[value['buildConfigurationList']]['buildConfigurations']]
    project_settings = configurations(objects[scope['projectid']])
    require(all(s.get('IPHONEOS_DEPLOYMENT_TARGET') == '15.0' for s in project_settings), 'Project must keep iOS 15')
    require(all(s.get('IPHONEOS_DEPLOYMENT_TARGET', '15.0') == '15.0' for s in configurations(targets['TouchColor'])), 'App must keep iOS 15')
    for name in ['TouchColorTests', 'TouchColorUITests']:
        require(all(s.get('IPHONEOS_DEPLOYMENT_TARGET') == '17.0' for s in configurations(targets[name])), name + ' must keep iOS 17 test floor')
    main = (ROOT / 'ColorPicker/ColorMainViewController.m').read_text()
    require('UITableViewStyleInsetGrouped' not in main and 'tintedButtonConfiguration' not in main, 'Redesigned primary home controls reintroduced')
    require('original.library' in main and 'original.about' in main, 'Original home/library route missing')
    require('palette.import.open' in main and 'photo.import.cancel' in main, 'Import/recovery controls missing')
    print(json.dumps({'status': 'source-only-pass', 'protected_methods': len(contract['protected_methods']),
                      'original_pngs': len(contract['original_pngs']), 'unchanged_core_and_metadata_files': len(contract['unchanged_core_and_metadata']),
                      'native_compile': 'not-run', 'visual_acceptance': 'not-run'}, indent=2))

if __name__ == '__main__':
    main()
