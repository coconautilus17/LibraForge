"""Search-query construction and the structured-path override in
app.fixer.clues, asserted on the exact values the fixer will use."""
import unittest
from pathlib import Path

from app.fixer.clues import (
    apply_structured_path_override,
    build_search_queries_from_clues,
    capture_publisher_clue,
    capture_sku_clue,
    choose_group_book_number,
    clean_group_folder_title,
    group_numbers_are_part_indices,
    infer_group_identity_from_path,
    read_current_book_metadata,
)

BASE = {"author": "Will Wight", "title": "Unsouled", "raw_title": "Unsouled", "series": "Cradle", "book_number": "1"}


class SearchQueryTests(unittest.TestCase):
    def q(self, **over):
        return build_search_queries_from_clues({**BASE, **over})

    def test_the_full_set_is_ordered_from_most_to_least_specific(self):
        self.assertEqual(self.q(), [
            "Unsouled Will Wight", "Cradle Will Wight", "Will Wight Cradle Book 1", "Will Wight Cradle 1",
            "Cradle Unsouled Will Wight", "Unsouled", "Cradle"])

    def test_without_an_author_only_title_and_series_alone_remain(self):
        self.assertEqual(self.q(author=""), ["Unsouled", "Cradle"])

    def test_without_a_series_there_are_no_series_or_number_queries(self):
        self.assertEqual(self.q(series="", book_number=""), ["Unsouled Will Wight", "Unsouled"])

    def test_without_a_book_number_the_numbered_series_queries_are_skipped(self):
        self.assertEqual(self.q(book_number=""), [
            "Unsouled Will Wight", "Cradle Will Wight", "Cradle Unsouled Will Wight", "Unsouled", "Cradle"])

    def test_a_leading_sequence_in_the_title_adds_a_sequence_free_variant_right_after(self):
        queries = self.q(title="01 - Unsouled", raw_title="01 - Unsouled")
        self.assertEqual(queries[:2], ["01 Unsouled Will Wight", "Unsouled Will Wight"])

    def test_a_different_raw_title_gets_its_own_author_query_after_the_title_ones(self):
        queries = self.q(raw_title="Cradle Book One Unsouled")
        self.assertEqual(queries[0], "Unsouled Will Wight")
        self.assertEqual(queries[1], "Cradle Book One Unsouled Will Wight")

    def test_a_sequence_free_raw_title_is_added_only_when_it_is_new(self):
        queries = self.q(title="Unsouled", raw_title="02 - Unsouled")
        self.assertIn("02 Unsouled Will Wight", queries)
        self.assertEqual(queries.count("Unsouled Will Wight"), 1)

    def test_years_and_trailing_parentheses_are_dropped_and_punctuation_flattened(self):
        queries = self.q(title="Unsouled (2016)", raw_title="Unsouled (2016)")
        self.assertEqual(queries[0], "Unsouled Will Wight")
        queries = self.q(title="Unsouled: A Cradle Novel", raw_title="Unsouled: A Cradle Novel")
        self.assertEqual(queries[0], "Unsouled A Cradle Novel Will Wight")

    def test_commas_become_spaces_and_duplicates_collapse_case_insensitively(self):
        queries = self.q(title="UNSOULED", raw_title="unsouled", series="unsouled")
        self.assertEqual(len({q.lower() for q in queries}), len(queries))

    def test_nothing_known_gives_no_queries(self):
        self.assertEqual(build_search_queries_from_clues(
            {"author": "", "title": "", "raw_title": "", "series": "", "book_number": ""}), [])


