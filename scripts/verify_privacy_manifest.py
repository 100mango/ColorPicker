"""Verify only the required reasons for actual local/user-selected file access."""
import plistlib
import sys
from pathlib import Path

manifest = plistlib.loads(Path(sys.argv[1]).read_bytes())
scope = sys.argv[2]
assert scope in ('none', 'container', 'selected')
expected = {'NSPrivacyAccessedAPICategoryUserDefaults': {'CA92.1'}}
if scope != 'none':
    expected['NSPrivacyAccessedAPICategoryFileTimestamp'] = {'C617.1'}
    if scope == 'selected': expected['NSPrivacyAccessedAPICategoryFileTimestamp'].add('3B52.1')
entries = manifest['NSPrivacyAccessedAPITypes']
actual = {entry['NSPrivacyAccessedAPIType']: set(entry['NSPrivacyAccessedAPITypeReasons']) for entry in entries}
assert len(actual) == len(entries) and actual == expected, (actual, expected)
assert manifest['NSPrivacyTracking'] is False
assert manifest['NSPrivacyCollectedDataTypes'] == [] and manifest['NSPrivacyTrackingDomains'] == []
print('Required API reasons verified:', scope)
