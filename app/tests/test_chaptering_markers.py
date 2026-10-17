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

    def test_non_numerals_and_the_unsupported_letters_are_none(self):
        for raw in ("", "abc", "MM", "cd", "d", "m", "  "):
            with self.subTest(raw=raw):
                self.assertIsNone(c.roman_to_int(raw))

    def test_integers_back_to_numerals(self):
        for number, expected in ((1, "I"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"), (90, "XC"), (99, "XCIX"), (399, "CCCXCIX")):
            with self.subTest(number=number):
                self.assertEqual(c.int_to_roman(number), expected)

    def test_numbers_may_be_digits_words_hyphenated_words_or_numerals(self):
        for raw, expected in (("12", 12), ("twelve", 12), ("Twenty one", 21), ("forty-two", 42), ("iv", 4), ("5 the book", 5)):
            with self.subTest(raw=raw):
                self.assertEqual(c.parse_number(raw), expected)

    def test_text_without_a_number_is_none(self):
        for raw in ("chapter", "", "   ", "!!!"):
            with self.subTest(raw=raw):
                self.assertIsNone(c.parse_number(raw))

    def test_marker_kinds_are_title_cased_with_the_spelling_fixed(self):
        for raw, expected in (("prolog", "Prologue"), ("EPILOG", "Epilogue"), ("chapter", "Chapter"), ("INTERLUDE", "Interlude")):
            with self.subTest(raw=raw):
                self.assertEqual(c.title_case_marker(raw), expected)


class HeadingTitleTests(unittest.TestCase):
    def test_all_caps_titles_are_title_cased_with_small_words_lowered(self):
        self.assertEqual(c.smart_title_case("THE END OF THE WORLD"), "The End of the World")
        self.assertEqual(c.smart_title_case("DON'T PANIC"), "Don't Panic")
        self.assertEqual(c.smart_title_case("A STORY"), "A Story")

    def test_mixed_case_titles_are_left_alone_and_edge_punctuation_trimmed(self):
        self.assertEqual(c.smart_title_case("The end of the world"), "The end of the world")
        self.assertEqual(c.smart_title_case("  X. "), "X")
        self.assertEqual(c.smart_title_case(""), "")

    def test_a_numbered_chapter_heading_is_rebuilt_from_the_marker_number_and_the_cased_rest(self):
        self.assertEqual(c.normalize_heading_title("CHAPTER FIVE THE LONG ROAD", "Chapter", 5), "Chapter 5 The Long Road")
        self.assertEqual(c.normalize_heading_title("chapter 5 the long road", "Chapter", 5), "Chapter 5 the long road")

    def test_prose_after_a_chapter_marker_is_dropped(self):
        self.assertEqual(c.normalize_heading_title("Chapter 5. He had walked all night and could not stop", "Chapter", 5), "Chapter 5")

    def test_structural_headings_keep_a_short_title_or_collapse_to_the_kind(self):
        self.assertEqual(c.normalize_heading_title("prologue", "Prologue", None), "Prologue")
        self.assertEqual(c.normalize_heading_title("Prologue", "Prologue", None), "Prologue")
        self.assertEqual(c.normalize_heading_title("Prologue The Beginning", "Prologue", None), "Prologue The Beginning")
        self.assertEqual(c.normalize_heading_title("Prologue he went home", "Prologue", None), "Prologue")      # prose start word

    def test_other_kinds_are_just_title_cased(self):
        self.assertEqual(c.normalize_heading_title("THE END", "Part", 2), "The End")
        self.assertEqual(c.normalize_heading_title("", "Chapter", 1), "")

    def test_titles_are_cut_to_140_characters(self):
        self.assertEqual(len(c.normalize_heading_title("THE " + "WORD " * 60, "Part", 2)), 140)

    def test_a_chapter_title_is_limited_to_seven_words_after_the_number(self):
        title = "Chapter 5 One two three four five six seven eight nine ten"
        self.assertEqual(c.trim_long_heading_title(title, "Chapter", 5), "Chapter 5 One two three four five six seven")
        self.assertEqual(c.trim_long_heading_title("Chapter 5 Short", "Chapter", 5), "Chapter 5 Short")

    def test_the_word_limit_applies_to_numbered_chapters_only(self):
        title = "Part 2 One two three four five six seven eight nine ten"
        self.assertEqual(c.trim_long_heading_title(title, "Part", 2), title)
        self.assertEqual(c.trim_long_heading_title("Chapter 5 x", "Chapter", None), "Chapter 5 x")

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

    def test_a_numberless_marker_is_bare_only_when_it_is_the_kind_itself(self):
        self.assertTrue(c.is_bare_marker_title("Prologue", "Prologue", None))
        self.assertFalse(c.is_bare_marker_title("Prologue and more", "Prologue", None))


class ExtendBareTitleTests(unittest.TestCase):
    def segs(self, *texts):
        return [T(start=i * 5.0, end=i * 5.0 + 3.0, text=t) for i, t in enumerate(texts)]

    def test_a_bare_chapter_heading_takes_the_next_segment_as_its_title(self):
        segments = self.segs("Chapter 5.", "The Long Road")
        self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0), ("Chapter 5. The Long Road", "title-extended-next-segment"))

    def test_nothing_is_added_when_the_title_is_not_bare_or_the_kind_is_not_a_numbered_chapter(self):
        segments = self.segs("Chapter 5.", "The Long Road")
        self.assertEqual(c.extend_bare_title("Chapter 5 Road", "Chapter", 5, segments, 0), ("Chapter 5 Road", None))
        self.assertEqual(c.extend_bare_title("Prologue", "Prologue", None, segments, 0), ("Prologue", None))
        self.assertEqual(c.extend_bare_title("Part 2", "Part", 2, segments, 0), ("Part 2", None))

    def test_the_last_segment_has_no_next_segment(self):
        segments = self.segs("Chapter 5.")
        self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0), ("Chapter 5", None))

    def test_a_next_segment_more_than_eight_seconds_later_is_not_a_title(self):
        segments = [T(start=0, end=3, text="Chapter 5."), T(start=11.5, end=14, text="The Long Road")]
        self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0), ("Chapter 5", None))
        segments = [T(start=0, end=3, text="Chapter 5."), T(start=10.9, end=14, text="The Long Road")]
        self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0)[1], "title-extended-next-segment")

    def test_empty_or_excluded_next_text_is_not_used(self):
        for text in ("   ", "chapter and verse"):
            segments = [T(start=0, end=3, text="Chapter 5."), T(start=4, end=6, text=text)]
            self.assertEqual(c.extend_bare_title("Chapter 5", "Chapter", 5, segments, 0), ("Chapter 5", None), text)


