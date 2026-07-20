"""write_cue() must emit a standard CUE sheet m4b-tool can actually parse.

m4b-tool's CueSheet parser only recognizes INDEX lines (mm:ss:mmm, no hours
component) -- it computes each chapter's end from the next chapter's start.
A prior version of this function wrote non-standard START/END fields that
m4b-tool silently ignored (zero chapters imported, no error).
"""
import unittest

from app.chaptering import cue_timecode, write_cue


class CueTimecodeTests(unittest.TestCase):
    def test_formats_minutes_seconds_milliseconds_without_hours(self):
        self.assertEqual(cue_timecode(0.0), "00:00:000")
        self.assertEqual(cue_timecode(2.0), "00:02:000")
        self.assertEqual(cue_timecode(75.25), "01:15:250")

    def test_handles_multi_hour_offsets_as_total_minutes(self):
        # 2h 3m 4s == 7384s -> 123 total minutes, no hours field in CUE INDEX
        self.assertEqual(cue_timecode(7384.0), "123:04:000")

    def test_rounds_milliseconds_that_carry_into_the_next_second(self):
        self.assertEqual(cue_timecode(1.9996), "00:02:000")


class WriteCueTests(unittest.TestCase):
    def test_emits_index_lines_not_start_end(self):
        chapters = [
            {"id": 1, "title": "Chapter One", "start": 0.0, "end": 120.5},
            {"id": 2, "title": "Chapter Two", "start": 120.5, "end": None},
        ]
        cue = write_cue(chapters, "Book.mp3")

        self.assertIn('FILE "Book.mp3" MP3', cue)
        self.assertIn("TRACK 01 AUDIO", cue)
        self.assertIn('TITLE "Chapter One"', cue)
        self.assertIn("INDEX 01 00:00:000", cue)
        self.assertIn("TRACK 02 AUDIO", cue)
        self.assertIn("INDEX 01 02:00:500", cue)
        self.assertNotIn("START", cue)
        self.assertNotIn("END", cue)


if __name__ == "__main__":
    unittest.main()
