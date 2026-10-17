import tempfile
import unittest
from pathlib import Path

from app.conversion_cache import (
    CACHE_VERSION,
    CachedAudioProbeReader,
    CachedChapterCountReader,
    load_discovery_cache,
    save_discovery_cache,
    search_cache_key,
)


class ConversionCacheTests(unittest.TestCase):
    def test_search_key_is_stable_and_scoped(self):
        root = Path("/library")
        self.assertEqual(
            search_cache_key(root, "fixer.py"),
            search_cache_key(root, "fixer.py"),
        )
        self.assertNotEqual(
            search_cache_key(root, "fixer.py"),
            search_cache_key(root / "other", "fixer.py"),
        )

    def test_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache = {"version": CACHE_VERSION, "searches": {"key": {"results": {}}}}

            save_discovery_cache(cache_path, cache)

            self.assertEqual(load_discovery_cache(cache_path), cache)

    def test_unchanged_file_reuses_chapter_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = Path(temp_dir) / "book.m4b"
            audio.write_bytes(b"audio")
            calls = []

            def probe(path):
                calls.append(path)
                return 12

            reader = CachedChapterCountReader(probe=probe)
            self.assertEqual(reader(audio), 12)
            self.assertEqual(reader(audio), 12)
            self.assertEqual(len(calls), 1)
            self.assertEqual(reader.probed, 1)
            self.assertEqual(reader.reused, 1)

    def test_changed_file_is_probed_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = Path(temp_dir) / "book.m4b"
            audio.write_bytes(b"audio")
            values = iter((2, 3))
            reader = CachedChapterCountReader(probe=lambda _path: next(values))

            self.assertEqual(reader(audio), 2)
            audio.write_bytes(b"changed audio")
            self.assertEqual(reader(audio), 3)
            self.assertEqual(reader.probed, 2)

    def test_audio_probe_is_cached_by_file_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = Path(temp_dir) / "book.m4a"
            audio.write_bytes(b"audio")
            calls = []

            def probe(path):
                calls.append(path)
                return {"probed": True, "codec": "aac"}

            reader = CachedAudioProbeReader(probe=probe)
            self.assertEqual(reader(audio)["codec"], "aac")
            self.assertEqual(reader(audio)["codec"], "aac")
            self.assertEqual(len(calls), 1)
            self.assertEqual(reader.probed, 1)
            self.assertEqual(reader.reused, 1)

    def test_audio_probe_is_reused_after_cache_file_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "book.m4a"
            cache_path = root / "cache.json"
            audio.write_bytes(b"audio")

            first = CachedAudioProbeReader(
                probe=lambda _path: {"probed": True, "codec": "aac"}
            )
            self.assertEqual(first(audio)["codec"], "aac")
            save_discovery_cache(
                cache_path,
                {
                    "version": CACHE_VERSION,
                    "searches": {
                        "key": {"audio_probes": first.pruned_entries()}
                    },
                },
            )

            calls = []
            reloaded = load_discovery_cache(cache_path)
            second = CachedAudioProbeReader(
                probe=lambda path: calls.append(path) or {"probed": True},
                entries=reloaded["searches"]["key"]["audio_probes"],
            )

            self.assertEqual(second(audio)["codec"], "aac")
            self.assertEqual(calls, [])
            self.assertEqual(second.reused, 1)
            self.assertEqual(second.probed, 0)


class ConversionCacheDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_timestamp_is_utc_iso8601_to_the_second(self):
        import re
        from app.conversion_cache import utc_timestamp
        self.assertRegex(utc_timestamp(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_saved_cache_is_readable_utf8_ends_with_a_newline_and_leaves_no_temp_file(self):
        target = self.dir / "sub" / "cache.json"
        save_discovery_cache(target, {"version": CACHE_VERSION, "searches": {"k": {"title": "Böse"}}})
        text = target.read_text(encoding="utf-8")
        self.assertIn("Böse", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual([p.name for p in target.parent.iterdir()], ["cache.json"])

    def _file(self, size=10):
        path = self.dir / "a.mp3"
        path.write_bytes(b"x" * size)
        return path

    def test_chapter_reader_reuses_an_entry_only_when_size_and_mtime_both_match(self):
        from app.conversion_cache import file_signature
        path = self._file()
        sig = file_signature(path)
        calls = []
        def probe(p):
            calls.append(p)
            return 7
        for entry, expect_probe in (
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"], "chapter_count": 3}, False),
            ({"size": sig["size"] + 1, "mtime_ns": sig["mtime_ns"], "chapter_count": 3}, True),
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"] + 1, "chapter_count": 3}, True),
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"]}, True),
        ):
            calls.clear()
            reader = CachedChapterCountReader(probe=probe, entries={str(path): dict(entry)})
            result = reader(path)
            self.assertEqual(bool(calls), expect_probe, entry)
            self.assertEqual(result, 7 if expect_probe else 3)
            self.assertEqual((reader.reused, reader.probed), (0, 1) if expect_probe else (1, 0))

    def test_audio_reader_reuses_an_entry_only_when_size_and_mtime_both_match(self):
        from app.conversion_cache import file_signature
        path = self._file()
        sig = file_signature(path)
        calls = []
        def probe(p):
            calls.append(p)
            return {"codec": "fresh"}
        for entry, expect_probe in (
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"], "audio": {"codec": "cached"}}, False),
            ({"size": sig["size"] + 1, "mtime_ns": sig["mtime_ns"], "audio": {"codec": "cached"}}, True),
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"] + 1, "audio": {"codec": "cached"}}, True),
            ({"size": sig["size"], "mtime_ns": sig["mtime_ns"], "audio": "not-a-dict"}, True),
        ):
            calls.clear()
            reader = CachedAudioProbeReader(probe=probe, entries={str(path): dict(entry)})
            result = reader(path)
            self.assertEqual(bool(calls), expect_probe, entry)
            self.assertEqual(result["codec"], "fresh" if expect_probe else "cached")

    def test_pruned_entries_keep_only_files_seen_this_run_in_path_order(self):
        reader = CachedChapterCountReader(probe=lambda p: 1, entries={
            "/z.mp3": {"chapter_count": 1}, "/a.mp3": {"chapter_count": 2}, "/gone.mp3": {"chapter_count": 3}})
        reader.seen.update({"/z.mp3", "/a.mp3", "/new.mp3"})
        pruned = reader.pruned_entries()
        self.assertEqual(list(pruned), ["/a.mp3", "/z.mp3"])
        self.assertNotIn("/gone.mp3", pruned)


if __name__ == "__main__":
    unittest.main()
