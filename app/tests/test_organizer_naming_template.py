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


class NonCoreTokensExcludedFromSignificanceTests(unittest.TestCase):
    """Only the "core" identity tokens (author, series, title, order,
    number) count toward the "2+ tokens all empty -> flag for review" rule.
    Everything else (narrator, publisher, year, asin, edition) is
    decoration -- a book can legitimately have no known narrator/publisher/
    year/ASIN/edition without that being a data-quality problem worth
    flagging. A segment where a non-core token is the only *other* token
    besides one core field behaves as if that field were alone --
    collapsing silently when empty, exactly like a bare {series} already
    does, rather than being treated as a 2-token segment.
    """

    def test_series_and_edition_both_empty_collapses_silently_not_flagged(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series} [{edition}]/",
            {"author": "Author Name", "series": "", "edition": ""},
        )
        self.assertEqual(folders, ["Author Name"])
        self.assertEqual(reasons, [])

    def test_series_present_edition_empty_collapses_brackets(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series} [{edition}]/",
            {"author": "Author Name", "series": "Dao of Magic", "edition": ""},
        )
        self.assertEqual(folders, ["Author Name", "Dao of Magic"])
        self.assertEqual(reasons, [])

    def test_series_empty_edition_present_keeps_edition(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series} [{edition}]/",
            {"author": "Author Name", "series": "", "edition": "GraphicAudio"},
        )
        self.assertEqual(folders, ["Author Name", "[GraphicAudio]"])
        self.assertEqual(reasons, [])

    def test_title_and_asin_both_empty_collapses_silently_not_flagged(self):
        # asin is non-core now too: {title},{asin} with title empty behaves
        # like a bare {title} would (silently collapses), not a 2-token
        # all-empty segment.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{asin}/",
            {"author": "Author Name", "title": "", "asin": ""},
        )
        self.assertEqual(folders, ["Author Name"])
        self.assertEqual(reasons, [])

    def test_publisher_year_narrator_all_excluded(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{publisher},{year},{narrator}/",
            {"author": "Author Name", "publisher": "", "year": "", "narrator": ""},
        )
        self.assertEqual(folders, ["Author Name"])
        self.assertEqual(reasons, [])

    def test_two_core_tokens_both_empty_still_flags_review(self):
        # Core tokens are unaffected by the exclusion -- genuinely
        # insufficient data still gets flagged, not silently guessed.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{series} [{edition}]/",
            {"author": "Author Name", "title": "", "series": "", "edition": ""},
        )
        self.assertEqual(len(reasons), 1)


class EmptyBracketCollapseTests(unittest.TestCase):
    def test_empty_square_brackets_removed(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{series} [{edition}]/",
            {"series": "Dao of Magic", "edition": ""},
        )
        self.assertEqual(folders, ["Dao of Magic"])

    def test_empty_parens_removed(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{series} ({edition})/",
            {"series": "Dao of Magic", "edition": ""},
        )
        self.assertEqual(folders, ["Dao of Magic"])

    def test_nonempty_brackets_kept(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{series} [{edition}]/",
            {"series": "Mistborn", "edition": "GraphicAudio"},
        )
        self.assertEqual(folders, ["Mistborn [GraphicAudio]"])

    def test_filename_that_collapses_to_empty_via_brackets_falls_back_to_none(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/[{edition}]",
            {"author": "Author Name", "edition": ""},
        )
        self.assertIsNone(filename)

    def test_two_bracket_wrapped_empty_tokens_stays_flagged_not_silently_dropped(self):
        # [{title}][{series}] both empty (both core tokens): bracket
        # removal alone empties the whole segment before the trailing
        # strip even runs. The flagged segment must still show up as
        # *something* non-empty, not vanish.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/[{title}][{series}]/",
            {"author": "Author Name", "title": "", "series": ""},
        )
        self.assertEqual(len(folders), 2)
        self.assertTrue(folders[1])
        self.assertEqual(len(reasons), 1)


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
        # {title},{series} are both core tokens, so both-empty flags.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{series}/",
            {"author": "Author Name", "title": "", "series": ""},
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
        # {title},{series} are both core tokens, so both-empty flags.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{series}/",
            {"author": "Author Name", "title": "", "series": ""},
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
        # {title},{series} are both core tokens, so both-empty flags.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title},{series}",
            {"author": "Author Name", "title": "", "series": ""},
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


