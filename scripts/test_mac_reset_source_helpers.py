"""Exact test-only normalization of the sole allowed launch-input edit."""
ENGLISH_SETUP = '''        if name.contains("testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail") {
            app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        } else if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {'''
RESET_SETUP = '''        // Reset-only diagnostic: the selected English contact adds no locale overrides.
        if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {'''


def restore_english_setup(text):
    if RESET_SETUP not in text:return text
    if text.count(RESET_SETUP)!=1 or ENGLISH_SETUP in text:raise ValueError('ambiguous reset-only source change')
    return text.replace(RESET_SETUP,ENGLISH_SETUP,1)
