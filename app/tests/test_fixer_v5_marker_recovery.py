"""Marker-recovery + metadata.json gap-fill behavior in the v5 fixer.

Covers the fix for applied markers whose ASIN tag was never actually written:
fill-missing must re-apply the marker's stored match (no fresh lookup), write
metadata.json, consolidate the sidecar, and stamp written_fields so healed
books fast-skip next run.
"""
import importlib.util
import json
import sys
import tempfile
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


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_marker_recovery", "scripts/audible-metadata-fixer-v5.py")


class MarkerRealAsinTests(unittest.TestCase):
    def test_real_asin_uppercased(self):
        self.assertEqual(FIXER.marker_real_asin({"audible": {"asin": "b0real1234"}}), "B0REAL1234")

    def test_norealasin_is_empty(self):
        self.assertEqual(FIXER.marker_real_asin({"audible": {"asin": "NOREALASIN"}}), "")

    def test_missing_is_empty(self):
        self.assertEqual(FIXER.marker_real_asin({}), "")
        self.assertEqual(FIXER.marker_real_asin({"audible": {}}), "")


class MetadataFromMarkerTests(unittest.TestCase):
    def test_builds_fill_metadata(self):
        marker = {
            "edit_mode": "full",
            "mode": "manual_full",
            "duration": {"local_minutes": 996},
            "audible": {
                "asin": "B0DXLXLX9W",
                "title": "1% Lifesteal",
                "chosen_title": "1% Lifesteal",
                "author": "Robert Blaise",
                "narrator": "Daniel Wisniewski",
                "series": "1% Lifesteal",
                "sequence": "1",
                "year": "2025",
                "duration_minutes": 996,
                "number_candidates": ["1"],
            },
        }
        md = FIXER.metadata_from_marker(marker)
        self.assertEqual(md["asin"], "B0DXLXLX9W")
        self.assertEqual(md["title"], "1% Lifesteal")
        self.assertEqual(md["author"], "Robert Blaise")
        self.assertEqual(md["narrator"], "Daniel Wisniewski")
        self.assertEqual(md["series"], "1% Lifesteal")
        self.assertEqual(md["sequence"], "1")
        self.assertEqual(md["year"], "2025")
        self.assertEqual(md["edit_mode"], "full")

    def test_norealasin_yields_empty_asin(self):
        md = FIXER.metadata_from_marker({"audible": {"asin": "NOREALASIN", "title": "X"}})
        self.assertEqual(md["asin"], "")
        self.assertEqual(md["title"], "X")

    def test_genre_subtitle_summary_isbn_round_trip(self):
        # These four were written into marker.audible but never read back out
        # by metadata_from_marker, so a recovered/re-filled book silently lost
        # them even though the marker had the data on disk all along.
        marker = {
            "audible": {
                "asin": "B0X",
                "chosen_title": "Book",
                "genre": "Fantasy",
                "subtitle": "A Subtitle",
                "summary": "A summary.",
                "isbn": "9781234567890",
            },
        }
        md = FIXER.metadata_from_marker(marker)
        self.assertEqual(md["genre"], "Fantasy")
        self.assertEqual(md["subtitle"], "A Subtitle")
        self.assertEqual(md["summary"], "A summary.")
        self.assertEqual(md["isbn"], "9781234567890")


class MarkerSkipIsCleanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Book.m4b"
        self.media.write_bytes(b"")
        self.meta_target = self.folder / "metadata.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _marker(self, **over):
        m = {"audible": {"asin": "B0REAL1234"}, "written_fields": ["asin"]}
        m.update(over)
        return m

    def test_clean_when_written_and_metadata_present_and_consolidated(self):
        self.meta_target.write_text("{}", encoding="utf-8")
        self.assertTrue(
            FIXER.marker_skip_is_clean(self.media, self._marker(), True, self.meta_target)
        )

    def test_not_clean_when_asin_not_in_written_fields(self):
        self.meta_target.write_text("{}", encoding="utf-8")
        self.assertFalse(
            FIXER.marker_skip_is_clean(
                self.media, self._marker(written_fields=[]), True, self.meta_target
            )
        )

    def test_not_clean_when_metadata_json_missing(self):
        self.assertFalse(
            FIXER.marker_skip_is_clean(self.media, self._marker(), True, self.meta_target)
        )

    def test_not_clean_when_per_file_sidecar_still_present_and_alone(self):
        self.meta_target.write_text("{}", encoding="utf-8")
        (self.folder / f"Book.m4b{FIXER.LIBRAFORGE_SUFFIX}").write_text("{}", encoding="utf-8")
        self.assertFalse(
            FIXER.marker_skip_is_clean(self.media, self._marker(), True, self.meta_target)
        )

    def test_clean_when_no_real_asin_and_metadata_present(self):
        # A series-only / no-ASIN marker has nothing to fill into tags.
        self.meta_target.write_text("{}", encoding="utf-8")
        m = {"audible": {"asin": "NOREALASIN"}, "written_fields": []}
        self.assertTrue(FIXER.marker_skip_is_clean(self.media, m, True, self.meta_target))

    def test_clean_for_json_sidecar_output_when_asin_is_in_written_fields(self):
        # Grouped/multi-file books use output_kind="json_sidecar": the ASIN
        # is recorded there, not in per-file tags, but that write is still a
        # real write and belongs in written_fields like any other (see the
        # written_fields computation fix in app/main.py and the CLI write
        # worker -- both used to gate written_fields on "wrote tags", which
        # always excluded sidecar-only grouped books).
        self.meta_target.write_text("{}", encoding="utf-8")
        m = self._marker(output_kind="json_sidecar")
        self.assertTrue(
            FIXER.marker_skip_is_clean(self.media, m, True, self.meta_target)
        )

    def test_not_clean_for_json_sidecar_output_when_asin_missing_from_written_fields(self):
        # If a sidecar write genuinely never recorded the ASIN (e.g. an old
        # marker from before written_fields tracked sidecar writes), this
        # must still route to recovery rather than being trusted as clean.
        self.meta_target.write_text("{}", encoding="utf-8")
        m = self._marker(written_fields=[], output_kind="json_sidecar")
        self.assertFalse(
            FIXER.marker_skip_is_clean(self.media, m, True, self.meta_target)
        )


class WriteMarkerWrittenFieldsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Solo.m4b"
        self.media.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _read_marker(self):
        return json.loads((self.folder / "Solo.m4b.libraforge.json").read_text())["marker"]

    def test_written_fields_recorded(self):
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"}, {}, 1.0, "normal", False,
            written_fields=["asin", "title"],
        )
        self.assertEqual(self._read_marker()["written_fields"], ["asin", "title"])

    def test_written_fields_merge_across_runs(self):
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"}, {}, 1.0, "normal", False,
            written_fields=["title"],
        )
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"}, {}, 1.0, "normal", False,
            written_fields=["asin"],
        )
        self.assertEqual(self._read_marker()["written_fields"], ["asin", "title"])

    def test_written_fields_none_preserves_existing(self):
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"}, {}, 1.0, "normal", False,
            written_fields=["asin"],
        )
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"}, {}, 1.0, "normal", False,
            written_fields=None,
        )
        self.assertEqual(self._read_marker()["written_fields"], ["asin"])

    def test_genre_is_persisted_in_marker(self):
        # marker.audible previously had no genre key at all, so a single-file
        # book's genre was unrecoverable from the marker on a later run (e.g.
        # Manual Review re-loading the book) even though it was correctly
        # embedded in the file's own tags.
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full", "genre": "Fantasy"}, {}, 1.0, "normal", False,
        )
        self.assertEqual(self._read_marker()["audible"]["genre"], "Fantasy")

    def test_genre_falls_back_to_current_when_match_has_none(self):
        # mutagen_write_mp4_tags/mutagen_write_mp3_tags only touch the genre
        # tag `if genre:` -- when the match provides no genre, the file's
        # pre-existing genre tag is left alone, not cleared. Confirmed against
        # 100 real _unorganized books: 85/99 single-file "tags"-output books
        # had a genre tag the writer had silently preserved, while
        # marker.audible.genre (and therefore the report's local/match
        # columns) claimed "" -- because it only ever recorded the match's
        # own genre, never the pure current-tags snapshot of what was already
        # embedded. clues["current"] (not top-level clue fields) is the
        # source: see read_current_book_metadata /
        # docs/design/comparison-card-data-source.md.
        FIXER.write_marker(
            self.media,
            {"asin": "B0X", "edit_mode": "full", "genre": ""},
            {"current": {"genre": "Preserved From File"}},
            1.0, "normal", False,
        )
        self.assertEqual(self._read_marker()["audible"]["genre"], "Preserved From File")

    def test_genre_from_match_wins_over_current_when_both_present(self):
        FIXER.write_marker(
            self.media,
            {"asin": "B0X", "edit_mode": "full", "genre": "New Genre"},
            {"current": {"genre": "Old Genre"}},
            1.0, "normal", False,
        )
        self.assertEqual(self._read_marker()["audible"]["genre"], "New Genre")

    def test_subtitle_summary_isbn_are_persisted_in_marker(self):
        # Same gap as genre: marker.audible silently dropped subtitle, summary,
        # and isbn even though the tag writers put them on the actual file.
        FIXER.write_marker(
            self.media,
            {
                "asin": "B0X", "edit_mode": "full",
                "subtitle": "A Subtitle", "summary": "A summary.", "isbn": "9781234567890",
            },
            {}, 1.0, "normal", False,
        )
        audible = self._read_marker()["audible"]
        self.assertEqual(audible["subtitle"], "A Subtitle")
        self.assertEqual(audible["summary"], "A summary.")
        self.assertEqual(audible["isbn"], "9781234567890")

    def test_local_before_uses_real_tag_series_not_path_clue(self):
        # local_before backs the report's "local" column on a later clean-skip
        # run (no fresh probe happens then) -- it must be built exclusively
        # from clues["current"] (the pure, matcher-untouched tag snapshot),
        # never from top-level `clues` fields like "series", which can be a
        # path/folder-derived guess used only to help the matcher.
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"},
            {
                "series": "001 Eric Vall - Pocket Dungeon",  # matcher-only path guess
                "current": {"series": "Pocket Dungeon", "genre": "Fantasy"},
            },
            1.0, "normal", False,
        )
        local_before = self._read_marker()["local_before"]
        self.assertEqual(local_before["series"], "Pocket Dungeon")
        self.assertEqual(local_before["genre"], "Fantasy")

    def test_local_before_series_blank_when_no_real_tag_series(self):
        FIXER.write_marker(
            self.media, {"asin": "B0X", "edit_mode": "full"},
            {"series": "Pocket Dungeon 4", "current": {"series": ""}},
            1.0, "normal", False,
        )
        self.assertEqual(self._read_marker()["local_before"]["series"], "")


class MetadataJsonFillMissingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Book.m4b"
        self.media.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_when_absent(self):
        target = FIXER.write_audiobookshelf_metadata_json(
            self.media, {"title": "T", "asin": "B0AAAA1111"}, None, True, fill_missing=True
        )
        data = json.loads(Path(target).read_text())
        self.assertEqual(data["title"], "T")
        self.assertEqual(data["asin"], "B0AAAA1111")

    def test_fills_only_empty_fields_and_keeps_existing(self):
        target = self.folder / "metadata.json"
        target.write_text(json.dumps({
            "title": "Existing Title",
            "asin": None,
            "publisher": "Real Publisher",
            "description": "",
        }), encoding="utf-8")
        FIXER.write_audiobookshelf_metadata_json(
            self.media,
            {"title": "New Title", "asin": "B0FILL1234", "publisher": "Other", "summary": "desc"},
            None, True, fill_missing=True,
        )
        data = json.loads(target.read_text())
        # Existing non-empty values kept.
        self.assertEqual(data["title"], "Existing Title")
        self.assertEqual(data["publisher"], "Real Publisher")
        # Empty/None values filled.
        self.assertEqual(data["asin"], "B0FILL1234")
        self.assertEqual(data["description"], "desc")

    def test_overwrite_mode_replaces(self):
        target = self.folder / "metadata.json"
        target.write_text(json.dumps({"title": "Old"}), encoding="utf-8")
        FIXER.write_audiobookshelf_metadata_json(
            self.media, {"title": "New"}, None, True, fill_missing=False
        )
        self.assertEqual(json.loads(target.read_text())["title"], "New")


if __name__ == "__main__":
    unittest.main()
