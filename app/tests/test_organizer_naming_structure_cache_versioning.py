import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_structure_cache", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class EmptyStructureCacheNamingTemplateTests(unittest.TestCase):
    def test_stamps_given_naming_template(self):
        cache = ORGANIZER.empty_structure_cache(Path("/library"), naming_template="{author}/{title}")
        self.assertEqual(cache["naming_template"], "{author}/{title}")

    def test_defaults_to_default_naming_template(self):
        cache = ORGANIZER.empty_structure_cache(Path("/library"))
        self.assertEqual(cache["naming_template"], ORGANIZER.DEFAULT_NAMING_TEMPLATE)


class LoadStructureCacheNamingTemplateTests(unittest.TestCase):
    def test_matching_template_keeps_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "structure-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": ORGANIZER.STRUCTURE_CACHE_SCHEMA_VERSION,
                        "destination_root": "/library",
                        "naming_template": "{author}/{series_dir}/{book_folder}/",
                        "entries": [{"series_key": "cradle"}],
                    }
                ),
                encoding="utf-8",
            )
            cache = ORGANIZER.load_structure_cache(
                cache_path, Path("/library"), naming_template="{author}/{series_dir}/{book_folder}/"
            )
            self.assertEqual(cache["entries"], [{"series_key": "cradle"}])

    def test_mismatched_template_is_treated_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "structure-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": ORGANIZER.STRUCTURE_CACHE_SCHEMA_VERSION,
                        "destination_root": "/library",
                        "naming_template": "{author}/{series_dir}/{book_folder}/",
                        "entries": [{"series_key": "cradle"}],
                    }
                ),
                encoding="utf-8",
            )
            cache = ORGANIZER.load_structure_cache(
                cache_path, Path("/library"), naming_template="{author}/{title}"
            )
            self.assertEqual(cache["entries"], [])
            self.assertEqual(cache["naming_template"], "{author}/{title}")

    def test_missing_naming_template_key_treated_as_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "structure-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": ORGANIZER.STRUCTURE_CACHE_SCHEMA_VERSION,
                        "destination_root": "/library",
                        "entries": [{"series_key": "cradle"}],
                    }
                ),
                encoding="utf-8",
            )
            # A pre-feature cache has no naming_template key; it was built
            # under the built-in ABS scheme, so a default-scheme run (whose
            # cache key is DEFAULT_SCHEME_KEY) must not invalidate it.
            cache = ORGANIZER.load_structure_cache(
                cache_path, Path("/library"), naming_template=ORGANIZER.DEFAULT_SCHEME_KEY
            )
            self.assertEqual(cache["entries"], [{"series_key": "cradle"}])


class BuildStructureCacheStampsTemplateTests(unittest.TestCase):
    def test_build_structure_cache_stamps_current_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination_root = Path(tmp) / "library"
            destination_root.mkdir()
            cache_path = Path(tmp) / "structure-cache.json"
            cache = ORGANIZER.build_structure_cache(
                destination_root, cache_path, progress_every=0, naming_template="{author}/{title}"
            )
            self.assertEqual(cache["naming_template"], "{author}/{title}")
            on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["naming_template"], "{author}/{title}")


if __name__ == "__main__":
    unittest.main()
