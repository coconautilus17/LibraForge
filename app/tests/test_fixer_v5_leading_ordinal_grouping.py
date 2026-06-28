"""Leading-ordinal multi-part grouping in the v5 fixer.

Covers the fix for chapter splits numbered at the FRONT of the filename
(e.g. "0. Opening Credits - Book - Narrator", "1. Time Starts Now - ...").
These could not be grouped before because part detection only understood
trailing "- 01" numbers. The new path groups them only when the folder
clearly holds one book cut into many parts, and otherwise leaves distinct
books (Spellmonger-style) split.
"""
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


FIXER = load_module("fixer_v5_leading_ordinal", "scripts/audible-metadata-fixer-v5.py")


def speedrunning_parts(count: int) -> list[Path]:
    """A single book cut into `count` leading-ordinal chapter files."""
    titles = ["Opening Credits", "Time Starts Now", "Plan", "Alchemist Hu", "Stung"]
    return [
        Path(
            "/book/Speedrunning the Multiverse (Book 1)/"
            f"{i}. {titles[i % len(titles)]} - Speedrunning the Multiverse - adastra339.m4b"
        )
        for i in range(count)
    ]


class LeadingOrdinalSequenceTests(unittest.TestCase):
    def test_contiguous_parts_with_shared_identity_are_detected(self):
        files = speedrunning_parts(6)
        self.assertEqual(FIXER.leading_ordinal_sequence_files(files), set(files))

    def test_part_sequence_files_prefers_trailing_then_falls_back_to_leading(self):
        # Trailing "- 01" numbering still wins (unchanged behavior).
        trailing = [
            Path("/b/Example Book - 01.mp3"),
            Path("/b/Example Book - 02.mp3"),
        ]
        self.assertEqual(FIXER.part_sequence_files(trailing), set(trailing))
        # Leading ordinals are picked up only when there is no trailing number.
        leading = speedrunning_parts(4)
        self.assertEqual(FIXER.part_sequence_files(leading), set(leading))

    def test_non_contiguous_ordinals_are_rejected(self):
        # Spellmonger-style: distinct books sharing a folder, gaps in numbering.
        files = [
            Path("/s/001 - Spellmonger - Book 001 - Spellmonger.m4b"),
            Path("/s/006 - Side Story 003 - Spellmongers wedding.m4b"),
            Path("/s/007 - Side Story 004 - Spellmonger's Honeymoon.m4b"),
            Path("/s/027 - Side Story 012 - The Spellmonger's Yule.m4b"),
        ]
        self.assertEqual(FIXER.leading_ordinal_sequence_files(files), set())

    def test_duplicate_index_is_rejected(self):
        # Two encodings of the same single book (both "01_...").
        files = [
            Path("/b/01_Depthless Hunger_[B0FX64WVSR]_AAC-LC.m4b"),
            Path("/b/01_Depthless Hunger_[B0FX64WVSR]_xHE-AAC.m4b"),
        ]
        self.assertEqual(FIXER.leading_ordinal_sequence_files(files), set())

    def test_without_shared_trailing_identity_rejected(self):
        # Contiguous 1..3 but each a different titled book, no shared suffix.
        files = [
            Path("/m/01 Master of the Towers.m4b"),
            Path("/m/02 Tower of the Undying Mage.m4b"),
            Path("/m/03 Tower of Claw and Sorcery.m4b"),
        ]
        self.assertEqual(FIXER.leading_ordinal_sequence_files(files), set())

    def test_too_few_parts_rejected(self):
        files = speedrunning_parts(2)
        self.assertEqual(FIXER.leading_ordinal_sequence_files(files), set())


class LeadingOrdinalGroupMapTests(unittest.TestCase):
    def test_low_chapter_parts_are_grouped(self):
        files = speedrunning_parts(6)
        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda _path: 1,  # one wrapper chapter per slice
        )
        self.assertEqual(groups[files[0].parent], files)

    def test_distinct_full_books_are_not_grouped_even_when_contiguous(self):
        # Contiguous leading ordinals, shared narrator suffix, but each file is a
        # full book (many embedded chapters) -> chapter-count net must reject.
        files = [
            Path("/x/1 - Spellmonger Book One - Narrator.m4b"),
            Path("/x/2 - Spellmonger Book Two - Narrator.m4b"),
            Path("/x/3 - Spellmonger Book Three - Narrator.m4b"),
        ]
        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda _path: 40,
        )
        self.assertEqual(groups, {})

    def test_existing_trailing_number_grouping_still_works(self):
        # Regression guard for the original numeric_part_sequence_files path.
        files = [
            Path("/book/Example Book 3 - 01.m4b"),
            Path("/book/Example Book 3 - 02.m4b"),
            Path("/book/Example Book 3 - 03.m4b"),
            Path("/book/Example Book 3.m4b"),
        ]
        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda path: 30 if path.name == "Example Book 3.m4b" else 0,
        )
        self.assertEqual(groups[Path("/book")], files[:3])


if __name__ == "__main__":
    unittest.main()
