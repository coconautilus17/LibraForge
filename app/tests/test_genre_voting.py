"""Per-book and per-series genre voting across sources (Enrichment Forge v2)."""
import unittest

from app import genre_voting as gv
from app.genre_voting import book_vote, vote_unit


def unit(votes, **kw):
    base = dict(series_labels=[], series_evidence=[], pf_progression=False, standalone=False)
    base.update(kw)
    return vote_unit(votes, **base)


class VotingTests(unittest.TestCase):
    def test_one_editorial_source_is_enough_crowd_sources_need_each_other(self):
        v = book_vote({"audible": ["thriller"], "goodreads": ["horror"], "openlibrary": ["romance", "horror"], "keywords": ["litrpg"]})
        self.assertIn("Thriller", v["main"])   # Audible alone: editorial
        self.assertIn("LitRPG", v["main"])     # publisher summary keywords: editorial
        self.assertIn("Horror", v["main"])     # Goodreads + Open Library agree
        self.assertNotIn("Romance", v["main"])  # Open Library alone: crowd

    def test_file_tags_are_editorial(self):
        self.assertEqual(book_vote({"file_tags": ["thriller"], "goodreads": ["fantasy"]})["main"], {"Thriller"})

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


class PinnedGenresTests(unittest.TestCase):
    """Genres the user set by hand in Audiobookshelf are pinned: always kept,
    never outvoted; sources only add to them."""

    def test_pinned_main_survives_without_any_source_support(self):
        votes = [book_vote({"audible": ["fantasy"]}) for _ in range(3)]
        r = unit(votes, pinned={"Horror": 1})
        self.assertIn("Horror", r["main"])
        self.assertEqual(r["evidence"]["Horror"], {"yours": 1})
        self.assertIn("Horror", r["pinned"])

    def test_pinned_unknown_genre_keeps_the_users_wording_as_subgenre(self):
        r = unit([book_vote({"audible": ["thriller"]})], pinned={"Small Town": 2})
        self.assertIn("Small Town", r["sub"])
        self.assertIn("Small Town", r["pinned"])

    def test_pinned_beats_conflict_rules(self):
        votes = [book_vote({"audible": ["science fiction"]}) for _ in range(5)]
        self.assertIn("Fantasy", unit(votes, pinned={"Fantasy": 1})["main"])

    def test_pinned_alone_is_agreement(self):
        r = unit([book_vote({})], pinned={"Thriller": 1}, standalone=True)
        self.assertEqual((r["main"], r["agreement"]), (["Thriller"], "ok"))


class CuratedListAuthorityTests(unittest.TestCase):
    def test_a_non_litrpg_listing_overrules_litrpg_from_blurbs_and_shelves(self):
        # A Thousand Li: blurbs mention the author's LitRPG series; readers
        # shelve it litrpg; progressionfantasy.co.uk lists it as non-LitRPG.
        votes = [book_vote({"audible": ["fantasy"], "keywords": ["litrpg", "cultivation"],
                            "goodreads": ["fantasy", "litrpg", "cultivation"]}) for _ in range(4)]
        r = unit(votes, pf_progression=True)
        self.assertNotIn("LitRPG", r["main"])
        self.assertIn("Cultivation", r["main"])
        self.assertIn("LitRPG", r["candidates"])  # still one click away

    def test_a_pinned_litrpg_still_wins(self):
        votes = [book_vote({"audible": ["fantasy"], "keywords": ["litrpg"]}) for _ in range(2)]
        self.assertIn("LitRPG", unit(votes, pf_progression=True, pinned={"LitRPG": 1})["main"])


class AudioSiloIsCrowdTests(unittest.TestCase):
    """AudioSilo's genres are mostly Audible categories auto-mapped by bulk
    imports plus contributor submissions: crowd weight, not editorial."""

    def test_audiosilo_alone_is_not_enough(self):
        self.assertEqual(book_vote({"audible": ["fantasy"], "audiosilo": ["fantasy", "science fiction", "humor"]})["main"], {"Fantasy"})

    def test_audiosilo_with_another_crowd_source_is(self):
        self.assertIn("Humor", book_vote({"audiosilo": ["humor"], "goodreads": ["humor"]})["main"])


