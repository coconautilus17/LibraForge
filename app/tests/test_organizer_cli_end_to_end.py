"""Folder Forge run end to end through its command line (dry run and apply) on a
temporary library: what it reports, what it moves and what it refuses to touch."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_cli_e2e", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.lib = self.base / "lib"
        self.un = self.lib / "_unorganized"
        self.un.mkdir(parents=True)

    def sidecar_book(self, name="Will Wight - Unsouled.m4b", title="Unsouled", author="Will Wight", series="Cradle", sequence="1"):
        audio = self.un / name
        audio.write_bytes(b"audio")
        audio.with_name(audio.name + ".libraforge.json").write_text(json.dumps(
            {"sidecar": {"book": {"title": title, "author": author, "series": series, "sequence": sequence}}}))
        return audio

    def run_cli(self, *args, root=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["organizer", str(root or self.un), "--destination-root", str(self.lib), "--structure-cache", str(self.base / "cache.json"),
                "--progress-every", "0", *args]
        old = sys.argv
        sys.argv = argv
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    ORG.main()
                except SystemExit as exit_:
                    code = exit_.code
        finally:
            sys.argv = old
        return out.getvalue(), err.getvalue(), code


class DryRunTests(CliFixture):
    def test_a_dry_run_reports_the_plan_and_moves_nothing(self):
        audio = self.sidecar_book()
        out, _, _ = self.run_cli()
        self.assertIn("Mode: DRY RUN", out)
        self.assertIn("Planned moves: 1", out)
        self.assertIn("Dry-run only. Re-run with --apply to move files.", out)
        self.assertIn(str(audio), out)
        self.assertIn(str(self.lib / "Will Wight" / "Cradle" / "Book 1 - Unsouled" / "Will Wight - Unsouled.m4b"), out)
        self.assertTrue(audio.exists())

    def test_the_book_block_names_title_author_series_number_and_the_metadata_source(self):
        self.sidecar_book()
        out, _, _ = self.run_cli()
        for line in ("Kind:   loose_file", "Title:  Unsouled", "Author: Will Wight", "Series: Cradle", "Number: Book 1"):
            self.assertIn(line, out)
        self.assertIn("Metadata Source: sidecar:Will Wight - Unsouled.m4b.libraforge.json", out)

    def test_without_any_sidecar_the_run_stops_and_says_so(self):
        (self.un / "Loose.m4b").write_bytes(b"x")
        out, _, _ = self.run_cli()
        self.assertIn("NO_SIDECARS_FOUND", out)
        self.assertNotIn("Planned moves", out)

    def test_acknowledging_the_missing_sidecars_lets_the_run_continue(self):
        (self.un / "Will Wight - Unsouled.m4b").write_bytes(b"x")
        out, _, _ = self.run_cli("--acknowledge-no-sidecars")
        self.assertIn("Planned moves: 1", out)

    def test_an_unknown_author_is_skipped_unless_allowed(self):
        self.sidecar_book("Mystery.m4b", title="Mystery", author="", series="", sequence="")
        out, err, _ = self.run_cli()
        self.assertIn("Skipped unknown author: 1", out)
        self.assertIn("Planned moves: 0", out)
        self.assertIn("SKIP: unknown author", err)

    def test_a_skip_pattern_excludes_matching_books_and_is_counted(self):
        self.sidecar_book()
        out, err, _ = self.run_cli("--skip-pattern", "cradle")
        self.assertIn("Skipped by pattern: 1", out)
        self.assertIn("Planned moves: 0", out)
        self.assertIn("SKIP: matched skip pattern: cradle", err)

    def test_the_m4b_only_filter_drops_other_formats(self):
        self.sidecar_book("Book.mp3")
        out, _, _ = self.run_cli("--m4b-only")
        self.assertIn("Found book items: 0", out)
        self.assertIn("Planned moves: 0", out)
        self.assertIn("No moves needed.", out)

    def test_without_the_filter_the_same_mp3_book_is_planned(self):
        self.sidecar_book("Book.mp3")
        out, _, _ = self.run_cli()
        self.assertIn("Found book items: 1", out)
        self.assertIn("Planned moves: 1", out)

    def test_max_items_limits_the_scan(self):
        self.sidecar_book("A - One.m4b", title="One")
        self.sidecar_book("B - Two.m4b", title="Two", author="Bob Roe", series="", sequence="")
        out, _, _ = self.run_cli("--max-items", "1")
        self.assertIn("Found book items: 1", out)

    def test_index_only_builds_the_cache_and_plans_nothing(self):
        out, _, _ = self.run_cli("--index-only")
        self.assertIn("Mode: INDEX ONLY", out)
        self.assertIn("Structure cache entries: 0", out)
        self.assertTrue((self.base / "cache.json").exists())
        self.assertNotIn("Planned moves", out)


class ArgumentValidationTests(CliFixture):
    def test_a_missing_root_is_an_error(self):
        _, _, code = self.run_cli(root=self.base / "nope")
        self.assertIn("root does not exist", str(code))

    def test_a_missing_destination_is_an_error(self):
        out, err, code = self.run_cli("--destination-root", str(self.base / "nowhere"))
        self.assertIn("destination root does not exist", str(code))

    def test_a_destination_inside_the_scan_root_is_refused(self):
        inner = self.un / "inner"
        inner.mkdir()
        _, _, code = self.run_cli("--destination-root", str(inner))
        self.assertIn("destination root cannot be inside the scan root", str(code))

    def test_an_invalid_naming_template_is_rejected(self):
        _, err, code = self.run_cli("--naming-template", "")
        self.assertEqual(code, 2)
        self.assertIn("Invalid --naming-template", err)

    def test_the_default_scheme_flag_skips_template_validation(self):
        self.sidecar_book()
        out, _, code = self.run_cli("--naming-template", "", "--use-default-scheme")
        self.assertIsNone(code)
        self.assertIn("Planned moves: 1", out)


class ApplyTests(CliFixture):
    def test_apply_moves_the_file_into_author_series_book_and_its_sidecar_becomes_the_folders(self):
        audio = self.sidecar_book()
        out, _, _ = self.run_cli("--apply")
        target = self.lib / "Will Wight" / "Cradle" / "Book 1 - Unsouled"
        self.assertTrue((target / "Will Wight - Unsouled.m4b").exists())
        self.assertTrue((target / "libraforge.json").exists())
        self.assertFalse(audio.exists())
        self.assertFalse((self.un / "Will Wight - Unsouled.m4b.libraforge.json").exists())
        self.assertNotIn("Dry-run only", out)

    def test_apply_does_not_overwrite_a_book_already_in_the_target_folder(self):
        target = self.lib / "Will Wight" / "Cradle" / "Book 1 - Unsouled"
        target.mkdir(parents=True)
        (target / "existing.m4b").write_bytes(b"old")
        audio = self.sidecar_book()
        self.run_cli("--apply")
        self.assertTrue(audio.exists())
        self.assertEqual((target / "existing.m4b").read_bytes(), b"old")

    def test_apply_can_remove_the_emptied_source_folders(self):
        sub = self.un / "sub"
        sub.mkdir()
        audio = sub / "Will Wight - Unsouled.m4b"
        audio.write_bytes(b"audio")
        audio.with_name(audio.name + ".libraforge.json").write_text(json.dumps({"sidecar": {"book": {"title": "Unsouled", "author": "Will Wight"}}}))
        self.run_cli("--apply", "--remove-empty-dirs")
        self.assertFalse(sub.exists())
        self.assertTrue(self.un.exists())


if __name__ == "__main__":
    unittest.main()
