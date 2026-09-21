import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    sys.modules["audible"] = stub


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ORGANIZER = load_module("organizer_author_scheme", "scripts/organize-audiobooks-by-metadata-v3_13.py")
FIXER = load_module("fixer_author_scheme", "scripts/audible-metadata-fixer-v5.py")


class SchemeHooksTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("LIBRAFORGE_AUTHOR_SCHEME")

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("LIBRAFORGE_AUTHOR_SCHEME", None)
        else:
            os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = self.saved

    def test_default_behaviour_is_unchanged(self):
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "legacy"
        self.assertEqual(ORGANIZER.canonical_author_name("JK Rowling"), "JK Rowling")
        self.assertEqual(ORGANIZER.canonical_author_name("V A Lewis"), "V.A. Lewis")
        self.assertEqual(FIXER.canonicalize_author_credits("A. F. Kay, TJ Klune"), "A. F. Kay, TJ Klune")

    def test_universal_scheme_applies_to_folders_and_fixer_output(self):
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "universal"
        self.assertEqual(ORGANIZER.canonical_author_name("JK Rowling"), "J.K. Rowling")
        self.assertEqual(FIXER.canonicalize_author_credits("A. F. Kay, TJ Klune"), "A.F. Kay, T.J. Klune")
        self.assertEqual(FIXER.canonicalize_author_credits("Mashton X X, Mashton X Y"), "Mashton XX, Mashton XY")

    def test_folder_name_parsers_keep_raw_text_in_both_modes(self):
        for mode in ("legacy", "universal"):
            os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = mode
            parsed = ORGANIZER.parse_explicit_identity_folder_name("Extra26, T C Liyanage - Magus Reborn 01")
            self.assertEqual(parsed.get("author"), "T C Liyanage", mode)

    def test_noncanonical_folders_are_listed_in_universal_mode(self):
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "universal"
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("A. F. Kay", "A.F. Wells", "_unorganized", "Brian McClellan"):
                (Path(tmp) / name).mkdir()
            self.assertEqual(ORGANIZER.noncanonical_author_folders(Path(tmp)), ["A. F. Kay"])

    def report_item(self, current_author, written_author):
        result = FIXER.ItemResult(index=1, file_path=Path("/x/a.m4b"), display_path=Path("a.m4b"))
        result.status = "matched"
        result.clues = {"current": {"author": current_author}}
        result.metadata = {"author": written_author}
        return FIXER._build_report_item(result)

    def test_report_flags_books_whose_initials_the_scheme_unified(self):
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "universal"
        self.assertTrue(self.report_item("V A Lewis", "V.A. Lewis").get("author_initials_fixed"))
        self.assertTrue(self.report_item("JK Rowling, TJ Klune", "J.K. Rowling, T.J. Klune").get("author_initials_fixed"))

    def test_report_does_not_flag_unchanged_or_different_authors_or_the_old_mode(self):
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "universal"
        self.assertNotIn("author_initials_fixed", self.report_item("V.A. Lewis", "V.A. Lewis"))
        self.assertNotIn("author_initials_fixed", self.report_item("V A Lewis", "Brian McClellan"))
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "legacy"
        self.assertNotIn("author_initials_fixed", self.report_item("V A Lewis", "V.A. Lewis"))


class SharedScriptSetupTests(unittest.TestCase):
    def test_ui_preferences_still_creates_the_preferences_every_page_needs(self):
        js = (ROOT / "app" / "static" / "ui-preferences.js").read_text(encoding="utf-8")
        self.assertIn("let preferences = readPreferences();", js)
        self.assertIn("window.LibraForgePrefs = { get: () => preferences };", js)


class ReportUiWiringTests(unittest.TestCase):
    def test_match_report_has_the_filter_badge_and_stat(self):
        static = ROOT / "app" / "static"
        html = (static / "index.html").read_text(encoding="utf-8")
        js = (static / "app.js").read_text(encoding="utf-8")
        css = (static / "style.css").read_text(encoding="utf-8")
        self.assertIn('<option value="initials_fixed">Author Initials Fixed</option>', html)
        self.assertIn("statusFilter === 'initials_fixed' && !item.author_initials_fixed", js)
        self.assertIn('class="match-initials-badge"', js)
        self.assertIn("stat('Author initials fixed'", js)
        self.assertIn(".match-initials-badge", css)


if __name__ == "__main__":
    unittest.main()
