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


if __name__ == "__main__":
    unittest.main()
