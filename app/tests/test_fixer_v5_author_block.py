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


FIXER = load_module("fixer_v5_author_block", "scripts/audible-metadata-fixer-v5.py")


def product(title, authors, asin="", language="english", duration_minutes=None):
    p = {
        "title": title,
        "authors": [{"name": a} for a in authors],
        "asin": asin,
        "language": language,
    }
    if duration_minutes is not None:
        p["runtime_length_min"] = duration_minutes
    return p


class AuthorIdentityConflictTests(unittest.TestCase):
    def test_clearly_different_author_conflicts(self):
        clues = {"title": "Cradle", "author": "Arthur C. Clarke"}
        prod = product("Cradle", ["Will Wight"])
        self.assertTrue(FIXER.has_author_identity_conflict(clues, prod))

    def test_same_author_no_conflict(self):
        clues = {"title": "Cradle", "author": "Will Wight"}
        prod = product("Cradle", ["Will Wight"])
        self.assertFalse(FIXER.has_author_identity_conflict(clues, prod))

    def test_coauthor_subset_no_conflict(self):
        # Local lists both authors; product lists one. Shared token / containment.
        clues = {"title": "Cradle", "author": "Arthur C. Clarke, Gentry Lee"}
        prod = product("Cradle", ["Arthur C. Clarke"])
        self.assertFalse(FIXER.has_author_identity_conflict(clues, prod))

    def test_name_format_variation_no_conflict(self):
        clues = {"title": "The Hobbit", "author": "J. R. R. Tolkien"}
        prod = product("The Hobbit", ["J.R.R. Tolkien"])
        self.assertFalse(FIXER.has_author_identity_conflict(clues, prod))

    def test_missing_local_author_no_conflict(self):
        clues = {"title": "Cradle", "author": ""}
        prod = product("Cradle", ["Will Wight"])
        self.assertFalse(FIXER.has_author_identity_conflict(clues, prod))

    def test_generic_author_no_conflict(self):
        clues = {"title": "Cradle", "author": "Unknown"}
        prod = product("Cradle", ["Will Wight"])
        self.assertFalse(FIXER.has_author_identity_conflict(clues, prod))


class AuthorHardBlockScoringTests(unittest.TestCase):
    def test_wrong_author_same_title_scores_zero(self):
        # The Clarke/Wight "Cradle" collision with a coincidental duration match.
        clues = {
            "title": "Cradle",
            "author": "Arthur C. Clarke",
            "series": "Cradle",
        }
        prod = product("Cradle", ["Will Wight"], duration_minutes=600)
        score = FIXER.score_product_for_metadata(clues, prod, local_duration_minutes=600)
        self.assertEqual(score, 0.0)

    def test_dante_king_vs_kw_foster_scores_zero(self):
        # Mind Breaker 1 (Dante King) matched "A Curse of Breath and Blood"
        # (K.W. Foster) at 0.9553 because the subtitle was "The Mind Breaker, Book 1".
        clues = {
            "title": "Mind Breaker 1",
            "author": "Dante King",
            "series": "Mind Breaker",
            "book_number": "1",
        }
        prod = product("A Curse of Breath and Blood", ["K.W. Foster"], duration_minutes=573)
        score = FIXER.score_product_for_metadata(clues, prod, local_duration_minutes=618)
        self.assertEqual(score, 0.0)

    def test_logan_jacobs_vs_sarah_maas_scores_zero(self):
        # Court of the Shifter 2 (Logan Jacobs) matched "A Court of Mist and Fury
        # Part 2" (Sarah J. Maas) at 0.7541 due to title overlap and sequence match.
        clues = {
            "title": "Court of the Shifter 2",
            "author": "Logan Jacobs",
            "series": "Court of the Shifter",
            "book_number": "2",
        }
        prod = product(
            "A Court of Mist and Fury (Part 2 of 2) (Dramatized Adaptation)",
            ["Sarah J. Maas"],
            duration_minutes=503,
        )
        score = FIXER.score_product_for_metadata(clues, prod, local_duration_minutes=557)
        self.assertEqual(score, 0.0)

    def test_correct_author_still_matches(self):
        clues = {"title": "Cradle", "author": "Will Wight", "series": "Cradle"}
        prod = product("Cradle", ["Will Wight"], duration_minutes=600)
        score = FIXER.score_product_for_metadata(clues, prod, local_duration_minutes=600)
        self.assertGreater(score, 0.0)

    def test_asin_identity_bypasses_block(self):
        # A confirmed embedded ASIN must still win even if author strings differ
        # wildly (the ASIN identity path requires its own title+author check, so
        # use matching author here to exercise the bypass ordering safely).
        clues = {
            "title": "Cradle",
            "author": "Will Wight",
            "existing_asin": "B0ABCDEFGH",
        }
        prod = product("Cradle", ["Will Wight"], asin="B0ABCDEFGH")
        score = FIXER.score_product_for_metadata(clues, prod)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
