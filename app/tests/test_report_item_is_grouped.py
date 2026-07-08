"""_build_report_item must expose is_grouped so the match report can badge
and filter multi-file/grouped books -- same source of truth already used by
discover_manual_review_targets and inspect_manual_review_target
(app/main.py), just missing from the report item dict. See
docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub

import importlib.util


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_report_item_is_grouped", "scripts/audible-metadata-fixer-v5.py")


class ReportItemIsGroupedTests(unittest.TestCase):
    def _result(self, group_search_applied: bool) -> "FIXER.ItemResult":
        result = FIXER.ItemResult(
            index=1,
            file_path=Path("/lib/Book/book.m4b"),
            display_path="/lib/Book",
            log_lines=[],
        )
        result.status = "matched"
        result.clues = {"group_search": {"applied": group_search_applied}}
        result.metadata = {"title": "Book", "author": "Author"}
        return result

    def test_grouped_book_reports_is_grouped_true(self):
        item = FIXER._build_report_item(self._result(True))
        self.assertTrue(item["is_grouped"])

    def test_single_file_book_reports_is_grouped_false(self):
        item = FIXER._build_report_item(self._result(False))
        self.assertFalse(item["is_grouped"])

    def test_missing_group_search_defaults_to_false(self):
        result = self._result(False)
        result.clues = {}
        item = FIXER._build_report_item(result)
        self.assertFalse(item["is_grouped"])


class ReportItemIsGroupedCleanSkipTests(unittest.TestCase):
    """marker_skip_is_clean's fast path returns before build_search_context
    ever runs, so result.clues stays None -- _build_report_item must fall
    back to the marker's own output_kind ("json_sidecar" == grouped, the
    same signal should_write_json_sidecar uses) to recover is_grouped for
    these steady-state, cleanly-skipped books.
    """

    def _write_marker(self, folder: Path, output_kind: str) -> Path:
        audio = folder / "Book.m4b"
        audio.write_bytes(b"")
        marker_path = folder / "libraforge.json"
        marker_path.write_text(json.dumps({
            "marker": {
                "output_kind": output_kind,
                "audible": {
                    "chosen_title": "Book",
                    "author": "Jane Doe",
                },
            },
        }), encoding="utf-8")
        return audio

    def _clean_skip_result(self, audio: Path) -> "FIXER.ItemResult":
        result = FIXER.ItemResult(
            index=1,
            file_path=audio,
            display_path=audio.parent,
            log_lines=[],
        )
        result.status = "skipped"
        result.skip_reason = "clean"
        result.clues = None
        return result

    def test_clean_skip_of_grouped_book_reports_is_grouped_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = self._write_marker(Path(temp_dir), "json_sidecar")
            item = FIXER._build_report_item(self._clean_skip_result(audio))

        self.assertTrue(item["is_grouped"])

    def test_clean_skip_of_single_file_book_reports_is_grouped_false(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = self._write_marker(Path(temp_dir), "tags")
            item = FIXER._build_report_item(self._clean_skip_result(audio))

        self.assertFalse(item["is_grouped"])


if __name__ == "__main__":
    unittest.main()
