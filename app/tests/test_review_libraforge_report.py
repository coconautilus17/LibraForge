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


class SplitTitleAndTrailingNumberTests(unittest.TestCase):
    def test_splits_base_and_number(self):
        self.assertEqual(
            REVIEW.split_title_and_trailing_number("Metal Mage 15"),
            ("metal mage", "15"),
        )

    def test_no_trailing_number_returns_none(self):
        self.assertIsNone(REVIEW.split_title_and_trailing_number("Some Standalone Title"))

    def test_blank_title_returns_none(self):
        self.assertIsNone(REVIEW.split_title_and_trailing_number(""))


class PotentialSeriesSiblingTests(unittest.TestCase):
    def test_finds_siblings_by_same_author_and_title_base(self):
        entries = [
            ("eric vall", "metal mage", "13", "Metal Mage 13"),
            ("eric vall", "metal mage", "14", "Metal Mage 14"),
        ]
        index = REVIEW.build_series_sibling_index(entries)

        siblings = REVIEW.find_potential_series_siblings(index, "Eric Vall", "Metal Mage 15")

        self.assertEqual(len(siblings), 2)
        self.assertEqual({s["number"] for s in siblings}, {"13", "14"})

    def test_no_siblings_for_different_author(self):
        entries = [("someone else", "metal mage", "13", "Metal Mage 13")]
        index = REVIEW.build_series_sibling_index(entries)

        siblings = REVIEW.find_potential_series_siblings(index, "Eric Vall", "Metal Mage 15")

        self.assertEqual(siblings, [])

    def test_excludes_own_number(self):
        entries = [("eric vall", "metal mage", "15", "Metal Mage 15 (duplicate rip)")]
        index = REVIEW.build_series_sibling_index(entries)

        siblings = REVIEW.find_potential_series_siblings(index, "Eric Vall", "Metal Mage 15")

        self.assertEqual(siblings, [])


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

    def test_missing_series_flagged_with_sibling_evidence(self):
        item = self._base_item(match={"title": "Metal Mage 15", "author": "Eric Vall", "series": ""})
        sibling_index = REVIEW.build_series_sibling_index([
            ("eric vall", "metal mage", "13", "Metal Mage 13"),
            ("eric vall", "metal mage", "14", "Metal Mage 14"),
        ])

        result = REVIEW.review_metadata_item(item, make_args(), sibling_index)

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_series", codes)
        missing_series_reason = next(r for r in result["reasons"] if r["code"] == "missing_series")
        self.assertEqual(len(missing_series_reason["evidence"]["potential_series_siblings"]), 2)

    def test_missing_series_flagged_without_sibling_evidence(self):
        # False positives here are fine (easy to dismiss in review) -- a
        # missing series still gets flagged even with no sibling evidence.
        item = self._base_item(match={"title": "A Standalone Book", "author": "Eric Vall", "series": ""})

        result = REVIEW.review_metadata_item(item, make_args(), {})

        self.assertIsNotNone(result)
        missing_series_reason = next(r for r in result["reasons"] if r["code"] == "missing_series")
        self.assertNotIn("potential_series_siblings", missing_series_reason["evidence"])

    def test_present_series_is_not_flagged(self):
        item = self._base_item()

        result = REVIEW.review_metadata_item(item, make_args(), {})

        self.assertIsNone(result)

    def test_missing_title_and_author_flagged(self):
        item = self._base_item(
            local={"title": "", "author": ""},
            match={"title": "", "author": "", "series": "Metal Mage"},
        )

        result = REVIEW.review_metadata_item(item, make_args(), {})

        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_title", codes)
        self.assertIn("missing_author", codes)

    def test_skipped_item_is_not_reviewed(self):
        item = self._base_item(write_action="write_skipped")

        result = REVIEW.review_metadata_item(item, make_args(), {})

        self.assertIsNone(result)


class ReviewOrganizerItemMissingSeriesTests(unittest.TestCase):
    def test_missing_series_flagged_with_sibling_evidence(self):
        item = {
            "title": "Metal Mage 15", "author": "Eric Vall", "series": "",
            "number": "15", "source": "/lib/Metal Mage 15.m4b", "target": "/lib/Eric Vall/Metal Mage 15",
        }
        sibling_index = REVIEW.build_series_sibling_index([
            ("eric vall", "metal mage", "13", "Metal Mage 13"),
            ("eric vall", "metal mage", "14", "Metal Mage 14"),
        ])

        result = REVIEW.review_organizer_item(item, make_args(), sibling_index)

        self.assertIsNotNone(result)
        codes = {r["code"] for r in result["reasons"]}
        self.assertIn("missing_series", codes)

    def test_present_series_not_flagged_for_series(self):
        item = {
            "title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage",
            "number": "15", "source": "/lib/Metal Mage 15.m4b", "target": "/lib/Eric Vall/Metal Mage/Book 15",
        }

        result = REVIEW.review_organizer_item(item, make_args(), {})

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