class FindMarkerTests(unittest.TestCase):
    def find(self, *segments):
        return c.find_marker_candidates(list(segments))

    def test_a_chapter_at_the_start_of_a_segment_is_a_confident_numbered_candidate(self):
        got = self.find(T(start=100.0, end=110.0, text="Chapter 5 The Long Road"))
        self.assertEqual(len(got), 1)
        cand_ = got[0]
        self.assertEqual((cand_.marker_kind, cand_.number, cand_.title), ("Chapter", 5, "Chapter 5 The Long Road"))
        self.assertAlmostEqual(cand_.confidence, 0.8)                # 0.45 + segment start 0.2 + number 0.15
        self.assertEqual(cand_.reasons[:3], ["marker:chapter", "segment-start", "number:5"])
        self.assertEqual((cand_.start, cand_.end), (100.0, 110.0))

    def test_structural_markers_get_a_bonus(self):
        got = self.find(T(start=0.0, end=5.0, text="Prologue"))
        self.assertEqual((got[0].marker_kind, got[0].title), ("Prologue", "Prologue"))
        self.assertAlmostEqual(got[0].confidence, 0.75)              # 0.45 + start 0.2 + structural 0.1
        self.assertIn("structural-marker", got[0].reasons)

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

    @unittest.expectedFailure
    def test_an_end_of_chapter_announcement_should_not_become_a_marker(self):
        # KNOWN BUG, issue #378: END_OF_RE is searched in the 16 characters BEFORE the
        # marker, which never contain the marker word itself ("chapter"), so it cannot fire.
        got = self.find(T(start=0, end=3, text="End of chapter 5. Chapter 6 The Road"))
        self.assertEqual([x.number for x in got], [6])

    def test_excluded_phrases_and_blank_text_are_ignored(self):
        self.assertEqual(self.find(T(start=0, end=3, text="This chapter is brought to you by")), [])
        self.assertEqual(self.find(T(start=0, end=3, text="   ")), [])

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

    def test_a_standalone_heading_with_prose_or_too_many_words_is_ignored(self):
        self.assertEqual(self.find(T(start=0, end=3, text="7. He walked home")), [])
        self.assertEqual(self.find(T(start=0, end=3, text="7. The Storm " + "word " * 10)), [])

    def test_the_marker_time_is_estimated_proportionally_inside_the_segment_capped_at_ninety_percent(self):
        seg = T(start=100.0, end=110.0, text="x" * 20)
        self.assertEqual(c.estimate_marker_time(seg, 0, 20), 100.0)
        self.assertEqual(c.estimate_marker_time(seg, 10, 20), 105.0)
        self.assertEqual(c.estimate_marker_time(seg, 20, 20), 109.0)
        self.assertEqual(c.estimate_marker_time(seg, 5, 0), 100.0)

    def test_the_source_file_is_carried_to_the_candidate(self):
        got = self.find(T(start=0, end=3, text="Chapter 1 Start", file="/x/01.mp3"))
        self.assertEqual(got[0].source_file, "/x/01.mp3")


