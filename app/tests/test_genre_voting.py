"""Per-book and per-series genre voting across sources (Enrichment Forge v2)."""
import unittest

from app.genre_voting import book_vote, vote_unit


def unit(votes, **kw):
    base = dict(series_labels=[], series_evidence=[], pf_progression=False, standalone=False)
    base.update(kw)
    return vote_unit(votes, **base)


class VotingTests(unittest.TestCase):
    def test_main_needs_two_sources_unless_strong(self):
        v = book_vote({"audible": ["thriller"], "audiosilo": ["horror"], "goodreads": ["litrpg", "fantasy"]})
        self.assertIn("LitRPG", v["main"])
        self.assertNotIn("Horror", v["main"])

    def test_single_source_book_keeps_its_top_genre(self):
        self.assertEqual(book_vote({"audible": ["thriller"]})["main"], {"Thriller"})

    def test_series_threshold_is_25_percent_of_books(self):
        votes = [book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"]}) for _ in range(8)]
        votes[0] = book_vote({"audible": ["horror"], "audiosilo": ["horror"]})
        self.assertEqual(unit(votes)["main"], ["Fantasy"])

    def test_evidence_counts_books_per_source(self):
        votes = [book_vote({"audible": ["fantasy"], "goodreads": ["fantasy"]}) for _ in range(3)]
        self.assertEqual(unit(votes)["evidence"]["Fantasy"], {"audible": 3, "goodreads": 3})

    def test_pf_progression_needs_corroboration_when_mainstream_conflicts(self):
        votes = [book_vote({"audible": ["mystery", "fantasy"], "audiosilo": ["mystery", "urban fantasy"]}) for _ in range(4)]
        self.assertNotIn("Progression Fantasy", unit(votes, pf_progression=True)["main"])
        clean = [book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"]}) for _ in range(4)]
        self.assertIn("Progression Fantasy", unit(clean, pf_progression=True)["main"])

    def test_series_source_counts_as_full_support_and_is_recorded(self):
        votes = [book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"]}) for _ in range(6)]
        r = unit(votes, series_labels=["haremlit"], series_evidence=["HaremLit wiki: X"])
        self.assertIn("Harem", r["main"])
        self.assertIn("series-source", r["evidence"]["Harem"])
        self.assertEqual(r["series_evidence"], ["HaremLit wiki: X"])

    def test_non_fiction_is_exclusive(self):
        votes = [book_vote({"audible": ["history"], "audiosilo": ["history"], "openlibrary": ["fantasy"]}) for _ in range(3)]
        self.assertEqual(unit(votes)["main"], ["Non-Fiction"])

    def test_at_most_three_mains_counting_strong_ones(self):
        labels = ["fantasy", "thriller", "mystery", "horror", "humor", "litrpg"]
        r = unit([book_vote({"audible": labels, "audiosilo": labels})])
        self.assertIn("LitRPG", r["main"])
        self.assertLessEqual(len(r["main"]), 3)

    def test_no_votes_means_no_agreement(self):
        r = unit([book_vote({})], standalone=True)
        self.assertEqual((r["main"], r["agreement"]), ([], "none"))

    def test_books_without_votes_do_not_dilute_the_threshold(self):
        votes = [book_vote({"audible": ["horror"], "audiosilo": ["horror"]})] + [book_vote({}) for _ in range(7)]
        self.assertEqual(unit(votes)["main"], ["Horror"])
