import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_scoring", "scripts/audible-metadata-fixer-v5.py")


def product(
    *,
    asin="B0TEST0001",
    title="",
    subtitle="",
    series="",
    sequence="",
    authors=("Author X",),
    narrators=("Narrator Y",),
    minutes=600,
    year="2020-01-01",
    language="",
):
    return {
        "asin": asin,
        "title": title,
        "subtitle": subtitle,
        "series": [{"title": series, "sequence": sequence}] if series else [],
        "authors": [{"name": name} for name in authors],
        "narrators": [{"name": name} for name in narrators],
        "runtime_length_min": minutes,
        "release_date": year,
        "language": language,
    }


class PublisherNoiseTests(unittest.TestCase):
    def test_strips_standalone_bbc(self):
        self.assertEqual(
            FIXER.strip_publisher_search_noise("Undone Series 1 to 3 BBC Ben Moor"),
            "Undone Series 1 to 3 Ben Moor",
        )

    def test_strips_multiword_imprints(self):
        self.assertEqual(
            FIXER.strip_publisher_search_noise("Some Book Tantor Audio Jane Doe"),
            "Some Book Jane Doe",
        )

    def test_keeps_non_publisher_words(self):
        self.assertEqual(
            FIXER.strip_publisher_search_noise("The Subtle Art of Not Caring"),
            "The Subtle Art of Not Caring",
        )


class TitleNoiseTests(unittest.TestCase):
    def test_strips_listening_to_prefix_and_by_author_with_number(self):
        self.assertEqual(
            FIXER.strip_title_search_noise(
                "Listening to Dirk Gently's Holistic Detective Agency by Douglas Adams 1"
            ),
            "Dirk Gently's Holistic Detective Agency",
        )

    def test_preserves_legit_by_in_title(self):
        # No trailing number and no author hint: must not be mistaken for noise.
        self.assertEqual(
            FIXER.strip_title_search_noise("Death by Black Hole"),
            "Death by Black Hole",
        )

    def test_strips_by_author_when_name_matches_known_author(self):
        self.assertEqual(
            FIXER.strip_title_search_noise("Some Title by Jane Roe", "Jane Roe"),
            "Some Title",
        )

    def test_extract_author_requires_trailing_number(self):
        self.assertEqual(
            FIXER.extract_author_from_title(
                "Dirk Gently's Holistic Detective Agency by Douglas Adams 1"
            ),
            "Douglas Adams",
        )
        self.assertEqual(FIXER.extract_author_from_title("Death by Black Hole"), "")


class QueryBuildTests(unittest.TestCase):
    def test_dirk_gently_query_is_clean(self):
        clues = {
            "title": "Listening to Dirk Gently's Holistic Detective Agency by Douglas Adams 1",
            "raw_title": "Listening to Dirk Gently's Holistic Detective Agency by Douglas Adams 1",
            "series": "Dirk Gently - Douglas Adams",
            "author": "",
            "book_number": "1",
        }
        queries = FIXER.build_search_queries_from_clues(clues)
        self.assertIn(
            "Dirk Gently's Holistic Detective Agency Douglas Adams", queries
        )
        self.assertFalse(any("Listening to" in q for q in queries))

    def test_publisher_token_removed_from_queries(self):
        clues = {
            "title": "Undone Series 1 to 3",
            "raw_title": "Undone Series 1 to 3",
            "series": "",
            "author": "BBC Ben Moor",
            "book_number": "",
        }
        queries = FIXER.build_search_queries_from_clues(clues)
        self.assertTrue(queries)
        self.assertFalse(any("bbc" in q.lower() for q in queries))

    def test_goodreads_query_prefers_number_without_book_label(self):
        queries = FIXER.goodreads_title_query_variants("Between Heaven and Hell, Book 1")
        self.assertEqual(queries[0], "Between Heaven and Hell 1")
        self.assertIn("Between Heaven and Hell, Book 1", queries)


