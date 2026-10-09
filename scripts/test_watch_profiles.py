import unittest
from watch_profiles import select_profile


class ProfileTests(unittest.TestCase):
    def test_actual_available_runtime_endpoints_only(self):
        def device(name, available=True):
            return {'name': name, 'udid': name, 'isAvailable': available}
        devices = {'com.apple.CoreSimulator.SimRuntime.watchOS-27-0': [
            device('Apple Watch Series 12 (46mm)'), device('Apple Watch SE 3 (40mm)'),
            device('Apple Watch Ultra 4 (49mm)'), device('Unavailable (38mm)', False)],
            'watchOS-26-0': [device('Older runtime (38mm)')]}
        self.assertEqual(select_profile(devices, 'watchOS-27-0', 'smallest')[1]['name'], 'Apple Watch SE 3 (40mm)')
        self.assertEqual(select_profile(devices, 'watchOS-27-0', 'largest')[1]['name'], 'Apple Watch Ultra 4 (49mm)')
        self.assertEqual(len(select_profile(devices, 'watchOS-27-0', 'largest')[2]), 3)

    def test_missing_profile_or_runtime_is_an_explicit_failure(self):
        with self.assertRaises(ValueError):
            select_profile({}, 'watchOS-27-0', 'smallest')
        with self.assertRaises(ValueError):
            select_profile({}, 'watchOS-27-0', 'unknown')


def load_tests(loader, tests, pattern):
    # Keep the new diagnostics checks on the existing source-owned Watch
    # preflight entrypoint without changing any workflow timeout/budget rows.
    from test_watch_diagnostics import WatchDiagnosticsTests
    tests.addTests(loader.loadTestsFromTestCase(WatchDiagnosticsTests))
    from test_watch_touch_drag import WatchTouchDragTests
    tests.addTests(loader.loadTestsFromTestCase(WatchTouchDragTests))
    from test_secondary_privacy_navigation import SecondaryPrivacyNavigationTests
    tests.addTests(loader.loadTestsFromTestCase(SecondaryPrivacyNavigationTests))
    return tests


if __name__ == '__main__':
    unittest.main()