class PathTraversalSafetyTests(unittest.TestCase):
    """A rendered segment must never reduce to a path-navigation component
    (".", "..") -- that would escape or self-reference destination_root when
    joined. The hardcoded default path is already safe (it substitutes
    "Unknown Title"/"Unknown Series"); the flat-token renderer must be too.
    """

    def test_dotdot_segment_is_treated_as_empty(self):
        self.assertTrue(ORGANIZER._naming_segment_is_effectively_empty(".."))

    def test_single_dot_segment_is_treated_as_empty(self):
        self.assertTrue(ORGANIZER._naming_segment_is_effectively_empty("."))

    def test_sanitize_never_emits_dotdot(self):
        self.assertNotIn(ORGANIZER._sanitize_naming_segment(".."), {".", ".."})

    def test_sanitize_never_emits_single_dot(self):
        self.assertNotIn(ORGANIZER._sanitize_naming_segment("."), {".", ".."})

    def test_dotdot_single_token_segment_collapses(self):
        # A title of ".." must drop its folder level, not build "/root/..".
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{title}/",
            {"author": "Author Name", "title": ".."},
        )
        self.assertEqual(folders, ["Author Name"])
        self.assertNotIn("..", folders)

    def test_literal_dotdot_segment_collapses(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/../{title}/",
            {"author": "Author Name", "title": "Hi"},
        )
        self.assertEqual(folders, ["Author Name", "Hi"])
        self.assertNotIn("..", folders)

    def test_build_target_dir_never_escapes_root(self):
        result = ORGANIZER.build_target_dir_for_template(
            Path("/audiobooks"), {"author": "Bob", "title": ".."}, "{title}/"
        )
        self.assertNotIn("..", result.target_dir.parts)


class NumberTokenRedundancyTests(unittest.TestCase):
    """Title-redundancy collapse must apply within a segment that uses
    {number} + {title}, not only {order} + {title} -- {number} is the
    alternative numbering token, so "5 - Book 5" is just as redundant as
    "Book 5 - Book 5".
    """

    def test_number_and_title_segment_collapses_redundant_title(self):
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series}/{number} - {title}/",
            {"author": "A", "series": "S", "number": "5", "title": "Book 5"},
            title_redundant_with_order=True,
        )
        self.assertEqual(folders[-1], "5")

    def test_standalone_title_with_number_elsewhere_keeps_full_title(self):
        # Per-segment: a filename segment with only {title} (no {number})
        # keeps the full title even when redundant.
        folders, filename, reasons = ORGANIZER.render_naming_template(
            "{author}/{series}/{number} - {title}/{title}",
            {"author": "A", "series": "S", "number": "5", "title": "Book 5"},
            title_redundant_with_order=True,
        )
        self.assertEqual(filename, "Book 5")


