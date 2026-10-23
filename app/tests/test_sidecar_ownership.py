"""folder_sidecar_belongs_to decides whether a folder's sidecar describes a
given audio file. Recorded paths may be from before a move, so only file names
are compared; a payload with no claim at all leaves the file available."""
import tempfile
import unittest
from pathlib import Path

from app.sidecar_ownership import folder_sidecar_file_belongs_to

SRC = Path("/library/Author/Book/part2.m4b")


class SidecarFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "libraforge.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_missing_or_corrupt_sidecar_is_treated_as_available(self):
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))
        self.path.write_text("{not json")
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))

    def test_a_sidecar_that_is_not_an_object_is_treated_as_available(self):
        self.path.write_text("[1, 2, 3]")
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))


if __name__ == "__main__":
    unittest.main()
