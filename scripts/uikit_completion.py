"""Three closed original-iOS groups execute five remaining functional cases.

Prior results retain their original source/run/attempt/device provenance: 212
hosted, four distinct Add Colors hosted profile points, 36 earlier UI points and
53 of the 58 selected UI points. This route runs only the five remaining UI cases
plus two existing nonmodal bootstrap cases on each of three fresh owned devices.
It does not qualify a full hosted target or migrate retained results to this source.
The completed Large iPad and all audit selections are retired from this route.
"""
import os
from palette_lifecycle_diagnostics import require

REF = 'refs/heads/ios-original-completion'
WORKFLOW = '100mango/ColorPicker/.github/workflows/ios-completion.yml@' + REF
BOOTSTRAP = tuple('TouchColorTests/PhonePaletteImportTests/' + name for name in (
    'testOriginalIOSImportIsPresentWithoutCompanion',
    'testCancelledFileSelectionAndUnsupportedPasteRejectLatePriorRead'))
def group(identity, family, names, audits, images, photos):
    cls = 'TouchColorIPadUITests' if family.startswith('iPad') else 'TouchColorUITests'
    return {'id': identity, 'family': family, 'bootstrap': BOOTSTRAP,
            'functional': tuple('TouchColorUITests/' + cls + '/' + n for n in names),
            'audits': audits, 'images': images,
            'resources': {'files': False, 'photos': photos}}

GROUPS = {
    'iphone-compact': group('iphone-compact', 'iPhoneCompact',
        ('testInvalidPalettePastePreservesHistory',), (), 2, False),
    'iphone-large': group('iphone-large', 'iPhoneLarge',
        ('testInvalidPalettePastePreservesHistory',
         'testLargestTextPaletteReviewAndImportHelp',
         'testPalettePasteReviewAcceptAndRelaunch'), (), 2, False),
    'ipad-mini': group('ipad-mini', 'iPadMini',
        ('testPaletteFileCancellationAndImportReturn',), (), 2, False),
}

def completion_group(family):
    """Closed internal environment hook; no caller-supplied case selectors."""
    value = os.environ.get('TC_COMPLETION_GROUP')
    if value is None:
        return None
    require(value in GROUPS, 'Unknown or absent completion group')
    selected = GROUPS[value]
    require(selected['family'] == family, 'Completion group belongs to another family')
    return selected


def selection(family, suite):
    selected = completion_group(family)
    if selected is None:
        return None
    require(suite in ('TouchColorTests', 'TouchColorUITests', 'AccessibilityAudits'),
            'Unknown completion suite')
    cases = selected[{'TouchColorTests': 'bootstrap', 'TouchColorUITests': 'functional',
                      'AccessibilityAudits': 'audits'}[suite]]
    require(cases, 'This completion group has no such suite')
    return {'group': selected['id'], 'suite': suite, 'cases': list(cases),
            'kind': 'selected_bootstrap' if suite == 'TouchColorTests' else 'selected_completion',
            'full_target': False, 'full_original_row': False}


def resource_selection(family):
    """Reconstruct dependencies only for these three closed selections.

    Files cancellation never selects PaletteFixtures JSON. The remaining phone
    cases use Paste and the in-app image; the remaining iPad cancellation case
    does not import a photo. Full targets keep their original Files and Photos
    preparation outside this selected receipt branch.
    """
    selected = completion_group(family)
    if selected is None:
        return None
    return {'group': selected['id'],
            'bootstrap': list(selected['bootstrap']),
            'functional': list(selected['functional']),
            'audits': list(selected['audits']),
            'required': dict(selected['resources'])}
