import unittest
from pathlib import Path

STATIC = Path(__file__).parents[1] / "static"


class ScanRootSettingTests(unittest.TestCase):
    def test_settings_library_section_has_the_field_and_the_default_subtext(self):
        html = (STATIC / "settings.html").read_text(encoding="utf-8")
        library = html[html.index('id="library"'):html.index('id="reports"')]
        self.assertIn('id="organizerScanRoot"', library)
        self.assertIn('id="organizerScanRootDefault"', library)

    def test_the_hard_coded_default_lives_in_one_place_and_is_shown(self):
        prefs = (STATIC / "ui-preferences.js").read_text(encoding="utf-8")
        self.assertEqual(prefs.count('"/audiobooks/_unorganized"'), 1)
        self.assertIn("organizerScanRoot: \"\"", prefs)
        self.assertIn("organizerScanRootDefault", prefs)

    def test_folder_forge_prefills_the_saved_scan_root(self):
        js = (STATIC / "organizer.js").read_text(encoding="utf-8")
        self.assertIn("organizerScanRoot", js)


if __name__ == "__main__":
    unittest.main()
