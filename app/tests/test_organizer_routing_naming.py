import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_routing", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def make_marker_item(root: Path, folder: str, audio_name: str, audible: dict) -> "ORGANIZER.BookItem":
    book_dir = root / folder
    book_dir.mkdir(parents=True, exist_ok=True)
    audio = book_dir / audio_name
    audio.touch()
    marker = audio.with_name(audio.name + ".audible-metadata-fixer.json")
    marker.write_text(json.dumps({"audible": audible}), encoding="utf-8")
    return ORGANIZER.BookItem("folder", book_dir, [audio], audio)


class AsinTokenTests(unittest.TestCase):
    def test_norealasin_is_asin_like(self):
        for token in ("NOREALASIN", "no-real-asin", "[NOREALASIN]", "no real asin"):
            self.assertTrue(ORGANIZER.is_asin_like_token(token), token)

    def test_real_asin_is_asin_like(self):
        self.assertTrue(ORGANIZER.is_asin_like_token("B07XYZ1234"))
        self.assertTrue(ORGANIZER.is_asin_like_token("ASIN B07XYZ1234"))

    def test_normal_title_is_not_asin_like(self):
        for token in ("Cradle", "Unsouled", "Book 2", "B is for Burglar"):
            self.assertFalse(ORGANIZER.is_asin_like_token(token), token)


class BookFolderAsinGuardTests(unittest.TestCase):
    def test_asin_title_never_becomes_book_folder_name(self):
        metadata = {
            "title": "NOREALASIN",
            "series": "Cradle",
            "book_number": "001",
            "sequence_label": "",
            "author_primary": "Arthur C. Clarke",
        }
        folder = ORGANIZER.build_book_folder_name(metadata)
        self.assertNotIn("NOREALASIN", folder)
        self.assertEqual(folder, "Book 1")

    def test_asin_title_without_series_falls_back_to_unknown(self):
        metadata = {"title": "B07XYZ1234", "series": "", "book_number": ""}
        folder = ORGANIZER.build_book_folder_name(metadata)
        self.assertNotIn("B07XYZ1234", folder)


class EditionTagDetectionTests(unittest.TestCase):
    def test_graphicaudio_wins(self):
        self.assertEqual(ORGANIZER.detect_edition_tag("Mistborn (GraphicAudio)"), "GraphicAudio")
        self.assertEqual(ORGANIZER.detect_edition_tag("", "graphic audio"), "GraphicAudio")

    def test_soundbooth_detected(self):
        self.assertEqual(ORGANIZER.detect_edition_tag("Dungeon Crawler [Soundbooth Theater]"), "Soundbooth Theater")

    def test_generic_dramatized(self):
        self.assertEqual(ORGANIZER.detect_edition_tag("Foundation: A Dramatized Adaptation"), "Dramatized")

    def test_plain_text_has_no_tag(self):
        self.assertEqual(ORGANIZER.detect_edition_tag("Cradle", "Unsouled", "Will Wight"), "")

    def test_strip_marker_removes_bracketed_imprint(self):
        self.assertEqual(ORGANIZER.strip_edition_marker("Mistborn (GraphicAudio)"), "Mistborn")
        self.assertEqual(ORGANIZER.strip_edition_marker("Cradle [Dramatized Adaptation]"), "Cradle")


class CanonicalAuthorNameTests(unittest.TestCase):
    def test_spaced_and_compact_initials_converge(self):
        a = ORGANIZER.canonical_author_name("J. R. R. Tolkien")
        b = ORGANIZER.canonical_author_name("J.R.R. Tolkien")
        self.assertEqual(a, b)
        self.assertEqual(a, "J.R.R. Tolkien")

    def test_mid_name_initials_collapse(self):
        self.assertEqual(
            ORGANIZER.canonical_author_name("George R. R. Martin"),
            ORGANIZER.canonical_author_name("George R.R. Martin"),
        )

    def test_lone_initial_gets_a_dot_but_no_merge(self):
        self.assertEqual(ORGANIZER.canonical_author_name("Iain M Banks"), "Iain M. Banks")

    def test_plain_name_unchanged(self):
        self.assertEqual(ORGANIZER.canonical_author_name("Brandon Sanderson"), "Brandon Sanderson")

    def test_tolkien_variants_share_one_author_folder(self):
        spaced = ORGANIZER.build_default_target_dir(
            Path("/out"),
            {"author_primary": "J. R. R. Tolkien", "series": "The Lord of the Rings",
             "title": "The Two Towers", "book_number": "2", "sequence_label": ""},
        )
        compact = ORGANIZER.build_default_target_dir(
            Path("/out"),
            {"author_primary": "J.R.R. Tolkien", "series": "The Lord of the Rings",
             "title": "The Fellowship of the Ring", "book_number": "1", "sequence_label": ""},
        )
        self.assertEqual(spaced.parts[:3], compact.parts[:3])
        self.assertIn("J.R.R. Tolkien", spaced.parts)


