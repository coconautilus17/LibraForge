"""Apply writes the matches the last dry run chose, without searching again,
for every book whose files are unchanged; it searches any other book, and the
checks before a search (applied or manually applied markers) still come first."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mutagen.mp4 import MP4

from app.tests.fixer_run import make_book, run_fixer
from app.tests.script_loader import load_script

FIXER = load_script("fixer_apply_from_dry_run", "audible-metadata-fixer-v5.py")


class Catalog:
    """Audible's catalog, knowing one listing per book (its title, by Some Author,
    read by Some Narrator); records which titles were searched for."""

    def __init__(self):
        self.searched: set[str] = set()

    def __call__(self, query, title, author):
        title = title or query.split(" - ")[0]
        self.searched.add(title)
        return [{
            "asin": f"B0{sum(map(ord, title)):08d}", "title": title, "authors": [{"name": "Some Author"}],
            "narrators": [{"name": "Some Narrator"}], "runtime_length_min": 1, "release_date": "2020-01-01",
            "publisher_name": "Some Publisher", "language": "english",
        }]


def tags(path: Path) -> dict:
    return {k: [str(v) for v in vals] for k, vals in (MP4(str(path)).tags or {}).items()}


class ApplyFromDryRunTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.reports = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.reports, ignore_errors=True)
        self.one = make_book(self.root / "Author" / "One" / "One.m4b", "One", seconds=60)
        self.two = make_book(self.root / "Author" / "Two" / "Two.m4b", "Two", seconds=60)
        self.plan = self.reports / "20990101-000000.plan.jsonl"

    def dry_run(self, *flags):
        catalog = Catalog()
        run_fixer(FIXER, self.root, "--save-plan", str(self.plan), *flags, catalog=catalog)
        self.assertEqual(catalog.searched, {"One", "Two"})

    def apply(self, *flags) -> Catalog:
        catalog = Catalog()
        self.output = run_fixer(FIXER, self.root, "--apply", "--from-plan", str(self.plan), *flags, catalog=catalog)
        return catalog

    def test_apply_writes_the_dry_run_matches_without_searching(self):
        self.dry_run()
        self.assertEqual(self.apply().searched, set())
        self.assertEqual(tags(self.one)["\xa9wrt"], ["Some Narrator"])
        self.assertIn("FROM DRY RUN 20990101-000000", self.output)

    def test_the_result_is_the_same_as_searching_again(self):
        fresh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fresh, ignore_errors=True)
        shutil.copytree(self.root, fresh, dirs_exist_ok=True)
        self.dry_run()
        self.apply()
        run_fixer(FIXER, fresh, "--apply", catalog=Catalog())
        for book in ("One/One.m4b", "Two/Two.m4b"):
            self.assertEqual(tags(self.root / "Author" / book), tags(fresh / "Author" / book))

    def test_a_book_the_dry_run_did_not_cover_is_searched(self):
        self.dry_run()
        make_book(self.root / "Author" / "Three" / "Three.m4b", "Three", seconds=60)
        self.assertEqual(self.apply().searched, {"Three"})

    def test_a_book_whose_file_changed_since_the_dry_run_is_searched(self):
        self.dry_run()
        make_book(self.two, "Two", seconds=61)
        self.assertEqual(self.apply().searched, {"Two"})

    def test_a_book_applied_by_hand_after_the_dry_run_is_left_alone(self):
        self.dry_run()
        # A Manual Review apply that pushed metadata only: the audio file is unchanged.
        picked = {"asin": "B0HANDPICK", "title": "One", "author": "Some Author", "narrator": "Hand Picked",
                  "edit_mode": "full"}
        FIXER.write_marker(self.one, picked, {"current": {"title": "One"}}, 1.0, "manual_full", False,
                           output_kind="metadata_json", alone=True, written_fields=["asin", "title", "narrator"])
        (self.one.parent / "metadata.json").write_text("{}", encoding="utf-8")
        before = tags(self.one)
        self.assertEqual(self.apply().searched, set())
        self.assertEqual(tags(self.one), before)
        self.assertIn("already manually applied", self.output)

    def test_a_dry_run_with_other_matching_settings_is_not_used(self):
        self.dry_run("--min-score", "0.9")
        self.assertEqual(self.apply().searched, {"One", "Two"})
        self.assertIn("used other matching settings (min_score)", self.output)

    def test_write_settings_may_differ_from_the_dry_run(self):
        self.dry_run()
        self.assertEqual(self.apply("--write-mode", "overwrite", "--write-workers", "2").searched, set())

    def test_the_dry_run_writes_nothing_into_the_library_but_the_plan_lands_in_reports(self):
        self.dry_run()
        header = json.loads(self.plan.read_text().splitlines()[0])
        self.assertEqual(header["root"], str(self.root.resolve()))
        self.assertEqual(len(self.plan.read_text().splitlines()), 3)
        self.assertFalse(list(self.root.rglob("*.json*")))


if __name__ == "__main__":
    unittest.main()
