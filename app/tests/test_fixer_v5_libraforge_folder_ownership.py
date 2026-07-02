"""_load_libraforge_raw() must never read from -- or write into -- a
folder-level libraforge.json that belongs to a DIFFERENT file.

Bug: `_unorganized` (a shared "unsorted books" root) can hold several
independent, loose single-file books. `_load_libraforge_raw` checked
`folder / "libraforge.json"` first and trusted it unconditionally, so once
ANY book in that shared folder got a folder-level libraforge.json (e.g. via
a wrongly-computed `alone=True`), every OTHER loose file sharing that folder
silently inherited its data: reads recovered the wrong book's title/author,
and writes clobbered the first book's record instead of creating their own.
This reproduced exactly what was observed live: loading "The Prince" showed
"Lessons of History"'s data, and "Sun Tzu - The Art of War"'s own search
query got corrupted with "The Prince"'s title.
"""
import importlib.util
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


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_libraforge_ownership", "scripts/audible-metadata-fixer-v5.py")


class LibraforgeFolderOwnershipTests(unittest.TestCase):
    def test_foreign_backup_is_not_read_for_a_different_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.mp3").touch()
            (folder / "Sun Tzu - Art of War.m4b").touch()
            (folder / "libraforge.json").write_text(json.dumps({
                "backup": {"source_file": "The Prince.mp3", "format_tags": {"title": "The Prince"}},
            }))

            sun_tzu = folder / "Sun Tzu - Art of War.m4b"
            lf_path, payload = FIXER._load_libraforge_raw(sun_tzu, alone=False)

            self.assertNotEqual(lf_path, folder / "libraforge.json")
            self.assertEqual(payload, {})

    def test_foreign_marker_is_not_read_for_a_different_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.mp3").touch()
            (folder / "Sun Tzu - Art of War.m4b").touch()
            (folder / "libraforge.json").write_text(json.dumps({
                "marker": {"applied": False, "source_file": "The Prince.mp3",
                           "audible": {"asin": "NOREALASIN"}},
            }))

            sun_tzu = folder / "Sun Tzu - Art of War.m4b"
            lf_path, payload = FIXER._load_libraforge_raw(sun_tzu, alone=False)

            self.assertNotEqual(lf_path, folder / "libraforge.json")
            self.assertEqual(payload, {})

    def test_wrongly_alone_write_does_not_clobber_a_foreign_folder_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "The Prince.mp3").touch()
            sun_tzu = folder / "Sun Tzu - Art of War.m4b"
            sun_tzu.touch()
            folder_lf = folder / "libraforge.json"
            folder_lf.write_text(json.dumps({
                "marker": {"applied": False, "source_file": "The Prince.mp3",
                           "audible": {"asin": "NOREALASIN"}},
            }))

            # Even if `alone` is (wrongly) computed True for Sun Tzu, its
            # write must not land in -- or overwrite -- The Prince's file.
            FIXER.write_skip_marker(sun_tzu, alone=True)

            prince_payload = json.loads(folder_lf.read_text())
            self.assertEqual(prince_payload["marker"]["source_file"], "The Prince.mp3")

            own_sidecar = sun_tzu.with_name(f"{sun_tzu.name}{FIXER.LIBRAFORGE_SUFFIX}")
            self.assertTrue(own_sidecar.is_file())
            own_payload = json.loads(own_sidecar.read_text())
            self.assertEqual(own_payload["marker"]["source_file"], "Sun Tzu - Art of War.m4b")

    def test_second_skip_marker_in_shared_folder_gets_its_own_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            book_a = folder / "Book A.mp3"
            book_b = folder / "Book B.mp3"
            book_a.touch()
            book_b.touch()

            FIXER.write_skip_marker(book_a, alone=True)
            FIXER.write_skip_marker(book_b, alone=True)

            folder_lf = folder / "libraforge.json"
            a_payload = json.loads(folder_lf.read_text())
            self.assertEqual(a_payload["marker"]["source_file"], "Book A.mp3")

            b_sidecar = book_b.with_name(f"{book_b.name}{FIXER.LIBRAFORGE_SUFFIX}")
            self.assertTrue(b_sidecar.is_file())

    def test_own_alone_book_still_uses_folder_level(self):
        # Regression: a real single-book folder must keep working exactly as
        # before -- own backup, own marker, folder-level libraforge.json.
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            book = folder / "Solo Book.mp3"
            book.touch()

            FIXER.write_skip_marker(book, alone=True)

            folder_lf = folder / "libraforge.json"
            self.assertTrue(folder_lf.is_file())
            payload = json.loads(folder_lf.read_text())
            self.assertEqual(payload["marker"]["source_file"], "Solo Book.mp3")

    def test_grouped_book_chapter_files_are_still_trusted(self):
        # Regression: a genuine multi-part group's folder-level sidecar
        # names the anchor file via chapter_files -- must still be trusted
        # for every part even though the queried file isn't literally the
        # backup/marker's own name.
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            part1 = folder / "Part 01.m4b"
            part2 = folder / "Part 02.m4b"
            part1.touch()
            part2.touch()
            (folder / "libraforge.json").write_text(json.dumps({
                "sidecar": {"source": {"root_file": str(part1), "chapter_files": [str(part1), str(part2)]}},
            }))

            lf_path, payload = FIXER._load_libraforge_raw(part2, alone=False)

            self.assertEqual(lf_path, folder / "libraforge.json")
            self.assertIn("sidecar", payload)


if __name__ == "__main__":
    unittest.main()
