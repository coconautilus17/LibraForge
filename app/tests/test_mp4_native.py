"""The in-process MP4 reader reports what ffprobe reports, on real files made with ffmpeg
and tagged with mutagen the way LibraForge and Audible tag them; and anything it does not
reproduce falls back to ffprobe instead of guessing."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

from app import media_probe, mp4_native
from app.tests.test_media_probe import make_m4b


def native_facts(path: Path) -> dict:
    n = mp4_native.read(path)
    return {"format_tags": media_probe._clean_tags(n["format_tags"]),
            "stream_tags": media_probe._clean_tags(n["stream_tags"]),
            "duration_seconds": n["duration_seconds"],
            "audio": media_probe.audio_properties(n["stream"], n["format"]),
            "chapter_count": n["chapter_count"]}


def ffprobe_facts(path: Path) -> dict:
    f = media_probe._read_ffprobe(path)
    return {"format_tags": f.format_tags, "stream_tags": f.stream_tags, "duration_seconds": f.duration_seconds,
            "audio": f.audio, "chapter_count": f.chapter_count}


class NativeMatchesFfprobeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def assertSameAsFfprobe(self, path: Path):
        self.assertEqual(native_facts(path), ffprobe_facts(path))

    def test_ffmpeg_output_with_a_chapter_track(self):
        self.assertSameAsFfprobe(make_m4b(self.dir / "a.m4b", chapters=4, seconds=3))

    def test_moov_before_the_media(self):
        book = make_m4b(self.dir / "a.m4b", chapters=2)
        fast = self.dir / "fast.m4b"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(book), "-map", "0:a", "-map_chapters", "0", "-c", "copy", "-movflags", "+faststart",
                        str(fast), "-y"], check=True)
        self.assertSameAsFfprobe(fast)

    def test_library_tags_written_by_mutagen(self):
        book = make_m4b(self.dir / "a.m4b", chapters=3)
        audio = MP4(str(book))
        audio.tags["\xa9nam"] = ["Dao Divinity"]
        audio.tags["\xa9gen"] = ["Fantasy", "Sci-Fi"]  # ffprobe keeps the first
        audio.tags["\xa9wrt"] = ["Bordeaux Black"]
        audio.tags["\xa9cmt"] = ["A long description.\nWith a second line."]
        audio.tags["trkn"] = [(3, 12)]
        audio.tags["disk"] = [(1, 0)]
        audio.tags["stik"] = [2]
        audio.tags["----:com.apple.iTunes:asin"] = [MP4FreeForm(b"B09MG9FJK1")]
        audio.tags["----:com.apple.iTunes:ASIN"] = [MP4FreeForm(b"NOREALASIN")]  # same key: the later one wins
        audio.tags["----:com.apple.iTunes:subtitle"] = [MP4FreeForm("Ünïcödé subtitle".encode())]
        audio.tags["----:com.apple.iTunes:mvnm"] = [MP4FreeForm(b"First Immortal")]
        audio.tags["\xa9mvn"] = ["First Immortal"]
        audio.tags["\xa9mvi"] = [1]
        audio.save()
        self.assertSameAsFfprobe(book)

    def test_opus_in_mp4_like_the_converted_library(self):
        book = self.dir / "a.m4b"
        meta = self.dir / "meta.txt"
        meta.write_text(";FFMETADATA1\ntitle=Opus Book\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1500\ntitle=One\n"
                        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=1500\nEND=3000\ntitle=Two\n")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-i", str(meta),
                        "-map_metadata", "1", "-map_chapters", "1", "-t", "3", "-c:a", "libopus", "-b:a", "32k",
                        "-f", "mp4", str(book), "-y"], check=True)
        self.assertEqual(native_facts(book)["audio"]["codec"], "opus")
        self.assertSameAsFfprobe(book)

    def test_itunsmpb_priming_and_a_zero_length_last_chapter(self):
        book = make_m4b(self.dir / "a.m4b", chapters=5, seconds=4)
        audio = MP4(str(book))
        audio.tags["----:com.apple.iTunes:iTunSMPB"] = [
            MP4FreeForm(b" 00000000 00000840 000001C0 0000000000020000 00000000")]
        audio.save()
        self.assertSameAsFfprobe(book)

    def test_a_file_without_chapters(self):
        book = self.dir / "plain.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2",
                        "-c:a", "aac", "-b:a", "64k", str(book), "-y"], check=True)
        self.assertSameAsFfprobe(book)


class LightReadTests(unittest.TestCase):
    """A light read skips the sample tables and cover images, yet reports the same
    tags, duration and chapters as a full read."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def assertLightMatchesFull(self, path: Path):
        full, light = mp4_native.read(path), mp4_native.read(path, light=True)
        for key in ("format_tags", "stream_tags", "duration_seconds", "chapter_count"):
            self.assertEqual(light[key], full[key], key)

    def test_a_long_book_with_a_chapter_track_and_a_cover(self):
        book = make_m4b(self.dir / "long.m4b", chapters=40, seconds=600)
        audio = MP4(str(book))
        audio.tags["covr"] = [MP4Cover(b"\xff\xd8\xff" + b"\1" * 300_000, MP4Cover.FORMAT_JPEG)]
        audio.tags["----:com.apple.iTunes:ASIN"] = [MP4FreeForm(b"B0TESTASIN")]
        audio.save()
        self.assertLightMatchesFull(book)
        # With small blocks, the 300 KB cover is plainly never read.
        with mock.patch.object(mp4_native, "LIGHT_BLOCK", 4096), \
                mock.patch.object(mp4_native.os, "pread", wraps=mp4_native.os.pread) as pread:
            mp4_native.read(book, light=True)
            light_bytes = sum(c.args[1] for c in pread.call_args_list)
        self.assertLess(light_bytes, 100_000)

    def test_a_file_without_chapters_or_tags(self):
        book = self.dir / "plain.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "30",
                        "-c:a", "aac", "-b:a", "64k", str(book), "-y"], check=True)
        self.assertLightMatchesFull(book)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        media_probe.reset()
        self.addCleanup(media_probe.reset)
        # The native reader runs only beside the ffprobe release it follows; the image ships it,
        # a test machine may not (Ubuntu 26.04 has FFmpeg 8.0).
        patcher = mock.patch.object(media_probe, "ffprobe_release", return_value=mp4_native.FFMPEG_RELEASE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_codec_it_does_not_read_goes_to_ffprobe(self):
        book = self.dir / "a.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1",
                        "-c:a", "alac", str(book), "-y"], check=True)
        with self.assertRaises(mp4_native.Unsupported):
            mp4_native.read(book)
        facts = media_probe.inspect(book)
        self.assertEqual((facts.backend, facts.audio["codec"]), ("ffprobe", "alac"))
        self.assertEqual(media_probe.stats().get("native_fallbacks"), 1)

    def test_with_another_ffprobe_release_ffprobe_reads_everything(self):
        book = make_m4b(self.dir / "a.m4b")
        with mock.patch.object(media_probe, "ffprobe_release", return_value="7.1"):
            self.assertEqual(media_probe.inspect(book).backend, "ffprobe")
        media_probe.reset()
        self.assertEqual(media_probe.inspect(book).backend, "native")

    def test_an_mp3_is_never_read_natively(self):
        book = self.dir / "a.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1",
                        str(book), "-y"], check=True)
        self.assertEqual(media_probe.inspect(book).backend, "ffprobe")

    def test_a_truncated_file_is_not_guessed(self):
        book = make_m4b(self.dir / "a.m4b")
        data = book.read_bytes()
        cut = self.dir / "cut.m4b"
        cut.write_bytes(data[: len(data) // 2])  # moov is at the end, so it is gone
        with self.assertRaises(mp4_native.Unsupported):
            mp4_native.read(cut)


if __name__ == "__main__":
    unittest.main()
