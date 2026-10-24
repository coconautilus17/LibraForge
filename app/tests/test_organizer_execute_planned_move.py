import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script


ORGANIZER = load_script("organizer_v3_13", "organize-audiobooks-by-metadata-v3_13.py")


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

    def test_two_books_in_one_folder_share_a_sidecar_and_a_cover_without_failing(self):
        # An audiobook and its ebook sit in one folder and are planned as two
        # loose files that both list libraforge.json and the same-stem cover.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "incoming" / "Some Book"
            folder.mkdir(parents=True)
            audio, ebook = folder / "Some Book.m4b", folder / "Some Book.epub"
            sidecar, cover = folder / "libraforge.json", folder / "Some Book.jpg"
            for path in (audio, ebook, sidecar, cover):
                path.touch()
            shared = [sidecar, cover]
            moves = [
                {"kind": "loose_file", "source": audio, "target": root / "lib" / "A" / "Some Book" / "Some Book.m4b", "companions": shared},
                {"kind": "loose_file", "source": ebook, "target": root / "lib" / "A" / "Some Book - EBOOK" / "Some Book.epub", "companions": shared},
            ]
            for move in moves:
                ORGANIZER.execute_planned_move(move, merge_existing_targets=False, remove_empty_dirs=True, root=root)

            self.assertTrue(moves[0]["target"].exists())
            self.assertTrue(moves[1]["target"].exists())
            self.assertTrue((moves[0]["target"].parent / "libraforge.json").exists())
            self.assertFalse(folder.exists(), "the emptied source folder is cleaned up after the last book")

    def test_a_cover_and_notes_file_keep_their_own_names_beside_the_book(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "incoming" / "Some Book"
            folder.mkdir(parents=True)
            audio = folder / "Some Book.m4b"
            extras = [folder / "cover-ln.jpg", folder / "info.txt", folder / "Other Name.nfo"]
            for path in [audio, *extras]:
                path.touch()
            target = root / "lib" / "Author" / "Some Book" / "Some Book.m4b"

            ORGANIZER.execute_planned_move(
                {"kind": "loose_file", "source": audio, "target": target, "companions": extras},
                merge_existing_targets=False, remove_empty_dirs=True, root=root,
            )

            self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["Other Name.nfo", "Some Book.m4b", "cover-ln.jpg", "info.txt"])
            self.assertFalse(folder.exists())

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
