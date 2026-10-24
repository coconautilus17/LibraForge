"""Tags naming one recording while the runtime matches another of the same
title: hold for review instead of applying either (#407)."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_runtime_rival", "scripts/audible-metadata-fixer-v5.py")
from app.fixer import scoring as SCORING  # noqa: E402


def listing(asin, title, narrator, minutes):
    return {
        "asin": asin, "title": title, "subtitle": "Jack Reacher, Book 29",
        "authors": [{"name": "Lee Child"}, {"name": "Andrew Child"}], "narrators": [{"name": narrator}],
        "series": [{"title": "Jack Reacher", "sequence": "29"}],
        "runtime_length_min": minutes, "runtime_length_sec": minutes * 60,
    }


HARDING = listing("B0CLGCXHQT", "In too Deep", "Jeff Harding", 537)
BRICK = listing("B0CRCHD41B", "In Too Deep", "Scott Brick", 598)

# The rip's original tags: the Harding edition's ASIN and narrator, Brick's audio.
CLUES = {
    "title": "In Too Deep", "raw_title": "In Too Deep", "author": "Lee Child, Andrew Child",
    "narrator": "Jeff Harding", "series": "Jack Reacher", "book_number": "29", "book_number_source": "path",
    "existing_asin": "B0CLGCXHQT", "local_duration_minutes": 598.1,
}


class RuntimeRivalScoringTests(unittest.TestCase):
    def test_tags_and_runtime_naming_two_recordings_is_unresolved(self):
        best, _score, ambiguity = SCORING.pick_best_match_for_metadata(CLUES, [HARDING, BRICK], 598.1)
        self.assertEqual(best["asin"], "B0CLGCXHQT")
        self.assertFalse(ambiguity["resolved"])
        self.assertIn("runtime matches In Too Deep [B0CRCHD41B]", ambiguity["reason"])

    def test_a_winner_with_a_perfect_runtime_is_not_contested(self):
        clues = dict(CLUES, local_duration_minutes=537.5)
        best, _score, ambiguity = SCORING.pick_best_match_for_metadata(clues, [HARDING, BRICK], 537.5)
        self.assertEqual(best["asin"], "B0CLGCXHQT")
        self.assertTrue(ambiguity is None or ambiguity["resolved"])

    def test_another_title_with_a_perfect_runtime_is_no_rival(self):
        other = dict(BRICK, title="Never Go Back")
        _best, _score, ambiguity = SCORING.pick_best_match_for_metadata(CLUES, [HARDING, other], 598.1)
        self.assertTrue(ambiguity is None or ambiguity.get("resolved") is not False)


class RuntimeRivalSearchItemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "In too Deep.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_embedded_asin_hit_is_held_when_the_runtime_matches_another_recording(self):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="abs", abs_provider="audible", abs_url="http://abs", abs_api_key="k",
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        with patch.object(FIXER, "abs_lookup_by_asin", return_value=dict(HARDING)), \
                patch.object(FIXER, "abs_search", return_value=[dict(HARDING), dict(BRICK)]):
            result = FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: (["In Too Deep Lee Child"], dict(CLUES))},
                search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )
        self.assertEqual(result.status, "skipped")
        self.assertTrue(result.add_to_manual_review)
        self.assertIn("runtime matches", result.skip_reason)


if __name__ == "__main__":
    unittest.main()
