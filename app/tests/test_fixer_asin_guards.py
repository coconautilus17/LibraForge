"""The Metadata Fixer's library-wide duplicate-ASIN guard (so one ASIN never ends
up on two books), the on-disk ASIN cache that feeds it, and the cover download
checks."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from app.tests.script_loader import load_script

FIXER = load_script("fixer_asin_guards", "audible-metadata-fixer-v5.py")


def result(path, asin, status="matched", conflict=False):
    return FIXER.ItemResult(index=1, file_path=Path(path), display_path=Path(path), status=status,
                            metadata={"asin": asin} if asin is not None else None, asin_conflict=conflict)


class GlobalDuplicateTests(unittest.TestCase):
    def test_the_book_that_already_owns_the_asin_is_not_flagged_when_it_rewrites_it(self):
        owner = result("/lib/A/owner.m4b", "B0X")
        other = result("/lib/B/new.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([owner, other], {"B0X": {"/lib/A/owner.m4b"}})
        self.assertFalse(owner.asin_conflict)
        self.assertTrue(other.asin_conflict)

    def test_several_books_in_one_run_claiming_a_new_asin_are_all_flagged(self):
        a, b = result("/lib/A/a.m4b", "B0X"), result("/lib/B/b.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([a, b], {})
        self.assertTrue(a.asin_conflict and b.asin_conflict)
        self.assertEqual(a.review_reasons, ["duplicate Audible ASIN B0X: matched to 2 different books in this run"])

    def test_unmatched_flagged_or_asinless_results_are_ignored(self):
        skipped = result("/lib/A/s.m4b", "B0X", status="skipped")
        flagged = result("/lib/B/f.m4b", "B0X", conflict=True)
        blank = result("/lib/C/c.m4b", "")
        none = result("/lib/D/d.m4b", None)
        fine = result("/lib/E/e.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([skipped, flagged, blank, none, fine], {})
        self.assertFalse(fine.asin_conflict)
        self.assertFalse(skipped.asin_conflict or blank.asin_conflict)

class DiskAsinMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(FIXER, "DISK_ASIN_CACHE_PATH", self.root / "cache" / "asin.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def book(self, name, content=b"x"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_many_workers_give_the_same_map_as_one(self):
        files = [self.book(f"b{i} [B0WORK000{i}].m4b") for i in range(4)]
        self.assertEqual(FIXER.build_disk_asin_map(files, workers=4), FIXER.build_disk_asin_map(files, workers=1))

class CoverDownloadTests(unittest.TestCase):
    JPEG = b"\xff\xd8\xff" + b"0" * 10
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 10

    class Response:
        def __init__(self, data, content_type=""):
            self.data, self.headers = data, {"Content-Type": content_type}
        def read(self, n=-1):
            return self.data[:n] if n >= 0 else self.data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fetch(self, data, content_type=""):
        with mock.patch("urllib.request.urlopen", return_value=self.Response(data, content_type)):
            return FIXER.download_cover_bytes("https://x.test/c")

    def test_the_content_type_decides_when_the_bytes_are_unrecognised(self):
        self.assertEqual(self.fetch(b"zzz", "image/JPEG")[1], "jpeg")
        self.assertEqual(self.fetch(b"zzz", "image/jpg")[1], "jpeg")
        self.assertEqual(self.fetch(b"zzz", "image/png")[1], "png")

    def test_a_local_file_must_come_from_the_upload_folder(self):
        with self.assertRaisesRegex(RuntimeError, "must come from a LibraForge upload"):
            FIXER.download_cover_bytes("file:///etc/passwd")
        upload = Path(tempfile.gettempdir()) / "libraforge-cover-uploads"
        upload.mkdir(exist_ok=True)
        target = upload / "audit-cover.jpg"
        target.write_bytes(self.JPEG)
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        self.assertEqual(FIXER.download_cover_bytes(target.resolve().as_uri()), (self.JPEG, "jpeg"))

    def test_cover_presence_helpers(self):
        self.assertTrue(FIXER.mp4_has_cover({"covr": [b"x"]}))
        self.assertFalse(FIXER.mp4_has_cover({"covr": []}))
        self.assertFalse(FIXER.mp4_has_cover({}))
        self.assertTrue(FIXER.mp3_has_cover(types.SimpleNamespace(getall=lambda k: ["a"])))
        self.assertFalse(FIXER.mp3_has_cover(types.SimpleNamespace(getall=lambda k: [])))


if __name__ == "__main__":
    unittest.main()
