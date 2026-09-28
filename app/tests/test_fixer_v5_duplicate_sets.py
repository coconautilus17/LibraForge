"""A folder holding two numbered sets of files (two rips of the same book,
e.g. "Spiral - 001..025.mp3" and "Spiral-Part01..13.mp3", both 728 min) must
not be split into one fake book per orphaned file: the folder is reported
once, for the user to keep one set."""
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

spec = importlib.util.spec_from_file_location("fixer_v5_duplicate_sets", ROOT / "scripts/audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = FIXER
spec.loader.exec_module(FIXER)

SPIRAL = Path("/audiobooks/_unorganized/Roderick Gordon - Tunnels 05 - Spiral")
CHAPTER_RIP = [SPIRAL / f"Spiral - {i:03d}.mp3" for i in range(1, 26)]
PART_RIP = [SPIRAL / f"Spiral-Part{i:02d}.mp3" for i in range(1, 14)]


class DuplicateSetTests(unittest.TestCase):
    def test_two_numbered_sets_in_one_folder_are_detected(self):
        found = FIXER.find_duplicate_set_folders(CHAPTER_RIP + PART_RIP)
        self.assertIn(SPIRAL, found)
        self.assertIn("13", found[SPIRAL])
        self.assertIn("25", found[SPIRAL])

    def test_such_a_folder_is_not_grouped_and_becomes_one_item(self):
        files = CHAPTER_RIP + PART_RIP
        dup = FIXER.find_duplicate_set_folders(files)
        group_map = FIXER.build_multi_part_group_map(files, chapter_count_reader=lambda p: None)
        self.assertNotIn(SPIRAL, group_map)
        self.assertEqual(len(FIXER.build_processing_items(files, group_map, dup)), 1)

    def test_one_set_plus_a_couple_of_extras_is_not_a_duplicate(self):
        book = Path("/b/Some Book")
        files = [book / f"Some Book - Part {i:02d}.mp3" for i in range(1, 11)] + [book / "Bonus 1.mp3", book / "Bonus 2.mp3"]
        self.assertEqual(FIXER.find_duplicate_set_folders(files), {})

    def test_a_normal_single_set_folder_is_untouched(self):
        self.assertEqual(FIXER.find_duplicate_set_folders(CHAPTER_RIP), {})
