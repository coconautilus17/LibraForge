"""The Metadata Fixer's library-wide duplicate-ASIN guard (so one ASIN never ends
up on two books), the on-disk ASIN cache that feeds it, and the cover download
checks."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_asin_guards", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


def result(path, asin, status="matched", conflict=False):
    return FIXER.ItemResult(index=1, file_path=Path(path), display_path=Path(path), status=status,
                            metadata={"asin": asin} if asin is not None else None, asin_conflict=conflict)


class GlobalDuplicateTests(unittest.TestCase):
    def test_a_book_adding_an_asin_that_another_book_already_holds_is_flagged_and_names_the_owner(self):
        writer = result("/lib/B/new.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([writer], {"B0X": {"/lib/A/owner.m4b"}})
        self.assertTrue(writer.asin_conflict)
        self.assertEqual(writer.review_reasons, ["duplicate Audible ASIN B0X: already embedded on another book in the library (owner.m4b)"])

    def test_the_book_that_already_owns_the_asin_is_not_flagged_when_it_rewrites_it(self):
        owner = result("/lib/A/owner.m4b", "B0X")
        other = result("/lib/B/new.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([owner, other], {"B0X": {"/lib/A/owner.m4b"}})
        self.assertFalse(owner.asin_conflict)
        self.assertTrue(other.asin_conflict)

    def test_an_owner_being_rewritten_to_a_different_asin_no_longer_holds_it(self):
        owner = result("/lib/A/owner.m4b", "B0NEW")
        taker = result("/lib/B/new.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([owner, taker], {"B0X": {"/lib/A/owner.m4b"}, "B0NEW": set()})
        self.assertFalse(taker.asin_conflict)

    def test_several_books_in_one_run_claiming_a_new_asin_are_all_flagged(self):
        a, b = result("/lib/A/a.m4b", "B0X"), result("/lib/B/b.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([a, b], {})
        self.assertTrue(a.asin_conflict and b.asin_conflict)
        self.assertEqual(a.review_reasons, ["duplicate Audible ASIN B0X: matched to 2 different books in this run"])

    def test_one_book_alone_with_an_asin_is_fine(self):
        a = result("/lib/A/a.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([a], {"B0X": {"/lib/A/a.m4b"}})
        self.assertFalse(a.asin_conflict)

    def test_asins_are_compared_case_insensitively_and_trimmed(self):
        a, b = result("/lib/A/a.m4b", " b0x "), result("/lib/B/b.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([a, b], {})
        self.assertTrue(a.asin_conflict and b.asin_conflict)

    def test_unmatched_flagged_or_asinless_results_are_ignored(self):
        skipped = result("/lib/A/s.m4b", "B0X", status="skipped")
        flagged = result("/lib/B/f.m4b", "B0X", conflict=True)
        blank = result("/lib/C/c.m4b", "")
        none = result("/lib/D/d.m4b", None)
        fine = result("/lib/E/e.m4b", "B0X")
        FIXER.detect_global_asin_duplicates([skipped, flagged, blank, none, fine], {})
        self.assertFalse(fine.asin_conflict)
        self.assertFalse(skipped.asin_conflict or blank.asin_conflict)

    def test_the_reason_is_not_repeated_on_a_second_pass(self):
        writer = result("/lib/B/new.m4b", "B0X")
        disk = {"B0X": {"/lib/A/owner.m4b"}}
        FIXER.detect_global_asin_duplicates([writer], disk)
        writer.asin_conflict = False
        FIXER.detect_global_asin_duplicates([writer], disk)
        self.assertEqual(len(writer.review_reasons), 1)


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

    def test_the_filename_token_is_read_first_and_the_media_file_is_not_opened(self):
        a = self.book("Book [B0ABCDEFGH].m4b")
        with mock.patch.object(FIXER, "probe_file", side_effect=AssertionError("probed")):
            got = FIXER.build_disk_asin_map([a], workers=1)
        self.assertEqual(got, {"B0ABCDEFGH": {str(a)}})

    def test_a_sidecar_asin_is_used_next_and_the_placeholder_is_ignored(self):
        a, b = self.book("a.m4b"), self.book("b.m4b")
        a.with_name("a.m4b.libraforge.json").write_text(json.dumps({"marker": {"audible": {"asin": "b0side0001"}}}))
        b.with_name("b.m4b.libraforge.json").write_text(json.dumps({"marker": {"audible": {"asin": "NOREALASIN"}}}))
        with mock.patch.object(FIXER, "probe_file", return_value=({}, 1.0)):
            got = FIXER.build_disk_asin_map([a, b], workers=1)
        self.assertEqual(got, {"B0SIDE0001": {str(a)}})

    def test_the_embedded_tag_is_the_last_resort(self):
        a = self.book("a.m4b")
        with mock.patch.object(FIXER, "probe_file", return_value=({"asin": " b0tag00001 "}, 1.0)):
            self.assertEqual(FIXER.build_disk_asin_map([a], workers=1), {"B0TAG00001": {str(a)}})

    def test_books_sharing_an_asin_are_grouped_and_asinless_books_are_left_out(self):
        a, b, c = self.book("a [B0SAME0001].m4b"), self.book("b [B0SAME0001].m4b"), self.book("c.m4b")
        with mock.patch.object(FIXER, "probe_file", return_value=({}, 1.0)):
            got = FIXER.build_disk_asin_map([a, b, c], workers=1)
        self.assertEqual(got, {"B0SAME0001": {str(a), str(b)}})

    def test_unchanged_files_come_from_the_cache_and_changed_ones_are_probed_again(self):
        a = self.book("a.m4b")
        with mock.patch.object(FIXER, "probe_file", return_value=({"asin": "B0ONE00001"}, 1.0)) as probe:
            FIXER.build_disk_asin_map([a], workers=1)
            FIXER.build_disk_asin_map([a], workers=1)
            self.assertEqual(probe.call_count, 1)
            import os
            os.utime(a, (a.stat().st_atime, a.stat().st_mtime + 100))
            FIXER.build_disk_asin_map([a], workers=1)
            self.assertEqual(probe.call_count, 2)

    def test_the_cache_is_pruned_to_the_current_files(self):
        a, b = self.book("a.m4b"), self.book("b.m4b")
        with mock.patch.object(FIXER, "probe_file", return_value=({"asin": "B0ONE00001"}, 1.0)):
            FIXER.build_disk_asin_map([a, b], workers=1)
            FIXER.build_disk_asin_map([a], workers=1)
        cached = json.loads(FIXER.DISK_ASIN_CACHE_PATH.read_text())
        self.assertEqual(list(cached), [str(a)])
        self.assertEqual(set(cached[str(a)]), {"mtime", "asin"})

    def test_many_workers_give_the_same_map_as_one(self):
        files = [self.book(f"b{i} [B0WORK000{i}].m4b") for i in range(4)]
        self.assertEqual(FIXER.build_disk_asin_map(files, workers=4), FIXER.build_disk_asin_map(files, workers=1))

    def test_a_missing_or_corrupt_cache_file_is_an_empty_cache(self):
        self.assertEqual(FIXER._load_disk_asin_cache(), {})
        FIXER.DISK_ASIN_CACHE_PATH.parent.mkdir(parents=True)
        FIXER.DISK_ASIN_CACHE_PATH.write_text("{bad")
        self.assertEqual(FIXER._load_disk_asin_cache(), {})
        FIXER.DISK_ASIN_CACHE_PATH.write_text("[1]")
        self.assertEqual(FIXER._load_disk_asin_cache(), {})


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

    def test_the_format_is_taken_from_the_image_bytes_first(self):
        self.assertEqual(self.fetch(self.JPEG, "image/png"), (self.JPEG, "jpeg"))
        self.assertEqual(self.fetch(self.PNG, "image/jpeg"), (self.PNG, "png"))

    def test_the_content_type_decides_when_the_bytes_are_unrecognised(self):
        self.assertEqual(self.fetch(b"zzz", "image/JPEG")[1], "jpeg")
        self.assertEqual(self.fetch(b"zzz", "image/jpg")[1], "jpeg")
        self.assertEqual(self.fetch(b"zzz", "image/png")[1], "png")

    def test_unknown_image_data_is_rejected_with_the_content_type_in_the_message(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported cover image format from URL: text/html"):
            self.fetch(b"<html>", "text/html")

    def test_an_empty_url_and_unsupported_schemes_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "No cover URL"):
            FIXER.download_cover_bytes("")
        with self.assertRaisesRegex(RuntimeError, "http, https, or a LibraForge upload"):
            FIXER.download_cover_bytes("ftp://x/c.jpg")

    def test_an_oversized_image_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "too large"):
            self.fetch(self.JPEG + b"0" * (10 * 1024 * 1024))

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