def _vote(**voters):
    return gv.book_vote({k.replace("_", ""): v for k, v in voters.items()})


def _unit(books, **kw):
    kw.setdefault("series_labels", [])
    kw.setdefault("series_evidence", [])
    kw.setdefault("pf_progression", False)
    kw.setdefault("standalone", False)
    return gv.vote_unit(books, **kw)


class BookVoteWeightTests(unittest.TestCase):
    def test_an_editorial_source_weighs_two_and_passes_alone(self):
        for source in ("audible", "file_tags", "keywords"):
            with self.subTest(source=source):
                self.assertEqual(gv.book_vote({source: ["fantasy"]})["main"], {"Fantasy"})

    def test_a_crowd_source_alone_goes_through_the_fallback_with_its_evidence(self):
        vote = gv.book_vote({"goodreads": ["romance"]})
        self.assertEqual(vote["main"], {"Romance"})
        self.assertEqual(vote["evidence"], {"Romance": {"goodreads"}})

    def test_two_crowd_sources_agreeing_pass_by_weight(self):
        vote = gv.book_vote({"goodreads": ["fantasy"], "openlibrary": ["fantasy"]})
        self.assertEqual(vote["main"], {"Fantasy"})
        self.assertEqual(vote["evidence"]["Fantasy"], {"goodreads", "openlibrary"})

    def test_an_unknown_source_counts_as_crowd_weight_one(self):
        vote = gv.book_vote({"mystery-source": ["fantasy"], "goodreads": ["fantasy"]})
        self.assertEqual(vote["main"], {"Fantasy"})

    def test_a_main_above_the_bar_makes_the_fallback_unnecessary(self):
        vote = gv.book_vote({"audible": ["fantasy"], "goodreads": ["romance"]})
        self.assertEqual(vote["main"], {"Fantasy"})
        self.assertEqual(vote["other"], {"Romance"})

    def test_disagreeing_crowd_sources_keep_at_most_two_in_taxonomy_order(self):
        vote = gv.book_vote({"goodreads": ["romance"], "openlibrary": ["science fiction"], "audiosilo": ["fantasy"]})
        self.assertEqual(vote["main"], {"Fantasy", "Sci-Fi"})
        self.assertEqual(vote["other"], {"Romance"})

    def test_the_fallback_prefers_the_best_supported_genre(self):
        vote = gv.book_vote({"goodreads": ["thriller"], "openlibrary": ["thriller"], "audiosilo": ["horror"],
                             "abs_existing": ["romance"]})
        self.assertEqual(vote["main"], {"Thriller"})

    def test_a_strong_genre_never_wins_on_crowd_shelving_alone(self):
        self.assertEqual(gv.book_vote({"goodreads": ["litrpg"]})["main"], set())
        self.assertEqual(gv.book_vote({"goodreads": ["litrpg"], "openlibrary": ["romance"]})["main"], {"Romance"})

    def test_subgenres_are_counted_per_source_with_their_evidence(self):
        vote = gv.book_vote({"audible": ["space opera"], "goodreads": ["space opera"]})
        self.assertEqual(vote["sub"]["Space Opera"], 2)
        self.assertEqual(vote["sub_evidence"]["Space Opera"], {"audible", "goodreads"})


class PlacePinnedTests(unittest.TestCase):
    def test_a_known_genre_lands_on_its_controlled_main_and_sub(self):
        self.assertEqual(gv.place_pinned("History"), (["Non-Fiction"], ["History"]))

    def test_an_ambiguous_question_marked_subgenre_is_not_pinned_as_such(self):
        mains, subs = gv.place_pinned("Epic")
        self.assertEqual(mains, [])
        self.assertTrue(all(not s.endswith("?") for s in subs))

    def test_an_unknown_name_keeps_the_users_wording_trimmed_as_a_subgenre(self):
        self.assertEqual(gv.place_pinned("  Zxqwv Unknown Whatever "), ([], ["Zxqwv Unknown Whatever"]))


