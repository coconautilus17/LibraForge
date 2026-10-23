"""Different editions of one ebook work get their own folder instead of colliding (#369).

Seen on a real dry run: "James Joyce - The Restored Finnegans Wake.epub" and
"Joyce, James - Finnegans Wake.epub" both resolved to "Finnegans Wake - EBOOK"
and the second was skipped; the same for two Plotinus pdfs.
"""
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

ORGANIZER = load_script("organizer_v3_13_editions", "organize-audiobooks-by-metadata-v3_13.py")

BASE = Path("/audiobooks/James Joyce/Finnegans Wake - EBOOK")


class EbookEditionLabelTests(unittest.TestCase):
    def label(self, stem, title="Finnegans Wake", author="James Joyce"):
        return ORGANIZER.ebook_edition_label(stem, title, author)

    def test_bracket_and_parenthesis_notes_name_the_edition(self):
        self.assertEqual(
            self.label("Plotinus - The Enneads [Penguin] (Abridged Edition)", "The Enneads", "Plotinus"),
            "Penguin, Abridged Edition",
        )
        self.assertEqual(
            self.label("Plotinus - The Enneads (trans. by Stephen McKenna)", "The Enneads", "Plotinus"),
            "trans. by Stephen McKenna",
        )

    def test_without_notes_the_words_beyond_title_and_author_name_it(self):
        self.assertEqual(self.label("James Joyce - The Restored Finnegans Wake"), "Restored")

    def test_a_name_with_nothing_extra_has_no_label(self):
        self.assertEqual(self.label("Joyce, James - Finnegans Wake"), "")


class EbookEditionTargetTests(unittest.TestCase):
    def target(self, stem, reserved, owners=None, stems=None):
        return ORGANIZER.disambiguate_ebook_target_dir(
            BASE, stem, "Finnegans Wake", "James Joyce", reserved, owners if owners is not None else {BASE: "ebook"}, stems)

    def test_an_unclaimed_folder_is_left_alone(self):
        self.assertEqual(self.target("Anything", set(), {}), BASE)

    def test_a_second_ebook_edition_gets_a_bracketed_label(self):
        got = self.target("James Joyce - The Restored Finnegans Wake", {BASE})
        self.assertEqual(got, Path("/audiobooks/James Joyce/Finnegans Wake - EBOOK [Restored]"))

    def test_without_a_label_it_is_numbered(self):
        got = self.target("Joyce, James - Finnegans Wake", {BASE})
        self.assertEqual(got, Path("/audiobooks/James Joyce/Finnegans Wake - EBOOK [Edition 2]"))

    def test_a_third_edition_with_the_same_label_does_not_reuse_it(self):
        taken = {BASE, Path("/audiobooks/James Joyce/Finnegans Wake - EBOOK [Restored]")}
        owners = {path: "ebook" for path in taken}
        got = self.target("James Joyce - The Restored Finnegans Wake", taken, owners)
        self.assertNotIn(got, taken)

    def test_a_file_with_the_same_name_is_a_duplicate_and_still_collides(self):
        got = self.target("Same Name", {BASE}, stems={BASE: "Same Name"})
        self.assertEqual(got, BASE)

    def test_a_folder_claimed_by_an_audiobook_is_not_touched(self):
        self.assertEqual(self.target("Whatever", {BASE}, {BASE: "audiobook"}), BASE)


if __name__ == "__main__":
    unittest.main()
