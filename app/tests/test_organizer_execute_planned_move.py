import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class ExecutePlannedMoveTests(unittest.TestCase):
    def test_moves_folder_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming" / "Some Book"
            source.mkdir(parents=True)
            (source / "book.m4b").touch()
            target = root / "library" / "Author" / "Some Book"

            ORGANIZER.execute_planned_move(
                {"kind": "folder", "source": source, "target": target, "companions": []},
                merge_existing_targets=False,
                remove_empty_dirs=False,
                root=root,
            )

            self.assertFalse(source.exists())
            self.assertTrue((target / "book.m4b").exists())

    def test_moves_loose_file_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming" / "book.m4b"
            source.parent.mkdir(parents=True)
            source.touch()
            target = root / "library" / "Author" / "Book" / "book.m4b"

            ORGANIZER.execute_planned_move(
                {"kind": "loose_file", "source": source, "target": target, "companions": []},
                merge_existing_targets=False,
                remove_empty_dirs=False,
                root=root,
            )

            self.assertFalse(source.exists())
            self.assertTrue(target.exists())

    def test_raises_when_source_no_longer_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            # Simulates a race: planned during scan, gone by the time we apply.
            source = root / "incoming" / "Some Book"
            target = root / "library" / "Author" / "Some Book"

            with self.assertRaises(FileNotFoundError):
                ORGANIZER.execute_planned_move(
                    {"kind": "folder", "source": source, "target": target, "companions": []},
                    merge_existing_targets=False,
                    remove_empty_dirs=False,
                    root=root,
                )

    def test_removes_empty_source_parent_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming" / "Some Book"
            source.mkdir(parents=True)
            (source / "book.m4b").touch()
            target = root / "library" / "Author" / "Some Book"

            ORGANIZER.execute_planned_move(
                {"kind": "folder", "source": source, "target": target, "companions": []},
                merge_existing_targets=False,
                remove_empty_dirs=True,
                root=root,
            )

            self.assertFalse((root / "incoming").exists())


if __name__ == "__main__":
    unittest.main()