class PartBracketStripTests(unittest.TestCase):
    """sanitize_technical_labels should strip "[Series N - PartN]" brackets."""

    def _sanitize(self, value: str) -> str:
        return FIXER.sanitize_technical_labels(value)

    def test_strips_part_indicator_bracket_between_dashes(self):
        result = self._sanitize(
            "Logan Jacobs - [Rise, My Minions 3 - 1] - Rise, My Minions 3"
        )
        self.assertEqual(result, "Logan Jacobs - Rise, My Minions 3")

    def test_strips_bracket_without_series_number(self):
        result = self._sanitize(
            "Logan Jacobs - [Kingdom of the Dragon Crystals - 1] - Kingdom of the Dragon Crystals"
        )
        self.assertEqual(result, "Logan Jacobs - Kingdom of the Dragon Crystals")

    def test_does_not_strip_narrator_brackets(self):
        # "Hel Rose, Will Rose" ends in a name, not "- N"
        result = self._sanitize("First Leash {Hel Rose, Will Rose}")
        self.assertIn("Hel Rose", result)

    def test_does_not_strip_asin_brackets(self):
        # ASIN brackets don't end in "- N" so they are not touched by the new rule
        result = self._sanitize("A Modern Mage 3 [B0H12BTSRK]")
        self.assertIn("B0H12BTSRK", result)

    def test_parse_rise_my_minions_extracts_correct_title(self):
        result = FIXER.parse_descriptive_book_text(
            "Logan Jacobs - [Rise, My Minions 3 - 1] - Rise, My Minions 3",
            known_author="Logan Jacobs",
        )
        self.assertEqual(result.get("title"), "Rise, My Minions 3")
        self.assertEqual(result.get("author"), "Logan Jacobs")

    def test_parse_kingdom_extracts_correct_title(self):
        result = FIXER.parse_descriptive_book_text(
            "Logan Jacobs - [Kingdom of the Dragon Crystals - 1] - Kingdom of the Dragon Crystals",
            known_author="Logan Jacobs",
        )
        self.assertEqual(result.get("title"), "Kingdom of the Dragon Crystals")
        self.assertEqual(result.get("author"), "Logan Jacobs")


class SequenceLeniencyTests(unittest.TestCase):
    def setUp(self):
        self.clues = {
            "title": "Power Mage 5",
            "raw_title": "Power Mage 5",
            "series": "Power Mage",
            "author": "Author X",
            "narrator": "Narrator Y",
            "book_number": "5",
            "book_number_source": "title",
        }

    def test_adjacent_series_book_rejected(self):
        wrong = product(asin="B06", title="Power Mage 6", series="Power Mage", sequence="6", minutes=605)
        self.assertTrue(FIXER.has_sequence_conflict(self.clues, wrong, 600.0))
        self.assertEqual(FIXER.score_product_for_metadata(self.clues, wrong, 600.0), 0.0)

    def test_correct_book_scores_high(self):
        right = product(asin="B05", title="Power Mage 5", series="Power Mage", sequence="5", minutes=601)
        self.assertGreaterEqual(
            FIXER.score_product_for_metadata(self.clues, right, 600.0), 0.70
        )

    def test_parallel_series_numbering_still_allowed(self):
        clues = {
            "title": "Of Dawn and Darkness",
            "raw_title": "Book 003 - Of Dawn and Darkness",
            "series": "The Elder Empire Sea",
            "author": "Will Wight",
            "narrator": "Nar",
            "book_number": "3",
            "book_number_source": "path",
        }
        par = product(
            asin="B0PAR", title="Of Dawn and Darkness", series="The Elder Empire Sea",
            sequence="2", authors=("Will Wight",), narrators=("Nar",), minutes=601,
        )
        self.assertFalse(FIXER.has_sequence_conflict(clues, par, 600.0))


