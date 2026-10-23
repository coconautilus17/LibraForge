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
    def test_two_empty_values_are_identical_and_one_empty_value_is_unrelated(self):
        self.assertEqual(REVIEW.similarity("", ""), 1.0)
        self.assertEqual(REVIEW.similarity("Alpha", ""), 0.0)
        self.assertEqual(REVIEW.similarity("", "Alpha"), 0.0)

    def test_series_similarity_ignores_book_qualifiers(self):
        self.assertEqual(REVIEW.series_similarity("Cradle, Book 3", "Cradle"), 1.0)
        self.assertEqual(REVIEW.series_similarity("", ""), 1.0)
        self.assertEqual(REVIEW.series_similarity("Cradle", ""), 0.0)
        self.assertEqual(REVIEW.series_similarity("Cradle Saga", "Cradle"), 0.92)

class NumberExtractionTests(unittest.TestCase):
    def test_normalize_number_drops_zero_padding_and_trailing_decimal_zeros(self):
        for raw, expected in (("3", "3"), ("03", "3"), ("1.50", "1.5"), ("2.0", "2"), ("Book 7.25", "7.25"), ("0.5", "0.5"),
                              ("10", "10"), ("abc", ""), ("", ""), (None, "")):
            with self.subTest(raw=raw):
                self.assertEqual(REVIEW.normalize_number(raw), expected)

class MultiBookTests(unittest.TestCase):
    def test_a_range_sequence_marks_it_and_a_single_number_does_not(self):
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Y", "sequence": "1-3"}))
        self.assertFalse(REVIEW.is_multi_book({"title": "X"}, {"title": "Y", "sequence": "3"}))

    def test_an_omnibus_container_folder_in_the_path_marks_it(self):
        self.assertTrue(REVIEW.is_multi_book({"title": "X"}, {"title": "Y"}, "/lib/Secret Alchemist (Book 1 & 2)/x.m4b"))
        self.assertFalse(REVIEW.is_multi_book({"title": "X"}, {"title": "Y"}, "/lib/Plain Folder/x.m4b"))

class SeverityTests(unittest.TestCase):
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


import copy


class ReviewMetadataItemReasonTests(unittest.TestCase):
    """One scenario per reason code: the severity it carries and, as importantly,
    the conditions under which it must NOT appear."""

    BASE = {"status": "matched", "write_action": "would_write", "mode": "full", "duration_status": "perfect", "score": 0.95,
            "local": {"title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage", "sequence": "15"},
            "match": {"title": "Metal Mage 15", "author": "Eric Vall", "series": "Metal Mage", "sequence": "15"}}

    def review(self, **over):
        item = copy.deepcopy(self.BASE)
        for key, value in over.items():
            if key in ("local", "match") and isinstance(value, dict):
                item[key].update(value)
            else:
                item[key] = value
        return REVIEW.review_metadata_item(item, REVIEW.parse_args(["x.json"]))

    def reasons(self, **over):
        result = self.review(**over)
        return {} if result is None else {r["code"]: r["severity"] for r in result["reasons"]}

    def test_a_low_score_is_high_severity_for_audible_and_uses_the_audible_threshold(self):
        self.assertEqual(self.reasons(score=0.84), {"low_score": "high"})
        self.assertEqual(self.reasons(score=0.85), {})
        self.assertEqual(self.reasons(score="not a number"), {})
        self.assertEqual(self.reasons(score=None), {})

    def test_only_a_real_duration_mismatch_is_flagged(self):
        self.assertEqual(self.reasons(duration_status="mismatch"), {"duration_mismatch": "high"})
        for status in ("unknown", "acceptable", "strong", "perfect"):
            self.assertEqual(self.reasons(duration_status=status), {})

    def test_a_sequence_conflict_inside_an_omnibus_folder_says_so(self):
        reason = self.review(match={"sequence": "3"}, path="/lib/Metal Mage (Books 1-3)/x.m4b")["reasons"][0]
        self.assertIn("omnibus_context", reason["evidence"])
        plain = self.review(match={"sequence": "3"}, path="/lib/Metal Mage/x.m4b")["reasons"][0]
        self.assertNotIn("omnibus_context", plain["evidence"])

    def test_a_missing_provider_sequence_is_flagged_only_for_full_mode_audible_matches_with_a_series(self):
        self.assertEqual(self.reasons(match={"sequence": ""}), {"provider_missing_sequence": "medium"})
        self.assertEqual(self.reasons(match={"sequence": ""}, provider="goodreads"), {})
        self.assertEqual(self.reasons(match={"sequence": ""}, mode="series_only"), {"series_only_mode": "medium"})
        self.assertEqual(self.reasons(match={"sequence": "", "series": ""}, local={"series": ""}), {"missing_series": "high"})

    def test_a_visible_number_that_disagrees_with_the_local_sequence_is_high(self):
        got = self.review(local={"title": "Metal Mage 14"})
        self.assertEqual({r["code"]: r["severity"] for r in got["reasons"]}, {"visible_number_conflict": "high"})

    def test_without_a_local_sequence_a_visible_number_is_checked_against_the_provider_at_medium(self):
        got = self.review(local={"sequence": "", "title": "Metal Mage 14"}, match={"sequence": "15", "title": "Metal Mage 14"})
        reasons = {r["code"]: r["severity"] for r in got["reasons"]}
        self.assertEqual(reasons.get("visible_number_conflict"), "medium")

    def test_a_dissimilar_title_is_medium_and_the_subtitle_can_rescue_it(self):
        self.assertEqual(self.reasons(match={"title": "Zzzzzz Qqqqq"}), {"title_mismatch": "medium"})
        rescued = self.reasons(match={"title": "Zzzzzz Qqqqq", "subtitle": "Metal Mage 15"})
        self.assertNotIn("title_mismatch", rescued)

    def test_a_dissimilar_series_is_high_but_a_folder_like_local_series_is_ignored(self):
        self.assertEqual(self.reasons(match={"series": "Totally Else"}), {"series_mismatch": "high"})
        self.assertEqual(self.reasons(local={"series": "Book 3"}, match={"series": "Totally Else"}), {})

    def test_a_dissimilar_author_is_high_but_containment_is_fine(self):
        self.assertEqual(self.reasons(match={"author": "Zed Quill"}), {"author_mismatch": "high"})
        self.assertEqual(self.reasons(match={"author": "Eric Vall, Zed Quill"}), {})
        self.assertEqual(self.reasons(local={"author": "Eric Vall, Zed Quill"}), {})

