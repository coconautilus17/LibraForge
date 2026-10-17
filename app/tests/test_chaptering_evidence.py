"""enrich_chapter_evidence attaches the transcript lines, word timings and
silences around each chapter start, which the AI review and the UI show as the
reason a chapter break was placed there."""
import unittest

from app.chaptering import TranscriptSegment, enrich_chapter_evidence


def chapter(start, **extra):
    return {"id": 1, "start": start, "source_text": "", **extra}


def seg(start, end, text, words=None):
    return TranscriptSegment(start=start, end=end, text=text, words=words or [])


class WindowTests(unittest.TestCase):
    def test_no_chapters_is_a_no_op(self):
        enrich_chapter_evidence([], [seg(0, 1, "x")])

    def test_segments_inside_the_default_window_become_timestamped_evidence_lines(self):
        ch = chapter(500.0)
        enrich_chapter_evidence([ch], [seg(450.0, 455.0, "Chapter five"), seg(520.0, 525.0, "It began")])
        self.assertEqual(ch["evidence_text"].splitlines(), ["[00:07:30.000 - 00:07:35.000] Chapter five",
                                                            "[00:08:40.000 - 00:08:45.000] It began"])
        self.assertEqual(ch["source_text"], ch["evidence_text"])

    def test_the_window_runs_120_seconds_before_and_180_after_the_chapter_start(self):
        ch = chapter(1000.0)
        segments = [seg(870.0, 879.0, "too early"), seg(881.0, 885.0, "just in"), seg(1179.0, 1181.0, "just in too"),
                    seg(1181.0, 1190.0, "too late")]
        enrich_chapter_evidence([ch], segments)
        self.assertEqual([line.split("] ")[1] for line in ch["evidence_text"].splitlines()], ["just in", "just in too"])

    def test_a_segment_that_overlaps_the_window_edge_counts(self):
        ch = chapter(1000.0)
        enrich_chapter_evidence([ch], [seg(870.0, 880.0, "ends at the edge"), seg(1180.0, 1190.0, "starts at the edge")])
        self.assertEqual(len(ch["evidence_text"].splitlines()), 2)

    def test_custom_window_sizes_are_honoured(self):
        ch = chapter(1000.0)
        enrich_chapter_evidence([ch], [seg(990.0, 995.0, "near"), seg(900.0, 905.0, "far")], before_seconds=20, after_seconds=20)
        self.assertEqual(len(ch["evidence_text"].splitlines()), 1)

    def test_the_window_never_starts_before_zero(self):
        ch = chapter(10.0)
        enrich_chapter_evidence([ch], [seg(0.0, 2.0, "intro")])
        self.assertIn("intro", ch["evidence_text"])

    def test_blank_segments_are_skipped_and_text_is_whitespace_normalised(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [seg(95.0, 96.0, "   "), seg(96.0, 97.0, "two   spaced\n words")])
        self.assertEqual(ch["evidence_text"], "[00:01:36.000 - 00:01:37.000] two spaced words")

    def test_without_nearby_text_the_existing_source_text_is_kept_as_the_evidence(self):
        ch = chapter(100.0, source_text="Chapter One")
        enrich_chapter_evidence([ch], [seg(5000.0, 5001.0, "far away")])
        self.assertEqual((ch["evidence_text"], ch["source_text"]), ("Chapter One", "Chapter One"))

    def test_each_chapter_gets_its_own_window(self):
        a, b = chapter(100.0), chapter(1000.0)
        enrich_chapter_evidence([a, b], [seg(100.0, 101.0, "first"), seg(1000.0, 1001.0, "second")])
        self.assertIn("first", a["evidence_text"])
        self.assertNotIn("second", a["evidence_text"])
        self.assertIn("second", b["evidence_text"])


