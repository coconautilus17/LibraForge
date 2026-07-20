import unittest

from app.main import score_ebook_candidate


class ScoreEbookCandidateTests(unittest.TestCase):
    def test_identical_title_and_author_scores_high(self):
        score = score_ebook_candidate(
            "Efficient Linux at the Command Line", "Daniel J. Barrett",
            "Efficient Linux at the Command Line", "Daniel J. Barrett",
        )
        self.assertGreaterEqual(score, 0.95)

    def test_unrelated_titles_score_low(self):
        score = score_ebook_candidate(
            "Efficient Linux at the Command Line", "Daniel J. Barrett",
            "The Hobbit", "J. R. R. Tolkien",
        )
        self.assertLess(score, 0.35)

    def test_blank_query_author_does_not_raise_and_scores_on_title_alone(self):
        score = score_ebook_candidate(
            "Kubernetes Up and Running", "",
            "Kubernetes Up and Running", "Kelsey Hightower",
        )
        self.assertGreaterEqual(score, 0.9)

    def test_blank_titles_score_zero_not_raise(self):
        self.assertEqual(score_ebook_candidate("", "", "", ""), 0.0)

    def test_case_and_whitespace_insensitive(self):
        score = score_ebook_candidate(
            "kubernetes   up and running", "",
            "Kubernetes Up And Running", "",
        )
        self.assertGreaterEqual(score, 0.95)


if __name__ == "__main__":
    unittest.main()
