"""Hardcover provider verification (abs-agg provider-verification workstream).

**Config gap resolved, 2026-07-21** -- a real HARDCOVER_TOKEN was obtained
and wired into the live abs-agg container. Confirmed via its startup log:
"Loaded provider: Hardcover (hardcover)" (previously "disabled: missing env
vars: HARDCOVER_TOKEN"), and it now appears in /providers with a full
returnedFields schema (title, subtitle, author, narrator, description,
cover, isbn, asin, publisher, publishedYear, language, series, tags).

**But the search itself is broken upstream, confirmed live -- not a
LibraForge bug.** Queried directly against the live, now-configured abs-agg
container with several definitely-real, well-known titles:

    docker exec abs-agg node -e "fetch('http://localhost:3000/hardcover/search?title=Dune')..."
    docker exec abs-agg node -e "...title=Project%20Hail%20Mary..."
    docker exec abs-agg node -e "...title=1984..."
    docker exec abs-agg node -e "...title=Mistborn..."

Every one returned `{"matches": []}` -- a clean 200, not an error, just
genuinely empty. `title` is confirmed to be the correct (and only required)
query parameter -- omitting it returns a 400 "Missing required query
parameter: title", and every other provider uses the same `title` param
successfully. abs-agg's own /providers schema self-documents this exact
issue for Hardcover: "The searching seems to be a bit broken, not finding
results that exist." Same category of finding as Storytel/Audioteka/
BookBeat (confirmed upstream blocker), just a different failure mode --
those fail on parameter passing (400s), this one fails silently (200, empty)
inside Hardcover's own provider implementation.

Standardization tests below use a schema-derived fixture (abs-agg's own
published returnedFields) since no real payload could be captured live --
same approach used for the other blocked providers.
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


HARDCOVER_SCHEMA_FIXTURE = {
    "title": "Dune",
    "subtitle": "",
    "author": "Frank Herbert",
    "narrator": "Simon Vance",
    "description": "A stunning blend of adventure and mysticism, environmentalism and politics.",
    "cover": "https://example.com/dune-cover.jpg",
    "isbn": "9780593099322",
    "asin": "B0018OKX3W",
    "publisher": "Recorded Books",
    "publishedYear": 1965,
    "language": "en",
    "series": [{"series": "Dune", "sequence": "1"}],
    "tags": ["Science Fiction"],
}


class HardcoverStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_and_real_publisher_is_used(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [HARDCOVER_SCHEMA_FIXTURE]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Dune", base_url="http://abs-agg:3000", provider="hardcover",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["title"], "Dune")
        self.assertEqual(meta["author"], "Frank Herbert")
        self.assertEqual(meta["narrator"], "Simon Vance")
        # Hardcover genuinely returns a real publisher -- must be used
        # verbatim, never overwritten (not a SPECIAL_PROVIDER).
        self.assertEqual(meta["publisher"], "Recorded Books")
        self.assertEqual(meta["language"], "en")
        self.assertEqual(meta["series"], "Dune")
        self.assertEqual(meta["sequence"], "1")
        self.assertEqual(meta["year"], "1965")
        self.assertEqual(meta["asin"], "B0018OKX3W")

    def test_title_is_the_only_required_query_parameter(self):
        from app.main import search_abs_agg_candidates

        captured = {}

        def _open(req, timeout=15):
            captured["url"] = req.full_url
            return _FakeResp({"matches": []})

        with patch("urllib.request.urlopen", _open):
            search_abs_agg_candidates(
                query="Dune", base_url="http://abs-agg:3000", provider="hardcover",
            )
        self.assertIn("/hardcover/search?", captured["url"])
        self.assertIn("title=Dune", captured["url"])


if __name__ == "__main__":
    unittest.main()
