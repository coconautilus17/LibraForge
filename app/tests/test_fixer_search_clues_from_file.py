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


class AsinAndPublisherTests(unittest.TestCase):
    def test_without_a_tag_an_asin_is_read_from_a_bracket_in_the_path(self):
        self.assertEqual(clues("/lib/x/Unsouled [B0ABCDEFGH].m4b", title="T")["existing_asin"], "B0ABCDEFGH")
        self.assertEqual(clues("/lib/x/Unsouled [ASIN.b0abcdefgh].m4b", title="T")["existing_asin"], "B0ABCDEFGH")

class DescriptivePathTests(unittest.TestCase):
    def test_an_author_and_title_in_the_file_name_fill_in_when_the_tags_are_empty(self):
        got = clues("/lib/x/Will Wight - Unsouled.m4b", title="", artist="")
        self.assertEqual((got["title"], got["author"]), ("Unsouled", "Will Wight"))

if __name__ == "__main__":
    unittest.main()
