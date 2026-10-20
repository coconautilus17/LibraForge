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
    def test_search_key_is_scoped_to_both_the_root_and_the_tool(self):
        root = Path("/library")
        key = search_cache_key(root, "fixer.py")
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertNotEqual(key, search_cache_key(root / "other", "fixer.py"))
        self.assertNotEqual(key, search_cache_key(root, "organizer.py"))

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


if __name__ == "__main__":
    unittest.main()
