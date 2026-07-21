"""LibriVox provider verification (abs-agg provider-verification workstream).

Catalog: volunteer-read public-domain audiobooks. Real, distinctive traits
confirmed via live fetches against the running abs-agg container, 2026-07-20
(docker exec abs-agg wget -qO- 'http://localhost:3000/librivox/search?...'):

- No publisher field at all in the real schema, and LibriVox itself is not a
  publisher (volunteer readers of already-public-domain texts) -- publisher
  must stay blank, never fabricated (see fix/abs-agg-provider-shared-fixes,
  issue #254).
- narrator is very often a long comma-joined list of many volunteer readers
  (a full cast), not a single narrator name -- this is a real, accepted
  source quirk, not a bug: the existing single-string narrator field just
  carries the whole cast list verbatim.
- Real language data is present and, unlike Storytel/Audioteka/BookBeat,
  LibriVox has no language-filter search parameter at all -- a plain query
  genuinely returns English, German, and Spanish readings of the same public-
  domain work side by side (verified live: "Frankenstein" returned English,
  German, and Spanish results). See test_abs_agg_batch_language.py for the
  batch-path scoring fix this motivated.
- Real duration data is present (unlike GraphicAudio/SoundBooth Theater/
  BookBeat/ARD Audiothek), though not every entry has it.
- Frequently returns many results for the exact same book/title, one per
  distinct volunteer reading -- a real cataloging trait of this source, not
  a search-quality problem.
"""
import unittest
from unittest.mock import patch


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen_for(payload):
    def _open(req, timeout=15):
        return _FakeResp(payload)
    return _open


# Real (trimmed) fixture captured live from abs-agg's librivox endpoint,
# 2026-07-20, for "Pride and Prejudice".
LIBRIVOX_PRIDE_AND_PREJUDICE = {
    "title": "Pride and Prejudice",
    "author": "Jane Austen",
    "narrator": (
        "Chris Goringe, Kara Shallenberg (1969-2023), Kristen McQuillin, "
        "Maureen S. O'Brien, Gord Mackenzie, Mark Bradford"
    ),
    "publishedYear": "1813",
    "description": "Pride and Prejudice is the most famous of Jane Austen's novels...",
    "cover": "https://archive.org/download/pride_and_prejudice_librivox/Pride_Prejudice_1104.jpg",
    "genres": ["Romance"],
    "language": "English",
    "duration": 47204,
}

# Real trait: a version with multiple genres and no duration at all.
LIBRIVOX_PRIDE_AND_PREJUDICE_MULTI_GENRE_NO_DURATION = {
    "title": "Pride and Prejudice",
    "author": "Jane Austen",
    "narrator": "KEllieP",
    "publishedYear": "1813",
    "genres": ["General Fiction", "Romance"],
    "language": "English",
}


class LibriVoxManualSearchStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_is_standardized_and_publisher_stays_blank(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [LIBRIVOX_PRIDE_AND_PREJUDICE]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Pride and Prejudice", base_url="http://abs-agg:3000", provider="librivox",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["title"], "Pride and Prejudice")
        self.assertEqual(meta["author"], "Jane Austen")
        self.assertIn("Chris Goringe", meta["narrator"])
        self.assertEqual(meta["genre"], "Romance")
        self.assertEqual(meta["language"], "English")
        self.assertEqual(meta["publisher"], "")
        self.assertEqual(meta["asin"], "")

    def test_multiple_genres_are_joined_not_truncated(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [LIBRIVOX_PRIDE_AND_PREJUDICE_MULTI_GENRE_NO_DURATION]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Pride and Prejudice", base_url="http://abs-agg:3000", provider="librivox",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["genre"], "General Fiction, Romance")

    def test_missing_duration_does_not_raise(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [LIBRIVOX_PRIDE_AND_PREJUDICE_MULTI_GENRE_NO_DURATION]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Pride and Prejudice", base_url="http://abs-agg:3000", provider="librivox",
            )
        self.assertIsNone(result["results"][0]["duration_minutes"])

    def test_many_results_for_one_title_all_standardize_cleanly(self):
        # Real LibriVox trait: many distinct volunteer readings of the same
        # book come back for one query. Confirm this doesn't break anything
        # (e.g. accidental de-dup, crashes on repeated titles).
        from app.main import search_abs_agg_candidates

        payload = {"matches": [
            LIBRIVOX_PRIDE_AND_PREJUDICE,
            {**LIBRIVOX_PRIDE_AND_PREJUDICE, "narrator": "Annie Coleman Rothenberg", "duration": 48301},
            {**LIBRIVOX_PRIDE_AND_PREJUDICE, "narrator": "Karen Savage", "duration": 37380},
        ]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Pride and Prejudice", base_url="http://abs-agg:3000", provider="librivox",
            )
        self.assertEqual(len(result["results"]), 3)
        narrators = {r["chosen_metadata"]["narrator"] for r in result["results"]}
        self.assertEqual(len(narrators), 3)


if __name__ == "__main__":
    unittest.main()
