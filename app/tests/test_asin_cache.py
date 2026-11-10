"""Tests for _asin_from_libraforge_json and the owned-ASIN scan."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import (
    ASIN_PLACEHOLDER,
    _asin_from_libraforge_json,
    _asin_string_from_libraforge_json,
    _scan_owned_asins,
)


class AsinFromLibraforgeJsonTests(unittest.TestCase):
    def _write(self, tmp: Path, data: dict) -> Path:
        p = tmp / "libraforge.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_real_asin_in_marker_audible_returns_true(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"marker": {"audible": {"asin": "B0ABC12345"}}})
            self.assertTrue(_asin_from_libraforge_json(p))

    def test_real_asin_in_audible_field_returns_true(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"audible": {"asin": "B0ABC12345"}})
            self.assertTrue(_asin_from_libraforge_json(p))

    def test_norealasin_in_marker_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"marker": {"audible": {"asin": "NOREALASIN"}}})
            self.assertFalse(_asin_from_libraforge_json(p))

    def test_norealasin_in_scan_cache_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"scan_cache": {"asin": "NOREALASIN"}})
            self.assertFalse(_asin_from_libraforge_json(p))

    def test_real_asin_in_scan_cache_returns_true(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"scan_cache": {"asin": "B0REAL1234"}})
            self.assertTrue(_asin_from_libraforge_json(p))

    def test_scan_cache_takes_priority_over_marker(self):
        with tempfile.TemporaryDirectory() as d:
            # scan_cache says NOREALASIN but marker says real -- scan_cache wins
            p = self._write(Path(d), {
                "scan_cache": {"asin": "NOREALASIN"},
                "marker": {"audible": {"asin": "B0REAL1234"}},
            })
            self.assertFalse(_asin_from_libraforge_json(p))

    def test_empty_asin_field_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"marker": {"audible": {"asin": ""}}})
            self.assertIsNone(_asin_from_libraforge_json(p))

    def test_missing_asin_field_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"marker": {}})
            self.assertIsNone(_asin_from_libraforge_json(p))

    def test_malformed_json_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "libraforge.json"
            p.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(_asin_from_libraforge_json(p))


class AsinStringFromLibraforgeJsonTests(unittest.TestCase):
    def _write(self, tmp: Path, data: dict) -> Path:
        p = tmp / "libraforge.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_returns_uppercased_real_asin(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {"audible": {"asin": "b0abc12345"}})
            self.assertEqual(_asin_string_from_libraforge_json(p), "B0ABC12345")

    def test_scan_cache_priority(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), {
                "scan_cache": {"asin": "B0SCAN1234"},
                "marker": {"audible": {"asin": "B0MARKER123"}},
            })
            self.assertEqual(_asin_string_from_libraforge_json(p), "B0SCAN1234")

    def test_norealasin_and_missing_return_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_asin_string_from_libraforge_json(self._write(Path(d), {"scan_cache": {"asin": ASIN_PLACEHOLDER}})), "")
            self.assertEqual(_asin_string_from_libraforge_json(self._write(Path(d), {"marker": {}})), "")


class ScanOwnedAsinsTests(unittest.TestCase):
    def test_collects_across_folders_from_mixed_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f1 = root / "Author A" / "Book One [B0AAA11111]"
            f1.mkdir(parents=True)
            (f1 / "track [B0AAA11111].m4b").write_bytes(b"")
            f2 = root / "Author B" / "Book Two"
            f2.mkdir(parents=True)
            (f2 / "book.m4b").write_bytes(b"")
            (f2 / "libraforge.json").write_text(json.dumps({"marker": {"audible": {"asin": "B0BBB22222"}}}), encoding="utf-8")
            with patch("app.main._read_asin_from_audio", return_value=""):
                owned = _scan_owned_asins(root)
            self.assertEqual(owned, {"B0AAA11111", "B0BBB22222"})

    def test_a_sidecar_without_an_asin_falls_back_to_the_audio_file(self):
        with tempfile.TemporaryDirectory() as d:
            book = Path(d) / "Author" / "Book"
            book.mkdir(parents=True)
            (book / "book.m4b").write_bytes(b"")
            (book / "libraforge.json").write_text(json.dumps({"backup": {"format_tags": {}}}), encoding="utf-8")
            with patch("app.main._read_asin_from_audio", return_value="B0CCC33333") as read:
                owned = _scan_owned_asins(Path(d))
            self.assertEqual(owned, {"B0CCC33333"})
            read.assert_called_once_with(book / "book.m4b")


if __name__ == "__main__":
    unittest.main()
