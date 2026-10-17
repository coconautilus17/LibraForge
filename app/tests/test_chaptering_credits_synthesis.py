"""finalize_chapters() must synthesize "Opening Credits"/"End Credits" rows
for the leading/trailing gaps around detected content, matching how Audible
itself always brackets a book -- our own silence+keyword detection has no
spoken cue to key off for either (no one says the word "credits" aloud), so
these are structural gap-fills, not marker-classified candidates.

Real-world bug found live: comparing hybrid vs Audible on Divine Apostasy
Book 2 showed hybrid missing both Opening Credits (0 -> 16.4s, absorbed into
nothing) and End Credits (absorbed into the Epilogue's end, which stretched
all the way to file duration instead of stopping at its own real content).
"""
import unittest

from app.chaptering import ChapterCandidate, finalize_chapters


def _candidate(start: float, title: str = "Chapter", marker_kind: str = "Chapter", number=None) -> ChapterCandidate:
    return ChapterCandidate(start=start, original_start=start, end=start + 1.0, title=title, marker_kind=marker_kind, number=number)


class OpeningCreditsSynthesisTests(unittest.TestCase):
    def test_synthesizes_opening_credits_for_a_real_leading_gap(self):
        candidates = [_candidate(16.415, "Prolog", "Prologue")]
        chapters = finalize_chapters(candidates, duration=1000.0)
        self.assertEqual(chapters[0]["title"], "Opening Credits")
        self.assertEqual(chapters[0]["start"], 0.0)
        self.assertEqual(chapters[0]["end"], 16.415)
        self.assertIsNone(chapters[0]["confidence"])
        self.assertEqual(chapters[1]["title"], "Prolog")
        self.assertEqual(chapters[0]["id"], 1)
        self.assertEqual(chapters[1]["id"], 2)

    def test_no_opening_credits_when_first_chapter_starts_near_zero(self):
        candidates = [_candidate(1.2)]
        chapters = finalize_chapters(candidates, duration=1000.0)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["title"], "Chapter")

    def test_no_opening_credits_with_no_candidates(self):
        self.assertEqual(finalize_chapters([], duration=1000.0), [])


class EndCreditsSynthesisTests(unittest.TestCase):
    """Each candidate list starts with an early (<=3s) marker so opening-
    credits synthesis never triggers here -- isolates the end-credits path.
    """

    def test_synthesizes_end_credits_for_a_qualifying_trailing_silence(self):
        # Mirrors Divine Apostasy Book 2's real numbers: last chapter starts
        # at 48972.999, a 4.8s silence sits at 49089.4-49094.2 (right where
        # Audible's own End Credits boundary is, 49093.6), a SECOND, longer
        # 5.9s silence at 49111.9-49117.8 sits *inside* the credits reading
        # itself (an internal sentence pause), duration is 49121.045.
        candidates = [_candidate(0.5, "Chapter 1"), _candidate(48972.999, "Epilogue", "Epilogue")]
        silences = [(100.0, 101.0), (49089.415, 49094.232), (49111.902, 49117.769)]
        chapters = finalize_chapters(candidates, duration=49121.045, silences=silences)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[1]["title"], "Epilogue")
        self.assertAlmostEqual(chapters[1]["end"], 49091.8235, places=2)
        self.assertEqual(chapters[2]["title"], "End Credits")
        self.assertAlmostEqual(chapters[2]["start"], 49091.8235, places=2)
        self.assertEqual(chapters[2]["end"], 49121.045)
        self.assertIsNone(chapters[2]["confidence"])

    def test_no_end_credits_without_a_qualifying_silence(self):
        candidates = [_candidate(0.5), _candidate(100.0)]
        silences = [(150.0, 150.8), (300.0, 300.5)]  # too short to count
        chapters = finalize_chapters(candidates, duration=1000.0, silences=silences)
        self.assertEqual(len(chapters), 2)

    def test_no_end_credits_when_silence_is_too_close_to_file_end(self):
        candidates = [_candidate(0.5), _candidate(100.0)]
        silences = [(995.0, 998.0)]  # qualifies as silence but leaves <3s trailing
        chapters = finalize_chapters(candidates, duration=1000.0, silences=silences)
        self.assertEqual(len(chapters), 2)

    def test_no_end_credits_for_silence_before_the_last_chapter(self):
        candidates = [_candidate(0.5), _candidate(50.0), _candidate(900.0)]
        silences = [(60.0, 65.0)]  # long, but occurs before the last chapter's own start
        chapters = finalize_chapters(candidates, duration=1000.0, silences=silences)
        self.assertEqual(len(chapters), 3)

    def test_no_end_credits_without_silences_argument(self):
        candidates = [_candidate(0.5), _candidate(48972.999)]
        chapters = finalize_chapters(candidates, duration=49121.045)
        self.assertEqual(len(chapters), 2)

    def test_picks_the_earliest_qualifying_silence_not_the_latest(self):
        # The credits reading itself has its own internal pauses -- picking
        # the *latest* qualifying gap risks landing inside it instead of at
        # the real content-to-credits boundary. Two gaps both within the
        # trailing search window; the earlier one is the real boundary.
        candidates = [_candidate(0.5), _candidate(850.0)]
        silences = [(900.0, 903.0), (950.0, 953.0)]
        chapters = finalize_chapters(candidates, duration=1000.0, silences=silences)
        self.assertEqual(len(chapters), 3)
        self.assertAlmostEqual(chapters[2]["start"], 901.5, places=3)

    def test_ignores_a_qualifying_gap_outside_the_trailing_search_window(self):
        # A legitimate 2.5s+ pause deep inside a long last chapter (well
        # outside the ~2-minute trailing window credits readings actually
        # live in) must not be mistaken for the credits boundary.
        candidates = [_candidate(0.5), _candidate(100.0)]
        silences = [(400.0, 404.0), (950.0, 953.0)]  # 400s gap is >120s before duration
        chapters = finalize_chapters(candidates, duration=1000.0, silences=silences)
        self.assertEqual(len(chapters), 3)
        self.assertAlmostEqual(chapters[2]["start"], 951.5, places=3)


