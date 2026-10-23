"""Direct tests of the small text helpers of Folder Forge
(scripts/organize-audiobooks-by-metadata-v3_13.py): book numbers, sequence
labels, author credits and generic folder names. Most were only reached through
whole-plan scenarios before."""
import unittest
from app.tests.script_loader import load_script

ORG = load_script("organizer_text_helpers", "organize-audiobooks-by-metadata-v3_13.py")


class NormalizeBookNumberTests(unittest.TestCase):
    def test_blank_oversized_and_non_numeric_values_pass_through(self):
        self.assertEqual(ORG.normalize_book_number(""), "")
        self.assertEqual(ORG.normalize_book_number("12345"), "12345")
        self.assertEqual(ORG.normalize_book_number("abc"), "abc")


class AuthorCreditHelperTests(unittest.TestCase):
    def test_people_keys_are_normalised_and_deduplicated(self):
        self.assertEqual(ORG.people_keys("Will Wight, Bob Roe"), ["willwight", "bobroe"])
        self.assertEqual(ORG.people_keys("Will Wight & Will Wight"), ["willwight"])
        self.assertEqual(ORG.people_keys(""), [])
        self.assertEqual(ORG.people_keys("   "), [])

    def test_keys_match_when_equal_or_nearly_equal(self):
        self.assertTrue(ORG.keys_match("willwight", "willwight"))
        self.assertTrue(ORG.keys_match("a", "a"))
        self.assertTrue(ORG.keys_match("willwightsmith", "willwightsmit"))     # ratio >= 0.92
        self.assertFalse(ORG.keys_match("willwight", "willwigth"))             # below the cut-off
        self.assertFalse(ORG.keys_match("willwight", "bobroe"))
        self.assertFalse(ORG.keys_match("", ""))
        self.assertFalse(ORG.keys_match("a", ""))
        self.assertFalse(ORG.keys_match("", "a"))

    def test_an_author_is_bad_for_a_series_when_blank_generic_or_the_series_itself(self):
        for author, series in (("", "Cradle"), ("Unknown Author", "Cradle"), ("Audiobooks", "Cradle"), ("Cradle", "Cradle"),
                               ("Reborn as a Space", "Reborn as a Space Mercenary - I Woke Up")):
            with self.subTest(author=author, series=series):
                self.assertTrue(ORG.author_is_probably_bad_for_series(author, series))
        self.assertFalse(ORG.author_is_probably_bad_for_series("Will Wight", "Cradle"))
        self.assertFalse(ORG.author_is_probably_bad_for_series("Will Wight", ""))

class GenericStructureNameTests(unittest.TestCase):
    def test_container_and_placeholder_folder_names_are_generic(self):
        for name in ("Audiobooks", "Unknown", "Books", "Library", "", "   ", "2016", "1-3", "Chapterized", "Complete Series",
                     "My Audiobook Collection", "Audio Files"):
            with self.subTest(name=name):
                self.assertTrue(ORG.is_generic_structure_name(name), name)


if __name__ == "__main__":
    unittest.main()
