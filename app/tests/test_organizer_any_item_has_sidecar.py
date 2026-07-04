import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class AnyItemHasSidecarTests(unittest.TestCase):
    def test_empty_items_returns_false(self):
        self.assertFalse(ORGANIZER.any_item_has_sidecar([]))

    def test_no_items_have_a_sidecar(self):
        items = [
            ORGANIZER.BookItem("folder", Path("/a"), [Path("/a/1.m4b")], Path("/a/1.m4b")),
            ORGANIZER.BookItem("loose_file", Path("/b/2.m4b"), [Path("/b/2.m4b")], Path("/b/2.m4b")),
        ]
        with patch.object(ORGANIZER, "metadata_from_sidecar", return_value=None):
            self.assertFalse(ORGANIZER.any_item_has_sidecar(items))

    def test_at_least_one_item_has_a_sidecar(self):
        items = [
            ORGANIZER.BookItem("folder", Path("/a"), [Path("/a/1.m4b")], Path("/a/1.m4b")),
            ORGANIZER.BookItem("loose_file", Path("/b/2.m4b"), [Path("/b/2.m4b")], Path("/b/2.m4b")),
        ]
        with patch.object(
            ORGANIZER,
            "metadata_from_sidecar",
            side_effect=[None, {"title": "Book Two"}],
        ):
            self.assertTrue(ORGANIZER.any_item_has_sidecar(items))


if __name__ == "__main__":
    unittest.main()
