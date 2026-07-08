"""Tests for read_current_book_metadata and its wiring into build_search_context.

Established this session: comparison-card "local"/"current" display must never
be built from `clues` fields, because several of those (title, series, author,
book_number) pass through path/folder-name overrides that exist only to help
the matcher find the right book -- they do not describe what is actually
embedded in the file. `clues["current"]`, built by read_current_book_metadata
from a genuine tag probe, is the one true source for comparison-card display.
See docs/design/comparison-card-data-source.md.
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
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_current_metadata", "scripts/audible-metadata-fixer-v5.py")

from app.fixer.clues import read_current_book_metadata  # noqa: E402


class ReadCurrentBookMetadataTests(unittest.TestCase):
    def test_extracts_every_field_from_mp4_style_tags(self):
        # Keys as ffprobe actually exposes MP4 freeform atoms (verified against
        # a real M4B: subtitle/asin/mvnm/mvin/isbn/publisher all come through
        # under their plain lowercase names, not "----:com.apple.iTunes:...").
        tags = {
            "title": "Soul Harvest",
            "artist": "Sarah Hawke",
            "composer": "Richard Brock",
            "grouping": "Dread Knight",
            "genre": "Fantasy",
            "date": "2024",
            "subtitle": "A Post-Apocalyptic Fantasy",
            "isbn": "9781234567890",
            "asin": "b0d463bwnq",
            "publisher": "Royal Guard Publishing LLC",
            "comment": "An ancient weapon.",
            "track": "2",
        }
        current = read_current_book_metadata(tags)
        self.assertEqual(current["title"], "Soul Harvest")
        self.assertEqual(current["author"], "Sarah Hawke")
        self.assertEqual(current["narrator"], "Richard Brock")
        self.assertEqual(current["series"], "Dread Knight")
        self.assertEqual(current["genre"], "Fantasy")
        self.assertEqual(current["year"], "2024")
        self.assertEqual(current["subtitle"], "A Post-Apocalyptic Fantasy")
        self.assertEqual(current["isbn"], "9781234567890")
        self.assertEqual(current["asin"], "B0D463BWNQ")
        self.assertEqual(current["publisher"], "Royal Guard Publishing LLC")
        self.assertEqual(current["summary"], "An ancient weapon.")
        self.assertEqual(current["sequence"], "2")

    def test_subtitle_from_tit3_for_mp3_style_tags(self):
        # ffprobe does not friendly-name ID3 TIT3 the way it does the MP4
        # freeform "subtitle" atom -- it comes through as the raw lowercased
        # frame id "tit3". Confirmed against a real MP3 in this session.
        tags = {"title": "Anarchism", "tit3": "An Audio Guide"}
        current = read_current_book_metadata(tags)
        self.assertEqual(current["subtitle"], "An Audio Guide")

    def test_missing_fields_are_blank_not_guessed(self):
        current = read_current_book_metadata({"title": "Solo Book"})
        self.assertEqual(current["subtitle"], "")
        self.assertEqual(current["genre"], "")
        self.assertEqual(current["isbn"], "")
        self.assertEqual(current["asin"], "")
        self.assertEqual(current["publisher"], "")
        self.assertEqual(current["summary"], "")
        self.assertEqual(current["series"], "")

    def test_series_never_falls_back_to_album(self):
        # album very often just echoes the title -- only a dedicated
        # grouping/series tag counts as real series data for display.
        tags = {"title": "Pocket Dungeon 4", "album": "Pocket Dungeon 4"}
        current = read_current_book_metadata(tags)
        self.assertEqual(current["series"], "")

    def test_year_reads_date_or_year_key(self):
        self.assertEqual(read_current_book_metadata({"year": "2020"})["year"], "2020")
        self.assertEqual(read_current_book_metadata({"date": "2021"})["year"], "2021")

    def test_grouped_generic_title_falls_back_to_album(self):
        # Real-world case: a multi-file rip's first (by natural sort) file is
        # a bonus "Opening Credits" track. Its own "title" tag names the
        # track, not the book -- "album" is the book's actual name.
        tags = {"title": "Opening Credits", "album": "Pocket Dungeon 3", "track": "1"}
        current = read_current_book_metadata(tags, is_grouped=True)
        self.assertEqual(current["title"], "Pocket Dungeon 3")

    def test_ungrouped_generic_title_still_falls_back_to_album(self):
        # The album fallback isn't grouping-specific -- it's just picking the
        # more useful of two tags on the same file, regardless of is_grouped.
        tags = {"title": "Chapter 1", "album": "Solo Book"}
        current = read_current_book_metadata(tags)
        self.assertEqual(current["title"], "Solo Book")

    def test_grouped_track_number_never_becomes_sequence(self):
        # The representative file's track number is its chapter position
        # (e.g. "1" for the first track), not the book's series sequence --
        # keeping it produces a plausible-looking but meaningless number.
        tags = {"title": "Opening Credits", "album": "Pocket Dungeon 3", "track": "1"}
        current = read_current_book_metadata(tags, is_grouped=True)
        self.assertEqual(current["sequence"], "")

    def test_ungrouped_track_number_still_becomes_sequence(self):
        # Single-file behavior (is_grouped defaults to False) is unchanged --
        # confirmed against the existing MP4-style-tags test above.
        tags = {"title": "Soul Harvest", "track": "2"}
        current = read_current_book_metadata(tags)
        self.assertEqual(current["sequence"], "2")

    def test_grouped_title_in_text_still_yields_sequence(self):
        # A genuine "Book N" pattern found in the title text itself (not the
        # track-number fallback) is real book-level data even on a per-track
        # tag -- only the track-number fallback is discarded for groups.
        tags = {"title": "Pocket Dungeon - Book 3 - Chapter 1", "track": "1"}
        current = read_current_book_metadata(tags, is_grouped=True)
        self.assertEqual(current["sequence"], "3")


class BuildSearchContextCurrentIsolationTests(unittest.TestCase):
    """clues["current"] must stay true to the raw tags even when the matcher
    heuristics (path overrides, hierarchy-folder series inference) rewrite
    clues["title"]/["series"]/["author"] for search purposes."""

    def test_path_override_changes_clues_but_not_current(self):
        path = Path(
            "/library/Manipulation - Magic Eater, Book 1 - Sean Oswald/"
            "Manipulation - Magic Eater, Book 1 - Sean Oswald.m4b"
        )
        tags = {
            "title": "Sean Oswald",
            "album": "Sean Oswald",
            "album_artist": "Sean Oswald",
            "grouping": "Magic Eater",
        }

        with patch.object(FIXER, "read_tags_and_duration", return_value=(tags, 400.0, True)):
            queries, clues, _ = FIXER.build_search_context(path, {})

        # Matcher-facing clues get the path-recovered title (this is correct
        # matcher behavior -- the raw title tag is just the author's name).
        self.assertEqual(clues["title"], "Manipulation")
        # But "current" must stay exactly what the raw title tag says, since
        # that's what the file's own metadata actually contains right now.
        self.assertEqual(clues["current"]["title"], "Sean Oswald")
        self.assertEqual(clues["current"]["series"], "Magic Eater")

    def test_cached_backup_tags_trigger_a_fresh_live_probe_for_current(self):
        # is_live=False means `tags` came from a cached backup/sidecar
        # snapshot, not a genuine current read -- "current" must still do one
        # more live probe rather than trust the (potentially stale/
        # incomplete) cached tags.
        cached_tags = {"title": "Stale Cached Title"}
        live_tags = {"title": "Real Current Title", "genre": "Fantasy"}
        path = Path("/library/Some Book/book.m4b")

        with (
            patch.object(FIXER, "read_tags_and_duration", return_value=(cached_tags, 400.0, False)),
            patch.object(FIXER, "read_file_tags", return_value=live_tags),
        ):
            _, clues, _ = FIXER.build_search_context(path, {})

        self.assertEqual(clues["current"]["title"], "Real Current Title")
        self.assertEqual(clues["current"]["genre"], "Fantasy")

    def test_live_tags_are_not_reread_a_second_time(self):
        # is_live=True (the common case: no backup exists yet) must reuse the
        # same tags already read, never trigger a second probe.
        tags = {"title": "Only Probed Once"}
        path = Path("/library/Some Book/book.m4b")

        with (
            patch.object(FIXER, "read_tags_and_duration", return_value=(tags, 400.0, True)),
            patch.object(FIXER, "read_file_tags") as mock_read_file_tags,
        ):
            _, clues, _ = FIXER.build_search_context(path, {})

        mock_read_file_tags.assert_not_called()
        self.assertEqual(clues["current"]["title"], "Only Probed Once")


if __name__ == "__main__":
    unittest.main()