class OriginalAndFilenameTokenTests(unittest.TestCase):
    """{original} = the audio file's current stem verbatim (only mandatory
    illegal-char sanitization); {filename} = that stem run through the
    existing loose-file noise cleanup. Both are filename-segment tokens that
    support additive append (e.g. `{original} [{asin}]`), and both are empty
    when the filename part doesn't apply (multi-file books).
    """

    def _render(self, template, tokens, **kw):
        base = {"author": "A", "series": "", "title": "", "asin": "", "original": "", "filename": ""}
        base.update(tokens)
        return ORGANIZER.render_naming_template(template, base, **kw)

    def test_original_is_raw_stem(self):
        _f, filename, _r = self._render(
            "{author}/{original}",
            {},
            source_file=Path("/lib/messy, book 3 - auth - narr.m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(filename, "messy, book 3 - auth - narr")

    def test_original_append_asin_is_additive(self):
        _f, filename, _r = self._render(
            "{author}/{original} [{asin}]",
            {"asin": "B0ABC12345"},
            source_file=Path("/lib/messy, book 3 - auth - narr.m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(filename, "messy, book 3 - auth - narr [B0ABC12345]")

    def test_filename_keeps_a_clean_name(self):
        _f, filename, _r = self._render(
            "{author}/{filename}",
            {},
            source_file=Path("/lib/A Perfectly Clean Title.m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(filename, "A Perfectly Clean Title")

    def test_filename_strips_bracketed_asin_junk(self):
        # A junky name goes through cleanup, which drops the bracketed asin.
        _f, filename, _r = self._render(
            "{author}/{title}/{filename}",
            {"title": "Great Title"},
            source_file=Path("/lib/Great Title [ASIN.B0ABC12345] [2025] [128].m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertNotIn("B0ABC12345", filename or "")

    def test_tokens_empty_when_filename_does_not_apply(self):
        _f, filename, _r = self._render(
            "{author}/{original}",
            {},
            source_file=Path("/lib/messy.m4b"),
            destination_root=Path("/audiobooks"),
            filename_applies=False,
        )
        self.assertIsNone(filename)

    def test_filename_noisy_source_falls_back_to_metadata_title_not_folder(self):
        # A redundant title collapses the folder leaf to "Book 5", but when the
        # source name is too noisy to keep, {filename} must fall back to the
        # metadata TITLE ("The Dao of Magic V"), not the collapsed folder leaf
        # ("Dao of Magic - Book 5") -- the descriptive title must survive.
        _f, filename, _r = self._render(
            "{author}/{series} [{edition}]/{order} - {title}/{filename}",
            {"series": "Dao of Magic", "order": "Book 5", "title": "The Dao of Magic V", "edition": ""},
            title_redundant_with_order=True,
            source_file=Path("/lib/The Dao of Magic V - vol_05 [ENG] {Narr}.m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(filename, "The Dao of Magic V")

    def test_filename_noisy_source_no_title_still_falls_back_to_folder(self):
        # With no usable metadata title, the folder-derived cleanup remains the
        # secondary fallback (source path stays the last resort inside it).
        _f, filename, _r = self._render(
            "{author}/{title}/{filename}",
            {"title": "Great Title"},
            source_file=Path("/lib/random junk [128] [2025].m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(filename, "Great Title")

    def test_tokens_render_empty_in_folder_segment(self):
        # {original}/{filename} are filename-only; in a folder level they are
        # empty (single-token segment collapses).
        folders, _filename, _r = self._render(
            "{author}/{original}/{title}/",
            {"title": "T"},
            source_file=Path("/lib/messy.m4b"),
            destination_root=Path("/audiobooks"),
        )
        self.assertEqual(folders, ["A", "T"])


class AsinMismatchFlagTests(unittest.TestCase):
    """When a filename template writes {asin} but the source name/path
    already carries a *different* identifier, that's a probable metadata
    mismatch worth surfacing -- but never a reason to skip the move. Same or
    absent identifiers raise nothing; the check only runs when the filename
    actually uses {asin}.
    """

    def _render(self, template, asin, source_file):
        base = {"author": "A", "series": "", "title": "T", "asin": asin, "original": "", "filename": ""}
        return ORGANIZER.render_naming_template(
            template, base, source_file=source_file, destination_root=Path("/audiobooks")
        )

    def test_different_asin_in_name_flags_but_renders(self):
        _f, filename, reasons = self._render(
            "{author}/{original} [{asin}]", "B0ABCDEFGH", Path("/lib/Some Title [B0ZZZZZZZZ].m4b")
        )
        self.assertTrue(any("differs" in r for r in reasons))
        self.assertIsNotNone(filename)

    def test_same_asin_in_name_does_not_flag(self):
        _f, _filename, reasons = self._render(
            "{author}/{original} [{asin}]", "B0ABCDEFGH", Path("/lib/Some Title [B0ABCDEFGH].m4b")
        )
        self.assertEqual(reasons, [])

    def test_no_identifier_in_name_does_not_flag(self):
        _f, _filename, reasons = self._render(
            "{author}/{original} [{asin}]", "B0ABCDEFGH", Path("/lib/A Perfectly Clean Title.m4b")
        )
        self.assertEqual(reasons, [])

    def test_no_flag_when_template_has_no_asin(self):
        _f, _filename, reasons = self._render(
            "{author}/{original}", "B0ABCDEFGH", Path("/lib/Some Title [B0ZZZZZZZZ].m4b")
        )
        self.assertEqual(reasons, [])

    def test_isbn_style_mismatch_is_detected(self):
        # Canonical is a 10-digit ISBN; the name carries a different B0 asin.
        _f, _filename, reasons = self._render(
            "{author}/{original} [{asin}]", "1774243989", Path("/lib/Some Title [B0ZZZZZZZZ].m4b")
        )
        self.assertTrue(any("differs" in r for r in reasons))

    def test_identifier_elsewhere_in_source_path_is_checked(self):
        _f, _filename, reasons = self._render(
            "{author}/{original} [{asin}]", "B0ABCDEFGH", Path("/lib/Author [B0ZZZZZZZZ]/book.m4b")
        )
        self.assertTrue(any("differs" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
