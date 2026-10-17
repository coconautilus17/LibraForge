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

    def test_a_clean_confirmed_match_raises_nothing(self):
        self.assertIsNone(self.review())

    def test_a_low_score_is_high_severity_for_audible_and_uses_the_audible_threshold(self):
        self.assertEqual(self.reasons(score=0.84), {"low_score": "high"})
        self.assertEqual(self.reasons(score=0.85), {})
        self.assertEqual(self.reasons(score="not a number"), {})
        self.assertEqual(self.reasons(score=None), {})

    def test_goodreads_and_kindle_use_their_own_lower_threshold_and_a_medium_severity(self):
        for provider in ("goodreads", "kindle"):
            with self.subTest(provider=provider):
                self.assertEqual(self.reasons(score=0.05, provider=provider), {"low_score": "medium"})
                self.assertEqual(self.reasons(score=0.5, provider=provider), {})

    def test_the_low_score_reason_reports_score_threshold_and_provider(self):
        evidence = self.review(score=0.5)["reasons"][0]["evidence"]
        self.assertEqual(evidence, {"score": 0.5, "threshold": 0.85, "provider": "audible"})

    def test_unsafe_modes_are_high_and_series_only_is_medium(self):
        self.assertEqual(self.reasons(mode="none"), {"unsafe_match": "high"})
        self.assertEqual(self.reasons(mode="unknown"), {"unsafe_match": "high"})
        self.assertEqual(self.reasons(mode="series_only"), {"series_only_mode": "medium"})

    def test_only_a_real_duration_mismatch_is_flagged(self):
        self.assertEqual(self.reasons(duration_status="mismatch"), {"duration_mismatch": "high"})
        for status in ("unknown", "acceptable", "strong", "perfect"):
            self.assertEqual(self.reasons(duration_status=status), {})

    def test_disagreeing_sequences_conflict_and_equal_ones_do_not(self):
        self.assertEqual(self.reasons(match={"sequence": "3"}), {"sequence_conflict": "high"})
        self.assertEqual(self.reasons(match={"sequence": "15.0"}), {})

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

    def test_a_missing_provider_sequence_is_not_flagged_for_omnibus_products(self):
        self.assertEqual(self.reasons(match={"sequence": "", "title": "Metal Mage Omnibus"},
                                      local={"title": "Metal Mage Omnibus"}), {})

    def test_a_visible_number_that_disagrees_with_the_local_sequence_is_high(self):
        got = self.review(local={"title": "Metal Mage 14"})
        self.assertEqual({r["code"]: r["severity"] for r in got["reasons"]}, {"visible_number_conflict": "high"})

    def test_a_visible_number_matching_the_provider_says_the_local_sequence_was_misread(self):
        got = self.review(local={"sequence": "14", "title": "Metal Mage 15"})
        codes = {r["code"] for r in got["reasons"]}
        self.assertIn("sequence_conflict", codes)
        conflict = [r for r in got["reasons"] if r["code"] == "visible_number_conflict"][0]
        self.assertIn("likely extracted incorrectly", conflict["message"])
        self.assertEqual(conflict["evidence"]["corroborates_match_sequence"], "15")

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

    def test_the_write_risk_checks_only_run_for_items_that_will_be_written(self):
        for action in ("smart_skipped", "write_skipped", "skipped", ""):
            with self.subTest(action=action):
                self.assertEqual(self.reasons(write_action=action, score=0.1, mode="none", duration_status="mismatch",
                                              match={"sequence": "3", "title": "Zzzzzz Qqqqq"}), {})

    def test_completeness_reasons_do_not_depend_on_the_write_action(self):
        self.assertEqual(self.reasons(write_action="smart_skipped", match={"series": ""}, local={"series": ""}),
                         {"missing_series": "high"})

    def test_missing_title_and_author_only_apply_to_matched_items(self):
        blank = {"title": "", "author": ""}
        self.assertEqual(self.reasons(match=blank, local=blank), {"missing_title": "high", "missing_author": "high"})
        self.assertEqual(self.reasons(status="failed", match=blank, local=blank), {})

    def test_title_and_author_fall_back_to_the_local_values(self):
        self.assertEqual(self.reasons(match={"title": "", "author": ""}).get("missing_title"), None)
        self.assertNotIn("missing_author", self.reasons(match={"author": ""}))

    def test_missing_series_applies_to_unmatched_items_too_and_falls_back_to_the_local_series(self):
        self.assertEqual(self.reasons(status="failed", match={"series": ""}, local={"series": ""}), {"missing_series": "high"})
        self.assertEqual(self.reasons(match={"series": ""}), {})

    def test_the_result_carries_identity_severity_and_recommendation(self):
        result = self.review(id="i7", path="/lib/x.m4b", match={"sequence": "3"}, used_query="q")
        self.assertEqual((result["id"], result["path"], result["tool"], result["severity"]), ("i7", "/lib/x.m4b", "metadata_fixer", "high"))
        self.assertEqual(result["recommendation"], "verify_sequence_before_apply")
        self.assertEqual((result["used_query"], result["score"], result["mode"]), ("q", 0.95, "full"))

    def test_the_path_falls_back_to_the_source_field(self):
        self.assertEqual(self.review(source="/lib/s.m4b", mode="none")["path"], "/lib/s.m4b")


