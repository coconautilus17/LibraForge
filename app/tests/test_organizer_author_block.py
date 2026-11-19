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


class FindAuthorBlockTests(unittest.TestCase):
    def test_last_first_layout_with_ampersand(self):
        block = ORG.find_author_block("{+}{lname}, {fname}{&}/{title}/{filename}")
        self.assertEqual(block.layout, (("token", "lname"), ("text", ", "), ("token", "fname")))
        self.assertTrue(block.multi)
        self.assertEqual(block.between, "&")
        self.assertIsNone(block.last)
        self.assertEqual((block.start, block.end), (0, len("{+}{lname}, {fname}{&}")))

    def test_control_tokens_in_any_order(self):
        block = ORG.find_author_block("{author}{,}{+}<, &>/{title}")
        self.assertEqual(block.layout, (("token", "author"),))
        self.assertTrue(block.multi)
        self.assertEqual((block.between, block.last), (",", ", &"))

    def test_single_name_token_is_a_block_without_multi(self):
        block = ORG.find_author_block("{lname}/{title}")
        self.assertEqual(block.layout, (("token", "lname"),))
        self.assertFalse(block.multi)

    def test_space_breaks_adjacency(self):
        block = ORG.find_author_block("{+} {author}/{title}")
        self.assertFalse(block.multi)
        self.assertEqual(block.start, len("{+} "))

    def test_only_the_first_block_counts(self):
        template = "{author}/{series}/{+}{lname}{&}"
        block = ORG.find_author_block(template)
        self.assertEqual((block.start, block.end), (0, len("{author}")))
        self.assertFalse(block.multi)

    def test_text_between_name_and_control_ends_the_block(self):
        block = ORG.find_author_block("{lname}{&}, {fname}/x")
        self.assertEqual(block.layout, (("token", "lname"),))

    def test_slash_ends_the_block(self):
        block = ORG.find_author_block("{lname}/{fname}")
        self.assertEqual(block.layout, (("token", "lname"),))

    def test_control_tokens_alone_are_not_a_block(self):
        self.assertIsNone(ORG.find_author_block("{+}{&}/{title}"))

    def test_no_block(self):
        self.assertIsNone(ORG.find_author_block("{series}/{title}"))


class StripStrayControlTokensTests(unittest.TestCase):
    def test_stray_separator_is_removed(self):
        self.assertEqual(ORG.strip_stray_control_tokens("{title} {&}", None), "{title} ")

    def test_tokens_inside_the_block_stay(self):
        template = "{+}{author}{&}/{title} {+}<and>"
        block = ORG.find_author_block(template)
        self.assertEqual(ORG.strip_stray_control_tokens(template, block), "{+}{author}{&}/{title} ")

    def test_angle_text_that_is_not_a_separator_survives(self):
        template = "{author}/{title} <draft>"
        block = ORG.find_author_block(template)
        self.assertEqual(ORG.strip_stray_control_tokens(template, block), template)


