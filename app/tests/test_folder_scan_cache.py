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

    def test_cache_key_is_stable_for_same_inputs(self):
        p = Path("/audiobooks")
        self.assertEqual(scan_cache_key(p, ["a", "b"]), scan_cache_key(p, ["a", "b"]))

    def test_cache_key_ignores_order_of_ignored_folders(self):
        p = Path("/audiobooks")
        self.assertEqual(scan_cache_key(p, ["a", "b"]), scan_cache_key(p, ["b", "a"]))

    def test_cache_key_differs_for_different_path(self):
        self.assertNotEqual(
            scan_cache_key(Path("/audiobooks"), []),
            scan_cache_key(Path("/audiobooks/_unorganized"), []),
        )
