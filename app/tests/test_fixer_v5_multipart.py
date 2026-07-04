import importlib.util
import sys
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


FIXER = load_module("fixer_v5_multipart", "scripts/audible-metadata-fixer-v5.py")


class DetectPartMarkerTests(unittest.TestCase):
    def test_part_word_with_trailing_parenthetical(self):
        a = FIXER.detect_part_marker("LotR1 - The Fellowship of the Ring - Part 1 (read by X)")
        b = FIXER.detect_part_marker("LotR1 - The Fellowship of the Ring - Part 2 (read by X)")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a[1], 1)
        self.assertEqual(b[1], 2)
        self.assertEqual(a[0], b[0])  # same identity prefix

    def test_part_inside_parens_single_digit(self):
        a = FIXER.detect_part_marker("Ready Player One (RP1SFX 9 Part 1)")
        b = FIXER.detect_part_marker("Ready Player One (RP1SFX 9 Part 2)")
        self.assertEqual(a[1], 1)
        self.assertEqual(b[1], 2)
        self.assertEqual(a[0], b[0])

    def test_n_of_m(self):
        a = FIXER.detect_part_marker("Some Book 1 of 3")
        c = FIXER.detect_part_marker("Some Book 3 of 3")
        self.assertEqual(a[1], 1)
        self.assertEqual(c[1], 3)
        self.assertEqual(a[0], c[0])

    def test_disc_marker(self):
        self.assertEqual(FIXER.detect_part_marker("Title - Disc 02")[1], 2)
        self.assertEqual(FIXER.detect_part_marker("Title CD3")[1], 3)

    def test_complete_file_has_no_marker(self):
        self.assertIsNone(FIXER.detect_part_marker("The Lord of the Rings The Fellowship of the Ring"))
        self.assertIsNone(FIXER.detect_part_marker("Ready Player One"))

    def test_series_number_is_not_a_part_marker(self):
        # A bare numeric series suffix must not look like a part.
        self.assertIsNone(FIXER.detect_part_marker("Mistborn 1"))
        self.assertIsNone(FIXER.detect_part_marker("Mistborn 2"))


class MultiPartGroupingTests(unittest.TestCase):
    def _group(self, names, chapters, folder="/book"):
        files = [Path(f"{folder}/{n}") for n in names]
        reader = lambda p: chapters.get(p.name)
        groups = FIXER.build_multi_part_group_map(files, chapter_count_reader=reader)
        grouped = {p for fs in groups.values() for p in fs}
        return files, groups, grouped

    def test_part_files_group_despite_high_chapter_counts(self):
        # The real _unorganized case: two parts with 10+ chapters each plus a
        # complete edition. Parts must group; the complete file stays separate.
        names = [
            "LotR1 - The Fellowship of the Ring - Part 1 (read by Phil Dragash).m4b",
            "LotR1 - The Fellowship of the Ring - Part 2 (read by Phil Dragash).m4b",
            "The Lord of the Rings The Fellowship of the Ring.m4b",
        ]
        chapters = {names[0]: 12, names[1]: 10, names[2]: 22}
        files, groups, grouped = self._group(names, chapters)
        self.assertEqual(groups[Path("/book")], files[:2])
        self.assertNotIn(files[2], grouped)  # complete edition processed alone

    def test_part_inside_parens_groups(self):
        names = [
            "Ready Player One (RP1SFX 9 Part 1).m4b",
            "Ready Player One (RP1SFX 9 Part 2).m4b",
            "Ready Player One.m4b",
        ]
        chapters = {names[0]: 32, names[1]: 8, names[2]: 40}
        files, groups, grouped = self._group(names, chapters)
        self.assertEqual(groups[Path("/book")], files[:2])
        self.assertNotIn(files[2], grouped)

    def test_distinct_complete_books_not_grouped(self):
        # Two complete books in one folder, no part markers, many chapters each.
        names = [
            "J. R. R. Tolkien - The Fellowship of the Ring.m4b",
            "J. R. R. Tolkien - The Two Towers.m4b",
        ]
        chapters = {names[0]: 50, names[1]: 50}
        _files, groups, _grouped = self._group(names, chapters)
        self.assertEqual(groups, {})

    def test_zero_padded_numeric_parts_still_group(self):
        # Pre-existing behavior must be preserved.
        names = [
            "Example Book 3 - 01.m4b",
            "Example Book 3 - 02.m4b",
            "Example Book 3 - 03.m4b",
            "Example Book 3.m4b",
        ]
        chapters = {n: (30 if n == "Example Book 3.m4b" else 0) for n in names}
        files, groups, grouped = self._group(names, chapters)
        self.assertEqual(groups[Path("/book")], files[:3])
        self.assertNotIn(files[3], grouped)


if __name__ == "__main__":
    unittest.main()
