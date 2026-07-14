"""Tests for ABS-first owned-ASIN lookup and the persistent fallback index."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class AbsOwnedAsinsTests(unittest.TestCase):
    def _abs_request(self, path, params):
        if path == "/api/libraries":
            return {"libraries": [{"id": "lib1", "name": "Books", "mediaType": "book"}]}
        if path == "/api/libraries/lib1/items":
            page = int(params["page"])
            if page == 0:
                return {"total": 3, "results": [
                    {"media": {"metadata": {"asin": "b0aaa11111"}}},
                    {"media": {"metadata": {"asin": "B0BBB22222"}}},
                    {"media": {"metadata": {"asin": ""}}},  # no asin -> skipped
                ]}
            return {"total": 3, "results": []}
        raise AssertionError(f"unexpected path {path}")

    def test_collects_and_uppercases_asins(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=self._abs_request):
            self.assertEqual(main._abs_owned_asins(), {"B0AAA11111", "B0BBB22222"})

    def test_no_api_key_returns_none(self):
        with patch("app.main._get_abs_api_key", return_value=""):
            self.assertIsNone(main._abs_owned_asins())

    def test_abs_error_returns_none(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=RuntimeError("down")):
            self.assertIsNone(main._abs_owned_asins())

    def test_no_libraries_at_all_returns_none(self):
        # Regression for #243: _abs_owned_asins() now delegates its
        # pagination walk to fetch_all_abs_book_items, which can't itself
        # distinguish "no libraries" from "libraries with zero items" (both
        # yield an empty item list) -- the None-vs-empty-set distinction
        # must still be preserved so the caller correctly falls back to the
        # filesystem scan only when ABS has no libraries at all.
        def no_libraries(path, params):
            if path == "/api/libraries":
                return {"libraries": []}
            raise AssertionError(f"unexpected path {path}")

        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=no_libraries):
            self.assertIsNone(main._abs_owned_asins())

    def test_libraries_exist_but_are_empty_returns_empty_set_not_none(self):
        def empty_library(path, params):
            if path == "/api/libraries":
                return {"libraries": [{"id": "lib1", "name": "Books", "mediaType": "book"}]}
            if path == "/api/libraries/lib1/items":
                return {"total": 0, "results": []}
            raise AssertionError(f"unexpected path {path}")

        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._abs_request", side_effect=empty_library):
            self.assertEqual(main._abs_owned_asins(), set())


class PersistentIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index_path = Path(self.tmp.name) / "owned-asin-index.json"
        self._p = patch("app.main._OWNED_INDEX_PATH", self.index_path)
        self._p.start()
        main._OWNED_ASIN_CACHE.clear()

    def tearDown(self):
        self._p.stop()
        main._OWNED_ASIN_CACHE.clear()
        self.tmp.cleanup()

    def test_store_then_load_roundtrip(self):
        main._store_owned_asins(Path("/lib"), {"B0AAA11111", "B0BBB22222"}, "fp-1")
        rec = main._load_owned_index()["/lib"]
        self.assertEqual(rec["fingerprint"], "fp-1")
        self.assertEqual(set(rec["asins"]), {"B0AAA11111", "B0BBB22222"})

    def test_cached_uses_persisted_index_without_scanning(self):
        main._store_owned_asins(Path("/lib"), {"B0AAA11111"}, "fp-match")
        main._OWNED_ASIN_CACHE.clear()  # force the disk path, not memory
        with patch("app.main._library_fingerprint", return_value="fp-match"), \
             patch("app.main._scan_owned_asins", side_effect=AssertionError("should not scan")) as scan:
            result = main._owned_asins_cached(Path("/lib"))
        self.assertEqual(result, {"B0AAA11111"})
        scan.assert_not_called()

    def test_cached_rescans_and_persists_on_fingerprint_miss(self):
        main._store_owned_asins(Path("/lib"), {"B0OLD111111"}, "fp-old")
        main._OWNED_ASIN_CACHE.clear()
        with patch("app.main._library_fingerprint", return_value="fp-new"), \
             patch("app.main._scan_owned_asins", return_value={"B0NEW111111"}):
            result = main._owned_asins_cached(Path("/lib"))
        self.assertEqual(result, {"B0NEW111111"})
        # New result persisted under the new fingerprint.
        rec = main._load_owned_index()["/lib"]
        self.assertEqual(rec["fingerprint"], "fp-new")
        self.assertEqual(set(rec["asins"]), {"B0NEW111111"})


if __name__ == "__main__":
    unittest.main()
