import unittest
from pathlib import Path
from app.tests.script_loader import load_module


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

    def test_files_with_many_embedded_chapters_are_not_forced_together(self):
        # A "Part N" filename token is not proof of a real split -- it can just
        # as easily be two separate (or duplicate) complete recordings sharing
        # a naming convention. A real high embedded chapter count outranks the
        # filename, so these must NOT be grouped just because they say "Part".
        # The tool leaves this for the user to merge or leave as-is.
        for label, files in (
            ("part tokens", {
                "LotR1 - The Fellowship of the Ring - Part 1 (read by Phil Dragash).m4b": 12,
                "LotR1 - The Fellowship of the Ring - Part 2 (read by Phil Dragash).m4b": 10,
                "The Lord of the Rings The Fellowship of the Ring.m4b": 22,
            }),
            ("part inside parens", {
                "Ready Player One (RP1SFX 9 Part 1).m4b": 32,
                "Ready Player One (RP1SFX 9 Part 2).m4b": 8,
                "Ready Player One.m4b": 40,
            }),
            # Two complete books in one folder, no part markers, many chapters each.
            ("distinct complete books", {
                "J. R. R. Tolkien - The Fellowship of the Ring.m4b": 50,
                "J. R. R. Tolkien - The Two Towers.m4b": 50,
            }),
        ):
            with self.subTest(label):
                _files, groups, _grouped = self._group(list(files), files)
                self.assertEqual(groups, {})

    def test_low_chapter_part_files_group_excluding_unrelated_complete_edition(self):
        # The narrow, safe case a part marker still helps with: two low-chapter
        # "Part N" files alongside an unrelated high-chapter complete edition.
        # Without marker-based candidate selection, the complete edition's real
        # chapter count would poison the whole folder's validation and reject
        # the legitimate parts too. The marker lets the parts be considered on
        # their own, while the complete edition (no marker, real chapters) is
        # still correctly rejected as its own book.
        names = [
            "Some Book - Part 1.m4b",
            "Some Book - Part 2.m4b",
            "Some Book Complete Edition.m4b",
        ]
        chapters = {names[0]: 2, names[1]: 2, names[2]: 40}
        files, groups, grouped = self._group(names, chapters)
        self.assertEqual(groups[Path("/book")], files[:2])
        self.assertNotIn(files[2], grouped)

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
