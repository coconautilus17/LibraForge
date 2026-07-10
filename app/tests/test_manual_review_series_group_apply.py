"""POST /api/manual-review/apply-series-group -- bulk field edit across
several books at once (the Fix Series feature). Loops _write_book_metadata
per included book with write_policy="fill" (blank shared field = untouched
on every book; filled = overwritten on every book, even one that already
had a value) -- see docs/design/2026-07-09-fix-series-cross-book-editor-design.md.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class SeriesGroupApplyTests(unittest.TestCase):
    def _context_for(self, path):
        return {
            "source_path": path,
            "display_path": path,
            "is_grouped": False,
            "group_search": {},
            "metadata": {"title": "Old Title", "author": "Old Author", "series": ""},
        }

    def _fixer(self, written: dict):
        return SimpleNamespace(
            FILL_FIELDS=("title", "author", "series", "sequence", "narrator", "year", "asin", "genre", "subtitle"),
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: bool((clues.get("group_search") or {}).get("applied")),
            is_mutagen_mp4_candidate=lambda source: True,
            is_mutagen_mp3_candidate=lambda source: False,
            write_audiobookshelf_metadata_json=lambda source, metadata, clues, alone, fill_missing=False, skip_blank_fields=False: Path(
                str(source) + ".metadata.json"
            ),
            write_tags=lambda source, metadata, **kwargs: written.setdefault("tags", []).append(
                (str(source), dict(metadata), kwargs.get("field_policy"))
            ),
            write_m4b_tool_metadata_sidecar=lambda source, metadata, clues, score, field_policy="legacy": Path(
                str(source) + ".libraforge.json"
            ),
            write_original_metadata_backup=lambda *a, **k: Path("/library/backup.json"),
            write_marker=lambda **kwargs: None,
        )

    def test_only_filled_shared_fields_are_sent_per_book_with_fill_policy(self):
        written: dict = {}
        req = main.SeriesGroupApplyRequest(
            script_name="audible-metadata-fixer-v5.py",
            series="Dungeon Core",
            author="",
            genre="",
            narrator="",
            explicit=False,
            explicit_set=False,
            language="",
            books=[
                main.SeriesGroupBookEntry(path="/lib/A2.m4b", sequence="2"),
                main.SeriesGroupBookEntry(path="/lib/A3.m4b", sequence="3"),
            ],
        )
        with (
            patch.object(main, "inspect_manual_review_target", side_effect=lambda **kw: self._context_for(kw["path"])),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.apply_series_group(req)

        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(all(r["status"] == "applied" for r in result["results"]))
        for path, metadata, field_policy in written["tags"]:
            self.assertEqual(field_policy, "fill")
            self.assertEqual(metadata["series"], "Dungeon Core")
            # Author/genre/narrator were left blank in the request -- must
            # not appear as forced-blank overwrites; "fill" already leaves
            # them untouched when absent/blank, so it's enough that they're
            # blank here (not asserting they're missing from the dict).
            self.assertEqual(metadata.get("author", ""), "")

    def test_per_book_sequence_is_applied(self):
        written: dict = {}
        req = main.SeriesGroupApplyRequest(
            script_name="audible-metadata-fixer-v5.py",
            series="Dungeon Core", author="", genre="", narrator="",
            explicit=False, explicit_set=False, language="",
            books=[
                main.SeriesGroupBookEntry(path="/lib/A2.m4b", sequence="2"),
                main.SeriesGroupBookEntry(path="/lib/A3.m4b", sequence="3"),
            ],
        )
        with (
            patch.object(main, "inspect_manual_review_target", side_effect=lambda **kw: self._context_for(kw["path"])),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_series_group(req)

        by_path = {path: metadata for path, metadata, _ in written["tags"]}
        self.assertEqual(by_path["/lib/A2.m4b"]["sequence"], "2")
        self.assertEqual(by_path["/lib/A3.m4b"]["sequence"], "3")

    def test_explicit_only_written_when_explicit_set_is_true(self):
        written: dict = {}
        req = main.SeriesGroupApplyRequest(
            script_name="audible-metadata-fixer-v5.py",
            series="", author="", genre="", narrator="",
            explicit=True, explicit_set=True, language="",
            books=[main.SeriesGroupBookEntry(path="/lib/A2.m4b", sequence="")],
        )
        with (
            patch.object(main, "inspect_manual_review_target", side_effect=lambda **kw: self._context_for(kw["path"])),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_series_group(req)
        _, metadata, _ = written["tags"][0]
        self.assertTrue(metadata["explicit"])

    def test_one_book_failing_does_not_stop_the_others(self):
        written: dict = {}

        def flaky_context(**kw):
            if kw["path"] == "/lib/Bad.m4b":
                raise Exception("boom")
            return self._context_for(kw["path"])

        req = main.SeriesGroupApplyRequest(
            script_name="audible-metadata-fixer-v5.py",
            series="Dungeon Core", author="", genre="", narrator="",
            explicit=False, explicit_set=False, language="",
            books=[
                main.SeriesGroupBookEntry(path="/lib/Bad.m4b", sequence="1"),
                main.SeriesGroupBookEntry(path="/lib/A2.m4b", sequence="2"),
            ],
        )
        with (
            patch.object(main, "inspect_manual_review_target", side_effect=flaky_context),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.apply_series_group(req)

        by_path = {r["path"]: r for r in result["results"]}
        self.assertEqual(by_path["/lib/Bad.m4b"]["status"], "failed")
        self.assertIn("boom", by_path["/lib/Bad.m4b"]["error"])
        self.assertEqual(by_path["/lib/A2.m4b"]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
