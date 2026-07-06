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


FIXER = load_module("fixer_v5_metadata_json", "scripts/audible-metadata-fixer-v5.py")


class MetadataJsonPathTests(unittest.TestCase):
    def test_grouped_book_uses_folder_metadata_json(self):
        source = Path("/lib/Some Book/Some Book - 01.mp3")
        clues = {"group_search": {"applied": True}}
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, clues, alone_in_folder=False),
            Path("/lib/Some Book/metadata.json"),
        )

    def test_single_file_alone_uses_folder_metadata_json(self):
        source = Path("/lib/Some Book/book.m4b")
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, {}, alone_in_folder=True),
            Path("/lib/Some Book/metadata.json"),
        )

    def test_loose_single_file_uses_companion(self):
        source = Path("/lib/Loose/book.m4b")
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, {}, alone_in_folder=False),
            Path("/lib/Loose/book.m4b.metadata.json"),
        )


class DecideWriteTests(unittest.TestCase):
    def _metadata(self):
        return {
            "title": "The Book",
            "author": "Jane Doe",
            "series": "The Series",
            "sequence": "2",
            "narrator": "Reader",
            "year": "2021",
            "asin": "B0ABCDEF12",
            "edit_mode": "full",
        }

    def test_smart_noop_when_tags_match(self):
        meta = self._metadata()
        current = {
            "title": "The Book",
            "artist": "Jane Doe",
            "grouping": "The Series",
            "genre": "",
            "asin": "B0ABCDEF12",
            "track": "2",
            "composer": "Reader",
            "date": "2021",
        }
        _eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "smart")
        self.assertTrue(skip_write)
        self.assertIn("Smart-skip", note)
        self.assertEqual(filled, [])

    def test_smart_writes_when_tags_differ(self):
        meta = self._metadata()
        current = {"title": "Old Title", "genre": "Audiobook"}
        _eff, skip_write, _note, _filled = FIXER.decide_write(current, meta, "full", "smart")
        self.assertFalse(skip_write)

    def test_goodreads_smart_ignores_unavailable_blank_fields(self):
        meta = {
            "title": "Mind Breaker 1",
            "author": "Dante King",
            "series": "",
            "sequence": "1",
            "narrator": "",
            "year": "",
            "asin": "",
            "genre": "",
            "edit_mode": "full",
        }
        current = {
            "title": "Mind Breaker 1",
            "artist": "Dante King",
            "grouping": "Mind Breaker",
            "track": "1",
            "composer": "Existing Narrator",
            "date": "2024",
            "asin": "B0EXISTING",
            "genre": "Audiobook",
        }
        _eff, skip_write, note, _filled = FIXER.decide_write(
            current, meta, "full", "smart", "goodreads"
        )
        self.assertTrue(skip_write)
        self.assertIn("Smart-skip", note)

    def test_goodreads_smart_requires_asserted_series_and_sequence(self):
        meta = {
            "title": "Backyard Dungeon 20",
            "author": "Logan Jacobs",
            "series": "Backyard Dungeon",
            "sequence": "20",
            "edit_mode": "full",
        }
        current = {
            "title": "Backyard Dungeon 20",
            "artist": "Logan Jacobs",
            "grouping": "Backyard Dungeon",
            "track": "19",
        }
        _eff, skip_write, _note, _filled = FIXER.decide_write(
            current, meta, "full", "smart", "goodreads"
        )
        self.assertFalse(skip_write)

    def test_fill_missing_reports_filled_fields(self):
        meta = self._metadata()
        current = {"title": "The Book", "artist": "Jane Doe"}  # series/asin/etc missing
        eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "fill-missing")
        self.assertFalse(skip_write)
        self.assertIn("series", filled)
        self.assertIn("asin", filled)
        # existing fields are preserved in the merged metadata
        self.assertEqual(eff["title"], "The Book")

    def test_fill_missing_noop_when_complete(self):
        meta = self._metadata()
        current = {
            "title": "The Book",
            "artist": "Jane Doe",
            "grouping": "The Series",
            "track": "2",
            "composer": "Reader",
            "date": "2021",
            "asin": "B0ABCDEF12",
        }
        _eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "fill-missing")
        self.assertTrue(skip_write)
        self.assertEqual(filled, [])