class StructuredPathOverrideTests(unittest.TestCase):
    PATH = Path("/lib/Will Wight/Cradle/Cradle - Book 01 - Unsouled/Unsouled.m4b")

    def run_override(self, **over):
        clues = {"author": "Will Wight", "title": "Unsouled", "raw_title": "Unsouled", "series": "Cradle",
                 "book_number": "1", "book_number_source": "tag", **over}
        return apply_structured_path_override(clues, self.PATH)

    def test_matching_tags_are_left_completely_alone(self):
        out = self.run_override()
        self.assertNotIn("path_override", out)
        self.assertEqual(out["book_number_source"], "tag")

    def test_a_wrong_embedded_title_is_replaced_and_the_change_is_recorded(self):
        out = self.run_override(title="Wrong", raw_title="Wrong")
        self.assertEqual((out["title"], out["raw_title"]), ("Unsouled", "Cradle - Book 01 - Unsouled"))
        self.assertEqual(out["path_override"]["changed"], ["title"])
        self.assertIs(out["path_override"]["applied"], True)
        self.assertEqual(out["embedded_before_path_override"]["title"], "Wrong")
        self.assertEqual(out["embedded_before_path_override"]["book_number_source"], "tag")

    def test_a_wrong_embedded_series_is_replaced(self):
        out = self.run_override(series="Other")
        self.assertEqual(out["series"], "Cradle")
        self.assertEqual(out["path_override"]["changed"], ["series"])

    def test_a_wrong_embedded_number_is_replaced_and_marked_as_coming_from_the_path(self):
        out = self.run_override(book_number="7")
        self.assertEqual((out["book_number"], out["book_number_source"]), ("1", "path"))
        self.assertEqual(out["path_override"]["changed"], ["number"])

    def test_equal_numbers_in_different_spellings_are_not_a_change(self):
        out = self.run_override(book_number="01")
        self.assertNotIn("path_override", out)

    def test_several_changes_are_listed_sorted(self):
        out = self.run_override(title="Wrong", raw_title="Wrong", series="Other", book_number="7")
        self.assertEqual(out["path_override"]["changed"], ["number", "series", "title"])

    def test_a_path_title_equal_to_the_series_name_is_not_taken_as_the_book_title(self):
        # tags say series "Unsouled" and title "Something Else": the folder's "Unsouled" is the series label
        out = self.run_override(series="Unsouled", title="Something Else", raw_title="Something Else")
        self.assertEqual(out["title"], "Something Else")

    def test_a_path_that_just_merges_embedded_title_and_series_does_not_override_the_series(self):
        path = Path("/lib/Magic Eater/Courts Magic Eater - Book 01/Courts.m4b")
        clues = {"author": "", "title": "Courts", "raw_title": "Courts", "series": "Magic Eater",
                 "book_number": "1", "book_number_source": "tag"}
        out = apply_structured_path_override(clues, path)
        self.assertEqual((out["title"], out["series"]), ("Courts", "Magic Eater"))

    def test_an_unstructured_path_changes_nothing(self):
        clues = dict(BASE, book_number_source="tag")
        out = apply_structured_path_override(clues, Path("/lib/random.m4b"))
        self.assertEqual(out, dict(BASE, book_number_source="tag"))


class ReadCurrentBookMetadataTests(unittest.TestCase):
    def test_tags_map_to_the_current_metadata_fields(self):
        out = read_current_book_metadata({"title": "Real", "artist": "A B", "comment": "sum", "date": "2020",
                                          "asin": "b0abc", "subtitle": "sub", "isbn": "978"})
        self.assertEqual((out["title"], out["author"], out["summary"], out["year"], out["asin"], out["subtitle"], out["isbn"]),
                         ("Real", "A B", "sum", "2020", "B0ABC", "sub", "978"))

    def test_a_generic_chapter_title_is_replaced_by_the_album_but_the_raw_title_is_kept(self):
        out = read_current_book_metadata({"title": "Chapter 1", "album": "Real Book"})
        self.assertEqual((out["title"], out["raw_title"]), ("Real Book", "Chapter 1"))

    def test_a_real_title_wins_over_the_album(self):
        self.assertEqual(read_current_book_metadata({"title": "Real", "album": "Other"})["title"], "Real")

    def test_a_generic_title_with_a_generic_album_stays_as_it_is(self):
        out = read_current_book_metadata({"title": "Chapter 1", "album": "Chapter 2"})
        self.assertEqual(out["title"], "Chapter 1")

    def test_a_generic_title_with_no_album_stays_as_it_is(self):
        self.assertEqual(read_current_book_metadata({"title": "Chapter 1"})["title"], "Chapter 1")


class PublisherAndSkuClueTests(unittest.TestCase):
    def test_a_sku_is_found_in_any_of_the_known_tags_and_upper_cased(self):
        self.assertEqual(capture_sku_clue({}, {"ufid": "xx bk_rhuk_002027 yy"}), {"sku": "BK_RHUK_002027"})
        self.assertEqual(capture_sku_clue({}, {"audible_sku": "BK_ABCD_000001"}), {"sku": "BK_ABCD_000001"})
        self.assertEqual(capture_sku_clue({"keep": 1}, {"sku": "nope"}), {"keep": 1})

    def test_a_dedicated_publisher_tag_is_recorded_and_verified_against_the_catalog(self):
        self.assertEqual(capture_publisher_clue({}, {"publisher": "Tantor Audio"}),
                         {"publisher": "Tantor Audio", "publisher_verified": True})

    def test_an_unknown_publisher_is_kept_but_not_verified(self):
        out = capture_publisher_clue({}, {"publisher": "Obscure Press Zed"})
        self.assertEqual((out["publisher"], out["publisher_verified"]), ("Obscure Press Zed", False))

    def test_a_catalog_imprint_in_a_neighbouring_field_is_recorded(self):
        out = capture_publisher_clue({}, {"comment": "Narrated, Tantor Audio"})
        self.assertEqual((out["publisher"], out["publisher_verified"]), ("Tantor Audio", True))

    def test_a_format_descriptor_is_not_a_publisher(self):
        self.assertEqual(capture_publisher_clue({}, {"publisher": "Unabridged"}), {})

    def test_a_publisher_leaked_into_the_author_is_stripped_from_it(self):
        out = capture_publisher_clue({"author": "Jane Doe, Tantor Audio"}, {"publisher": "Tantor Audio"})
        self.assertEqual(out["author"], "Jane Doe")

    def test_an_author_that_is_nothing_but_a_publisher_is_left_alone(self):
        out = capture_publisher_clue({"author": "Tantor Audio"}, {})
        self.assertEqual(out["author"], "Tantor Audio")

    def test_clean_authors_and_narrators_are_not_touched(self):
        out = capture_publisher_clue({"author": "Jane Doe", "narrator": "Bob Roe"}, {})
        self.assertEqual((out["author"], out["narrator"]), ("Jane Doe", "Bob Roe"))


