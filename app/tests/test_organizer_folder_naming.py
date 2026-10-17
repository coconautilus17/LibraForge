"""How Folder Forge turns known metadata into folder names: the sequence prefix,
when a title is redundant next to it, the book folder, and the default
Author/Series/Book path. Also the legacy collection-folder parser and the rule
that decides when two different titles are a real conflict."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_folder_naming", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class DisplayNumberTests(unittest.TestCase):
    def test_padding_and_trailing_zero_decimals_are_removed(self):
        for raw, expected in (("001", "1"), ("003.5", "3.5"), ("001-002", "1-2"), ("001+002", "1+2"), ("010", "10"), ("000", "0"),
                              ("1.0", "1"), ("", ""), ("abc", "abc")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.display_book_number(raw), expected)


class SequencePrefixTests(unittest.TestCase):
    def test_a_single_number_uses_the_label_defaulting_to_book(self):
        for label, number, expected in (("Book", "001", "Book 1"), ("", "001", "Book 1"), ("Vol.", "003.5", "Vol. 3.5"),
                                        ("Volume", "002", "Volume 2"), ("garbage", "001", "Book 1")):
            with self.subTest(label=label, number=number):
                self.assertEqual(ORG.build_sequence_prefix(label, number), expected)

    def test_a_range_pluralises_the_label(self):
        for label, expected in (("Book", "Books 1-2"), ("", "Books 1-2"), ("Volume", "Volumes 1-2"), ("vol", "Vol. 1-2"),
                                ("Novel", "Novels 1-2"), ("Side Story", "Side Story 1-2")):
            with self.subTest(label=label):
                self.assertEqual(ORG.build_sequence_prefix(label, "001-002"), expected)


class RedundantTitleTests(unittest.TestCase):
    def redundant(self, title, series="Cradle", label="Book", number="005"):
        return ORG.title_is_redundant_with_sequence(title, series, label, number)

    def test_titles_that_only_restate_the_sequence_or_series_are_redundant(self):
        for title in ("Book 5", "Cradle", "5", "Book Five", "cradle"):
            with self.subTest(title=title):
                self.assertTrue(self.redundant(title), title)
        self.assertTrue(self.redundant("Books 1-2", number="001-002"))
        self.assertTrue(self.redundant("Vol. 5", label="Vol."))

    def test_a_real_title_is_not(self):
        self.assertFalse(self.redundant("Unsouled", number="001"))
        self.assertFalse(self.redundant("Book 6"))

    def test_without_a_series_or_a_number_nothing_is_redundant(self):
        self.assertFalse(self.redundant("Book 5", series=""))
        self.assertFalse(self.redundant("Book 5", number=""))


class BookFolderNameTests(unittest.TestCase):
    def name(self, **meta):
        return ORG.build_book_folder_name(meta)

    def test_a_series_book_gets_its_prefix_before_the_title(self):
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number="001", sequence_label="Book"), "Book 1 - Unsouled")
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number="001-002"), "Books 1-2 - Unsouled")
        self.assertEqual(self.name(title="Foo: Bar?", series="S", book_number="003.5", sequence_label="Vol."), "Vol. 3.5 - Foo - Bar")

    def test_a_title_that_only_repeats_the_series_collapses_to_the_prefix(self):
        self.assertEqual(self.name(title="Cradle", series="Cradle", book_number="001"), "Book 1")

    def test_an_asin_in_the_title_slot_never_becomes_the_folder_name(self):
        self.assertEqual(self.name(title="B0ABCDEFGH", series="Cradle", book_number="002"), "Book 2")
        self.assertEqual(self.name(title="NOREALASIN"), "Unknown Title")

    def test_without_a_series_or_number_the_title_stands_alone(self):
        self.assertEqual(self.name(title="Unsouled", series="", book_number="001"), "Unsouled")
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number=""), "Unsouled")
        self.assertEqual(self.name(title="", series="", book_number=""), "Unknown Title")


class DefaultTargetDirTests(unittest.TestCase):
    ROOT = Path("/lib")

    def target(self, **meta):
        return ORG.build_default_target_dir(self.ROOT, meta)

    def test_a_series_book_goes_under_author_series_and_book_folder(self):
        self.assertEqual(self.target(title="Unsouled", author_primary="Will Wight", series="Cradle", book_number="001"),
                         self.ROOT / "Will Wight" / "Cradle" / "Book 1 - Unsouled")

    def test_the_primary_author_beats_the_full_credit_and_initials_are_canonicalised(self):
        self.assertEqual(self.target(title="X", author="J R R Tolkien, Ann Lee", author_primary="J R R Tolkien"),
                         self.ROOT / "J.R.R. Tolkien" / "X")

    def test_a_missing_author_goes_to_unknown_author(self):
        self.assertEqual(self.target(title="Dune", author="", series=""), self.ROOT / "Unknown Author" / "Dune")

    def test_a_dramatized_series_gets_an_imprint_suffixed_series_folder(self):
        self.assertEqual(self.target(title="Unsouled", author="Will Wight", series="Cradle", book_number="001", edition_tag="GraphicAudio"),
                         self.ROOT / "Will Wight" / "Cradle [GraphicAudio]" / "Book 1 - Unsouled")

    def test_a_standalone_dramatization_tags_the_book_folder_instead(self):
        self.assertEqual(self.target(title="The Hobbit", author="Tolkien", edition_tag="Dramatized"),
                         self.ROOT / "Tolkien" / "The Hobbit [Dramatized]")

    def test_ebooks_never_share_a_folder_with_the_audiobook(self):
        self.assertEqual(self.target(title="Dune", author="Frank Herbert", media_type="ebook"), self.ROOT / "Frank Herbert" / "Dune - EBOOK")
        self.assertEqual(self.target(title="Dune", author="Frank Herbert", series="Dune", book_number="001", media_type="ebook"),
                         self.ROOT / "Frank Herbert" / "Dune - EBOOK" / "Book 1")


class SeriesDirLabelTests(unittest.TestCase):
    def label(self, **meta):
        return ORG.series_dir_label(meta)

    def test_plain_tagged_and_ebook_series_labels(self):
        self.assertEqual(self.label(series="Cradle"), "Cradle")
        self.assertEqual(self.label(series="Cradle", edition_tag="Dramatized"), "Cradle [Dramatized]")
        self.assertEqual(self.label(series="Cradle", media_type="ebook"), "Cradle - EBOOK")
        self.assertEqual(self.label(series="Cradle", edition_tag="Dramatized", media_type="ebook"), "Cradle [Dramatized] - EBOOK")
        self.assertEqual(self.label(series=""), "Unknown Series")


class LegacyContainerTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_legacy_series_container(name)

    def test_series_author_narrator_folders(self):
        self.assertEqual(self.parse("Cradle - Will Wight - Travis Baldree"), {"series": "Cradle", "author": "Will Wight", "narrator": "Travis Baldree"})
        self.assertEqual(self.parse("A - B - C - D"), {"series": "A", "author": "B", "narrator": "C, D"})

    def test_author_series_pack_folders(self):
        self.assertEqual(self.parse("Will Wight - Cradle (#1-6)"), {"series": "Cradle", "author": "Will Wight", "narrator": ""})

    def test_series_with_a_book_range_in_parentheses(self):
        for name in ("Cradle (Book 1 & 2)", "Cradle (Books 1-3)"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {"series": "Cradle", "author": "", "narrator": ""})

    def test_ordinary_folders_are_not_containers(self):
        for name in ("Will Wight - Unsouled", "Cradle", "", "(Books 1-3)"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {})


class TitleConflictTests(unittest.TestCase):
    def conflict(self, metadata_title, path_title, series="Cradle", number="001", author="", narrator=""):
        return ORG.title_conflict_should_trigger_review(metadata_title, path_title, series, number, author, narrator)

    def test_two_genuinely_different_titles_are_a_conflict(self):
        self.assertTrue(self.conflict("Unsouled", "Totally Different Words"))
        self.assertTrue(self.conflict("Qwerty Uiop", "Qwerty Asdf", series="S"))

    def test_identical_or_contained_titles_are_not(self):
        self.assertFalse(self.conflict("Unsouled", "Unsouled"))
        self.assertFalse(self.conflict("Alpha Beta Gamma", "Alpha Beta Gamma Delta", series="S"))
        self.assertFalse(self.conflict("The Warlock", "Warlock"))

    def test_an_author_decoration_on_one_side_is_not_a_conflict(self):
        self.assertFalse(self.conflict("Unsouled", "Unsouled - Will Wight", author="Will Wight"))

    def test_a_side_that_only_restates_the_series_and_number_is_not_a_distinct_title(self):
        self.assertFalse(self.conflict("Cradle Book 1", "Book 1"))
        self.assertFalse(self.conflict("", "Unsouled"))


class StandaloneFolderNameTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_standalone_book_folder_name(name)

    def test_author_title_in_either_order_by_which_side_looks_like_a_person(self):
        self.assertEqual(self.parse("Will Wight - Unsouled"), {"author": "Will Wight", "title": "Unsouled"})
        self.assertEqual(self.parse("Will Wight, Bob Roe - Unsouled"), {"author": "Will Wight, Bob Roe", "title": "Unsouled"})

    def test_title_author_narrator_for_three_segments(self):
        self.assertEqual(self.parse("Unsouled - Will Wight - Travis Baldree"),
                         {"title": "Unsouled", "author": "Will Wight", "narrator": "Travis Baldree"})

    def test_a_bracketed_middle_segment_is_a_tag_not_an_author(self):
        self.assertEqual(self.parse("Title - [Series-2] - Real Title"), {})

    def test_a_track_style_name_with_a_numeric_last_segment_gives_author_and_title(self):
        self.assertEqual(self.parse("Will Wight - Unsouled - 01"), {"author": "Will Wight", "title": "Unsouled"})
        self.assertEqual(self.parse("Wight, Will - Unsouled - 5"), {"author": "Wight, Will", "title": "Unsouled"})

    def test_a_by_credit_after_the_title_names_the_author(self):
        self.assertEqual(self.parse("Brief History - Subtitle by Stephen Hawking, Leonard Mlodinow"),
                         {"title": "Brief History", "author": "Stephen Hawking, Leonard Mlodinow"})

    def test_numbered_prefixes_unrecognised_shapes_and_blanks_give_nothing(self):
        for name in ("01 - Unsouled", "Cradle 3 - Unsouled", "Unsouled", "", "Unsouled - Will Wight"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {})

    def test_a_numeric_last_segment_needs_a_person_shaped_author(self):
        self.assertEqual(ORG.parse_representative_track_name("Unsouled - Cradle - 01"), {})
        self.assertEqual(ORG.parse_representative_track_name("Will Wight - Unsouled - 01"), {"author": "Will Wight", "title": "Unsouled"})
        self.assertEqual(ORG.parse_representative_track_name("Will Wight - Unsouled - Chapter One"), {})
        self.assertEqual(ORG.parse_representative_track_name("Will 5 Wight - Unsouled - 01"), {})
        self.assertEqual(ORG.parse_representative_track_name(""), {})


class ExplicitIdentityFolderTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_explicit_identity_folder_name(name)

    def test_series_book_title_author_in_the_three_segment_forms(self):
        expected = {"title": "Unsouled", "author": "Will Wight", "series": "Cradle", "number": "001", "sequence_label": "Book"}
        self.assertEqual(self.parse("Cradle Book 1 - Unsouled - Will Wight"), expected)

    def test_author_title_with_a_series_in_parentheses(self):
        self.assertEqual(self.parse("Will Wight - Unsouled (Cradle, Book 1)"),
                         {"title": "Unsouled", "author": "Will Wight", "series": "Cradle", "number": "001", "sequence_label": "Book"})

    def test_series_book_n_dash_author_uses_the_series_as_the_title(self):
        self.assertEqual(self.parse("Cradle, Book 1 - Will Wight"),
                         {"title": "Cradle", "author": "Will Wight", "series": "Cradle", "number": "001", "sequence_label": "Book"})

    def test_a_bare_number_series_needs_an_initials_author_to_avoid_false_positives(self):
        self.assertEqual(self.parse("Cradle 1 - W. Wight")["author"], "W. Wight")
        self.assertEqual(self.parse("Cradle 1 - Will Wight"), {})

    def test_title_author_dash_series_number(self):
        self.assertEqual(self.parse("Unsouled, Will Wight - Cradle 1"),
                         {"title": "Unsouled", "author": "Will Wight", "series": "Cradle", "number": "001", "sequence_label": "Book"})

    def test_co_author_folders_ending_in_a_book_label_are_left_to_other_parsers(self):
        self.assertEqual(self.parse("Sebastian Wilde, Jamie Hawke - Happy Hunting Planet Kill, Book 2"), {})

    def test_year_and_book_label_tails_are_not_series_numbers(self):
        self.assertEqual(self.parse("TheFirstDefier, J.F.Brink - Dungeon Run - 2024"), {})

    def test_plain_titles_and_blanks_are_not_explicit_identities(self):
        for name in ("Unsouled", "Book 1 - Unsouled", ""):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {})


class BookFolderNameParserTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_book_folder_name(name)

    def test_the_organised_book_folder_form_gives_a_padded_number_and_the_title(self):
        self.assertEqual(self.parse("Book 01 - Unsouled"), {"number": "001", "title": "Unsouled", "sequence_label": "Book"})
        self.assertEqual(self.parse("Vol. 4 - Title"), {"number": "004", "title": "Title", "sequence_label": "Vol."})

    def test_a_series_with_a_book_number_gets_the_series_as_its_title(self):
        self.assertEqual(self.parse("Cradle, Book 3"), {"series": "Cradle", "number": "003", "sequence_label": "Book", "title": "Cradle"})
        self.assertEqual(self.parse("Cradle Book 3"), {"title": "Cradle", "number": "003", "sequence_label": "Book"})

    def test_a_range_becomes_a_books_title_and_number(self):
        self.assertEqual(self.parse("Books 1-3"), {"number": "001-003", "sequence_label": "Book", "title": "Books 1-3"})

    def test_a_light_novel_folder_with_author_year_series_volume_and_narrator(self):
        got = self.parse("Isuna Hasekura (2008) Spice and Wolf, Volume 8 - Town of Strife 1 (Narrator)")
        self.assertEqual(got, {"author": "Isuna Hasekura", "year": "2008", "series": "Spice and Wolf", "number": "008",
                               "title": "Town of Strife 1", "narrator": "Narrator", "sequence_label": "Volume"})

    def test_an_ambiguous_author_title_series_form_keeps_only_the_reliable_number(self):
        self.assertEqual(self.parse("Shane Walker - Corporate Warfare All Trades, Book 3"), {"number": "003", "sequence_label": "Book"})

    def test_plain_names_are_just_a_title_with_no_number(self):
        self.assertEqual(self.parse("Plain Name"), {"title": "Plain Name", "number": ""})
        self.assertEqual(self.parse("Unsouled (2016)"), {"title": "Unsouled (2016)", "number": ""})

    def test_a_blank_name_gives_nothing(self):
        self.assertEqual(self.parse(""), {})

    @unittest.expectedFailure
    def test_a_series_first_folder_should_not_invent_an_author_and_a_series_called_book(self):
        # KNOWN BUG (see docs/test-audit-2026-10-16.md): "Destiny Cycle - Book 004 - Threads
        # of Destiny Vol 1" is the very example finish() documents as series-first, but
        # parse_explicit_identity_folder_name reads the first segment as an AUTHOR and
        # "Book" as the SERIES (loose_middle_series), so the real series is lost.
        got = self.parse("Destiny Cycle - Book 004 - Threads of Destiny Vol 1")
        self.assertNotEqual(got.get("series"), "Book")
        self.assertNotEqual(got.get("author"), "Destiny Cycle")


if __name__ == "__main__":
    unittest.main()