class AuthorBlockValidationTests(unittest.TestCase):
    def problems(self, template):
        return ORG.validate_naming_template(template)

    def test_valid_block_templates(self):
        for template in (
            "{+}{author}{,}<, &>/{series}/{title}",
            "{+}{lname}, {fname} {initials}{&}/{title}",
            "{+}{author}{;}<;>/{title}",
            "{+}{author}<and>/{title}",
            "{+}{author}{&}<, &>/{title}",
            "{title} {&}/{author}",
            "{author}/{title} <draft>",
        ):
            with self.subTest(template=template):
                self.assertEqual(self.problems(template), [])

    def test_author_with_name_parts(self):
        self.assertIn("Use either {author} or {fname}/{lname}/{initials} in the author block, not both.",
                      self.problems("{+}{author} {lname}/{title}"))

    def test_bad_between_separator(self):
        self.assertIn("Author separator {.} can't be used. Between authors use {,} {;} or {&}.",
                      self.problems("{+}{author}{.}/{title}"))
        self.assertIn("Author separator {, &} can't be used. Between authors use {,} {;} or {&}.",
                      self.problems("{+}{author}{, &}/{title}"))

    def test_bad_last_separator(self):
        self.assertIn("Last-author separator <-> can't be used. Use <,> <;> <&> <and> <, &> or <, and>.",
                      self.problems("{+}{author}<->/{title}"))
        self.assertIn("Last-author separator <And> can't be used. Use <,> <;> <&> <and> <, &> or <, and>.",
                      self.problems("{+}{author}<And>/{title}"))

    def test_separators_abs_cannot_read_together(self):
        self.assertIn("Audiobookshelf can't read {;} together with <&>: it splits on only one kind of separator.",
                      self.problems("{+}{author}{;}<&>/{title}"))
        self.assertIn("Audiobookshelf can't read {&} together with <and>: it splits on only one kind of separator.",
                      self.problems("{+}{author}{&}<and>/{title}"))

    def test_letters_in_braces(self):
        message = "Separators can't contain letters inside { }. Put words in < >, like <and>."
        self.assertIn(message, self.problems("{+}{author}{and}/{title}"))
        self.assertIn(message, self.problems("{+}{author}{, and}/{title}"))
        self.assertNotIn("Unknown token: {and}", self.problems("{+}{author}{and}/{title}"))

    def test_separator_tokens_are_not_malformed_braces(self):
        self.assertNotIn("Unbalanced or malformed curly brace in template.", self.problems("{+}{author}{,}/{title}"))

    def test_empty_and_odd_braces_are_still_malformed(self):
        for template in ("{author}/{}/{title}", "{author}/{1}/{title}"):
            with self.subTest(template=template):
                self.assertIn("Unbalanced or malformed curly brace in template.", self.problems(template))

    def test_unknown_token_still_reported(self):
        self.assertIn("Unknown token: {autor}", self.problems("{+}{autor}{&}/{title}"))

    def test_existing_templates_unchanged(self):
        for template in (ORG.DEFAULT_NAMING_TEMPLATE, "{author}/{title},{asin}", "{author}/{series}/{order} - {title}"):
            with self.subTest(template=template):
                self.assertEqual(self.problems(template), [])


class AuthorBlockWarningTests(unittest.TestCase):
    WARNING = ("The author folder uses only part of each name, so different authors can end up in one folder "
               "(for example two authors named Holt), and Audiobookshelf would read them as one author. "
               "Use {fname} and {lname} together here, or move this block to a later folder.")

    def test_partial_name_in_first_folder_warns(self):
        for template in ("{+}{lname}{&}/{title}/{filename}", "{+}{initials}/{title}", "{fname}/{title}"):
            with self.subTest(template=template):
                self.assertEqual(ORG.naming_template_warnings(template), [self.WARNING])

    def test_full_names_or_later_folder_do_not_warn(self):
        for template in ("{+}{lname}, {fname}{&}/{title}", "{author}/{title}", "{series}/{+}{lname}/{title}",
                         ORG.DEFAULT_NAMING_TEMPLATE):
            with self.subTest(template=template):
                self.assertEqual(ORG.naming_template_warnings(template), [])


