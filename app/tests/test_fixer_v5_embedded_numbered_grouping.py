"""Numbered chapter splits where the index sits BETWEEN a shared book-title
prefix and a varying chapter-title suffix, e.g.:

  "The Evolution of Nuclear Strategy [B09B4FJ7MV] - 01 - Opening Credits.m4b"
  "The Evolution of Nuclear Strategy [B09B4FJ7MV] - 02 - Preface.m4b"
  ...
  "The Evolution of Nuclear Strategy [B09B4FJ7MV] - 43 - Chapter 40: ....m4b"

numeric_part_sequence_files() previously only matched a part number anchored
at the very END of the filename ("Book - 01.mp3"). A number sandwiched
between a shared prefix and a per-file chapter title (this pattern) never
matched, so these folders fell back to per-filename chapter-keyword
guessing, and any file whose title didn't hit a keyword (e.g. "Preface")
sank the whole folder's grouping.
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


FIXER = load_module("fixer_v5_embedded_numbered", "scripts/audible-metadata-fixer-v5.py")


def nuclear_strategy_parts(count: int) -> list[Path]:
    prefix = "The Evolution of Nuclear Strategy [B09B4FJ7MV]"
    titles = ["Opening Credits", "Preface", "Chapter 1", "Chapter 2", "Chapter 3"]
    return [
        Path(f"/book/{prefix}/{prefix} - {i + 1:02d} - {titles[i % len(titles)]}.m4b")
        for i in range(count)
    ]


class EmbeddedNumberedSequenceTests(unittest.TestCase):
    def test_number_between_shared_prefix_and_varying_suffix_is_detected(self):
        files = nuclear_strategy_parts(6)
        self.assertEqual(FIXER.numeric_part_sequence_files(files), set(files))

    def test_part_sequence_files_also_picks_it_up(self):
        files = nuclear_strategy_parts(6)
        self.assertEqual(FIXER.part_sequence_files(files), set(files))

    def test_whole_group_is_grouped_despite_a_non_chapter_named_file(self):
        # "Preface" (index 2) matches no chapter-keyword pattern on its own;
        # the shared numeric identity must be enough to keep the group safe.
        files = nuclear_strategy_parts(5)
        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda _path: 0,
        )
        self.assertEqual(groups[Path(f"/book/{files[0].parent.name}")], files)

    def test_trailing_only_numbering_is_unaffected(self):
        # Existing "Book - 01.mp3" (no suffix after the number) still matches.
        files = [
            Path("/b/Example Book - 01.mp3"),
            Path("/b/Example Book - 02.mp3"),
        ]
        self.assertEqual(FIXER.numeric_part_sequence_files(files), set(files))

    def test_different_shared_prefixes_do_not_cross_group(self):
        files = [
            Path("/book/Series A - 01 - Intro.m4b"),
            Path("/book/Series B - 02 - Intro.m4b"),
        ]
        self.assertEqual(FIXER.numeric_part_sequence_files(files), set())


if __name__ == "__main__":
    unittest.main()
