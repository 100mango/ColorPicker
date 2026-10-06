"""Four closed original-iOS remaining-failure groups, never a full-profile receipt.

Historical 212 hosted and 36 UI points, plus 48 selected UI passes and four distinct
new hosted profile points from 2d65c7321990eae57b7c9b661a1d5d1180dffc03,
run 37501950379 attempt 1, remain external per-case provenance. This route executes
nine functional failures and one audit failure, plus a fresh two-case bootstrap on
each of four owned devices. It does not qualify a 54-case hosted target or migrate
any retained result to this source. The former split iPad identities are retired.
"""
import os
from palette_lifecycle_diagnostics import require

REF = 'refs/heads/codex/ios-original-completion'
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
        ('testInvalidPalettePastePreservesHistory',
         'testPalettePasteReviewAcceptAndRelaunch'), (), 2, False),
    'iphone-large': group('iphone-large', 'iPhoneLarge',
        ('testInvalidPalettePastePreservesHistory',
         'testLargestTextPaletteReviewAndImportHelp',
         'testPalettePasteReviewAcceptAndRelaunch'), (), 2, False),
    'ipad-mini': group('ipad-mini', 'iPadMini',
        ('testPaletteFileCancellationAndImportReturn',
         'testPrivacyCloseRetainsPhotoSelection'),
        ('TouchColorUITests/TouchColorAccessibilityUITests/testAccessibilityLiveCameraUnavailable',), 2, True),
    'ipad-large': group('ipad-large', 'iPadLarge',
        ('testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState',
         'testPalettePasteReviewAcceptAndRelaunch',
         'testLiveCanvasPickerCancellationAndSceneLifecycle'), (), 4, True),
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
    """Reconstruct preparation dependencies only for the four closed selections.

    Files cancellation never selects PaletteFixtures JSON. Phone cases use Paste
    and the in-app image; both iPad groups call importFixture, including after
    cancellation/Home in the Large live-canvas case. Full targets use their
    existing Files and Photos preparation, outside this selected receipt branch.
    """
    selected = completion_group(family)
    if selected is None:
        return None
    return {'group': selected['id'],
            'bootstrap': list(selected['bootstrap']),
            'functional': list(selected['functional']),
            'audits': list(selected['audits']),
            'required': dict(selected['resources'])}
