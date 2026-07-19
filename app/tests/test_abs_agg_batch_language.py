"""_abs_match_to_product (app/fixer/search.py): the batch/automated-run
abs-agg normalizer silently dropped every provider's real "language" field,
unlike the interactive-search path. Found live during LibriVox verification
(docs/... provider-verification workstream): a plain "Frankenstein" query
against the real abs-agg LibriVox endpoint returns English, German, and
Spanish readings of the same public-domain work side by side (LibriVox has
no language-filter param, unlike Storytel/Audioteka/BookBeat) -- so a batch
run genuinely risks scoring a foreign-language reading as a match for an
English local book, with nothing to catch it. The scoring engine's language
penalty (app/fixer/scoring.py score_product_for_metadata) already reads
product.get("language") generically for any source -- it just needed the
batch abs-agg/abs-tract normalizer to actually populate it.

Real (trimmed) fixture captured live from abs-agg's librivox endpoint,
2026-07-20: an English Frankenstein reading and a German one for the exact
same work.
"""
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


SEARCH = load_module("fixer_search_abs_agg_language", "app/fixer/search.py")
SCORING = load_module("fixer_scoring_abs_agg_language", "app/fixer/scoring.py")


LIBRIVOX_FRANKENSTEIN_EN = {
    "title": "Frankenstein, or The Modern Prometheus",
    "author": "Mary Wollstonecraft Shelley",
    "narrator": "Eric Connover, Carl Cravens",
    "publishedYear": "1818",
    "genres": ["Science Fiction"],
    "language": "English",
    "duration": 29808,
}

LIBRIVOX_FRANKENSTEIN_DE = {
    "title": "Frankenstein oder der moderne Prometheus",
    "author": "Mary Wollstonecraft Shelley",
    "narrator": "Ramona Deininger-Schnabel",
    "publishedYear": "1908",
    "genres": ["Action & Adventure Fiction", "Fantastic Fiction"],
    "language": "German",
    "duration": 27969,
}


class AbsMatchToProductLanguageTests(unittest.TestCase):
    def test_language_is_carried_through(self):
        product = SEARCH._abs_match_to_product(LIBRIVOX_FRANKENSTEIN_EN, "librivox", asin="")
        self.assertEqual(product["language"], "English")

    def test_missing_language_is_blank_not_absent(self):
        product = SEARCH._abs_match_to_product({"title": "X", "author": "Y"}, "librivox", asin="")
        self.assertEqual(product["language"], "")


class LanguagePenaltyAppliesToAbsAggMatchesTests(unittest.TestCase):
    """End-to-end: once language is carried through, the existing generic
    language-penalty in score_product_for_metadata (previously dead code for
    every abs-agg source, since the field was always absent) actually
    distinguishes the English and German real LibriVox readings of the same
    book."""

    def _clues(self):
        return {
            "title": "Frankenstein, or The Modern Prometheus",
            "author": "Mary Wollstonecraft Shelley",
            "existing_asin": "",
        }

    def test_english_reading_outscores_german_reading_of_the_same_book(self):
        en_product = SEARCH._abs_match_to_product(LIBRIVOX_FRANKENSTEIN_EN, "librivox", asin="")
        de_product = SEARCH._abs_match_to_product(LIBRIVOX_FRANKENSTEIN_DE, "librivox", asin="")
        # Identical title/author and no local duration supplied (isolates the
        # language penalty as the only variable between the two calls --
        # duration deliberately excluded so it can't confound the comparison).
        en_score = SCORING.score_product_for_metadata(self._clues(), en_product, local_duration_minutes=None)
        de_score = SCORING.score_product_for_metadata(self._clues(), de_product, local_duration_minutes=None)
        # ~0.30 is the language penalty itself; a small remainder comes from
        # unrelated scoring components (e.g. narrator-string similarity)
        # that aren't the subject of this test.
        self.assertAlmostEqual(en_score - de_score, 0.30, delta=0.02)


if __name__ == "__main__":
    unittest.main()
