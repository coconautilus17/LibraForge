"""Metadata Forge takes genres from Audible's category ladders (item 3 of the
20260928-194730 review): Audible matches used to carry no genre at all, so a
file's "Audiobook" / foreign-store genre tag was never replaced."""
import unittest

from app.fixer.scoring import metadata_from_product
from app.fixer.search import RESPONSE_GROUPS


def ladder(*names):
    return {"ladder": [{"name": n} for n in names]}


PRODUCT = {
    "asin": "B0CDN8WK3D", "title": "Prism Academy: Shadowfall",
    "authors": [{"name": "David Burke"}], "narrators": [], "runtime_length_min": 796,
    "series": [{"title": "Prism Academy", "sequence": "5"}],
    "category_ladders": [
        ladder("Science Fiction & Fantasy", "Fantasy", "Epic"),
        ladder("Science Fiction & Fantasy", "Fantasy", "Paranormal & Urban", "Urban"),
    ],
}
CLUES = {"title": "Shadowfall", "author": "David Burke", "series": "Prism Academy",
         "book_number": "5", "local_duration_minutes": 796.3}


class AudibleGenreTests(unittest.TestCase):
    def test_search_requests_category_ladders(self):
        self.assertIn("category_ladders", RESPONSE_GROUPS.split(","))

    def test_audible_match_takes_genres_from_its_ladders(self):
        # Named by Enrichment Forge's taxonomy (main genres, then subgenres),
        # the same result EF's vote gives from Audible alone.
        metadata = metadata_from_product(PRODUCT, CLUES, 1.0)
        self.assertEqual(metadata["genre"], "Fantasy, Epic Fantasy, Urban Fantasy")

    def test_provider_genres_still_win(self):
        metadata = metadata_from_product({**PRODUCT, "_abs_genres": ["Horror"]}, CLUES, 1.0)
        self.assertEqual(metadata["genre"], "Horror")


if __name__ == "__main__":
    unittest.main()
