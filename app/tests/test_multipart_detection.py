"""Folder Forge and the Metadata Fixer each decide whether several audio files
are slices of ONE book by their names (explicit part markers, shared prefix +
number, leading ordinals) and then refuse the grouping when a file looks like a
complete book. The two scripts carry separate copies of this logic, so every
test below runs against BOTH: a change to one copy that the other does not get
fails here."""
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


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ORGANIZER = _load("multipart_parity_organizer", "scripts/organize-audiobooks-by-metadata-v3_13.py")
FIXER = _load("multipart_parity_fixer", "scripts/audible-metadata-fixer-v5.py")


def files(*stems, ext=".m4b"):
    return [Path("/x") / f"{stem}{ext}" for stem in stems]


def stems(paths):
    return sorted(p.stem for p in paths)


class DetectPartMarkerTests:
    def test_each_explicit_marker_style_gives_the_identity_and_part_index(self):
        for stem, expected in (("Book - Part 2", ("book", 2)), ("Book (Pt. 3)", ("book", 3)), ("Book Disc 4", ("book", 4)),
                               ("Book CD2", ("book", 2)), ("Book Disk 5", ("book", 5)), ("Book 1 of 3", ("book", 1)),
                               ("Book Part 007", ("book", 7))):
            with self.subTest(stem=stem):
                self.assertEqual(self.M.detect_part_marker(stem), expected)

    def test_the_last_marker_wins_so_a_leading_series_number_does_not_shadow_the_part(self):
        self.assertEqual(self.M.detect_part_marker("LotR1 - Fellowship - Part 2"), ("lotr1 fellowship", 2))

    def test_a_name_that_is_only_a_marker_gets_a_placeholder_identity(self):
        self.assertEqual(self.M.detect_part_marker("Part 01"), ("_", 1))

    def test_no_marker_gives_none(self):
        self.assertIsNone(self.M.detect_part_marker("Plain Title"))
        self.assertIsNone(self.M.detect_part_marker(""))


class MarkerSequenceTests:
    def test_a_contiguous_run_from_one_is_a_sequence(self):
        got = self.M.marker_sequence_files(files("Book Part 1", "Book Part 2", "Book Part 3"))
        self.assertEqual(stems(got), ["Book Part 1", "Book Part 2", "Book Part 3"])

    def test_a_run_may_start_at_zero(self):
        self.assertEqual(stems(self.M.marker_sequence_files(files("Book Part 0", "Book Part 1"))), ["Book Part 0", "Book Part 1"])

    def test_gaps_duplicates_late_starts_and_single_files_are_not_sequences(self):
        for names in (("Book Part 1", "Book Part 3"), ("Book Part 1", "Book Part 1"), ("Book Part 2", "Book Part 3"), ("Book Part 1",)):
            with self.subTest(names=names):
                self.assertEqual(self.M.marker_sequence_files(files(*names)), set())

    def test_the_largest_complete_group_wins_among_several_identities(self):
        names = ("A Part 1", "A Part 2", "B Part 1", "B Part 2", "B Part 3")
        self.assertEqual(stems(self.M.marker_sequence_files(files(*names))), ["B Part 1", "B Part 2", "B Part 3"])

    def test_files_without_markers_are_ignored(self):
        self.assertEqual(self.M.marker_sequence_files(files("One", "Two")), set())


class NumericPartSequenceTests:
    def test_a_shared_prefix_and_dash_number_is_a_sequence(self):
        got = self.M.numeric_part_sequence_files(files("Book - 01", "Book - 02", "Book - 03"))
        self.assertEqual(stems(got), ["Book - 01", "Book - 02", "Book - 03"])

    def test_a_varying_chapter_title_after_the_number_does_not_block_grouping(self):
        got = self.M.numeric_part_sequence_files(files("Book - 01 - Chapter One", "Book - 02 - Preface"))
        self.assertEqual(len(got), 2)

    def test_the_run_must_start_at_zero_or_one_be_contiguous_and_share_the_prefix_and_width(self):
        for names in (("Book - 02", "Book - 03"), ("Book - 01", "Other - 02"), ("Book - 01", "Book - 03"),
                      ("Book - 1", "Book - 2"), ("Book - 01", "Book - 002")):
            with self.subTest(names=names):
                self.assertEqual(self.M.numeric_part_sequence_files(files(*names)), set())

    def test_a_single_numbered_file_is_not_a_sequence(self):
        self.assertEqual(self.M.numeric_part_sequence_files(files("Book - 01")), set())