class BothEndsSynthesisTests(unittest.TestCase):
    def test_synthesizes_both_opening_and_end_credits(self):
        candidates = [_candidate(16.415, "Prolog", "Prologue"), _candidate(48972.999, "Epilogue", "Epilogue")]
        silences = [(49089.415, 49094.232)]
        chapters = finalize_chapters(candidates, duration=49121.045, silences=silences)
        self.assertEqual([c["title"] for c in chapters], ["Opening Credits", "Prolog", "Epilogue", "End Credits"])
        self.assertEqual([c["id"] for c in chapters], [1, 2, 3, 4])
        self.assertEqual(chapters[0]["start"], 0.0)
        self.assertEqual(chapters[-1]["end"], 49121.045)


class CreditsThresholdAndShapeTests(unittest.TestCase):
    def test_the_opening_gap_must_exceed_three_seconds(self):
        self.assertEqual(len(finalize_chapters([_candidate(3.0)], duration=1000.0)), 1)
        chapters = finalize_chapters([_candidate(3.01)], duration=1000.0)
        self.assertEqual([c["title"] for c in chapters], ["Opening Credits", "Chapter"])

    def test_synthesized_rows_name_their_reason_and_carry_blank_source_fields(self):
        chapters = finalize_chapters([_candidate(10.123456)], duration=1000.0,
                                     silences=[(990.0, 994.0)])
        opening, _, end = chapters
        self.assertEqual(opening["reasons"], ["synthesized:leading-gap"])
        self.assertEqual(end["reasons"], ["synthesized:trailing-gap"])
        for row in (opening, end):
            self.assertEqual((row["source_text"], row["source_file"], row["number"], row["marker_kind"]),
                             ("", "", None, row["title"]))
        self.assertEqual(opening["end"], 10.123)            # rounded to milliseconds
        self.assertEqual(opening["original_start"], 0.0)
        self.assertEqual([c["id"] for c in chapters], [1, 2, 3])

    def test_end_credits_split_at_the_middle_of_the_silence_and_the_last_chapter_ends_there(self):
        chapters = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(990.0, 994.0)])
        chapter, end = chapters[-2], chapters[-1]
        self.assertEqual(end["title"], "End Credits")
        self.assertEqual((end["start"], end["end"]), (992.0, 1000.0))
        self.assertEqual(chapter["end"], 992.0)
        self.assertEqual(end["original_start"], 992.0)

    def test_the_silence_must_last_two_and_a_half_seconds(self):
        short = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(990.0, 992.4)])
        self.assertEqual([c["title"] for c in short], ["Opening Credits", "Chapter"])
        exact = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(990.0, 992.5)])
        self.assertEqual(exact[-1]["title"], "End Credits")

    def test_enough_audio_must_remain_after_the_silence(self):
        close = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(995.0, 998.0)])
        self.assertNotIn("End Credits", [c["title"] for c in close])
        ok = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(994.0, 997.0)])
        self.assertEqual(ok[-1]["title"], "End Credits")

    def test_only_silences_in_the_last_two_minutes_are_considered(self):
        far = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(500.0, 504.0)])
        self.assertNotIn("End Credits", [c["title"] for c in far])
        edge = finalize_chapters([_candidate(100.0)], duration=1000.0, silences=[(880.0, 884.0)])
        self.assertEqual(edge[-1]["title"], "End Credits")

    def test_the_search_never_starts_before_the_last_chapter_does(self):
        late_chapter = finalize_chapters([_candidate(950.0)], duration=1000.0, silences=[(900.0, 905.0)])
        self.assertNotIn("End Credits", [c["title"] for c in late_chapter])

    def test_the_earliest_qualifying_silence_wins(self):
        chapters = finalize_chapters([_candidate(100.0)], duration=1000.0,
                                     silences=[(960.0, 964.0), (900.0, 904.0)])
        self.assertEqual(chapters[-1]["start"], 902.0)

    def test_chapter_end_is_the_next_start_and_a_zero_length_chapter_gets_a_one_second_minimum(self):
        chapters = finalize_chapters([_candidate(10.0), _candidate(10.0, "Dup")], duration=1000.0)
        by_title = {c["title"]: c for c in chapters}
        self.assertEqual(by_title["Chapter"]["end"], 10.0 + 1.0)
        self.assertEqual(finalize_chapters([_candidate(50.0), _candidate(80.0, "B")], 200.0)[-2]["end"], 80.0)

    def test_candidates_are_sorted_and_confidence_is_clamped(self):
        low = ChapterCandidate(start=60.0, original_start=60.0, end=61.0, title="B", marker_kind="Chapter", confidence=7.0)
        high = ChapterCandidate(start=20.0, original_start=19.1234, end=21.0, title="A", marker_kind="Chapter", confidence=-3.0)
        rows = finalize_chapters([low, high], duration=100.0)
        chapters = [r for r in rows if r["title"] in ("A", "B")]
        self.assertEqual([r["title"] for r in chapters], ["A", "B"])
        self.assertEqual((chapters[0]["confidence"], chapters[1]["confidence"]), (0.0, 1.0))
        self.assertEqual(chapters[0]["original_start"], 19.123)


if __name__ == "__main__":
    unittest.main()
