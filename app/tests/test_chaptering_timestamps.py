"""hms() / parse_hms() are the timestamp format every Chapter Forge artifact
uses (ffmpeg metadata, SRT, review JSON), so their exact output matters."""
import unittest

from app.chaptering import hms, normalize_text, parse_hms


class HmsTests(unittest.TestCase):
    def test_zero_and_whole_seconds(self):
        self.assertEqual(hms(0), "00:00:00.000")
        self.assertEqual(hms(59), "00:00:59.000")
        self.assertEqual(hms(60), "00:01:00.000")

    def test_hours_minutes_seconds_and_milliseconds_are_independent_fields(self):
        self.assertEqual(hms(3600 + 2 * 60 + 3 + 0.045), "01:02:03.045")
        self.assertEqual(hms(10 * 3600 + 59 * 60 + 59.5), "10:59:59.500")

    def test_milliseconds_round_to_nearest_and_carry_into_the_seconds(self):
        self.assertEqual(hms(1.2344), "00:00:01.234")
        self.assertEqual(hms(1.2346), "00:00:01.235")
        self.assertEqual(hms(59.9996), "00:01:00.000")
        self.assertEqual(hms(3599.9999), "01:00:00.000")

    def test_the_srt_form_uses_a_comma(self):
        self.assertEqual(hms(61.5, comma=True), "00:01:01,500")

    def test_negative_values_clamp_to_zero_and_numeric_strings_are_accepted(self):
        self.assertEqual(hms(-5), "00:00:00.000")
        self.assertEqual(hms("2.5"), "00:00:02.500")


class ParseHmsTests(unittest.TestCase):
    def test_each_field_has_its_own_weight(self):
        self.assertEqual(parse_hms("01:00:00"), 3600.0)
        self.assertEqual(parse_hms("00:01:00"), 60.0)
        self.assertEqual(parse_hms("00:00:01"), 1.0)
        self.assertEqual(parse_hms("02:03:04.5"), 2 * 3600 + 3 * 60 + 4.5)

    def test_a_comma_decimal_separator_is_accepted_and_whitespace_trimmed(self):
        self.assertEqual(parse_hms("  00:00:01,250 "), 1.25)

    def test_anything_but_three_fields_is_rejected(self):
        for bad in ("12:30", "1:2:3:4", "", "abc"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "Invalid timestamp|invalid literal|could not convert"):
                parse_hms(bad)

    def test_round_trips_with_hms(self):
        for seconds in (0.0, 1.5, 61.25, 3725.125, 36000.5):
            self.assertAlmostEqual(parse_hms(hms(seconds)), seconds, places=3)
            self.assertAlmostEqual(parse_hms(hms(seconds, comma=True)), seconds, places=3)


class NormalizeTextTests(unittest.TestCase):
    def test_runs_of_whitespace_collapse_and_ends_are_trimmed(self):
        self.assertEqual(normalize_text("  a \t b\n\nc  "), "a b c")

    def test_none_and_blank_become_empty(self):
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("   "), "")


if __name__ == "__main__":
    unittest.main()
