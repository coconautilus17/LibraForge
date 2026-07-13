import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_move_execution", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class PlanLooseFileMoveTemplateFilenameTests(unittest.TestCase):
    def test_no_template_filename_falls_back_to_clean_loose_audio_filename(self):
        target_dir = Path("/library/G.D. Brooks/Dashing Devil/Book 5 - Bold Beginnings")
        item = ORGANIZER.BookItem(
            "loose_file", Path("/incoming/Bold Beginnings.m4b"), [Path("/incoming/Bold Beginnings.m4b")],
            Path("/incoming/Bold Beginnings.m4b"),
        )
        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(item, target_dir)
        self.assertTrue(can_move)
        self.assertEqual(target_path, target_dir / "Bold Beginnings.m4b")

    def test_restatement_source_name_rebuilt_from_metadata_in_builtin_scheme(self):
        # A jumbled name that restates the metadata (doubled series) slips past
        # clean_loose_audio_filename (kept verbatim), but with metadata the
        # built-in scheme rebuilds it as "Book N - Title" too.
        target_dir = Path("/library/David Burke/Crystal Core/Book 1")
        src = Path("/incoming/Crystal_Core_Crystal_Core,_Book_1.m4b")
        item = ORGANIZER.BookItem("loose_file", src, [src], src)
        metadata = {"author": "David Burke", "series": "Crystal Core", "title": "Crystal Core", "book_number": "1", "sequence_label": ""}
        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(item, target_dir, metadata=metadata)
        self.assertTrue(can_move)
        self.assertEqual(target_path, target_dir / "Book 1 - Crystal Core.m4b")

    def test_clean_source_name_untouched_in_builtin_scheme_even_with_metadata(self):
        # A clean, non-restating source name is still kept verbatim -- metadata
        # is only a fallback for junk, never an override of a good name.
        target_dir = Path("/library/Andrew Rowe/The War of Broken Mirrors/Book 1 - Forging Divinity")
        src = Path("/incoming/Forging Divinity.m4b")
        item = ORGANIZER.BookItem("loose_file", src, [src], src)
        metadata = {"author": "Andrew Rowe", "series": "The War of Broken Mirrors", "title": "Forging Divinity", "book_number": "1", "sequence_label": ""}
        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(item, target_dir, metadata=metadata)
        self.assertTrue(can_move)
        self.assertEqual(target_path, target_dir / "Forging Divinity.m4b")

    def test_template_filename_overrides_clean_loose_audio_filename(self):
        # template_filename is an extension-less stem; the source file's
        # own extension must survive onto the final target filename.
        target_dir = Path("/library/G.D. Brooks/Dashing Devil/Book 5 - Bold Beginnings")
        item = ORGANIZER.BookItem(
            "loose_file", Path("/incoming/Bold Beginnings.m4b"), [Path("/incoming/Bold Beginnings.m4b")],
            Path("/incoming/Bold Beginnings.m4b"),
        )
        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(
            item, target_dir, template_filename="Custom Name"
        )
        self.assertTrue(can_move)
        self.assertEqual(target_path, target_dir / "Custom Name.m4b")


class ExecutePlannedMoveFolderRenameTests(unittest.TestCase):
    def test_folder_move_renames_single_audio_file_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "_unorganized" / "Some Book"
            source.mkdir(parents=True)
            (source / "book.m4b").write_text("audio", encoding="utf-8")
            target = root / "Author" / "Custom Filename.m4b_folder"
            move = {
                "kind": "folder",
                "source": source,
                "target": target,
                "companions": [],
                "partial_group": False,
                "leftover_files": [],
                "original_audio_name": "book.m4b",
                "rename_audio_to": "Custom Filename.m4b",
            }
            ORGANIZER.execute_planned_move(
                move, merge_existing_targets=False, remove_empty_dirs=False, root=root
            )
            self.assertTrue((target / "Custom Filename.m4b").is_file())
            self.assertFalse((target / "book.m4b").exists())

    def test_folder_move_without_rename_request_keeps_original_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "_unorganized" / "Some Book"
            source.mkdir(parents=True)
            (source / "book.m4b").write_text("audio", encoding="utf-8")
            target = root / "Author" / "Some Book"
            move = {
                "kind": "folder",
                "source": source,
                "target": target,
                "companions": [],
                "partial_group": False,
                "leftover_files": [],
            }
            ORGANIZER.execute_planned_move(
                move, merge_existing_targets=False, remove_empty_dirs=False, root=root
            )
            self.assertTrue((target / "book.m4b").is_file())


if __name__ == "__main__":
    unittest.main()
