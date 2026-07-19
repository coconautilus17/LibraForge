"""BookBeat provider verification (abs-agg provider-verification workstream).

Catalog: general Nordic/European subscription audiobook platform. Required
"market" parameter (country name, e.g. "germany"). Real schema has no
narrator, no publisher, and no duration field at all -- unlike LibriVox/
Storytel/Audioteka/Big Finish/Die drei ???, this source has none of those.
abs-agg's own /providers description for this one explicitly warns: "Data
might be unrelated a bit" and "There are made up to 4 requests per search,
so consider ratelimiting if self-hosted!" -- a real, self-documented
scraping/multi-request risk (the same class of concern that made abs-tract's
Goodreads path need a circuit breaker), not a hypothetical one.

**BLOCKED for live verification, 2026-07-20** -- same confirmed upstream
abs-agg bug as Storytel/Audioteka: every URL shape for the required "market"
parameter returns 400 {"error": "Missing required parameter: market"} against
the live, up-to-date abs-agg container, despite server logs confirming the
value reaches it ("Parameter string: [ 'germany' ]"). Not a LibraForge bug.

Standardization tests use a schema-derived fixture (abs-agg's own published
returnedFields: title, author, description, cover, isbn, series, language,
publishedYear).
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


BOOKBEAT_SCHEMA_FIXTURE = {
    "title": "Der Vorleser",
    "author": "Bernhard Schlink",
    "description": "Ein Roman über Liebe, Schuld und Erinnerung.",
    "cover": "https://example.com/cover.jpg",
    "isbn": "9783257228069",
    "series": [],
    "language": "de",
    "publishedYear": "1995",
}


class BookBeatStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_no_fabricated_publisher_no_narrator_no_duration(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [BOOKBEAT_SCHEMA_FIXTURE]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Der Vorleser", base_url="http://abs-agg:3000",
                provider="bookbeat", provider_params="germany",
            )
        candidate = result["results"][0]
        meta = candidate["chosen_metadata"]
        self.assertEqual(meta["title"], "Der Vorleser")
        self.assertEqual(meta["author"], "Bernhard Schlink")
        self.assertEqual(meta["language"], "de")
        # BookBeat has no publisher or narrator field at all in its real
        # schema, and is not a SPECIAL_PROVIDER -- both must stay blank,
        # never fabricated from the provider's own name.
        self.assertEqual(meta["publisher"], "")
        self.assertEqual(meta["narrator"], "")
        self.assertIsNone(candidate["duration_minutes"])

    def test_required_market_param_is_placed_in_the_url_path(self):
        from app.main import search_abs_agg_candidates

        captured = {}

        def _open(req, timeout=15):
            captured["url"] = req.full_url
            return _FakeResp({"matches": []})

        with patch("urllib.request.urlopen", _open):
            search_abs_agg_candidates(
                query="Der Vorleser", base_url="http://abs-agg:3000",
                provider="bookbeat", provider_params="germany",
            )
        self.assertIn("/bookbeat/germany/search", captured["url"])


if __name__ == "__main__":
    unittest.main()
