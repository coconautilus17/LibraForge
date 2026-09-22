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
FOLDER2 = Path("/in/Pocket Dungeon/Pocket Dungeon 3")
MERGED2 = FOLDER2 / "Eric Vall - [Pocket Dungeon-3] - Pocket Dungeon 3.m4b"
TARGET2 = Path("/lib/Eric Vall/Pocket Dungeon/Book 3")


def move(kind, source, target, audio_count=1, **extra):
    return {"kind": kind, "source": source, "target": target, "metadata": {"review_reasons": []},
            "audio_count": audio_count, **extra}


def detail_map(metadata):
    return {entry["label"]: entry["value"] for entry in metadata.get("review_details", [])}


class PossibleDuplicateTests(unittest.TestCase):
    def test_skipped_merged_file_and_its_folder_share_one_reason_with_the_paths_as_details(self):
        folder = move("folder", FOLDER, TARGET, audio_count=26)
        skipped = move("loose_file", MERGED, TARGET, skipped=True)
        self.assertEqual(ORGANIZER.annotate_possible_duplicates([folder], [skipped]), 1)
        file_reasons = skipped["metadata"]["review_reasons"]
        folder_reasons = folder["metadata"]["review_reasons"]
        self.assertEqual(file_reasons, [ORGANIZER.POSSIBLE_DUPLICATE_REASON])
        self.assertEqual(folder_reasons, [ORGANIZER.POSSIBLE_DUPLICATE_REASON])
        file_details = detail_map(skipped["metadata"])
        self.assertEqual(file_details["Chapter folder"], str(FOLDER))
        self.assertEqual(file_details["Would land in"], str(TARGET))
        folder_details = detail_map(folder["metadata"])
        merged_key = next(k for k in folder_details if k.startswith("Merged file"))
        self.assertIn("26 chapter files", merged_key)
        self.assertEqual(folder_details[merged_key], str(MERGED))

    def test_two_different_duplicate_books_get_the_identical_review_reason(self):
        # The reason string is what the report groups and filters by -- it must
        # be identical across unrelated books, unlike the paths (which differ
        # and live in review_details instead).
        folder_a = move("folder", FOLDER, TARGET, audio_count=26)
        skipped_a = move("loose_file", MERGED, TARGET, skipped=True)
        folder_b = move("folder", FOLDER2, TARGET2, audio_count=23)
        skipped_b = move("loose_file", MERGED2, TARGET2, skipped=True)
        ORGANIZER.annotate_possible_duplicates([folder_a, folder_b], [skipped_a, skipped_b])
        reasons = {
            skipped_a["metadata"]["review_reasons"][0],
            skipped_b["metadata"]["review_reasons"][0],
            folder_a["metadata"]["review_reasons"][0],
            folder_b["metadata"]["review_reasons"][0],
        }
        self.assertEqual(reasons, {ORGANIZER.POSSIBLE_DUPLICATE_REASON})
        # But the paths in review_details are book-specific.
        self.assertNotEqual(detail_map(skipped_a["metadata"]), detail_map(skipped_b["metadata"]))

    def test_planned_merged_file_becomes_a_skipped_review_item(self):
        folder = move("folder", FOLDER, TARGET, audio_count=3)
        loose = move("loose_file", MERGED, Path("/lib/Eric Vall/Pocket Dungeon 2/x.m4b"))
        planned, skipped = [folder, loose], []
        self.assertEqual(ORGANIZER.annotate_possible_duplicates(planned, skipped), 1)
        self.assertEqual(planned, [folder])
        self.assertEqual(skipped, [loose])
        self.assertTrue(loose["skipped"])
        self.assertEqual(loose["skip_reason"], "skipped: possible duplicate of the chapter files")
        self.assertEqual(loose["metadata"]["review_reasons"], [ORGANIZER.POSSIBLE_DUPLICATE_REASON])

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
        self.assertEqual(len(skipped["metadata"]["review_details"]), 2)


class ConflictReviewDetailsTests(unittest.TestCase):
    def test_conflict_details_name_the_owner_and_the_target(self):
        details = ORGANIZER.conflict_review_details(TARGET, FOLDER)
        self.assertEqual(details, [
            {"label": "Already claimed by", "value": str(FOLDER)},
            {"label": "Would land in", "value": str(TARGET)},
        ])

    def test_conflict_without_a_known_owner_only_names_the_target(self):
        details = ORGANIZER.conflict_review_details(TARGET, None)
        self.assertEqual(details, [{"label": "Would land in", "value": str(TARGET)}])

    def test_conflict_reason_itself_stays_short_and_identical_across_books(self):
        # make_skipped_review_move is what the real conflict call sites use.
        item = ORGANIZER.BookItem("loose_file", MERGED, [MERGED], MERGED)
        a = ORGANIZER.make_skipped_review_move(
            item=item, metadata={}, target=TARGET,
            reason="skipped conflict: target folder already used by another book this run",
            structure="skipped_conflict", review_details=ORGANIZER.conflict_review_details(TARGET, FOLDER),
        )
        item2 = ORGANIZER.BookItem("loose_file", MERGED2, [MERGED2], MERGED2)
        b = ORGANIZER.make_skipped_review_move(
            item=item2, metadata={}, target=TARGET2,
            reason="skipped conflict: target folder already used by another book this run",
            structure="skipped_conflict", review_details=ORGANIZER.conflict_review_details(TARGET2, FOLDER2),
        )
        self.assertEqual(a["metadata"]["review_reasons"], b["metadata"]["review_reasons"])
        self.assertNotEqual(a["metadata"]["review_details"], b["metadata"]["review_details"])


if __name__ == "__main__":
    unittest.main()
