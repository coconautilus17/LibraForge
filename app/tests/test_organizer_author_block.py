"""Folder Forge author block: multi-author folder names (made-up names only)."""
import unittest

from app.tests.script_loader import load_script

ORG = load_script("organizer_author_block", "organize-audiobooks-by-metadata-v3_13.py")


def _people(author: str, primary: str | None = None) -> list[str]:
    metadata = {"author": author}
    metadata["author_primary"] = primary if primary is not None else ORG.canonical_author_name(ORG.primary_author(author))
    return ORG.author_block_people(metadata)


class AuthorBlockPeopleTests(unittest.TestCase):
    def test_translator_is_dropped(self):
        self.assertEqual(_people("Ana Pell, Rook Marr - translator"), ["Ana Pell"])

    def test_foreword_is_dropped(self):
        self.assertEqual(_people("Ana Pell, Ivo Sand, Lee Doan - foreword"), ["Ana Pell", "Ivo Sand"])

    def test_generic_credit_is_dropped(self):
        self.assertEqual(_people("Ana Pell, Various"), ["Ana Pell"])

    def test_names_are_canonicalized(self):
        self.assertEqual(_people("A. B. Carver & Ivo Sand"), ["A.B. Carver", "Ivo Sand"])

    def test_cache_corrected_primary_replaces_first(self):
        self.assertEqual(_people("Ana Pell, Ivo Sand", primary="Ana Pell-Rowe"), ["Ana Pell-Rowe", "Ivo Sand"])

    def test_translator_credited_first_is_not_taken_for_a_correction(self):
        self.assertEqual(_people("Rook Marr - translator, Ana Pell"), ["Ana Pell"])

    def test_only_a_role_credit_gives_empty_list(self):
        self.assertEqual(_people("Rook Marr - translator"), [])

    def test_split_people_keeps_roles_by_default(self):
        self.assertEqual(ORG.split_people("Ana Pell, Rook Marr - translator"), ["Ana Pell", "Rook Marr"])


if __name__ == "__main__":
    unittest.main()
