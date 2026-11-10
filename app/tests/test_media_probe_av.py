"""Reading with FFmpeg's libraries in-process (PyAV) answers what ffprobe answers, and a
file PyAV can't open is still read by ffprobe. Uses small real files made with ffmpeg."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import media_probe


def make(path: Path, *codec_args: str, chapters: int = 0) -> Path:
    meta = path.with_name(path.name + ".ffmeta")
    lines = [";FFMETADATA1", "title=Some Book", "artist=Some Author", "album=Some Series"]
    for i in range(chapters):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={i * 500}", f"END={(i + 1) * 500}", f"title=Chapter {i + 1}"]
    meta.write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                    "-i", str(meta), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1", "-t", "2",
                    *codec_args, str(path), "-y"], check=True)
    meta.unlink()
    return path


@unittest.skipUnless(media_probe.av, "PyAV not installed")
class InProcessReadTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        media_probe.reset()
        self.addCleanup(media_probe.reset)

    def assertSameAsFfprobe(self, path: Path) -> media_probe.MediaFacts:
        ours = media_probe._read_av(path)
        theirs = media_probe._read_ffprobe(path)
        self.assertEqual(ours.backend, "av")
        # PyAV carries a newer FFmpeg than the image's ffprobe 6.1, which no longer
        # reports an all-zero MP4 vendor_id; nothing in LibraForge reads it.
        their_stream_tags = {k: v for k, v in theirs.stream_tags.items()
                             if not (k == "vendor_id" and v == "[0][0][0][0]")}
        self.assertEqual((ours.fields, ours.format_tags, ours.stream_tags, ours.chapter_count),
                         (theirs.fields, theirs.format_tags, their_stream_tags, theirs.chapter_count))
        self.assertAlmostEqual(ours.duration_seconds, theirs.duration_seconds, delta=0.05)
        for key in ("probed", "codec", "container", "bitrate_kbps", "channels", "sample_rate_hz"):
            self.assertEqual(ours.audio[key], theirs.audio[key], key)
        return ours

    def test_an_mp3_with_chapters(self):
        facts = self.assertSameAsFfprobe(make(self.dir / "a.mp3", "-c:a", "libmp3lame", "-b:a", "64k", chapters=3))
        self.assertEqual((facts.format_tags["title"], facts.chapter_count, facts.audio["codec"]),
                         ("Some Book", 3, "mp3"))

    def test_an_opus_file(self):
        self.assertSameAsFfprobe(make(self.dir / "a.opus", "-c:a", "libopus", "-b:a", "32k"))

    def test_an_mp4_the_native_reader_passes_on(self):
        facts = self.assertSameAsFfprobe(make(self.dir / "a.m4a", "-c:a", "alac"))
        self.assertEqual(facts.audio["codec"], "alac")

    def test_a_file_it_cannot_open_goes_to_ffprobe(self):
        junk = self.dir / "junk.mp3"
        junk.write_bytes(b"not audio at all")
        facts = media_probe.inspect(junk)
        self.assertEqual((facts.backend, facts.fields), ("ffprobe", frozenset()))
        self.assertEqual((media_probe.stats()["av_fallbacks"], media_probe.stats()["ffprobe_runs"]), (1, 1))

    def test_an_mp3_is_one_read_in_process(self):
        book = make(self.dir / "a.mp3", "-c:a", "libmp3lame")
        with mock.patch.object(media_probe, "_read_ffprobe") as ffprobe:
            media_probe.inspect(book, {"tags"})
            self.assertEqual(media_probe.chapter_count(book), 0)
            self.assertIsNotNone(media_probe.audio_properties_of(book)["codec"])
        ffprobe.assert_not_called()
        self.assertEqual(media_probe.stats()["av_reads"], 1)

    def test_facts_read_with_another_ffmpeg_library_are_dropped(self):
        self.assertIn(".".join(map(str, media_probe.av.library_versions["libavformat"])),
                      media_probe.reader_identity())


if __name__ == "__main__":
    unittest.main()
