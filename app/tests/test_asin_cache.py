"""Tests for _asin_from_libraforge_json and _write_scan_asin_cache."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import (
    _NOREALASIN,
    _asin_from_libraforge_json,
    _asin_string_from_libraforge_json,
    _owned_asins_for_folder,
    _scan_owned_asins,
    _write_scan_asin_cache,
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


class WriteScanAsinCacheTests(unittest.TestCase):
    def test_writes_to_existing_sidecar_audible_field(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            sidecar = folder / "libraforge.json"
            sidecar.write_text(json.dumps({"audible": {}}), encoding="utf-8")

            _write_scan_asin_cache(folder, audio, "B0CACHED12")

            data = json.loads(sidecar.read_text())
            self.assertEqual(data["scan_cache"]["asin"], "B0CACHED12")

    def test_writes_norealasin_to_existing_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            sidecar = folder / "libraforge.json"
            sidecar.write_text(json.dumps({}), encoding="utf-8")

            _write_scan_asin_cache(folder, audio, _NOREALASIN)

            data = json.loads(sidecar.read_text())
            self.assertEqual(data["scan_cache"]["asin"], _NOREALASIN)

    def test_does_not_create_new_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            sidecar = folder / "libraforge.json"

            _write_scan_asin_cache(folder, audio, "B0CACHED12")

            # No sidecar existed -- should NOT be created
            self.assertFalse(sidecar.exists())

    def test_does_not_overwrite_existing_marker_asin(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            sidecar = folder / "libraforge.json"
            original = {"marker": {"audible": {"asin": "B0ORIGINAL"}}}
            sidecar.write_text(json.dumps(original), encoding="utf-8")

            _write_scan_asin_cache(folder, audio, "B0CACHED12")

            data = json.loads(sidecar.read_text())
            # scan_cache written, but marker.audible.asin untouched
            self.assertEqual(data["scan_cache"]["asin"], "B0CACHED12")
            self.assertEqual(data["marker"]["audible"]["asin"], "B0ORIGINAL")

    def test_prefers_per_file_sidecar_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            per_file = folder / "book.m4b.libraforge.json"
            per_file.write_text(json.dumps({}), encoding="utf-8")
            folder_sidecar = folder / "libraforge.json"
            folder_sidecar.write_text(json.dumps({}), encoding="utf-8")

            _write_scan_asin_cache(folder, audio, "B0PERFILE1")

            per_file_data = json.loads(per_file.read_text())
            folder_data = json.loads(folder_sidecar.read_text())
            self.assertEqual(per_file_data["scan_cache"]["asin"], "B0PERFILE1")
            # folder sidecar not written when per-file exists
            self.assertNotIn("scan_cache", folder_data)


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
            self.assertEqual(_asin_string_from_libraforge_json(self._write(Path(d), {"scan_cache": {"asin": _NOREALASIN}})), "")
            self.assertEqual(_asin_string_from_libraforge_json(self._write(Path(d), {"marker": {}})), "")


class OwnedAsinsForFolderTests(unittest.TestCase):
    def test_filename_asin_wins_without_opening_media(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Book One"
            folder.mkdir()
            (folder / "Book One [B0FILE1234].m4b").write_bytes(b"")
            with patch("app.main._read_asin_from_audio") as read_audio:
                self.assertEqual(_owned_asins_for_folder(folder), {"B0FILE1234"})
                read_audio.assert_not_called()  # cheap source used, no media open

    def test_sidecar_used_before_media(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Book Two"
            folder.mkdir()
            audio = folder / "book.m4b"
            audio.write_bytes(b"")
            (folder / "libraforge.json").write_text(json.dumps({"audible": {"asin": "B0SIDE12345"}}), encoding="utf-8")
            with patch("app.main._read_asin_from_audio") as read_audio:
                self.assertEqual(_owned_asins_for_folder(folder), {"B0SIDE12345"})
                read_audio.assert_not_called()

    def test_falls_back_to_embedded_tag(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Book Three"
            folder.mkdir()
            (folder / "book.m4b").write_bytes(b"")
            with patch("app.main._read_asin_from_audio", return_value="B0EMBED1234") as read_audio:
                self.assertEqual(_owned_asins_for_folder(folder), {"B0EMBED1234"})
                read_audio.assert_called_once()


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


if __name__ == "__main__":
    unittest.main()
