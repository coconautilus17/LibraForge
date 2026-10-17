"""build_search_clues_from_file: how the Metadata Fixer combines a file's tags
with its folder hierarchy into the clues used to search. Tags are passed in, so
no audio files are needed; each test is one rule of the combination."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub

SPEC = importlib.util.spec_from_file_location("fixer_search_clues_from_file", ROOT / "scripts" / "audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = FIXER
SPEC.loader.exec_module(FIXER)


def clues(path, **tags):
    return FIXER.build_search_clues_from_file(Path(path), tags=tags)


class PathHierarchyTests(unittest.TestCase):
    BOOK = "/lib/Will Wight/Cradle/Book 1 - Unsouled/Unsouled.m4b"

    def test_a_book_n_folder_gives_the_number_and_its_parent_gives_the_series(self):
        got = clues(self.BOOK, title="Unsouled", artist="Will Wight")
        self.assertEqual((got["book_number"], got["book_number_source"], got["series"], got["author"]), ("1", "path", "Cradle", "Will Wight"))

    def test_the_path_number_beats_a_stale_track_number_in_the_tags(self):
        got = clues(self.BOOK, title="Unsouled", artist="Will Wight", track="7")
        self.assertEqual((got["book_number"], got["book_number_source"]), ("1", "path"))

    def test_a_clearly_structured_folder_number_beats_a_number_in_the_title_tag(self):
        got = clues("/lib/Will Wight/Cradle/Book 5 - Foo/Foo.m4b", title="Foo - Book 3", artist="Will Wight")
        self.assertEqual((got["book_number"], got["book_number_source"]), ("5", "path"))

    def test_an_unstructured_path_leaves_the_number_from_the_title_tag_alone(self):
        got = clues("/lib/x/Foo.m4b", title="Foo - Book 3", artist="Will Wight")
        self.assertEqual((got["book_number"], got["book_number_source"]), ("3", "title"))

    def test_the_folder_series_replaces_an_album_that_just_repeats_the_title(self):
        got = clues("/lib/Will Wight/Cradle/Book 2 - Foo/Foo.m4b", title="Foo", artist="Will Wight", album="Foo")
        self.assertEqual(got["series"], "Cradle")

    def test_a_series_tag_that_already_names_a_different_series_is_kept(self):
        got = clues("/lib/Will Wight/Cradle/Book 2 - Foo/Foo.m4b", title="Foo", artist="Will Wight", series="Other Saga")
        self.assertEqual(got["series"], "Other Saga")

    def test_generic_container_folders_are_never_used_as_the_series(self):
        got = clues("/lib/_unorganized/Book 2 - Foo/Foo.m4b", title="Foo", artist="Will Wight")
        self.assertNotIn("series", {k: v for k, v in got.items() if v})
        self.assertEqual(got["book_number"], "2")

    def test_a_folder_without_a_book_number_gives_no_hierarchy_series(self):
        got = clues("/lib/Will Wight/Cradle/Unsouled/Unsouled.m4b", title="Unsouled", artist="Will Wight")
        self.assertFalse(got.get("series"))


class AsinAndPublisherTests(unittest.TestCase):
    def test_an_asin_tag_is_upper_cased(self):
        self.assertEqual(clues("/lib/x/a.m4b", title="T", asin="b0xyz12345")["existing_asin"], "B0XYZ12345")
        self.assertEqual(clues("/lib/x/a.m4b", title="T", audible_asin="B0ABC12345")["existing_asin"], "B0ABC12345")

    def test_without_a_tag_an_asin_is_read_from_a_bracket_in_the_path(self):
        self.assertEqual(clues("/lib/x/Unsouled [B0ABCDEFGH].m4b", title="T")["existing_asin"], "B0ABCDEFGH")
        self.assertEqual(clues("/lib/x/Unsouled [ASIN.b0abcdefgh].m4b", title="T")["existing_asin"], "B0ABCDEFGH")

    def test_only_b0_asins_of_ten_characters_count_in_a_path(self):
        self.assertNotIn("existing_asin", clues("/lib/x/Unsouled [A1ABCDEFGH].m4b", title="T"))
        self.assertNotIn("existing_asin", clues("/lib/x/Unsouled [B0ABC].m4b", title="T"))

    def test_a_tag_wins_over_the_path(self):
        self.assertEqual(clues("/lib/x/Unsouled [B0ABCDEFGH].m4b", title="T", asin="B0TAGGED12")["existing_asin"], "B0TAGGED12")

    def test_publisher_and_sku_are_captured(self):
        got = clues("/lib/x/a.m4b", title="T", publisher="Tantor Audio", ufid="BK_RHUK_002027")
        self.assertEqual((got["publisher"], got["sku"]), ("Tantor Audio", "BK_RHUK_002027"))


class DescriptivePathTests(unittest.TestCase):
    def test_the_author_credited_by_a_read_by_folder_replaces_the_reader_in_the_author_tag(self):
        got = clues("/lib/Virgil - The Aeneid (Read by David Collins)/file.mp3", title="x", artist="David Collins")
        self.assertEqual((got["author"], got["narrator"]), ("Virgil", "David Collins"))

    def test_an_author_and_title_in_the_file_name_fill_in_when_the_tags_are_empty(self):
        got = clues("/lib/x/Will Wight - Unsouled.m4b", title="", artist="")
        self.assertEqual((got["title"], got["author"]), ("Unsouled", "Will Wight"))

    def test_a_good_author_tag_is_kept_over_the_path(self):
        got = clues("/lib/x/Someone Else - Unsouled.m4b", title="Unsouled", artist="Will Wight")
        self.assertEqual(got["author"], "Will Wight")


if __name__ == "__main__":
    unittest.main()
