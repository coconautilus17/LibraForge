"""derive_manual_review_items builds the Manual Review queue from a finished
fixer run: which books are listed, with which short reasons, and in what order.
Intentional skips must NOT appear."""
import unittest

from app.main import derive_manual_review_items as derive


def row(path, title=""):
    return {"path": path, "title": title}


class DeriveManualReviewTests(unittest.TestCase):
    def derive(self, files_by_category=None, stats=None):
        return derive(stats or {}, files_by_category or {})

    def reasons(self, files_by_category=None, stats=None):
        return {item["path"]: item["reasons"] for item in self.derive(files_by_category, stats)}

    def test_each_category_adds_its_own_label(self):
        got = self.reasons({"mode:none": [row("/a")], "mode:series_only": [row("/b")], "review:duration-tiebreak": [row("/c")],
                            "status:manual_applied": [row("/d")]})
        self.assertEqual(got, {"/a": ["mode:none"], "/b": ["mode:series_only"], "/c": ["duration tie-break"], "/d": ["manually applied"]})

    def test_skip_reasons_are_mapped_to_short_labels(self):
        cases = {
            "duplicate Audible ASIN B0X in series": "asin conflict",
            "skipped: ASIN conflict with another book": "asin conflict",
            "no usable Audible match": "no match",
            "score below minimum (0.5)": "low score",
            "missing title or author": "missing metadata",
            "match marked unsafe": "unsafe match",
            "no editable metadata action": "unsafe match",
            "no useful embedded metadata": "no metadata",
            "something unforeseen": "status:skipped",
            "": "status:skipped",
        }
        for reason, label in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(self.reasons({"status:skipped": [row("/a", reason)]}), {"/a": [label]})

    def test_large_duration_items_carry_the_threshold_and_the_difference(self):
        got = self.derive({}, {"large_duration_threshold": 12.5, "large_duration_items": [{"path": "/a", "diff_percent": 33.3}]})
        self.assertEqual(got, [{"path": "/a", "reasons": ["duration>12.5%"], "diff_percent": 33.3}])

if __name__ == "__main__":
    unittest.main()