class LeadingOrdinalSequenceTests:
    def test_chapter_files_sharing_a_trailing_identity_group(self):
        names = ("0. Opening Credits - The Book - Narrator", "1. Time Starts - The Book - Narrator", "2. Next - The Book - Narrator")
        self.assertEqual(len(self.M.leading_ordinal_sequence_files(files(*names))), 3)

    def test_chapter_files_sharing_a_leading_identity_group(self):
        names = ("001 Author - The Book - Opening", "002 Author - The Book - Next", "003 Author - The Book - Last")
        self.assertEqual(len(self.M.leading_ordinal_sequence_files(files(*names))), 3)

    def test_fewer_than_three_files_do_not_group(self):
        self.assertEqual(self.M.leading_ordinal_sequence_files(files("1. A - The Book", "2. B - The Book")), set())

    def test_exactly_three_files_are_enough(self):
        names = ("1. A - The Book N", "2. B - The Book N", "3. C - The Book N")
        self.assertEqual(len(self.M.leading_ordinal_sequence_files(files(*names))), 3)

    def test_gaps_late_starts_and_duplicate_indexes_do_not_group(self):
        for names in (("1. A - The Book - N", "2. B - The Book - N", "4. D - The Book - N"),
                      ("2. A - The Book - N", "3. B - The Book - N", "4. C - The Book - N"),
                      ("1. A - The Book - N", "1. B - The Book - N", "2. C - The Book - N")):
            with self.subTest(names=names):
                self.assertEqual(self.M.leading_ordinal_sequence_files(files(*names)), set())

    def test_files_without_a_shared_identity_of_two_tokens_do_not_group(self):
        names = ("1. A - X", "2. B - Y", "3. C - Z")
        self.assertEqual(self.M.leading_ordinal_sequence_files(files(*names)), set())

    def test_common_tokens_are_taken_from_the_requested_end(self):
        self.assertEqual(self.M._common_trailing_tokens([["a", "b", "c"], ["x", "b", "c"]]), ["b", "c"])
        self.assertEqual(self.M._common_trailing_tokens([["a", "b", "c"], ["c"], ["b", "c"]]), ["c"])
        self.assertEqual(self.M._common_trailing_tokens([["a", "b"], ["c", "d"]]), [])
        self.assertEqual(self.M._common_trailing_tokens([["a", "b"]]), ["a", "b"])
        self.assertEqual(self.M._common_trailing_tokens([]), [])
        self.assertEqual(self.M._common_leading_tokens([["a", "b", "c"], ["a", "b", "x"]]), ["a", "b"])
        self.assertEqual(self.M._common_leading_tokens([["a", "b"], ["a", "b"], ["a"]]), ["a"])
        self.assertEqual(self.M._common_leading_tokens([["a"], ["b"]]), [])
        self.assertEqual(self.M._common_leading_tokens([]), [])

    def test_the_overall_recogniser_prefers_markers_then_numeric_then_leading_ordinals(self):
        markers = files("Book Part 1", "Book Part 2")
        self.assertEqual(stems(self.M.part_sequence_files(markers)), ["Book Part 1", "Book Part 2"])
        numeric = files("Book - 01", "Book - 02")
        self.assertEqual(stems(self.M.part_sequence_files(numeric)), ["Book - 01", "Book - 02"])
        ordinals = files("1. A - The Book N", "2. B - The Book N", "3. C - The Book N")
        self.assertEqual(len(self.M.part_sequence_files(ordinals)), 3)
        self.assertEqual(self.M.part_sequence_files(files("One", "Two")), set())


class ClassifyMultiPartSafetyTests:
    def classify(self, name, chapters, numeric=False):
        return self.M.classify_multi_part_file_safety(Path(name), chapters, numeric)

    def test_unreadable_chapter_data_is_unsafe(self):
        self.assertEqual(self.classify("a.mp3", None), (False, "chapter metadata unreadable"))

    def test_a_non_m4b_with_at_most_one_chapter_is_safe(self):
        self.assertEqual(self.classify("a.mp3", 0), (True, "no embedded chapters or one wrapper chapter"))
        self.assertEqual(self.classify("a.mp3", 1), (True, "no embedded chapters or one wrapper chapter"))

    def test_a_non_m4b_with_two_or_more_chapters_needs_a_chapter_like_name(self):
        self.assertFalse(self.classify("a.mp3", 2)[0])
        self.assertTrue(self.classify("Chapter 01.mp3", 2)[0])
        self.assertTrue(self.classify("a.mp3", 2, numeric=True)[0])

    def test_a_named_part_may_carry_up_to_three_chapters(self):
        self.assertTrue(self.classify("Chapter 01.m4b", 3)[0])
        self.assertEqual(self.classify("Chapter 01.m4b", 4), (False, "embedded chapter count 4 suggests a complete audiobook"))
        self.assertIn("low embedded chapter count (3)", self.classify("Chapter 01.m4b", 3)[1])

    def test_a_plain_m4b_with_one_chapter_is_refused_unless_its_name_marks_it_as_a_part(self):
        self.assertEqual(self.classify("a.m4b", 1), (False, "low chapter count M4B lacks a chapter-like filename"))
        self.assertTrue(self.classify("a.m4b", 1, numeric=True)[0])
        self.assertTrue(self.classify("Part 2.m4b", 1)[0])

    def test_many_chapters_always_mean_a_complete_book(self):
        self.assertEqual(self.classify("a.mp3", 30), (False, "embedded chapter count 30 suggests a complete audiobook"))
        self.assertFalse(self.classify("a.m4b", 5, numeric=True)[0])


def _register():
    for mixin_name in ['DetectPartMarkerTests', 'MarkerSequenceTests', 'NumericPartSequenceTests', 'LeadingOrdinalSequenceTests', 'ClassifyMultiPartSafetyTests']:
        mixin = globals()[mixin_name]
        for label, module in (("Organizer", ORGANIZER), ("Fixer", FIXER)):
            cls = type(f"{mixin_name}{label}", (mixin, unittest.TestCase), {"M": module})
            globals()[cls.__name__] = cls


_register()


if __name__ == "__main__":
    unittest.main()
