"""A number is only written with a series, and a listing whose title carries
its series ("Frigid Magic (Ard's Oath Book 3)") gives that series and a clean
title. Benchmark: "Supers of Vault 12" was written as #12 with no series,
"Fahrenheit 451" as #451.
"""
import unittest

from app.fixer.parsing import series_from_subtitle
from app.fixer.scoring import get_primary_series, metadata_from_product


def listing(title, series=None, minutes=600):
    return {"asin": "B0TESTTEST", "title": title, "authors": [{"name": "Bruce Sentar"}],
            "narrators": [{"name": "Christopher Boucher"}], "series": series or [],
            "runtime_length_min": minutes}


def clues(title, **extra):
    return {"title": title, "author": "Bruce Sentar", "narrator": "Christopher Boucher",
            "local_duration_minutes": 600.4, **extra}


class ListingTitleSeriesTests(unittest.TestCase):
    def test_no_series_means_no_number(self):
        md = metadata_from_product(listing("Supers of Vault 12"), clues("Supers of Vault 12"), 1.0)
        self.assertEqual((md["series"], md["sequence"]), ("", ""))

    def test_title_number_still_written_with_a_series(self):
        md = metadata_from_product(listing("Power Mage 6", [{"title": "Power Mage", "sequence": "6"}]),
                                   clues("Power Mage 6"), 1.0)
        self.assertEqual((md["series"], md["sequence"]), ("Power Mage", "6"))

    def test_series_in_the_listings_title_is_the_series(self):
        md = metadata_from_product(listing("Frigid Magic (Ard's Oath Book 3)"), clues("Frigid Magic"), 1.0)
        self.assertEqual((md["series"], md["sequence"], md["title"]), ("Ard's Oath", "3", "Frigid Magic"))

    def test_parenthetical_without_comma_or_with_hash(self):
        self.assertEqual(series_from_subtitle("The Bourne Ultimatum (Jason Bourne Book #3)"), ("Jason Bourne", "3"))
        self.assertEqual(series_from_subtitle("A LitRPG Fantasy (Last Light, Book 1)"), ("Last Light", "1"))

    def test_a_plain_parenthetical_is_not_a_series(self):
        self.assertEqual(get_primary_series(listing("Network Effect (Dramatized Adaptation)")), ("", ""))


if __name__ == "__main__":
    unittest.main()