class MetadataJsonWriteTests(unittest.TestCase):
    def test_write_places_folder_metadata_for_alone(self):
        meta = {
            "title": "Solo Book",
            "author": "Jane Doe",
            "narrator": "Reader",
            "series": "S",
            "sequence": "1",
            "year": "2020",
            "asin": "B0SOLO0001",
            "isbn": "9781234567890",
            "genre": "Fantasy",
            "summary": "x",
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Solo Book" / "book.m4b"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True
            )
            self.assertEqual(target, source.parent / "metadata.json")
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "Solo Book")
            self.assertEqual(payload["asin"], "B0SOLO0001")
            self.assertEqual(payload["isbn"], "9781234567890")
            self.assertEqual(payload["genres"], ["Fantasy"])

    def test_write_places_companion_for_loose(self):
        meta = {"title": "Loose Book", "author": "Jane Doe", "asin": "B0LOOSE001"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "loose.m4b"
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=False
            )
            self.assertEqual(target, source.with_name("loose.m4b.metadata.json"))
            self.assertTrue(target.exists())

    def test_metadata_json_does_not_add_audiobook_genre_fallback(self):
        meta = {"title": "No Genre", "author": "Jane Doe"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.m4b"
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["genres"], [])

    def test_multi_genre_string_splits_into_separate_array_entries(self):
        # Previously ["Fantasy, LitRPG"] (one malformed combined entry) --
        # confirmed live before this fix.
        meta = {"title": "Multi Genre", "author": "Jane Doe", "genre": "Fantasy, LitRPG"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.m4b"
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["genres"], ["Fantasy", "LitRPG"])

    def test_multi_genre_split_still_applies_blocklist_and_dedup(self):
        meta = {"title": "T", "author": "A", "genre": "Fantasy, Audiobook, fantasy"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.m4b"
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["genres"], ["Fantasy"])


class SkipBlankFieldsTests(unittest.TestCase):
    """skip_blank_fields (Manual Review's Apply Fill) is keyed off the *new*
    value's blankness -- distinct from fill_missing, which is keyed off the
    *existing file's* blankness. They must not be conflated."""

    def _existing(self, tmp: Path) -> Path:
        target = tmp / "metadata.json"
        target.write_text(json.dumps({
            "title": "Existing Title",
            "subtitle": "Existing Subtitle",
            "authors": ["Existing Author"],
            "publisher": "Existing Publisher",
            "genres": ["Existing Genre"],
        }), encoding="utf-8")
        return target

    def test_blank_new_value_preserves_existing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._existing(tmp_path)
            source = tmp_path / "book.m4b"
            source.write_bytes(b"")
            meta = {"title": "", "author": "", "publisher": ""}
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True, skip_blank_fields=True
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "Existing Title")
            self.assertEqual(payload["authors"], ["Existing Author"])
            self.assertEqual(payload["publisher"], "Existing Publisher")

    def test_non_blank_new_value_always_overwrites_existing(self):
        # Unlike fill_missing, skip_blank_fields does not preserve an
        # existing non-blank value when the new value is also non-blank --
        # the new value always wins as long as it's present.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._existing(tmp_path)
            source = tmp_path / "book.m4b"
            source.write_bytes(b"")
            meta = {"title": "Brand New Title", "author": "New Author"}
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True, skip_blank_fields=True
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "Brand New Title")
            self.assertEqual(payload["authors"], ["New Author"])

    def test_differs_from_fill_missing_when_new_value_present_but_old_also_present(self):
        # fill_missing would keep "Existing Title" here (old is non-blank);
        # skip_blank_fields must not -- the new value is what the user chose.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._existing(tmp_path)
            source = tmp_path / "book.m4b"
            source.write_bytes(b"")
            meta = {"title": "User Chosen Title", "author": "A"}

            fill_missing_target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True, fill_missing=True
            )
            self.assertEqual(
                json.loads(fill_missing_target.read_text())["title"], "Existing Title"
            )

            self._existing(tmp_path)  # reset, since the call above overwrote it
            skip_blank_target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True, skip_blank_fields=True
            )
            self.assertEqual(
                json.loads(skip_blank_target.read_text())["title"], "User Chosen Title"
            )


class ReportItemTests(unittest.TestCase):
    def test_report_item_surfaces_match_genre_and_isbn(self):
        result = FIXER.ItemResult(
            index=1,
            file_path=Path("/lib/book.m4b"),
            display_path=Path("/lib/book.m4b"),
            status="matched",
            metadata={
                "title": "The Book",
                "author": "Jane Doe",
                "genre": "Fantasy",
                "isbn": "9781234567890",
            },
            clues={"title": "The Book", "author": "Jane Doe"},
        )
        item = FIXER._build_report_item(result)
        self.assertEqual(item["match"]["genre"], "Fantasy")
        self.assertEqual(item["match"]["isbn"], "9781234567890")


