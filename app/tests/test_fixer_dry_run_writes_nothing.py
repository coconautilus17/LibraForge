"""A dry run writes nothing into the library: no skip markers, no original-tag
backups, no chapter-count caches. Apply still records what it found."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.tests.fixer_run import library_listing, make_book, no_match, run_fixer
from app.tests.script_loader import load_script

FIXER = load_script("fixer_dry_run_writes_nothing", "audible-metadata-fixer-v5.py")


class DryRunWritesNothingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        make_book(self.root / "Author" / "Lone Book" / "Lone Book.m4b", "Lone Book")
        make_book(self.root / "Author" / "Two Parts" / "Part 1.m4b", "Two Parts 1")
        make_book(self.root / "Author" / "Two Parts" / "Part 2.m4b", "Two Parts 2")

    def test_a_dry_run_with_backup_on_leaves_the_library_as_it_was(self):
        before = library_listing(self.root)
        run_fixer(FIXER, self.root, "--backup", search=no_match)
        self.assertEqual(library_listing(self.root), before)

    def test_apply_still_records_the_books_it_could_not_match(self):
        run_fixer(FIXER, self.root, "--apply", search=no_match)
        sidecar = self.root / "Author" / "Lone Book" / "libraforge.json"
        self.assertEqual(json.loads(sidecar.read_text())["marker"]["applied"], False)


if __name__ == "__main__":
    unittest.main()