class DedupeAndValidateTests(unittest.TestCase):
    def test_candidates_within_twenty_seconds_collapse_to_the_most_confident(self):
        got = c.dedupe_candidates([cand(100, 1, confidence=0.5), cand(110, 1, confidence=0.7), cand(200, 2, confidence=0.5)])
        self.assertEqual([(x.start, x.confidence) for x in got], [(110, 0.7), (200, 0.5)])

    def test_the_window_edge_is_inclusive_and_the_input_order_does_not_matter(self):
        got = c.dedupe_candidates([cand(300, 3), cand(100, 1), cand(120, 2)])
        self.assertEqual([x.start for x in got], [100, 300])
        self.assertEqual([x.start for x in c.dedupe_candidates([cand(100, 1), cand(120.1, 2)])], [100, 120.1])

    def test_only_numbered_chapters_count_as_numbered(self):
        self.assertTrue(c.is_numbered_chapter(cand(0, 1)))
        self.assertFalse(c.is_numbered_chapter(cand(0, None)))
        self.assertFalse(c.is_numbered_chapter(cand(0, 1, kind="Part")))

    def test_consecutive_chapters_gain_confidence(self):
        got = c.validate_sequence([cand(0, 1, confidence=0.5), cand(100, 2, confidence=0.5)])
        self.assertEqual([x.number for x in got], [1, 2])
        self.assertAlmostEqual(got[1].confidence, 0.7)
        self.assertIn("sequence-ok", got[1].reasons)

    def test_a_backtrack_loses_confidence_and_a_big_gap_loses_less(self):
        got = c.validate_sequence([cand(0, 5, confidence=0.9), cand(100, 5, confidence=0.9), cand(200, 9, confidence=0.9)])
        self.assertIn("sequence-backtrack", got[1].reasons)
        self.assertAlmostEqual(got[1].confidence, 0.55)
        self.assertIn("sequence-gap", got[2].reasons)
        self.assertAlmostEqual(got[2].confidence, 0.75)

    def test_a_candidate_below_the_acceptance_bar_is_dropped(self):
        got = c.validate_sequence([cand(0, 5, confidence=0.9), cand(100, 2, confidence=0.6)])
        self.assertEqual([x.number for x in got], [5])

    def test_a_skip_of_exactly_two_is_not_a_gap(self):
        got = c.validate_sequence([cand(0, 1, confidence=0.9), cand(100, 3, confidence=0.9)])
        self.assertNotIn("sequence-gap", got[1].reasons)

    def test_candidates_closer_than_the_minimum_chapter_length_compete(self):
        # the later one is penalised by 0.25 before it may replace the earlier one
        got = c.validate_sequence([cand(0, 1, confidence=0.7), cand(30, 2, confidence=0.9)])
        self.assertEqual([x.number for x in got], [1])               # 0.9 - 0.25 = 0.65 does not beat 0.7
        got = c.validate_sequence([cand(0, 1, confidence=0.5), cand(30, 2, confidence=0.9)])
        self.assertEqual([x.number for x in got], [2])               # 0.65 beats 0.5 and replaces it
        self.assertIn("too-close", got[0].reasons)
        got = c.validate_sequence([cand(0, 1, confidence=0.9), cand(60, 2, confidence=0.6)])
        self.assertEqual([x.number for x in got], [1, 2])            # exactly the minimum length: no longer "too close"

    def test_non_numbered_candidates_need_only_the_confidence_bar(self):
        got = c.validate_sequence([cand(0, None, kind="Prologue", confidence=0.45), cand(100, None, kind="Epilogue", confidence=0.44)])
        self.assertEqual([x.marker_kind for x in got], ["Prologue"])


