"""A series_only match is another book of the series: it fixes only the
grouping fields (#398) and never ends the search (#399).
"""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_series_only_safety", "scripts/audible-metadata-fixer-v5.py")
from app.fixer import scoring as SCORING  # noqa: E402


def product(asin, title, minutes, sequence, subtitle="", isbn=""):
    return {
        "asin": asin, "title": title, "subtitle": subtitle,
        "authors": [{"name": "Christopher G. Nuttall"}], "narrators": [{"name": "Tavia Gilbert"}],
        "series": [{"title": "Schooled in Magic", "sequence": sequence}],
        "runtime_length_min": minutes, "runtime_length_sec": minutes * 60,
        "_abs_isbn": isbn,
    }


GENNADY = product("B0C413M12W", "Gennady's Tale", 211, "", subtitle="A Schooled in Magic Novella",
                  isbn="9781039403352")


def fists_clues(**extra):
    clues = {
        "title": "Fists of Justice", "raw_title": "Fists of Justice", "author": "Christopher G. Nuttall",
        "narrator": "Tavia Gilbert", "series": "Schooled in Magic", "book_number": "12",
        "book_number_source": "title", "local_duration_minutes": 746.3,
        "current": {"subtitle": "", "isbn": "", "asin": ""},
    }
    clues.update(extra)
    return clues


class SeriesOnlyMetadataTests(unittest.TestCase):
    def test_other_books_asin_isbn_and_subtitle_are_not_written(self):
        md = SCORING.metadata_from_product(GENNADY, fists_clues(), 0.72)
        self.assertEqual(md["edit_mode"], "series_only")
        self.assertEqual((md["asin"], md["isbn"], md["subtitle"]), ("", "", ""))
        self.assertEqual(md["series"], "Schooled in Magic")
        self.assertEqual(md["series_match_asin"], "B0C413M12W")

    def test_the_files_own_identifiers_are_kept(self):
        clues = fists_clues(existing_asin="B079H8GKHR",
                            current={"subtitle": "Schooled in Magic, Book 12", "isbn": "9781000000001"})
        md = SCORING.metadata_from_product(GENNADY, clues, 0.72)
        self.assertEqual(md["asin"], "B079H8GKHR")
        self.assertEqual(md["isbn"], "9781000000001")
        self.assertEqual(md["subtitle"], "Schooled in Magic, Book 12")

    def test_an_asin_left_by_an_earlier_series_only_write_is_dropped(self):
        md = SCORING.metadata_from_product(GENNADY, fists_clues(existing_asin="B0C413M12W"), 0.72)
        self.assertEqual(md["asin"], "")

    def test_a_full_match_still_writes_its_asin(self):
        fists = product("B079H8GKHR", "Fists of Justice", 746, "12", isbn="9781039400000")
        md = SCORING.metadata_from_product(fists, fists_clues(), 1.0)
        self.assertEqual(md["edit_mode"], "full")
        self.assertEqual(md["asin"], "B079H8GKHR")
        self.assertNotIn("series_match_asin", md)


class SeriesOnlyMarkerTests(unittest.TestCase):
    def _skip(self, marker):
        with patch.object(FIXER, "load_marker", return_value=marker):
            return FIXER.should_skip_due_to_marker(Path("/x/book.m4b"), aggressive_run=False, force=False)

    def test_a_series_only_apply_is_searched_again(self):
        self.assertEqual(self._skip({"applied": True, "edit_mode": "series_only"}), (False, ""))

    def test_a_full_apply_is_still_skipped(self):
        self.assertEqual(self._skip({"applied": True, "edit_mode": "full", "audible": {"asin": "B079H8GKHR"}}),
                         (True, "already processed"))

    def test_a_manual_series_only_apply_is_never_redone(self):
        self.assertEqual(self._skip({"applied": True, "manually_applied": True, "edit_mode": "series_only"}),
                         (True, "already manually applied"))


class SeriesOnlyDoesNotEndTheSearchTests(unittest.TestCase):
    """Legend to Farmer 1: the first query returns only the 1-6 omnibus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "Legend to Farmer 1.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _product(self, asin, title, minutes, sequence):
        return {
            "asin": asin, "title": title, "subtitle": "A Slice of Life Fantasy",
            "authors": [{"name": "Dante King"}], "narrators": [],
            "series": [{"title": "Legend to Farmer", "sequence": sequence}],
            "runtime_length_min": minutes, "runtime_length_sec": minutes * 60,
        }

    def test_a_later_query_replaces_the_series_only_omnibus(self):
        omnibus = self._product("B0HG1FTMVR", "Legend to Farmer Omnibus: Books 1-6", 3142, "1-6")
        book = self._product("B0CWSZNLKT", "Legend to Farmer", 657, "1")
        clues = {"title": "Legend to Farmer 1", "raw_title": "Legend to Farmer 1", "author": "Dante King",
                 "series": "Legend to Farmer", "book_number": "1", "book_number_source": "path",
                 "local_duration_minutes": 657.7}
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="abs", abs_provider="audible", abs_url="http://abs", abs_api_key="k",
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        with patch.object(FIXER, "abs_search", side_effect=[[omnibus], [book]]) as search:
            result = FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: (["Legend to Farmer 1 Dante King", "Legend to Farmer Dante King"], clues)},
                search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result.metadata["asin"], "B0CWSZNLKT")
        self.assertEqual(result.metadata["edit_mode"], "full")


if __name__ == "__main__":
    unittest.main()