class OmnibusRangeTests(unittest.TestCase):
    def setUp(self):
        self.clues = {
            "title": "Legend of the Arch Magus - Books 011-012",
            "raw_title": "Legend of the Arch Magus - Books 011-012",
            "series": "Legend of the Arch Magus",
            "author": "Michael Sisa",
            "narrator": "Justin Thomas James",
            "book_number": "",
            "book_number_source": "",
        }
        self.pack6 = product(
            asin="B0PACK6", title="Legend of the Arch Magus: Publisher's Pack 6",
            subtitle="Books 11-12", series="Legend of the Arch Magus", sequence="11-12",
            authors=("Michael Sisa",), narrators=("Justin Thomas James",), minutes=811,
        )
        self.pack7 = product(
            asin="B0PACK7", title="Legend of the Arch Magus: Publisher's Pack 7",
            subtitle="Books 13-14", series="Legend of the Arch Magus", sequence="13-14",
            authors=("Michael Sisa",), narrators=("Justin Thomas James",), minutes=811,
        )

    def test_exact_range_matches(self):
        self.assertEqual(FIXER.omnibus_range_relation(self.clues, self.pack6), "match")
        self.assertGreaterEqual(
            FIXER.score_product_for_metadata(self.clues, self.pack6, 820.0), 0.70
        )

    def test_different_range_rejected(self):
        self.assertEqual(FIXER.omnibus_range_relation(self.clues, self.pack7), "conflict")
        self.assertEqual(
            FIXER.score_product_for_metadata(self.clues, self.pack7, 820.0), 0.0
        )

    def test_parse_range_variants(self):
        self.assertEqual(FIXER.parse_book_number_range("Books 11-12"), (11, 12))
        self.assertEqual(FIXER.parse_book_number_range("11 to 12"), (11, 12))
        self.assertEqual(FIXER.parse_book_number_range("Books 011 012"), (11, 12))
        self.assertIsNone(FIXER.parse_book_number_range("Just a Title"))

    def test_local_omnibus_title_can_full_match_omnibus_product(self):
        clues = {
            "title": "After the End Omnibus",
            "raw_title": "After the End Omnibus: Books 1-3 [B0DMTPP1V8]",
            "series": "Dante King - After the End",
            "author": "Dante King",
            "narrator": "Melanie Hastings, Jonathan Waters",
            "book_number": "1",
            "book_number_source": "path",
        }
        candidate = product(
            asin="B0DMTQ1FK7",
            title="After the End Omnibus",
            subtitle="Books 1-3",
            series="After the End",
            sequence="1-3",
            authors=("Dante King",),
            narrators=("Melanie Hastings", "Jonathan Waters"),
            minutes=2088,
        )
        duration = FIXER.compare_duration(2088.34, candidate["runtime_length_min"])
        score = FIXER.score_product_for_metadata(clues, candidate, 2088.34)

        self.assertEqual(score, 1.0)
        self.assertEqual(
            FIXER.determine_edit_mode(candidate, clues, score, duration),
            "full",
        )


class TieBreakTests(unittest.TestCase):
    def setUp(self):
        self.clues = {
            "title": "Power Mage 5",
            "raw_title": "Power Mage 5",
            "series": "Power Mage",
            "author": "Author X",
            "narrator": "Narrator Y",
            "book_number": "5",
            "book_number_source": "title",
        }

    def _twin(self, asin, minutes):
        # Same identity, differing only in duration exactness.
        return product(asin=asin, title="Power Mage 5", series="Power Mage", sequence="5", minutes=minutes)

    def test_perfect_beats_strong_resolved(self):
        perfect = self._twin("B0PERF", 601)
        strong = self._twin("B0STRG", 650)
        chosen, score, ambiguity = FIXER.pick_best_match_for_metadata(
            self.clues, [strong, perfect], 600.0
        )
        self.assertEqual(chosen["asin"], "B0PERF")
        self.assertIsNotNone(ambiguity)
        self.assertTrue(ambiguity["resolved"])

    def test_perfect_vs_perfect_clear_winner(self):
        close = self._twin("B0CLOSE", 600)
        near = self._twin("B0NEAR", 601.2)  # ~72s vs 0s -> gap > 30s
        chosen, _score, ambiguity = FIXER.pick_best_match_for_metadata(
            self.clues, [near, close], 600.0
        )
        self.assertEqual(chosen["asin"], "B0CLOSE")
        self.assertTrue(ambiguity["resolved"])

    def test_true_tie_unresolved(self):
        a = self._twin("B0TIE1", 600.0)
        b = self._twin("B0TIE2", 600.1)  # ~6s apart -> below 30s margin
        _chosen, _score, ambiguity = FIXER.pick_best_match_for_metadata(
            self.clues, [a, b], 600.0
        )
        self.assertIsNotNone(ambiguity)
        self.assertFalse(ambiguity["resolved"])

    def test_single_candidate_no_ambiguity(self):
        only = self._twin("B0ONLY", 601)
        _chosen, _score, ambiguity = FIXER.pick_best_match_for_metadata(
            self.clues, [only], 600.0
        )
        self.assertIsNone(ambiguity)