class VoteUnitRuleTests(unittest.TestCase):
    def _books(self, **counts):
        """counts: genre label -> number of books (each an editorial vote)."""
        books = []
        for label, n in counts.items():
            books += [gv.book_vote({"audible": [label.replace("_", " ")]}) for _ in range(n)]
        return books

    def test_a_small_series_needs_one_book_a_big_one_a_quarter(self):
        self.assertEqual(_unit(self._books(fantasy=3, romance=1))["main"], ["Fantasy", "Romance"])
        self.assertEqual(_unit(self._books(fantasy=7, romance=1))["main"], ["Fantasy"])
        self.assertEqual(_unit(self._books(fantasy=6, romance=2))["main"], ["Fantasy", "Romance"])

    def test_fantasy_and_scifi_both_stay_only_when_neither_is_under_half_the_other(self):
        self.assertEqual(_unit(self._books(fantasy=4, science_fiction=2))["main"], ["Fantasy", "Sci-Fi"])
        self.assertEqual(_unit(self._books(fantasy=5, science_fiction=2))["main"], ["Fantasy"])
        self.assertEqual(_unit(self._books(fantasy=2, science_fiction=5))["main"], ["Sci-Fi"])

    def test_non_fiction_wins_only_when_it_outvotes_every_fiction_genre(self):
        self.assertEqual(_unit(self._books(history=3, fantasy=1))["main"], ["Non-Fiction"])
        self.assertEqual(_unit(self._books(history=1, fantasy=3))["main"], ["Fantasy"])
        self.assertEqual(_unit(self._books(history=2, fantasy=2))["main"], ["Fantasy"])

    def test_classics_needs_half_of_the_voting_books(self):
        self.assertEqual(_unit(self._books(classics=1, fantasy=3))["main"], ["Fantasy"])
        self.assertIn("Classics", _unit(self._books(classics=2, fantasy=2))["main"])
        self.assertIn("Classics", _unit(self._books(classics=1))["main"])

    def test_litrpg_filed_under_cyberpunk_is_not_science_fiction_without_a_real_sf_subgenre(self):
        books = [gv.book_vote({"audible": ["litrpg", "cyberpunk"]}) for _ in range(3)]
        result = _unit(books)
        self.assertIn("LitRPG", result["main"])
        self.assertNotIn("Sci-Fi", result["main"])
        self.assertNotIn("Cyberpunk", result["sub"])

    def test_a_real_sf_subgenre_keeps_science_fiction_next_to_litrpg(self):
        books = [gv.book_vote({"audible": ["litrpg", "cyberpunk", "space opera"]}) for _ in range(3)]
        result = _unit(books)
        self.assertIn("LitRPG", result["main"])
        self.assertIn("Sci-Fi", result["main"])

    def test_non_fiction_units_keep_only_non_fiction_subgenres(self):
        books = [gv.book_vote({"audible": ["history"]}) for _ in range(3)]
        books.append(gv.book_vote({"audible": ["history", "dragons"]}))
        result = _unit(books)
        self.assertEqual(result["main"], ["Non-Fiction"])
        self.assertIn("History", result["sub"])
        self.assertNotIn("Dragons", result["sub"])

    def test_fiction_units_drop_non_fiction_subgenres(self):
        books = [gv.book_vote({"audible": ["fantasy", "history"]}) for _ in range(2)]
        result = _unit(books)
        self.assertIn("Fantasy", result["main"])
        self.assertNotIn("History", result["sub"])

    def test_subgenres_are_sorted_by_votes_then_name_and_capped(self):
        books = [gv.book_vote({"audible": ["fantasy", "dragons"]}) for _ in range(2)]
        books += [gv.book_vote({"audible": ["fantasy"]})]
        result = _unit(books)
        self.assertEqual(result["sub"][0], "Dragons")
        self.assertLessEqual(len(result["sub"]), gv.MAX_SUBS)

    def test_pinned_main_is_added_pinned_sub_goes_first_and_both_carry_pinned_evidence(self):
        books = self._books(fantasy=2)
        result = _unit(books, pinned={"Romance": 4, "Zxqwv Unknown": 2})
        self.assertIn("Romance", result["main"])
        self.assertEqual(result["sub"][0], "Zxqwv Unknown")
        self.assertEqual(result["evidence"]["Romance"][gv.PINNED_SOURCE], 4)
        self.assertEqual(result["evidence"]["Zxqwv Unknown"][gv.PINNED_SOURCE], 2)
        self.assertEqual(result["pinned"], ["Romance", "Zxqwv Unknown"])

    def test_a_pinned_sub_that_is_already_a_main_is_not_duplicated(self):
        result = _unit(self._books(fantasy=2), pinned={"Fantasy": 1})
        self.assertEqual(result["main"].count("Fantasy"), 1)
        self.assertNotIn("Fantasy", result["sub"])

    def test_candidates_are_mentioned_genres_that_missed_out_and_exclude_pinned_names(self):
        books = self._books(fantasy=8) + [gv.book_vote({"audible": ["romance"]})]
        unit = _unit(books)
        self.assertIn("Romance", unit["candidates"])
        pinned = _unit(books, pinned={"Romance": 1})
        self.assertNotIn("Romance", pinned["candidates"])

    def test_non_fiction_subgenres_are_candidates_only_for_non_fiction_units(self):
        fiction = _unit(self._books(fantasy=8) + [gv.book_vote({"audible": ["history"]})])
        self.assertNotIn("History", fiction["candidates"])

    def test_progression_series_listing_adds_progression_and_counts_as_evidence(self):
        books = self._books(fantasy=2)
        unit = _unit(books, pf_progression=True, series_evidence=["pf"])
        self.assertIn("Progression Fantasy", unit["main"])
        self.assertEqual(unit["series_evidence"], ["pf"])
        self.assertEqual(unit["evidence"]["Progression Fantasy"][gv.SERIES_SOURCE], 1)

    def test_standalone_ignores_series_level_sources_and_evidence(self):
        unit = _unit(self._books(fantasy=1), pf_progression=True, series_evidence=["pf"], standalone=True,
                     series_labels=["romance"])
        self.assertEqual(unit["main"], ["Fantasy"])
        self.assertEqual(unit["series_evidence"], [])

    def test_series_labels_count_as_full_support(self):
        unit = _unit(self._books(fantasy=8), series_labels=["romance"])
        self.assertIn("Romance", unit["main"])
        self.assertEqual(unit["evidence"]["Romance"][gv.SERIES_SOURCE], 1)

    def test_progression_listing_is_distrusted_when_a_mainstream_genre_conflicts_uncorroborated(self):
        books = self._books(mystery=3)
        unit = _unit(books, pf_progression=True)
        self.assertNotIn("Progression Fantasy", unit["main"])
        self.assertIn("Mystery", unit["main"])

    def test_progression_listing_is_trusted_when_corroborated_by_a_book_mention(self):
        books = self._books(mystery=3) + [gv.book_vote({"audible": ["progression fantasy"]})]
        unit = _unit(books, pf_progression=True)
        self.assertIn("Progression Fantasy", unit["main"] + unit["sub"])


class VoteUnitCornerTests(unittest.TestCase):
    def test_science_fiction_with_cyberpunk_is_kept_when_litrpg_is_not_a_main(self):
        books = [gv.book_vote({"audible": ["science fiction", "cyberpunk"]}) for _ in range(3)]
        result = _unit(books)
        self.assertEqual(result["main"], ["Sci-Fi"])
        self.assertIn("Cyberpunk", result["sub"])

    def test_a_progression_listing_is_corroborated_by_a_mere_mention_in_a_book(self):
        books = [gv.book_vote({"audible": ["mystery"]}) for _ in range(3)]
        books.append(gv.book_vote({"audible": ["mystery"], "goodreads": ["progression fantasy"]}))
        unit = _unit(books, pf_progression=True)
        self.assertIn("Progression Fantasy", unit["main"])

    def test_a_pinned_subgenre_that_the_vote_already_found_is_not_listed_twice(self):
        books = [gv.book_vote({"audible": ["fantasy", "dragons"]}) for _ in range(2)]
        result = _unit(books, pinned={"Dragons": 1})
        self.assertEqual(result["sub"].count("Dragons"), 1)
