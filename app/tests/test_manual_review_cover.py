"""_embedded_cover_bytes()/extract_current_cover() must return the actual
front cover (covr[0]), not an arbitrary embedded picture/video stream.

Bug: extract_current_cover used `ffmpeg -map 0:v:0` (the first stream ffmpeg
classifies as video) to grab the "cover" for manual review. Some M4Bs embed
several pictures (per-chapter thumbnails, stray art) as additional covr
entries, and the true front cover doesn't always land on ffmpeg's video
stream index 0 -- reproduced live on a real file where -map 0:v:0 returned
an unrelated leftover image while mutagen's covr[0] was the correct cover.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import main


def _make_silent_m4a(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
            "-t", "1", "-c:a", "aac", str(path), "-y",
        ],
        check=True,
    )


@unittest.skipUnless(sys.platform.startswith("linux"), "ffmpeg fixture requires the container env")
class EmbeddedCoverSelectionTests(unittest.TestCase):
    def test_first_covr_entry_is_used_when_multiple_covers_exist(self):
        from mutagen.mp4 import MP4, MP4Cover

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "book.m4b"
            _make_silent_m4a(audio_path)

            real_cover = b"\xff\xd8\xff" + b"REAL-COVER-BYTES" + b"\x00" * 50
            other_picture = b"\x89PNG\r\n\x1a\n" + b"UNRELATED-CHAPTER-ART"

            audio = MP4(str(audio_path))
            audio["covr"] = [
                MP4Cover(real_cover, imageformat=MP4Cover.FORMAT_JPEG),
                MP4Cover(other_picture, imageformat=MP4Cover.FORMAT_PNG),
            ]
            audio.save()

            result = main._embedded_cover_bytes(audio_path)

            self.assertIsNotNone(result)
            data, media_type = result
            self.assertEqual(data, real_cover)
            self.assertEqual(media_type, "image/jpeg")

    def test_extract_current_cover_prefers_embedded_tag_over_ffmpeg_stream_scan(self):
        from mutagen.mp4 import MP4, MP4Cover

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "book.m4b"
            _make_silent_m4a(audio_path)

            real_cover = b"\xff\xd8\xff" + b"REAL-COVER-BYTES" + b"\x00" * 50
            audio = MP4(str(audio_path))
            audio["covr"] = [MP4Cover(real_cover, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

            data, media_type = main.extract_current_cover(audio_path)

            self.assertEqual(data, real_cover)
            self.assertEqual(media_type, "image/jpeg")


if __name__ == "__main__":
    unittest.main()