class CrossSeriesSameAuthorTests(unittest.TestCase):
    """Arena Road 3-5 matched Arena, Book 3-5 -- same author, different series.

    "Arena" is a substring of "Arena Road", so the series containment check
    was setting series_score = 1.0, and book numbers coincidentally aligned.
    The combined score was ~0.94-1.0 (above the 0.70 gate).
    """

    def _arena_road_clues(self, n: int) -> dict:
        return {
            "title": f"Arena Road {n}",
            "raw_title": f"Arena Road {n}",
            "series": "Arena Road",
            "author": "Logan Jacobs",
            "narrator": "",
            "book_number": str(n),
            "book_number_source": "path",
        }

    # (local_minutes, audible_minutes) from the 20260629 run report
    _ARENA_ROAD_DURATIONS = {
        3: (453.0, 513.0),   # 11.67% diff -> acceptable
        4: (631.0, 547.0),   # 13.3%  diff -> acceptable
        5: (590.0, 487.0),   # 17.4%  diff -> acceptable
    }

    def _arena_product(self, n: int, comma: bool = True) -> dict:
        title = f"Arena, Book {n}" if comma else f"Arena Book {n}"
        _local, aud_min = self._ARENA_ROAD_DURATIONS[n]
        return product(
            asin=f"B0ARENA{n:02d}",
            title=title,
            series="Arena",
            sequence=str(n),
            authors=("Logan Jacobs",),
            narrators=("Joshua Story",),
            minutes=aud_min,
        )

    def test_arena_road_3_does_not_match_arena_book_3(self):
        local_min, _ = self._ARENA_ROAD_DURATIONS[3]
        score = FIXER.score_product_for_metadata(
            self._arena_road_clues(3), self._arena_product(3, comma=True), local_min
        )
        self.assertLess(score, 0.70, f"Arena Road 3 should not match Arena, Book 3 (score={score})")

    def test_arena_road_4_does_not_match_arena_book_4(self):
        local_min, _ = self._ARENA_ROAD_DURATIONS[4]
        score = FIXER.score_product_for_metadata(
            self._arena_road_clues(4), self._arena_product(4, comma=False), local_min
        )
        self.assertLess(score, 0.70, f"Arena Road 4 should not match Arena Book 4 (score={score})")

    def test_arena_road_5_does_not_match_arena_book_5(self):
        local_min, _ = self._ARENA_ROAD_DURATIONS[5]
        score = FIXER.score_product_for_metadata(
            self._arena_road_clues(5), self._arena_product(5, comma=True), local_min
        )
        self.assertLess(score, 0.70, f"Arena Road 5 should not match Arena, Book 5 (score={score})")

    def test_arena_book_1_still_matches_arena_1(self):
        """Actual Arena series books should still match the Arena series."""
        clues = {
            "title": "Arena 1",
            "raw_title": "Arena 1",
            "series": "Arena",
            "author": "Logan Jacobs",
            "narrator": "",
            "book_number": "1",
            "book_number_source": "path",
        }
        p = product(
            asin="B0ARENA01",
            title="Arena",
            series="Arena",
            sequence="1",
            authors=("Logan Jacobs",),
            minutes=520,
        )
        score = FIXER.score_product_for_metadata(clues, p, 520.0)
        self.assertGreaterEqual(score, 0.70, f"Arena 1 should match Arena series (score={score})")

    def test_the_prefix_does_not_break_series_match(self):
        """'Iron Teeth' local vs 'The Iron Teeth' Audible should still match."""
        clues = {
            "title": "Iron Teeth 3",
            "raw_title": "Iron Teeth 3",
            "series": "Iron Teeth",
            "author": "C. Stelter",
            "narrator": "Narrator",
            "book_number": "3",
            "book_number_source": "path",
        }
        p = product(
            asin="B0IRON03",
            title="Iron Teeth 3",
            series="The Iron Teeth",
            sequence="3",
            authors=("C. Stelter",),
            narrators=("Narrator",),
            minutes=600,
        )
        score = FIXER.score_product_for_metadata(clues, p, 600.0)
        self.assertGreaterEqual(score, 0.70, f"Iron Teeth 3 should still match The Iron Teeth 3 (score={score})")


