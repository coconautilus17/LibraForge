"""Direct tests of the scoring rules in app.fixer.scoring (duration bands,
omnibus detection, number identity, year), asserting the returned values."""
import unittest
from unittest import mock

from app.fixer import scoring as s


def product(**over):
    base = {"title": "The Lost Bloodline 5", "series": [{"title": "The Lost Bloodline", "sequence": "5"}]}
    base.update(over)
    return base


class OmnibusTests(unittest.TestCase):
    def test_a_book_range_in_the_title_or_subtitle_marks_an_omnibus(self):
        for title, subtitle in (("Cradle Books 1 to 3", ""), ("Cradle", "Books 2 through 4")):
            with self.subTest(title=title, subtitle=subtitle):
                self.assertIs(s.is_omnibus_product(product(title=title, subtitle=subtitle, series=[])), True)

    def test_has_matching_omnibus_range_is_true_only_for_a_match(self):
        pack = product(title="Pack Books 11-12", series=[])
        self.assertIs(s.has_matching_omnibus_range({"title": "Books 11-12"}, pack), True)
        self.assertIs(s.has_matching_omnibus_range({"title": "Books 13-14"}, pack), False)


def side_story(title="Dominion", seq="0", dur=600, authors=("Jane Doe",), narrators=("Bob Roe",), series="Saga"):
    return {"title": title, "series": [{"title": series, "sequence": seq}], "runtime_length_min": dur,
            "authors": [{"name": a} for a in authors], "narrators": [{"name": n} for n in narrators]}


class StrongIdentityOverrideTests(unittest.TestCase):
    CLUES = {"title": "0.5 - Dominion", "author": "Jane Doe", "narrator": "Bob Roe", "series": "Saga", "book_number": "0.5"}

    def override(self, product, clues=None, minutes=600):
        return s.strong_identity_overrides_number_conflict(clues or self.CLUES, product, minutes)

    def test_only_perfect_and_strong_durations_count(self):
        self.assertIs(self.override(side_story(dur=640)), True)       # strong
        self.assertIs(self.override(side_story(dur=700)), False)      # acceptable
        self.assertIs(self.override(side_story(dur=1200)), False)     # mismatch
        self.assertIs(self.override(side_story(), minutes=None), False)

    def test_one_matching_person_is_enough_and_none_is_not(self):
        self.assertIs(self.override(side_story(authors=("Zed Q",))), True)
        self.assertIs(self.override(side_story(narrators=("Yan Z",))), True)
        self.assertIs(self.override(side_story(authors=("Zed Q",), narrators=("Yan Z",))), False)

    def test_titles_differing_in_one_word_each_are_two_books(self):
        # Hitchhiker's radio plays (#406): Secondary Phase is not Tertiary Phase,
        # however similar the titles and close the runtimes.
        clues = {"title": "The Hitchhiker's Guide to the Galaxy - The Secondary Phase", "author": "Douglas Adams",
                 "narrator": "Geoffrey McGivern", "series": "Hitchhiker's Guide (radio plays)",
                 "book_number": "2", "book_number_source": "path"}
        tertiary = side_story(title="The Hitchhiker's Guide To The Galaxy: Tertiary Phase", seq="3", dur=192,
                              authors=("Douglas Adams",), narrators=("Full Cast", "Geoffrey McGivern"),
                              series="Hitchhiker's Guide (radio plays)")
        self.assertIs(self.override(tertiary, clues, minutes=175.6), False)
        self.assertEqual(s.score_product_for_metadata(clues, tertiary, 175.6), 0.0)

    def test_a_subtitle_only_on_one_side_still_overrides(self):
        self.assertIs(self.override(side_story(title="Dominion: A Saga Novella")), True)