class AnchorTests(unittest.TestCase):
    def test_transcript_anchors_carry_time_label_kind_and_text_cut_to_220_characters(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [seg(95.0, 99.0, "x" * 300)])
        anchor = ch["evidence_anchors"][0]
        self.assertEqual((anchor["time"], anchor["kind"], anchor["label"]), (95.0, "transcript", "00:01:35.000 transcript"))
        self.assertEqual(len(anchor["text"]), 220)

    def test_silence_edges_inside_the_window_become_anchors_sorted_by_time(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [], silences=[(90.0, 94.0)])
        self.assertEqual([(a["time"], a["text"]) for a in ch["evidence_anchors"]], [(90.0, "silence start"), (94.0, "silence end")])

    def test_only_the_edge_inside_the_window_is_an_anchor_but_the_silence_is_clipped_into_the_windows(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [], silences=[(-50.0, 2.0)], before_seconds=100, after_seconds=100)
        self.assertEqual([a["text"] for a in ch["evidence_anchors"]], ["silence end"])
        self.assertEqual(ch["evidence_silences"], [{"start": 0.0, "end": 2.0, "duration": 2.0}])

    def test_silences_outside_the_window_are_ignored_entirely(self):
        ch = chapter(1000.0)
        enrich_chapter_evidence([ch], [], silences=[(10.0, 20.0), (5000.0, 5005.0)])
        self.assertEqual((ch["evidence_anchors"], ch["evidence_silences"]), ([], []))

    def test_a_silence_overlapping_the_window_is_clipped_to_it(self):
        ch = chapter(1000.0)
        enrich_chapter_evidence([ch], [], silences=[(850.0, 900.0)])
        self.assertEqual(ch["evidence_silences"], [{"start": 880.0, "end": 900.0, "duration": 20.0}])

    def test_same_kind_anchors_closer_than_fifty_milliseconds_collapse_to_one(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [seg(95.0, 96.0, "a"), seg(95.04, 96.0, "b"), seg(95.06, 96.0, "c")])
        self.assertEqual([a["time"] for a in ch["evidence_anchors"]], [95.0, 95.06])

    def test_a_transcript_and_a_silence_at_the_same_moment_are_both_kept(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [seg(95.0, 96.0, "a")], silences=[(95.0, 95.5)])
        self.assertEqual(sorted(a["kind"] for a in ch["evidence_anchors"] if a["time"] == 95.0), ["silence", "transcript"])


class WordTests(unittest.TestCase):
    def test_words_inside_the_window_are_listed_with_timings_and_probability(self):
        ch = chapter(100.0)
        words = [{"word": " Chapter ", "start": 99.5, "end": 100.0, "probability": 0.9}]
        enrich_chapter_evidence([ch], [seg(99.0, 101.0, "Chapter one", words)])
        self.assertEqual(ch["evidence_words"], [{"start": 99.5, "end": 100.0, "text": "Chapter", "probability": 0.9}])

    def test_words_outside_the_window_or_blank_are_dropped(self):
        ch = chapter(1000.0)
        words = [{"word": "early", "start": 880.1, "end": 881.0}, {"word": "late", "start": 1180.5, "end": 1181.0},
                 {"word": "  ", "start": 1000.0, "end": 1000.5}, {"word": "inside", "start": 1000.0, "end": 1000.5}]
        enrich_chapter_evidence([ch], [seg(870.0, 1190.0, "long segment", words)])
        self.assertEqual([w["text"] for w in ch["evidence_words"]], ["early", "inside"])

    def test_a_missing_word_time_falls_back_to_the_segment_start_and_a_missing_end_to_the_start(self):
        ch = chapter(100.0)
        enrich_chapter_evidence([ch], [seg(99.0, 101.0, "x", [{"word": "hi"}])])
        self.assertEqual(ch["evidence_words"], [{"start": 99.0, "end": 99.0, "text": "hi", "probability": None}])


class CapTests(unittest.TestCase):
    def test_the_lists_are_capped_at_120_lines_180_anchors_500_words_and_80_silences(self):
        ch = chapter(5000.0)
        segments = [seg(4900.0 + i * 0.5, 4900.2 + i * 0.5, f"line {i}",
                        [{"word": f"w{i}-{j}", "start": 4900.0 + i * 0.5 + j * 0.01, "end": 4900.0 + i * 0.5 + j * 0.01 + 0.005}
                         for j in range(4)])
                    for i in range(300)]
        silences = [(4900.0 + i, 4900.4 + i) for i in range(100)]
        enrich_chapter_evidence([ch], segments, silences)
        self.assertEqual(len(ch["evidence_text"].splitlines()), 120)
        self.assertEqual(len(ch["evidence_anchors"]), 180)
        self.assertEqual(len(ch["evidence_words"]), 500)
        self.assertEqual(len(ch["evidence_silences"]), 80)

    def test_a_list_exactly_at_the_cap_is_not_truncated_further(self):
        ch = chapter(5000.0)
        segments = [seg(4950.0 + i, 4950.5 + i, f"line {i}") for i in range(120)]
        enrich_chapter_evidence([ch], segments)
        self.assertEqual(len(ch["evidence_text"].splitlines()), 120)
        self.assertTrue(ch["evidence_text"].splitlines()[-1].endswith("line 119"))


if __name__ == "__main__":
    unittest.main()
