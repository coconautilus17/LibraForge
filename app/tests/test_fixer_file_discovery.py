"""Which files the Metadata Fixer considers, and in what order: supported
extensions, ignored system folders, temporary outputs, natural ordering, the
folder-ignore tokens and the user's skip patterns."""
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

FIXER = load_script("fixer_file_discovery", "audible-metadata-fixer-v5.py")


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

class IgnoreAndSkipPatternTests(unittest.TestCase):
    def test_a_token_in_the_middle_of_a_directory_name_does_not_match(self):
        self.assertEqual(FIXER.matches_ignored_folders(Path("/lib/my.thumbs/a.m4b"), ["thumbs"]), (False, ""))

    def test_no_pattern_blank_patterns_or_no_match_do_not_skip(self):
        clues = {"title": "Alpha"}
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, []), (False, ""))
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, ["", "  ", None]), (False, ""))
        self.assertEqual(FIXER.matches_skip_patterns(Path("/lib/a.m4b"), clues, ["zzz"]), (False, ""))


if __name__ == "__main__":
    unittest.main()
