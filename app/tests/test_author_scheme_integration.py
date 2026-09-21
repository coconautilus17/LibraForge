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


if __name__ == "__main__":
    unittest.main()