class NoSeriesEditionRoutingTests(unittest.TestCase):
    def test_no_series_dramatized_suffixes_book_folder(self):
        target = ORGANIZER.build_default_target_dir(
            Path("/out"),
            {"author_primary": "J.R.R. Tolkien", "series": "", "edition_tag": "Dramatized",
             "title": "The Hobbit", "book_number": "", "sequence_label": ""},
        )
        # No bare "[Dramatized]" folder level; tag rides on the book folder.
        self.assertNotIn("[Dramatized]", target.parts)
        self.assertEqual(target.parts[-1], "The Hobbit [Dramatized]")
        self.assertEqual(target.parts[-2], "J.R.R. Tolkien")


class EditionRoutingTests(unittest.TestCase):
    def test_dramatized_series_routes_to_imprint_bucket(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = make_marker_item(
                root,
                "Mistborn GA",
                "Mistborn - The Final Empire.m4b",
                {
                    "chosen_title": "The Final Empire",
                    "author": "Brandon Sanderson",
                    "series": "Mistborn (GraphicAudio)",
                    "sequence": "1",
                },
            )
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["edition_tag"], "GraphicAudio")
            self.assertEqual(metadata["series"], "Mistborn")

            target = ORGANIZER.build_default_target_dir(root / "out", metadata)
            self.assertIn("Mistborn [GraphicAudio]", target.parts)
            self.assertIn("Brandon Sanderson", target.parts)

    def test_dramatized_bypasses_cache_merge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = ORGANIZER.empty_structure_cache(root / "out")
            cache["entries"].append({
                "series": "Mistborn",
                "series_key": ORGANIZER.normalize_series_key("Mistborn"),
                "path": str(root / "out" / "Brandon Sanderson" / "Mistborn"),
                "canonical_author": "Brandon Sanderson",
                "author_keys": ORGANIZER.people_keys("Brandon Sanderson"),
                "series_aliases": ["Mistborn"],
                "book_count": 3,
            })
            metadata = {
                "title": "The Final Empire",
                "author": "Brandon Sanderson",
                "author_primary": "Brandon Sanderson",
                "series": "Mistborn",
                "edition_tag": "GraphicAudio",
                "book_number": "001",
                "sequence_label": "",
            }
            result = ORGANIZER.build_cached_target_dir(root / "out", metadata, cache)
            target, status = result.target_dir, result.status
            self.assertEqual(status, "new")
            self.assertIn("Mistborn [GraphicAudio]", target.parts)


class AuthorCompatibilityTests(unittest.TestCase):
    def test_clearly_different_authors_incompatible(self):
        self.assertFalse(ORGANIZER.authors_compatible("Arthur C. Clarke", "Will Wight"))

    def test_same_author_compatible(self):
        self.assertTrue(ORGANIZER.authors_compatible("Brandon Sanderson", "Brandon Sanderson"))

    def test_missing_author_is_compatible(self):
        self.assertTrue(ORGANIZER.authors_compatible("", "Will Wight"))
        self.assertTrue(ORGANIZER.authors_compatible("Unknown Author", "Will Wight"))


class CrossAuthorSeriesGuardTests(unittest.TestCase):
    def _cradle_cache(self, root: Path) -> dict:
        cache = ORGANIZER.empty_structure_cache(root / "out")
        cache["entries"].append({
            "series": "Cradle",
            "series_key": ORGANIZER.normalize_series_key("Cradle"),
            "path": str(root / "out" / "Will Wight" / "Cradle"),
            "canonical_author": "Will Wight",
            "author_keys": ORGANIZER.people_keys("Will Wight"),
            "series_aliases": ["Cradle"],
            "book_count": 12,
        })
        return cache

    def test_resolve_series_directory_rejects_foreign_author(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = self._cradle_cache(root)
            metadata = {
                "series": "Cradle",
                "author": "Arthur C. Clarke",
                "author_primary": "Arthur C. Clarke",
            }
            series_dir, status, entry = ORGANIZER.resolve_series_directory(cache, metadata)
            self.assertIsNone(series_dir)
            self.assertEqual(status, "new")
            self.assertIsNone(entry)

    def test_resolve_series_directory_keeps_matching_author(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = self._cradle_cache(root)
            metadata = {
                "series": "Cradle",
                "author": "Will Wight",
                "author_primary": "Will Wight",
            }
            series_dir, status, entry = ORGANIZER.resolve_series_directory(cache, metadata)
            self.assertIsNotNone(series_dir)
            self.assertEqual(status, "existing")

    def test_prefix_fallback_rejects_foreign_author(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = self._cradle_cache(root)
            book_dir = root / "Cradle"
            book_dir.mkdir()
            audio = book_dir / "Cradle.m4b"
            audio.touch()
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)
            metadata = {
                "series": "",
                "author": "Arthur C. Clarke",
                "author_primary": "Arthur C. Clarke",
                "title": "Cradle",
            }
            result = ORGANIZER.apply_cache_prefix_fallback(metadata, item, cache)
            # Author must not be overwritten to Will Wight, series stays empty.
            self.assertEqual(result.get("author_primary"), "Arthur C. Clarke")
            self.assertFalse(result.get("series"))


if __name__ == "__main__":
    unittest.main()
