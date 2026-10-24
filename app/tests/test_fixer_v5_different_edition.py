"""A match from a different recording of the same book keeps the book's own
narrator, and says so.

Tunnels 05 Spiral: the files are the Recorded Books edition read by Steven
Crossley (728 min, credited "Roderick Gordon/Brian Williams/Steven Crossley");
Audible US only sells the Audible Studios edition read by Paul Chequer
(682 min). A full match would have written Paul Chequer as the narrator.
"""
import unittest
from pathlib import Path

from app.fixer.parsing import split_credit_names
from app.fixer.scoring import metadata_from_product
from app.tests.script_loader import load_script

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

    def test_the_files_author_spelled_unlike_the_match_is_not_a_reader(self):
        # The Idle System (#405): artist "Pegaz A", Audible author "Pegaz", no
        # narrator tag. The credit is the author, so the match's ASIN is written.
        idle = {"asin": "B07RSCQMKZ", "title": "The Idle System: The Birth", "authors": [{"name": "Pegaz"}],
                "narrators": [{"name": "Roman Howell"}], "series": [{"title": "The Idle System", "sequence": "3"}],
                "runtime_length_min": 562}
        clues = {"title": "The Idle System: The Birth", "author": "Pegaz A", "narrator": "",
                 "credit_names": ["Pegaz A"], "book_number": "3", "book_number_source": "title",
                 "existing_asin": "B07RRFDQ2J", "local_duration_minutes": 562.66}
        metadata = metadata_from_product(idle, clues, 1.0)
        self.assertNotIn("different_edition", metadata)
        self.assertEqual(metadata["asin"], "B07RSCQMKZ")
        self.assertEqual(metadata["narrator"], "Roman Howell")

    def test_other_recording_keeps_the_files_recording_fields(self):
        # Its ASIN, cover, release year and ISBN describe the other recording.
        product = {**SPIRAL, "release_date": "2012-01-10", "_abs_isbn": "9781111111111",
                   "product_images": {"500": "https://example/chequer.jpg"}}
        clues = {**SPIRAL_CLUES, "existing_asin": "B00LOCAL01",
                 "current": {"year": "2010", "isbn": "9782222222222"}}
        metadata = metadata_from_product(product, clues, 1.0)
        self.assertEqual(metadata["asin"], "B00LOCAL01")
        self.assertEqual(metadata["year"], "2010")
        self.assertEqual(metadata["isbn"], "9782222222222")
        self.assertEqual(metadata["cover_url"], "")
        self.assertEqual(metadata["different_edition"]["match_asin"], "B006QM9TO4")
        # Book-level fields still come from the match.
        self.assertEqual((metadata["title"], metadata["series"], metadata["sequence"]), ("Spiral", "Tunnels", "5"))

    def test_other_recording_without_a_local_asin_writes_none(self):
        for existing in ("", "NOREALASIN"):
            metadata = metadata_from_product(SPIRAL, {**SPIRAL_CLUES, "existing_asin": existing}, 1.0)
            self.assertEqual(metadata["asin"], "")

    def test_same_recording_still_writes_the_match_asin_and_cover(self):
        product = {**SPIRAL, "product_images": {"500": "https://example/chequer.jpg"}}
        clues = {**SPIRAL_CLUES, "local_duration_minutes": 684.0, "existing_asin": "B00LOCAL01",
                 "credit_names": ["Roderick Gordon", "Paul Chequer"]}
        metadata = metadata_from_product(product, clues, 1.0)
        self.assertEqual(metadata["asin"], "B006QM9TO4")
        self.assertEqual(metadata["cover_url"], "https://example/chequer.jpg")

    def test_et_al_credit_naming_the_author_is_not_another_narrator(self):
        # Movies and the Meaning of Life: the "narrator" tag held the editors
        # ("Kimberly A. Blessing et al."); the match, at the same runtime, is
        # the file's own recording read by Gary Roelofs.
        movies = {"asin": "B07MFM825D", "title": "Movies and the Meaning of Life",
                  "authors": [{"name": "Kimberly A. Blessing"}, {"name": "Paul J. Tudico"}],
                  "narrators": [{"name": "Gary Roelofs"}], "runtime_length_min": 649}
        clues = {"title": "Movies and the Meaning of Life", "author": "Kimberly A. Blessing",
                 "narrator": "Kimberly A. Blessing et al.", "credit_names": ["Kimberly A. Blessing et al."],
                 "local_duration_minutes": 649.72}
        metadata = metadata_from_product(movies, clues, 1.0)
        self.assertNotIn("different_edition", metadata)
        self.assertEqual(metadata["narrator"], "Gary Roelofs")
        self.assertEqual(split_credit_names("Kimberly A. Blessing et al."), ["Kimberly A. Blessing"])
        self.assertEqual(split_credit_names("Peter Etal"), ["Peter Etal"])

    def test_ai_voice_edition_is_penalised_against_a_human_narrator(self):
        from app.fixer.scoring import score_product_for_metadata
        clues = {**GUNS_CLUES}
        human = score_product_for_metadata(clues, GUNS, clues["local_duration_minutes"])
        ai = score_product_for_metadata(clues, {**GUNS, "is_vvab": True}, clues["local_duration_minutes"])
        self.assertEqual(human, 0.9)
        self.assertAlmostEqual(ai, 0.7)


