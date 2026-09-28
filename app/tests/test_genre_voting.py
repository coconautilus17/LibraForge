"""Per-book and per-series genre voting across sources (Enrichment Forge v2)."""
import unittest

from app.genre_voting import book_vote, vote_unit


def unit(votes, **kw):
    base = dict(series_labels=[], series_evidence=[], pf_progression=False, standalone=False)
    base.update(kw)
    return vote_unit(votes, **base)


class VotingTests(unittest.TestCase):
    def test_main_needs_two_sources_unless_strong(self):
        v = book_vote({"audible": ["thriller"], "audiosilo": ["horror"], "keywords": ["litrpg"]})
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

    def test_no_cap_on_main_genres(self):
        # Every genre the evidence supports is kept; no arbitrary cap.
        labels = ["fantasy", "thriller", "mystery", "horror", "humor", "litrpg"]
        r = unit([book_vote({"audible": labels, "audiosilo": labels})])
        self.assertEqual(r["main"], ["Fantasy", "LitRPG", "Thriller", "Mystery", "Horror", "Humor"])

    def test_no_votes_means_no_agreement(self):
        r = unit([book_vote({})], standalone=True)
        self.assertEqual((r["main"], r["agreement"]), ([], "none"))

    def test_books_without_votes_do_not_dilute_the_threshold(self):
        votes = [book_vote({"audible": ["horror"], "audiosilo": ["horror"]})] + [book_vote({}) for _ in range(7)]
        self.assertEqual(unit(votes)["main"], ["Horror"])


class LiveCalibrationTests(unittest.TestCase):
    """From the first live compiles against the benchmark (Cradle, Dragon
    Emperor, Intensity)."""

    def test_goodreads_shelf_alone_cannot_make_a_strong_main(self):
        # Cradle: readers shelve it as litrpg, but it is progression, not LitRPG.
        v = book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"], "goodreads": ["fantasy", "litrpg"]})
        self.assertNotIn("LitRPG", v["main"])
        corroborated = book_vote({"audible": ["fantasy"], "goodreads": ["fantasy", "litrpg"], "keywords": ["litrpg"]})
        self.assertIn("LitRPG", corroborated["main"])
        self.assertIn("LitRPG", book_vote({"audible": ["fantasy", "litrpg"], "goodreads": ["fantasy"]})["main"])

    def test_non_fiction_subgenres_stay_out_of_fiction(self):
        votes = [book_vote({"audible": ["thriller", "criminology"], "audiosilo": ["thriller", "criminology"]})]
        self.assertNotIn("True Crime", unit(votes)["sub"])


class EvidenceAndSuggestionTests(unittest.TestCase):
    """From the first real-browser run: subgenre chips had no evidence, and
    'other suggestions' showed raw source labels."""

    def test_subgenres_carry_evidence_too(self):
        votes = [book_vote({"audible": ["fantasy", "epic"], "audiosilo": ["epic fantasy", "fantasy"]}) for _ in range(2)]
        r = unit(votes)
        self.assertIn("Epic Fantasy", r["sub"])
        self.assertEqual(r["evidence"]["Epic Fantasy"], {"audible": 2, "audiosilo": 2})

    def test_candidates_are_taxonomy_names_that_missed_the_threshold(self):
        votes = [book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"]}) for _ in range(7)]
        votes.append(book_vote({"audible": ["fantasy", "romance", "sword & sorcery"], "audiosilo": ["fantasy", "romance"]}))
        r = unit(votes)
        self.assertEqual(r["main"], ["Fantasy"])
        self.assertIn("Romance", r["candidates"])
        self.assertIn("Sword & Sorcery", r["candidates"])
        self.assertNotIn("Fantasy", r["candidates"])
        self.assertFalse([c for c in r["candidates"] if c.endswith("?")])


class FinalReviewVotingTests(unittest.TestCase):
    def test_existing_abs_genres_alone_cannot_make_a_strong_main(self):
        # v1 wrote Goodreads' loose LitRPG into ABS genres; it must not come back on its own.
        self.assertNotIn("LitRPG", book_vote({"audible": ["fantasy"], "abs_existing": ["fantasy", "litrpg"]})["main"])

    def test_tie_break_never_picks_a_crowd_only_strong_genre(self):
        self.assertEqual(book_vote({"audible": ["thriller"], "goodreads": ["litrpg"]})["main"], {"Thriller"})


class ProgressionHierarchyTests(unittest.TestCase):
    """LitRPG and Cultivation are kinds of progression fantasy: when either is
    a main genre, Progression Fantasy is kept as a subgenre instead."""

    def test_litrpg_main_moves_progression_to_subgenre(self):
        votes = [book_vote({"audible": ["fantasy", "litrpg"], "audiosilo": ["fantasy", "litrpg", "progression fantasy"],
                            "keywords": ["progression fantasy"]}) for _ in range(3)]
        r = unit(votes)
        self.assertEqual(r["main"], ["Fantasy", "LitRPG"])
        self.assertIn("Progression Fantasy", r["sub"])

    def test_litrpg_implies_progression_subgenre_even_unnamed(self):
        r = unit([book_vote({"audible": ["fantasy", "litrpg"], "audiosilo": ["fantasy", "litrpg"]})])
        self.assertEqual(r["sub"][:1], ["Progression Fantasy"])
        self.assertEqual(r["evidence"]["Progression Fantasy"], {"implied": 1})

    def test_cultivation_is_a_main_genre(self):
        r = unit([book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"], "keywords": ["cultivation"]})])
        self.assertEqual(r["main"], ["Fantasy", "Cultivation"])
        self.assertIn("Progression Fantasy", r["sub"])

    def test_plain_progression_stays_main_without_litrpg_or_cultivation(self):
        r = unit([book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"], "keywords": ["progression fantasy"]})])
        self.assertEqual(r["main"], ["Fantasy", "Progression Fantasy"])

    def test_pf_non_litrpg_listing_confirms_goodreads_cultivation(self):
        # Cradle: Goodreads shelves it as cultivation; progressionfantasy.co.uk
        # lists it as non-LitRPG progression. Together: Cultivation.
        votes = [book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy"], "goodreads": ["fantasy", "cultivation", "litrpg"]})
                 for _ in range(4)]
        r = unit(votes, pf_progression=True)
        self.assertEqual(r["main"], ["Fantasy", "Cultivation"])
        self.assertIn("Progression Fantasy", r["sub"])
        self.assertIn("series-source", r["evidence"]["Cultivation"])

    def test_harem_pairs_with_romance(self):
        r = unit([book_vote({"audible": ["fantasy", "romance"], "audiosilo": ["romance", "harem"]})],
                 series_labels=["haremlit"], series_evidence=["HaremLit wiki: X"])
        self.assertIn("Harem", r["main"])
        self.assertIn("Romance", r["main"])
