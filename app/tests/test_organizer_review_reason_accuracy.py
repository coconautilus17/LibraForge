"""Review reasons the organizer raised on a real run that were wrong, or that hid a wrong result.

Each case comes from the 530-item `_unorganized` run of 2026-10-24.
"""
import tempfile
import unittest
from pathlib import Path

from app.fixer import scoring
from app.tests.script_loader import load_script

ORG = load_script("reason_accuracy_organizer", "organize-audiobooks-by-metadata-v3_13.py")
REPORT = load_script("reason_accuracy_report", "review-libraforge-report.py")
JS = (Path(__file__).parents[1] / "static" / "organizer.js").read_text(encoding="utf-8")


def clues_for(relative):
    root = Path(tempfile.mkdtemp())
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    item = ORG.BookItem(kind="loose_file", source_path=path, audio_files=[path], representative=path)
    return ORG.path_clues(item, root)


class PackFolderRangeTests(unittest.TestCase):
    def test_a_range_tail_is_not_part_of_the_series_name(self):
        cases = {
            "Walrus King - Tunnel Rat Books 1 thru 3": "Tunnel Rat",
            "Walrus King - Tunnel Rat Books 1-3": "Tunnel Rat",
            "Walrus King - Tunnel Rat Books 1 through 3": "Tunnel Rat",
            "Walrus King - Tunnel Rat Books 1 & 2": "Tunnel Rat",
            "Walrus King - Tunnel Rat Book 9+10": "Tunnel Rat",
            "Walrus King - Tunnel Rat (#1-3)": "Tunnel Rat",
        }
        for name, series in cases.items():
            with self.subTest(name):
                self.assertEqual(ORG.parse_legacy_series_container(name), {"series": series, "author": "Walrus King", "narrator": ""})

    def test_a_series_that_merely_has_book_in_its_name_is_untouched(self):
        self.assertEqual(
            ORG.parse_legacy_series_container("Some Author - The Book 2 Chronicles")["series"],
            "The Book 2 Chronicles",
        )

    def test_the_series_clue_for_a_pack_folder_drops_the_range(self):
        clues = clues_for("Walrus King - Tunnel Rat Books 1 thru 3/Walrus King - Tunnel Rat 02.epub")
        self.assertEqual(clues["series"], "Tunnel Rat")

    def test_a_range_in_the_folder_above_does_not_number_one_file(self):
        clues = clues_for("The Titan Book 9+10/the-titan 09 nova-terra-catalyst.m4b")
        self.assertNotIn("book_number", clues)

    def test_a_single_number_in_the_folder_above_still_numbers_the_file(self):
        self.assertEqual(clues_for("The Titan Book 9/untitled track.m4b")["book_number"], "009")

    def test_a_range_in_the_file_name_itself_is_kept(self):
        self.assertEqual(clues_for("Pack/Series Books 1-3.m4b")["book_number"], "001-003")


class AudibleYearAsNumberTests(unittest.TestCase):
    def test_a_year_at_the_end_of_a_subtitle_is_not_a_book_number(self):
        product = {"title": "Postwar", "subtitle": "How Europe rebuilt and redefined itself after 1945", "series": []}
        self.assertEqual(scoring.get_audible_number_candidates(product), [])

    def test_a_trailing_book_number_still_counts(self):
        self.assertEqual(scoring.get_audible_number_candidates({"title": "Casual Farming 3", "series": []}), ["3"])


class TitleIdentityTests(unittest.TestCase):
    def differs(self, metadata_title, path_title, author="", series="", number=""):
        return ORG.title_conflict_should_trigger_review(metadata_title, path_title, series, number, author, "")

    def test_same_book_written_differently_is_not_a_conflict(self):
        cases = [
            ("a release code is not a title", "Dungeon Spiteful", "DS1WBMMNBTD-EA", "Melissa McShane", "Warmaster", "1"),
            ("an honorific on the author", "Cannabis (seeing through the smoke)", "David Nutt - Cannabis (Seeing Through the Smoke) Audiobook", "Professor David Nutt", "", ""),
            ("a subtitle only on the path", "1177 B.C. (Revised and Updated)", "1177 B C The Year Civilization Collapsed (Revised and Updated)", "Eric H. Cline", "", ""),
            ("an audible file stem cut after the series", "The Birth", "3 The Idle System_ The_B07RRFDQ2J_LC_32_22050_Mono", "Pegaz", "The Idle System", "3"),
            ("a credit after the number", "Meditations - Stan Edwards Translation", "Meditations; Marcus Aurelius - A Modern Translation - Trans by Stan Edwards", "Marcus Aurelius", "", ""),
        ]
        for label, metadata_title, path_title, author, series, number in cases:
            with self.subTest(label):
                self.assertFalse(self.differs(metadata_title, path_title, author, series, number))

    def test_two_different_books_still_conflict(self):
        self.assertTrue(self.differs("Shadow of the Scorpion", "The Hidden Orchard", "Neal Asher"))
        self.assertTrue(self.differs("The Birth", "The Fall", "Pegaz", "The Idle System", "3"))

    def test_a_shared_word_alone_is_not_a_match(self):
        self.assertTrue(self.differs("Dragon Bound Fire", "Dragon Rider Ice", "A Writer"))


class SeriesBookTitleFolderTests(unittest.TestCase):
    def test_the_text_after_book_n_is_the_title_not_an_author(self):
        for name, title in (
            ("The System Apocalypse Liberty, Book 1 - Head Of The Class", "Head Of The Class"),
            ("The System Apocalypse Liberty,Book 2 - Dropout", "Dropout"),
        ):
            with self.subTest(name):
                parsed = ORG.parse_book_folder_name(name)
                self.assertEqual(parsed["series"], "The System Apocalypse Liberty")
                self.assertNotEqual(parsed.get("author"), title)
                self.assertEqual(parsed["title"], title)

    def test_a_real_author_after_book_n_is_still_an_author(self):
        parsed = ORG.parse_book_folder_name("Cradle, Book 1 - Will Wight")
        self.assertEqual(parsed["author"], "Will Wight")


class HonorificTests(unittest.TestCase):
    def test_an_honorific_does_not_hide_the_author_credit(self):
        self.assertTrue(ORG.person_segment_matches("David Nutt", ["Professor David Nutt"]))
        self.assertTrue(ORG.person_segment_matches("Jane Roe", ["Dr. Jane Roe"]))
        self.assertFalse(ORG.person_segment_matches("A Different Name", ["Professor David Nutt"]))


class ReasonTiersAgreeTests(unittest.TestCase):
    """Folder Forge's muted-note tier and the suspicion report's info-only tier are one list."""

    def test_the_card_notes_and_the_report_info_reasons_are_the_same_set(self):
        block = JS[JS.index("const NOTE_ONLY_REASONS"):JS.index("function reviewReasonsOf")]
        notes = {line.strip().strip(",").strip('"') for line in block.splitlines()[1:] if line.strip().startswith('"')}
        self.assertEqual(notes, set(REPORT._ORGANIZER_INFO_ONLY_REASONS))


if __name__ == "__main__":
    unittest.main()
