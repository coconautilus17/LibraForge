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


class MediaProbeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        media_probe.reset()
        self.addCleanup(media_probe.reset)

    def test_one_read_answers_every_field_and_is_remembered(self):
        book = make_m4b(self.dir / "a.m4b", chapters=3)
        facts = media_probe.inspect(book, {"tags"})
        self.assertEqual(facts.format_tags.get("title"), "Book")
        self.assertEqual(media_probe.chapter_count(book), 3)
        self.assertAlmostEqual(media_probe.duration_seconds(book), 2.0, delta=0.1)
        audio = media_probe.audio_properties_of(book)
        self.assertEqual((audio["codec"], audio["channels"], audio["sample_rate_hz"]), ("aac", 1, 8000))
        self.assertEqual(media_probe.stats()["ffprobe_runs"], 1)
        self.assertEqual(media_probe.stats()["memo_hits"], 3)

    def test_a_changed_file_is_read_again(self):
        book = make_m4b(self.dir / "a.m4b", title="First")
        self.assertEqual(media_probe.inspect(book).format_tags["title"], "First")
        make_m4b(self.dir / "b.m4b", title="Second", seconds=3)
        os.replace(self.dir / "b.m4b", book)
        self.assertEqual(media_probe.inspect(book).format_tags["title"], "Second")
        self.assertEqual(media_probe.stats()["ffprobe_runs"], 2)

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
        real = media_probe._read_ffprobe
        started = threading.Event()

        def slow(path):
            started.set()
            threading.Event().wait(0.3)
            return real(path)

        with mock.patch.object(media_probe, "_read_ffprobe", side_effect=slow):
            threads = [threading.Thread(target=media_probe.inspect, args=(book,)) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(media_probe.stats()["ffprobe_runs"], 1)

    def test_container_tags_win_over_stream_tags(self):
        facts = media_probe.MediaFacts(path="x", format_tags={"title": "Container"},
                                       stream_tags={"title": "Stream", "artist": "Only On Stream"})
        self.assertEqual(facts.merged_tags(), {"title": "Container", "artist": "Only On Stream"})


if __name__ == "__main__":
    unittest.main()
