"""Exact test-only normalization of the sole allowed launch-input edit."""
from test_mac_store_source_helpers import restore_store_ui

ENGLISH_SETUP = '''        if name.contains("testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail") {
            app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        } else if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {'''
RESET_SETUP = '''        // Reset-only diagnostic: the selected English contact adds no locale overrides.
        if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {'''


CHINESE_SETUP = '        if name.contains("testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail") {\n            app.launchArguments += ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]\n        }'
CHINESE_PLAN_SETUP = '        // Chinese contact localization is supplied by the fixed Xcode test plan.'


def restore_chinese_setup(text):
    text=restore_store_ui(text)
    if CHINESE_PLAN_SETUP not in text:return text
    if text.count(CHINESE_PLAN_SETUP)!=1 or CHINESE_SETUP in text:raise ValueError("ambiguous Chinese source change")
    return text.replace(CHINESE_PLAN_SETUP,CHINESE_SETUP,1)


def restore_english_setup(text):
    text=restore_chinese_setup(text)
    if RESET_SETUP not in text:return text
    if text.count(RESET_SETUP)!=1 or ENGLISH_SETUP in text:raise ValueError('ambiguous reset-only source change')
    return text.replace(RESET_SETUP,ENGLISH_SETUP,1)
