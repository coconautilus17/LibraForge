"""Folder Forge file-move rules, on a real temporary folder tree: where a loose
file may land, which companions travel with it, what is never overwritten, and
how companion names are normalised after the move."""
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

ORG = load_script("organizer_move_safety", "organize-audiobooks-by-metadata-v3_13.py")


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def touch(self, rel, content=b"x"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


if __name__ == "__main__":
    unittest.main()
