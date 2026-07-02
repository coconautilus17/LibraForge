"""pick_sidecar() must never hand back a DIFFERENT book's sidecar.

Bug: in a folder holding several independent, single-file books (e.g. a
mixed "Classics" dump: The Prince.m4b, Sun Tzu - The Art of War.m4b,
Lessons of History.m4b), only some of which have been processed and thus
have a per-file `<name>.m4b-tool-metadata.json` sidecar, loading manual
review for an *unprocessed* book (no sidecar of its own) fell through to
`sidecars[0]` -- an arbitrary, unrelated sibling's sidecar -- instead of
reporting "no sidecar for this file". That made the compare table (and the
matcher fed by it) show a completely different book's metadata.
"""
import tempfile
import unittest
from pathlib import Path

from app import main


class PickSidecarAmbiguousFolderTests(unittest.TestCase):
    def test_unprocessed_file_in_a_multi_book_folder_gets_no_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.m4b").touch()
            (folder / "Sun Tzu - The Art of War.m4b").touch()
            (folder / "Lessons of History.m4b").touch()
            # Only "Lessons of History" has been processed already.
            (folder / "Lessons of History.m4b.m4b-tool-metadata.json").write_text("{}")

            target = folder / "The Prince.m4b"
            sidecars = main.discover_sidecars(target)
            selected = main.pick_sidecar(target, sidecars)

            self.assertIsNone(selected)

    def test_second_unprocessed_file_also_gets_no_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.m4b").touch()
            (folder / "Sun Tzu - The Art of War.m4b").touch()
            (folder / "Lessons of History.m4b").touch()
            (folder / "Lessons of History.m4b.m4b-tool-metadata.json").write_text("{}")

            target = folder / "Sun Tzu - The Art of War.m4b"
            sidecars = main.discover_sidecars(target)
            selected = main.pick_sidecar(target, sidecars)

            self.assertIsNone(selected)

    def test_own_sidecar_is_still_picked_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.m4b").touch()
            (folder / "Lessons of History.m4b").touch()
            (folder / "The Prince.m4b.m4b-tool-metadata.json").write_text("{}")
            (folder / "Lessons of History.m4b.m4b-tool-metadata.json").write_text("{}")

            target = folder / "The Prince.m4b"
            sidecars = main.discover_sidecars(target)
            selected = main.pick_sidecar(target, sidecars)

            self.assertEqual(selected, folder / "The Prince.m4b.m4b-tool-metadata.json")

    def test_grouped_sidecar_naming_the_anchor_file_still_covers_its_parts(self):
        # A genuinely grouped book: the sidecar is named after the group's
        # first part rather than the folder or the specific part being
        # queried, but its recorded source.chapter_files explicitly lists
        # every part -- so it's trusted even without a name match.
        import json as _json

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            part1 = folder / "Part 01.m4b"
            part2 = folder / "Part 02.m4b"
            part1.touch()
            part2.touch()
            sidecar_path = folder / "Part 01.m4b.m4b-tool-metadata.json"
            sidecar_path.write_text(
                _json.dumps({"source": {"chapter_files": [str(part1), str(part2)]}})
            )

            target = part2
            sidecars = main.discover_sidecars(target)
            selected = main.pick_sidecar(target, sidecars)

            self.assertEqual(selected, sidecar_path)

    def test_unrelated_sole_sidecar_does_not_cover_a_different_file(self):
        # Same shape as above, but the sidecar's recorded chapter_files does
        # NOT include the queried file -- it must not be borrowed even
        # though it's the only sidecar in the folder.
        import json as _json

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.m4b").touch()
            other = folder / "Lessons of History.m4b"
            other.touch()
            sidecar_path = folder / "Lessons of History.m4b.m4b-tool-metadata.json"
            sidecar_path.write_text(
                _json.dumps({"source": {"chapter_files": [str(other)]}})
            )

            target = folder / "The Prince.m4b"
            sidecars = main.discover_sidecars(target)
            selected = main.pick_sidecar(target, sidecars)

            self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
