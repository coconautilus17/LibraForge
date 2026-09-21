import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "organizer_duplicate_warning", ROOT / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
)
ORGANIZER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)

FOLDER = Path("/in/Pocket Dungeon/Pocket Dungeon 2")
MERGED = FOLDER / "Eric Vall - [Pocket Dungeon-2] - Pocket Dungeon 2.m4b"
TARGET = Path("/lib/Eric Vall/Pocket Dungeon/Book 2")


def move(kind, source, target, audio_count=1, **extra):
    return {"kind": kind, "source": source, "target": target, "metadata": {"review_reasons": []},
            "audio_count": audio_count, **extra}


class PossibleDuplicateTests(unittest.TestCase):
    def test_skipped_merged_file_and_its_folder_both_name_the_paths(self):
        folder = move("folder", FOLDER, TARGET, audio_count=26)
        skipped = move("loose_file", MERGED, TARGET, skipped=True)
        self.assertEqual(ORGANIZER.annotate_possible_duplicates([folder], [skipped]), 1)
        file_reasons = skipped["metadata"]["review_reasons"]
        folder_reasons = folder["metadata"]["review_reasons"]
        self.assertEqual(len(file_reasons), 1)
        for text in (file_reasons[0], folder_reasons[0]):
            self.assertIn("possible duplicate", text)
            self.assertIn(str(MERGED), text)
        self.assertIn(str(FOLDER), file_reasons[0])
        self.assertIn(str(TARGET), file_reasons[0])
        self.assertIn("26 chapter file(s)", file_reasons[0])

    def test_planned_merged_file_becomes_a_skipped_review_item(self):
        folder = move("folder", FOLDER, TARGET, audio_count=3)
        loose = move("loose_file", MERGED, Path("/lib/Eric Vall/Pocket Dungeon 2/x.m4b"))
        planned, skipped = [folder, loose], []
        self.assertEqual(ORGANIZER.annotate_possible_duplicates(planned, skipped), 1)
        self.assertEqual(planned, [folder])
        self.assertEqual(skipped, [loose])
        self.assertTrue(loose["skipped"])
        self.assertIn("possible duplicate", loose["skip_reason"])
        self.assertIn(str(FOLDER), loose["skip_reason"])
        self.assertIn("possible duplicate", loose["metadata"]["review_reasons"][0])

    def test_unrelated_loose_file_and_lone_books_are_not_flagged(self):
        other = move("loose_file", Path("/in/Other/Book 1.m4b"), Path("/lib/A/Book 1"))
        folder = move("folder", FOLDER, TARGET, audio_count=26)
        self.assertEqual(ORGANIZER.annotate_possible_duplicates([folder, other], []), 0)
        self.assertEqual(folder["metadata"]["review_reasons"], [])
        self.assertEqual(other["metadata"]["review_reasons"], [])
        self.assertEqual(ORGANIZER.annotate_possible_duplicates([other], []), 0)

    def test_annotation_is_repeatable(self):
        folder = move("folder", FOLDER, TARGET, audio_count=26)
        skipped = move("loose_file", MERGED, TARGET, skipped=True)
        ORGANIZER.annotate_possible_duplicates([folder], [skipped])
        ORGANIZER.annotate_possible_duplicates([folder], [skipped])
        self.assertEqual(len(skipped["metadata"]["review_reasons"]), 1)
        self.assertEqual(len(folder["metadata"]["review_reasons"]), 1)


class ConflictPathsTests(unittest.TestCase):
    def test_conflict_reason_names_this_item_and_what_it_collides_with(self):
        text = ORGANIZER.conflict_reason_with_paths(
            "target folder already used by another book this run", MERGED, TARGET, FOLDER)
        self.assertIn("already used by another book", text)
        self.assertIn(str(MERGED), text)
        self.assertIn(f"already claimed by {FOLDER}", text)
        self.assertIn(str(TARGET), text)

    def test_conflict_without_a_known_owner_names_the_target(self):
        text = ORGANIZER.conflict_reason_with_paths("target already exists", MERGED, TARGET, None)
        self.assertIn(f"conflicts with: target {TARGET}", text)


if __name__ == "__main__":
    unittest.main()