class ReviewOrganizerItemTests(unittest.TestCase):
    BASE = {"id": "o1", "source": "/lib/_unorganized/Cradle 1/a.m4b", "target": "/lib/Will Wight/Cradle/Book 1 - Unsouled",
            "title": "Unsouled", "author": "Will Wight", "series": "Cradle", "number": "1"}

    def review(self, **over):
        item = {**self.BASE, **over}
        return REVIEW.review_organizer_item(item, REVIEW.parse_args(["x.json"]))

    def reasons(self, **over):
        result = self.review(**over)
        return {} if result is None else {r["code"]: r["severity"] for r in result["reasons"]}

    def test_a_differing_number_in_the_source_or_target_path_is_a_conflict(self):
        self.assertEqual(self.reasons(source="/lib/_unorganized/Cradle Book 2/a.m4b"), {"organizer_source_number_conflict": "high"})
        self.assertEqual(self.reasons(target="/lib/Will Wight/Cradle/Book 2 - Unsouled"), {"organizer_target_number_conflict": "critical"})
        self.assertEqual(self.reasons(source="/lib/_unorganized/Cradle Book 1/a.m4b"), {})

    def test_a_bitrate_annotation_in_the_title_is_high(self):
        self.assertEqual(self.reasons(title="Unsouled 64k"), {"bitrate_in_title": "high"})
        for rate in ("64k", "96k", "128K", "192k", "256k", "320k"):
            self.assertEqual(self.reasons(title=f"Unsouled {rate}").get("bitrate_in_title"), "high", rate)
        self.assertNotIn("bitrate_in_title", self.reasons(title="Unsouled 100k"))
        self.assertNotIn("bitrate_in_title", self.reasons(title="Unsouled 1280k"))

    def test_an_abs_bracket_artifact_is_high_only_when_both_halves_are_alike(self):
        self.assertEqual(self.reasons(title="[Unsouled (Unabridged)] - Unsouled (Unabridged)"), {"title_bracket_artifact": "high"})
        self.assertEqual(self.reasons(title="[Alpha Beta Gamma] - Zzzz Qqqq Xxxx"), {})

    def test_the_unorganized_root_with_thin_metadata_is_medium(self):
        thin_series = self.reasons(source="/lib/_unorganized", series="")
        self.assertEqual(thin_series.get("source_is_unorganized_root"), "medium")
        got = self.reasons(source="/lib/_unorganized", title="")
        self.assertEqual(got.get("source_is_unorganized_root"), "medium")
        self.assertNotIn("source_is_unorganized_root", self.reasons(source="/lib/_unorganized"))
        self.assertNotIn("source_is_unorganized_root", self.reasons(source="/lib/other", series=""))

    def test_a_series_prefix_in_the_title_is_low_for_series_names_over_ten_characters(self):
        long = {"series": "Towers of Heaven", "title": "Towers of Heaven - Book 1"}
        self.assertEqual(self.reasons(**long), {"title_has_redundant_series_prefix": "low"})
        self.assertEqual(self.reasons(series="Towers of Heaven", title="Towers of Heaven, Book 1").get("title_has_redundant_series_prefix"), "low")
        self.assertEqual(self.reasons(series="Towers of Heaven", title="Towers of Heaven: Book 1").get("title_has_redundant_series_prefix"), "low")
        self.assertNotIn("title_has_redundant_series_prefix", self.reasons(series="Cradle", title="Cradle - Book 1"))

    def test_a_generic_omnibus_title_is_low(self):
        self.assertEqual(self.reasons(title="Omnibus, Books 1-3").get("generic_omnibus_title"), "low")

if __name__ == "__main__":
    unittest.main()
