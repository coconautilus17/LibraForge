"""Apply fetches covers while books are still being matched: once per cover, only
for books whose write will embed one, and a failed fetch is simply tried again
by the write."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.mp4 import MP4, MP4Cover

from app.tests.fixer_run import make_book
from app.tests.script_loader import load_script

FIXER = load_script("fixer_cover_prefetch", "audible-metadata-fixer-v5.py")
JPEG = (b"\xff\xd8\xff" + b"\0" * 64, "jpeg")


def matched(path: Path, url: str = "https://img.example/cover.jpg"):
    return FIXER.ItemResult(index=1, file_path=path, display_path=path, status="matched", clues={},
                            metadata={"edit_mode": "full", "cover_url": url})


class CoverPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bare = make_book(self.dir / "Bare.m4b", "Bare")
        self.covered = make_book(self.dir / "Covered.m4b", "Covered")
        audio = MP4(str(self.covered))
        audio.tags["covr"] = [MP4Cover(JPEG[0], MP4Cover.FORMAT_JPEG)]
        audio.save()

    def prefetch(self, *, cover_if_missing=True, replace_cover=False):
        prefetch = FIXER.CoverPrefetch(4, cover_if_missing, replace_cover)
        self.addCleanup(prefetch.shutdown)
        return prefetch

    def test_a_book_without_a_cover_is_fetched_once_and_the_write_uses_it(self):
        prefetch = self.prefetch()
        with mock.patch.object(FIXER, "fetch_cover_bytes", return_value=JPEG) as fetch, \
                mock.patch.object(FIXER, "_cover_prefetch", prefetch):
            prefetch.start(matched(self.bare))
            prefetch.start(matched(self.bare))
            self.assertEqual(FIXER.download_cover_bytes("https://img.example/cover.jpg"), JPEG)
        fetch.assert_called_once_with("https://img.example/cover.jpg")

    def test_a_book_that_has_a_cover_is_not_fetched_unless_covers_are_replaced(self):
        with mock.patch.object(FIXER, "fetch_cover_bytes", return_value=JPEG) as fetch:
            keep = self.prefetch()
            keep.start(matched(self.covered))
            self.assertIsNone(keep.take("https://img.example/cover.jpg"))
            replace = self.prefetch(cover_if_missing=False, replace_cover=True)
            replace.start(matched(self.covered))
            self.assertEqual(replace.take("https://img.example/cover.jpg"), JPEG)
        self.assertEqual(fetch.call_count, 1)

    def test_a_failed_fetch_is_tried_again_by_the_write(self):
        prefetch = self.prefetch()
        with mock.patch.object(FIXER, "fetch_cover_bytes", side_effect=[OSError("timeout"), JPEG]) as fetch, \
                mock.patch.object(FIXER, "_cover_prefetch", prefetch):
            prefetch.start(matched(self.bare))
            self.assertEqual(FIXER.download_cover_bytes("https://img.example/cover.jpg"), JPEG)
        self.assertEqual(fetch.call_count, 2)

    def test_only_full_matches_with_a_cover_url_are_fetched(self):
        prefetch = self.prefetch()
        series_only = matched(self.bare)
        series_only.metadata["edit_mode"] = "series_only"
        with mock.patch.object(FIXER, "fetch_cover_bytes", return_value=JPEG) as fetch:
            prefetch.start(series_only)
            prefetch.start(matched(self.bare, url=""))
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
