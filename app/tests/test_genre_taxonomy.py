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
