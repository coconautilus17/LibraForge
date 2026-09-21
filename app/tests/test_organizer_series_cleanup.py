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

    def test_dropped_series_adds_review_reason_without_changing_series(self):
        md = self._run("Street Cultivation", "Street Cultivation 2")
        self.assertEqual(md["series"], "")
        self.assertIn(ORGANIZER.MARKETING_SERIES_DROPPED_REASON, md["review_reasons"])

    def test_ordinary_series_is_not_flagged(self):
        md = self._run("Pocket Dungeon", "Pocket Dungeon 2")
        self.assertEqual(md["series"], "Pocket Dungeon")
        self.assertFalse(ORGANIZER.MARKETING_REASONS & set(md["review_reasons"]))


class SummaryParsingTests(unittest.TestCase):
    def test_app_parses_the_new_summary_lines(self):
        main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        for text in ("Flagged by generic marketing cleanup", '"flagged_marketing_cleanup"',
                     "Possible duplicates flagged", '"possible_duplicates_flagged"'):
            self.assertIn(text, main_src)


if __name__ == "__main__":
    unittest.main()
