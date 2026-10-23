"""Regression tests for the defects the test audit found (issues #373 to #379)."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app import chaptering as c
from app.fixer import scoring as s

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_script("known_defects_fixer", "audible-metadata-fixer-v5.py")
ORG = load_script("known_defects_organizer", "organize-audiobooks-by-metadata-v3_13.py")


def product(**over):
    base = {"title": "The Lost Bloodline 5", "series": [{"title": "The Lost Bloodline", "sequence": "5"}]}
    base.update(over)
    return base


class ChapterForgeRegressions(unittest.TestCase):
    def test_an_end_of_chapter_announcement_should_not_become_a_marker(self):
        # Issue #378: END_OF_RE is searched in the 16 characters BEFORE the marker, which
        # never contain the marker word itself ("chapter"), so it cannot fire.
        got = c.find_marker_candidates([c.TranscriptSegment(start=0, end=3, text="End of chapter 5. Chapter 6 The Road")])
        self.assertEqual([x.number for x in got], [6])


class FixerRegressions(unittest.TestCase):
    def test_a_failing_restore_should_be_counted_and_the_loop_should_continue(self):
        # Issue #379: the except branch uses an undefined name `manual_review`, so the
        # first failure raises NameError and ends the whole restore run.
        with tempfile.TemporaryDirectory() as tmp:
            ok, broken = Path(tmp) / "ok.m4b", Path(tmp) / "bad.m4b"
            for path in (ok, broken):
                path.write_bytes(b"x")
                path.with_name(path.name + ".libraforge.json").write_text(
                    '{"schema_version": 2, "backup": {"format_tags": {"title": "T"}, "created_at": "t"},'
                    ' "marker": {"applied": true, "manually_applied": true}}')

            def fake_restore(source, writer="auto"):
                if source == broken:
                    raise RuntimeError("boom")
                return source

            with mock.patch.object(FIXER, "restore_metadata_from_backup", side_effect=fake_restore), mock.patch("builtins.print"):
                self.assertEqual(FIXER.restore_metadata_backups([broken, ok]), (1, 0, 1))

    def test_hyphen_and_ampersand_ranges_in_the_title_should_mark_an_omnibus(self):
        # Issue #373: is_omnibus_product runs its range regex on normalize_for_match()
        # output, which has already turned "1-3" into "1 3" and dropped "&", so only
        # "to"/"through" ranges are recognised.
        for title, subtitle in (("Cradle Book 1 & 2", ""), ("Cradle Books 1-3 Collection", ""), ("Cradle", "Books 5-7")):
            with self.subTest(title=title, subtitle=subtitle):
                self.assertIs(s.is_omnibus_product(product(title=title, subtitle=subtitle, series=[])), True)

    def test_series_plus_book_n_should_be_generic_too(self):
        # Issue #374: the docstring example "All the Skills - Book 003" never matches,
        # because normalize_for_match() strips "Book N" from the title before the
        # "<series> book N" pattern runs. Only the "<series> N" pattern can ever fire.
        clues = {"title": "All the Skills - Book 003", "series": "All the Skills", "book_number": "3"}
        self.assertIs(s.is_generic_series_number_title(clues), True)


class FolderForgeRegressions(unittest.TestCase):
    def test_a_whole_number_written_with_a_zero_decimal_should_not_keep_a_dangling_dot(self):
        # Issue #375: "1.0" becomes "001." because ".0".rstrip("0") is "." (truthy),
        # so the `or ".0"` fallback never applies.
        self.assertFalse(ORG.normalize_book_number("1.0").endswith("."))

    def test_a_co_author_prefix_should_be_removed_as_the_docstring_promises(self):
        # Issue #376: the docstring lists "Dan Raxor, Jace Cannon - Supers of Vault 12"
        # as handled, but the leading segment is compared with each author separately,
        # so a two-author prefix (ratio ~0.44 against either) never matches.
        self.assertEqual(
            ORG.strip_author_narrator_noise_from_title("Dan Raxor, Jace Cannon - Supers of Vault 12", "Dan Raxor, Jace Cannon", "", False),
            "Supers of Vault 12")

    def test_a_series_first_folder_should_not_invent_an_author_and_a_series_called_book(self):
        # Issue #377: "Destiny Cycle - Book 004 - Threads of Destiny Vol 1" is the very
        # example finish() documents as series-first, but parse_explicit_identity_folder_name
        # reads the first segment as an AUTHOR and "Book" as the SERIES, so the real series is lost.
        got = ORG.parse_explicit_identity_folder_name("Destiny Cycle - Book 004 - Threads of Destiny Vol 1")
        self.assertNotEqual(got.get("series"), "Book")
        self.assertNotEqual(got.get("author"), "Destiny Cycle")


if __name__ == "__main__":
    unittest.main()
