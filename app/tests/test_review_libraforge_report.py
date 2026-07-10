import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT_PATH = ROOT / "scripts" / "review-libraforge-report.py"
SPEC = importlib.util.spec_from_file_location("review_libraforge_report", SCRIPT_PATH)
REVIEW = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = REVIEW
SPEC.loader.exec_module(REVIEW)


def make_args():
    return REVIEW.parse_args(["dummy-report.json"])


class ReviewMetadataItemMissingFieldsTests(unittest.TestCase):
    def _base_item(self, **overrides):
        item = {
            "status": "matched",
            "write_action": "would_write",
            "mode": "full",
            "duration_status": "perfect",
            "score": 0.95,
            "local": {"title": "Metal Mage 15", "author": "Eric Vall"},
            "match": {"title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage"},
        }
        item.update(overrides)
        return item

    def test_missing_series_is_flagged(self):
        # This is a correct match, just missing series -- from bad source
        # tagging or the data never existing in the first place. False
        # positives here are fine (easy to dismiss in review).
        item = self._base_item(match={"title": "Metal Mage 15", "author": "Eric Vall", "series": ""})

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_series", codes)

    def test_real_local_series_with_no_match_series_is_not_flagged(self):
        # report_items' local.series is now real embedded-tag data (the fixer
        # preserves it as "tag_series" before any path/folder-name override
        # can replace the search-clue "series" -- see
        # build_search_clues_from_file). If the book genuinely has a series
        # locally and the confirmed match just didn't corroborate it, that's
        # fine and must NOT be flagged: the match not listing a series is not
        # the same as the book having no series.
        item = self._base_item(
            local={"title": "Pocket Dungeon 4", "author": "Eric Vall", "series": "Pocket Dungeon"},
            match={"title": "Pocket Dungeon 4", "author": "Eric Vall", "series": ""},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNone(result)

    def test_no_series_anywhere_is_flagged(self):
        item = self._base_item(
            local={"title": "Pocket Dungeon 4", "author": "Eric Vall", "series": ""},
            match={"title": "Pocket Dungeon 4", "author": "Eric Vall", "series": ""},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_series", codes)

    def test_unmatched_item_with_no_local_series_is_flagged(self):
        # A cleaner completeness picture wants every book with no series
        # identified anywhere, including ones that never matched at all --
        # not just matched/would-write items.
        item = self._base_item(
            status="skipped",
            write_action="write_skipped",
            local={"title": "Some Book", "author": "Eric Vall", "series": ""},
            match={},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertEqual(codes, {"missing_series"})

    def test_unmatched_item_with_real_local_series_is_not_flagged(self):
        item = self._base_item(
            status="skipped",
            write_action="write_skipped",
            local={"title": "Some Book", "author": "Eric Vall", "series": "Some Series"},
            match={},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNone(result)

    def test_present_series_is_not_flagged(self):
        item = self._base_item()

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNone(result)

    def test_missing_series_flagged_even_when_smart_skipped(self):
        # missing_series describes the book's current state, not the risk of
        # a fresh write -- it must fire even when write_action is not
        # "would_write" (e.g. smart-skipped because an earlier run already
        # wrote this same incomplete match, so there's nothing new to write
        # this time). Confirmed against a real report: 6 of 9 items with no
        # series on the confirmed match were smart-skipped and were being
        # silently excluded entirely before this fix.
        item = self._base_item(
            write_action="smart_skipped",
            match={"title": "Metal Mage 15", "author": "Eric Vall", "series": ""},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertEqual(codes, {"missing_series"})

    def test_mismatch_checks_do_not_fire_when_not_would_write(self):
        # Everything except missing_title/author/series is specifically about
        # the risk of a fresh write this run -- these must stay gated.
        item = self._base_item(
            write_action="smart_skipped",
            score=0.1,
            local={"title": "Totally Different Title", "author": "Eric Vall"},
            match={"title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage"},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNone(result)

    def test_missing_title_and_author_flagged(self):
        item = self._base_item(
            local={"title": "", "author": ""},
            match={"title": "", "author": "", "series": "Metal Mage"},
        )

        result = REVIEW.review_metadata_item(item, make_args())

        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_title", codes)
        self.assertIn("missing_author", codes)

    def test_skipped_item_is_not_reviewed(self):
        item = self._base_item(write_action="write_skipped")

        result = REVIEW.review_metadata_item(item, make_args())

        self.assertIsNone(result)


class ReviewOrganizerItemMissingSeriesTests(unittest.TestCase):
    def test_missing_series_is_flagged(self):
        item = {
            "title": "Metal Mage 15", "author": "Eric Vall", "series": "",
            "number": "15", "source": "/lib/Metal Mage 15.m4b", "target": "/lib/Eric Vall/Metal Mage 15",
        }

        result = REVIEW.review_organizer_item(item, make_args())

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_series", codes)

    def test_present_series_not_flagged_for_series(self):
        item = {
            "title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage",
            "number": "15", "source": "/lib/Metal Mage 15.m4b", "target": "/lib/Eric Vall/Metal Mage/Book 15",
        }

        result = REVIEW.review_organizer_item(item, make_args())

        self.assertIsNone(result)


class SplitTitleBaseAndNumberTests(unittest.TestCase):
    def test_splits_trailing_number(self):
        self.assertEqual(REVIEW.split_title_base_and_number("Dungeon Core 2"), ("Dungeon Core", "2"))

    def test_no_trailing_number_returns_whole_title(self):
        self.assertEqual(REVIEW.split_title_base_and_number("Dungeon Core"), ("Dungeon Core", ""))

    def test_number_must_be_a_separate_token(self):
        # "1% Lifesteal" must not be split -- the leading "1" isn't a
        # trailing sequence number and isn't even at the end of the string.
        self.assertEqual(REVIEW.split_title_base_and_number("1% Lifesteal"), ("1% Lifesteal", ""))

    def test_decimal_sequence_number(self):
        self.assertEqual(REVIEW.split_title_base_and_number("Side Quest 2.5"), ("Side Quest", "2.5"))


class MajorityAuthorAndNoteTests(unittest.TestCase):
    def test_all_same_author_has_no_note(self):
        members = [{"author": "Eric Vall"}, {"author": "Eric Vall"}]
        author, note = REVIEW._majority_author_and_note(members)
        self.assertEqual(author, "Eric Vall")
        self.assertIsNone(note)

    def test_differing_author_produces_a_note(self):
        members = [{"author": "Eric Vall"}, {"author": "Eric Vall"}, {"author": "Logan Jacobs"}]
        author, note = REVIEW._majority_author_and_note(members)
        self.assertEqual(author, "Eric Vall")
        self.assertIn("2 of 3 share author", note)
        self.assertIn("Logan Jacobs", note)

    def test_no_authors_at_all(self):
        author, note = REVIEW._majority_author_and_note([{"author": ""}, {"author": ""}])
        self.assertEqual(author, "")
        self.assertIsNone(note)


class GroupMissingSeriesByTitlePatternTests(unittest.TestCase):
    def _item(self, path, title, author, series="", **overrides):
        item = {
            "path": path,
            "status": "matched",
            "local": {"title": title, "author": author, "series": series},
            "match": {"title": title, "author": author, "series": series},
        }
        item.update(overrides)
        return item

    def test_groups_numbered_siblings_with_no_series(self):
        items = [
            self._item("/lib/Dungeon Core 2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/Dungeon Core 3.m4b", "Dungeon Core 3", "Eric Vall"),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["base_title"], "Dungeon Core")
        self.assertEqual(group["suggested_series"], "Dungeon Core")
        self.assertEqual(group["suggested_author"], "Eric Vall")
        paths = {m["path"] for m in group["members"]}
        self.assertEqual(paths, {"/lib/Dungeon Core 2.m4b", "/lib/Dungeon Core 3.m4b"})

    def test_single_book_is_not_a_group(self):
        items = [self._item("/lib/Standalone.m4b", "Standalone Book", "Someone")]
        self.assertEqual(REVIEW.group_missing_series_by_title_pattern(items), [])

    def test_books_with_a_series_already_are_excluded(self):
        items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall", series="Dungeon Core"),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        self.assertEqual(groups, [])

    def test_opener_with_no_number_joins_and_is_flagged(self):
        items = [
            self._item("/lib/A1.m4b", "Dungeon Core", "Eric Vall"),
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        self.assertEqual(len(groups), 1)
        opener = next(m for m in groups[0]["members"] if m["path"] == "/lib/A1.m4b")
        self.assertEqual(opener["flag"], "missing_number")
        self.assertEqual(opener["sequence"], "")

    def test_differing_author_is_flagged_but_still_grouped(self):
        items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
            self._item("/lib/A4.m4b", "Dungeon Core 4", "Logan Jacobs"),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        group = groups[0]
        self.assertEqual(len(group["members"]), 3)
        odd_one = next(m for m in group["members"] if m["path"] == "/lib/A4.m4b")
        self.assertEqual(odd_one["flag"], "author_differs")
        self.assertIn("Eric Vall", group["author_note"])
        self.assertIn("Logan Jacobs", group["author_note"])

    def test_all_same_author_has_no_author_note(self):
        items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
        ]
        self.assertIsNone(REVIEW.group_missing_series_by_title_pattern(items)[0]["author_note"])

    def test_omnibus_joins_group_and_is_flagged_instead_of_author_differs(self):
        # Reuses is_multi_book() -- keyword in the title is enough on its own.
        items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
            self._item(
                "/lib/AOmni.m4b", "Dungeon Core: The Complete Series", "Someone Else",
            ),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        group = groups[0]
        omni = next(m for m in group["members"] if m["path"] == "/lib/AOmni.m4b")
        self.assertEqual(omni["flag"], "omnibus")

    def test_title_that_normalizes_to_empty_does_not_crash_grouping(self):
        # A title like "A" normalizes to an empty string (normalize() strips
        # stopwords and non-alphanumeric characters) -- this must not crash
        # the whole grouping pass for the entire report.
        items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
            self._item("/lib/Weird.m4b", "A", "Someone"),
        ]
        groups = REVIEW.group_missing_series_by_title_pattern(items)
        # The real group must still be found; the garbage-titled book must
        # not appear in it (it has nothing to group with).
        self.assertEqual(len(groups), 1)
        paths = {m["path"] for m in groups[0]["members"]}
        self.assertEqual(paths, {"/lib/A2.m4b", "/lib/A3.m4b"})


class GroupExistingSeriesByNormalizedTagTests(unittest.TestCase):
    def _item(self, path, title, author, series, **overrides):
        item = {
            "path": path,
            "status": "matched",
            "local": {"title": title, "author": author, "series": series},
            "match": {"title": title, "author": author, "series": series},
        }
        item.update(overrides)
        return item

    def test_groups_by_normalized_series_despite_raw_variants(self):
        items = [
            self._item("/lib/B1.m4b", "Dungeon Core", "Eric Vall", "Dungeon Core "),
            self._item("/lib/B2.m4b", "Dungeon Core 2", "Eric Vall", "Dungeon Core, Book 2"),
            self._item("/lib/B3.m4b", "Dungeon Core 3", "Eric Vall", "Dungeon Core"),
        ]
        groups = REVIEW.group_existing_series_by_normalized_tag(items, claimed_paths=set())
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["pass"], 2)
        self.assertEqual(group["suggested_series"], "Dungeon Core")
        self.assertIn("Dungeon Core ", group["context_note"])
        self.assertIn("Dungeon Core, Book 2", group["context_note"])

    def test_skips_paths_already_claimed_by_pass_one(self):
        items = [
            self._item("/lib/B1.m4b", "Dungeon Core", "Eric Vall", "Dungeon Core"),
            self._item("/lib/B2.m4b", "Dungeon Core 2", "Eric Vall", "Dungeon Core"),
        ]
        groups = REVIEW.group_existing_series_by_normalized_tag(items, claimed_paths={"/lib/B2.m4b"})
        self.assertEqual(groups, [])  # only one un-claimed member left -- not a group

    def test_single_book_is_not_a_group(self):
        items = [self._item("/lib/B1.m4b", "Solo", "Someone", "Solo Series")]
        self.assertEqual(REVIEW.group_existing_series_by_normalized_tag(items, set()), [])

    def test_works_for_non_numbered_series_names(self):
        items = [
            self._item("/lib/C1.m4b", "The Silent Deep", "A. Author", "Chronicles of the Deep"),
            self._item("/lib/C2.m4b", "The Rising Tide", "A. Author", "Chronicles of the Deep, Book 2"),
        ]
        groups = REVIEW.group_existing_series_by_normalized_tag(items, set())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["suggested_series"], "Chronicles of the Deep")

    def test_suggested_series_strips_suffix_regardless_of_input_order(self):
        # Put the suffixed variant first -- the old buggy code picked
        # whichever raw variant appeared first when all counts tied at 1,
        # which could leak ", Book 2" into the suggestion.
        items = [
            self._item("/lib/D2.m4b", "Dungeon Core 2", "Eric Vall", "Dungeon Core, Book 2"),
            self._item("/lib/D1.m4b", "Dungeon Core", "Eric Vall", "Dungeon Core "),
            self._item("/lib/D3.m4b", "Dungeon Core 3", "Eric Vall", "Dungeon Core"),
        ]
        groups = REVIEW.group_existing_series_by_normalized_tag(items, claimed_paths=set())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["suggested_series"], "Dungeon Core")

    def test_suggested_series_strips_stacked_suffixes(self):
        # A raw tag can carry BOTH a "Series" word and a ", Book N" suffix
        # stacked together -- both must be stripped so this variant still
        # collapses into the same canonical bucket as a plain "Dungeon Core".
        # Two members carry the stacked suffix (vote weight >= the plain
        # variant) so this test only passes if stripping is actually
        # complete -- with incomplete (single-pass) stripping the stacked
        # variant would tie or win the vote as "Dungeon Core Series"
        # instead of collapsing to "Dungeon Core".
        items = [
            self._item("/lib/E1.m4b", "Dungeon Core", "Eric Vall", "Dungeon Core Series, Book 2"),
            self._item("/lib/E2.m4b", "Dungeon Core 2", "Eric Vall", "Dungeon Core Series, Book 3"),
            self._item("/lib/E3.m4b", "Dungeon Core 3", "Eric Vall", "Dungeon Core"),
        ]
        groups = REVIEW.group_existing_series_by_normalized_tag(items, claimed_paths=set())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["suggested_series"], "Dungeon Core")


class AddSeriesGroupSuspectsTests(unittest.TestCase):
    def _item(self, path, title, author, series="", genre="", narrator="", **overrides):
        item = {
            "path": path,
            "status": "matched",
            "local": {"title": title, "author": author, "series": series, "genre": genre, "narrator": narrator},
            "match": {"title": title, "author": author, "series": series, "genre": genre, "narrator": narrator},
        }
        item.update(overrides)
        return item

    def test_pass_one_group_becomes_a_series_group_suspect(self):
        report_items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
        ]
        suspects: list = []
        REVIEW.add_series_group_suspects(suspects, report_items, make_args())
        self.assertEqual(len(suspects), 1)
        suspect = suspects[0]
        self.assertEqual(suspect["status"], "series_group")
        self.assertEqual(suspect["reasons"][0]["code"], "series_group_missing")
        self.assertEqual(set(suspect["related_paths"]), {"/lib/A2.m4b", "/lib/A3.m4b"})

    def test_pass_two_group_becomes_a_series_group_suspect_with_different_code(self):
        report_items = [
            self._item("/lib/B1.m4b", "Dungeon Core", "Eric Vall", series="Dungeon Core"),
            self._item("/lib/B2.m4b", "Dungeon Core 2", "Eric Vall", series="Dungeon Core, Book 2"),
        ]
        suspects: list = []
        REVIEW.add_series_group_suspects(suspects, report_items, make_args())
        self.assertEqual(suspects[0]["reasons"][0]["code"], "series_group_normalize")

    def test_genre_and_narrator_are_deduped_across_tagged_siblings(self):
        # Two books with no series (the group) plus one already-tagged
        # sibling that supplies genre/narrator for the suggestion.
        report_items = [
            self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
            self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
            self._item(
                "/lib/A1.m4b", "Dungeon Core 1", "Eric Vall", series="Dungeon Core",
                genre="LitRPG", narrator="JD Tanner",
            ),
            self._item(
                "/lib/A4.m4b", "Dungeon Core 4", "Eric Vall", series="Dungeon Core",
                genre="Fantasy", narrator="Sierra Taft",
            ),
        ]
        suspects: list = []
        REVIEW.add_series_group_suspects(suspects, report_items, make_args())
        pass_one = next(s for s in suspects if s["reasons"][0]["code"] == "series_group_missing")
        evidence = pass_one["reasons"][0]["evidence"]
        self.assertEqual(evidence["suggested_genre"], "LitRPG, Fantasy")
        self.assertEqual(evidence["suggested_narrator"], "JD Tanner, Sierra Taft")
        sibling_paths = {s["path"] for s in evidence["tagged_siblings"]}
        self.assertEqual(sibling_paths, {"/lib/A1.m4b", "/lib/A4.m4b"})

    def test_no_series_groups_when_nothing_qualifies(self):
        report_items = [self._item("/lib/Solo.m4b", "Standalone", "Someone")]
        suspects: list = []
        REVIEW.add_series_group_suspects(suspects, report_items, make_args())
        self.assertEqual(suspects, [])

    def test_extract_suspects_includes_series_groups(self):
        report = {
            "report_items": [
                self._item("/lib/A2.m4b", "Dungeon Core 2", "Eric Vall"),
                self._item("/lib/A3.m4b", "Dungeon Core 3", "Eric Vall"),
            ],
        }
        suspects, _ = REVIEW.extract_suspects(report, make_args())
        self.assertTrue(any(s["status"] == "series_group" for s in suspects))


if __name__ == "__main__":
    unittest.main()
