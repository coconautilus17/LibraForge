import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class OrganizerMetadataInferenceTests(unittest.TestCase):
    def test_representative_filename_does_not_override_dashing_devil_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = root / "Dashing Devil" / "Dashing Devil 5 - Bold Beginnings"
            book_dir.mkdir(parents=True)
            audio = book_dir / "G.D. Brooks - Dashing Devil 5 - Bold Beginnings.m4b"
            audio.touch()
            marker = audio.with_name(audio.name + ".audible-metadata-fixer.json")
            marker.write_text(
                json.dumps(
                    {
                        "audible": {
                            "chosen_title": "Dashing Devil 5: Bold Beginnings",
                            "author": "G.D. Brooks",
                            "series": "Dashing Devil",
                            "sequence": "5",
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)

            metadata = ORGANIZER.infer_metadata(item, root, prefer_path_structure=True)

            self.assertEqual(metadata["title"], "Bold Beginnings")
            self.assertEqual(metadata["author"], "G.D. Brooks")
            self.assertEqual(metadata["book_number"], "005")
            self.assertEqual(
                ORGANIZER.build_book_folder_name(metadata),
                "Book 5 - Bold Beginnings",
            )

    def test_numeric_grouped_track_filename_still_supplies_author_and_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = root / "CS Pacat Dark Rise"
            book_dir.mkdir()
            audio = book_dir / "CS Pacat - Dark Rise - 001.mp3"
            audio.touch()
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)

            clues = ORGANIZER.path_clues(item, root)

            self.assertEqual(clues["author"], "CS Pacat")
            self.assertEqual(clues["title"], "Dark Rise")

    def test_ambiguous_folder_keeps_sidecar_title_author_and_series(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = (
                root
                / "Shane Walker - Corporate Warfare All Trades, Book 3"
            )
            book_dir.mkdir()
            audio = book_dir / "Chapter 01.m4b"
            audio.touch()
            marker = audio.with_name(audio.name + ".audible-metadata-fixer.json")
            marker.write_text(
                json.dumps(
                    {
                        "audible": {
                            "chosen_title": "Corporate Warfare",
                            "author": "Shane Walker",
                            "series": "All Trades",
                            "sequence": "3",
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)

            metadata = ORGANIZER.infer_metadata(
                item,
                root,
                prefer_path_structure=True,
            )

            self.assertEqual(metadata["title"], "Corporate Warfare")
            self.assertEqual(metadata["author"], "Shane Walker")
            self.assertEqual(metadata["series"], "All Trades")
            self.assertEqual(metadata["book_number"], "003")
            self.assertEqual(metadata["review_reasons"], [])

    def test_clean_author_series_volume_path_supplies_all_path_clues(self):
        root = Path("/library")
        book_dir = (
            root
            / "Isuna Hasekura"
            / "Spice and Wolf"
            / "Volume 7 - Side Colors"
        )
        audio = book_dir / "01 Chapter.opus"
        item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)

        clues = ORGANIZER.path_clues(item, root)

        self.assertEqual(clues["title"], "Side Colors")
        self.assertEqual(clues["parent_author"], "Isuna Hasekura")
        self.assertEqual(clues["series"], "Spice and Wolf")
        self.assertEqual(clues["book_number"], "007")
        self.assertEqual(clues["sequence_label"], "Volume")

    def test_missing_author_in_tags_is_flagged_when_inferred_from_path(self):
        root = Path("/library")
        book_dir = root / "Jane Doe - Standalone Story"
        audio = book_dir / "Chapter 01.mp3"
        item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)
        tag_metadata = {
            "title": "Standalone Story",
            "author": "Unknown Author",
            "series": "",
            "book_number": "",
            "sequence_label": "",
            "narrator": "",
            "source": "ffprobe",
        }

        with patch.object(ORGANIZER, "metadata_from_sidecar", return_value=None):
            with patch.object(ORGANIZER, "metadata_from_tags", return_value=tag_metadata):
                metadata = ORGANIZER.infer_metadata(item, root)

        self.assertEqual(metadata["author"], "Jane Doe")
        self.assertIn("author inferred from path", metadata["review_reasons"])

    def test_conflicting_book_number_is_flagged(self):
        root = Path("/library")
        book_dir = root / "Example Series, Book 2 - Second"
        audio = book_dir / "book.m4b"
        item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)
        tag_metadata = {
            "title": "Second",
            "author": "Jane Doe",
            "series": "Example Series",
            "book_number": "001",
            "sequence_label": "Book",
            "narrator": "",
            "source": "marker:test.json",
        }

        with patch.object(ORGANIZER, "metadata_from_sidecar", return_value=tag_metadata):
            metadata = ORGANIZER.infer_metadata(item, root)

        self.assertIn(
            "book number differs between metadata and path",
            metadata["review_reasons"],
        )

    def test_batch_author_correction_is_flagged(self):
        metadata = {
            "title": "Book Two",
            "author": "Example",
            "author_primary": "Example",
            "series": "Example Series",
            "review_reasons": [],
        }

        corrected = ORGANIZER.apply_run_author_correction(
            metadata,
            {ORGANIZER.normalize_series_key("Example Series"): "Jane Doe"},
        )

        self.assertEqual(corrected["author"], "Jane Doe")
        self.assertIn(
            "author inferred from other books in this run",
            corrected["review_reasons"],
        )


class OrganizerMultiFileTests(unittest.TestCase):
    def test_natural_audio_sort_orders_numeric_parts(self):
        paths = [Path("Chapter 10.m4a"), Path("Chapter 2.m4a"), Path("Chapter 1.m4a")]

        ordered = sorted(paths, key=ORGANIZER.natural_audio_sort_key)

        self.assertEqual(
            [path.name for path in ordered],
            ["Chapter 1.m4a", "Chapter 2.m4a", "Chapter 10.m4a"],
        )

    def test_low_chapter_count_named_m4a_parts_are_grouped(self):
        files = [Path("/book/Chapter 1.m4a"), Path("/book/Chapter 2.m4a")]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=2):
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_complete_chapterized_m4b_files_are_not_grouped(self):
        files = [Path("/book/Book 1.m4b"), Path("/book/Book 2.m4b")]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=20):
            self.assertFalse(ORGANIZER.looks_like_multi_file_book(files))

    def test_low_chapter_count_complete_m4b_files_are_not_grouped(self):
        files = [Path("/book/Book 1.m4b"), Path("/book/Book 2.m4b")]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=0):
            self.assertFalse(ORGANIZER.looks_like_multi_file_book(files))

    def test_low_chapter_count_named_m4b_parts_are_grouped(self):
        files = [
            Path("/book/Downtown Druid - Chapter 1.m4b"),
            Path("/book/Downtown Druid - Chapter 2.m4b"),
        ]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=1):
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_zero_padded_numeric_m4b_parts_are_grouped(self):
        files = [
            Path("/book/Example Book 3 - 01.m4b"),
            Path("/book/Example Book 3 - 02.m4b"),
            Path("/book/Example Book 3 - 03.m4b"),
            Path("/book/Example Book 3.m4b"),
        ]

        def chapter_count(path):
            return 30 if path.name == "Example Book 3.m4b" else 0

        with patch.object(ORGANIZER, "read_file_chapter_count", side_effect=chapter_count):
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_different_numeric_m4b_prefixes_are_not_grouped(self):
        files = [
            Path("/book/Example Book 1 - 01.m4b"),
            Path("/book/Example Book 2 - 02.m4b"),
        ]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=0):
            self.assertFalse(ORGANIZER.looks_like_multi_file_book(files))

    def test_unreadable_m4a_chapter_metadata_is_not_grouped(self):
        files = [Path("/book/Chapter 1.m4a"), Path("/book/Chapter 2.m4a")]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=None):
            self.assertFalse(ORGANIZER.looks_like_multi_file_book(files))

    def test_mp3_parts_do_not_require_chapter_probe(self):
        files = [Path("/book/1.mp3"), Path("/book/2.mp3")]

        with patch.object(ORGANIZER, "read_file_chapter_count") as chapter_probe:
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))
            chapter_probe.assert_not_called()

    def test_mixed_eligible_and_other_audio_formats_are_not_grouped(self):
        files = [Path("/book/Chapter 1.m4a"), Path("/book/Chapter 2.flac")]

        with patch.object(ORGANIZER, "read_file_chapter_count") as chapter_probe:
            self.assertFalse(ORGANIZER.looks_like_multi_file_book(files))
            chapter_probe.assert_not_called()

    def test_leading_ordinal_bare_space_mp3_parts_are_grouped(self):
        # Ported from the fixer's PR #154 fix: some release conventions (e.g.
        # Eric Vall's Pocket Dungeon rips) use a bare space, not punctuation,
        # between the zero-padded leading index and the rest of the name.
        files = [
            Path("/book/001 Eric Vall - Pocket Dungeon 2 - Opening Credits.mp3"),
            Path("/book/002 Eric Vall - Pocket Dungeon 2 - Chapter 1.mp3"),
            Path("/book/003 Eric Vall - Pocket Dungeon 2 - Chapter 2.mp3"),
        ]

        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=0):
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_leading_ordinal_group_map_excludes_merged_edition(self):
        # The exact Pocket Dungeon scenario: a leading-ordinal chapter split
        # plus a separately merged M4B whose source chapters were never
        # cleaned up. build_multi_part_group_map must isolate just the three
        # chapter parts -- the merged edition is a real, complete audiobook
        # (high chapter count) and must not be pulled into the group, but its
        # presence also must not block the parts from being recognized.
        folder = Path("/book")
        parts = [
            folder / "001 Eric Vall - Pocket Dungeon 2 - Opening Credits.mp3",
            folder / "002 Eric Vall - Pocket Dungeon 2 - Chapter 1.mp3",
            folder / "003 Eric Vall - Pocket Dungeon 2 - Chapter 2.mp3",
        ]
        merged = folder / "Eric Vall - [Pocket Dungeon-2] - Pocket Dungeon 2.m4b"

        def chapter_count(path):
            return 30 if path.suffix == ".m4b" else 0

        with patch.object(ORGANIZER, "read_file_chapter_count", side_effect=chapter_count):
            group_map = ORGANIZER.build_multi_part_group_map(parts + [merged])

        self.assertEqual(group_map.get(folder), sorted(parts, key=ORGANIZER.natural_audio_sort_key))

    def test_leading_ordinal_group_map_excludes_merged_edition_for_ogg(self):
        # Same shape, different formats -- proves the fix isn't mp3/m4b-specific
        # but follows CHAPTER_METADATA_EXTENSIONS/MULTI_PART_AUDIO_EXTENSIONS.
        folder = Path("/book")
        parts = [
            folder / "001 Author - Book Two - Opening Credits.ogg",
            folder / "002 Author - Book Two - Chapter 1.ogg",
            folder / "003 Author - Book Two - Chapter 2.ogg",
        ]
        merged = folder / "Author - Book Two (merged).m4a"

        def chapter_count(path):
            return 30 if path.suffix == ".m4a" else 0

        with patch.object(ORGANIZER, "read_file_chapter_count", side_effect=chapter_count):
            group_map = ORGANIZER.build_multi_part_group_map(parts + [merged])

        self.assertEqual(group_map.get(folder), sorted(parts, key=ORGANIZER.natural_audio_sort_key))

    def test_build_book_items_splits_group_from_merged_edition(self):
        # End-to-end: the recognized group becomes one "folder" BookItem, and
        # the separately merged edition sharing its folder becomes its own
        # loose_file item -- mirroring the fixer's build_processing_items,
        # instead of either sweeping them together or exploding every file.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = root / "Eric Vall - Pocket Dungeon 1-6 (64k)" / "Pocket Dungeon" / "Pocket Dungeon 2"
            book_dir.mkdir(parents=True)
            part_names = [
                "001 Eric Vall - Pocket Dungeon 2 - Opening Credits.mp3",
                "002 Eric Vall - Pocket Dungeon 2 - Chapter 1.mp3",
                "003 Eric Vall - Pocket Dungeon 2 - Chapter 2.mp3",
            ]
            for name in part_names:
                (book_dir / name).touch()
            merged = book_dir / "Eric Vall - [Pocket Dungeon-2] - Pocket Dungeon 2.m4b"
            merged.touch()

            def chapter_count(path):
                return 30 if path.suffix == ".m4b" else 0

            with patch.object(ORGANIZER, "read_file_chapter_count", side_effect=chapter_count):
                items = ORGANIZER.build_book_items(root, root)

        folder_items = [item for item in items if item.kind == "folder"]
        loose_items = [item for item in items if item.kind == "loose_file"]

        self.assertEqual(len(folder_items), 1)
        self.assertTrue(folder_items[0].partial_group)
        self.assertEqual(len(folder_items[0].audio_files), 3)
        self.assertEqual(folder_items[0].leftover_files, (merged,))

        self.assertEqual(len(loose_items), 1)
        self.assertEqual(loose_items[0].source_path, merged)

    def test_execute_partial_group_move_leaves_leftover_file_behind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book_dir = root / "Pocket Dungeon 2"
            book_dir.mkdir()
            parts = []
            for name in ["001 Opening Credits.mp3", "002 Chapter 1.mp3", "003 Chapter 2.mp3"]:
                path = book_dir / name
                path.touch()
                parts.append(path)
            merged = book_dir / "Pocket Dungeon 2.m4b"
            merged.touch()
            (book_dir / "libraforge.json").write_text("{}", encoding="utf-8")
            (book_dir / "cover.jpg").touch()

            target = root / "Author" / "Pocket Dungeon" / "Book 2"
            move = {
                "kind": "folder",
                "source": book_dir,
                "target": target,
                "companions": [],
                "partial_group": True,
                "leftover_files": [merged],
            }

            ORGANIZER.execute_planned_move(
                move, merge_existing_targets=False, remove_empty_dirs=False, root=root,
            )

            for path in parts:
                self.assertTrue((target / path.name).exists())
            self.assertTrue((target / "libraforge.json").exists())
            self.assertTrue((target / "cover.jpg").exists())

            self.assertTrue(merged.exists(), "leftover merged file must stay in the source folder")
            self.assertFalse((target / merged.name).exists())

    def test_marker_sequence_files_ported_from_fixer(self):
        files = [
            Path("/book/My Book - Part 1.m4b"),
            Path("/book/My Book - Part 2.m4b"),
            Path("/book/My Book - Part 3.m4b"),
        ]
        self.assertEqual(set(files), ORGANIZER.marker_sequence_files(files))


