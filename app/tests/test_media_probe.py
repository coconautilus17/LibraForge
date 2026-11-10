"""The shared media inspection: one read per unchanged file answers every field, a
changed file is read again, a failed read is never remembered, and concurrent askers
share one read. Uses small real files made with ffmpeg."""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import media_probe


def make_m4b(path: Path, *, title: str = "Book", chapters: int = 2, seconds: int = 2) -> Path:
    meta = path.with_suffix(".ffmeta")
    lines = [";FFMETADATA1", f"title={title}", "artist=Some Author"]
    step = seconds * 1000 // chapters
    for i in range(chapters):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={i * step}", f"END={(i + 1) * step}", f"title=Chapter {i + 1}"]
    meta.write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-i", str(meta),
                    "-map_metadata", "1", "-map_chapters", "1", "-t", str(seconds), "-c:a", "aac",
                    "-f", "mp4", str(path), "-y"], check=True)
    return path


def reads() -> int:
    """Files actually read, in-process or by ffprobe."""
    stats = media_probe.stats()
    return (stats.get("ffprobe_runs", 0) + stats.get("native_reads", 0) + stats.get("native_light_reads", 0)
            + stats.get("av_reads", 0))


class MediaProbeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        media_probe.reset()
        self.addCleanup(media_probe.reset)

    def test_one_read_answers_every_field_and_is_remembered(self):
        book = make_m4b(self.dir / "a.m4b", chapters=3)
        audio = media_probe.audio_properties_of(book)
        self.assertEqual((audio["codec"], audio["channels"], audio["sample_rate_hz"]), ("aac", 1, 8000))
        facts = media_probe.inspect(book, {"tags"})
        self.assertEqual(facts.format_tags.get("title"), "Book")
        self.assertEqual(media_probe.chapter_count(book), 3)
        self.assertAlmostEqual(media_probe.duration_seconds(book), 2.0, delta=0.1)
        self.assertEqual(reads(), 1)
        self.assertEqual(media_probe.stats()["memo_hits"], 3)

    def test_without_audio_wanted_the_sample_tables_are_skipped(self):
        book = make_m4b(self.dir / "a.m4b", chapters=3)
        light = media_probe.inspect(book, {"tags", "duration", "chapters"})
        self.assertEqual(media_probe.stats().get("native_light_reads"), 1)
        self.assertNotIn("audio", light.fields)
        # Asking for audio afterwards reads the file in full once; the rest agrees.
        full = media_probe.inspect(book)
        self.assertEqual(media_probe.stats().get("native_reads"), 1)
        self.assertEqual((full.format_tags, full.duration_seconds, full.chapter_count),
                         (light.format_tags, light.duration_seconds, light.chapter_count))
        self.assertIsNotNone(media_probe.audio_properties_of(book))
        self.assertEqual(reads(), 2)

    def test_stored_facts_without_audio_are_not_served_for_audio(self):
        store = self.dir / "facts.sqlite"
        media_probe.configure_store(store)
        self.addCleanup(media_probe.configure_store, None)
        book = make_m4b(self.dir / "a.m4b")
        media_probe.inspect(book, {"tags"})
        media_probe.reset()
        media_probe.configure_store(store)
        self.assertEqual(media_probe.audio_properties_of(book)["codec"], "aac")
        self.assertEqual(media_probe.stats().get("native_reads"), 1)

    def test_a_changed_file_is_read_again(self):
        book = make_m4b(self.dir / "a.m4b", title="First")
        self.assertEqual(media_probe.inspect(book).format_tags["title"], "First")
        make_m4b(self.dir / "b.m4b", title="Second", seconds=3)
        os.replace(self.dir / "b.m4b", book)
        self.assertEqual(media_probe.inspect(book).format_tags["title"], "Second")
        self.assertEqual(reads(), 2)

    def test_a_failed_read_is_unknown_and_not_remembered(self):
        junk = self.dir / "junk.m4b"
        junk.write_bytes(b"not audio at all")
        for _ in range(2):
            facts = media_probe.inspect(junk)
            self.assertEqual(facts.fields, frozenset())
            self.assertTrue(facts.error)
            self.assertIsNone(media_probe.chapter_count(junk))
            self.assertIsNone(media_probe.duration_seconds(junk))
            self.assertEqual(media_probe.audio_properties_of(junk), {"probed": False})
        self.assertEqual(media_probe.stats()["ffprobe_runs"], 8)
        self.assertEqual(media_probe.stats().get("memo_hits", 0), 0)

    def test_a_file_without_chapters_has_zero_not_unknown(self):
        book = self.dir / "plain.m4b"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1",
                        "-c:a", "aac", str(book), "-y"], check=True)
        self.assertEqual(media_probe.chapter_count(book), 0)

    def test_concurrent_askers_share_one_read(self):
        book = make_m4b(self.dir / "a.m4b")
        real = media_probe._read
        started = threading.Event()

        def slow(path, *args):
            started.set()
            threading.Event().wait(0.3)
            return real(path, *args)

        with mock.patch.object(media_probe, "_read", side_effect=slow):
            threads = [threading.Thread(target=media_probe.inspect, args=(book,)) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(reads(), 1)

    def test_the_store_answers_a_new_process_until_the_file_changes(self):
        book = make_m4b(self.dir / "a.m4b", title="First", chapters=3)
        media_probe.configure_store(self.dir / "facts.sqlite")
        self.addCleanup(media_probe.configure_store, None)
        first = media_probe.inspect(book)
        media_probe.reset()  # a new process: nothing in memory
        again = media_probe.inspect(book)
        self.assertEqual(media_probe.stats().get("store_hits"), 1)
        self.assertEqual(reads(), 0)
        self.assertEqual((again.format_tags, again.chapter_count, again.duration_seconds, again.audio, again.fields),
                         (first.format_tags, first.chapter_count, first.duration_seconds, first.audio, first.fields))
        make_m4b(self.dir / "b.m4b", title="Second")
        os.replace(self.dir / "b.m4b", book)
        media_probe.reset()
        self.assertEqual(media_probe.inspect(book).format_tags["title"], "Second")
        self.assertEqual(media_probe.stats().get("store_hits", 0), 0)

    def test_facts_from_another_reader_version_are_dropped(self):
        book = make_m4b(self.dir / "a.m4b")
        media_probe.configure_store(self.dir / "facts.sqlite")
        self.addCleanup(media_probe.configure_store, None)
        media_probe.inspect(book)
        with mock.patch.object(media_probe, "READER_VERSION", media_probe.READER_VERSION + 1):
            media_probe.configure_store(self.dir / "facts.sqlite")
            media_probe.reset()
            media_probe.inspect(book)
        self.assertEqual(media_probe.stats().get("store_hits", 0), 0)

    def test_prune_forgets_deleted_files_but_never_on_an_empty_root(self):
        library = self.dir / "library"
        library.mkdir()
        kept = make_m4b(library / "kept.m4b")
        gone = make_m4b(library / "gone.m4b")
        media_probe.configure_store(self.dir / "facts.sqlite")
        self.addCleanup(media_probe.configure_store, None)
        media_probe.inspect(kept)
        media_probe.inspect(gone)
        gone.unlink()
        self.assertEqual(media_probe.prune_missing(library), 1)
        self.assertEqual(media_probe._store.paths_under(str(library)), [str(kept)])
        # An unmounted share is an empty folder: nothing is pruned.
        kept.rename(self.dir / "kept.m4b")
        for leftover in library.glob("*.ffmeta"):
            leftover.unlink()
        self.assertEqual(media_probe.prune_missing(library), 0)
        self.assertEqual(media_probe.prune_missing(self.dir / "missing"), 0)
        self.assertEqual(media_probe._store.paths_under(str(library)), [str(kept)])

    def test_container_tags_win_over_stream_tags(self):
        facts = media_probe.MediaFacts(path="x", format_tags={"title": "Container"},
                                       stream_tags={"title": "Stream", "artist": "Only On Stream"})
        self.assertEqual(facts.merged_tags(), {"title": "Container", "artist": "Only On Stream"})


if __name__ == "__main__":
    unittest.main()