class LanguagePenaltyTests(unittest.TestCase):
    """Non-English editions must not beat an English match via duration coincidence.

    e.g. "Le Hobbit" or "Herejes de Dune" scoring above an English original
    because runtime happened to align.
    """

    def test_non_english_product_is_penalized(self):
        clues = {
            "title": "Dune Messiah",
            "raw_title": "Dune Messiah",
            "author": "Frank Herbert",
            "narrator": "",
            "book_number": "",
            "book_number_source": "",
        }
        p = product(
            asin="B0DUNEFR",
            title="Dune Messiah",
            authors=("Frank Herbert",),
            minutes=600,
            language="french",
        )
        p_en = product(
            asin="B0DUNEEN",
            title="Dune Messiah",
            authors=("Frank Herbert",),
            minutes=600,
            language="english",
        )
        score_fr = FIXER.score_product_for_metadata(clues, p, 600.0)
        score_en = FIXER.score_product_for_metadata(clues, p_en, 600.0)
        self.assertLess(score_fr, score_en)

    def test_missing_language_is_not_penalized(self):
        clues = {
            "title": "Dune Messiah",
            "raw_title": "Dune Messiah",
            "author": "Frank Herbert",
            "narrator": "",
            "book_number": "",
            "book_number_source": "",
        }
        p = product(asin="B0DUNE01", title="Dune Messiah", authors=("Frank Herbert",), minutes=600)
        score_no_lang = FIXER.score_product_for_metadata(clues, p, 600.0)
        p_en = product(
            asin="B0DUNE02",
            title="Dune Messiah",
            authors=("Frank Herbert",),
            minutes=600,
            language="english",
        )
        score_en = FIXER.score_product_for_metadata(clues, p_en, 600.0)
        self.assertEqual(score_no_lang, score_en)


class MissingCandidateSequenceTests(unittest.TestCase):
    """A candidate that carries no sequence info at all must not be trusted as
    confidently as one that confirms the local book number.

    Regression (2026-07-04 matcher run against real _unorganized data):
    "Building Harem Town 2" (local book_number=2, path-sourced) matched an
    Audible entry with empty series/sequence at score 0.80 (full write) via
    the title_score>=0.75 duration-confirmed floor -- that entry is a
    different book in the series (or an incomplete catalog listing), not
    book 2. Same pattern hit Dragon Conjurer 2-9 and The Duelist 2-3.
    """

    def test_missing_candidate_sequence_does_not_reach_high_confidence_floor(self):
        clues = {
            "title": "Building Harem Town 2",
            "raw_title": "Building Harem Town 2",
            "author": "Eric Vall",
            "narrator": "",
            "series": "Building Harem Town",
            "book_number": "2",
            "book_number_source": "path",
        }
        p = product(
            asin="B0HAREM01",
            title="Building Harem Town",
            authors=("Eric Vall",),
            minutes=634.02,
        )
        score = FIXER.score_product_for_metadata(clues, p, 634.0237324333334)
        self.assertLess(score, 0.80)

    def test_confirmed_candidate_sequence_still_reaches_high_confidence(self):
        """The guard must not suppress a genuinely confirmed sequence match."""
        clues = {
            "title": "Building Harem Town 5",
            "raw_title": "Building Harem Town 5",
            "author": "Eric Vall",
            "narrator": "",
            "series": "Building Harem Town",
            "book_number": "5",
            "book_number_source": "path",
        }
        p = product(
            asin="B0HAREM05",
            title="Building Harem Town 5",
            series="Building Harem Town",
            sequence="5",
            authors=("Eric Vall",),
            minutes=634.0,
        )
        score = FIXER.score_product_for_metadata(clues, p, 634.0)
        self.assertGreaterEqual(score, 0.80)

    def test_weak_track_derived_number_is_not_guarded(self):
        """Track-derived numbers are weak metadata; do not gate on them."""
        clues = {
            "title": "Some Book 2",
            "raw_title": "Some Book 2",
            "author": "Eric Vall",
            "narrator": "",
            "series": "Some Book",
            "book_number": "2",
            "book_number_source": "track",
        }
        p = product(
            asin="B0SOME01",
            title="Some Book",
            authors=("Eric Vall",),
            minutes=634.02,
        )
        score = FIXER.score_product_for_metadata(clues, p, 634.0237324333334)
        self.assertGreaterEqual(score, 0.80)