class GroupNumberTests(unittest.TestCase):
    def _c(self, number, source):
        return {"book_number": number, "book_number_source": source}

    def test_different_numbers_per_file_are_part_indices(self):
        self.assertIs(group_numbers_are_part_indices([self._c("1", "path"), self._c("2", "path")]), True)

    def test_the_same_number_on_every_file_is_a_book_number(self):
        self.assertIs(group_numbers_are_part_indices([self._c("1", "path"), self._c("1", "path")]), False)

    def test_one_numbered_file_is_not_enough_to_tell(self):
        self.assertIs(group_numbers_are_part_indices([self._c("1", "path")]), False)

    def test_tag_numbers_are_not_considered(self):
        self.assertIs(group_numbers_are_part_indices([self._c("1", "tag"), self._c("2", "tag")]), False)

    def test_path_numbers_beat_title_numbers(self):
        files = [self._c("2", "path")] * 3
        self.assertEqual(choose_group_book_number(files, "x"), ("2", "path"))
        self.assertEqual(choose_group_book_number([self._c("2", "title")] * 3, "x"), ("2", "title"))
        mixed = [self._c("2", "path")] * 2 + [self._c("5", "title")]
        self.assertEqual(choose_group_book_number(mixed, "x"), ("2", "path"))

    def test_a_number_only_a_minority_of_files_carry_is_not_the_book_number(self):
        files = [self._c("2", "path"), self._c("", ""), self._c("", "")]
        self.assertEqual(choose_group_book_number(files, "Plain"), ("", ""))

    def test_a_spread_of_numbers_falls_back_to_the_folder_name(self):
        files = [self._c("1", "path"), self._c("2", "path")]
        self.assertEqual(choose_group_book_number(files, "Book 4 - Foo"), ("4", "path"))

    def test_track_numbers_are_never_a_group_book_number(self):
        self.assertEqual(choose_group_book_number([self._c("3", "track")], "Plain"), ("", ""))


class GroupIdentityFromPathTests(unittest.TestCase):
    def test_author_and_series_come_from_the_two_folders_above_a_book_n_folder(self):
        self.assertEqual(infer_group_identity_from_path(Path("/lib/Will Wight/Cradle/Book 1 - Unsouled")),
                         ("Will Wight", "Cradle"))
        self.assertEqual(infer_group_identity_from_path(Path("/lib/Will Wight/Cradle/Volume 2")), ("Will Wight", "Cradle"))

    def test_a_folder_that_is_not_a_numbered_book_gives_nothing(self):
        self.assertEqual(infer_group_identity_from_path(Path("/lib/Will Wight/Cradle/Unsouled")), ("", ""))

    def test_generic_top_level_folders_are_not_an_author_or_a_series(self):
        self.assertEqual(infer_group_identity_from_path(Path("/lib/Audiobooks/Cradle/Book 1")), ("", "Cradle"))
        self.assertEqual(infer_group_identity_from_path(Path("/lib/Will Wight/Library/Book 1")), ("Will Wight", ""))

    def test_something_that_does_not_look_like_a_person_is_not_an_author(self):
        self.assertEqual(infer_group_identity_from_path(Path("/lib/12345 Stuff/Cradle/Book 1"))[0], "")


class CleanGroupFolderTitleTests(unittest.TestCase):
    def test_leading_sequence_and_trailing_author_are_removed(self):
        self.assertEqual(clean_group_folder_title("01 - Unsouled - Will Wight", "Will Wight"), "Unsouled")
        self.assertEqual(clean_group_folder_title("Unsouled by Will Wight", "Will Wight"), "Unsouled")

    def test_a_title_without_noise_is_unchanged(self):
        self.assertEqual(clean_group_folder_title("Unsouled", ""), "Unsouled")
        self.assertEqual(clean_group_folder_title("Unsouled", "Will Wight"), "Unsouled")

    def test_the_author_is_only_removed_from_the_end(self):
        self.assertEqual(clean_group_folder_title("Will Wight Presents Unsouled", "Will Wight"), "Will Wight Presents Unsouled")


if __name__ == "__main__":
    unittest.main()