class DifferentEditionReportTests(unittest.TestCase):
    def setUp(self):
        self.fixer = load_script("fixer_v5_different_edition", "audible-metadata-fixer-v5.py")

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

    def _apply(self, folder, metadata, clues):
        source = Path(folder) / "Spiral.m4b"
        source.write_bytes(b"")
        self.fixer.write_marker(source=source, metadata=metadata, clues=clues, score=0.9,
                                mode="normal", aggressive=False, alone=True, written_fields=["title"])
        return source

    def test_different_edition_without_real_asin_is_retried_next_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            clues = {**SPIRAL_CLUES, "current": {}}
            source = self._apply(folder, metadata_from_product(SPIRAL, clues, 0.9), clues)
            marker = self.fixer.load_marker(source)
            self.assertEqual(marker["different_edition"]["match_asin"], "B006QM9TO4")
            self.assertEqual(self.fixer.should_skip_due_to_marker(source, False, False), (False, ""))

    def test_different_edition_with_the_files_own_asin_is_not_retried(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            clues = {**SPIRAL_CLUES, "existing_asin": "B00LOCAL01", "current": {"asin": "B00LOCAL01"}}
            source = self._apply(folder, metadata_from_product(SPIRAL, clues, 0.9), clues)
            self.assertEqual(self.fixer.should_skip_due_to_marker(source, False, False),
                             (True, "already processed"))

    def test_same_recording_marker_drops_an_old_different_edition_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            clues = {**SPIRAL_CLUES, "current": {}}
            source = self._apply(folder, metadata_from_product(SPIRAL, clues, 0.9), clues)
            same = {**SPIRAL_CLUES, "local_duration_minutes": 684.0, "current": {},
                    "credit_names": ["Roderick Gordon", "Paul Chequer"]}
            self._apply(folder, metadata_from_product(SPIRAL, same, 1.0), same)
            self.assertNotIn("different_edition", self.fixer.load_marker(source))
            self.assertEqual(self.fixer.should_skip_due_to_marker(source, False, False),
                             (True, "already processed"))

    def test_report_item_without_the_flag(self):
        clues = {**SPIRAL_CLUES, "local_duration_minutes": 684.0,
                 "credit_names": ["Roderick Gordon", "Paul Chequer"]}
        self.assertNotIn("different_edition", self._item(metadata_from_product(SPIRAL, clues, 1.0)))


if __name__ == "__main__":
    unittest.main()
