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
