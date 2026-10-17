"""Chapter Forge's focused-rescan merge, the LLM correction step and the ffmpeg
silence parser. The LLM and ffmpeg are replaced by canned data so only the
decision logic is under test."""
import types
import unittest
from pathlib import Path
from unittest import mock

from app import chaptering as c


def cand(start, number, kind="Chapter", confidence=0.6, title=None):
    return c.ChapterCandidate(start=start, original_start=start, end=start + 30, title=title or f"Chapter {number}",
                              marker_kind=kind, number=number, confidence=confidence, reasons=[])


def gap(number, start, end, reason="missing-between-detected"):
    return c.SequenceGap(number, start, end, reason)


class MergeRescanTests(unittest.TestCase):
    def test_nothing_rescanned_returns_the_base_list_unchanged(self):
        base = [cand(0, 1)]
        self.assertIs(c.merge_rescan_candidates(base, [], [gap(2, 0, 100)]), base)

    def test_a_rescanned_chapter_with_the_expected_number_inside_the_gap_is_added(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9), cand(1000, 3, confidence=0.9)],
                                           [cand(500, 2, confidence=0.5)], [gap(2, 100, 900)])
        self.assertEqual([x.number for x in merged], [1, 2, 3])
        added = merged[1]
        self.assertIn("focused-gap-rescan", added.reasons)

    def test_the_added_candidate_gets_a_twelve_point_bonus_then_the_sequence_bonus_from_validation(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9)], [cand(500, 2, confidence=0.5)], [gap(2, 100, 900)])
        added = [x for x in merged if x.number == 2][0]
        self.assertAlmostEqual(added.confidence, 0.5 + 0.12 + 0.2)          # rescan bonus + "sequence-ok"
        self.assertEqual(added.reasons, ["focused-gap-rescan", "sequence-ok"])

    def test_the_rescan_bonus_is_capped_at_ninety_seven_hundredths(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9)], [cand(500, 2, confidence=0.95)], [gap(2, 100, 900)])
        added = [x for x in merged if x.number == 2][0]
        self.assertAlmostEqual(added.confidence - 0.2, 0.97)

    def test_wrong_number_outside_the_gap_or_non_chapter_candidates_are_not_added(self):
        base = [cand(0, 1, confidence=0.9)]
        for rescanned in ([cand(500, 3)], [cand(2000, 2)], [cand(500, 2, kind="Part")]):
            with self.subTest(rescanned=rescanned):
                self.assertEqual([x.number for x in c.merge_rescan_candidates(base, rescanned, [gap(2, 100, 900)])], [1])

    def test_a_candidate_within_twenty_seconds_of_an_existing_chapter_is_a_duplicate(self):
        base = [cand(0, 1, confidence=0.9), cand(500, 9, confidence=0.9)]
        merged = c.merge_rescan_candidates(base, [cand(510, 2)], [gap(2, 100, 900)])
        self.assertNotIn(2, [x.number for x in merged])

    def test_among_several_matches_the_most_confident_one_wins(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9)],
                                           [cand(300, 2, confidence=0.55), cand(700, 2, confidence=0.7)], [gap(2, 100, 900)])
        self.assertEqual([x.start for x in merged if x.number == 2], [700])

    def test_equal_confidence_prefers_the_one_nearer_the_middle_of_the_gap(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9)],
                                           [cand(150, 2, confidence=0.6), cand(480, 2, confidence=0.6)], [gap(2, 100, 900)])
        self.assertEqual([x.start for x in merged if x.number == 2], [480])


