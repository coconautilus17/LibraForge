"""--provider abs: the ASIN-first lookup, structured title/author queries and the
language/publisher fields that ABS mode used to skip or drop (#382).

Calls search_item() with a pre-filled search context and a fake ABS, so this
exercises the real per-book wiring.
"""
import importlib.util
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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


FIXER = load_module("fixer_v5_abs_search_mode", "scripts/audible-metadata-fixer-v5.py")
from app.fixer import search as SEARCH  # noqa: E402


def product(asin, narrator, minutes, language="English", publisher=""):
    return {
        "asin": asin, "title": "Moby Dick", "subtitle": "",
        "authors": [{"name": "Herman Melville"}], "narrators": [{"name": narrator}],
        "series": [], "runtime_length_min": minutes, "runtime_length_sec": minutes * 60,
        "language": language, "publisher_name": publisher,
    }


NAXOS = product("B0038GOF7C", "William Hootkins", 1309, publisher="Naxos AudioBooks")
LARKIN = product("B08WBVYMY2", "Jonathan Epstein", 1309, publisher="Alison Larkin Presents")


class SearchItemAbsModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "Moby Dick.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _call(self, clues, queries):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="abs", abs_provider="audible", abs_url="http://abs", abs_api_key="k",
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        return FIXER.search_item(
            index=1, file_path=self.book, total=1, multi_part_group_map={},
            args=args, auth_file="", auth_password=None,
            search_context_cache={key: (queries, clues)}, search_context_lock=threading.Lock(),
            match_cache={}, match_cache_lock=threading.Lock(),
            search_cache={}, search_cache_lock=threading.Lock(),
            search_in_flight={}, folder_audio_counts=None, abs_index=None,
        )

    def _clues(self, **extra):
        clues = {"title": "Moby Dick", "author": "Herman Melville", "local_duration_minutes": 1309.0}
        clues.update(extra)
        return clues

    def test_embedded_asin_is_looked_up_through_abs_before_keyword_search(self):
        with patch.object(FIXER, "abs_lookup_by_asin", return_value=dict(NAXOS)) as lookup, \
                patch.object(FIXER, "abs_search", return_value=[dict(LARKIN)]) as search:
            result = self._call(self._clues(existing_asin="B0038GOF7C"), ["Moby Dick Herman Melville"])
        lookup.assert_called_once_with("B0038GOF7C", "audible", "http://abs", "k")
        search.assert_not_called()
        self.assertEqual(result.metadata["asin"], "B0038GOF7C")

    def test_asin_lookup_miss_falls_back_to_keyword_search(self):
        with patch.object(FIXER, "abs_lookup_by_asin", return_value=None), \
                patch.object(FIXER, "abs_search", return_value=[dict(NAXOS)]) as search:
            result = self._call(self._clues(existing_asin="B0038GOF7C"), ["Moby Dick Herman Melville"])
        search.assert_called()
        self.assertEqual(result.metadata["asin"], "B0038GOF7C")

    def test_structured_title_and_first_credit_are_sent_before_joined_queries(self):
        clues = self._clues(author="Herman Melville, Anthony Heald - foreword")
        with patch.object(FIXER, "abs_search", return_value=[]) as search:
            self._call(clues, ["Moby Dick Herman Melville", "Moby Dick"])
        sent = [(c.kwargs["title"], c.kwargs["author"]) for c in search.call_args_list]
        self.assertEqual(sent, [
            ("Moby Dick", "Herman Melville"),
            ("Moby Dick Herman Melville", ""),
            ("Moby Dick", ""),
        ])


class AbsSearchFieldMappingTests(unittest.TestCase):
    def _fake_urlopen(self, payload):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        return lambda *a, **k: Resp()

    def test_language_and_publisher_are_kept(self):
        payload = [{"asin": "B0038GOF7C", "title": "Moby Dick", "language": "Spanish",
                    "publisher": "Naxos AudioBooks", "duration": 1309}]
        with patch("urllib.request.urlopen", self._fake_urlopen(payload)):
            products = SEARCH.abs_search("Moby Dick", "", "audible", "http://abs", "k", 10)
        self.assertEqual(products[0]["language"], "Spanish")
        self.assertEqual(products[0]["publisher_name"], "Naxos AudioBooks")

    def test_asin_lookup_returns_only_an_exact_asin_match(self):
        with patch.object(SEARCH, "abs_search", return_value=[{"asin": "B0OTHER000"}, {"asin": "b0038gof7c"}]) as s:
            self.assertEqual(SEARCH.abs_lookup_by_asin(" b0038gof7c ", "audible", "u", "k")["asin"], "b0038gof7c")
        s.assert_called_once_with("B0038GOF7C", "", "audible", "u", "k", 5)
        with patch.object(SEARCH, "abs_search", return_value=[{"asin": "B0OTHER000"}]):
            self.assertIsNone(SEARCH.abs_lookup_by_asin("B0038GOF7C", "audible", "u", "k"))


if __name__ == "__main__":
    unittest.main()
