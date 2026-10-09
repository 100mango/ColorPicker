"""Portable source contracts only. Apple compilation and navigation remain native gates."""
from pathlib import Path
import hashlib
import json
import re
import unittest
from secondary_privacy_navigation_contract import before_secondary_privacy, DELTAS

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads(Path(__file__).with_name('secondary_privacy_navigation_baseline.json').read_text())
def source(path): return (ROOT / path).read_text()


class SecondaryPrivacyNavigationTests(unittest.TestCase):
    def test_exact_reviewed_delta_preserves_all_other_changed_file_bytes(self):
        for path, expected in BASELINE.items():
            with self.subTest(path=path):
                restored = before_secondary_privacy(path, source(path))
                self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), expected)

    def test_inverse_rejects_missing_or_duplicate_new_navigation_hunks(self):
        for path, changes in DELTAS.items():
            current = source(path)
            new = changes[-1]['after']
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    before_secondary_privacy(path, current.replace(new, '', 1))
                with self.assertRaises(ValueError):
                    before_secondary_privacy(path, current + new)

    def test_mac_secondary_menu_and_settings_leave_the_workspace_toolbar_unchanged(self):
        window = source('TouchColorMac/ColorWindow.swift')
        toolbar = window.split('        .toolbar {', 1)[1].split('        .focusedSceneValue', 1)[0]
        for action in ('image.open', 'image.photos', 'image.paste', 'image.export', 'camera.open'):
            self.assertIn(action, toolbar)
        self.assertNotIn('privacy.open', toolbar)
        self.assertNotIn('about.open', toolbar)
        self.assertIn('showingAbout || showingCamera || session.errorMessage != nil', window)
        self.assertIn('.focusedSceneValue(\\.showAbout, ownsModalPresentation ? nil : { showingAbout = true })', window)
        app = source('TouchColorMac/TouchColorMacApp.swift')
        self.assertIn('CommandGroup(replacing: .appInfo)', app)
        self.assertIn('Settings { MacAboutView(showsClose: false) }', app)
        self.assertIn('.disabled(showAbout == nil)', app)

    def test_mac_about_action_is_unavailable_while_any_workspace_modal_owns_presentation(self):
        window = source('TouchColorMac/ColorWindow.swift')
        app = source('TouchColorMac/TouchColorMacApp.swift')
        self.assertEqual(window.count('.focusedSceneValue(\\.showAbout,'), 1)
        self.assertIn('private var ownsModalPresentation: Bool { showingAbout || showingCamera || session.errorMessage != nil }', window)
        self.assertIn('.focusedSceneValue(\\.showAbout, ownsModalPresentation ? nil : { showingAbout = true })', window)
        self.assertNotIn('.focusedSceneValue(\\.showAbout, { showingAbout = true })', window)
        menu = app.split('CommandGroup(replacing: .appInfo)', 1)[1].split('CommandGroup(after: .newItem)', 1)[0]
        self.assertIn('Button("About TouchColor") { showAbout?() }', menu)
        self.assertIn('.disabled(showAbout == nil)', menu)

    def test_vision_about_is_palette_footer_not_primary_toolbar(self):
        window = source('TouchColorVision/VisionColorWindow.swift')
        palette, details = window.split('        } detail: {', 1)
        self.assertIn('.safeAreaInset(edge: .bottom)', palette)
        self.assertIn('Button("About") { about = true }', palette)
        toolbar = details.split('                .toolbar {', 1)[1].split('        .fileImporter', 1)[0]
        self.assertNotIn('Privacy', toolbar)
        self.assertNotIn('About', toolbar)
        for action in ('image.open', 'image.photos', 'image.paste', 'image.export'):
            self.assertIn(action, toolbar)

    def test_tv_about_is_after_palette_list_with_existing_focus_sections(self):
        window = source('TouchColorTV/TVColorWindow.swift')
        palette, actions = window.split('                }.frame(width: 270).focusSection()', 1)
        self.assertIn('Button("About")', palette)
        self.assertGreater(palette.index('Button("About")'), palette.index('ForEach('))
        top = actions.split('                    if let raster', 1)[0]
        self.assertIn('Button("Photos")', top)
        self.assertIn('Button("Create Color")', top)
        self.assertNotIn('Privacy', top)
        self.assertNotIn('About', top)
        self.assertIn('.frame(maxHeight: .infinity).focusSection()', actions)
        about = window.split('private struct TVAboutView', 1)[1].split('struct TVSamplingCanvas', 1)[0]
        self.assertIn('.onExitCommand { dismiss() }', about)
        self.assertIn('.sheet(isPresented: $showingPrivacy) { PrivacyView() }', about)

    def test_watch_replaces_only_trailing_home_row_and_keeps_native_back_navigation(self):
        window = source('TouchColorWatch/WatchViews.swift')
        home = window.split('struct WatchSwatch:', 1)[0]
        self.assertIn('NavigationLink("About") { WatchAbout() }', home)
        self.assertNotIn('WatchPrivacy()', home)
        self.assertNotIn('watch.privacy', home)
        about = window.split('private struct WatchAbout:', 1)[1].split('struct WatchPrivacy:', 1)[0]
        self.assertIn('NavigationLink("Privacy") { WatchPrivacy() }', about)
        self.assertIn('.navigationTitle("About")', about)
        native = source('TouchColorWatchUITests/WatchWorkflowTests.swift')
        cold = native.split('func testHomeListDigitalCrownFromColdLaunch()', 1)[1].split('    /// A fresh bounded snapshot', 1)[0]
        self.assertIn('let target = app.buttons["watch.about"]', cold)
        self.assertIn('XCTAssertFalse(target.exists && target.isHittable', cold)
        self.assertIn('for attempt in 0..<12', cold)
        self.assertIn('rotateDigitalCrown(delta: -0.1)', cold)
        self.assertIn('XCTAssertTrue(target.isHittable', cold)
        self.assertIn('app.navigationBars["Privacy"].waitForExistence', cold)
        self.assertIn('app.navigationBars["TouchColor"].waitForExistence', cold)
        self.assertNotIn('swipe', cold)
        self.assertNotIn('app.buttons["watch.editor"].tap()', cold)

    def test_approved_shared_policy_is_unchanged_and_watch_policy_stays_exact(self):
        original = before_secondary_privacy('TouchColorWatch/WatchViews.swift', source('TouchColorWatch/WatchViews.swift'))
        policy = source('TouchColorWatch/WatchViews.swift').split('struct WatchPrivacy:', 1)[1].split('private struct WatchSavedColor:', 1)[0]
        self.assertEqual(policy, original.split('struct WatchPrivacy:', 1)[1].split('private struct WatchSavedColor:', 1)[0])
        for path in ('TouchColorMac/PrivacyView.swift', 'TouchColorTV/PrivacyView.swift'):
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), BASELINE[path])

    def test_native_cases_check_secondary_open_back_reopen_and_preserved_state(self):
        mac = source('TouchColorMacUITests/TouchColorMacUITests.swift')
        self.assertEqual(mac.count('        openAboutFromAppMenu()'), 5)
        self.assertEqual(mac.count('        closeAboutAndRestoreWorkspace()'), 4)
        self.assertIn('app.menuItems["about.open"]', mac)
        tv = source('TouchColorTVUITests/TVWorkflowTests.swift')
        route = tv.split('private func assertSecondaryPrivacyAndRemoteReturn(context: String)', 1)[1].split('func testRemoteColorEditorAndMenuReturn()', 1)[0]
        self.assertEqual(route.count('remote.press(.menu)'), 2)
        self.assertIn('select(app.buttons["privacy.close"])', route)
        self.assertIn('select(app.buttons["about.close"])', route)
        vision = source('TouchColorVisionUITests/VisionWorkflowTests.swift')
        route = vision.split('func testRealPastePrecisionZoomPaletteAndRelaunch()', 1)[1].split('func testNativeExport', 1)[0]
        self.assertIn('for _ in 0..<2', route)
        self.assertIn('XCTAssertFalse(app.buttons["privacy.open"].exists)', route)
        self.assertIn('hex("#ff00ff")', route)

    def test_about_labels_are_localized_without_duplicates(self):
        for platform in ('Mac', 'TV', 'Vision', 'Watch'):
            for locale in ('en', 'zh-Hans'):
                catalog = source(f'TouchColor{platform}/{locale}.lproj/Localizable.strings')
                entries = re.findall(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', catalog, re.M)
                self.assertEqual(len(entries), len(dict(entries)))
                self.assertEqual(dict(entries)['About'], 'About' if locale == 'en' else '关于')
                if platform != 'Watch':
                    self.assertEqual(dict(entries)['About TouchColor'], 'About TouchColor' if locale == 'en' else '关于 TouchColor')


if __name__ == '__main__': unittest.main()
