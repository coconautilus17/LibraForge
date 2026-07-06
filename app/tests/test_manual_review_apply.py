import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class SidecarBookGenreTests(unittest.TestCase):
    """_read_sidecar_book's single-file fallback (marker.audible, used when
    there's no sidecar.book) used to hardcode genre to "" regardless of what
    was actually embedded in the file -- Manual Review would show a blank
    "Current" genre for a previously-processed single-file book even though
    its real genre was written correctly."""

    def test_single_file_marker_surfaces_real_genre(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            audio = folder / "Book.m4b"
            audio.write_bytes(b"")
            # _read_sidecar_book always reads the flat "libraforge.json" in the
            # parent folder -- a file alone in its own dedicated folder (not
            # sharing it with siblings) gets its marker written there directly.
            marker_path = folder / "libraforge.json"
            marker_path.write_text(json.dumps({
                "marker": {
                    "audible": {
                        "chosen_title": "Book",
                        "author": "Jane Doe",
                        "genre": "Fantasy",
                    },
                },
            }), encoding="utf-8")

            result = main._read_sidecar_book(audio)

        self.assertEqual(result["genre"], "Fantasy")

    def test_single_file_marker_surfaces_real_subtitle_summary_isbn(self):
        # Same hardcoded-blank bug as genre had, for three more fields that
        # write_marker now persists into marker.audible.
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            audio = folder / "Book.m4b"
            audio.write_bytes(b"")
            marker_path = folder / "libraforge.json"
            marker_path.write_text(json.dumps({
                "marker": {
                    "audible": {
                        "chosen_title": "Book",
                        "author": "Jane Doe",
                        "subtitle": "A Subtitle",
                        "summary": "A summary.",
                        "isbn": "9781234567890",
                    },
                },
            }), encoding="utf-8")

            result = main._read_sidecar_book(audio)

        self.assertEqual(result["subtitle"], "A Subtitle")
        self.assertEqual(result["summary"], "A summary.")
        self.assertEqual(result["isbn"], "9781234567890")


class PickGenreTests(unittest.TestCase):
    """_pick_genre used to return only the first non-generic genre, silently
    dropping the rest of a provider's multi-genre response."""

    def test_keeps_every_non_generic_genre(self):
        self.assertEqual(
            main._pick_genre(["Fantasy", "Romance", "Mystery"]),
            "Fantasy, Romance, Mystery",
        )

    def test_drops_only_the_blocklisted_generic_label(self):
        self.assertEqual(
            main._pick_genre(["Audiobook", "Fantasy", "Romance"]),
            "Fantasy, Romance",
        )

    def test_deduplicates_case_insensitively(self):
        self.assertEqual(main._pick_genre(["Fantasy", "fantasy", "Romance"]), "Fantasy, Romance")

    def test_all_generic_returns_empty(self):
        self.assertEqual(main._pick_genre(["Audiobook", "Audiobooks"]), "")


class ManualReviewApplyTests(unittest.TestCase):
    def test_grouped_manual_apply_writes_sidecar_with_existing_group(self):
        chapter_files = [
            "/library/Book/Part 01.m4a",
            "/library/Book/Part 02.mp3",
        ]
        group_search = {
            "applied": True,
            "folder": "/library/Book",
            "file_count": 2,
            "files": chapter_files,
        }
        context = {
            "source_path": chapter_files[0],
            "display_path": "/library/Book",
            "is_grouped": True,
            "group_search": group_search,
            "metadata": {
                "title": "Existing Title",
                "author": "Existing Author",
                "series": "Existing Series",
                "sequence": "2",
            },
        }
        written = {}

        def write_sidecar(source, metadata, clues, score):
            written["source"] = source
            written["metadata"] = metadata
            written["clues"] = clues
            written["score"] = score
            return Path("/library/Book/Book.m4b-tool-metadata.json")

        def write_meta_json(source, metadata, clues, alone, fill_missing=False):
            written["meta_json_alone"] = alone
            return Path("/library/Book/metadata.json")

        def write_marker(**kwargs):
            written["marker_alone"] = kwargs.get("alone")

        fixer = SimpleNamespace(
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: bool(
                clues.get("group_search", {}).get("applied")
            ),
            write_m4b_tool_metadata_sidecar=write_sidecar,
            write_audiobookshelf_metadata_json=write_meta_json,
            write_original_metadata_backup=lambda *a, **k: Path("/library/Book/libraforge.json"),
            write_tags=lambda *args, **kwargs: self.fail("grouped apply wrote tags"),
            write_marker=write_marker,
        )
        selected_result = {
            "score": 1.0,
            "title": "Matched Title",
            "sequence": "2",
            "year": "2024",
            "duration_minutes": 600,
            "allowed_edit_modes": ["full"],
            "chosen_metadata_by_mode": {
                "full": {
                    "asin": "B012345678",
                    "title": "Matched Title",
                    "author": "Matched Author",
                    "series": "Matched Series",
                    "sequence": "2",
                }
            },
        }
        request = main.ManualReviewApplyRequest(
            path="/library/Book",
            selected_result=selected_result,
            edit_mode="full",
        )

        with (
            patch.object(main, "inspect_manual_review_target", return_value=context),
            patch.object(main, "load_fixer_module", return_value=fixer),
        ):
            result = main.apply_manual_review_result(request)

        self.assertEqual(result["output_kind"], "json_sidecar")
        self.assertEqual(written["source"], Path(chapter_files[0]))
        self.assertEqual(written["clues"]["group_search"], group_search)
        self.assertEqual(
            written["clues"]["group_search"]["files"],
            chapter_files,
        )
        # A grouped book routes folder-level (alone=False; the group_search clue
        # forces folder placement) and still writes a metadata.json.
        self.assertFalse(written["marker_alone"])
        self.assertFalse(written["meta_json_alone"])
        self.assertEqual(result["metadata_json_path"], "/library/Book/metadata.json")


if __name__ == "__main__":
    unittest.main()
