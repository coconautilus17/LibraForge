"""An applied book whose metadata lives in Audiobookshelf is finished (#546); a
dry run converts and deletes no old sidecar files (#547); each book's report
item is built on its search worker, not the main thread (#548)."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tests.fixer_run import library_listing, make_book, no_match, run_fixer
from app.tests.script_loader import load_script

FIXER = load_script("fixer_marker_skip_and_sidecar_reads", "audible-metadata-fixer-v5.py")

ASIN = "B0REAL1234"


def report_items(out: str) -> list[dict]:
    return [json.loads(line.split(": ", 1)[1]) for line in out.splitlines() if line.startswith("REPORT_ITEM_JSON: ")]


class AppliedBookInAudiobookshelfTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.folder = self.root / "Author" / "Lone Book"
        make_book(self.folder / "Lone Book.m4b", "Lone Book")
        # Applied earlier; its metadata.json was moved into Audiobookshelf.
        marker = {
            "applied": True, "score": 1.0, "edit_mode": "full", "source_file": "Lone Book.m4b",
            "audible": {"asin": ASIN, "title": "Lone Book", "author": "Some Author"},
            "written_fields": ["title", "author", "asin"],
        }
        (self.folder / "libraforge.json").write_text(json.dumps({"marker": marker}), encoding="utf-8")

    def dry_run(self, *abs_args: str, abs_items=()) -> str:
        with patch.object(FIXER, "fetch_all_abs_book_items", return_value=list(abs_items)):
            return run_fixer(FIXER, self.root, *abs_args)

    def test_it_is_skipped_as_already_processed(self):
        item = {"id": "li1", "path": str(self.folder), "media": {"metadata": {"asin": ASIN}}}
        out = self.dry_run("--abs-url", "http://abs", "--abs-api-key", "key", abs_items=[item])
        self.assertNotIn("RECOVER:", out)
        [report] = report_items(out)
        self.assertEqual((report["status"], report["skip_reason"]), ("skipped", "already processed"))

    def test_a_book_audiobookshelf_does_not_know_is_still_repaired(self):
        out = self.dry_run("--abs-url", "http://abs", "--abs-api-key", "key", abs_items=[])
        self.assertIn("RECOVER: re-applying stored match from marker", out)


class DryRunLeavesOldSidecarFilesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        folder = self.root / "Author" / "Shared"
        self.book = make_book(folder / "One.m4b", "One")
        make_book(folder / "Two.m4b", "Two")
        # Old-format files: a per-file marker and a backup, and a per-file
        # libraforge.json next to a leftover old marker.
        (folder / f"One.m4b{FIXER.MARKER_SUFFIX}").write_text(
            json.dumps({"applied": False, "source_file": "One.m4b"}), encoding="utf-8")
        (folder / f"One.m4b{FIXER.METADATA_BACKUP_SUFFIX}").write_text(
            json.dumps({"source_file": "One.m4b", "format_tags": {"title": "One"}}), encoding="utf-8")
        (folder / f"Two.m4b{FIXER.LIBRAFORGE_SUFFIX}").write_text(
            json.dumps({"marker": {"applied": False, "source_file": "Two.m4b"}}), encoding="utf-8")
        (folder / f"Two.m4b{FIXER.MARKER_SUFFIX}").write_text(
            json.dumps({"applied": False, "source_file": "Two.m4b"}), encoding="utf-8")

    def test_a_dry_run_leaves_them_as_they_are(self):
        before = library_listing(self.root)
        run_fixer(FIXER, self.root, search=no_match)
        self.assertEqual(library_listing(self.root), before)

    def test_reading_them_in_a_dry_run_still_sees_their_data(self):
        with patch.object(FIXER, "LIBRARY_WRITES", False):
            self.assertEqual(FIXER.load_marker(self.book)["source_file"], "One.m4b")

    def test_apply_still_converts_them(self):
        run_fixer(FIXER, self.root, "--apply", search=no_match)
        names = {p.name for p in (self.root / "Author" / "Shared").iterdir()}
        self.assertFalse({f"One.m4b{FIXER.MARKER_SUFFIX}", f"One.m4b{FIXER.METADATA_BACKUP_SUFFIX}",
                          f"Two.m4b{FIXER.MARKER_SUFFIX}"} & names)
        self.assertIn(f"One.m4b{FIXER.LIBRAFORGE_SUFFIX}", names)


class ReportItemOnTheSearchWorkerTests(unittest.TestCase):
    def test_the_main_thread_builds_no_report_item(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        make_book(root / "Author" / "Lone Book" / "Lone Book.m4b", "Lone Book")
        threads = []
        build = FIXER._build_report_item

        def recording(result):
            threads.append(threading.current_thread() is threading.main_thread())
            return build(result)

        def searched(fixer, index, file_path, total):
            result = no_match(fixer, index, file_path, total)
            result.clues = {"title": "Lone Book"}
            return result

        plan = root / "run.plan.jsonl"
        with patch.object(FIXER, "_build_report_item", side_effect=recording):
            out = run_fixer(FIXER, root, "--save-plan", str(plan), search=searched)
        self.assertEqual(threads, [False])
        self.assertEqual(len(report_items(out)), 1)
        # The plan still records the book's audio file as it was.
        [record] = [json.loads(line) for line in plan.read_text().splitlines()[1:]]
        book = root / "Author" / "Lone Book" / "Lone Book.m4b"
        self.assertEqual(record["files"], [[str(book), book.stat().st_size, book.stat().st_mtime_ns]])


if __name__ == "__main__":
    unittest.main()
