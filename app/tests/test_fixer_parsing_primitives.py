"""Direct tests of the small text helpers in app.fixer.parsing. Most were only
exercised through bigger scenarios before, where a flipped branch could pass
unnoticed because the scenario happened to take another route."""
import unittest

from app.fixer import parsing as p


class NormalizeBookNumberTests(unittest.TestCase):
    def test_blank_and_non_numeric_values_pass_through_trimmed(self):
        self.assertEqual(p.normalize_book_number(""), "")
        self.assertEqual(p.normalize_book_number(None), "")
        self.assertEqual(p.normalize_book_number("abc"), "abc")
        self.assertEqual(p.normalize_book_number(" abc "), "abc")


class DescriptiveBookTextTests(unittest.TestCase):
    def parse(self, value, known=""):
        return p.parse_descriptive_book_text(value, known)

    def test_title_author_and_a_numbered_trailing_segment_is_title_author_series(self):
        got = self.parse("Unsouled - Will Wight - Book 1")
        self.assertEqual((got["title"], got["author"], got["book_number"], got["narrator"]), ("Unsouled", "Will Wight", "1", ""))
        got = self.parse("Unsouled - Will Wight - Cradle 1")
        self.assertEqual((got["title"], got["author"], got["series"], got["book_number"]), ("Unsouled", "Will Wight", "Cradle 1", "1"))

    def test_the_year_form_without_a_narrator_has_an_empty_narrator_string(self):
        got = self.parse("Will Wight (2016) Unsouled")
        self.assertEqual((got["title"], got["narrator"]), ("Unsouled", ""))

if __name__ == "__main__":
    unittest.main()