class ReviewOrganizerItemTests(unittest.TestCase):
    BASE = {"id": "o1", "source": "/lib/_unorganized/Cradle 1/a.m4b", "target": "/lib/Will Wight/Cradle/Book 1 - Unsouled",
            "title": "Unsouled", "author": "Will Wight", "series": "Cradle", "number": "1"}

    def review(self, **over):
        item = {**self.BASE, **over}
        return REVIEW.review_organizer_item(item, REVIEW.parse_args(["x.json"]))

    def reasons(self, **over):
        result = self.review(**over)
        return {} if result is None else {r["code"]: r["severity"] for r in result["reasons"]}

    def test_a_complete_consistent_item_is_not_a_suspect(self):
        self.assertIsNone(self.review())

    def test_unknown_or_blank_authors_are_high_and_unknown_or_blank_titles_medium(self):
        for author in ("", "Unknown Author", "unknown"):
            self.assertEqual(self.reasons(author=author).get("unknown_author"), "high", author)
        for title in ("", "Unknown Title", "UNKNOWN"):
            self.assertEqual(self.reasons(title=title).get("unknown_title"), "medium", title)
        self.assertNotIn("unknown_author", self.reasons(author="Ann Unknownson"))
        self.assertNotIn("unknown_title", self.reasons(title="The Unknown Soldier"))

    def test_review_reasons_become_medium_unless_they_only_describe_how_a_value_was_derived(self):
        reasons = self.review(review_reasons=["possible duplicate", "title inferred from path", "series inferred from path",
                                              "author inferred from path", "title matches series name; using sequence only"])["reasons"]
        self.assertEqual({r["evidence"]["review_reason"]: r["severity"] for r in reasons}, {
            "possible duplicate": "medium", "title inferred from path": "info", "series inferred from path": "info",
            "author inferred from path": "info", "title matches series name; using sequence only": "info"})
        self.assertTrue(all(r["code"] == "existing_review_reason" for r in reasons))

    def test_an_item_whose_only_reasons_are_informational_is_not_a_suspect(self):
        self.assertIsNone(self.review(review_reasons=["title inferred from path"]))

    def test_a_number_without_a_series_is_flagged_only_when_nothing_else_explains_it(self):
        self.assertEqual(self.reasons(series=""), {"missing_series": "high"})
        self.assertEqual(self.reasons(series="", number=""), {})
        self.assertNotIn("missing_series", self.reasons(series="", review_reasons=["possible duplicate"]))
        self.assertNotIn("missing_series", self.reasons(series="", author=""))

    def test_a_differing_number_in_the_source_or_target_path_is_a_conflict(self):
        self.assertEqual(self.reasons(source="/lib/_unorganized/Cradle Book 2/a.m4b"), {"organizer_source_number_conflict": "high"})
        self.assertEqual(self.reasons(target="/lib/Will Wight/Cradle/Book 2 - Unsouled"), {"organizer_target_number_conflict": "critical"})
        self.assertEqual(self.reasons(source="/lib/_unorganized/Cradle Book 1/a.m4b"), {})

    def test_conflict_evidence_names_both_numbers(self):
        reason = self.review(target="/lib/x/Book 2 - Unsouled")["reasons"][0]
        self.assertEqual(reason["evidence"], {"selected_number": "1", "visible_target_number": "2"})

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

    def test_a_series_of_exactly_ten_characters_is_too_short_to_flag(self):
        self.assertEqual(len("Ten Chars!!"), 11)
        self.assertEqual(len("Tenchars10"), 10)
        self.assertNotIn("title_has_redundant_series_prefix", self.reasons(series="Tenchars10", title="Tenchars10 - Book 1"))
        self.assertIn("title_has_redundant_series_prefix", self.reasons(series="Tenchars-11", title="Tenchars-11 - Book 1"))

    def test_a_generic_omnibus_title_is_low(self):
        self.assertEqual(self.reasons(title="Omnibus, Books 1-3").get("generic_omnibus_title"), "low")

    def test_the_result_has_identity_status_and_the_organizer_fields_under_local(self):
        result = self.review(author="", status="planned_move", metadata_source="sidecar")
        self.assertEqual((result["id"], result["path"], result["tool"], result["status"]), ("o1", self.BASE["source"], "organizer", "planned_move"))
        self.assertEqual(result["severity"], "high")
        self.assertEqual(result["local"], {"title": "Unsouled", "author": "", "series": "Cradle", "sequence": "1",
                                          "target": self.BASE["target"], "metadata_source": "sidecar"})

    def test_the_status_defaults_to_planned_move(self):
        self.assertEqual(self.review(author="")["status"], "planned_move")


if __name__ == "__main__":
    unittest.main()
