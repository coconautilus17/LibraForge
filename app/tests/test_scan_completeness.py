"""Scan completeness: sidecar naming, scan_cache read/validity, and creation.

Pure-logic coverage (no media decoding needed); end-to-end probing of real tags
is exercised separately. Empty .m4b files stand in for audio: _probe returns all
fields False for them, which is the documented graceful fallback.
"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.library_index as library_index
import app.main as main_module
from app.main import (
    _CORE_FIELDS,
    _ensure_scan_sidecar,
    _marker_says_no_asin,
    _probe_book_metadata,
    _scan_cache_from_sidecar,
    _scan_sidecar_target,
)

client = TestClient(main_module.app)


class SidecarTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return p

    def test_single_file_alone_is_folder_level(self):
        a = self._touch("Book/Book.m4b")
        self.assertEqual(_scan_sidecar_target([a], a.parent, a), a.parent / "libraforge.json")

    def test_single_file_shared_folder_is_per_file(self):
        a = self._touch("Shared/A.m4b")
        self._touch("Shared/B.m4b")
        self.assertEqual(
            _scan_sidecar_target([a], a.parent, a),
            a.with_name(a.name + ".libraforge.json"),
        )

    def test_multifile_is_folder_level(self):
        p1 = self._touch("Multi/part1.m4b")
        p2 = self._touch("Multi/part2.m4b")
        self.assertEqual(_scan_sidecar_target([p1, p2], p1.parent, p1), p1.parent / "libraforge.json")


class EnsureSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_folder_level_with_fields_and_mtime(self):
        a = self.root / "Book" / "Book.m4b"
        a.parent.mkdir(parents=True)
        a.write_bytes(b"")
        fields = {"title": True, "author": True, "narrator": False}
        _ensure_scan_sidecar([a], a.parent, a, "B0AAAA1111", fields)
        sc = json.loads((a.parent / "libraforge.json").read_text())["scan_cache"]
        self.assertEqual(sc["asin"], "B0AAAA1111")
        self.assertEqual(sc["fields"], fields)
        self.assertIsNotNone(sc["mtime"])

    def test_shared_folder_uses_per_file_not_folder_level(self):
        # A and B are distinct books sharing one folder. A stray folder-level
        # libraforge.json (e.g. belonging to a real multi-part book, or left over)
        # must NOT be adopted for A -- that is exactly the clobber that funnelled
        # Iron Guild's three books into one corrupt sidecar. A gets its own per-file
        # sidecar and the folder-level file is left untouched.
        a = self.root / "Shared" / "A.m4b"
        a.parent.mkdir(parents=True)
        a.write_bytes(b"")
        (self.root / "Shared" / "B.m4b").write_bytes(b"")
        (a.parent / "libraforge.json").write_text('{"marker": {"applied": true}}', encoding="utf-8")
        _ensure_scan_sidecar([a], a.parent, a, "B0BBBB2222", {f: True for f in _CORE_FIELDS})
        # A's own per-file sidecar was created with the scan_cache.
        per_file = a.with_name(a.name + ".libraforge.json")
        self.assertTrue(per_file.is_file())
        self.assertEqual(json.loads(per_file.read_text())["scan_cache"]["asin"], "B0BBBB2222")
        # The folder-level file was not adopted or polluted with A's scan_cache.
        folder = json.loads((a.parent / "libraforge.json").read_text())
        self.assertNotIn("scan_cache", folder)
        self.assertTrue(folder["marker"]["applied"])


class ScanCacheReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / "Book" / "Book.m4b"
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, scan_cache):
        (self.audio.parent / "libraforge.json").write_text(
            json.dumps({"scan_cache": scan_cache}), encoding="utf-8")

    def test_valid_cache_returns_state(self):
        self._write({"asin": "B0REAL11111", "fields": {"title": True, "author": True, "narrator": False},
                     "mtime": self.audio.stat().st_mtime_ns})
        res = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertEqual(res, (True, {"title": True, "author": True, "narrator": False}))

    def test_norealasin_is_not_present(self):
        self._write({"asin": "NOREALASIN", "fields": {f: True for f in _CORE_FIELDS},
                     "mtime": self.audio.stat().st_mtime_ns})
        present, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertFalse(present)

    def test_stale_mtime_returns_none(self):
        self._write({"asin": "B0REAL11111", "fields": {f: True for f in _CORE_FIELDS}, "mtime": 1})
        self.assertIsNone(_scan_cache_from_sidecar(self.audio, self.audio.parent))

    def test_old_asin_only_cache_returns_none(self):
        self._write({"asin": "B0REAL11111"})  # no fields -> needs full probe
        self.assertIsNone(_scan_cache_from_sidecar(self.audio, self.audio.parent))


class MarkerNoAsinTests(unittest.TestCase):
    def test_marker_says_no_asin(self):
        self.assertTrue(_marker_says_no_asin({"marker": {"audible": {"asin": "NOREALASIN"}}}))
        self.assertFalse(_marker_says_no_asin({"marker": {"audible": {"asin": "B0REAL11111"}}}))
        self.assertFalse(_marker_says_no_asin({"marker": {"audible": {}}}))
        self.assertFalse(_marker_says_no_asin({}))


class ScanCacheAsinSatisfiedTests(unittest.TestCase):
    """asin is 'satisfied' by a real embedded tag OR a confirmed NOREALASIN marker,
    but never by a marker that merely *claims* a real ASIN."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / "Book" / "Book.m4b"
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, payload):
        (self.audio.parent / "libraforge.json").write_text(json.dumps(payload), encoding="utf-8")

    def _scan_cache(self, asin):
        return {"asin": asin, "fields": {f: True for f in _CORE_FIELDS},
                "mtime": self.audio.stat().st_mtime_ns}

    def test_norealasin_marker_satisfies_asin(self):
        self._write({"scan_cache": self._scan_cache("NOREALASIN"),
                     "marker": {"audible": {"asin": "NOREALASIN"}}})
        satisfied, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertTrue(satisfied)

    def test_marker_claiming_real_asin_does_not_satisfy(self):
        # marker claims a real ASIN but the embedded tag (scan_cache) is absent.
        self._write({"scan_cache": self._scan_cache("NOREALASIN"),
                     "marker": {"audible": {"asin": "B0CLAIM1234"}}})
        satisfied, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertFalse(satisfied)

    def test_embedded_asin_satisfies(self):
        self._write({"scan_cache": self._scan_cache("B0EMBED1234")})
        satisfied, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertTrue(satisfied)