class RecurringSubtitleSequenceConflictTests(unittest.TestCase):
    """A recurring saga tagline shared across many books must not override a
    confident, explicit sequence disagreement in the same series.

    Regression (2026-07-04 matcher run): local "Dragon Emperor 9" (sequence 9
    from both folder and filename) has embedded title "From Human to Dragon
    to God" -- a tagline this series reuses loosely across several volumes
    (book 8: "Human to Dragon to God", book 13: "From Human to Dragon to
    God"). It matched Audible's "Dragon Emperor 12" (sequence 12) at score
    1.0 full write via the parallel/companion-series leniency in
    has_sequence_conflict(), which forgives title+duration+author agreement
    regardless of how large the sequence gap is. That leniency exists for a
    real case (different numbering *schemes*, e.g. an omnibus-numbered local
    book 3 matching a differently-numbered sub-series book 2 -- see
    test_parallel_series_numbering_still_allowed) where the gap is a small,
    consistent offset. A 3-book gap in the *same* series numbering is not a
    scheme difference; it's the wrong book.
    """

    def test_large_sequence_gap_in_same_series_is_a_conflict(self):
        clues = {
            "title": "From Human to Dragon to God",
            "raw_title": "From Human to Dragon to God",
            "series": "Dragon Emperor",
            "author": "Eric Vall",
            "narrator": "",
            "book_number": "9",
            "book_number_source": "path",
        }
        p = product(
            asin="B0DRAGON12",
            title="Dragon Emperor 12",
            subtitle="From Human to Dragon to God",
            series="Dragon Emperor",
            sequence="12",
            authors=("Eric Vall",),
            narrators=("Alex Perone", "Marissa Parness"),
            minutes=470.0,
        )
        self.assertTrue(FIXER.has_sequence_conflict(clues, p, 480.03))
        self.assertLess(FIXER.score_product_for_metadata(clues, p, 480.03), 0.70)

    def test_adjacent_gap_parallel_numbering_still_allowed(self):
        """Existing off-by-one companion-numbering leniency must survive."""
        clues = {
            "title": "Of Dawn and Darkness",
            "raw_title": "Book 003 - Of Dawn and Darkness",
            "series": "The Elder Empire Sea",
            "author": "Will Wight",
            "narrator": "Nar",
            "book_number": "3",
            "book_number_source": "path",
        }
        par = product(
            asin="B0PAR", title="Of Dawn and Darkness", series="The Elder Empire Sea",
            sequence="2", authors=("Will Wight",), narrators=("Nar",), minutes=601,
        )
        self.assertFalse(FIXER.has_sequence_conflict(clues, par, 600.0))


class SubstringSeriesCoincidentalMatchTests(unittest.TestCase):
    """A partial-substring series name (not confirmed as the same series by
    the token-jaccard bar) must not let its raw SequenceMatcher ratio inflate
    the additive score enough to clear min_score on its own.

    Regression (2026-07-04 matcher run): local "Summoner School 2" (series
    "Summoner School") matched Audible "Summoner 2" (series "Summoner") at
    score 0.8128 -- a different, shorter series by the same prolific author
    that happens to share the word "summoner" and, coincidentally, book
    number 2. The jaccard gate already blocks forcing series_score to 1.0
    and blocks crediting the sequence-match bonus (see
    CrossSeriesSameAuthorTests for the Arena/Arena Road case this
    protects), but the raw substring-inflated SequenceMatcher ratio still
    flows into the additive score at full strength.
    """

    def test_summoner_school_2_does_not_match_summoner_2(self):
        clues = {
            "title": "Summoner School 2",
            "raw_title": "Summoner School 2",
            "series": "Summoner School",
            "author": "Eric Vall",
            "narrator": "",
            "book_number": "2",
            "book_number_source": "path",
        }
        p = product(
            asin="B07MXR8LR9",
            title="Summoner 2",
            series="Summoner",
            sequence="2",
            authors=("Eric Vall",),
            narrators=("Joshua Story",),
            minutes=458.0,
        )
        score = FIXER.score_product_for_metadata(clues, p, 458.6784981166667)
        self.assertLess(score, 0.70, f"score={score}")


if __name__ == "__main__":
    unittest.main()
