"""When Audible leaves the series field empty but the subtitle names the series, the fixer uses it."""
import unittest

from app.fixer import scoring


class PrimarySeriesFromSubtitleTests(unittest.TestCase):
    def test_a_subtitle_supplies_the_series_when_the_field_is_empty(self):
        shardborn = {"title": "Shardborn", "subtitle": "A LitRPG Fantasy (Last Light, Book 1)", "series": []}
        kokoro = {"title": "Welcome to the Kokoro Cat Clinic", "subtitle": "Volume 3 in the Kokoro Cat Clinic series for fans of THE TRAVELLING CAT CHRONICLES"}
        self.assertEqual(scoring.get_primary_series(shardborn), ("Last Light", "1"))
        self.assertEqual(scoring.get_primary_series(kokoro), ("Kokoro Cat Clinic", "3"))

    def test_the_number_candidates_agree_with_it(self):
        product = {"title": "Shardborn", "subtitle": "A LitRPG Fantasy (Last Light, Book 1)", "series": []}
        self.assertEqual(scoring.get_audible_number_candidates(product)[0], "1")

    def test_audibles_own_series_wins_over_the_subtitle(self):
        product = {"title": "Shardborn", "subtitle": "(Other Saga, Book 9)", "series": [{"title": "Last Light", "sequence": "1"}]}
        self.assertEqual(scoring.get_primary_series(product), ("Last Light", "1"))

    def test_an_ordinary_subtitle_gives_no_series(self):
        product = {"title": "Postwar", "subtitle": "How Europe rebuilt and redefined itself after 1945", "series": []}
        self.assertEqual(scoring.get_primary_series(product), ("", ""))


if __name__ == "__main__":
    unittest.main()