class OrganizerConflictDetectionTests(unittest.TestCase):
    """A recognized multi-part group and a separately merged single-file
    edition of the same book resolve to the identical destination directory.
    Neither file literally overwrites the other, but landing both there is a
    real duplicate-content conflict and must be surfaced, not silently
    resolved by moving one and nesting the other alongside it."""

    def _book_item(self, kind, source_path):
        return ORGANIZER.BookItem(kind, source_path, [source_path], source_path)

    def test_folder_move_conflicts_with_already_reserved_target_dir(self):
        target_dir = Path("/library/Author/Series/Book 2")
        item = self._book_item("folder", Path("/incoming/Book 2"))

        can_move, reason = ORGANIZER.plan_folder_move(
            item, target_dir, reserved_target_dirs={target_dir},
        )

        self.assertFalse(can_move)
        self.assertIn("already used by another book", reason)

    def test_loose_file_move_conflicts_with_already_reserved_target_dir(self):
        target_dir = Path("/library/Author/Series/Book 2")
        item = self._book_item(
            "loose_file", Path("/incoming/Author - [Book-2] - Book 2.m4b"),
        )

        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(
            item, target_dir, reserved_target_dirs={target_dir},
        )

        self.assertFalse(can_move)
        self.assertIsNone(target_path)
        self.assertIn("already used by another book", reason)

    def test_loose_file_move_succeeds_when_target_dir_not_reserved(self):
        target_dir = Path("/library/Author/Series/Book 2")
        item = self._book_item(
            "loose_file", Path("/incoming/Author - [Book-2] - Book 2.m4b"),
        )

        can_move, target_path, reason = ORGANIZER.plan_loose_file_move(
            item, target_dir, reserved_target_dirs=set(),
        )

        self.assertTrue(can_move)
        self.assertEqual(target_path, target_dir / item.source_path.name)
        self.assertEqual(reason, "")