class AuthorIdentityConflictTests(unittest.TestCase):
    def conflict(self, local, *product_authors):
        product = {"authors": [{"name": a} for a in product_authors]}
        return s.has_author_identity_conflict({"author": local}, product)

    def test_missing_or_generic_authors_never_conflict(self):
        for local, remote in (("", "Will Wight"), ("Will Wight", ""), ("Unknown", "Will Wight"), ("Various Authors", "Will Wight"),
                              ("Will Wight", "Anonymous"), ("Audiobook Audio", "Will Wight")):
            with self.subTest(local=local, remote=remote):
                self.assertIs(self.conflict(local, remote) if remote else self.conflict(local), False)

    def test_formatting_variants_containment_and_shared_tokens_never_conflict(self):
        for local, remote in (("J R R Tolkien", "J.R.R. Tolkien"), ("Clarke", "Arthur C. Clarke"),
                              ("Arthur C. Clarke", "Arthur C. Clarke, Gentry Lee"), ("Ann Marie Lee", "Zed Lee"),
                              ("Will Wight", "Will Wight")):
            with self.subTest(local=local, remote=remote):
                self.assertIs(self.conflict(local, remote), False)


UNRELATED = {"title": "Totally Different", "author": "", "narrator": "", "series": "", "book_number": ""}


def candidate(asin, minutes=600, narrators=("Bob Roe",), title="The Book", authors=("Jane Doe",), **extra):
    return {"asin": asin, "title": title, "runtime_length_min": minutes, "authors": [{"name": a} for a in authors],
            "narrators": [{"name": n} for n in narrators], **extra}


class PickBestMatchTests(unittest.TestCase):
    """Tie-breaking, with every candidate scoring the same so only the rules under test decide."""

    def pick(self, clues, products, minutes=600.0, score=0.8):
        with mock.patch.object(s, "score_product_for_metadata", return_value=score):
            return s.pick_best_match_for_metadata(clues, products, minutes)

    def test_the_publisher_decides_after_the_sku(self):
        best, _, amb = self.pick({"publisher": "Tantor Audio"},
                                 [candidate("B", 600.1, narrators=("Z",), publisher_name="Podium Audio"),
                                  candidate("A", 600.1, narrators=("Y",), publisher_name="Tantor Audio")])
        self.assertEqual((best["asin"], amb["resolved"]), ("A", True))
        self.assertIn("on publisher", amb["reason"])


class ChooseBestTitleTests(unittest.TestCase):
    def test_a_missing_local_title_uses_audibles_and_a_missing_audible_title_uses_the_local_one(self):
        self.assertEqual(s.choose_best_title("Unsouled", "Cradle", ""), "Unsouled")
        self.assertEqual(s.choose_best_title("", "Cradle", "Local Title"), "Local Title")
        self.assertEqual(s.choose_best_title("", "", ""), "")

class MetadataFromProductTests(unittest.TestCase):
    def meta(self, clues=None, product=None, minutes=None):
        product = product or {"asin": "B0X", "title": "Unsouled", "authors": [{"name": "Will Wight"}],
                              "narrators": [{"name": "Travis Baldree"}], "runtime_length_min": 600,
                              "series": [{"title": "Cradle", "sequence": "1"}], "release_date": "2016-04-01",
                              "product_images": {"500": "cover500"}}
        clues = {"title": "Unsouled", "author": "Will Wight", "narrator": "Travis Baldree", "series": "Cradle",
                 "book_number": "1", **(clues or {})}
        return s.metadata_from_product(product, clues, 0.9, "full")

    def test_a_product_without_authors_keeps_the_local_author(self):
        product = {"asin": "B0X", "title": "Unsouled", "authors": [], "series": []}
        meta = s.metadata_from_product(product, {"title": "Unsouled", "author": "Local Author"}, 0.9, "full")
        self.assertEqual(meta["author"], "Local Author")

def edit_prod(**over):
    base = {"title": "Unsouled", "series": [{"title": "Cradle", "sequence": "1"}], "authors": [{"name": "Will Wight"}],
            "narrators": [{"name": "Travis Baldree"}], "runtime_length_min": 600}
    base.update(over)
    return base


EDIT_CLUES = {"title": "Unsouled", "author": "Will Wight", "series": "Cradle", "book_number": "1"}


