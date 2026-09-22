import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ORGANIZER = load_module(
    "organizer_v3_13_series_cleanup",
    "scripts/organize-audiobooks-by-metadata-v3_13.py",
)


class MarketingCleanupKindTests(unittest.TestCase):
    def test_genre_only_and_genre_suffixed_names_are_dropped(self):
        for raw in ("LitRPG", "Street Cultivation", "Slice of Life"):
            self.assertEqual(ORGANIZER.marketing_cleanup_kind(raw), "dropped", raw)

    def test_trailing_marketing_text_is_trimmed(self):
        for raw in (
            "The Wandering Inn: A LitRPG Adventure",
            "Amelia the Level Zero Hero: A LitRPG Adventure",
        ):
            self.assertEqual(ORGANIZER.marketing_cleanup_kind(raw), "trimmed", raw)

    def test_ordinary_names_are_untouched(self):
        for raw in ("Amelia", "The Nine Magics", "Pocket Dungeon", "Emma", "Ascension", ""):
            self.assertEqual(ORGANIZER.marketing_cleanup_kind(raw), "", raw)

    def test_reason_set_contains_all_three_constants(self):
        self.assertEqual(
            ORGANIZER.MARKETING_REASONS,
            frozenset({
                ORGANIZER.MARKETING_SERIES_DROPPED_REASON,
                ORGANIZER.MARKETING_SERIES_TRIMMED_REASON,
                ORGANIZER.MARKETING_TITLE_TRIMMED_REASON,
            }),
        )


class GenreCouplingTests(unittest.TestCase):
    def test_bare_genre_words_and_couplings_are_genre_only(self):
        for value in ("LitRPG", "Cultivation", "Isekai", "Fantasy Cultivation", "LitRPG Isekai", "a LitRPG"):
            self.assertTrue(ORGANIZER.is_generic_genre_coupling(value), value)

    def test_a_real_word_in_front_is_not_genre_only(self):
        for value in ("Street Cultivation", "Dungeon Lord", "The Wraith's Haunt", "Pocket Dungeon"):
            self.assertFalse(ORGANIZER.is_generic_genre_coupling(value), value)

    def test_empty_value_is_not_genre_only(self):
        self.assertFalse(ORGANIZER.is_generic_genre_coupling(""))


class SanitizeBookTitleTrustTests(unittest.TestCase):
    def test_untrusted_drops_any_marketing_shaped_value(self):
        self.assertEqual(ORGANIZER.sanitize_book_title("Street Cultivation"), "")
        self.assertEqual(ORGANIZER.sanitize_book_title("LitRPG"), "")

    def test_trusted_keeps_a_real_name_but_still_drops_a_bare_genre_bucket(self):
        self.assertEqual(ORGANIZER.sanitize_book_title("Street Cultivation", trusted=True), "Street Cultivation")
        self.assertEqual(ORGANIZER.sanitize_book_title("LitRPG", trusted=True), "")
        self.assertEqual(ORGANIZER.sanitize_book_title("Fantasy Cultivation", trusted=True), "")