class LlmCorrectionTests(unittest.TestCase):
    def result(self):
        return {"chapters": [{"number": 5, "start": 100.0, "title": "Chapter 5", "reasons": []},
                             {"number": 6, "start": 300.0, "title": "Chapter 6", "reasons": []}]}

    def apply(self, corrections):
        result = self.result()
        c._apply_llm_chapter_corrections(result, {"accepted_corrections": corrections})
        return result

    def good(self, **over):
        return {"action": "clean_title", "number": 5, "timestamp": "00:01:41.000", "title": "Chapter 5 The Road", "evidence": "heard it", **over}

    def test_a_matching_correction_renames_the_chapter_and_is_recorded(self):
        result = self.apply([self.good()])
        chapter = result["chapters"][0]
        self.assertEqual(chapter["title"], "Chapter 5 The Road")
        self.assertEqual(chapter["reasons"], ["llm-reviewed-title"])
        self.assertEqual(chapter["llm_evidence"], "heard it")
        self.assertEqual(result["hybrid"]["llm_applied_corrections"],
                         [{"number": 5, "timestamp": "00:01:41.000", "old_title": "Chapter 5", "new_title": "Chapter 5 The Road"}])

    def test_the_timestamp_must_be_within_eight_seconds_of_the_chapter(self):
        self.assertEqual(self.apply([self.good(timestamp="00:01:48.000")])["chapters"][0]["title"], "Chapter 5 The Road")
        self.assertEqual(self.apply([self.good(timestamp="00:01:49.000")])["chapters"][0]["title"], "Chapter 5")

    def test_only_known_actions_are_applied(self):
        for action in ("correct_number", "clean_title", "add_missing_chapter", "keep"):
            self.assertEqual(self.apply([self.good(action=action)])["chapters"][0]["title"], "Chapter 5 The Road", action)
        for action in ("delete", "", None):
            self.assertEqual(self.apply([self.good(action=action)])["chapters"][0]["title"], "Chapter 5", action)

    def test_incomplete_or_wrongly_typed_corrections_are_skipped(self):
        for bad in ({"number": "5"}, {"number": None}, {"timestamp": ""}, {"title": ""}, {"title": "   "}):
            with self.subTest(bad=bad):
                self.assertEqual(self.apply([self.good(**bad)])["chapters"][0]["title"], "Chapter 5")

    def test_a_correction_for_another_chapter_number_finds_that_chapter(self):
        result = self.apply([self.good(number=6, timestamp="00:05:01.000", title="Chapter 6 Night")])
        self.assertEqual([ch["title"] for ch in result["chapters"]], ["Chapter 5", "Chapter 6 Night"])

    def test_the_review_reason_is_added_once(self):
        result = self.apply([self.good(), self.good(title="Chapter 5 Again")])
        self.assertEqual(result["chapters"][0]["reasons"], ["llm-reviewed-title"])
        self.assertEqual(result["chapters"][0]["title"], "Chapter 5 Again")

    def test_at_most_eight_corrections_are_considered(self):
        result = self.apply([self.good(title=f"T{i}") for i in range(10)])
        self.assertEqual(len(result["hybrid"]["llm_applied_corrections"]), 8)
        self.assertEqual(result["chapters"][0]["title"], "T7")

    def test_with_no_corrections_the_applied_list_is_empty(self):
        self.assertEqual(self.apply([])["hybrid"]["llm_applied_corrections"], [])

    def test_stamps_convert_to_seconds(self):
        self.assertEqual(c._stamp_to_seconds("01:02:03.5"), 3723.5)
        self.assertEqual(c._stamp_to_seconds(" 00:00:01,250 "), 1.25)
        self.assertEqual(c._stamp_to_seconds("12:34"), 0.0)
        self.assertEqual(c._stamp_to_seconds(""), 0.0)


class DetectSilencesTests(unittest.TestCase):
    def run_detect(self, stderr_by_file, offsets=None, **kw):
        outputs = list(stderr_by_file)
        with mock.patch.object(c.subprocess, "run", side_effect=lambda *a, **k: types.SimpleNamespace(stderr=outputs.pop(0))) as run:
            files = [Path(f"/b/{i}.mp3") for i in range(len(stderr_by_file))]
            got = c.detect_silences(files, offsets or {}, **kw)
        return got, run

    def test_start_end_pairs_become_intervals(self):
        stderr = "[silencedetect] silence_start: 10.5\n[silencedetect] silence_end: 12.0 | silence_duration: 1.5\n"
        self.assertEqual(self.run_detect([stderr])[0], [(10.5, 12.0)])

    def test_each_files_offset_is_added_to_its_silences(self):
        stderr = "silence_start: 1.0\nsilence_end: 2.0 | silence_duration: 1.0\n"
        got, _ = self.run_detect([stderr, stderr], offsets={"/b/0.mp3": 0.0, "/b/1.mp3": 100.0})
        self.assertEqual(got, [(1.0, 2.0), (101.0, 102.0)])

    def test_an_end_without_a_start_and_a_start_without_an_end_are_ignored(self):
        self.assertEqual(self.run_detect(["silence_end: 5.0 | silence_duration: 1\n"])[0], [])
        self.assertEqual(self.run_detect(["silence_start: 5.0\n"])[0], [])

    def test_a_malformed_start_discards_its_end(self):
        self.assertEqual(self.run_detect(["silence_start: x\nsilence_end: 5.0 | silence_duration: 1\n"])[0], [])

    def test_the_detection_threshold_and_minimum_duration_are_passed_to_ffmpeg(self):
        _, run = self.run_detect([""], noise_db=-40, min_duration=1.2)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("silencedetect=noise=-40dB:d=1.2", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 900)

    def test_defaults_are_minus_35_db_and_six_tenths_of_a_second(self):
        _, run = self.run_detect([""])
        self.assertIn("silencedetect=noise=-35dB:d=0.6", run.call_args.args[0])

    def test_no_output_means_no_silences(self):
        self.assertEqual(self.run_detect([""])[0], [])
        self.assertEqual(self.run_detect([None])[0], [])


if __name__ == "__main__":
    unittest.main()