class SequenceGapTests(unittest.TestCase):
    def test_missing_numbers_between_detected_chapters_get_a_padded_search_window(self):
        gaps = c.sequence_gaps([cand(100, 1), cand(1000, 4)], duration=5000.0)
        self.assertEqual([(g.expected_number, g.reason) for g in gaps], [(2, "missing-between-detected"), (3, "missing-between-detected")])
        self.assertEqual((gaps[0].start, gaps[0].end), (100 - c.RESCAN_BOUNDARY_PAD_BEFORE_SECONDS, 1000 + c.RESCAN_BOUNDARY_PAD_AFTER_SECONDS))

    def test_the_window_end_is_capped_at_the_duration_and_the_start_at_zero(self):
        gaps = c.sequence_gaps([cand(5, 1), cand(1000, 3)], duration=1010.0)
        self.assertEqual((gaps[0].start, gaps[0].end), (0.0, 1010.0))

    def test_chapters_missing_before_the_first_detected_one(self):
        gaps = c.sequence_gaps([cand(2000, 3)], duration=9000.0)
        self.assertEqual([(g.expected_number, g.reason) for g in gaps], [(1, "missing-before-first"), (2, "missing-before-first")])
        self.assertEqual((gaps[0].start, gaps[0].end), (1400.0, 1970.0))      # 600s window before the first, ending 30s early

    def test_the_before_first_window_is_at_least_the_minimum_and_never_negative(self):
        gaps = c.sequence_gaps([cand(100, 2)], duration=9000.0)
        self.assertEqual((gaps[0].start, gaps[0].end), (0.0, 70.0))

    def test_a_complete_sequence_has_no_gaps_and_non_chapters_are_ignored(self):
        self.assertEqual(c.sequence_gaps([cand(0, 1), cand(100, 2), cand(200, 3)], 500.0), [])
        self.assertEqual(c.sequence_gaps([cand(0, None, kind="Prologue")], 500.0), [])
        self.assertEqual(c.sequence_gaps([], 500.0), [])

    def test_backwards_numbers_are_not_gaps(self):
        gaps = c.sequence_gaps([cand(0, 1), cand(100, 3), cand(200, 2)], 500.0)
        self.assertEqual([g.expected_number for g in gaps], [2])      # 1 -> 3 is missing 2; 3 -> 2 adds nothing

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

    def test_a_misread_is_only_corrected_when_the_following_number_confirms_it(self):
        items = [cand(0, 4), cand(100, 9), cand(200, 20)]
        c.correct_obvious_sequence_misreads(items)
        self.assertEqual(items[1].number, 9)

    def test_a_correctly_numbered_middle_chapter_is_untouched(self):
        items = [cand(0, 4), cand(100, 5), cand(200, 6)]
        c.correct_obvious_sequence_misreads(items)
        self.assertEqual([x.number for x in items], [4, 5, 6])

    def test_a_corrected_confidence_never_falls_below_the_floor(self):
        items = [cand(0, 1), cand(100, 7, confidence=0.4), cand(200, 3)]
        c.correct_obvious_sequence_misreads(items)
        self.assertEqual(items[1].number, 2)
        self.assertEqual(items[1].confidence, 0.55)


class SnapToSilenceTests(unittest.TestCase):
    def test_a_marker_is_placed_a_second_before_the_nearest_point_of_a_silence_that_contains_it(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(98.0, 100.5)])
        self.assertEqual(item.start, 99.0)
        self.assertIn("silence-lead-snapped", item.reasons)
        self.assertAlmostEqual(item.confidence, 0.68)

    def test_the_target_is_clamped_into_the_silence(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(101.0, 103.0)])
        self.assertEqual(item.start, 101.0)

    def test_a_silence_beyond_the_window_does_not_snap(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(110.0, 112.0)])
        self.assertEqual((item.start, item.reasons), (100.0, []))

    def test_with_no_lead_the_nearest_silence_boundary_wins(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(97.0, 99.8)], marker_lead_seconds=0)
        self.assertEqual(item.start, 99.8)
        self.assertIn("silence-snapped", item.reasons)

    def test_with_no_lead_a_silence_ending_after_the_marker_snaps_to_its_start(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [(99.0, 103.0)], marker_lead_seconds=0)
        self.assertEqual(item.start, 99.0)

    def test_the_start_never_goes_negative_and_confidence_is_capped(self):
        item = cand(0.5, 1, confidence=0.97)
        c.snap_to_silence([item], [(0.0, 1.0)])
        self.assertGreaterEqual(item.start, 0.0)
        self.assertEqual(item.confidence, 0.99)

    def test_no_silences_leaves_the_candidate_alone(self):
        item = cand(100.0, 1)
        c.snap_to_silence([item], [])
        self.assertEqual((item.start, item.reasons, item.confidence), (100.0, [], 0.6))


if __name__ == "__main__":
    unittest.main()
