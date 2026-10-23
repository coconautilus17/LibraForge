import unittest
from pathlib import Path
from unittest.mock import patch
from app.tests.script_loader import load_script


ORGANIZER = load_script("organizer_v3_13", "organize-audiobooks-by-metadata-v3_13.py")


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