class SplitAuthorNameTests(unittest.TestCase):
    def test_middle_initial_stays_with_first_name(self):
        parts = ORG.split_author_name("Mara J. Holt", take_initials=False)
        self.assertEqual((parts.first, parts.last, parts.initials), ("Mara J.", "Holt", ""))

    def test_initials_are_taken_out_of_the_first_part(self):
        parts = ORG.split_author_name("Mara J. Holt", take_initials=True)
        self.assertEqual((parts.first, parts.last, parts.initials), ("Mara", "Holt", "J."))

    def test_particle_stays_with_last_name(self):
        self.assertEqual(ORG.split_author_name("Jon Le Brun", take_initials=False).last, "Le Brun")
        self.assertEqual(ORG.split_author_name("Mira van der Holt", take_initials=False).last, "van der Holt")

    def test_suffix_stays_with_last_name(self):
        parts = ORG.split_author_name("Tomas Reed Jr.", take_initials=False)
        self.assertEqual((parts.first, parts.last), ("Tomas", "Reed Jr."))

    def test_initials_only_first_part(self):
        parts = ORG.split_author_name("A.B. Carver", take_initials=True)
        self.assertEqual((parts.first, parts.last, parts.initials), ("", "Carver", "A.B."))

    def test_single_word_is_the_last_name(self):
        parts = ORG.split_author_name("Quillon", take_initials=True)
        self.assertEqual((parts.first, parts.last, parts.initials), ("", "Quillon", ""))

    def test_case_is_kept_as_written(self):
        parts = ORG.split_author_name("ana pell", take_initials=False)
        self.assertEqual((parts.first, parts.last), ("ana", "pell"))

    def test_caps_initials_kept_by_default_and_follow_scheme_when_asked(self):
        self.assertEqual(ORG.split_author_name("JK Varn", take_initials=True).initials, "JK")
        self.assertEqual(
            ORG.split_author_name("JK Varn", take_initials=True, follow_author_scheme=True).initials, "J.K."
        )

    def test_full_name_is_kept_for_author_token(self):
        self.assertEqual(ORG.split_author_name("Mara J. Holt", take_initials=False).full, "Mara J. Holt")


class RenderAuthorLayoutTests(unittest.TestCase):
    LAYOUT = (("token", "lname"), ("text", ", "), ("token", "fname"), ("text", " "), ("token", "initials"))

    def test_empty_first_name_drops_the_text_after_it(self):
        parts = ORG.split_author_name("A.B. Carver", take_initials=True)
        self.assertEqual(ORG.render_author_layout(self.LAYOUT, parts), "Carver, A.B.")

    def test_single_word_name(self):
        parts = ORG.split_author_name("Quillon", take_initials=True)
        self.assertEqual(ORG.render_author_layout(self.LAYOUT, parts), "Quillon")

    def test_all_parts_present(self):
        parts = ORG.split_author_name("Mara J. Holt", take_initials=True)
        self.assertEqual(ORG.render_author_layout(self.LAYOUT, parts), "Holt, Mara J.")

    def test_author_token(self):
        parts = ORG.split_author_name("Mara J. Holt", take_initials=False)
        self.assertEqual(ORG.render_author_layout((("token", "author"),), parts), "Mara J. Holt")


class JoinAuthorsTests(unittest.TestCase):
    THREE = ["A", "B", "C"]

    def test_three_names(self):
        cases = [
            ((",", ", &"), "A, B, & C"),
            ((",", "and"), "A, B and C"),
            ((";", None), "A; B; C"),
            (("&", None), "A & B & C"),
            ((None, None), "A, B, C"),
            ((None, "&"), "A, B & C"),
            ((",", ", and"), "A, B, and C"),
        ]
        for (between, last), expected in cases:
            with self.subTest(between=between, last=last):
                self.assertEqual(ORG.join_authors(self.THREE, between, last), expected)

    def test_two_names_collapse_the_oxford_comma(self):
        self.assertEqual(ORG.join_authors(["A", "B"], ",", ", &"), "A & B")
        self.assertEqual(ORG.join_authors(["A", "B"], ",", ", and"), "A and B")
        self.assertEqual(ORG.join_authors(["A", "B"], ",", None), "A, B")

    def test_one_name(self):
        self.assertEqual(ORG.join_authors(["A"], "&", "and"), "A")

    def test_four_names_render_all(self):
        self.assertEqual(ORG.join_authors(["A", "B", "C", "D"], ",", "and"), "A, B, C and D")

    def test_over_the_cap_ends_with_et_al(self):
        five = ["A", "B", "C", "D", "E"]
        self.assertEqual(ORG.join_authors(five, ",", "and"), "A, B, C, D and et al")
        self.assertEqual(ORG.join_authors(five, "&", None), "A & B & C & D & et al")
        self.assertEqual(ORG.join_authors(five, ",", ", &"), "A, B, C, D, & et al")


if __name__ == "__main__":
    unittest.main()
