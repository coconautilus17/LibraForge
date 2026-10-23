"""The Metadata Fixer's review decisions: why a selected match is flagged for a
human, and how several books matched to one ASIN are separated into the one that
is right and the ones that are not."""
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

FIXER = load_script("fixer_review_decisions", "audible-metadata-fixer-v5.py")


class SelectedMatchReasonTests(unittest.TestCase):
    def reasons(self, metadata=None, clues=None, score=0.9, threshold=10.0):
        return FIXER.selected_match_review_reasons({"edit_mode": "full", **(metadata or {})}, clues or {}, score, threshold)

    def test_series_only_and_unusable_modes_each_have_their_own_reason(self):
        self.assertEqual(self.reasons({"edit_mode": "series_only"}), ["series-only match: full metadata rewrite not considered safe"])
        self.assertEqual(self.reasons({"edit_mode": "none"}), ["unsafe match: no editable metadata action"])
        self.assertEqual(FIXER.selected_match_review_reasons({}, {}, 0.9, 10.0), ["unsafe match: no editable metadata action"])
        self.assertEqual(FIXER.selected_match_review_reasons({"edit_mode": None}, {}, 0.9, 10.0), ["unsafe match: no editable metadata action"])

    def test_several_reasons_come_in_a_fixed_order_without_duplicates(self):
        got = self.reasons({"edit_mode": "series_only", "duration": {"diff_percent": 50}, "audible_sequence": "5"},
                           {"book_number": "3", "book_number_source": "title"}, score=0.5)
        self.assertEqual([r.split(":")[0].split(" ")[0] for r in got], ["series-only", "duration", "local/Audible", "low"])

class AsinConflictTests(unittest.TestCase):
    def item(self, name, series, asin, local, audible, path_number=None):
        folder = f"/lib/{series}/Book {path_number} - X" if path_number is not None else f"/lib/{series}"
        return FIXER.ItemResult(index=1, file_path=Path(folder) / f"{name}.m4b", display_path=Path(folder) / f"{name}.m4b",
                                status="matched", metadata={"series": series, "asin": asin, "audible_sequence": audible},
                                clues={"book_number": local})

    def test_a_clues_match_without_any_folder_number_is_trusted(self):
        a = self.item("a", "Cradle", "B0X", "6", "6")
        b = self.item("b", "Cradle", "B0X", "4", "6")
        FIXER.detect_asin_conflicts([a, b])
        self.assertEqual((a.asin_conflict, b.asin_conflict), (False, True))

    def test_unmatched_items_and_items_without_a_series_or_asin_are_ignored(self):
        skipped = self.item("a", "Cradle", "B0X", "4", "6")
        skipped.status = "skipped"
        no_series = self.item("b", "", "B0X", "4", "6")
        no_asin = self.item("c", "Cradle", "", "4", "6")
        no_meta = self.item("d", "Cradle", "B0X", "4", "6")
        no_meta.metadata = None
        other = self.item("e", "Cradle", "B0X", "4", "6")
        FIXER.detect_asin_conflicts([skipped, no_series, no_asin, no_meta, other])
        self.assertFalse(any(r.asin_conflict for r in (skipped, no_series, no_asin, no_meta, other)))

if __name__ == "__main__":
    unittest.main()
