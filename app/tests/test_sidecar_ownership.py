"""folder_sidecar_belongs_to decides whether a folder's sidecar describes a
given audio file. Recorded paths may be from before a move, so only file names
are compared; a payload with no claim at all leaves the file available."""
import json
import tempfile
import unittest
from pathlib import Path

from app.sidecar_ownership import folder_sidecar_belongs_to, folder_sidecar_file_belongs_to

SRC = Path("/library/Author/Book/part2.m4b")


class SourceBlockTests(unittest.TestCase):
    def test_an_empty_payload_claims_nothing(self):
        self.assertTrue(folder_sidecar_belongs_to({}, SRC))
        self.assertTrue(folder_sidecar_belongs_to(None, SRC))

    def test_the_root_file_path_matches_exactly(self):
        payload = {"sidecar": {"source": {"root_file": str(SRC)}}}
        self.assertTrue(folder_sidecar_belongs_to(payload, SRC))

    def test_the_root_file_matches_by_name_after_a_move(self):
        payload = {"sidecar": {"source": {"root_file": "/old/place/part2.m4b"}}}
        self.assertTrue(folder_sidecar_belongs_to(payload, SRC))

    def test_a_different_root_file_name_does_not_match(self):
        payload = {"sidecar": {"source": {"root_file": "/library/Author/Book/other.m4b"}}}
        self.assertFalse(folder_sidecar_belongs_to(payload, SRC))

    def test_chapter_files_alone_are_a_claim(self):
        mine = {"sidecar": {"source": {"chapter_files": [str(SRC), "/x/part3.m4b"]}}}
        theirs = {"sidecar": {"source": {"chapter_files": ["/x/part3.m4b"]}}}
        self.assertTrue(folder_sidecar_belongs_to(mine, SRC))
        self.assertFalse(folder_sidecar_belongs_to(theirs, SRC))

    def test_chapter_file_match_by_name_after_a_move(self):
        payload = {"sidecar": {"source": {"chapter_files": ["/old/part1.m4b", "/old/part2.m4b"]}}}
        self.assertTrue(folder_sidecar_belongs_to(payload, SRC))

    def test_being_listed_as_a_chapter_file_wins_even_if_root_file_differs(self):
        payload = {"sidecar": {"source": {"root_file": "/library/Author/Book/part1.m4b",
                                          "chapter_files": [str(SRC)]}}}
        self.assertTrue(folder_sidecar_belongs_to(payload, SRC))

    def test_marker_and_scan_cache_sections_are_read_too(self):
        for section in ("marker", "scan_cache"):
            with self.subTest(section=section):
                self.assertFalse(folder_sidecar_belongs_to({section: {"source": {"root_file": "/x/other.m4b"}}}, SRC))
                self.assertTrue(folder_sidecar_belongs_to({section: {"source": {"root_file": "/x/part2.m4b"}}}, SRC))

    def test_the_first_section_with_a_claim_decides(self):
        payload = {"sidecar": {"source": {"root_file": "/x/other.m4b"}},
                   "marker": {"source": {"root_file": "/x/part2.m4b"}}}
        self.assertFalse(folder_sidecar_belongs_to(payload, SRC))

    def test_a_section_with_an_empty_source_is_skipped(self):
        payload = {"sidecar": {"source": {}}, "marker": {"source": {"root_file": "/x/part2.m4b"}}}
        self.assertTrue(folder_sidecar_belongs_to(payload, SRC))


class NamedFileTests(unittest.TestCase):
    def test_marker_or_backup_source_file_is_compared_by_name(self):
        for section in ("marker", "backup"):
            with self.subTest(section=section):
                self.assertTrue(folder_sidecar_belongs_to({section: {"source_file": "part2.m4b"}}, SRC))
                self.assertFalse(folder_sidecar_belongs_to({section: {"source_file": "part9.m4b"}}, SRC))

    def test_a_payload_naming_nothing_leaves_the_file_available(self):
        self.assertTrue(folder_sidecar_belongs_to({"sidecar": {"book": {"title": "T"}}}, SRC))


class SidecarFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "libraforge.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_readable_sidecar_is_judged_on_its_content(self):
        self.path.write_text(json.dumps({"marker": {"source_file": "other.m4b"}}))
        self.assertFalse(folder_sidecar_file_belongs_to(self.path, SRC))
        self.path.write_text(json.dumps({"marker": {"source_file": "part2.m4b"}}))
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))

    def test_a_missing_or_corrupt_sidecar_is_treated_as_available(self):
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))
        self.path.write_text("{not json")
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))

    def test_a_sidecar_that_is_not_an_object_is_treated_as_available(self):
        self.path.write_text("[1, 2, 3]")
        self.assertTrue(folder_sidecar_file_belongs_to(self.path, SRC))


if __name__ == "__main__":
    unittest.main()
