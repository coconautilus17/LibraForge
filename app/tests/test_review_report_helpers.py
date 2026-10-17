"""Direct tests of the comparison and classification helpers in
scripts/review-libraforge-report.py. The review script decides which matches a
human has to look at, so each helper's exact output matters."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("review_libraforge_report_helpers", ROOT / "scripts" / "review-libraforge-report.py")
REVIEW = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = REVIEW
SPEC.loader.exec_module(REVIEW)


class SimilarityTests(unittest.TestCase):
    def test_equal_after_normalising_is_one_and_containment_is_point_nine_two(self):
        self.assertEqual(REVIEW.similarity("The Book", "the book"), 1.0)
        self.assertEqual(REVIEW.similarity("Book", "The Big Book"), 0.92)

    def test_two_empty_values_are_identical_and_one_empty_value_is_unrelated(self):
        self.assertEqual(REVIEW.similarity("", ""), 1.0)
        self.assertEqual(REVIEW.similarity("Alpha", ""), 0.0)
        self.assertEqual(REVIEW.similarity("", "Alpha"), 0.0)

    def test_otherwise_it_is_the_sequence_matcher_ratio(self):
        self.assertAlmostEqual(REVIEW.similarity("Alpha", "Beta"), 0.222, places=3)

    def test_series_similarity_ignores_book_qualifiers(self):
        self.assertEqual(REVIEW.series_similarity("Cradle, Book 3", "Cradle"), 1.0)
        self.assertEqual(REVIEW.series_similarity("", ""), 1.0)
        self.assertEqual(REVIEW.series_similarity("Cradle", ""), 0.0)
        self.assertEqual(REVIEW.series_similarity("Cradle Saga", "Cradle"), 0.92)

    def test_the_subtitle_rescues_only_an_essentially_unrelated_title(self):
        self.assertAlmostEqual(REVIEW.title_similarity("Dragon Born 3", "Totally Different", "Dragon Born, Book 3"), 0.8387, places=3)
        self.assertEqual(REVIEW.title_similarity("Dragon Born 3", "Dragon Born 3 Extended", "Zzz"), 0.92)
        self.assertEqual(REVIEW.title_similarity("Qqq", "Zzzzz", "Qqq"), 1.0)
        self.assertEqual(REVIEW.title_similarity("Qqq", "Qqq Zzz", "Qqq"), 0.92)

    def test_a_worse_subtitle_does_not_lower_the_score(self):
        self.assertAlmostEqual(REVIEW.title_similarity("Alpha", "Beta", "Zzzz"), REVIEW.similarity("Alpha", "Beta"), places=6)


class NumberExtractionTests(unittest.TestCase):
    def test_normalize_number_drops_zero_padding_and_trailing_decimal_zeros(self):
        for raw, expected in (("3", "3"), ("03", "3"), ("1.50", "1.5"), ("2.0", "2"), ("Book 7.25", "7.25"), ("0.5", "0.5"),
                              ("10", "10"), ("abc", ""), ("", ""), (None, "")):
            with self.subTest(raw=raw):
                self.assertEqual(REVIEW.normalize_number(raw), expected)

    def test_strong_numbers_come_from_book_volume_v_and_hash_labels(self):
        for raw, expected in (("Cradle Book 3", "3"), ("Vol. 2", "2"), ("V4", "4"), ("#5", "5"), ("Book 7.50", "7.5")):
            with self.subTest(raw=raw):
                self.assertEqual(REVIEW.extract_strong_number_from_text(raw), expected)

    def test_ranges_and_plain_text_are_not_strong_numbers(self):
        for raw in ("#5-6", "Books 1-3", "Plain", "", None):
            with self.subTest(raw=raw):
                self.assertEqual(REVIEW.extract_strong_number_from_text(raw), "")

    def test_a_series_suffix_number_needs_the_series_prefix_and_one_or_two_digits(self):
        for value, series, expected in (("Cradle 3", "Cradle", "3"), ("Cradle 12", "Cradle", "12"), ("Cradle 123", "Cradle", ""),
                                        ("Cradle 2016", "Cradle", ""), ("Cradle", "Cradle", ""), ("Other 3", "Cradle", ""),
                                        ("Cradle 3", "", ""), ("", "Cradle", "")):
            with self.subTest(value=value, series=series):
                self.assertEqual(REVIEW.extract_series_suffix_number(value, series), expected)

    def test_visible_numbers_are_collected_per_source_with_series_suffixes_only_for_local_sources(self):
        item = {"path": "/lib/Will Wight/Cradle 2/Cradle 2.m4b"}
        local = {"title": "Cradle 2", "series": "Cradle"}
        match = {"title": "Cradle 5", "subtitle": "Book 7", "series": "Cradle"}
        got = REVIEW.extract_any_visible_number(item, local, match)
        self.assertEqual(got["local_title"], "2")
        self.assertEqual(got["path_parent"], "2")
        self.assertEqual(got["match_subtitle"], "7")
        self.assertNotIn("match_title", got)          # "Cradle 5" is a suffix number, honoured only locally
        self.assertNotIn("path_grandparent", got)

    def test_a_strong_number_beats_a_series_suffix_in_the_same_source(self):
        got = REVIEW.extract_any_visible_number({}, {"title": "Cradle Book 4", "series": "Cradle"}, {})
        self.assertEqual(got, {"local_title": "4"})


class MultiBookTests(unittest.TestCase):
    def test_range_keywords_in_any_title_or_subtitle_mark_a_multi_book_item(self):
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Books 1-3"}))
        self.assertTrue(REVIEW.is_multi_book({"title": "Omnibus"}, {}))
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Y", "subtitle": "Box Set"}))

    def test_a_range_sequence_marks_it_and_a_single_number_does_not(self):
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Y", "sequence": "1-3"}))
        self.assertFalse(REVIEW.is_multi_book({"title": "X"}, {"title": "Y", "sequence": "3"}))

    def test_an_omnibus_container_folder_in_the_path_marks_it(self):
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Y"}, "/lib/Secret Alchemist (Book 1 & 2)/x.m4b"))
        self.assertFalse(REVIEW.is_multi_book({"title": "X"}, {"title": "Y"}, "/lib/Plain Folder/x.m4b"))

    def test_nothing_suspicious_is_a_single_book(self):
        self.assertFalse(REVIEW.is_multi_book({"title": "X"}, {}))
        self.assertFalse(REVIEW.is_multi_book({}, {}))


class SeverityTests(unittest.TestCase):
    def test_ranks_ascend_and_unknown_is_info(self):
        ranks = [REVIEW.severity_rank(v) for v in ("info", "low", "medium", "high", "critical")]
        self.assertEqual(ranks, [0, 1, 2, 3, 4])
        self.assertEqual(REVIEW.severity_rank("weird"), 0)

    def test_max_severity_picks_the_highest_and_defaults_missing_to_info(self):
        self.assertEqual(REVIEW.max_severity([]), "none")
        self.assertEqual(REVIEW.max_severity([{"severity": "low"}, {"severity": "critical"}, {"severity": "medium"}]), "critical")
        self.assertEqual(REVIEW.max_severity([{}]), "info")
        self.assertEqual(REVIEW.max_severity([{"severity": "medium"}, {}]), "medium")


class RecommendationTests(unittest.TestCase):
    def rec(self, *codes):
        return REVIEW.recommendation_for_reasons([{"code": c} for c in codes])

    def test_each_reason_family_has_its_recommendation(self):
        for codes, expected in ((("failed_item",), "manual_lookup"), (("no_match",), "manual_lookup"),
                                (("unsafe_match",), "manual_lookup"), (("score_below_minimum",), "manual_lookup"),
                                (("non_matched_status",), "manual_lookup"),
                                (("sequence_conflict",), "verify_sequence_before_apply"),
                                (("visible_number_conflict",), "verify_sequence_before_apply"),
                                (("title_number_conflict",), "verify_sequence_before_apply"),
                                (("provider_missing_sequence",), "verify_sequence_before_apply"),
                                (("title_mismatch",), "compare_against_runner_up_or_search_manually"),
                                (("series_mismatch",), "compare_against_runner_up_or_search_manually"),
                                (("author_mismatch",), "compare_against_runner_up_or_search_manually"),
                                (("series_only_mode",), "verify_metadata_completeness"),
                                (("missing_title",), "verify_metadata_completeness"),
                                (("missing_author",), "verify_metadata_completeness"),
                                (("missing_series",), "verify_metadata_completeness"),
                                (("duplicate_asin",), "check_duplicate_or_alternate_edition"),
                                (("duplicate_local_identity",), "check_duplicate_or_alternate_edition"),
                                (("something_else",), "manual_review"), ((), "manual_review")):
            with self.subTest(codes=codes):
                self.assertEqual(self.rec(*codes), expected)

    def test_the_most_urgent_family_wins_when_several_apply(self):
        self.assertEqual(self.rec("sequence_conflict", "no_match"), "manual_lookup")
        self.assertEqual(self.rec("title_mismatch", "sequence_conflict"), "verify_sequence_before_apply")
        self.assertEqual(self.rec("missing_title", "title_mismatch"), "compare_against_runner_up_or_search_manually")
        self.assertEqual(self.rec("duplicate_asin", "missing_title"), "verify_metadata_completeness")


class ReportKindTests(unittest.TestCase):
    def test_the_explicit_kind_wins(self):
        self.assertEqual(REVIEW.infer_report_kind({"stats": {"kind": "organizer"}}), "organizer")
        self.assertEqual(REVIEW.infer_report_kind({"stats": {"kind": "fixer"}}), "metadata_fixer")
        self.assertEqual(REVIEW.infer_report_kind({"stats": {"kind": "metadata_fixer", "move_items": []}}), "metadata_fixer")

    def test_otherwise_the_report_shape_decides(self):
        self.assertEqual(REVIEW.infer_report_kind({"stats": {"move_items": []}}), "organizer")
        self.assertEqual(REVIEW.infer_report_kind({"report_items": [{}]}), "metadata_fixer")
        self.assertEqual(REVIEW.infer_report_kind({"items": [{}], "stats": {"mode_breakdown": {}}}), "metadata_fixer")

    def test_an_unrecognisable_report_is_unknown(self):
        self.assertEqual(REVIEW.infer_report_kind({"items": [{}]}), "unknown")
        self.assertEqual(REVIEW.infer_report_kind({"report_items": []}), "unknown")
        self.assertEqual(REVIEW.infer_report_kind({}), "unknown")


if __name__ == "__main__":
    unittest.main()
