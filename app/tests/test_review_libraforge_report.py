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

    def test_present_series_is_not_flagged(self):
        item = self._base_item()

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
