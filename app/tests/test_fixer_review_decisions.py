"""The Metadata Fixer's review decisions: why a selected match is flagged for a
human, and how several books matched to one ASIN are separated into the one that
is right and the ones that are not."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_review_decisions", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


class SelectedMatchReasonTests(unittest.TestCase):
    def reasons(self, metadata=None, clues=None, score=0.9, threshold=10.0):
        return FIXER.selected_match_review_reasons({"edit_mode": "full", **(metadata or {})}, clues or {}, score, threshold)

    def test_a_clean_full_match_has_no_reasons(self):
        self.assertEqual(self.reasons({"duration": {"diff_percent": 5}}, {"book_number": "3", "book_number_source": "path"}), [])

    def test_series_only_and_unusable_modes_each_have_their_own_reason(self):
        self.assertEqual(self.reasons({"edit_mode": "series_only"}), ["series-only match: full metadata rewrite not considered safe"])
        self.assertEqual(self.reasons({"edit_mode": "none"}), ["unsafe match: no editable metadata action"])
        self.assertEqual(FIXER.selected_match_review_reasons({}, {}, 0.9, 10.0), ["unsafe match: no editable metadata action"])
        self.assertEqual(FIXER.selected_match_review_reasons({"edit_mode": None}, {}, 0.9, 10.0), ["unsafe match: no editable metadata action"])

    def test_a_duration_gap_is_flagged_only_above_the_threshold(self):
        self.assertEqual(self.reasons({"duration": {"diff_percent": 10}}), [])
        self.assertEqual(self.reasons({"duration": {"diff_percent": 10.1}}), ["duration differs by 10.1% from Audible"])
        self.assertEqual(self.reasons({"duration": {"diff_percent": 25}}, threshold=30), [])
        self.assertEqual(self.reasons({"duration": {}}), [])
        self.assertEqual(self.reasons({"duration": None}), [])

    def test_conflicting_sequences_name_both_numbers_and_where_the_local_one_came_from(self):
        got = self.reasons({"audible_sequence": "5"}, {"book_number": "3", "book_number_source": "path"})
        self.assertEqual(got, ["local/Audible sequence conflict: local 3 (path) vs Audible 5"])
        got = self.reasons({"sequence": "5"}, {"book_number": "3"})
        self.assertEqual(got, ["local/Audible sequence conflict: local 3 (-) vs Audible 5"])

    def test_the_audible_sequence_field_wins_over_the_written_sequence(self):
        got = self.reasons({"audible_sequence": "3", "sequence": "9"}, {"book_number": "3"})
        self.assertEqual(got, [])

    def test_equal_or_missing_sequences_are_not_a_conflict(self):
        self.assertEqual(self.reasons({"audible_sequence": "3.0"}, {"book_number": "3"}), [])
        self.assertEqual(self.reasons({}, {"book_number": "3"}), [])
        self.assertEqual(self.reasons({"audible_sequence": "5"}, {}), [])

    def test_a_score_below_the_aggressive_threshold_is_flagged(self):
        self.assertEqual(self.reasons(score=0.69), ["low match score: 0.69"])
        self.assertEqual(self.reasons(score=FIXER.AGGRESSIVE_SCORE_THRESHOLD), [])
        self.assertEqual(self.reasons(score=0.123456789), ["low match score: 0.1235"])

    def test_several_reasons_come_in_a_fixed_order_without_duplicates(self):
        got = self.reasons({"edit_mode": "series_only", "duration": {"diff_percent": 50}, "audible_sequence": "5"},
                           {"book_number": "3", "book_number_source": "title"}, score=0.5)
        self.assertEqual([r.split(":")[0].split(" ")[0] for r in got], ["series-only", "duration", "local/Audible", "low"])

    def test_appending_a_reason_twice_or_blank_is_ignored(self):
        reasons = []
        FIXER.append_unique_reason(reasons, "  same  ")
        FIXER.append_unique_reason(reasons, "same")
        FIXER.append_unique_reason(reasons, "   ")
        self.assertEqual(reasons, ["same"])


class AsinConflictTests(unittest.TestCase):
    def item(self, name, series, asin, local, audible, path_number=None):
        folder = f"/lib/{series}/Book {path_number} - X" if path_number is not None else f"/lib/{series}"
        return FIXER.ItemResult(index=1, file_path=Path(folder) / f"{name}.m4b", display_path=Path(folder) / f"{name}.m4b",
                                status="matched", metadata={"series": series, "asin": asin, "audible_sequence": audible},
                                clues={"book_number": local})

    def test_the_book_whose_numbers_agree_keeps_the_asin_and_the_others_are_flagged(self):
        right = self.item("a", "Cradle", "B0X", "6", "6", path_number=6)
        wrong = self.item("b", "Cradle", "B0X", "4", "6", path_number=4)
        FIXER.detect_asin_conflicts([right, wrong])
        self.assertFalse(right.asin_conflict)
        self.assertTrue(wrong.asin_conflict)
        self.assertEqual(wrong.review_reasons, ["duplicate Audible ASIN B0X in series 'Cradle': local book 4 matched to Audible sequence 6"])

    def test_the_folder_number_overrules_clues_that_were_corrupted_by_applied_tags(self):
        # clues say 6 (from a stale title) but the folder says Book 3: that book is not the Audible book 6
        stale = self.item("a", "Cradle", "B0X", "6", "6", path_number=3)
        right = self.item("b", "Cradle", "B0X", "6", "6", path_number=6)
        FIXER.detect_asin_conflicts([stale, right])
        self.assertTrue(stale.asin_conflict)
        self.assertFalse(right.asin_conflict)

    def test_a_clues_match_without_any_folder_number_is_trusted(self):
        a = self.item("a", "Cradle", "B0X", "6", "6")
        b = self.item("b", "Cradle", "B0X", "4", "6")
        FIXER.detect_asin_conflicts([a, b])
        self.assertEqual((a.asin_conflict, b.asin_conflict), (False, True))

    def test_a_single_book_per_asin_is_never_flagged(self):
        a = self.item("a", "Cradle", "B0X", "4", "6")
        FIXER.detect_asin_conflicts([a])
        self.assertFalse(a.asin_conflict)

    def test_different_series_or_different_asins_do_not_conflict(self):
        a = self.item("a", "Cradle", "B0X", "4", "6")
        b = self.item("b", "Dune", "B0X", "4", "6")
        c = self.item("c", "Cradle", "B0Y", "4", "6")
        FIXER.detect_asin_conflicts([a, b, c])
        self.assertEqual([a.asin_conflict, b.asin_conflict, c.asin_conflict], [False, False, False])

    def test_series_names_are_compared_ignoring_case_and_punctuation(self):
        a = self.item("a", "The Cradle Saga", "B0X", "6", "6", path_number=6)
        b = self.item("b", "the cradle  saga!", "B0X", "4", "6", path_number=4)
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

    def test_the_reason_is_not_added_twice_on_a_second_pass(self):
        a = self.item("a", "Cradle", "B0X", "6", "6", path_number=6)
        b = self.item("b", "Cradle", "B0X", "4", "6", path_number=4)
        FIXER.detect_asin_conflicts([a, b])
        FIXER.detect_asin_conflicts([a, b])
        self.assertEqual(len(b.review_reasons), 1)

    def test_an_unknown_local_number_is_shown_as_a_question_mark(self):
        a = self.item("a", "Cradle", "B0X", "6", "6", path_number=6)
        b = self.item("b", "Cradle", "B0X", "", "6")
        FIXER.detect_asin_conflicts([a, b])
        self.assertIn("local book ? matched to Audible sequence 6", b.review_reasons[0])


if __name__ == "__main__":
    unittest.main()
