"""OGG multi-file grouping in the v5 fixer (and organizer ext-set sync).

Per-chapter .ogg dumps (e.g. "1301.ogg".."1900.ogg" for one book) were
discovered and tagged but never grouped, so each chapter counted as its own
book. .ogg now mirrors .opus: groupable and written via an m4b-tool sidecar.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
    sys.modules[spec.name] = module  # register so dataclasses resolve __module__
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_ogg", "scripts/audible-metadata-fixer-v5.py")
ORGANIZER = load_module("organizer_v3_13_ogg", "scripts/organize-audiobooks-by-metadata-v3_13.py")


def bare_number_ogg(folder: str, start: int, count: int) -> list[Path]:
    return [Path(f"{folder}/{n}.ogg") for n in range(start, start + count)]


class OggGroupingTests(unittest.TestCase):
    def test_ogg_is_a_full_peer_of_opus(self):
        self.assertIn(".ogg", FIXER.MULTI_PART_AUDIO_EXTENSIONS)
        self.assertIn(".ogg", FIXER.SIDECAR_OUTPUT_AUDIO_EXTENSIONS)
        # ffprobe can read chapter markers from OGG/MP3/OPUS too (e.g. ID3
        # CHAP/CTOC in podcast-style MP3s), so .ogg gets the same embedded-
        # chapter safety check as .m4a/.m4b/.mp4 (issue #140).
        self.assertIn(".ogg", FIXER.CHAPTER_METADATA_EXTENSIONS)

    def test_per_chapter_ogg_dump_groups_as_one_book(self):
        files = bare_number_ogg("/book/Shadow Slave Vol 9 (1301-1900)", 1301, 8)

        def reader(_path):
            return 0  # no embedded chapters -- the common case for real dumps

        groups = FIXER.build_multi_part_group_map(files, chapter_count_reader=reader)
        self.assertEqual(groups[files[0].parent], files)
        # The whole folder collapses to a single processing item.
        self.assertEqual(FIXER.build_processing_items(files, groups), [files[0]])

    def test_ogg_folder_with_complete_audiobook_is_not_grouped(self):
        # A mislabeled complete .ogg audiobook sitting alongside real
        # chapter-split parts must now be caught, same as .m4b (issue #140).
        complete = Path("/book/Mixed/Complete Audiobook.ogg")
        files = [Path("/book/Mixed/Chapter 1.ogg"), Path("/book/Mixed/Chapter 2.ogg"), complete]

        def reader(path):
            return 40 if path == complete else 0

        validation = FIXER.validate_multi_part_group_files(files, chapter_count_reader=reader)
        self.assertFalse(validation["safe"])
        self.assertTrue(any(u["file"] == str(complete) for u in validation["unsafe_files"]))

    def test_grouped_ogg_routes_to_m4b_tool_sidecar(self):
        rep = Path("/book/Shadow Slave Vol 9 (1301-1900)/1301.ogg")
        self.assertTrue(
            FIXER.should_write_json_sidecar(rep, {"group_search": {"applied": True}})
        )

    def test_single_ogg_writes_direct_tags_not_sidecar(self):
        # A lone .ogg (no group_search.applied) must write tags directly, not a
        # sidecar -- same rule as single .mp3. Only grouped multi-part books
        # get a sidecar so that book-level metadata is not stamped onto every
        # chapter file individually.
        self.assertFalse(FIXER.should_write_json_sidecar(Path("/b/only.ogg")))

    def test_organizer_recognizes_grouped_ogg_book(self):
        files = bare_number_ogg("/book/Shadow Slave Vol 9 (1301-1900)", 1301, 5)
        self.assertIn(".ogg", ORGANIZER.MULTI_PART_AUDIO_EXTENSIONS)
        with patch.object(ORGANIZER, "read_file_chapter_count", return_value=0):
            self.assertTrue(ORGANIZER.looks_like_multi_file_book(files))

    def test_fixer_and_organizer_multipart_sets_stay_in_sync(self):
        self.assertEqual(
            FIXER.MULTI_PART_AUDIO_EXTENSIONS,
            ORGANIZER.MULTI_PART_AUDIO_EXTENSIONS,
        )

    def test_fixer_and_organizer_chapter_metadata_sets_stay_in_sync(self):
        self.assertEqual(
            FIXER.CHAPTER_METADATA_EXTENSIONS,
            ORGANIZER.CHAPTER_METADATA_EXTENSIONS,
        )


class Mp3OpusChapterValidationTests(unittest.TestCase):
    """ffprobe can read embedded chapter markers from MP3/OPUS too (e.g. ID3
    CHAP/CTOC in podcast-style MP3s), so these formats get the same
    embedded-chapter safety check as .m4a/.m4b/.mp4 instead of being accepted
    unconditionally (issue #140)."""

    def test_mp3_and_opus_are_chapter_metadata_candidates(self):
        self.assertIn(".mp3", FIXER.CHAPTER_METADATA_EXTENSIONS)
        self.assertIn(".opus", FIXER.CHAPTER_METADATA_EXTENSIONS)
        self.assertIn(".mp3", ORGANIZER.CHAPTER_METADATA_EXTENSIONS)
        self.assertIn(".opus", ORGANIZER.CHAPTER_METADATA_EXTENSIONS)

    def test_mp3_folder_with_complete_audiobook_is_not_grouped(self):
        complete = Path("/book/Mixed Mp3/Complete Audiobook.mp3")
        files = [Path("/book/Mixed Mp3/Chapter 1.mp3"), Path("/book/Mixed Mp3/Chapter 2.mp3"), complete]

        def reader(path):
            return 40 if path == complete else 0

        validation = FIXER.validate_multi_part_group_files(files, chapter_count_reader=reader)
        self.assertFalse(validation["safe"])
        self.assertTrue(any(u["file"] == str(complete) for u in validation["unsafe_files"]))

    def test_real_mp3_chapter_split_still_groups(self):
        files = [Path("/book/Real Split/Chapter 1.mp3"), Path("/book/Real Split/Chapter 2.mp3")]
        validation = FIXER.validate_multi_part_group_files(files, chapter_count_reader=lambda _p: 0)
        self.assertTrue(validation["safe"])


if __name__ == "__main__":
    unittest.main()
