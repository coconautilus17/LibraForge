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
    def test_a_rescanned_chapter_with_the_expected_number_inside_the_gap_is_added(self):
        merged = c.merge_rescan_candidates([cand(0, 1, confidence=0.9), cand(1000, 3, confidence=0.9)],
                                           [cand(500, 2, confidence=0.5)], [gap(2, 100, 900)])
        self.assertEqual([x.number for x in merged], [1, 2, 3])
        added = merged[1]
        self.assertIn("focused-gap-rescan", added.reasons)

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

class DetectSilencesTests(unittest.TestCase):
    def run_detect(self, stderr_by_file, offsets=None, **kw):
        outputs = list(stderr_by_file)
        with mock.patch.object(c.subprocess, "run", side_effect=lambda *a, **k: types.SimpleNamespace(stderr=outputs.pop(0))) as run:
            files = [Path(f"/b/{i}.mp3") for i in range(len(stderr_by_file))]
            got = c.detect_silences(files, offsets or {}, **kw)
        return got, run

    def test_each_files_offset_is_added_to_its_silences(self):
        stderr = "silence_start: 1.0\nsilence_end: 2.0 | silence_duration: 1.0\n"
        got, _ = self.run_detect([stderr, stderr], offsets={"/b/0.mp3": 0.0, "/b/1.mp3": 100.0})
        self.assertEqual(got, [(1.0, 2.0), (101.0, 102.0)])

if __name__ == "__main__":
    unittest.main()
