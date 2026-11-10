"""Scan completeness: the reports-side tag cache, legacy scan_cache reads, and no library writes.

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
from app.book_tag_cache import BookTagCache
from app.main import (
    _CORE_FIELDS,
    _book_metadata_state,
    _marker_says_no_asin,
    _probe_book_metadata,
    _scan_cache_from_sidecar,
)

client = TestClient(main_module.app)


class BookTagCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache_path = self.root / "reports" / "book-tag-cache.json"
        self.cache_path.parent.mkdir()
        self.cache = BookTagCache(self.cache_path)
        original = main_module.BOOK_TAG_CACHE
        main_module.BOOK_TAG_CACHE = self.cache
        self.addCleanup(setattr, main_module, "BOOK_TAG_CACHE", original)
        self.audio = self.root / "lib" / "Book" / "Book.m4b"
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b"not a real m4b")

    def test_a_read_is_remembered_in_the_reports_folder_not_the_library(self):
        _book_metadata_state(self.audio.parent, [self.audio])
        self.cache.save()
        self.assertEqual([p.name for p in self.audio.parent.iterdir()], ["Book.m4b"])
        reloaded = BookTagCache(self.cache_path)
        mtime = self.audio.stat().st_mtime_ns
        self.assertEqual(reloaded.get(self.audio, mtime), {"asin": "", "fields": {f: False for f in _CORE_FIELDS}})

    def test_a_remembered_read_is_used_until_the_file_changes(self):
        mtime = self.audio.stat().st_mtime_ns
        self.cache.put(self.audio, mtime, {"asin": "B0AAAA1111", "fields": {f: True for f in _CORE_FIELDS}})
        self.assertEqual(_book_metadata_state(self.audio.parent, [self.audio]),
                         (True, {f: True for f in _CORE_FIELDS}))
        self.assertIsNone(self.cache.get(self.audio, mtime + 1))

    def test_a_no_match_marker_still_counts_as_asin_satisfied(self):
        (self.audio.parent / "libraforge.json").write_text(
            json.dumps({"marker": {"audible": {"asin": "NOREALASIN"}, "source_file": "Book.m4b"}}), encoding="utf-8")
        satisfied, _ = _book_metadata_state(self.audio.parent, [self.audio])
        self.assertIs(satisfied, True)


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
        self.assertIs(satisfied, True)

    def test_marker_claiming_real_asin_does_not_satisfy(self):
        # marker claims a real ASIN but the embedded tag (scan_cache) is absent.
        self._write({"scan_cache": self._scan_cache("NOREALASIN"),
                     "marker": {"audible": {"asin": "B0CLAIM1234"}}})
        satisfied, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertFalse(satisfied)

    def test_embedded_asin_satisfies(self):
        self._write({"scan_cache": self._scan_cache("B0EMBED1234")})
        satisfied, _ = _scan_cache_from_sidecar(self.audio, self.audio.parent)
        self.assertIs(satisfied, True)


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
        self._orig_tag_cache = main_module.BOOK_TAG_CACHE
        main_module.BOOK_TAG_CACHE = BookTagCache(self.root / "book-tag-cache.json")
        library_index.reset_state_for_tests()

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module.FOLDER_SCAN_CACHE = self._orig_cache_path
        main_module.BOOK_TAG_CACHE = self._orig_tag_cache
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
        self.assertEqual(second.json()["total"], first_total + 1)

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

    def test_a_scan_writes_nothing_into_the_library(self):
        self._touch("Author/Book1/Book1.m4b")
        self._touch("Author/Shared/A.m4b")
        self._touch("Author/Shared/B.m4b")
        before = sorted(p.relative_to(self.root) for p in (self.root / "Author").rglob("*"))
        client.post("/api/scan", json={"path": str(self.root / "Author"), "ignored_folders": []})
        after = sorted(p.relative_to(self.root) for p in (self.root / "Author").rglob("*"))
        self.assertEqual(after, before)

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

    def test_two_standalone_books_sharing_a_folder_keep_distinct_categories_after_cache_hit(self):
        # Critical whole-branch review finding: _scan_book_units explicitly yields ONE
        # UNIT PER standalone book, so a folder holding two complete standalone books
        # (e.g. an _unorganized dump folder with a.m4b and b.mp3 side by side) produces
        # two units sharing the same folder_key. The per-folder cache must not collapse
        # their two distinct categories into a single stored value -- whichever unit's
        # write happened to run last in the loop used to silently win for both on the
        # next (cache-hit) call.
        complete = self._touch("Unorganized/A.mp3")
        incomplete = self._touch("Unorganized/B.m4b")
        main_module.BOOK_TAG_CACHE.put(
            complete, complete.stat().st_mtime_ns,
            {"asin": "B0COMPLETE1", "fields": {"title": True, "author": True, "narrator": True}},
        )
        scan_root = self.root / "Unorganized"

        first = client.post("/api/scan/books", json={"path": str(scan_root), "ignored_folders": []})
        self.assertEqual(first.status_code, 200)
        first_by_path = {b["path"]: b["category"] for b in first.json()["books"]}
        self.assertEqual(first_by_path.get(str(complete)), "needs_conversion")
        self.assertEqual(first_by_path.get(str(incomplete)), "needs_metadata")

        # Second call: the folder's listing signature is unchanged, so both units
        # should be served from the cache -- but each must still resolve to its own
        # correct category, not both collapsed to whichever one was written last.
        second = client.post("/api/scan/books", json={"path": str(scan_root), "ignored_folders": []})
        self.assertEqual(second.status_code, 200)
        second_by_path = {b["path"]: b["category"] for b in second.json()["books"]}
        self.assertEqual(second_by_path.get(str(complete)), "needs_conversion")
        self.assertEqual(second_by_path.get(str(incomplete)), "needs_metadata")

    def test_scan_counts_stay_correct_for_two_standalone_books_sharing_a_folder(self):
        # Same bug as above, proven via /api/scan's aggregate counts: needs_conversion
        # and needs_metadata must both stay 1 after a cached second call, not collapse
        # onto a single category counted twice while the other silently drops to zero.
        complete = self._touch("Dump/A.mp3")
        self._touch("Dump/B.m4b")
        main_module.BOOK_TAG_CACHE.put(
            complete, complete.stat().st_mtime_ns,
            {"asin": "B0COMPLETE2", "fields": {"title": True, "author": True, "narrator": True}},
        )
        scan_root = self.root / "Dump"

        first = client.post("/api/scan", json={"path": str(scan_root), "ignored_folders": []})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["needs_conversion"], 1)
        self.assertEqual(first.json()["needs_metadata"], 1)

        second = client.post("/api/scan", json={"path": str(scan_root), "ignored_folders": []})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["needs_conversion"], 1)
        self.assertEqual(second.json()["needs_metadata"], 1)

    def test_standalone_loose_file_with_no_real_cover_reports_has_cover_false(self):
        # Task 6 review finding: scan_books_route's fast_entry computed has_cover
        # from `ref` (the unit's display path), which for a standalone unit IS the
        # audio file itself -- _has_cover_fast short-circuits to True for any file,
        # regardless of whether the containing folder actually has a cover or
        # sibling audio. The correct check targets book_dir (the containing
        # folder), matching the pre-Task-6 slow-path behavior. .flac is used here
        # because it falls outside _AUDIO_EXTS_COVER (m4b/m4a/mp3/mp4), so the
        # folder-based check can't accidentally match the book's own file either.
        self._touch("Author/notes.txt")
        self._touch("Author/loose.flac")
        resp = client.post("/api/scan/books", json={"path": str(self.root), "ignored_folders": []})
        self.assertEqual(resp.status_code, 200)
        books = resp.json()["books"]
        self.assertEqual(len(books), 1)
        self.assertFalse(books[0]["has_cover"])


if __name__ == "__main__":
    unittest.main()
