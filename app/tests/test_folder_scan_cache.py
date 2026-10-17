"""Tests for the disk-backed Folder Forge scan cache: load/save round trip
and tolerance for a missing or corrupt cache file, mirroring
conversion_cache.py's established pattern for M4B."""
import json
import tempfile
import unittest
from pathlib import Path

from app.folder_scan_cache import (
    FOLDER_SCAN_CACHE_VERSION,
    load_scan_cache_file,
    save_scan_cache_file,
    scan_cache_key,
)


class FolderScanCacheFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tmp.name) / "folder-scan-cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_empty_structure(self):
        cache = load_scan_cache_file(self.cache_path)
        self.assertEqual(cache, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}})

    def test_corrupt_file_returns_empty_structure(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text("{not valid json")
        cache = load_scan_cache_file(self.cache_path)
        self.assertEqual(cache, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}})

    def test_version_mismatch_returns_empty_structure(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"version": -1, "scans": {"x": {}}}))
        cache = load_scan_cache_file(self.cache_path)
        self.assertEqual(cache, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}})

    def test_save_then_load_round_trips(self):
        cache = {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {"key": {"a": 1}}}
        save_scan_cache_file(self.cache_path, cache)
        self.assertEqual(load_scan_cache_file(self.cache_path), cache)

    def test_cache_key_is_a_known_digest_so_it_only_changes_when_the_scheme_does(self):
        # Pinned: a silent change of the key recipe would orphan every user's cache file.
        import hashlib
        import json as _json
        expected = hashlib.sha256(_json.dumps({"ignored_folders": ["a", "b"], "path": "/audiobooks"},
                                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(scan_cache_key(Path("/audiobooks"), ["b", "A"]), expected)

    def test_cache_key_ignores_order_of_ignored_folders(self):
        p = Path("/audiobooks")
        self.assertEqual(scan_cache_key(p, ["a", "b"]), scan_cache_key(p, ["b", "a"]))

    def test_cache_key_differs_for_different_path(self):
        self.assertNotEqual(
            scan_cache_key(Path("/audiobooks"), []),
            scan_cache_key(Path("/audiobooks/_unorganized"), []),
        )


class ScanCacheKeyNormalisationTests(unittest.TestCase):
    P = Path("/library")

    def test_no_ignored_folders_none_and_empty_list_are_the_same_key(self):
        self.assertEqual(scan_cache_key(self.P, None), scan_cache_key(self.P, []))

    def test_blank_and_whitespace_tokens_do_not_change_the_key(self):
        self.assertEqual(scan_cache_key(self.P, ["", "   ", "Extras"]), scan_cache_key(self.P, ["Extras"]))

    def test_tokens_are_compared_trimmed_and_case_insensitively(self):
        self.assertEqual(scan_cache_key(self.P, ["  EXTRAS "]), scan_cache_key(self.P, ["extras"]))

    def test_a_different_ignored_set_gives_a_different_key(self):
        self.assertNotEqual(scan_cache_key(self.P, ["extras"]), scan_cache_key(self.P, ["extras", "samples"]))
        self.assertNotEqual(scan_cache_key(self.P, ["extras"]), scan_cache_key(self.P, None))

    def test_the_key_is_a_sha256_hex_digest(self):
        key = scan_cache_key(self.P, ["a"])
        self.assertRegex(key, r"^[0-9a-f]{64}$")


class SaveScanCacheFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_creates_missing_parent_folders(self):
        target = self.root / "a" / "b" / "cache.json"
        save_scan_cache_file(target, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {"k": 1}})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["scans"], {"k": 1})

    def test_save_leaves_no_temporary_file_behind(self):
        target = self.root / "cache.json"
        save_scan_cache_file(target, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}})
        self.assertEqual([p.name for p in self.root.iterdir()], ["cache.json"])

    def test_save_keeps_non_ascii_text_readable_and_ends_with_a_newline(self):
        target = self.root / "cache.json"
        save_scan_cache_file(target, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {"t": "Böse Žena"}})
        text = target.read_text(encoding="utf-8")
        self.assertIn("Böse Žena", text)
        self.assertTrue(text.endswith("\n"))

    def test_save_overwrites_an_existing_cache(self):
        target = self.root / "cache.json"
        save_scan_cache_file(target, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {"old": 1}})
        save_scan_cache_file(target, {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {"new": 2}})
        self.assertEqual(load_scan_cache_file(target)["scans"], {"new": 2})

    def test_a_cache_whose_scans_is_not_a_dict_is_discarded(self):
        target = self.root / "cache.json"
        target.write_text(json.dumps({"version": FOLDER_SCAN_CACHE_VERSION, "scans": []}), encoding="utf-8")
        self.assertEqual(load_scan_cache_file(target), {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}})
