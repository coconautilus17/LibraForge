"""A tag save moves the audio at most once per book: the first save that has to
rewrite the file leaves spare room, and later edits (a cover, a longer
description) land inside it."""
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover

from app.tag_padding import REWRITE_PADDING, save_padding


def mdat_offset(path: Path) -> int:
    with path.open("rb") as fh:
        pos = 0
        while True:
            fh.seek(pos)
            size, kind = struct.unpack(">I4s", fh.read(8))
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
            if kind == b"mdat":
                return pos
            pos += size


class TagPaddingTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.book = self.dir / "book.m4b"
        # Like a fresh download: tags in front of the audio, no spare room.
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "5",
                        "-c:a", "aac", "-b:a", "8k", "-metadata", "title=Original", "-movflags", "+faststart",
                        "-f", "mp4", str(self.book), "-y"], check=True)

    def save(self, **tags):
        audio = MP4(str(self.book))
        for key, value in tags.items():
            audio.tags[key] = value
        audio.save(padding=save_padding)

    def test_first_rewrite_leaves_room_for_a_cover(self):
        before = mdat_offset(self.book)
        self.save(**{"\xa9nam": ["A much longer title than the original one"]})
        moved_to = mdat_offset(self.book)
        self.assertGreaterEqual(moved_to - before, REWRITE_PADDING)

        # A 600 KB cover afterwards fits: the audio stays where it is.
        self.save(covr=[MP4Cover(b"\xff\xd8" + b"\0" * 600_000, MP4Cover.FORMAT_JPEG)])
        self.assertEqual(mdat_offset(self.book), moved_to)

    def test_existing_room_is_kept_not_shrunk(self):
        self.save(**{"\xa9nam": ["Longer title"]})
        moved_to = mdat_offset(self.book)
        # A shorter tag would let mutagen trim the room, which moves the audio.
        self.save(**{"\xa9nam": ["T"]})
        self.assertEqual(mdat_offset(self.book), moved_to)


if __name__ == "__main__":
    unittest.main()
