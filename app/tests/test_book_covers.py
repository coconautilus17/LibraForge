"""Cover thumbnails: made once from the file's own cover, served from the reports
folder while the file is unchanged, never kept for a file that changed while it was
read, and the full image when a thumbnail can't be made."""
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

import app.main as main_module
from app import book_covers
from app.tests.test_media_probe import make_m4b


def jpeg(width: int, height: int, color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "JPEG")
    return out.getvalue()


def set_cover(path: Path, image: bytes) -> None:
    audio = MP4(str(path))
    audio["covr"] = [MP4Cover(image, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


class _BookWithCover(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.thumbs = self.dir / "thumbs"
        book_covers.configure(self.thumbs)
        self.addCleanup(book_covers.configure, None)
        (self.dir / "lib" / "Book").mkdir(parents=True)
        self.book = make_m4b(self.dir / "lib" / "Book" / "book.m4b")
        self.book.with_suffix(".ffmeta").unlink()
        set_cover(self.book, jpeg(1400, 1400))


class BookCoverThumbnailTests(_BookWithCover):
    def test_a_cover_becomes_a_small_jpeg_kept_until_the_file_changes(self):
        thumb = book_covers.embedded_thumbnail(self.book)
        self.assertEqual(Image.open(io.BytesIO(thumb)).size, (book_covers.THUMB_PIXELS, book_covers.THUMB_PIXELS))
        with mock.patch.object(book_covers, "embedded_cover_bytes") as read:
            self.assertEqual(book_covers.embedded_thumbnail(self.book), thumb)
        read.assert_not_called()
        set_cover(self.book, jpeg(600, 900, color=(10, 10, 200)))
        again = book_covers.embedded_thumbnail(self.book)
        self.assertEqual(Image.open(io.BytesIO(again)).size, (213, 320))
        self.assertEqual(len(list(self.thumbs.glob("*.jpg"))), 1)  # the old version's is gone

    def test_a_file_that_changes_while_its_cover_is_read_is_not_kept(self):
        real = book_covers.embedded_cover_bytes

        def read_then_rewrite(path):
            cover = real(path)
            os.utime(path, ns=(1, 1))
            return cover
        with mock.patch.object(book_covers, "embedded_cover_bytes", side_effect=read_then_rewrite):
            self.assertIsNotNone(book_covers.embedded_thumbnail(self.book))
        self.assertEqual(list(self.thumbs.glob("*.jpg")), [])

    def test_a_file_without_a_cover_or_with_an_unreadable_one_gets_none(self):
        plain = make_m4b(self.dir / "lib" / "Book" / "plain.m4b")
        self.assertIsNone(book_covers.embedded_thumbnail(plain))
        set_cover(plain, b"\xff\xd8\xff" + b"not really a picture")
        self.assertIsNone(book_covers.embedded_thumbnail(plain))
        self.assertEqual(list(self.thumbs.glob("*.jpg")), [])


class BookCoverRouteTests(_BookWithCover):
    def setUp(self):
        super().setUp()
        root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = (self.dir / "lib").resolve()
        self.addCleanup(setattr, main_module, "AUDIOBOOKS_ROOT", root)

    def test_the_route_serves_the_thumbnail_for_a_file_and_a_folder(self):
        for target in (self.book, self.book.parent):
            response = main_module.book_cover(str(target))
            self.assertEqual(response.media_type, "image/jpeg")
            self.assertEqual(Image.open(io.BytesIO(response.body)).size, (320, 320))

    def test_a_folder_cover_image_is_used_before_the_audio_file(self):
        (self.book.parent / "cover.jpg").write_bytes(jpeg(800, 400, color=(0, 200, 0)))
        response = main_module.book_cover(str(self.book.parent))
        self.assertEqual(Image.open(io.BytesIO(response.body)).size, (320, 160))

    def test_an_image_that_cannot_be_shrunk_is_served_whole(self):
        odd = b"\xff\xd8\xff" + b"not really a picture"
        (self.book.parent / "cover.jpg").write_bytes(odd)
        self.assertEqual(main_module.book_cover(str(self.book.parent)).body, odd)


if __name__ == "__main__":
    unittest.main()
