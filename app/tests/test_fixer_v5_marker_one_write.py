"""After a tag write, the marker and the backup's applied tags go to the book's
libraforge.json in one write, with the same content the two separate writes
(write_marker, then update_backup_with_applied_metadata) used to leave."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.tests.script_loader import load_module


FIXER = load_module("fixer_v5_marker_one_write", "scripts/audible-metadata-fixer-v5.py")

METADATA = {"asin": "B0TESTASIN", "title": "New Title", "author": "Author", "narrator": "Narrator",
            "series": "Series", "sequence": "2", "year": "2020", "genre": "Fantasy", "edit_mode": "full"}


class MarkerOneWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name) / "Book.m4b"
        self.media.write_bytes(b"")
        FIXER.write_original_metadata_backup(self.media, tags={"title": "Old"}, duration_minutes=60.0)
        self.sidecar = self.media.parent / "Book.m4b.libraforge.json"

    def write_marker(self, **extra):
        FIXER.write_marker(self.media, METADATA, {"current": {"title": "Old"}}, 1.0, "normal", False, **extra)

    def test_one_write_holds_marker_and_applied_tags(self):
        with mock.patch.object(FIXER, "_write_libraforge", wraps=FIXER._write_libraforge) as writes:
            self.write_marker(applied_tags_metadata=METADATA)
        self.assertEqual(writes.call_count, 1)
        payload = json.loads(self.sidecar.read_text())
        self.assertEqual(payload["marker"]["audible"]["asin"], "B0TESTASIN")
        self.assertEqual(payload["backup"]["applied_tags"], FIXER._synthesize_applied_tags(METADATA))
        self.assertEqual(payload["backup"]["format_tags"], {"title": "Old"})

    def test_same_result_as_the_two_separate_writes(self):
        self.write_marker(applied_tags_metadata=METADATA)
        combined = json.loads(self.sidecar.read_text())

        FIXER.write_original_metadata_backup(self.media.with_name("Other.m4b"), tags={"title": "Old"},
                                             duration_minutes=60.0)
        other = self.media.with_name("Other.m4b")
        FIXER.update_backup_with_applied_metadata(other, METADATA)
        FIXER.write_marker(other, METADATA, {"current": {"title": "Old"}}, 1.0, "normal", False)
        separate = json.loads(other.with_name("Other.m4b.libraforge.json").read_text())

        for payload in (combined, separate):
            for key in ("created_at", "applied_at", "source_file"):
                payload["backup"].pop(key, None)
            for key in ("processed_at", "source_file"):
                payload["marker"].pop(key, None)
        self.assertEqual(combined, separate)

    def test_no_tag_write_leaves_the_backup_alone(self):
        self.write_marker()
        self.assertNotIn("applied_tags", json.loads(self.sidecar.read_text())["backup"])


if __name__ == "__main__":
    unittest.main()
