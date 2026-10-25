"""Foreign-store genres learned from Audible's category trees (#442) and scrap
that was kept as the user's own (#443)."""
import json
import tempfile
import unittest
from pathlib import Path

from app import store_genres
from app.abs_client import has_real_genres
from app.enrichment import detect_manual_genres
from app.genre_taxonomy import classify, is_foreign_store_genre, labels_from_genres, normalize_label, split_compound_genres


def tree(*nodes):
    """(id, name, parent id) rows -> a fetch_tree() result."""
    names = {cid: name for cid, name, _ in nodes}
    parents = {cid: parent for cid, _, parent in nodes}

    def root(cid):
        while parents[cid]:
            cid = parents[cid]
        return names[cid]
    return {cid: (name, root(cid), parent) for cid, name, parent in nodes}


US_EN = tree(("1", "Science Fiction & Fantasy", ""), ("2", "Fantasy", "1"), ("3", "Health & Wellness", ""),
             ("4", "Physical Illness & Disease", "3"), ("5", "Medicine & Health Care Industry", "3"))
US_ES = tree(("1", "Ciencia Ficción y Fantasía", ""), ("2", "Fantasía", "1"), ("3", "Salud y Bienestar", ""),
             ("4", "Enfermedades Físicas", "3"), ("5", "Industria de la Medicina y Salud", "3"))
# Spain: same structure, other IDs and other wording.
ES_ES = tree(("a", "Ciencia ficción y fantasía", ""), ("b", "Fantasía", "a"), ("c", "Salud y bienestar", ""),
             ("d", "Enfermedad física y trastornos", "c"), ("e", "Medicina y sector de la salud", "c"))
DE_DE = tree(("x", "Science-Fiction & Fantasy", ""), ("y", "Fantasy", "x"), ("z", "Abenteuer", "x"))
DE_EN = tree(("x", "Science Fiction & Fantasy", ""), ("y", "Fantasy", "x"), ("z", "Adventure", "x"))
IT_IT = tree(("p", "Fantascienza e fantasy", ""), ("q", "Fantasy", "p"), ("r", "Thriller", "p"))


def fake_fetch(store, locale):
    return {("us", "en-US"): US_EN, ("us", "es-US"): US_ES, ("es", "es-ES"): ES_ES, ("de", "de-DE"): DE_DE,
            ("de", "en-GB"): DE_EN, ("it", "it-IT"): IT_IT}.get((store, locale), {})


class StoreTableTests(unittest.TestCase):
    def setUp(self):
        self.table = store_genres.build_table(fake_fetch)
        store_genres.set_table(self.table)

    def tearDown(self):
        store_genres.set_table({})

    def test_a_category_is_translated_by_its_id(self):
        self.assertEqual(self.table["foreign"]["fantasía"][0], "fantasy")
        self.assertEqual(self.table["foreign"]["abenteuer"], ["adventure", "science fiction & fantasy"])

    def test_spains_wording_is_paired_with_the_us_stores_spanish(self):
        self.assertEqual(self.table["foreign"]["enfermedad física y trastornos"], ["physical illness & disease", "health & wellness"])
        self.assertEqual(self.table["foreign"]["medicina y sector de la salud"][0], "medicine & health care industry")

    def test_a_store_without_english_is_still_known(self):
        self.assertEqual(self.table["foreign"]["fantascienza e fantasy"], [])
        self.assertTrue(is_foreign_store_genre("Fantascienza e fantasy"))

    def test_an_english_name_on_a_foreign_store_is_not_foreign(self):
        self.assertNotIn("fantasy", self.table["foreign"])
        self.assertFalse(is_foreign_store_genre("Thriller"))
        self.assertEqual(normalize_label("Thriller"), "thriller")

    def test_a_foreign_genre_votes_as_its_english_one_with_its_root(self):
        mains, subs = classify([labels_from_genres(["Enfermedad física y trastornos"])], cap_sub=20)
        self.assertEqual(mains, ["Non-Fiction"])
        self.assertIn("Health", subs)

    def test_a_genre_without_english_never_votes(self):
        self.assertEqual(labels_from_genres(["Fantascienza e fantasy", "Fantasía"]), ["fantasy"])

    def test_it_is_never_the_users_own_genre(self):
        self.assertEqual(detect_manual_genres(["Enfermedad física y trastornos, Abenteuer"], [], False, None), [])
        self.assertFalse(has_real_genres(["Abenteuer"]))


class StoreTableCacheTests(unittest.TestCase):
    def tearDown(self):
        store_genres.set_table({})

    def test_a_fetch_is_saved_and_loaded_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audible-store-genres.json"
            store_genres.configure(path)
            store_genres._last_attempt = 0.0
            store_genres.refresh_if_stale(fake_fetch)
            self.assertIn("fantasía", json.loads(path.read_text(encoding="utf-8"))["foreign"])
            store_genres.set_table({})
            store_genres.configure(path)
            self.assertTrue(store_genres.is_store_genre("Fantasía"))

    def test_a_failed_fetch_keeps_the_old_table(self):
        store_genres.set_table({"fetched_at": 0, "foreign": {"fantasía": ["fantasy", ""]}})
        store_genres._last_attempt = 0.0

        def broken(store, locale):
            raise OSError("offline")
        store_genres.refresh_if_stale(broken)
        self.assertTrue(store_genres.is_store_genre("Fantasía"))


class ScrapIsNobodysGenreTests(unittest.TestCase):
    def test_scrap_in_abs_is_not_pinned(self):
        pinned = detect_manual_genres(["Audbioook", "Speech", "dragon shapeshifter dinosaur tamer king quest fae", "Gaslamp Fantasy"],
                                      [], False, None)
        self.assertEqual(pinned, ["Gaslamp Fantasy"])

    def test_pieces_of_a_cut_genre_are_scrap(self):
        for junk in ("men&#8217", "s Adventure", "A Dungeon Core Experience"):
            with self.subTest(junk=junk):
                self.assertEqual(labels_from_genres([junk]), [])
        self.assertEqual(labels_from_genres(["Children's"]), ["children's"])

    def test_a_store_name_glued_to_more_words_is_split(self):
        self.assertEqual(labels_from_genres(["Arts & Entertainment Film Philosophy"]), ["arts & entertainment", "film philosophy"])
        self.assertEqual(split_compound_genres(["Arts & Entertainment Film Philosophy"])[-1], "Film Philosophy")

    def test_a_radio_drama_under_arts_is_not_non_fiction(self):
        drama = labels_from_genres(["Arts & Entertainment:Entertainment & Performing Arts:Radio, Science Fiction & Fantasy:Fantasy"])
        self.assertEqual(classify([drama])[0], ["Fantasy"])
        self.assertEqual(classify([labels_from_genres(["Arts & Entertainment:Music"])])[0], ["Non-Fiction"])

    def test_a_non_fiction_subgenre_alone_votes_non_fiction(self):
        for genre in ("Society", "Self-Help", "Literary Criticism"):
            with self.subTest(genre=genre):
                self.assertEqual(classify([labels_from_genres([genre])])[0], ["Non-Fiction"])


if __name__ == "__main__":
    unittest.main()