class OrganizerPrintMoveTests(unittest.TestCase):
    """A skipped-review move's "target" is always the bare directory (planning
    never reaches plan_loose_file_move to append a filename), unlike an
    accepted loose_file move whose "target" is the full file path. print_move
    must not truncate the bare directory as if it were a file path -- that
    silently dropped the last path segment (e.g. "Book 2") for every skipped
    loose_file review, which is exactly what made the group-vs-merged-edition
    conflict look like it was landing on the wrong, unrelated directory."""

    def _capture(self, move):
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ORGANIZER.print_move(move)
        return buf.getvalue()

    def test_skipped_loose_file_review_shows_full_target_directory(self):
        move = {
            "kind": "loose_file",
            "source": Path("/incoming/Book.m4b"),
            "target": Path("/library/Author/Series/Book 2"),
            "metadata": {"title": "Book 2", "author": "Author"},
            "audio_count": 1,
            "structure": "skipped_conflict",
            "skipped": True,
        }

        output = self._capture(move)

        self.assertIn("/library/Author/Series/Book 2", output)
        self.assertNotIn("/library/Author/Series\n", output)

    def test_accepted_loose_file_move_shows_containing_directory(self):
        move = {
            "kind": "loose_file",
            "source": Path("/incoming/Book.m4b"),
            "target": Path("/library/Author/Series/Book 2/Book 2.m4b"),
            "metadata": {"title": "Book 2", "author": "Author"},
            "audio_count": 1,
            "structure": "new",
        }

        output = self._capture(move)

        self.assertIn("/library/Author/Series/Book 2\n", output)
        self.assertNotIn("Book 2.m4b\n", output)


class OrganizerLooseFilenameTests(unittest.TestCase):
    def test_release_junk_uses_clean_series_and_volume_filename(self):
        source = Path(
            "/incoming/Reborn as a Space Mercenary, Vol. 5 - "
            "vol_05 [2025] [ASIN.B012345678] [ENG].m4b"
        )
        target = Path(
            "/library/Ryuto/Reborn as a Space Mercenary/Vol. 5"
        )

        self.assertEqual(
            ORGANIZER.clean_loose_audio_filename(source, target),
            "Reborn as a Space Mercenary - Vol. 5.m4b",
        )

    def test_clean_filename_is_preserved(self):
        source = Path("/incoming/Bold Beginnings.m4b")
        target = Path(
            "/library/G.D. Brooks/Dashing Devil/Book 5 - Bold Beginnings"
        )

        self.assertEqual(
            ORGANIZER.clean_loose_audio_filename(source, target),
            source.name,
        )


if __name__ == "__main__":
    unittest.main()