class ProbeGracefulTests(unittest.TestCase):
    def test_unreadable_file_yields_empty_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.m4b"
            p.write_bytes(b"not a real m4b")
            res = _probe_book_metadata(p)
            self.assertEqual(res["asin"], "")
            self.assertEqual(res["fields"], {f: False for f in _CORE_FIELDS})


class ScanStalenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root
        self._orig_cache_path = main_module.FOLDER_SCAN_CACHE
        main_module.FOLDER_SCAN_CACHE = self.root / "folder-scan-cache.json"
        library_index.reset_state_for_tests()

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module.FOLDER_SCAN_CACHE = self._orig_cache_path
        library_index.reset_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_file_added_inside_existing_folder_two_levels_deep_is_reflected_on_next_scan(self):
        # The bug this fixes: the old _library_fingerprint gate on
        # scan_folder_route only sees root + first-level subdir mtimes, so a
        # file appearing inside Author/Book (two levels down) previously
        # kept serving the stale needs_metadata/ready_to_organize counts
        # from _scan_cache until its 1-hour TTL expired.
        self._touch("Author/Book1/Book1.m4b")
        first = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertEqual(first.status_code, 200)
        first_total = first.json()["total"]

        self._touch("Author/Book2/Book2.m4b")
        second = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertEqual(second.status_code, 200)
        self.assertGreater(second.json()["total"], first_total)

    def test_new_book_folder_under_existing_series_is_counted(self):
        self._touch("Sanderson/Mistborn/Book 1/Book1.m4b")
        first = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        first_total = first.json()["total"]

        self._touch("Sanderson/Mistborn/Book 2/Book2.m4b")
        second = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertEqual(second.json()["total"], first_total + 1)

    def test_second_call_with_nothing_changed_reports_from_cache(self):
        self._touch("Author/Book1/Book1.m4b")
        client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        second = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertTrue(second.json()["from_cache"])

    def test_cache_persists_to_disk(self):
        self._touch("Author/Book1/Book1.m4b")
        client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertTrue(main_module.FOLDER_SCAN_CACHE.is_file())
        data = json.loads(main_module.FOLDER_SCAN_CACHE.read_text())
        self.assertIn("scans", data)

    def test_loose_audio_file_directly_in_scan_root_is_never_falsely_cached_as_unchanged(self):
        # library_index.build_library_index's own docstring: loose root
        # files (audio sitting directly in AUDIOBOOKS_ROOT, not inside any
        # subfolder) get NO signature entry in shared.signatures, and
        # AUDIOBOOKS_ROOT itself is never a key either. When the scan
        # target resolves to AUDIOBOOKS_ROOT, a loose top-level file's
        # "folder" (per _scan_book_units) is AUDIOBOOKS_ROOT itself, so a
        # naive per-folder signature comparison would compare against a
        # signature that structurally never exists and could misread that
        # perpetual absence as "unchanged forever". Prove instead that a
        # second file appearing loose at root is picked up on the very
        # next scan, not silently missed.
        self._touch("Loose1.m4b")
        first = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        first_total = first.json()["total"]

        self._touch("Loose2.m4b")
        second = client.post("/api/scan", json={"path": str(self.root), "ignored_folders": []})
        self.assertEqual(second.json()["total"], first_total + 1)


if __name__ == "__main__":
    unittest.main()