class DetermineEditModeTests(unittest.TestCase):
    def mode(self, product=None, clues=None, score=0.9, duration="perfect"):
        return s.determine_edit_mode(product or edit_prod(), {**EDIT_CLUES, **(clues or {})}, score, {"status": duration})

    def test_reordered_title_words_are_never_written(self):
        self.assertEqual(self.mode(edit_prod(title="Alpha Beta"), {"title": "Beta Alpha"}), "none")

    def test_a_series_named_product_title_is_a_full_edit_only_with_a_clean_sequence_and_good_duration(self):
        stand_in = edit_prod(title="Cradle")
        self.assertEqual(self.mode(stand_in, {"title": "Unsouled"}), "full")
        self.assertEqual(self.mode(stand_in, {"title": "Unsouled"}, duration="acceptable"), "full")
        self.assertEqual(self.mode(stand_in, {"title": "Unsouled"}, duration="unknown"), "series_only")
        ranged = edit_prod(title="Cradle", series=[{"title": "Cradle", "sequence": "1-2"}])
        self.assertEqual(self.mode(ranged, {"title": "Unsouled"}, duration="acceptable"), "series_only")

    def test_titles_each_with_words_the_other_lacks_name_two_books(self):
        # "Mistborn - Collected Tales" holds "Secret History"; sharing the
        # series word and a strong runtime does not make them one book.
        secret_history = edit_prod(title="Mistborn: Secret History", authors=[{"name": "Brandon Sanderson"}],
                                   series=[{"title": "The Mistborn Saga", "sequence": "3.5"}])
        clues = {"title": "Mistborn - Collected Tales", "author": "Brandon Sanderson",
                 "series": "The Mistborn Saga", "book_number": ""}
        self.assertEqual(self.mode(secret_history, clues, score=0.82, duration="strong"), "series_only")
        # A subtitle on one side only is the same book.
        self.assertEqual(self.mode(edit_prod(title="Mistborn: The Final Empire", authors=[{"name": "Brandon Sanderson"}],
                                             series=[{"title": "The Mistborn Saga", "sequence": "1"}]),
                                   {**clues, "title": "The Final Empire", "book_number": "1"}), "full")

    def test_a_series_number_title_names_a_book_of_that_series_only(self):
        # "The Riyria Revelations 02" is book 2 of the Revelations, not book 2
        # of the Riyria Chronicles.
        clues = {"title": "The Riyria Revelations 02", "author": "Michael J. Sullivan",
                 "series": "The Riyria Revelations", "book_number": "2"}
        def book_two(series):
            return edit_prod(title="A Book Title", authors=[{"name": "Michael J. Sullivan"}],
                             series=[{"title": series, "sequence": "2"}])
        self.assertNotEqual(self.mode(book_two("The Riyria Chronicles"), clues, score=0.72, duration="strong"), "full")
        self.assertEqual(self.mode(book_two("The Riyria Revelations"), clues, score=0.72, duration="strong"), "full")


class SpecialProviderEditModeTests(unittest.TestCase):
    def mode(self, tags, title="Dragon Emperor", author="Eric Vall", provider="graphicaudio"):
        product = {"title": title, "authors": [{"name": author}], "_abs_provider": provider, "series": []}
        clues = {"title": "Dragon Emperor", "author": "Eric Vall", "_raw_tags": tags}
        return s.determine_edit_mode(product, clues, 0.1, None)

    def test_the_mp4_composer_atom_is_read_as_bytes_or_text(self):
        self.assertEqual(self.mode({"\xa9wrt": [b"GraphicAudio"]}), "full")
        self.assertEqual(self.mode({"\xa9wrt": ["graphicaudio"]}), "full")

    def test_an_unconfirmed_or_wrong_company_title_or_author_is_rejected(self):
        self.assertEqual(self.mode({"composer": "Someone"}), "none")
        self.assertEqual(self.mode({}), "none")
        self.assertEqual(self.mode({"composer": "GraphicAudio"}, provider="soundbooththeater"), "none")
        self.assertEqual(self.mode({"composer": "graphicaudio"}, title="Totally Different Title"), "none")
        self.assertEqual(self.mode({"composer": "graphicaudio"}, author="Zed Q"), "none")


if __name__ == "__main__":
    unittest.main()
