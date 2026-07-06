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


if __name__ == "__main__":
    unittest.main()
