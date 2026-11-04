"""A listing in several Audible series gets the same series however Audible orders them (#427)."""
import unittest

from app.fixer import scoring


def mage_errant(order):
    series = {"mage": {"title": "Mage Errant", "sequence": "5"}, "aeth": {"title": "The Aetheriad", "sequence": "4"}}
    return {"asin": "1774249979", "title": "The Siege of Skyhold", "authors": [{"name": "John Bierce"}],
            "series": [series[k] for k in order]}


class PrimarySeriesChoiceTests(unittest.TestCase):
    def test_a_numbered_series_beats_an_unnumbered_umbrella(self):
        product = {"title": "Rhythm of War", "series": [
            {"title": "The Cosmere", "sequence": ""}, {"title": "The Stormlight Archive", "sequence": "4"}]}
        self.assertEqual(scoring.get_primary_series(product), ("The Stormlight Archive", "4"))

    def test_the_series_the_file_names_wins_in_either_order(self):
        clues = {"title": "The Siege of Skyhold", "author": "John Bierce", "series": "Mage Errant", "book_number": "5"}
        for order in (["mage", "aeth"], ["aeth", "mage"]):
            product = scoring.with_preferred_series(mage_errant(order), clues)
            self.assertEqual(scoring.get_primary_series(product), ("Mage Errant", "5"))
            md = scoring.metadata_from_product(mage_errant(order), clues, 0.95)
            self.assertEqual((md["series"], md["sequence"]), ("Mage Errant", "5"))

    def test_an_unnumbered_series_the_file_names_still_wins(self):
        product = {"title": "Rhythm of War", "series": [
            {"title": "The Stormlight Archive", "sequence": "4"}, {"title": "The Cosmere", "sequence": ""}]}
        chosen = scoring.with_preferred_series(product, {"series": "The Cosmere"})
        self.assertEqual(scoring.get_primary_series(chosen), ("The Cosmere", ""))

    def test_scoring_does_not_depend_on_the_order(self):
        clues = {"title": "The Siege of Skyhold", "author": "John Bierce", "series": "Mage Errant", "book_number": "5"}
        scores = {scoring.score_product_for_metadata(clues, mage_errant(o)) for o in (["mage", "aeth"], ["aeth", "mage"])}
        self.assertEqual(len(scores), 1)

    def test_the_series_the_files_title_names_wins_when_the_series_tag_names_none(self):
        # #501: Audible lists Into the Storm (B00HS1WT4Y) as War Machine 5 first; the file,
        # book 1 by its folder, says "Book One of The Malcontents" in its title.
        storm = {"asin": "B00HS1WT4Y", "title": "Into the Storm", "subtitle": "Book One of The Malcontents",
                 "authors": [{"name": "Larry Correia"}], "narrators": [{"name": "Ray Porter"}],
                 "runtime_length_min": 476, "series": [{"title": "War Machine", "sequence": "5"},
                                                       {"title": "The Malcontents", "sequence": "1"}]}
        clues = {"title": "Into the Storm: Book One of The Malcontents",
                 "raw_title": "Into the Storm: Book One of The Malcontents",
                 "series": "Larry Correia", "book_number": "1", "book_number_source": "path",
                 "author": "Larry Correia", "local_duration_minutes": 476.17}
        self.assertEqual(scoring.get_primary_series(scoring.with_preferred_series(storm, clues)), ("The Malcontents", "1"))
        self.assertGreater(scoring.score_product_for_metadata(clues, storm, 476.17), 0.7)
        md = scoring.metadata_from_product(storm, clues, 0.95)
        self.assertEqual((md["series"], md["sequence"]), ("The Malcontents", "1"))

    def test_the_most_specific_series_the_title_names_wins(self):
        sinners = {"title": "Monster Hunter Memoirs: Sinners", "series": [
            {"title": "Monster Hunter", "sequence": ""}, {"title": "Monster Hunter Memoirs", "sequence": "2"}]}
        clues = {"title": "Monster Hunter Memoirs: Sinners", "raw_title": "Monster Hunter Memoirs: Sinners"}
        chosen = scoring.with_preferred_series(sinners, clues)
        self.assertEqual(scoring.get_primary_series(chosen), ("Monster Hunter Memoirs", "2"))

    def test_a_title_naming_neither_series_leaves_the_order_alone(self):
        product = mage_errant(["aeth", "mage"])
        clues = {"title": "The Siege of Skyhold", "raw_title": "The Siege of Skyhold", "author": "John Bierce"}
        self.assertIs(scoring.with_preferred_series(product, clues), product)

    def test_the_listing_itself_is_not_changed(self):
        product = mage_errant(["aeth", "mage"])
        scoring.with_preferred_series(product, {"series": "Mage Errant"})
        self.assertEqual(product["series"][0]["title"], "The Aetheriad")


if __name__ == "__main__":
    unittest.main()
