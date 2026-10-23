"""hms() / parse_hms() are the timestamp format every Chapter Forge artifact
uses (ffmpeg metadata, SRT, review JSON), so their exact output matters."""
import unittest

from app.chaptering import hms


class HmsTests(unittest.TestCase):
    def test_milliseconds_round_to_nearest_and_carry_into_the_seconds(self):
        self.assertEqual(hms(1.2344), "00:00:01.234")
        self.assertEqual(hms(1.2346), "00:00:01.235")
        self.assertEqual(hms(59.9996), "00:01:00.000")
        self.assertEqual(hms(3599.9999), "01:00:00.000")


if __name__ == "__main__":
    unittest.main()
