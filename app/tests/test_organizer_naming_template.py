import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_template", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class StraySeparatorCleanupTests(unittest.TestCase):
    def test_trailing_stray_dash_and_comma_from_empty_edge_tokens_are_trimmed(self):
        # {order} - {title},{edition} with title AND edition both empty
        # left "Book 1 - ," in real testing -- a real, ugly artifact, not
        # the intentionally-accepted "stray separator" tradeoff.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{order} - {title},{edition}/",
            {"order": "Book 1", "title": "", "edition": ""},
        )
        self.assertEqual(folders, ["Book 1"])

    def test_leading_stray_comma_from_empty_title_is_trimmed(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{asin}",
            {"author": "Author Name", "title": "", "asin": "B0TEST"},
        )
        self.assertEqual(filename, "B0TEST")

    def test_fully_separator_only_segment_is_not_stripped_to_empty(self):
        # A flagged-for-review segment that's literally just leftover
        # separators must never collapse to a true empty string -- Path
        # silently drops empty components, which would make a flagged item
        # vanish from its own directory level instead of staying visible.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{asin}/",
            {"author": "Author Name", "title": "", "asin": ""},
        )
        self.assertEqual(folders, ["Author Name", ","])
        self.assertEqual(len(reasons), 1)


class BareSingleTokenSegmentTests(unittest.TestCase):
    def test_empty_bare_token_segment_is_dropped(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series}/{title}/",
            {"author": "Author Name", "series": "", "title": "The Title"},
        )
        self.assertEqual(folders, ["Author Name", "The Title"])
        self.assertIsNone(filename)
        self.assertEqual(reasons, [])

    def test_nonempty_bare_token_segment_renders(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series}/",
            {"author": "Author Name", "series": "Series Name"},
        )
        self.assertEqual(folders, ["Author Name", "Series Name"])
        self.assertIsNone(filename)
        self.assertEqual(reasons, [])


class MultiTokenSegmentTests(unittest.TestCase):
    def test_all_empty_multi_token_segment_flags_for_review(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{asin}/",
            {"author": "Author Name", "title": "", "asin": ""},
        )
        self.assertEqual(folders, ["Author Name", ","])
        self.assertIsNone(filename)
        self.assertEqual(len(reasons), 1)
        self.assertIn("not enough data", reasons[0].lower())

    def test_partially_empty_multi_token_segment_renders_literally_no_flag(self):
        # Sanitization (added alongside this test) trims the trailing " - "
        # left by narrator being empty -- a nice side effect of generic
        # path-safety cleanup, not special-cased collapsing logic.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title} - {narrator}/",
            {"author": "Author Name", "title": "The Title", "narrator": ""},
        )
        self.assertEqual(folders, ["Author Name", "The Title"])
        self.assertEqual(reasons, [])


class LiteralOnlySegmentTests(unittest.TestCase):
    def test_pure_empty_literal_segment_is_dropped(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}//{title}/",
            {"author": "Author Name", "title": "The Title"},
        )
        self.assertEqual(folders, ["Author Name", "The Title"])
        self.assertEqual(reasons, [])

    def test_pure_nonempty_literal_segment_is_kept(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/Fixed Folder/{title}/",
            {"author": "Author Name", "title": "The Title"},
        )
        self.assertEqual(folders, ["Author Name", "Fixed Folder", "The Title"])


class FilenameSegmentTests(unittest.TestCase):
    def test_nonempty_filename_segment_used(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title}",
            {"author": "Author Name", "title": "The Title"},
        )
        self.assertEqual(folders, ["Author Name"])
        self.assertEqual(filename, "The Title")
        self.assertEqual(reasons, [])

    def test_empty_bare_filename_token_falls_back_to_none(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title}",
            {"author": "Author Name", "title": ""},
        )
        self.assertIsNone(filename)
        self.assertEqual(reasons, [])

    def test_empty_multi_token_filename_falls_back_to_none_and_flags(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{asin}",
            {"author": "Author Name", "title": "", "asin": ""},
        )
        self.assertIsNone(filename)
        self.assertEqual(len(reasons), 1)


class UnknownTokenTests(unittest.TestCase):
    def test_unknown_token_raises(self):
        with self.assertRaises(ORGANIZER.UnknownNamingTokenError) as ctx:
            ORGANIZER.render_naming_template(
                "{author}/{bogus}/",
                {"author": "Author Name"},
            )
        self.assertEqual(ctx.exception.token, "bogus")


if __name__ == "__main__":
    unittest.main()