class InferMetadataFlagTests(unittest.TestCase):
    def _run(self, series: str, title: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "_unorganized"
            book = root / "Sarah Lin - Street Cultivation 2 [1541438302]"
            book.mkdir(parents=True)
            (book / "Street Cultivation 2.m4b").write_bytes(b"")
            (book / "libraforge.json").write_text(json.dumps({
                "schema_version": 2,
                "marker": {"audible": {
                    "asin": "1541438302", "title": title, "chosen_title": title,
                    "author": "Sarah Lin", "series": series, "sequence": "2",
                }},
            }))
            item = ORGANIZER.build_book_items(root, Path(tmp) / "dest")[0]
            return ORGANIZER.infer_metadata(item, root)

    def test_a_real_name_that_ends_in_a_genre_word_is_kept_from_trusted_metadata(self):
        # "Street Cultivation" is a real Audible series (trusted marker data);
        # unlike a bare genre bucket it has a real word in front of the genre
        # word, so it must not be treated as marketing text at all.
        md = self._run("Street Cultivation", "Street Cultivation 2")
        self.assertEqual(md["series"], "Street Cultivation")
        self.assertFalse(ORGANIZER.MARKETING_REASONS & set(md["review_reasons"]))
        self.assertEqual(md["review_details"], [])

    def test_a_bare_genre_bucket_is_still_dropped_even_from_trusted_metadata(self):
        # "LitRPG" has no real content of its own -- Audible sometimes files a
        # book under the genre bucket itself with nothing else, and that is
        # still not a real series, trusted source or not.
        md = self._run("LitRPG", "LitRPG 2")
        self.assertEqual(md["series"], "")
        self.assertIn(ORGANIZER.MARKETING_SERIES_DROPPED_REASON, md["review_reasons"])
        details = {d["label"]: d["value"] for d in md["review_details"]}
        self.assertEqual(details["Source series"], "LitRPG")

    def test_a_coupling_of_two_genre_words_is_also_dropped(self):
        # Neither word is real content on its own -- "Fantasy" is as generic
        # a modifier here as "Cultivation" is, unlike "Street".
        md = self._run("Fantasy Cultivation", "Fantasy Cultivation 2")
        self.assertEqual(md["series"], "")
        self.assertIn(ORGANIZER.MARKETING_SERIES_DROPPED_REASON, md["review_reasons"])

    def test_two_different_dropped_series_share_the_identical_review_reason(self):
        # The reason itself must group; only review_details may vary per book.
        a = self._run("LitRPG", "LitRPG 2")
        b = self._run("Isekai LitRPG", "Isekai LitRPG 2")
        self.assertIn(ORGANIZER.MARKETING_SERIES_DROPPED_REASON, a["review_reasons"])
        self.assertIn(ORGANIZER.MARKETING_SERIES_DROPPED_REASON, b["review_reasons"])
        a_details = {d["label"]: d["value"] for d in a["review_details"]}
        b_details = {d["label"]: d["value"] for d in b["review_details"]}
        self.assertEqual(a_details["Source series"], "LitRPG")
        self.assertEqual(b_details["Source series"], "Isekai LitRPG")

    def test_untrusted_path_derived_series_is_still_dropped_even_when_real(self):
        # A folder-name guess never gets the trusted exemption -- only marker/
        # sidecar data is confirmed enough to keep a genre-shaped real name.
        self.assertEqual(ORGANIZER.clean_series_name("Street Cultivation"), "")
        self.assertEqual(ORGANIZER.clean_series_name("Street Cultivation", trusted=False), "")
        self.assertEqual(ORGANIZER.clean_series_name("Street Cultivation", trusted=True), "Street Cultivation")

    def test_ordinary_series_is_not_flagged(self):
        md = self._run("Pocket Dungeon", "Pocket Dungeon 2")
        self.assertEqual(md["series"], "Pocket Dungeon")
        self.assertFalse(ORGANIZER.MARKETING_REASONS & set(md["review_reasons"]))
        self.assertEqual(md["review_details"], [])


class SanitizePathNameTests(unittest.TestCase):
    def test_in_word_asterisk_is_dropped(self):
        self.assertEqual(ORGANIZER.sanitize_path_name("Unfu*k Yourself"), "Unfuk Yourself")

    def test_other_reserved_characters_unchanged(self):
        self.assertEqual(ORGANIZER.sanitize_path_name("AC/DC: The Story"), "AC - DC - The Story")
        self.assertEqual(ORGANIZER.sanitize_path_name("Halo * Reach"), "Halo - Reach")
        self.assertEqual(ORGANIZER.sanitize_path_name("Who Wants to Be a Millionaire?"), "Who Wants to Be a Millionaire")


class SeriesIsAuthorCreditTests(unittest.TestCase):
    def test_full_credit_list_matches_ignoring_role_suffix(self):
        self.assertTrue(ORGANIZER.series_is_author_credit(
            "Joe Harris, Chris Carter, Dirk Maggs",
            "Joe Harris, Chris Carter, Dirk Maggs - adaptation",
        ))
        self.assertTrue(ORGANIZER.series_is_author_credit("Sarah Lin", "Sarah Lin"))
        self.assertTrue(ORGANIZER.series_is_author_credit("Landon Scott, Adam Sage", "Landon Scott, Adam Sage"))

    def test_real_series_is_not_matched(self):
        self.assertFalse(ORGANIZER.series_is_author_credit("Amelia", "V.A. Lewis"))
        self.assertFalse(ORGANIZER.series_is_author_credit("Street Cultivation", "Sarah Lin"))
        self.assertFalse(ORGANIZER.series_is_author_credit("", "Sarah Lin"))


class SeriesFromSubtitleTests(unittest.TestCase):
    def test_series_and_number_parsed(self):
        self.assertEqual(ORGANIZER.series_from_subtitle("Blight, Book 1"), ("Blight", "1"))
        self.assertEqual(ORGANIZER.series_from_subtitle("Tower Mage, Volume 3"), ("Tower Mage", "3"))

    def test_non_series_subtitles_are_ignored(self):
        for subtitle in ("", "LitRPG", "A Novel", "How to Change Your Mind"):
            self.assertEqual(ORGANIZER.series_from_subtitle(subtitle), ("", ""), subtitle)


class SummaryParsingTests(unittest.TestCase):
    def test_app_parses_the_new_summary_lines(self):
        main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        for text in ("Flagged by generic marketing cleanup", '"flagged_marketing_cleanup"',
                     "Possible duplicates flagged", '"possible_duplicates_flagged"'):
            self.assertIn(text, main_src)


if __name__ == "__main__":
    unittest.main()
