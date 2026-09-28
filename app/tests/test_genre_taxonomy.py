"""Controlled genre vocabulary for Enrichment Forge v2 (ported from the
full-library prototype in docs/design/efv2-prototype/)."""
import unittest

from app import genre_taxonomy as t


class TaxonomyTests(unittest.TestCase):
    def test_audible_ladder_parts_map_to_main_and_sub(self):
        labels = t.labels_from_genres(["Science Fiction & Fantasy: Fantasy: Epic", "Mystery, Thriller & Suspense: Thriller & Suspense: Legal"])
        self.assertIn("fantasy", labels)
        self.assertIn("legal", labels)
        self.assertNotIn("mystery, thriller & suspense", labels)
        self.assertEqual(t.classify([labels])[0][:1], ["Fantasy"])

    def test_aliases_and_suffixes(self):
        self.assertEqual(t.normalize_label("Juvenile Fiction"), "young adult")
        self.assertEqual(t.normalize_label("litrpg (g)"), "litrpg")
        self.assertEqual(t.normalize_label("Smut"), "erotica")

    def test_keywords_and_harem_negation(self):
        self.assertIn("litrpg", t.labels_from_text("A LitRPG adventure"))
        self.assertIn("cultivation", t.labels_from_text("a xianxia cultivation epic"))
        self.assertNotIn("harem", t.labels_from_text("This is not a harem story."))
        self.assertIn("harem", t.labels_from_text("A harem fantasy."))

    def test_never_emits_audiobook(self):
        mains, subs = t.classify([t.labels_from_genres(["Audiobook", "Audiobooks", "Fantasy"])])
        self.assertNotIn("Audiobook", mains + subs)
        self.assertNotIn("audiobook", t.labels_from_genres(["Audiobook"]))

    def test_fantasy_vs_sf_ratio_and_ya_vs_children(self):
        mains, _ = t.classify([["fantasy"], ["fantasy"], ["fantasy"], ["science fiction"]])
        self.assertEqual(mains, ["Fantasy"])
        mains, _ = t.classify([["young adult"], ["young adult"], ["children's audiobooks"]])
        self.assertIn("Young Adult", mains)
        self.assertNotIn("Children's", mains)

    def test_litrpg_filed_under_cyberpunk_is_not_science_fiction(self):
        mains, subs = t.classify([["litrpg", "cyberpunk", "science fiction"]])
        self.assertEqual(mains, ["LitRPG"])
        self.assertNotIn("Cyberpunk", subs)

    def test_series_level_labels_count_as_full_support(self):
        mains, _ = t.classify([["fantasy"]] * 8, extra_labels=["haremlit"])
        self.assertIn("Harem", mains)

    def test_every_map_target_is_in_the_vocabulary(self):
        for label, (mains, _subs) in t.LABEL_MAP.items():
            for m in mains:
                self.assertIn(m, t.MAIN_ORDER, label)


class GoodreadsGenreNamesTests(unittest.TestCase):
    def test_every_goodreads_shelf_genre_maps_into_the_taxonomy(self):
        from app import goodreads_shelves as g
        names = set(g._NICHE.values()) | set(g._AUDIENCE.values()) | set(g._BROAD.values())
        self.assertEqual(sorted(n for n in names if t.normalize_label(n) not in t.LABEL_MAP), [])


class CompoundGenreSplitTests(unittest.TestCase):
    """Store-style merged genres ("Action & Adventure") are split for a library;
    a genre whose own name contains '&' (Sword & Sorcery) is kept whole."""

    def test_split_and_dedupe(self):
        self.assertEqual(t.split_compound_genres(["Action & Adventure", "Science Fiction and Fantasy", "Adventure"]),
                         ["Action", "Adventure", "Science Fiction", "Fantasy"])
        self.assertEqual(t.split_compound_genres(["Mystery, Thriller & Suspense"]), ["Mystery", "Thriller", "Suspense"])

    def test_true_compound_names_stay_whole(self):
        # Rule, not a list: split only when a part is a genre in its own right.
        self.assertEqual(t.split_compound_genres(["Sword & Sorcery"]), ["Sword & Sorcery"])
        self.assertEqual(t.split_compound_genres(["Cloak & Dagger"]), ["Cloak & Dagger"])
        self.assertEqual(t.split_compound_genres(["Dragons & Mythical Creatures"]), ["Dragons", "Mythical Creatures"])
        self.assertEqual(t.split_compound_genres(["Biographies & Memoirs"]), ["Biographies", "Memoirs"])
        self.assertFalse(hasattr(t, "COMPOUND_GENRES"))

    def test_taxonomy_never_outputs_a_merged_name_except_real_compounds(self):
        names = {n for m, s in t.LABEL_MAP.values() for n in m + s} | set(t.MAIN_ORDER)
        self.assertEqual(sorted(n for n in names if "&" in n or " and " in n.lower()), ["Sword & Sorcery"])
        self.assertEqual(t.LABEL_MAP["action & adventure"], ([], ["Action", "Adventure"]))


class ScienceFictionVariantTests(unittest.TestCase):
    def test_a_mangled_single_genre_is_joined_not_split(self):
        self.assertEqual(t.split_compound_genres(["Science & Fiction"]), ["Science Fiction"])
        self.assertEqual(t.split_compound_genres(["Science and Fiction"]), ["Science Fiction"])

    def test_non_genre_parts_are_dropped_after_a_split(self):
        self.assertEqual(t.split_compound_genres(["Literature & Fiction", "Thriller & Audiobook"]), ["Literature", "Thriller"])

    def test_sci_fi_spellings(self):
        for spelling in ("Sci-Fi", "SciFi", "Scifi", "Sci Fi", "Science-Fiction"):
            self.assertEqual(t.labels_from_genres([spelling]), ["science fiction"], spelling)

    def test_unknown_merged_input_labels_are_split_before_mapping(self):
        self.assertEqual(t.labels_from_genres(["Sci-Fi & Fantasy"]), ["science fiction", "fantasy"])
        self.assertEqual(t.labels_from_genres(["Science Fiction & Fantasy"]), [])  # store umbrella: no evidence either way


class CanonicalSpellingTests(unittest.TestCase):
    def test_known_genres_use_one_spelling_unknown_keep_the_users(self):
        self.assertEqual(t.split_compound_genres(["Sci-Fi & Fantasy", "scifi", "Small Town"]),
                         ["Science Fiction", "Fantasy", "Small Town"])
