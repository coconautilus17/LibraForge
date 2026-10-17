"""Which files the Metadata Fixer considers, and in what order: supported
extensions, ignored system folders, temporary outputs, natural ordering, the
folder-ignore tokens and the user's skip patterns."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_file_discovery", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


class SupportedFileTests(unittest.TestCase):
    def test_audio_extensions_are_supported_case_insensitively(self):
        for name in ("a.m4b", "a.M4A", "a.mp4", "a.mp3", "a.MP3", "a.ogg", "a.opus", "a.flac"):
            with self.subTest(name=name):
                self.assertTrue(FIXER.is_supported_audio_file(Path("/lib/Book") / name), name)

    def test_other_extensions_are_not(self):
        for name in ("a.txt", "a.jpg", "a.json", "a", "a.m4b.bak"):
            with self.subTest(name=name):
                self.assertFalse(FIXER.is_supported_audio_file(Path("/lib/Book") / name), name)

    def test_system_folders_hide_their_files_at_any_depth_case_insensitively(self):
        for folder in ("#recycle", "@eaDir", "@EADIR"):
            with self.subTest(folder=folder):
                self.assertTrue(FIXER.path_is_ignored(Path("/lib") / folder / "Book" / "a.m4b"))
                self.assertFalse(FIXER.is_supported_audio_file(Path("/lib") / folder / "Book" / "a.m4b"))
        self.assertFalse(FIXER.path_is_ignored(Path("/lib/Book/a.m4b")))

    def test_a_folder_that_merely_contains_an_ignored_word_is_not_ignored(self):
        self.assertFalse(FIXER.path_is_ignored(Path("/lib/my #recycle bin/a.m4b")))

    def test_the_fixers_own_temporary_outputs_are_not_inputs(self):
        for name in ("Book.metadata-fixed.m4b", "Book.metadata-restored.mp3", "BOOK.METADATA-FIXED.m4b"):
            with self.subTest(name=name):
                self.assertTrue(FIXER.is_temporary_output_file(Path(name)))
                self.assertFalse(FIXER.is_supported_audio_file(Path("/lib") / name))
        self.assertFalse(FIXER.is_temporary_output_file(Path("Book.m4b")))

    def test_the_file_type_is_the_lower_cased_extension_or_unknown(self):
        self.assertEqual(FIXER.get_file_type(Path("a.M4B")), "m4b")
        self.assertEqual(FIXER.get_file_type(Path("a")), "unknown")


class NaturalSortTests(unittest.TestCase):
    def test_numbers_inside_names_compare_numerically(self):
        names = ["Chapter 10.mp3", "Chapter 2.mp3", "chapter 1.mp3", "Chapter 21.mp3"]
        ordered = sorted((Path(n) for n in names), key=FIXER.natural_audio_sort_key)
        self.assertEqual([p.name for p in ordered], ["chapter 1.mp3", "Chapter 2.mp3", "Chapter 10.mp3", "Chapter 21.mp3"])

    def test_the_key_separates_numeric_and_text_parts(self):
        self.assertEqual(FIXER.natural_audio_sort_key(Path("A12b.mp3")),
                         [(1, "a"), (0, 12), (1, "b.mp"), (0, 3), (1, "")])

    def test_plain_names_sort_alphabetically_and_case_insensitively(self):
        ordered = sorted((Path(n) for n in ("b.mp3", "A.mp3", "c.mp3")), key=FIXER.natural_audio_sort_key)
        self.assertEqual([p.name for p in ordered], ["A.mp3", "b.mp3", "c.mp3"])


class FindAudioFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ("A/b2.m4b", "A/b10.m4b", "A/cover.jpg", "B/c.mp3", "#recycle/x.m4b", "A/x.metadata-fixed.m4b"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_supported_non_ignored_non_temporary_audio_files_are_found_in_sorted_order(self):
        got = FIXER.find_audio_files(self.root)
        self.assertEqual([p.relative_to(self.root).as_posix() for p in got], ["A/b10.m4b", "A/b2.m4b", "B/c.mp3"])

    def test_progress_reports_entries_and_files_found_and_ends_with_the_root(self):
        calls = []
        FIXER.find_audio_files(self.root, lambda entries, found, slowest, where: calls.append((entries, found, where)))
        self.assertEqual(calls[0][0], 1)                       # reported on the very first entry
        last_entries, last_found, last_where = calls[-1]
        self.assertEqual((last_found, last_where), (3, self.root))
        self.assertGreaterEqual(last_entries, 9)

    def test_a_single_supported_file_is_returned_as_is_with_one_progress_report(self):
        calls = []
        target = self.root / "B" / "c.mp3"
        got = FIXER.collect_audio_files(target, lambda *args: calls.append(args))
        self.assertEqual(got, [target])
        self.assertEqual(calls, [(1, 1, 0.0, target.parent)])

    def test_a_single_unsupported_file_gives_nothing_and_no_progress(self):
        calls = []
        got = FIXER.collect_audio_files(self.root / "A" / "cover.jpg", lambda *args: calls.append(args))
        self.assertEqual((got, calls), ([], []))

    def test_a_folder_is_walked(self):
        self.assertEqual(len(FIXER.collect_audio_files(self.root)), 3)


class IgnoreAndSkipPatternTests(unittest.TestCase):
    def test_ignore_tokens_match_directory_prefixes_case_insensitively_and_report_the_token(self):
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/.thumbs/a.m4b"), ["."]), (True, "."))
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/@eaDir/a.m4b"), ["@EADIR"]), (True, "@EADIR"))
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/_unorganized/x/a.m4b"), ["#", "_un"]), (True, "_un"))

    def test_the_file_name_itself_never_matches(self):
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/Book/.hidden.m4b"), ["."]), (False, ""))

    def test_a_token_in_the_middle_of_a_directory_name_does_not_match(self):
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/my.thumbs/a.m4b"), ["thumbs"]), (False, ""))

    def test_blank_tokens_and_empty_lists_never_match(self):
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/a/b.m4b"), []), (False, ""))
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/a/b.m4b"), ["", "  ", None]), (False, ""))

    def test_skip_patterns_are_substrings_of_the_path_or_the_local_metadata_fields(self):
        clues = {"raw_title": "Raw", "title": "Casual Farming 3", "series": "S", "author": "Zed", "narrator": "Roe"}
        path = Path("/lib/Book/a.m4b")
        for pattern in ("casual farming", "book/a", "ZED", "roe", " S ", "raw"):
            with self.subTest(pattern=pattern):
                got = FIXER.matches_skip_patterns(path, clues, [pattern])
                self.assertTrue(got[0], pattern)
                self.assertEqual(got[1], pattern)

    def test_the_first_matching_pattern_is_reported(self):
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), {"title": "Alpha Beta"}, ["zzz", "beta", "alpha"]), (True, "beta"))

    def test_no_pattern_blank_patterns_or_no_match_do_not_skip(self):
        clues = {"title": "Alpha"}
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, []), (False, ""))
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, ["", "  ", None]), (False, ""))
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, ["zzz"]), (False, ""))


if __name__ == "__main__":
    unittest.main()
