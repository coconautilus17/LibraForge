"""_build_report_item must prefer the stored marker match over a fresh raw-tag
probe when a book was manually applied, even if a fresh search also ran this
session (clues populated). Manual Review already wrote this book's tags to
match its marker exactly, so the marker is the reliable source -- a fresh
raw-tag reread is redundant at best and, for a grouped multi-file book,
actively wrong (the representative file's own tags describe one
chapter/track, not the book). Reported: the report's "local"/current field
showed a bonus track's chapter label ("Opening Credits") and its track
number ("1") for manually-applied grouped books, while Manual Review (which
reads the marker directly) correctly showed the book's real title/sequence.
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


FIXER = load_module("fixer_v5_report_item_manually_applied_local", "scripts/audible-metadata-fixer-v5.py")


class ManuallyAppliedLocalTests(unittest.TestCase):
    def _write_marker(self, folder: Path) -> Path:
        audio = folder / "001 Eric Vall - Pocket Dungeon 3 - Opening Credits.mp3"
        audio.write_bytes(b"")
        marker_path = folder / "libraforge.json"
        marker_path.write_text(json.dumps({
            "marker": {
                "output_kind": "json_sidecar",
                "manually_applied": True,
                "audible": {
                    "chosen_title": "Pocket Dungeon 3",
                    "author": "Eric Vall",
                    "sequence": "3",
                },
            },
        }), encoding="utf-8")
        return audio

    def _result_with_fresh_probe(self, audio: Path) -> "FIXER.ItemResult":
        # Simulates a fresh search this session (clues populated with a
        # bonus intro track's own tags as the group's representative file).
        result = FIXER.ItemResult(
            index=1,
            file_path=audio,
            display_path=str(audio.parent),
            log_lines=[],
        )
        result.status = "matched"
        result.was_manually_applied = True
        result.clues = {
            "group_search": {"applied": True},
            "current": {
                "title": "Opening Credits",
                "author": "Eric Vall",
                "sequence": "1",
            },
        }
        result.metadata = {"title": "Opening Credits", "author": "Eric Vall", "sequence": "1"}
        return result

    def test_manually_applied_grouped_book_local_uses_marker_not_raw_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = self._write_marker(Path(temp_dir))
            item = FIXER._build_report_item(self._result_with_fresh_probe(audio))

        self.assertEqual(item["local"]["title"], "Pocket Dungeon 3")
        self.assertEqual(item["local"]["sequence"], "3")

    def _write_single_file_marker(self, folder: Path) -> Path:
        # Single, non-grouped book: no bonus track involved at all -- proves
        # the was_manually_applied fix is not a grouped-book-only patch. A
        # stale tag reread here would be a plain "edited outside LibraForge
        # since" case, not a chapter/book conflation like the grouped one.
        audio = folder / "Solo Book.m4b"
        audio.write_bytes(b"")
        marker_path = folder / "libraforge.json"
        marker_path.write_text(json.dumps({
            "marker": {
                "output_kind": "tags",
                "manually_applied": True,
                "audible": {
                    "chosen_title": "Solo Book",
                    "author": "Jane Doe",
                    "sequence": "",
                },
            },
        }), encoding="utf-8")
        return audio

    def test_manually_applied_single_file_book_local_uses_marker_not_raw_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = self._write_single_file_marker(Path(temp_dir))
            result = FIXER.ItemResult(
                index=1,
                file_path=audio,
                display_path=str(audio.parent),
                log_lines=[],
            )
            result.status = "matched"
            result.was_manually_applied = True
            # No group_search here -- an ungrouped single file's own probe.
            result.clues = {
                "current": {
                    "title": "Stale Title From Before The Edit",
                    "author": "Jane Doe",
                    "sequence": "1",
                },
            }
            result.metadata = {"title": "Stale Title From Before The Edit", "author": "Jane Doe"}
            item = FIXER._build_report_item(result)

        self.assertEqual(item["local"]["title"], "Solo Book")
        self.assertFalse(item["is_grouped"])

    def test_non_manually_applied_book_still_uses_fresh_current_regardless_of_grouping(self):
        # The normal automated-match path (was_manually_applied stays False)
        # must keep showing the fresh raw-tag probe -- confirms the fix only
        # changes behavior for the manually-applied case, for either type.
        result = FIXER.ItemResult(
            index=1,
            file_path=Path("/lib/Solo Book/book.m4b"),
            display_path="/lib/Solo Book",
            log_lines=[],
        )
        result.status = "matched"
        result.clues = {"current": {"title": "Fresh Probe Title", "sequence": "1"}}
        result.metadata = {"title": "Fresh Probe Title", "sequence": "1"}
        item = FIXER._build_report_item(result)

        self.assertEqual(item["local"]["title"], "Fresh Probe Title")


if __name__ == "__main__":
    unittest.main()
