"""Sidecar cleanup: which JSON files get removed and which are left alone."""
import tempfile
import types
import unittest
from pathlib import Path

import app.main as main_module
from app.main import collect_cleanup_targets, _classify_sidecar


# Stub fixer module exposing only the suffix constants the cleanup reads.
FIXER_STUB = types.SimpleNamespace(
    LIBRAFORGE_SUFFIX=".libraforge.json",
    M4B_TOOL_METADATA_SUFFIX=".m4b-tool-metadata.json",
    CHAPTER_COUNT_CACHE_SUFFIX=".chapter-count-cache.json",
    METADATA_BACKUP_SUFFIX=".metadata-backup.json",
    MARKER_SUFFIX=".audible-metadata-fixer.json",
)

STATE_NAMES = {"libraforge.json"}
STATE_SUFFIXES = {
    ".libraforge.json",
    ".m4b-tool-metadata.json",
    ".chapter-count-cache.json",
    ".metadata-backup.json",
    ".audible-metadata-fixer.json",
}


class ClassifySidecarTests(unittest.TestCase):
    def test_libraforge_family(self):
        for name in (
            "libraforge.json",
            "1301.ogg.libraforge.json",
            "Book.m4b-tool-metadata.json",
            "Folder.chapter-count-cache.json",
            "1301.ogg.metadata-backup.json",
            "1301.ogg.audible-metadata-fixer.json",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    _classify_sidecar(Path("/x") / name, STATE_NAMES, STATE_SUFFIXES),
                    "libraforge",
                )

    def test_metadata_json_family(self):
        for name in ("metadata.json", "1301.ogg.metadata.json"):
            with self.subTest(name=name):
                self.assertEqual(
                    _classify_sidecar(Path("/x") / name, STATE_NAMES, STATE_SUFFIXES),
                    "metadata_json",
                )

    def test_unrelated_json_is_ignored(self):
        for name in ("random.json", "cover.json", "info.json"):
            with self.subTest(name=name):
                self.assertIsNone(
                    _classify_sidecar(Path("/x") / name, STATE_NAMES, STATE_SUFFIXES)
                )

    def test_metadata_backup_is_libraforge_not_metadata_json(self):
        # ".metadata-backup.json" must not be mistaken for a metadata.json file.
        self.assertEqual(
            _classify_sidecar(
                Path("/x/1.ogg.metadata-backup.json"), STATE_NAMES, STATE_SUFFIXES
            ),
            "libraforge",
        )


class CollectCleanupTargetsTests(unittest.TestCase):
    def _make_tree(self, root: Path) -> None:
        book = root / "Vol 9"
        book.mkdir(parents=True)
        # audio + sidecars
        (book / "1301.ogg").write_text("audio")
        (book / "1301.ogg.libraforge.json").write_text("{}")
        (book / "libraforge.json").write_text("{}")
        (book / "Vol 9.chapter-count-cache.json").write_text("{}")
        (book / "metadata.json").write_text("{}")
        (book / "1301.ogg.metadata.json").write_text("{}")
        (book / "cover.jpg").write_text("img")
        (book / "notes.json").write_text("{}")  # unrelated, must survive

    def test_libraforge_only_excludes_metadata_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_tree(root)
            found = collect_cleanup_targets(root, include_metadata_json=False, fixer_module=FIXER_STUB)
            self.assertEqual(len(found["libraforge"]), 3)  # per-file + folder + cache
            self.assertEqual(found["metadata_json"], [])
            names = {p.name for p in found["libraforge"]}
            self.assertNotIn("notes.json", names)
            self.assertNotIn("metadata.json", names)

    def test_include_metadata_json_catches_folder_and_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_tree(root)
            found = collect_cleanup_targets(root, include_metadata_json=True, fixer_module=FIXER_STUB)
            meta_names = {p.name for p in found["metadata_json"]}
            self.assertEqual(meta_names, {"metadata.json", "1301.ogg.metadata.json"})

    def test_audio_and_unrelated_files_never_targeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_tree(root)
            found = collect_cleanup_targets(root, include_metadata_json=True, fixer_module=FIXER_STUB)
            all_targets = found["libraforge"] + found["metadata_json"]
            target_names = {p.name for p in all_targets}
            self.assertNotIn("1301.ogg", target_names)
            self.assertNotIn("cover.jpg", target_names)
            self.assertNotIn("notes.json", target_names)


if __name__ == "__main__":
    unittest.main()
