"""All native Vision UI cases, split by system-provider workload on fresh VMs."""
SUITES = {
    'canvas': [
        'testChinesePasteAndPrecisionControls',
        'testRealPastePrecisionZoomPaletteAndRelaunch',
        'testOfficialAccessibilityEmptyAndPastedCanvas',
        'testOfficialAccessibilityCorruptPasteRetainsPreviousSource',
    ],
    'files': [
        'testRealPhotosImport',
        'testNativeExportSaveAndReopenActualPNG',
        'testNativePaletteExportReopensActualChangedSelectionAndDuplicates',
        'testNativeFileAndPhotosCancelRepeatedly',
        'testRealFilesPickerSelectsExportedPNG',
    ],
}
