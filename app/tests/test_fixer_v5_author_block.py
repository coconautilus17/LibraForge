import unittest
from app.tests.script_loader import load_module


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
    def test_author_identity_conflict(self):
        for title, local_author, product_authors, expected in (
            ("Cradle", "Arthur C. Clarke", ["Will Wight"], True),
            ("Cradle", "Will Wight", ["Will Wight"], False),
            # Local lists both authors; product lists one. Shared token / containment.
            ("Cradle", "Arthur C. Clarke, Gentry Lee", ["Arthur C. Clarke"], False),
            ("The Hobbit", "J. R. R. Tolkien", ["J.R.R. Tolkien"], False),
            ("Cradle", "", ["Will Wight"], False),
        ):
            with self.subTest(local_author=local_author, product_authors=product_authors):
                clues = {"title": title, "author": local_author}
                self.assertIs(FIXER.has_author_identity_conflict(clues, product(title, product_authors)), expected)

    def test_generic_author_no_conflict(self):
        prod = product("Cradle", ["Will Wight"])
        for author in ("Unknown", "Misc"):
            with self.subTest(author=author):
                clues = {"title": "Cradle", "author": author}
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
        self.assertEqual(score, 1.0)

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
