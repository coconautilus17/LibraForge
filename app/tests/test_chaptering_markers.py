"""Chapter Forge's marker detection, step by step: reading numbers, building
heading titles, finding "Chapter N" markers in transcript segments, validating
the sequence, finding gaps and snapping to silences. Values are asserted
exactly because they become the chapter names and times written to the book."""
import unittest

from app import chaptering as c

T = c.TranscriptSegment


def cand(start, number=None, kind="Chapter", confidence=0.6, title=None, **kw):
    return c.ChapterCandidate(start=start, original_start=start, end=start + 30, title=title or f"{kind} {number or ''}".strip(),
                              marker_kind=kind, number=number, confidence=confidence, reasons=kw.pop("reasons", []), **kw)


class RomanAndNumberTests(unittest.TestCase):
    def test_roman_numerals_up_to_four_hundred_ninety_nine(self):
        for raw, expected in (("iv", 4), ("XIX", 19), ("c", 100), ("xl", 40), ("ix ", 9), ("iiii", 4), ("cccxcix", 399)):
            with self.subTest(raw=raw):
                self.assertEqual(c.roman_to_int(raw), expected)

class HeadingTitleTests(unittest.TestCase):
    def test_structural_headings_keep_a_short_title_or_collapse_to_the_kind(self):
        self.assertEqual(c.normalize_heading_title("prologue", "Prologue", None), "Prologue")
        self.assertEqual(c.normalize_heading_title("Prologue", "Prologue", None), "Prologue")
        self.assertEqual(c.normalize_heading_title("Prologue The Beginning", "Prologue", None), "Prologue The Beginning")
        self.assertEqual(c.normalize_heading_title("Prologue he went home", "Prologue", None), "Prologue")      # prose start word

    def test_other_kinds_are_just_title_cased(self):
        self.assertEqual(c.normalize_heading_title("THE END", "Part", 2), "The End")
        self.assertEqual(c.normalize_heading_title("", "Chapter", 1), "")

    def test_a_chapter_title_is_limited_to_seven_words_after_the_number(self):
        title = "Chapter 5 One two three four five six seven eight nine ten"
        self.assertEqual(c.trim_long_heading_title(title, "Chapter", 5), "Chapter 5 One two three four five six seven")
        self.assertEqual(c.trim_long_heading_title("Chapter 5 Short", "Chapter", 5), "Chapter 5 Short")

    def test_short_titles_pass_through_the_prose_trimmer_and_prose_starts_are_cut_off(self):
        self.assertEqual(c.trim_title_prose("Chapter 5", "Chapter", 5), "Chapter 5")
        self.assertEqual(c.trim_title_prose("Chapter 5 The Road", "Chapter", 5), "Chapter 5 The Road")
        self.assertEqual(c.trim_title_prose("Prologue", "Prologue", None), "Prologue")
        self.assertEqual(c.trim_title_prose("Chapter 5 The Long Road he walked every day", "Chapter", 5), "Chapter 5 The Long Road")

    def test_a_title_that_only_restates_its_marker_is_bare(self):
        for title in ("Chapter 5", "Chapter five", "Chapter V.", "chapter 5.", ""):
            with self.subTest(title=title):
                self.assertTrue(c.is_bare_marker_title(title, "Chapter", 5), title)
        for title in ("Chapter 5 The Road", "chapter 6"):
            with self.subTest(title=title):
                self.assertFalse(c.is_bare_marker_title(title, "Chapter", 5), title)

class ExtendBareTitleTests(unittest.TestCase):
    def segs(self, *texts):
        return [T(start=i * 5.0, end=i * 5.0 + 3.0, text=t) for i, t in enumerate(texts)]

    def test_the_last_segment_has_no_next_segment(self):
        segments = self.segs("Chapter 5.")
        self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0), ("Chapter 5", None))

