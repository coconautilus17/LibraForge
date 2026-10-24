"""Enrichment Forge keeps every genre a source names unless it is scrap (#431, #432, #434)."""
import unittest

from app.abs_client import has_real_genres
from app.enrichment import audible_category_ladder_genres, build_book_voters, detect_manual_genres
from app.genre_taxonomy import classify, is_scrap_label, labels_from_genres
from app.genre_voting import book_vote, vote_unit


def ladders(*paths):
    return {"category_ladders": [{"ladder": [{"name": n} for n in p.split(" > ")]} for p in paths]}


def genres_of(*paths):
    return classify([labels_from_genres(audible_category_ladder_genres(ladders(*paths)))], cap_sub=20)


class KeepUnknownGenresTests(unittest.TestCase):
    def test_a_label_the_table_lacks_is_kept_under_its_own_spelling(self):
        mains, subs = genres_of("Children's Audiobooks > Folk Tales & Myths", "Literature & Fiction > LGBTQ+")
        self.assertIn("Folk Tales & Myths", subs)
        self.assertIn("LGBTQ+", subs)

    def test_a_genre_the_vote_itself_names_counts_as_input(self):
        self.assertIn("Historical Fantasy", classify([labels_from_genres(["Historical Fantasy"])])[1])

    def test_non_fiction_subjects_vote_non_fiction(self):
        mains, subs = genres_of("Politics & Social Sciences > Philosophy > Consciousness & Thought")
        self.assertEqual(mains, ["Non-Fiction"])
        self.assertIn("Philosophy", subs)

    def test_the_audible_root_category_votes(self):
        self.assertIn("History", audible_category_ladder_genres(ladders("History > World")))
        self.assertNotIn("Science Fiction & Fantasy", audible_category_ladder_genres(ladders("Science Fiction & Fantasy > Fantasy")))

    def test_spies_and_politics_is_a_thriller_shelf(self):
        mains, subs = genres_of("Mystery, Thriller & Suspense > Thriller & Suspense > Spies & Politics > Espionage")
        self.assertEqual(mains, ["Thriller"])
        self.assertIn("Espionage", subs)


class ScrapListTests(unittest.TestCase):
    def test_format_words_and_junk_are_scrap(self):
        for junk in ("Audiobook", "Audio Book", "Hörbuch", "Audbioook", "Speech", "dragon shapeshifter dinosaur tamer king quest fae"):
            with self.subTest(junk=junk):
                self.assertEqual(labels_from_genres([junk]), [])

    def test_a_format_word_is_stripped_from_a_genre(self):
        self.assertEqual(labels_from_genres(["Fantasy Audiobook"]), ["fantasy"])
        self.assertEqual(labels_from_genres(["The Legends of the First Empire Audiobook"]), [])

    def test_a_long_real_genre_name_is_not_scrap(self):
        self.assertFalse(is_scrap_label("asian american & pacific islander"))

    def test_an_html_entity_does_not_split_a_genre(self):
        self.assertEqual(labels_from_genres(["Men&#8217;s Adventure"]), ["men’s adventure"])


class UmbrellaInAbsGenresTests(unittest.TestCase):
    def test_science_fiction_and_fantasy_in_abs_votes_neither(self):
        voters = build_book_voters({"existing_genres": ["Science Fiction & Fantasy"]}, None, None, None, None, None)
        self.assertNotIn("abs_existing", voters)


class ForeignStoreGenresTests(unittest.TestCase):
    def test_a_spanish_store_genre_votes_as_its_english_one(self):
        mains, subs = classify([labels_from_genres(["Ciencia e ingeniería"])])
        self.assertEqual((mains, subs), (["Non-Fiction"], ["Science"]))

    def test_it_stays_replaceable_for_metadata_forge_and_is_never_pinned(self):
        self.assertFalse(has_real_genres(["Fantasía, Acción y aventura"]))
        self.assertEqual(detect_manual_genres(["Fantasía", "Política y ciencias sociales"], [], False, None), [])


class SeriesVoteTests(unittest.TestCase):
    def test_a_series_with_only_subgenres_still_has_an_answer(self):
        votes = [book_vote({"goodreads": ["folk tales & myths"]}) for _ in range(2)]
        unit = vote_unit(votes, series_labels=[], series_evidence=[], pf_progression=False, standalone=False)
        self.assertEqual(unit["sub"], ["Folk Tales & Myths"])
        self.assertEqual(unit["agreement"], "ok")

    def test_non_fiction_keeps_a_subgenre_the_table_lacks(self):
        votes = [book_vote({"audible": ["philosophy", "ideologies & doctrines"]})]
        unit = vote_unit(votes, series_labels=[], series_evidence=[], pf_progression=False, standalone=True)
        self.assertEqual(unit["main"], ["Non-Fiction"])
        self.assertIn("Ideologies & Doctrines", unit["sub"])


if __name__ == "__main__":
    unittest.main()
