"""A match from a different recording of the same book keeps the book's own
narrator, and says so.

Tunnels 05 Spiral: the files are the Recorded Books edition read by Steven
Crossley (728 min, credited "Roderick Gordon/Brian Williams/Steven Crossley");
Audible US only sells the Audible Studios edition read by Paul Chequer
(682 min). A full match would have written Paul Chequer as the narrator.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

from app.fixer.parsing import split_credit_names
from app.fixer.scoring import metadata_from_product

SPIRAL = {
    "asin": "B006QM9TO4", "title": "Spiral", "authors": [{"name": "Roderick Gordon"}],  # co-author Brian Williams unlisted
    "narrators": [{"name": "Paul Chequer"}], "series": [{"title": "Tunnels", "sequence": "5"}],
    "runtime_length_min": 682,
}
SPIRAL_CLUES = {
    "title": "Spiral", "author": "Roderick Gordon", "narrator": "", "series": "Tunnels", "book_number": "5",
    "credit_names": ["Roderick Gordon/Brian Williams/Steven Crossley"], "local_duration_minutes": 727.7,
}
GUNS = {
    "asin": "B002V5CUFK", "title": "The Guns of August",
    "authors": [{"name": "Barbara W. Tuchman"}],
    "narrators": [{"name": "Wanda McCaddon"}],
    "runtime_length_min": 1149,
}
GUNS_CLUES = {
    "title": "The Guns of August", "author": "Barbara W. Tuchman",
    "narrator": "John Lee", "credit_names": ["Barbara W. Tuchman", "John Lee"],
    "local_duration_minutes": 1139.1965,
}


class DifferentEditionTests(unittest.TestCase):
    def test_credit_string_splits_into_readable_names(self):
        self.assertEqual(split_credit_names("Roderick Gordon/Brian Williams & Steven Crossley"),
                         ["Roderick Gordon", "Brian Williams", "Steven Crossley"])

    def test_other_recording_keeps_the_books_own_narrator(self):
        metadata = metadata_from_product(SPIRAL, SPIRAL_CLUES, 1.0)
        self.assertEqual(metadata["edit_mode"], "full")
        self.assertEqual(metadata["narrator"], "Steven Crossley")
        edition = metadata["different_edition"]
        self.assertEqual(edition["local_narrator"], "Steven Crossley")
        self.assertEqual(edition["match_narrator"], "Paul Chequer")
        self.assertEqual((edition["local_minutes"], edition["match_minutes"]), (727.7, 682.0))

    def test_narrator_tag_is_used_when_present(self):
        clues = {**SPIRAL_CLUES, "narrator": "Steven Crossley", "credit_names": ["Roderick Gordon"]}
        self.assertEqual(metadata_from_product(SPIRAL, clues, 1.0)["narrator"], "Steven Crossley")

    def test_perfect_duration_with_another_narrator_keeps_local_tag(self):
        metadata = metadata_from_product(GUNS, GUNS_CLUES, 1.0)
        self.assertEqual(metadata["edit_mode"], "full")
        self.assertEqual(metadata["narrator"], "John Lee")
        self.assertEqual(metadata["duration"]["status"], "perfect")
        self.assertEqual(metadata["different_edition"]["match_narrator"], "Wanda McCaddon")

    def test_same_recording_is_not_flagged(self):
        clues = {**SPIRAL_CLUES, "local_duration_minutes": 684.0,
                 "credit_names": ["Roderick Gordon", "Paul Chequer"]}
        metadata = metadata_from_product(SPIRAL, clues, 1.0)
        self.assertEqual(metadata["narrator"], "Paul Chequer")
        self.assertNotIn("different_edition", metadata)

    def test_author_narrated_book_keeps_its_narrator_tag(self):
        clues = {**SPIRAL_CLUES, "narrator": "Roderick Gordon",
                 "credit_names": ["Roderick Gordon"], "local_duration_minutes": 684.0}
        metadata = metadata_from_product(SPIRAL, clues, 1.0)
        self.assertEqual(metadata["narrator"], "Roderick Gordon")
        self.assertEqual(metadata["different_edition"]["match_narrator"], "Paul Chequer")

    def test_author_in_narrator_tag_uses_other_local_reader(self):
        clues = {**SPIRAL_CLUES, "narrator": "Roderick Gordon",
                 "local_duration_minutes": 684.0}
        metadata = metadata_from_product(SPIRAL, clues, 1.0)
        self.assertEqual(metadata["narrator"], "Steven Crossley")

    def test_match_narrator_among_the_books_credits_is_the_same_edition(self):
        # Tanya rips: uploader in album_artist, narrator in artist, author in
        # composer; the match's narrator is one of those credits.
        tanya = {**SPIRAL, "authors": [{"name": "Carlo Zen"}], "narrators": [{"name": "Shiromi Arserio"}],
                 "series": [], "runtime_length_min": 620}
        clues = {**SPIRAL_CLUES, "author": "Phantom Z. Greyfire", "narrator": "Carlo Zen",
                 "credit_names": ["Phantom Z. Greyfire", "Shiromi Arserio", "Carlo Zen"],
                 "local_duration_minutes": 643.0}
        metadata = metadata_from_product(tanya, clues, 1.0)
        self.assertNotIn("different_edition", metadata)

    def test_no_local_narrator_evidence_changes_nothing(self):
        clues = {**SPIRAL_CLUES, "credit_names": ["Roderick Gordon"]}
        metadata = metadata_from_product(SPIRAL, clues, 1.0)
        self.assertEqual(metadata["narrator"], "Paul Chequer")
        self.assertNotIn("different_edition", metadata)


class DifferentEditionReportTests(unittest.TestCase):
    def setUp(self):
        if "audible" not in sys.modules:
            stub = types.ModuleType("audible")
            stub.Client = stub.Authenticator = type("Stub", (), {})
            sys.modules["audible"] = stub
        path = Path(__file__).parents[2] / "scripts/audible-metadata-fixer-v5.py"
        spec = importlib.util.spec_from_file_location("fixer_v5_different_edition", path)
        self.fixer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.fixer
        spec.loader.exec_module(self.fixer)

    def _item(self, metadata):
        result = self.fixer.ItemResult(index=1, file_path=Path("/lib/Spiral/01.mp3"),
                                       display_path="/lib/Spiral", log_lines=[])
        result.status = "matched"
        result.clues = SPIRAL_CLUES
        result.metadata = metadata
        return self.fixer._build_report_item(result)

    def test_report_item_carries_the_different_edition_flag(self):
        item = self._item(metadata_from_product(SPIRAL, SPIRAL_CLUES, 1.0))
        self.assertEqual(item["different_edition"]["match_narrator"], "Paul Chequer")
        self.assertEqual(item["match"]["narrator"], "Steven Crossley")

    def test_report_item_flags_perfect_duration_different_narrator(self):
        item = self._item(metadata_from_product(GUNS, GUNS_CLUES, 1.0))
        self.assertEqual(item["different_edition"]["local_narrator"], "John Lee")
        self.assertEqual(item["match"]["narrator"], "John Lee")

    def test_report_item_without_the_flag(self):
        clues = {**SPIRAL_CLUES, "local_duration_minutes": 684.0,
                 "credit_names": ["Roderick Gordon", "Paul Chequer"]}
        self.assertNotIn("different_edition", self._item(metadata_from_product(SPIRAL, clues, 1.0)))


if __name__ == "__main__":
    unittest.main()
