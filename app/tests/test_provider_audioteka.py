"""Audioteka provider verification (abs-agg provider-verification workstream).

Catalog: Central/Eastern European audiobooks (Polish/Czech/German/Slovak/
Lithuanian). Required "lang" parameter, enum pl/cz/de/sk/lt.

**BLOCKED for live verification, 2026-07-20** -- same confirmed upstream
abs-agg bug as Storytel and BookBeat (see test_provider_storytel.py for the
full diagnostic detail): every URL shape (path segment, query string, both)
returns 400 {"error": "Missing required parameter: lang"} against the live,
up-to-date abs-agg container, even though the container's own logs show the
value reaching the server ("Parameter string: [ 'pl' ]"). Not a LibraForge
bug -- flagged upstream, not fixed here.

Standardization tests use a schema-derived fixture (abs-agg's own published
returnedFields: title, author, narrator, description, cover, publisher,
genres, tags, series, language, duration) since the endpoint could not
actually be queried live.
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


AUDIOTEKA_SCHEMA_FIXTURE = {
    "title": "Wiedźmin: Ostatnie życzenie",
    "author": "Andrzej Sapkowski",
    "narrator": "Jacek Rozenek",
    "description": "Zbiór opowiadań o wiedźminie Geralcie z Rivii.",
    "cover": "https://example.com/cover.jpg",
    "publisher": "Audioteka.pl",
    "genres": ["Fantasy"],
    "tags": ["Wiedźmin"],
    "series": [{"series": "Wiedźmin", "sequence": "1"}],
    "language": "pl",
    "duration": 32400,
}


class AudiotekaStandardizationTests(unittest.TestCase):
    def test_full_meta_shape_and_real_publisher_is_used(self):
        from app.main import search_abs_agg_candidates

        payload = {"matches": [AUDIOTEKA_SCHEMA_FIXTURE]}
        with patch("urllib.request.urlopen", fake_urlopen_for(payload)):
            result = search_abs_agg_candidates(
                query="Ostatnie zyczenie", base_url="http://abs-agg:3000",
                provider="audioteka", provider_params="pl",
            )
        meta = result["results"][0]["chosen_metadata"]
        self.assertEqual(meta["title"], "Wiedźmin: Ostatnie życzenie")
        self.assertEqual(meta["author"], "Andrzej Sapkowski")
        # Audioteka genuinely returns a real publisher -- must be used
        # verbatim, never overwritten with "Audioteka" (not a SPECIAL_PROVIDER).
        self.assertEqual(meta["publisher"], "Audioteka.pl")
        self.assertEqual(meta["language"], "pl")
        self.assertEqual(meta["series"], "Wiedźmin")
        self.assertEqual(meta["sequence"], "1")
        self.assertEqual(result["results"][0]["duration_minutes"], 540.0)

    def test_required_lang_param_is_placed_in_the_url_path(self):
        from app.main import search_abs_agg_candidates

        captured = {}

        def _open(req, timeout=15):
            captured["url"] = req.full_url
            return _FakeResp({"matches": []})

        with patch("urllib.request.urlopen", _open):
            search_abs_agg_candidates(
                query="Wiedzmin", base_url="http://abs-agg:3000",
                provider="audioteka", provider_params="pl",
            )
        self.assertIn("/audioteka/pl/search", captured["url"])


if __name__ == "__main__":
    unittest.main()
