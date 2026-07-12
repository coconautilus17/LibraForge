import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_validation", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


BASE_METADATA = {
    "title": "Bold Beginnings",
    "author": "G.D. Brooks",
    "author_primary": "G.D. Brooks",
    "series": "Dashing Devil",
    "edition_tag": "",
    "book_number": "5",
    "sequence_label": "",
    "narrator": "",
    "asin": "",
    "publisher": "",
    "genre": "",
    "year": "",
}


class ValidateNamingTemplateTests(unittest.TestCase):
    def test_default_template_has_no_problems(self):
        self.assertEqual(ORGANIZER.validate_naming_template(ORGANIZER.DEFAULT_NAMING_TEMPLATE), [])

    def test_unknown_token_is_reported(self):
        problems = ORGANIZER.validate_naming_template("{author}/{bogus}/")
        self.assertTrue(any("bogus" in p for p in problems))

    def test_unbalanced_brace_is_reported(self):
        problems = ORGANIZER.validate_naming_template("{author}/{title/")
        self.assertTrue(any("brace" in p.lower() for p in problems))

    def test_no_slash_is_reported(self):
        problems = ORGANIZER.validate_naming_template("{title}")
        self.assertTrue(any("/" in p for p in problems))

    def test_custom_valid_template_has_no_problems(self):
        problems = ORGANIZER.validate_naming_template("{author}/{title},{asin}")
        self.assertEqual(problems, [])


class BuildTargetDirForTemplateTests(unittest.TestCase):
    def test_default_template_matches_build_default_target_dir(self):
        root = Path("/library")
        expected = ORGANIZER.build_default_target_dir(root, BASE_METADATA)
        result = ORGANIZER.build_target_dir_for_template(
            root, BASE_METADATA, ORGANIZER.DEFAULT_NAMING_TEMPLATE
        )
        self.assertEqual(result.target_dir, expected)
        self.assertIsNone(result.filename)

    def test_custom_template_builds_different_path(self):
        # BASE_METADATA has an empty publisher -- the bare {publisher}
        # segment collapses (dropped) rather than becoming a literal
        # "Unknown".
        root = Path("/library")
        result = ORGANIZER.build_target_dir_for_template(
            root, BASE_METADATA, "{publisher}/{author}/{title}"
        )
        self.assertEqual(result.target_dir, root / "G.D. Brooks")
        self.assertEqual(result.filename, "Bold Beginnings")

    def test_custom_template_with_asin_publisher_tokens(self):
        metadata = dict(BASE_METADATA, asin="B0TESTASIN", publisher="Publisher House")
        root = Path("/library")
        result = ORGANIZER.build_target_dir_for_template(
            root, metadata, "{author}/{title} [{asin}] ({publisher})/"
        )
        self.assertEqual(result.target_dir, root / "G.D. Brooks" / "Bold Beginnings [B0TESTASIN] (Publisher House)")
        self.assertIsNone(result.filename)


class BuildCachedTargetDirNamingTemplateTests(unittest.TestCase):
    def test_default_template_unchanged(self):
        root = Path("/library")
        cache = ORGANIZER.empty_structure_cache(root)
        expected = ORGANIZER.build_cached_target_dir(root, BASE_METADATA, cache)
        actual = ORGANIZER.build_cached_target_dir(
            root, BASE_METADATA, cache, naming_template=ORGANIZER.DEFAULT_NAMING_TEMPLATE
        )
        self.assertEqual(actual.target_dir, expected.target_dir)
        self.assertEqual(actual.status, expected.status)

    def test_custom_template_used_on_no_cache_match_fallback(self):
        root = Path("/library")
        cache = ORGANIZER.empty_structure_cache(root)
        result = ORGANIZER.build_cached_target_dir(
            root, BASE_METADATA, cache, naming_template="{author}/{title}"
        )
        self.assertEqual(result.target_dir, root / "G.D. Brooks")

    def test_custom_template_used_on_edition_tag_dramatized_branch(self):
        root = Path("/library")
        cache = ORGANIZER.empty_structure_cache(root)
        metadata = dict(BASE_METADATA, edition_tag="GraphicAudio")
        result = ORGANIZER.build_cached_target_dir(
            root, metadata, cache, naming_template="{author}/{order} [{edition}]"
        )
        self.assertEqual(result.status, "new")
        self.assertEqual(result.target_dir, root / "G.D. Brooks")

    def test_existing_cache_match_branch_still_uses_book_folder_logic(self):
        # Known limitation: a book routed into an already-indexed series
        # folder always uses build_book_folder_name() for its leaf, even
        # under a custom template -- the cache only stores author/series
        # path aliases, not a per-book rendered leaf. This test documents
        # that boundary rather than asserting it's ideal.
        root = Path("/library")
        cache = ORGANIZER.empty_structure_cache(root)
        cache["entries"].append(
            {
                "series": "Dashing Devil",
                "series_key": ORGANIZER.normalize_series_key("Dashing Devil"),
                "path": str(root / "G.D. Brooks" / "Dashing Devil"),
                "canonical_author": "G.D. Brooks",
                "author_keys": ORGANIZER.people_keys("G.D. Brooks"),
                "series_aliases": ["Dashing Devil"],
                "book_count": 3,
            }
        )
        result = ORGANIZER.build_cached_target_dir(
            root, BASE_METADATA, cache, naming_template="{author}/{title}"
        )
        self.assertEqual(result.status, "existing")
        self.assertIsNone(result.filename)
        self.assertEqual(
            result.target_dir, root / "G.D. Brooks" / "Dashing Devil" / ORGANIZER.build_book_folder_name(BASE_METADATA)
        )


if __name__ == "__main__":
    unittest.main()
