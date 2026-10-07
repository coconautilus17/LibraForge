"""Regression tests for the 2026-10-08 Folder Forge dry-run review of _unorganized.

Each class pins one wrong result seen in a real dry run (539 items):
  - "Book 3 - Book III": a roman-numeral label restating the sequence was kept as a title
  - "Sapiens/Sapiens/Sapiens.m4b": a series equal to the title, with no number, nested twice
  - "Shortest History/of Reality": the series prefix was stripped out of the middle of a title
  - a loose file planned into an on-disk book folder that already holds that book ("-2" copy)
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_dry_run_review", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class RomanLabelRestatesSequenceTests(unittest.TestCase):
    SERIES = "All Jobs and Classes! I Just Wanted One Skill, Not Them All!"

    def test_book_roman_label_matching_number_is_redundant(self):
        self.assertTrue(ORGANIZER.title_is_redundant_with_sequence("Book III", self.SERIES, "", "3"))
        self.assertTrue(ORGANIZER.title_is_redundant_with_sequence("Book IV", self.SERIES, "", "4"))
        self.assertTrue(ORGANIZER.title_is_redundant_with_sequence("Volume II", self.SERIES, "", "2"))

    def test_roman_label_not_matching_number_is_a_distinct_title(self):
        self.assertFalse(ORGANIZER.title_is_redundant_with_sequence("Book III", self.SERIES, "", "4"))

    def test_has_distinct_book_title_agrees(self):
        self.assertFalse(ORGANIZER.has_distinct_book_title("Book III", self.SERIES, "3"))
        self.assertTrue(ORGANIZER.has_distinct_book_title("Book III", self.SERIES, "4"))

    def test_folder_name_collapses_to_sequence_only(self):
        metadata = {"title": "Book I", "series": "DESTINY;DIVINE", "book_number": "1", "sequence_label": ""}
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 1")

    def test_roman_looking_word_that_does_not_equal_the_number_stays_a_title(self):
        # "Book Mix" reads as the roman numeral 1009; for book 5 it is a title.
        self.assertFalse(ORGANIZER.title_is_redundant_with_sequence("Book Mix", self.SERIES, "", "5"))


class SeriesEqualsTitleWithoutNumberTests(unittest.TestCase):
    def target_parts(self, **fields):
        metadata = {"title": "", "series": "", "book_number": "", "sequence_label": "",
                    "author": "Yuval Noah Harari", "author_primary": "Yuval Noah Harari"}
        metadata.update(fields)
        metadata = ORGANIZER.normalize_metadata_title_for_target(metadata)
        return ORGANIZER.build_default_target_dir(Path("/audiobooks"), metadata).parts[2:]

    def test_series_equal_to_title_is_not_nested_twice(self):
        self.assertEqual(
            self.target_parts(title="Sapiens", series="Sapiens"),
            ("Yuval Noah Harari", "Sapiens"),
        )

    def test_series_equal_to_title_ignoring_leading_article(self):
        self.assertEqual(
            self.target_parts(title="The Iliad", series="Iliad", author="Homer", author_primary="Homer"),
            ("Homer", "The Iliad"),
        )

    def test_numbered_book_in_a_series_of_the_same_name_keeps_its_series_folder(self):
        parts = self.target_parts(title="Tunnels", series="Tunnels", book_number="1",
                                  author="Roderick Gordon", author_primary="Roderick Gordon")
        self.assertEqual(parts, ("Roderick Gordon", "Tunnels", "Book 1"))


class SeriesNameInsideTitleTests(unittest.TestCase):
    def test_series_that_is_part_of_the_title_sentence_is_not_stripped(self):
        self.assertEqual(
            ORGANIZER.strip_series_prefix("The Shortest History of Reality", "Shortest History"),
            "The Shortest History of Reality",
        )

    def test_real_prefix_decoration_is_still_stripped(self):
        self.assertEqual(
            ORGANIZER.strip_series_prefix("Dashing Devil Bold Beginnings", "Dashing Devil"),
            "Bold Beginnings",
        )

    def test_separator_prefix_is_still_stripped_even_before_a_connective(self):
        self.assertEqual(
            ORGANIZER.strip_series_prefix("Dashing Devil: Of Fire and Blood", "Dashing Devil"),
            "Of Fire and Blood",
        )


class LooseFileIntoOccupiedFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "src" / "Forge Master.m4b"
        self.source.parent.mkdir()
        self.source.write_bytes(b"x")
        self.target_dir = self.root / "lib" / "Seth Ring" / "The Tower" / "Book 1 - Forge Master"
        self.target_dir.mkdir(parents=True)
        self.item = ORGANIZER.BookItem("loose_file", self.source, [self.source], self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_that_already_holds_the_audio_is_a_conflict_not_a_dash_two_copy(self):
        (self.target_dir / "Forge Master.m4b").write_bytes(b"y")
        ok, path, reason = ORGANIZER.plan_loose_file_move(self.item, self.target_dir)
        self.assertFalse(ok)
        self.assertIsNone(path)
        self.assertEqual(reason, "target folder already exists")

    def test_other_audio_format_in_the_folder_also_counts(self):
        (self.target_dir / "prism-academy-prophecy.mp3").write_bytes(b"y")
        ok, _path, reason = ORGANIZER.plan_loose_file_move(self.item, self.target_dir)
        self.assertFalse(ok)
        self.assertEqual(reason, "target folder already exists")

    def test_folder_with_only_a_cover_and_sidecars_is_still_fine(self):
        (self.target_dir / "cover.jpg").write_bytes(b"y")
        (self.target_dir / "libraforge.json").write_text("{}")
        ok, path, reason = ORGANIZER.plan_loose_file_move(self.item, self.target_dir)
        self.assertTrue(ok, reason)
        self.assertEqual(path, self.target_dir / "Forge Master.m4b")

    def test_empty_existing_folder_is_fine(self):
        ok, path, _reason = ORGANIZER.plan_loose_file_move(self.item, self.target_dir)
        self.assertTrue(ok)
        self.assertEqual(path.parent, self.target_dir)

    def test_merge_existing_targets_keeps_the_old_uniquify_behaviour(self):
        (self.target_dir / "Forge Master.m4b").write_bytes(b"y")
        ok, path, _reason = ORGANIZER.plan_loose_file_move(self.item, self.target_dir, merge_existing=True)
        self.assertTrue(ok)
        self.assertEqual(path.name, "Forge Master-2.m4b")

    def test_ebook_item_ignores_audio_already_in_the_folder(self):
        book = self.root / "src" / "Forge Master.epub"
        book.write_bytes(b"x")
        item = ORGANIZER.BookItem("loose_file", book, [book], book, media_type="ebook")
        (self.target_dir / "Forge Master.m4b").write_bytes(b"y")
        ok, _path, reason = ORGANIZER.plan_loose_file_move(item, self.target_dir)
        self.assertTrue(ok, reason)

    def test_conflict_details_name_what_is_already_there(self):
        (self.target_dir / "Forge Master.m4b").write_bytes(b"y")
        details = ORGANIZER.conflict_review_details(self.target_dir, None, existing_files=[self.target_dir / "Forge Master.m4b"])
        labels = {d["label"] for d in details}
        self.assertIn("Already in that folder", labels)
        self.assertIn("Would land in", labels)


class BracketOnlyTitleTests(unittest.TestCase):
    def test_a_title_that_is_only_a_bracketed_release_tag_is_bad(self):
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("[PZG]"))
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("[Yen Press]"))
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("(Unabridged)"))
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("[Yen Press] {LuCaZ}"))

    def test_label_and_number_with_only_a_release_tag_is_bad(self):
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("Vol. 11 [PZG]"))
        self.assertTrue(ORGANIZER.title_is_bad_after_cleanup("Volume 11 [Yen Press]"))
        self.assertFalse(ORGANIZER.title_is_bad_after_cleanup("Vol. 11 Dawn of War [PZG]"))

    def test_a_real_title_with_a_tag_is_not_bad(self):
        self.assertFalse(ORGANIZER.title_is_bad_after_cleanup("Title [PZG]"))
        self.assertFalse(ORGANIZER.title_is_bad_after_cleanup("[Dramatized] The Hobbit"))

    def test_trusted_sidecar_title_that_is_only_a_tag_falls_back_to_the_sequence(self):
        metadata = {
            "title": "[PZG]", "series": "The Saga of Tanya the Evil", "book_number": "011",
            "sequence_label": "Vol.", "author": "Carlo Zen", "author_primary": "Carlo Zen",
            "metadata_source": "sidecar:libraforge.json",
        }
        metadata = ORGANIZER.normalize_metadata_title_for_target(metadata)
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Vol. 11")


class LeadingSequenceLabelTests(unittest.TestCase):
    def test_leading_book_label_matching_the_number_is_dropped(self):
        self.assertEqual(
            ORGANIZER.clean_book_title("Book 1 - Return of the Wand Mage", "Return of the Wand Mage", "001", trusted=True),
            "Return of the Wand Mage",
        )

    def test_folder_name_is_then_just_the_sequence(self):
        metadata = {
            "title": "Book 1 - Return of the Wand Mage", "series": "Return of the Wand Mage",
            "book_number": "001", "sequence_label": "", "author": "Outspan Foster",
            "author_primary": "Outspan Foster", "metadata_source": "marker:libraforge.json",
        }
        metadata = ORGANIZER.normalize_metadata_title_for_target(metadata)
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 1")

    def test_label_with_a_different_number_is_kept(self):
        self.assertEqual(
            ORGANIZER.clean_book_title("Book 2 - Something", "Series", "001", trusted=True),
            "Book 2 - Something",
        )

    def test_a_title_that_is_a_number_is_kept(self):
        self.assertEqual(ORGANIZER.clean_book_title("1984", "Series", "1984", trusted=True), "1984")


class TrailingSeriesNeedsASeparatorTests(unittest.TestCase):
    def test_series_name_that_ends_the_title_sentence_is_kept(self):
        self.assertEqual(
            ORGANIZER.strip_trailing_series_from_title("The New Market Wizards", "Market Wizards"),
            "The New Market Wizards",
        )
        self.assertEqual(
            ORGANIZER.strip_trailing_series_from_title("Hedge Fund Market Wizards", "Market Wizards"),
            "Hedge Fund Market Wizards",
        )

    def test_series_appended_after_a_volume_marker_is_still_stripped(self):
        self.assertEqual(
            ORGANIZER.strip_trailing_series_from_title(
                "Critical Failures IV The Phantom Pinas Caverns and Creatures", "Caverns and Creatures"
            ),
            "Critical Failures IV The Phantom Pinas",
        )

    def test_series_after_a_separator_is_still_stripped(self):
        self.assertEqual(
            ORGANIZER.strip_trailing_series_from_title(
                "Morningwood - Everybody Loves Large Chests - Morningwood", "Morningwood"
            ),
            "Morningwood - Everybody Loves Large Chests",
        )


class SeriesPrefixBeforeASubtitleTests(unittest.TestCase):
    def test_series_plus_one_word_before_a_subtitle_is_the_title(self):
        # series "The Bright" + "Lord: An Epic Sci Fi Litrpg: Books 1-7" is the book
        # "The Bright Lord" with a subtitle, not a series prefix.
        title = "The Bright Lord: An Epic Sci Fi Litrpg: Books 1-7"
        result = ORGANIZER.strip_series_prefix(title, "The Bright")
        self.assertTrue(result.startswith("The Bright Lord"), result)

    def test_real_series_prefix_with_multi_word_title_is_still_stripped(self):
        self.assertEqual(
            ORGANIZER.strip_series_prefix("Reborn-as-a-Space-Mercenary A New Voyage", "Reborn as a Space Mercenary"),
            "A New Voyage",
        )


class SeriesDescriptorParentheticalTests(unittest.TestCase):
    def test_trailing_genre_series_parenthetical_and_series_restatement_are_dropped(self):
        self.assertEqual(
            ORGANIZER.clean_book_title(
                "Family: The Idle System (A LitRPG series, Book 7)", "The Idle System", "7", trusted=True
            ),
            "Family",
        )

    def test_a_parenthetical_without_the_word_series_is_kept(self):
        self.assertEqual(
            ORGANIZER.clean_book_title("The Hobbit (Unabridged Edition)", "", "", trusted=True),
            "The Hobbit (Unabridged Edition)",
        )


class TitleBySomeoneStandaloneFolderTests(unittest.TestCase):
    def test_title_subtitle_by_authors_is_parsed_as_title_and_authors(self):
        self.assertEqual(
            ORGANIZER.parse_standalone_book_folder_name(
                "A Brief History of Thought - A Philosophical Guide for Living by Luc Ferry, Theo Cuffe"
            ),
            {"title": "A Brief History of Thought", "author": "Luc Ferry, Theo Cuffe"},
        )

    def test_author_dash_title_is_unchanged(self):
        self.assertEqual(
            ORGANIZER.parse_standalone_book_folder_name("Dennis E. Taylor - Heaven's River"),
            {"author": "Dennis E. Taylor", "title": "Heaven's River"},
        )

    def test_by_clause_that_is_not_a_name_list_is_not_an_author(self):
        self.assertNotEqual(
            ORGANIZER.parse_standalone_book_folder_name("Dennis E. Taylor - Walking by the river at night").get("author"),
            "the river at night",
        )


class PathNarratorThatIsReallyTheTitleTests(unittest.TestCase):
    """"Author - Series 01 - Title" read as "Title - Author - Narrator" turns the real title into the
    narrator, which then strips it out of the title and leaves the author name behind."""

    def test_sidecar_without_title_or_narrator_still_resolves_to_the_book_number_only(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Roderick Gordon - Tunnels 01 - Tunnels"
            folder.mkdir()
            audio = folder / "Roderick Gordon - Tunnels 01 - Tunnels.m4b"
            audio.write_bytes(b"x")
            (folder / "libraforge.json").write_text(json.dumps(
                {"book": {"title": "", "author": "Roderick Gordon", "series": "Tunnels", "sequence": "1"}}
            ))
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            metadata = ORGANIZER.normalize_metadata_title_for_target(metadata)
            self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 1")


def _move(source, target, **metadata):
    base = {"title": "T", "author": "A Author", "author_primary": "A Author", "series": "", "book_number": "",
            "sequence_label": "", "asin": "", "media_type": "audiobook", "review_reasons": [], "review_details": []}
    base.update(metadata)
    return {"kind": "loose_file", "source": Path(source), "target": Path(target), "metadata": base}


class RunConsistencyChecksTests(unittest.TestCase):
    def reasons(self, move):
        return move["metadata"]["review_reasons"]

    def test_title_cut_off_by_a_trailing_connective_is_flagged(self):
        move = _move("/in/a.m4b", "/lib/A/Apocalypse Breaker/Book 2 - Book 2 of/a.m4b", title="Book 2 of")
        count = ORGANIZER.annotate_run_consistency([move])
        self.assertEqual(count, 1)
        self.assertIn(ORGANIZER.DANGLING_TITLE_REASON, self.reasons(move))

    def test_title_with_an_unclosed_parenthesis_is_flagged(self):
        move = _move("/in/a.m4b", "/lib/Audiobooks Dimension/Critias (Atlantis/a.m4b", title="Critias (Atlantis")
        ORGANIZER.annotate_run_consistency([move])
        self.assertIn(ORGANIZER.DANGLING_TITLE_REASON, self.reasons(move))

    def test_number_without_a_series_is_flagged_but_a_range_is_not(self):
        numbered = _move("/in/a.m4b", "/lib/Seth Ring/Nova Terra - Kingbreaker/a.m4b", title="Nova Terra - Kingbreaker", book_number="003")
        omnibus = _move("/in/b.m4b", "/lib/Seth Ring/Titan Omnibus/b.m4b", title="Titan Omnibus", book_number="001-003")
        ORGANIZER.annotate_run_consistency([numbered, omnibus])
        self.assertIn(ORGANIZER.NUMBER_WITHOUT_SERIES_REASON, self.reasons(numbered))
        self.assertNotIn(ORGANIZER.NUMBER_WITHOUT_SERIES_REASON, self.reasons(omnibus))

    def test_complete_title_is_not_flagged(self):
        move = _move("/in/a.m4b", "/lib/A/S/Book 2 - Dragon Fire/a.m4b", title="Dragon Fire")
        self.assertEqual(ORGANIZER.annotate_run_consistency([move]), 0)

    def test_book_folder_repeating_the_series_folder_is_flagged(self):
        move = _move("/in/a.m4b", "/lib/Homer/Meditations/Meditations/a.m4b", series="Meditations")
        ORGANIZER.annotate_run_consistency([move])
        self.assertIn(ORGANIZER.REPEATED_FOLDER_REASON, self.reasons(move))

    def test_longer_series_variant_by_the_same_author_is_flagged_not_the_short_one(self):
        short = _move("/in/1.m4b", "/lib/Seth Ring/The Titan/Book 10 - X/1.m4b", author_primary="Seth Ring", series="The Titan")
        long_ = _move("/in/2.m4b", "/lib/Seth Ring/Nova Terra - Catalyst - The Titan Series/2.m4b",
                      author_primary="Seth Ring", series="Nova Terra - Catalyst - The Titan Series")
        ORGANIZER.annotate_run_consistency([short, long_])
        self.assertIn(ORGANIZER.SERIES_VARIANT_REASON, self.reasons(long_))
        self.assertNotIn(ORGANIZER.SERIES_VARIANT_REASON, self.reasons(short))

    def test_unrelated_series_by_one_author_are_not_flagged(self):
        a = _move("/in/1.m4b", "/lib/X/Alpha Saga/a.m4b", author_primary="X Writer", series="Alpha Saga")
        b = _move("/in/2.m4b", "/lib/X/Beta Chronicles/b.m4b", author_primary="X Writer", series="Beta Chronicles")
        self.assertEqual(ORGANIZER.annotate_run_consistency([a, b]), 0)

    def test_author_written_two_ways_flags_the_minority_spelling(self):
        main1 = _move("/in/1.m4b", "/lib/Seth Ring/S/1.m4b", author_primary="Seth Ring")
        main2 = _move("/in/2.m4b", "/lib/Seth Ring/S/2.m4b", author_primary="Seth Ring")
        odd = _move("/in/3.m4b", "/lib/Seth Ring (Titan)/S/3.m4b", author_primary="Seth Ring (Titan)")
        ORGANIZER.annotate_run_consistency([main1, main2, odd])
        self.assertIn(ORGANIZER.AUTHOR_VARIANT_REASON, self.reasons(odd))
        self.assertNotIn(ORGANIZER.AUTHOR_VARIANT_REASON, self.reasons(main1))

    def test_mixed_book_and_volume_labels_in_one_series_flag_the_odd_one(self):
        kwargs = dict(author_primary="Leon West", series="Idle Village Hero")
        a = _move("/in/1.m4b", "/lib/L/I/Book 1/1.m4b", book_number="1", sequence_label="Book", **kwargs)
        b = _move("/in/2.m4b", "/lib/L/I/Volume 2/2.m4b", book_number="2", sequence_label="Volume", **kwargs)
        c = _move("/in/3.m4b", "/lib/L/I/Book 3/3.m4b", book_number="3", sequence_label="Book", **kwargs)
        ORGANIZER.annotate_run_consistency([a, b, c])
        self.assertIn(ORGANIZER.LABEL_VARIANT_REASON, self.reasons(b))
        self.assertNotIn(ORGANIZER.LABEL_VARIANT_REASON, self.reasons(a))

    def test_same_real_asin_twice_flags_both_but_placeholders_do_not(self):
        a = _move("/in/1.m4b", "/lib/A/S/Book 4 - P/1.m4b", asin="B075M1RFCQ")
        b = _move("/in/2.m4b", "/lib/A/S/Book 7 - P/2.m4b", asin="B075M1RFCQ")
        ORGANIZER.annotate_run_consistency([a, b])
        self.assertIn(ORGANIZER.DUPLICATE_ASIN_REASON, self.reasons(a))
        self.assertIn(ORGANIZER.DUPLICATE_ASIN_REASON, self.reasons(b))
        c = _move("/in/3.m4b", "/lib/A/S/c.m4b", asin="HAS_ASIN")
        d = _move("/in/4.m4b", "/lib/A/S/d.m4b", asin="HAS_ASIN")
        self.assertEqual(ORGANIZER.annotate_run_consistency([c, d]), 0)


class SequenceOnlyNoteIsNotFlaggedForNoiseTests(unittest.TestCase):
    def test_path_title_that_is_only_author_and_asin_noise_adds_no_review_reason(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Idle Village Hero - Leon West [B0G362ZYYK].m4b"
            audio.write_bytes(b"x")
            Path(str(audio) + ".libraforge.json").write_text(json.dumps({"book": {
                "title": "Idle Village Hero", "author": "Leon West", "series": "Idle Village Hero", "sequence": "1",
            }}))
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertNotIn("title matches series name; using sequence only", metadata["review_reasons"])


class ArticleOnlyTitleDifferenceIsNotAConflictTests(unittest.TestCase):
    def test_leading_article_difference_does_not_trigger_review(self):
        self.assertFalse(ORGANIZER.title_conflict_should_trigger_review(
            metadata_title="The Ghoul on the Hill", path_title="Ghoul on the Hill",
            series="The Hipposync Archives", book_number="2",
        ))


if __name__ == "__main__":
    unittest.main()