class FindMarkerTests(unittest.TestCase):
    def find(self, *segments):
        return c.find_marker_candidates(list(segments))

    def test_prolog_and_epilog_are_normalised(self):
        kinds = [c_.marker_kind for c_ in self.find(T(start=0, end=2, text="Prolog"), T(start=90, end=92, text="Epilog"))]
        self.assertEqual(kinds, ["Prologue", "Epilogue"])

    def test_an_embedded_marker_is_less_confident_and_a_numberless_embedded_chapter_is_ignored(self):
        got = self.find(T(start=0.0, end=10.0, text="and so it ended. Chapter 6 The Road"))
        self.assertEqual(len(got), 1)
        self.assertIn("embedded-marker", got[0].reasons)
        self.assertAlmostEqual(got[0].confidence, 0.4)               # 0.45 + number 0.15 - embedded 0.2
        self.assertEqual(self.find(T(start=0.0, end=10.0, text="we were reading the chapter about it all")), [])

    def test_part_book_and_section_need_a_number(self):
        self.assertEqual(self.find(T(start=0, end=3, text="Part of the plan")), [])
        got = self.find(T(start=0, end=3, text="Part Two"))
        self.assertEqual((got[0].marker_kind, got[0].number), ("Part", 2))

    def test_a_bare_chapter_heading_borrows_the_next_segment_as_its_title(self):
        got = self.find(T(start=10.0, end=12.0, text="Chapter 7."), T(start=13.0, end=16.0, text="The Storm"))
        self.assertEqual(got[0].title, "Chapter 7 The Storm")
        self.assertIn("title-extended-next-segment", got[0].reasons)
        self.assertAlmostEqual(got[0].confidence, 0.85)              # 0.8 + 0.05

    def test_a_standalone_numbered_heading_becomes_a_chapter_with_fixed_low_confidence(self):
        got = self.find(T(start=200.0, end=203.0, text="7. The Storm Breaks"))
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].number, got[0].marker_kind, got[0].title, got[0].confidence), (7, "Chapter", "Chapter 7 The Storm Breaks", 0.52))
        self.assertEqual(got[0].reasons, ["standalone-numbered-heading", "number:7"])

class DedupeAndValidateTests(unittest.TestCase):
    def test_candidates_within_twenty_seconds_collapse_to_the_most_confident(self):
        got = c.dedupe_candidates([cand(100, 1, confidence=0.5), cand(110, 1, confidence=0.7), cand(200, 2, confidence=0.5)])
        self.assertEqual([(x.start, x.confidence) for x in got], [(110, 0.7), (200, 0.5)])

    def test_a_backtrack_loses_confidence_and_a_big_gap_loses_less(self):
        got = c.validate_sequence([cand(0, 5, confidence=0.9), cand(100, 5, confidence=0.9), cand(200, 9, confidence=0.9)])
        self.assertIn("sequence-backtrack", got[1].reasons)
        self.assertAlmostEqual(got[1].confidence, 0.55)
        self.assertIn("sequence-gap", got[2].reasons)
        self.assertAlmostEqual(got[2].confidence, 0.75)

    def test_candidates_closer_than_the_minimum_chapter_length_compete(self):
        # the later one is penalised by 0.25 before it may replace the earlier one
        got = c.validate_sequence([cand(0, 1, confidence=0.7), cand(30, 2, confidence=0.9)])
        self.assertEqual([x.number for x in got], [1])               # 0.9 - 0.25 = 0.65 does not beat 0.7
        got = c.validate_sequence([cand(0, 1, confidence=0.5), cand(30, 2, confidence=0.9)])
        self.assertEqual([x.number for x in got], [2])               # 0.65 beats 0.5 and replaces it
        self.assertIn("too-close", got[0].reasons)
        got = c.validate_sequence([cand(0, 1, confidence=0.9), cand(60, 2, confidence=0.6)])
        self.assertEqual([x.number for x in got], [1, 2])            # exactly the minimum length: no longer "too close"

class SequenceGapTests(unittest.TestCase):
    def test_chapters_missing_before_the_first_detected_one(self):
        gaps = c.sequence_gaps([cand(2000, 3)], duration=9000.0)
        self.assertEqual([(g.expected_number, g.reason) for g in gaps], [(1, "missing-before-first"), (2, "missing-before-first")])
        self.assertEqual((gaps[0].start, gaps[0].end), (1400.0, 1970.0))      # 600s window before the first, ending 30s early

    def test_unresolved_gaps_are_reported_as_plain_dicts_rounded(self):
        got = c.annotate_unresolved_gaps([cand(100.12345, 1), cand(1000.9876, 3)], 5000.0)
        self.assertEqual(got, [{"expected_number": 2, "start": 90.123, "end": 1030.988, "reason": "missing-between-detected"}])

    def test_an_obvious_misread_between_two_consistent_neighbours_is_corrected(self):
        items = [cand(0, 4, title="Chapter 4"), cand(100, 9, title="Chapter 9 The Road", confidence=0.9), cand(200, 6, title="Chapter 6")]
        c.correct_obvious_sequence_misreads(items)
        self.assertEqual(items[1].number, 5)
        self.assertEqual(items[1].title, "Chapter 5 The Road")
        self.assertIn("sequence-corrected-from:9", items[1].reasons)
        self.assertAlmostEqual(items[1].confidence, 0.85)

class SnapToSilenceTests(unittest.TestCase):
    def test_with_no_lead_a_silence_ending_after_the_marker_snaps_to_its_start(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(99.0, 103.0)], marker_lead_seconds=0)
        self.assertEqual(item.start, 99.0)

    def test_the_start_never_goes_negative_and_confidence_is_capped(self):
        item = cand(0.5, 1, confidence=0.97)
        c.snap_to_silence([item], [(0.0, 1.0)])
        self.assertGreaterEqual(item.start, 0.0)
        self.assertEqual(item.confidence, 0.99)

if __name__ == "__main__":
    unittest.main()
