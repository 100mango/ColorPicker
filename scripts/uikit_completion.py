"""Six closed original-iOS completion groups, never a full-profile receipt.

Historical 212 hosted and 36 retained UI points remain external per-case provenance.
This route executes 58 outstanding or helper-affected UI points plus a fresh two-case bootstrap
on each of six owned devices. It does not qualify a 54-case hosted target.
"""
import os
from palette_lifecycle_diagnostics import require

REF = 'refs/heads/codex/ios-original-completion'
WORKFLOW = '100mango/ColorPicker/.github/workflows/ios-completion.yml@' + REF
BOOTSTRAP = tuple('TouchColorTests/PhonePaletteImportTests/' + name for name in (
    'testActualAddColorsBarActionAppendsDuplicateSelectionAndDismisses',
    'testOriginalIOSImportIsPresentWithoutCompanion'))
PALETTE = (
    'testPalettePasteReviewAcceptAndRelaunch',
    'testInvalidPalettePastePreservesHistory',
    'testPaletteFileCancellationAndImportReturn',
    'testPaletteFileSelectionReviewAndRelaunch',
    'testLargestTextPaletteReviewAndImportHelp',
    'testLargestTextPaletteRotationReplacesSelection',
    'testFullScreenPaletteCancelRetainsPhotoAndKeyboardState',
    'testFullScreenPaletteAcceptRetainsPhotoAndKeyboardState')
CANVAS = (
    'testNativeCanvasPaletteSavePreviewPickerCancelAndRelaunch',
    'testKeyboardImportSamplingZoomSaveAndRotation',
    'testCancelPhotoLoadingRetainsTheCurrentCanvasAndPalette',
    'testLargestTextNativePaletteAndCanvasControls',
    'testLiveCanvasPickerCancellationAndSceneLifecycle',
    'testFullScreenPaletteFlowsResumeLiveUnavailableState',
    'testPrivacyCloseRetainsPhotoSelection',
    'testZNativeWindowResizePreservesSelectionAndPaletteReturn')
AUDITS = tuple('TouchColorUITests/TouchColorAccessibilityUITests/' + name for name in (
    'testAccessibilityEmptyPalette', 'testAccessibilityPaletteImportReview',
    'testAccessibilityPaletteImportHelp', 'testAccessibilitySampledPhoto',
    'testAccessibilitySavedPalette', 'testAccessibilityLiveCameraUnavailable',
    'testAccessibilityNativePolicyBodyAndActions'))

def group(identity, family, names, audits, images):
    cls = 'TouchColorIPadUITests' if family.startswith('iPad') else 'TouchColorUITests'
    return {'id': identity, 'family': family, 'bootstrap': BOOTSTRAP,
            'functional': tuple('TouchColorUITests/' + cls + '/' + n for n in names),
            'audits': audits, 'images': images}

PHONE_PALETTE = (PALETTE[0], PALETTE[1], PALETTE[3], PALETTE[4], PALETTE[5])

GROUPS = {
    'iphone-compact': group('iphone-compact', 'iPhoneCompact',
        PHONE_PALETTE, (AUDITS[1],), 2),
    'iphone-large': group('iphone-large', 'iPhoneLarge',
        PHONE_PALETTE, (AUDITS[1],), 2),
    'ipad-mini-palette': group('ipad-mini-palette', 'iPadMini', PALETTE, (), 1),
    'ipad-mini-canvas': group('ipad-mini-canvas', 'iPadMini', CANVAS, AUDITS, 1),
    'ipad-large-palette': group('ipad-large-palette', 'iPadLarge', PALETTE, (), 2),
    'ipad-large-canvas': group('ipad-large-canvas', 'iPadLarge', CANVAS, AUDITS, 2),
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
