"""Every real Vision UI case owns one fresh, serial standard VM.

Budgets include result summaries, resource records, manifests and full-size
compressed screenshots. The complete Vision allocation stays at eight MB.
"""
CASES = {
    'chinese': ('testChinesePasteAndPrecisionControls', 950_000),
    'corrupt-audit': ('testOfficialAccessibilityCorruptPasteRetainsPreviousSource', 650_000),
    'canvas-audit': ('testOfficialAccessibilityEmptyAndPastedCanvas', 650_000),
    'paste-relaunch': ('testRealPastePrecisionZoomPaletteAndRelaunch', 1_300_000),
    'png-export': ('testNativeExportSaveAndReopenActualPNG', 900_000),
    'json-export': ('testNativePaletteExportReopensActualChangedSelectionAndDuplicates', 900_000),
    'photos': ('testRealPhotosImport', 950_000),
    'cancel': ('testNativeFileAndPhotosCancelRepeatedly', 750_000),
    'files-select': ('testRealFilesPickerSelectsExportedPNG', 950_000),
}


def needs_photo_seed(platform, case=None):
    """Only actual library selection needs a populated synthetic library.

    Paste, Files export/reopen, audits and picker cancellation remain independent
    of addmedia. Their real app assertions still execute in their exact case row.
    """
    if platform == 'vision':
        if case not in CASES: raise ValueError('Unknown isolated Vision case')
        return case == 'photos'
    return platform == 'tv'
