"""Genres that exclude each other but both reach the vote are reported (#436)."""
import unittest

from app.enrichment_batch import slim_result
from app.genre_voting import vote_unit


def vote(*mains):
    return {"main": set(mains), "sub": {}, "evidence": {g: {"audible"} for g in mains}, "sub_evidence": {}, "other": set()}


def unit_of(votes):
    return vote_unit(votes, series_labels=[], series_evidence=[], pf_progression=False, standalone=False)


class GenreConflictTests(unittest.TestCase):
    def test_fiction_and_non_fiction_both_reaching_the_vote_is_a_conflict(self):
        unit = unit_of([vote("Thriller")] * 6 + [vote("Thriller", "Non-Fiction")] * 2)
        self.assertEqual(unit["main"], ["Thriller"])
        self.assertEqual(unit["conflicts"], [{"genres": ["Non-Fiction", "Thriller"], "support": {"Non-Fiction": 2, "Thriller": 8},
                                              "kept": ["Thriller"]}])

    def test_the_larger_side_is_kept_either_way(self):
        unit = unit_of([vote("Non-Fiction")] * 6 + [vote("Fantasy")] * 2)
        self.assertEqual(unit["main"], ["Non-Fiction"])
        self.assertEqual(unit["conflicts"][0]["kept"], ["Non-Fiction"])

    def test_a_genre_under_the_threshold_is_no_conflict(self):
        unit = unit_of([vote("Thriller")] * 11 + [vote("Thriller", "Non-Fiction")])
        self.assertEqual(unit["conflicts"], [])

    def test_young_adult_and_childrens_both_kept_is_a_conflict(self):
        unit = unit_of([vote("Fantasy", "Young Adult", "Children's")] * 2)
        self.assertEqual(unit["conflicts"][0]["genres"], ["Young Adult", "Children's"])

    def test_the_batch_review_keeps_the_conflicts(self):
        conflict = {"genres": ["Non-Fiction", "Thriller"], "support": {"Non-Fiction": 2, "Thriller": 8}, "kept": ["Thriller"]}
        self.assertEqual(slim_result({"genre_conflicts": [conflict]})["conflicts"], [conflict])


if __name__ == "__main__":
    unittest.main()
