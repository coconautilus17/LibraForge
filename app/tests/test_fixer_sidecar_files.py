"""Where the Metadata Fixer keeps its per-book record (libraforge.json), how it
migrates the old file layouts, who owns a shared folder's sidecar and what the
original-tags backup keeps. Every assertion is on files on disk."""
import json
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

FIXER = load_script("fixer_sidecar_files", "audible-metadata-fixer-v5.py")


class SidecarFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / "Book"
        self.folder.mkdir()
        self.source = self.folder / "book.m4b"
        self.source.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def folder_lf(self):
        return self.folder / "libraforge.json"

    @property
    def file_lf(self):
        return self.folder / "book.m4b.libraforge.json"


if __name__ == "__main__":
    unittest.main()