class ReportItemCleanSkipFallbackTests(unittest.TestCase):
    # A cleanly-skipped file (already matched/marked good by a prior run)
    # gets no fresh probe this run, so result.clues/result.metadata are never
    # populated -- previously this meant the report's "local" and "match"
    # sections were both silently blank for every clean-skip, which is most
    # of a large library on a routine re-run. _build_report_item must fall
    # back to the marker's own data in that case -- specifically to
    # marker.audible (the last-applied, currently-embedded state), not
    # marker.local_before (the snapshot from *before* that write, which goes
    # stale the moment the write completes). See
    # docs/design/comparison-card-data-source.md for the full rationale.
    #
    # local_before is deliberately given DIFFERENT values than audible below
    # (narrator/duration only present in local_before, not audible) so a
    # regression back to reading local_before would be caught here instead
    # of being masked by fixture data that happens to agree either way.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.media = self.folder / "Book.m4b"
        self.media.write_bytes(b"")
        (self.folder / "libraforge.json").write_text(json.dumps({
            "marker": {
                "duration": {"local_minutes": 615, "audible_minutes": 615},
                "audible": {
                    "asin": "B0REAL1234",
                    "chosen_title": "Metal Mage 15",
                    "author": "Eric Vall",
                    "narrator": "Jeff Hays",
                    "series": "Metal Mage",
                    "sequence": "15",
                    "genre": "Fantasy",
                    "subtitle": "A LitRPG Adventure",
                },
                "local_before": {
                    # Stale pre-fix snapshot: contaminated album-fallback
                    # series and a different narrator/duration, standing in
                    # for "what the file looked like before the last write
                    # corrected it." None of these should leak into "local".
                    "raw_title": "015 Metal Mage - Eric Vall",
                    "title": "015 Metal Mage - Eric Vall",
                    "author": "Eric Vall",
                    "series": "",
                    "number": "15",
                    "narrator": "Stale Narrator",
                    "genre": "",
                    "duration_minutes": 612,
                },
            },
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_skip_local_falls_back_to_marker_audible_not_local_before(self):
        result = FIXER.ItemResult(
            index=1, file_path=self.media, display_path=self.media, status="skipped",
        )
        item = FIXER._build_report_item(result)
        self.assertEqual(item["local"]["title"], "Metal Mage 15")
        self.assertEqual(item["local"]["author"], "Eric Vall")
        self.assertEqual(item["local"]["series"], "Metal Mage")
        self.assertEqual(item["local"]["sequence"], "15")
        self.assertEqual(item["local"]["narrator"], "Jeff Hays")
        self.assertEqual(item["local"]["genre"], "Fantasy")
        self.assertEqual(item["local"]["duration_minutes"], 615)

    def test_clean_skip_match_falls_back_to_marker_audible(self):
        result = FIXER.ItemResult(
            index=1, file_path=self.media, display_path=self.media, status="skipped",
        )
        item = FIXER._build_report_item(result)
        self.assertEqual(item["match"]["title"], "Metal Mage 15")
        self.assertEqual(item["match"]["series"], "Metal Mage")
        self.assertEqual(item["match"]["asin"], "B0REAL1234")

    def test_fresh_clues_take_priority_over_marker_fallback(self):
        # "local" must come from clues["current"] (the pure, matcher-untouched
        # tag snapshot), not from top-level clue fields like "title"/"series",
        # which pass through path/folder overrides meant only for the matcher.
        result = FIXER.ItemResult(
            index=1, file_path=self.media, display_path=self.media, status="matched",
            metadata={"title": "Fresh Match", "author": "Eric Vall"},
            clues={
                "title": "Path-Derived Title",  # matcher-only, must not leak into "local"
                "author": "Eric Vall",
                "current": {"title": "Fresh Local", "author": "Eric Vall", "series": "Fresh Series"},
            },
        )
        item = FIXER._build_report_item(result)
        self.assertEqual(item["local"]["title"], "Fresh Local")
        self.assertEqual(item["local"]["series"], "Fresh Series")
        self.assertEqual(item["match"]["title"], "Fresh Match")


if __name__ == "__main__":
    unittest.main()
